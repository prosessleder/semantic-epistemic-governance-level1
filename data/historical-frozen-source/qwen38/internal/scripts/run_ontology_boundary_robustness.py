#!/usr/bin/env python3
"""Freeze and run the independent-family, reasoner-assisted robustness follow-up."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from internal.benchmarks import ontology_boundary_robustness as followup
from internal.benchmarks import ontology_boundary_runner as original
from ontology_boundary import dataset
from ontology_boundary.oracle import Ontology
from ontology_boundary.rdf_adapter import crosscheck_ontology

DEFAULT_RUN = ROOT / "runs/ontology-boundary-robustness-2026-10-12"
BASELINE = ROOT / "runs/ontology-boundary-pilot-2026-10-10"
MISTRAL_REVISION = "c170c708c41dac9275d15a8fff4eca08d52bab71"
MODELS = {
    "qwen3": {"id": "Qwen/Qwen3-4B-Instruct-2507", "revision": "cdbee75f17c01a7cc42f958dc650907174af0554",
        "snapshot": str(Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen3-4B-Instruct-2507/snapshots/cdbee75f17c01a7cc42f958dc650907174af0554")},
    "mistral": {"id": "mistralai/Mistral-7B-Instruct-v0.3", "revision": MISTRAL_REVISION,
        "snapshot": str(ROOT / f"runs/hf-cache-robustness-2026-10-12/models--mistralai--Mistral-7B-Instruct-v0.3/snapshots/{MISTRAL_REVISION}")},
}
NEW_SOURCES = (
    "internal/benchmarks/ontology_boundary_robustness.py",
    "internal/scripts/run_ontology_boundary_robustness.py",
    "internal/scripts/audit_ontology_boundary_robustness.py",
    "tests/test_ontology_boundary_robustness.py",
    "internal/planning/ontology-boundary-robustness-2026-10-12.md",
    "internal/planning/ontology-boundary-robustness-requirements.txt",
    "internal/planning/ontology-boundary-robustness-requirements.lock",
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def emit(event, **values):
    print(original.canonical(dict(event=event, **values)), flush=True)


def sources():
    plan = json.loads((BASELINE / "execution-plan.json").read_text())
    for name, expected in plan["source_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError(f"Original frozen source changed: {name}")
    return {name: digest(ROOT / name) for name in (*plan["source_sha256"], *NEW_SOURCES)}


def artifacts(snapshot):
    snapshot = Path(snapshot)
    files = sorted(p for p in snapshot.iterdir() if p.is_file())
    index = snapshot / "model.safetensors.index.json"
    if index.exists():
        required = set(json.loads(index.read_text())["weight_map"].values())
        if not all((snapshot / name).is_file() for name in required):
            raise ValueError("incomplete pinned checkpoint")
    if not any(p.suffix == ".safetensors" for p in files):
        raise ValueError("checkpoint weights absent")
    return {p.name: {"sha256": digest(p), "bytes": p.stat().st_size} for p in files}


def inventory(tokenizer, data):
    all_cases = {case["base_id"]: case for split in ("dev", "test") for case in data[split]}
    tasks = [job for split in ("dev", "test") for job in followup.jobs(data[split])]
    prefix = followup.select_prefix(tokenizer, tasks, all_cases)
    rows = []
    for job in tasks:
        case = all_cases[job["base_id"]]
        text, ids, labels = followup.encode(tokenizer, followup.packet(case, job), followup.codebook(case, job), prefix)
        rows.append({"job": job, "prompt_sha256": original.sha(text),
            "input_ids_sha256": original.sha(original.canonical(ids)), "input_tokens": len(ids),
            "labels": labels, "codebook": followup.codebook(case, job), "gold": followup.truth(case, job)})
    return {"response_prefix": prefix, "rows": rows, "max_input_tokens": max(r["input_tokens"] for r in rows)}


def prepare(run_dir):
    from transformers import AutoTokenizer
    data = json.loads((BASELINE / "dataset.json").read_text())
    source_sha256 = sources()
    checked = []
    for split in ("dev", "test"):
        for case in data[split]:
            for side in ("old", "new"):
                result = crosscheck_ontology(Ontology.from_dict(case[side]), case["public_classes"])
                if not result["matches"]:
                    raise ValueError("Independent OWL-RL comparison failed")
                checked.append({"base_id": case["base_id"], "side": side, "result": result})
    model_receipts = {}
    for name, config in MODELS.items():
        emit("preflight_model", model=name)
        snapshot = Path(config["snapshot"])
        if snapshot.name != config["revision"]:
            raise ValueError("model revision path mismatch")
        tok = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
        model_receipts[name] = dict(config, artifacts=artifacts(snapshot), tokenizer=inventory(tok, data))
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "dataset.json").write_bytes((BASELINE / "dataset.json").read_bytes())
    write_json(run_dir / "materialization.json", checked)
    write_json(run_dir / "certificates.json", {c["base_id"]: followup.certificate(c) for split in ("dev", "test") for c in data[split]})
    plan = {"declared_at_utc": datetime.now(timezone.utc).isoformat(), "data_sha256": digest(run_dir / "dataset.json"),
        "baseline_plan_sha256": digest(BASELINE / "execution-plan.json"), "sources": source_sha256,
        "materialization_sha256": digest(run_dir / "materialization.json"), "certificates_sha256": digest(run_dir / "certificates.json"),
        "models": model_receipts, "versions": {p: version(p) for p in ("torch", "transformers", "sentencepiece", "protobuf", "rdflib", "owlrl", "pyshacl")},
        "settings": {"device": "mps", "dtype": "bfloat16", "attn_implementation": "eager", "seed": 20261012,
                     "context_limit": 4096, "batch_size": 1, "use_cache": False, "attention_mask": "explicit all ones; unpadded"},
        "post_hoc": True, "fresh_confirmation": False,
        "scope": "Model-family and information-interface robustness on reused finite ontology pairs; no training, activation steering or autonomous release execution.",
        "arms": list(followup.ARMS), "primary_comparison": "verified vs raw, identical request except for the verified finite-profile fact table",
        "legacy_comparison": "Measurement bridge; raw also changes existential wording and binary semantic legend order.",
        "counts_per_model": {"dev": 160, "test": 960, "total": 1120},
        "controls": "224 underlying single-ontology questions per model: derived/effective, two versions, selected/sham profiles; each repeated under both A/B mappings. Report sensitivity, specificity and encoding agreement; labels are imbalanced.",
        "units": "28 reused pairs, 24 TEST pairs in six motifs; approval modes, arms and response encodings are repeated observations.",
        "no_selection": "All cells run irrespective of DEV outcomes; no prompt, dose, model or parameter selection from responses.",
        "interpretation": "Reasoner facts change supplied information; improved review would not establish better unaided deduction or a novel formal checker. Separate model-semantic plus exact-approval baseline is secondary."}
    write_json(run_dir / "execution-plan.json", plan)
    emit("prepared", plan_sha256=digest(run_dir / "execution-plan.json"), counts=plan["counts_per_model"],
         max_tokens={m: v["tokenizer"]["max_input_tokens"] for m, v in model_receipts.items()})


def execute(run_dir, name):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    plan = json.loads((run_dir / "execution-plan.json").read_text())
    if sources() != plan["sources"] or digest(run_dir / "dataset.json") != plan["data_sha256"]:
        raise ValueError("frozen sources/data changed")
    for filename, key in (("materialization.json", "materialization_sha256"), ("certificates.json", "certificates_sha256")):
        if digest(run_dir / filename) != plan[key]:
            raise ValueError("frozen reasoner facts changed")
    config = plan["models"][name]
    if artifacts(config["snapshot"]) != config["artifacts"]:
        raise ValueError("checkpoint artifacts changed")
    data = json.loads((run_dir / "dataset.json").read_text())
    tok = AutoTokenizer.from_pretrained(config["snapshot"], local_files_only=True, trust_remote_code=False)
    if inventory(tok, data) != config["tokenizer"]:
        raise ValueError("tokenized inputs changed")
    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS unavailable; no silent fallback")
    out = run_dir / name
    out.mkdir(exist_ok=False)
    started = time.monotonic()
    torch.manual_seed(plan["settings"]["seed"])
    emit("loading", model=name, id=config["id"], revision=config["revision"])
    model = AutoModelForCausalLM.from_pretrained(config["snapshot"], local_files_only=True, trust_remote_code=False,
        dtype=torch.bfloat16, attn_implementation="eager").to("mps").eval()
    model.requires_grad_(False)
    emit("loaded", model=name, seconds=round(time.monotonic() - started, 2))
    cases = {c["base_id"]: c for split in ("dev", "test") for c in data[split]}
    receipts = {r["job"]["job_id"]: r for r in config["tokenizer"]["rows"]}
    for split in ("dev", "test"):
        rows = []
        with (out / f"{split}-records.jsonl").open("x") as handle, torch.inference_mode():
            tasks = followup.jobs(data[split])
            for i, job in enumerate(tasks, 1):
                case = cases[job["base_id"]]
                text, ids, labels = followup.encode(tok, followup.packet(case, job), followup.codebook(case, job), config["tokenizer"]["response_prefix"])
                expected = receipts[job["job_id"]]
                if original.sha(text) != expected["prompt_sha256"] or original.sha(original.canonical(ids)) != expected["input_ids_sha256"]:
                    raise ValueError("runtime prompt changed")
                t0 = time.monotonic()
                inputs = torch.tensor([ids], device="mps", dtype=torch.long)
                output = model(input_ids=inputs, attention_mask=torch.ones_like(inputs), use_cache=False, logits_to_keep=1)
                logits = output.logits[0, -1].float().cpu()
                logps = torch.log_softmax(logits.double(), dim=0)
                scores = {code: float(logps[token]) for code, token in labels.items()}
                chosen = max(labels, key=scores.get)
                book = followup.codebook(case, job)
                prediction, gold = book[chosen], followup.truth(case, job)
                key = "/".join(str(job.get(k, "")) for k in ("base_id", "task", "mode", "side", "role", "query"))
                record = dict(job, job_key=key, prompt_sha256=original.sha(text), input_ids_sha256=original.sha(original.canonical(ids)),
                    input_tokens=len(ids), labels=labels, codebook=book, response_prefix=config["tokenizer"]["response_prefix"],
                    code_logprobs=scores, response_code=chosen, prediction=prediction, gold=gold, gold_code=next(c for c, v in book.items() if v == gold),
                    correct=prediction == gold, seconds=time.monotonic() - t0,
                    full_logits_sha256=hashlib.sha256(logits.numpy().tobytes()).hexdigest(),
                    unconstrained_top_token_id=int(torch.argmax(logits)),
                    allowed_probability_mass=sum(float(torch.exp(logps[t])) for t in labels.values()))
                if job["task"] == "joint":
                    record["exact_approval"] = dataset.approval_matches(case, dataset.release_approval(case, job["mode"]))
                handle.write(original.canonical(record) + "\n")
                handle.flush()
                rows.append(record)
                del output, inputs, logits, logps
                if i == 1 or i % 20 == 0 or i == len(tasks):
                    emit("progress", model=name, split=split, completed=i, total=len(tasks), seconds=round(time.monotonic() - started, 2))
        write_json(out / f"{split}-summary.json", followup.summarize(rows))
    write_json(out / "completion.json", {"completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": time.monotonic() - started, "plan_sha256": digest(run_dir / "execution-plan.json"),
        "raw_sha256": {split: digest(out / f"{split}-records.jsonl") for split in ("dev", "test")},
        "post_hoc": True, "fresh_confirmation": False})
    emit("complete", model=name, seconds=round(time.monotonic() - started, 2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--model", choices=MODELS, default="qwen3")
    args = parser.parse_args()
    prepare(args.run_dir) if args.action == "prepare" else execute(args.run_dir, args.model)


if __name__ == "__main__":
    main()
