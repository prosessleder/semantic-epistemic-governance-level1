#!/usr/bin/env python3
"""Post-hoc native-Boolean diagnostic and semantic-plus-exact-approval pipeline."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from internal.benchmarks import ontology_boundary_robustness as coded
from internal.benchmarks import ontology_boundary_runner as original
from internal.scripts import run_ontology_boundary_robustness as parent
from internal.scripts.audit_ontology_boundary_robustness import independent_certificate, independent_state
from ontology_boundary import dataset

DEFAULT_RUN = ROOT / "runs/ontology-boundary-native-boolean-2026-10-12"
PARENT_RUN = ROOT / "runs/ontology-boundary-robustness-2026-10-12"
SOURCES = ("internal/scripts/run_ontology_boundary_native_boolean.py",
           "tests/test_ontology_boundary_native_boolean.py",
           "internal/planning/ontology-boundary-native-boolean-2026-10-12.md")


def tasks(data):
    result = []
    for split in ("dev", "test"):
        for case in data[split]:
            for arm in ("raw", "verified"):
                result.append({"base_id": case["base_id"], "split": split, "family": case["family"], "task": "semantic", "arm": arm})
            for side in ("old", "new"):
                for role in ("relevant", "sham"):
                    for query in coded.QUERIES:
                        result.append({"base_id": case["base_id"], "split": split, "family": case["family"], "task": "local",
                                       "arm": "control", "side": side, "role": role, "query": query})
    for i, task in enumerate(result):
        task["job_id"] = f"native-{i:04d}"
    return result


def messages(case, job):
    packet = (coded.review_prompt(case, job["arm"], "semantic") if job["task"] == "semantic"
              else coded.local_prompt(case, job["side"], job["role"], job["query"], 0))
    user = packet[1]["content"].split("Code mapping:\n", 1)[0]
    user += 'Return a JSON object with only the key "answer" and a native Boolean value. True means YES to the question; false means NO. Do not explain.'
    return [{"role": "system", "content": 'Evaluate the supplied question. Answer using the native Boolean field "answer", without a letter codebook.'},
            {"role": "user", "content": user}]


def encoded(tokenizer, packet, assistant_prefix, value_prefix):
    text = tokenizer.apply_chat_template(packet, tokenize=False, add_generation_prompt=True) + assistant_prefix + '{"answer":'
    ids = tokenizer.encode(text, add_special_tokens=False)
    if len(ids) > 4096:
        raise ValueError("context overflow; no truncation")
    labels = {}
    for word in ("true", "false"):
        suffix = tokenizer.encode(value_prefix + word, add_special_tokens=False)
        if len(suffix) != 1 or tokenizer.encode(text + value_prefix + word, add_special_tokens=False) != ids + suffix:
            raise ValueError("noncanonical native-Boolean word boundary")
        labels[word] = suffix[0]
    return text, ids, labels


def gold(case, job):
    if job["task"] == "local":
        return independent_state(case[job["side"]], case["profiles"][job["role"]], case["protected_permission"])[job["query"]]
    cert = independent_certificate(case)
    return any(r["new"]["effective"] and not r["old"]["effective"] for r in cert["profiles"])


def summarize(rows, cases):
    result = {"review": {}, "controls": {}, "paired": {}, "pipeline": {}}
    for arm in ("raw", "verified"):
        group = [r for r in rows if r["task"] == "semantic" and r["arm"] == arm]
        result["review"][arm] = {"n": len(group), "correct": sum(r["correct"] for r in group),
            "yes": sum(r["prediction"] for r in group),
            "missed": sum(r["gold"] and not r["prediction"] for r in group),
            "spurious": sum(not r["gold"] and r["prediction"] for r in group)}
        decisions = []
        for row in group:
            case = cases[row["base_id"]]
            for mode in original.MODES:
                approval = dataset.approval_matches(case, dataset.release_approval(case, mode))
                decisions.append((not row["prediction"] or approval, not row["gold"] or approval))
        result["pipeline"][arm] = {"n": len(decisions), "correct": sum(a == b for a, b in decisions),
            "unsafe": sum(a and not b for a, b in decisions), "unnecessary_hold": sum(not a and b for a, b in decisions),
            "unsafe_opportunities": sum(not b for _, b in decisions), "admissible_opportunities": sum(b for _, b in decisions)}
    for query in coded.QUERIES:
        group = [r for r in rows if r["task"] == "local" and r["query"] == query]
        yes = [r for r in group if r["gold"]]
        no = [r for r in group if not r["gold"]]
        sensitivity = sum(r["prediction"] for r in yes) / len(yes)
        specificity = sum(not r["prediction"] for r in no) / len(no)
        result["controls"][query] = {"n": len(group), "correct": sum(r["correct"] for r in group),
            "positive_n": len(yes), "negative_n": len(no), "sensitivity": sensitivity, "specificity": specificity,
            "balanced_accuracy": (sensitivity + specificity) / 2}
    raw = {r["base_id"]: r for r in rows if r["task"] == "semantic" and r["arm"] == "raw"}
    verified = {r["base_id"]: r for r in rows if r["task"] == "semantic" and r["arm"] == "verified"}
    result["paired"] = {"n": len(raw), "rescues": sum(not raw[k]["correct"] and verified[k]["correct"] for k in raw),
        "harms": sum(raw[k]["correct"] and not verified[k]["correct"] for k in raw)}
    return result


def prepare(run_dir):
    from transformers import AutoTokenizer
    main = json.loads((PARENT_RUN / "execution-plan.json").read_text())
    data = json.loads((PARENT_RUN / "dataset.json").read_text())
    cases = {c["base_id"]: c for split in ("dev", "test") for c in data[split]}
    jobs = tasks(data)
    models = {}
    for name, config in main["models"].items():
        tok = AutoTokenizer.from_pretrained(config["snapshot"], local_files_only=True, trust_remote_code=False)
        assistant_prefix = config["tokenizer"]["response_prefix"]
        value_prefix = None
        for candidate in (" ", ""):
            try:
                for job in jobs:
                    encoded(tok, messages(cases[job["base_id"]], job), assistant_prefix, candidate)
                value_prefix = candidate
                break
            except ValueError:
                pass
        if value_prefix is None:
            raise ValueError("no canonical single-token Boolean values")
        inventory = []
        for job in jobs:
            text, ids, labels = encoded(tok, messages(cases[job["base_id"]], job), assistant_prefix, value_prefix)
            inventory.append({"job": job, "prompt_sha256": original.sha(text), "input_ids_sha256": original.sha(original.canonical(ids)),
                "input_tokens": len(ids), "labels": labels, "gold": gold(cases[job["base_id"]], job)})
        models[name] = {k: config[k] for k in ("id", "revision", "snapshot", "artifacts")}
        models[name].update(assistant_prefix=assistant_prefix, value_prefix=value_prefix, inventory=inventory)
    source_hashes = dict(main["sources"])
    source_hashes.update({p: parent.digest(ROOT / p) for p in SOURCES})
    run_dir.mkdir(exist_ok=False)
    (run_dir / "dataset.json").write_bytes((PARENT_RUN / "dataset.json").read_bytes())
    plan = {"declared_at_utc": datetime.now(timezone.utc).isoformat(), "parent_plan_sha256": parent.digest(PARENT_RUN / "execution-plan.json"),
        "data_sha256": parent.digest(run_dir / "dataset.json"), "sources": source_hashes, "models": models,
        "versions": main["versions"], "settings": main["settings"], "post_hoc": True, "fresh_confirmation": False,
        "motivation": "Mistral DEV code-reversal inconsistency observed while coded TEST runs were still in progress; no native-Boolean outputs observed before freeze.",
        "counts_per_model": {"dev": 40, "test": 240, "total": 280},
        "endpoint": "Teacher-forced partial JSON prefix; two complete native Boolean word likelihoods, not free generation or JSON-format compliance.",
        "comparison": "Native vs coded changes instructions, lexical values and assistant prefill together; cannot isolate a causal codebook mechanism. Native raw vs verified differs only by finite reasoner facts.",
        "pipeline": "Native semantic judgment plus exact simulated approval validator; no model approval judgment or actual activation.",
        "selection": "All fixed cells and reused cases reported; no chosen replacement primary endpoint."}
    parent.write_json(run_dir / "execution-plan.json", plan)
    parent.emit("native_prepared", plan_sha256=parent.digest(run_dir / "execution-plan.json"), count=len(jobs),
        max_tokens={name: max(r["input_tokens"] for r in c["inventory"]) for name, c in models.items()})


def validate(run_dir):
    plan = json.loads((run_dir / "execution-plan.json").read_text())
    for name, digest in plan["sources"].items():
        if parent.digest(ROOT / name) != digest:
            raise ValueError("source changed after native freeze")
    if parent.digest(run_dir / "dataset.json") != plan["data_sha256"]:
        raise ValueError("data changed after native freeze")
    return plan


def execute(run_dir, name):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    plan = validate(run_dir)
    config = plan["models"][name]
    if parent.artifacts(config["snapshot"]) != config["artifacts"]:
        raise ValueError("checkpoint changed")
    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS unavailable")
    data = json.loads((run_dir / "dataset.json").read_text())
    cases = {c["base_id"]: c for split in ("dev", "test") for c in data[split]}
    tok = AutoTokenizer.from_pretrained(config["snapshot"], local_files_only=True, trust_remote_code=False)
    out = run_dir / name
    out.mkdir(exist_ok=False)
    started = time.monotonic()
    torch.manual_seed(plan["settings"]["seed"])
    model = AutoModelForCausalLM.from_pretrained(config["snapshot"], local_files_only=True, trust_remote_code=False,
        dtype=torch.bfloat16, attn_implementation="eager").to("mps").eval()
    model.requires_grad_(False)
    for split in ("dev", "test"):
        rows = []
        entries = [r for r in config["inventory"] if r["job"]["split"] == split]
        with (out / f"{split}-records.jsonl").open("x") as handle, torch.inference_mode():
            for i, receipt in enumerate(entries, 1):
                job = receipt["job"]
                text, ids, labels = encoded(tok, messages(cases[job["base_id"]], job), config["assistant_prefix"], config["value_prefix"])
                assert original.sha(text) == receipt["prompt_sha256"] and original.sha(original.canonical(ids)) == receipt["input_ids_sha256"]
                t0 = time.monotonic()
                inputs = torch.tensor([ids], dtype=torch.long, device="mps")
                output = model(input_ids=inputs, attention_mask=torch.ones_like(inputs), use_cache=False, logits_to_keep=1)
                logits = output.logits[0, -1].float().cpu()
                logps = torch.log_softmax(logits.double(), dim=0)
                scores = {word: float(logps[token]) for word, token in labels.items()}
                prediction = scores["true"] >= scores["false"]
                truth = receipt["gold"]
                row = dict(job, prediction=prediction, gold=truth, correct=prediction == truth, labels=labels, word_logprobs=scores,
                    prompt_sha256=receipt["prompt_sha256"], input_ids_sha256=receipt["input_ids_sha256"], input_tokens=len(ids),
                    full_logits_sha256=hashlib.sha256(logits.numpy().tobytes()).hexdigest(),
                    unconstrained_top_token_id=int(torch.argmax(logits)), allowed_probability_mass=sum(float(torch.exp(logps[t])) for t in labels.values()),
                    seconds=time.monotonic() - t0)
                handle.write(original.canonical(row) + "\n")
                handle.flush()
                rows.append(row)
                del output, inputs, logits, logps
                if i == 1 or i % 20 == 0 or i == len(entries):
                    parent.emit("native_progress", model=name, split=split, completed=i, total=len(entries), seconds=round(time.monotonic() - started, 2))
        parent.write_json(out / f"{split}-summary.json", summarize(rows, cases))
    parent.write_json(out / "completion.json", {"elapsed_seconds": time.monotonic() - started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(), "plan_sha256": parent.digest(run_dir / "execution-plan.json"),
        "raw_sha256": {split: parent.digest(out / f"{split}-records.jsonl") for split in ("dev", "test")}})
    parent.emit("native_complete", model=name, seconds=round(time.monotonic() - started, 2))


def audit(run_dir, preflight):
    from transformers import AutoTokenizer
    plan = validate(run_dir)
    data = json.loads((run_dir / "dataset.json").read_text())
    cases = {c["base_id"]: c for split in ("dev", "test") for c in data[split]}
    expected_jobs = tasks(data)
    result = {"status": "PASS", "preflight_only": preflight, "plan_sha256": parent.digest(run_dir / "execution-plan.json"),
        "post_hoc": True, "fresh_confirmation": False, "models": {},
        "limits": "No GPU replay/attestation. Independent closure is reused from the separate CPU audit; summaries are separately recounted for primary counts. Native words are scored after forced prefix, not freely generated."}
    for name, config in plan["models"].items():
        assert [r["job"] for r in config["inventory"]] == expected_jobs
        tok = AutoTokenizer.from_pretrained(config["snapshot"], local_files_only=True, trust_remote_code=False)
        raw = {}
        if not preflight:
            complete = json.loads((run_dir / name / "completion.json").read_text())
            assert complete["plan_sha256"] == result["plan_sha256"]
            for split in ("dev", "test"):
                path = run_dir / name / f"{split}-records.jsonl"
                assert parent.digest(path) == complete["raw_sha256"][split]
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                assert len(rows) == plan["counts_per_model"][split]
                assert len({r["job_id"] for r in rows}) == len(rows)
                supplied = json.loads((run_dir / name / f"{split}-summary.json").read_text())
                assert summarize(rows, cases) == supplied
                # Explicit independent aggregate recounts in addition to whole-summary replay.
                for arm in ("raw", "verified"):
                    group = [r for r in rows if r["task"] == "semantic" and r["arm"] == arm]
                    assert supplied["review"][arm]["correct"] == sum(r["prediction"] == gold(cases[r["base_id"]], r) for r in group)
                    decisions = []
                    for r in group:
                        true_expansion = gold(cases[r["base_id"]], r)
                        for mode in original.MODES:
                            trusted = mode == "valid"
                            decisions.append((not r["prediction"] or trusted, not true_expansion or trusted))
                    assert supplied["pipeline"][arm]["correct"] == sum(a == b for a, b in decisions)
                    assert supplied["pipeline"][arm]["unsafe"] == sum(a and not b for a, b in decisions)
                    assert supplied["pipeline"][arm]["unnecessary_hold"] == sum(not a and b for a, b in decisions)
                raw.update({r["job_id"]: r for r in rows})
        for receipt in config["inventory"]:
            job = receipt["job"]
            packet = messages(cases[job["base_id"]], job)
            assert all("Code mapping:" not in m["content"] for m in packet)
            text, ids, labels = encoded(tok, packet, config["assistant_prefix"], config["value_prefix"])
            assert original.sha(text) == receipt["prompt_sha256"] and original.sha(original.canonical(ids)) == receipt["input_ids_sha256"]
            assert labels == receipt["labels"] and len(ids) == receipt["input_tokens"]
            assert gold(cases[job["base_id"]], job) == receipt["gold"]
            if not preflight:
                r = raw[job["job_id"]]
                assert all(r[k] == v for k, v in job.items())
                assert r["labels"] == labels and r["gold"] == receipt["gold"]
                assert r["prompt_sha256"] == receipt["prompt_sha256"] and r["input_ids_sha256"] == receipt["input_ids_sha256"]
                assert r["input_tokens"] == len(ids)
                assert r["prediction"] == (r["word_logprobs"]["true"] >= r["word_logprobs"]["false"])
                assert r["correct"] == (r["prediction"] == r["gold"])
        result["models"][name] = {"packets": len(config["inventory"]), "records": len(raw)}
    path = run_dir / ("preflight-audit.json" if preflight else "postflight-audit.json")
    parent.write_json(path, result)
    parent.emit("native_audit", status="PASS", receipt=str(path), packets=560, records=sum(c["records"] for c in result["models"].values()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "audit"))
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--model", choices=parent.MODELS, default="mistral")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare": prepare(args.run_dir)
    elif args.action == "run": execute(args.run_dir, args.model)
    else: audit(args.run_dir, args.preflight)
