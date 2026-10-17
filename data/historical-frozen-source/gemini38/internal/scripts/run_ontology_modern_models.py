#!/usr/bin/env python3
"""Pinned local replication; leave all historical runners and sources unchanged."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from internal.benchmarks import ontology_checked_proposals as fixtures
from internal.benchmarks import ontology_reasoning_diagnostics as diagnostics
from internal.scripts import run_ontology_checked_proposals as previous
from internal.scripts.audit_ontology_checked_proposals import (
    reference_candidate, reference_review, sha, validate_sources,
)
from ontology_boundary.checked_release import ReviewContract, first_proposal_object
from ontology_boundary.proposal_commit import commit_frame
from ontology_boundary.rdf_adapter import crosscheck_ontology

RUN = ROOT / "runs/ontology-modern-models-2026-10-12"
PRIOR = ROOT / "runs/ontology-checked-proposals-2026-10-12/execution-plan.json"
NEW_SOURCES = (
    "internal/scripts/run_ontology_modern_models.py",
    "internal/planning/ontology-modern-models-2026-10-12.md",
    "tests/test_ontology_modern_models.py",
    "src/ontology_boundary/proposal_commit.py",
    "internal/planning/ontology-modern-models-requirements.lock",
)
MODEL_SPECS = {
    "qwen35": ("Qwen/Qwen3.5-4B", "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"),
    "gemma4": ("google/gemma-4-E4B-it", "ee0ef6023621cff504d758262d4e04895a5af4a2"),
}
MODEL_WEIGHTS = {
    "qwen35": {
        "model.safetensors-00001-of-00002.safetensors": {
            "bytes": 5329398688, "sha256": "26a93f066e1916adb13453dae5a0c707c0fbc71299ed98779571a907b8e74c61"},
        "model.safetensors-00002-of-00002.safetensors": {
            "bytes": 3990429408, "sha256": "cb544bd9bfae93dc59b0f22b292f5933573854a7f9b97835c67060d7d910e188"},
    },
    "gemma4": {"model.safetensors": {
        "bytes": 15992595884, "sha256": "cfbd3d2f1cd71bd471c37fe2bf8546d5028d41e5736f64e1ca6c6b8893125503"}},
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest_value(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def checkpoint_artifacts(snapshot):
    """Stream multi-GB files; avoid allocating an entire shard just to hash it."""
    snapshot = Path(snapshot)
    index = snapshot / "model.safetensors.index.json"
    if index.exists():
        required = set(json.loads(index.read_text())["weight_map"].values())
        if not all((snapshot / name).is_file() for name in required):
            raise ValueError("incomplete pinned checkpoint")
    files = sorted(p for p in snapshot.iterdir() if p.is_file())
    if not any(p.suffix == ".safetensors" for p in files):
        raise ValueError("checkpoint weights absent")
    result = {}
    for p in files:
        with p.open("rb") as handle:
            result[p.name] = dict(sha256=hashlib.file_digest(handle, "sha256").hexdigest(), bytes=p.stat().st_size)
    return result


def write(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


def emit(event, **values):
    print(canonical(dict(event=event, **values)), flush=True)


def versions():
    return {p: metadata.version(p) for p in (
        "torch", "transformers", "tokenizers", "huggingface-hub", "safetensors",
        "accelerate", "rdflib", "owlrl", "pyshacl",
    )}


def fetch(run):
    from concurrent.futures import ThreadPoolExecutor
    from huggingface_hub import snapshot_download
    run.mkdir(parents=True, exist_ok=True)
    def one(item):
        name, (mid, revision) = item
        t0 = time.monotonic()
        snapshot = snapshot_download(mid, revision=revision, cache_dir=str(run / "hf-cache"),
            allow_patterns=["*.json", "*.safetensors", "*.md", "*.jinja", "*.txt", "*.model"], max_workers=4)
        write(run / (name + "-snapshot.json"), dict(id=mid, revision=revision,
              snapshot=str(Path(snapshot).resolve()), download_seconds=time.monotonic() - t0))
        emit("modern_download_complete", model=name)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one, MODEL_SPECS.items()))


def jobs(tasks):
    result = []
    for arm in ("direct", "reasoned"):
        result.extend(dict(job_id=f"{arm}/{t['task_id']}", arm=arm, kind="proposal", task=t) for t in tasks)
    for context in diagnostics.microcases():
        context = diagnostics.renamed(context, "short")
        for query in ("derived", "effective"):
            result.append(dict(job_id=f"control/{context['context_id']}/{query}", arm="direct",
                               kind="control", context=context, query=query,
                               expected=diagnostics.gold(context)[query]))
    return result


def encode(tok, job):
    messages = (fixtures.messages(job["task"]) if job["kind"] == "proposal"
                else diagnostics.direct_messages(job["context"], job["query"]))
    if job["arm"] == "reasoned":
        messages[-1]["content"] = messages[-1]["content"].replace(
            "Return one proposal JSON object only, without prose or extra fields.",
            "You may reason in your native thinking channel. In the final response return one "
            "proposal JSON object only, without prose or extra fields.")
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                  enable_thinking=job["arm"] == "reasoned")
    if job["arm"] == "direct":
        text += '{"op":' if job["kind"] == "proposal" else '{"answer":'
    ids = tok.encode(text, add_special_tokens=False)
    if len(ids) > 4096:
        raise ValueError("context overflow; truncation is forbidden")
    # Published template tokenization and our text tokenization must agree.
    native = tok.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                     enable_thinking=job["arm"] == "reasoned", return_dict=False)
    if job["arm"] == "reasoned" and ids != native:
        raise ValueError("template token mismatch")
    if job["arm"] == "direct":
        prefill = '{"op":' if job["kind"] == "proposal" else '{"answer":'
        continued = tok.apply_chat_template(messages + [{"role": "assistant", "content": prefill}],
            tokenize=True, continue_final_message=True, enable_thinking=False, return_dict=False)
        if ids != continued:
            raise ValueError("partial assistant object does not match the native continuation boundary")
    return text, ids


def final_frame(name, arm, raw, kind="proposal"):
    """Transport framing only; never extract an object from arbitrary prose."""
    if arm == "direct":
        return ('{"op":' if kind == "proposal" else '{"answer":') + raw
    if name == "qwen35":
        if raw.count("</think>") != 1:
            raise ValueError("missing or ambiguous native thinking boundary")
        raw = raw.split("</think>", 1)[1]
    elif name == "gemma4":
        raw = raw.lstrip()
        if raw.startswith("<|channel>thought\n"):
            if raw.count("<channel|>") != 1:
                raise ValueError("incomplete or ambiguous native thought channel")
            raw = raw.split("<channel|>", 1)[1]
    else:
        raise ValueError("unknown model framing")
    raw = raw.lstrip()
    if not raw.startswith("{"):
        raise ValueError("final channel does not start with a JSON object")
    return raw


def strip_terminal_ids(ids, terminal_ids):
    ids = list(ids)
    while ids and ids[-1] in terminal_ids:
        ids.pop()
    return ids


def prepare(run):
    from transformers import AutoTokenizer
    old = json.loads(PRIOR.read_text())
    validate_sources(old)
    tasks = fixtures.tasks()
    assert tasks == old["tasks"] and len(tasks) == 32
    plan = dict(declared_at_utc=datetime.now(timezone.utc).isoformat(), exploratory=True,
                reused_tasks=True, prior_plan_sha256=sha(PRIOR), tasks=tasks, jobs=jobs(tasks),
                authority_modes=list(fixtures.MODES), dependency_versions=versions(), models={},
                settings=dict(seed=20261012, device="mps", dtype="bfloat16", attention="eager",
                              batch_size=1, do_sample=False, use_cache=True, max_input_tokens=4096,
                              direct_max_new_tokens=96, reasoned_max_new_tokens=2048),
                sources=dict(old["sources"], **{p: sha(ROOT/p) for p in NEW_SOURCES}))
    reference = []
    for task in tasks:
        contract = ReviewContract.from_dict(task["contract"])
        candidate = reference_candidate(contract, task["reference_patch"])
        assert candidate.to_dict() == task["reference_candidate"]
        _, reviews = previous.evaluate(contract, task["reference_patch"])
        for mode in fixtures.MODES:
            assert reviews[mode]["goal_satisfied"]
        reference.append(dict(task_id=task["task_id"], owl=crosscheck_ontology(candidate, contract.public_classes)))
        assert reference[-1]["owl"]["matches"]
    for name in ("qwen35", "gemma4"):
        receipt = run / (name + "-snapshot.json")
        if receipt.exists():
            cfg = json.loads(receipt.read_text())
        else:
            mid, revision = MODEL_SPECS[name]
            cfg = dict(id=mid, revision=revision, download_pending_at_freeze=True,
                       snapshot=str(run / "hf-cache" / ("models--" + mid.replace("/", "--")) / "snapshots" / revision))
        assert (cfg["id"], cfg["revision"]) == MODEL_SPECS[name]
        # Immutable HF LFS SHA256/size records let inputs freeze while another
        # checkpoint downloads. Every actual file is hashed again before load.
        snapshot = Path(cfg["snapshot"])
        cfg["artifacts"] = {p.name: dict(sha256=sha(p), bytes=p.stat().st_size)
            for p in sorted(snapshot.iterdir()) if p.is_file() and p.suffix != ".safetensors"}
        cfg["artifacts"].update(MODEL_WEIGHTS[name])
        tok = AutoTokenizer.from_pretrained(cfg["snapshot"], local_files_only=True, trust_remote_code=False)
        cfg["inventory"] = []
        for job in plan["jobs"]:
            text, ids = encode(tok, job)
            cfg["inventory"].append(dict(job_id=job["job_id"], prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),
                                         input_ids_sha256=digest_value(ids), input_tokens=len(ids)))
        plan["models"][name] = cfg
    write(run / "reference-preflight.json", reference)
    write(run / "execution-plan.json", plan)
    emit("modern_study_frozen", plan_sha256=sha(run / "execution-plan.json"), requests=len(plan["jobs"]) * 2,
         dependency_versions=plan["dependency_versions"])


def load(cfg):
    import torch
    import transformers
    from transformers import AutoTokenizer
    assert checkpoint_artifacts(cfg["snapshot"]) == cfg["artifacts"], "checkpoint files differ from the pinned plan"
    tok = AutoTokenizer.from_pretrained(cfg["snapshot"], local_files_only=True, trust_remote_code=False)
    cls = getattr(transformers, "AutoModelForMultimodalLM", None)
    if cls is None:
        cls = transformers.AutoModelForImageTextToText
    model = cls.from_pretrained(cfg["snapshot"], local_files_only=True, trust_remote_code=False,
                               dtype=torch.bfloat16, attn_implementation="eager").to("mps").eval()
    assert all(p.device.type == "mps" for p in model.parameters()), "model parameters are not all on MPS"
    model.requires_grad_(False)
    emit("modern_model_loaded", parameters=sum(p.numel() for p in model.parameters()),
         mps_allocated_bytes=torch.mps.current_allocated_memory(), mps_driver_bytes=torch.mps.driver_allocated_memory())
    return tok, model


def generate(tok, model, name, job, ids, cap):
    import torch
    from transformers import StoppingCriteria, StoppingCriteriaList
    eos = model.generation_config.eos_token_id
    terminal = set(eos if isinstance(eos, list) else [eos])
    terminal.add(tok.pad_token_id)

    class Complete(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs):
            tokens = input_ids[0, len(ids):].tolist()
            raw = tok.decode(strip_terminal_ids(tokens, terminal), skip_special_tokens=False)
            try:
                frame = final_frame(name, job["arm"], raw, job["kind"])
                json.JSONDecoder().raw_decode(frame)
                return True
            except ValueError:
                return False

    t0 = time.monotonic()
    inputs = torch.tensor([ids], dtype=torch.long, device="mps")
    with torch.inference_mode():
        output = model.generate(input_ids=inputs, attention_mask=torch.ones_like(inputs),
                                do_sample=False, use_cache=True, max_new_tokens=cap,
                                pad_token_id=tok.eos_token_id if tok.pad_token_id is None else tok.pad_token_id,
                                stopping_criteria=StoppingCriteriaList([Complete()]))
    tokens = output[0, len(ids):].cpu().tolist()
    raw = tok.decode(strip_terminal_ids(tokens, terminal), skip_special_tokens=False)
    del output, inputs
    frame = None
    try:
        frame = final_frame(name, job["arm"], raw, job["kind"])
        obj, trailing = first_proposal_object(frame)
        error = None
    except ValueError as exc:
        obj, trailing, error = None, None, str(exc)
    return dict(raw_response=raw, complete_frame=frame, proposal=obj, trailing_text=trailing,
                parse_error=error, generated_token_ids=tokens, output_tokens=len(tokens),
                terminal_token_ids=sorted(t for t in terminal if t is not None),
                hit_cap=len(tokens) == cap, seconds=time.monotonic() - t0)


def smoke(run, name):
    import torch
    plan = json.loads((run / "execution-plan.json").read_text())
    validate_sources(plan)
    assert versions() == plan["dependency_versions"]
    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS unavailable")
    tok, model = load(plan["models"][name])
    rows = []
    for arm in ("direct", "reasoned"):
        messages = [{"role": "user", "content": 'Return a JSON object with exactly "color":"blue".'}]
        text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                      enable_thinking=arm == "reasoned")
        # A proposal-key prefill is unnecessary in this transport-only smoke.
        if arm == "direct":
            text += '{"op":'
            messages[0]["content"] = 'Return a JSON object with exactly "op":"blue".'
            text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                          enable_thinking=False) + '{"op":'
        ids = tok.encode(text, add_special_tokens=False)
        row = generate(tok, model, name, dict(arm=arm, kind="proposal"), ids, 256)
        row.update(arm=arm, input_ids_sha256=digest_value(ids), input_tokens=len(ids))
        rows.append(row)
    receipt = dict(model=name, scope="non-benchmark transport check", records=rows,
                   mps_allocated_bytes=torch.mps.current_allocated_memory(),
                   mps_driver_bytes=torch.mps.driver_allocated_memory())
    write(run / (name + "-smoke.json"), receipt)
    emit("modern_smoke_complete", model=name, records=[dict(arm=r["arm"], proposal=r["proposal"],
         parse_error=r["parse_error"], seconds=round(r["seconds"], 2)) for r in rows])


def execute(run, name):
    import torch
    plan = json.loads((run / "execution-plan.json").read_text())
    validate_sources(plan)
    assert versions() == plan["dependency_versions"]
    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS unavailable")
    smoke_receipt = json.loads((run / (name + "-smoke.json")).read_text())
    assert [r["arm"] for r in smoke_receipt["records"]] == ["direct", "reasoned"]
    assert all(r["output_tokens"] > 0 for r in smoke_receipt["records"]), "no local model output was produced"
    # A completed GPU generation establishes executability. Do not select or
    # exclude models by the correctness/verbosity of a non-benchmark smoke.
    out = run / name
    out.mkdir(exist_ok=False)
    t0 = time.monotonic()
    torch.manual_seed(plan["settings"]["seed"])
    tok, model = load(plan["models"][name])
    rows = []
    with (out / "records.jsonl").open("x") as handle:
        for job, packet in zip(plan["jobs"], plan["models"][name]["inventory"]):
            text, ids = encode(tok, job)
            assert hashlib.sha256(text.encode()).hexdigest() == packet["prompt_sha256"]
            assert digest_value(ids) == packet["input_ids_sha256"]
            cap = 96 if job["arm"] == "direct" else 2048
            row = dict(packet, arm=job["arm"], kind=job["kind"], **generate(tok, model, name, job, ids, cap))
            if job["kind"] == "proposal":
                contract = ReviewContract.from_dict(job["task"]["contract"])
                candidate, reviews = previous.evaluate(contract, row["proposal"])
                row.update(task_id=job["task"]["task_id"], family=job["task"]["family"], reviews=reviews,
                           valid_proposal=candidate is not None, candidate=None if candidate is None else candidate.to_dict())
            else:
                obj = row["proposal"]
                valid = type(obj) is dict and set(obj) == {"answer"} and type(obj["answer"]) is bool
                row.update(context_id=job["context"]["context_id"], query=job["query"], expected=job["expected"],
                           valid_answer=valid, answer=obj["answer"] if valid else None,
                           correct=valid and obj["answer"] == job["expected"])
            handle.write(canonical(row) + "\n")
            handle.flush()
            rows.append(row)
            if len(rows) == 1 or len(rows) % 4 == 0:
                emit("modern_progress", model=name, completed=len(rows), total=len(plan["jobs"]),
                     arm=job["arm"], seconds=round(time.monotonic() - t0, 2))
    result = {}
    for arm in ("direct", "reasoned"):
        sub = [r for r in rows if r["kind"] == "proposal" and r["arm"] == arm]
        result[arm] = dict(previous.summarize(sub), token_caps=sum(r["hit_cap"] for r in sub),
                           generation_seconds=sum(r["seconds"] for r in sub))
    controls = [r for r in rows if r["kind"] == "control"]
    result["controls"] = {q: control_summary([r for r in controls if r["query"] == q]) for q in ("derived", "effective")}
    write(out / "summary.json", result)
    write(out / "completion.json", dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),
          elapsed_seconds=time.monotonic() - t0, plan_sha256=sha(run / "execution-plan.json"),
          records_sha256=sha(out / "records.jsonl"), mps_driver_bytes=torch.mps.driver_allocated_memory()))
    emit("modern_complete", model=name, seconds=round(time.monotonic() - t0, 2), summary=result)


def control_summary(rows):
    pos, neg = [r for r in rows if r["expected"]], [r for r in rows if not r["expected"]]
    sensitivity = sum(r["correct"] for r in pos) / len(pos)
    specificity = sum(r["correct"] for r in neg) / len(neg)
    return dict(n=len(rows), valid=sum(r["valid_answer"] for r in rows), correct=sum(r["correct"] for r in rows),
                sensitivity=sensitivity, specificity=specificity, balanced_accuracy=(sensitivity + specificity) / 2)


def audit(run):
    from transformers import AutoTokenizer
    plan = json.loads((run / "execution-plan.json").read_text())
    validate_sources(plan)
    result = dict(status="PASS", plan_sha256=sha(run / "execution-plan.json"), models={},
                  limits="Independent edit/closure/goals/authority recount; shared datatypes, framing and tokenization. No independent GPU replication or real release.")
    for name, cfg in plan["models"].items():
        tok = AutoTokenizer.from_pretrained(cfg["snapshot"], local_files_only=True, trust_remote_code=False)
        out = run / name
        completion = json.loads((out / "completion.json").read_text())
        assert completion["plan_sha256"] == result["plan_sha256"]
        assert completion["records_sha256"] == sha(out / "records.jsonl")
        rows = [json.loads(l) for l in (out / "records.jsonl").read_text().splitlines()]
        assert len(rows) == len(plan["jobs"]) and [r["job_id"] for r in rows] == [j["job_id"] for j in plan["jobs"]]
        candidates = commits = 0
        for job, row in zip(plan["jobs"], rows):
            text, ids = encode(tok, job)
            assert row["prompt_sha256"] == hashlib.sha256(text.encode()).hexdigest()
            assert row["input_ids_sha256"] == digest_value(ids)
            assert row["raw_response"] == tok.decode(strip_terminal_ids(
                row["generated_token_ids"], set(row["terminal_token_ids"])), skip_special_tokens=False)
            try:
                frame = final_frame(name, job["arm"], row["raw_response"], job["kind"])
                obj, trailing = first_proposal_object(frame)
            except ValueError:
                obj, trailing = None, None
            assert obj == row["proposal"] and trailing == row["trailing_text"]
            if job["kind"] == "control":
                assert row["expected"] == diagnostics.gold(job["context"])[job["query"]]
                valid = type(obj) is dict and set(obj) == {"answer"} and type(obj["answer"]) is bool
                assert row["valid_answer"] == valid
                assert row["correct"] == (valid and obj["answer"] == row["expected"])
                continue
            contract = ReviewContract.from_dict(job["task"]["contract"])
            try:
                candidate = reference_candidate(contract, row["proposal"])
            except (ValueError, TypeError):
                candidate = None
            assert row["valid_proposal"] == (candidate is not None)
            if candidate is not None:
                assert candidate.to_dict() == row["candidate"]
                assert crosscheck_ontology(candidate, contract.public_classes)["matches"]
                candidates += 1
                for mode in fixtures.MODES:
                    registry = fixtures.registry(contract, candidate, mode)
                    expected = reference_review(contract, candidate, registry)
                    assert all(row["reviews"][mode][k] == expected[k] for k in expected)
                    state, receipt = commit_frame(contract.base, contract, row["complete_frame"], registry)
                    assert receipt["admitted"] == expected["admitted"]
                    assert state == (candidate if expected["admitted"] else contract.base)
                    commits += 1
            else:
                assert not any(r["admitted"] for r in row["reviews"].values())
        result["models"][name] = dict(records=len(rows), owl_candidates=candidates, commit_replays=commits)
    write(run / "postflight-audit.json", result)
    emit("modern_audit", **result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fetch", "prepare", "smoke", "run", "audit"))
    parser.add_argument("--model", choices=("qwen35", "gemma4"), default="qwen35")
    parser.add_argument("--run-dir", type=Path, default=RUN)
    args = parser.parse_args()
    if args.action == "fetch": fetch(args.run_dir)
    elif args.action == "prepare": prepare(args.run_dir)
    elif args.action == "smoke": smoke(args.run_dir, args.model)
    elif args.action == "run": execute(args.run_dir, args.model)
    else: audit(args.run_dir)
