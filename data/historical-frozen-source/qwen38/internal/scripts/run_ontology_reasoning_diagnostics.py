#!/usr/bin/env python3
"""Frozen control-failure investigation; does not change original experiments."""
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
from internal.benchmarks import ontology_reasoning_diagnostics as diagnostic
from internal.scripts import run_ontology_boundary_native_boolean as native
from internal.scripts import run_ontology_boundary_robustness as parent

RUN = ROOT / "runs/ontology-reasoning-diagnostics-2026-10-12"
PARENT = ROOT / "runs/ontology-boundary-native-boolean-2026-10-12"
SOURCES = ("internal/benchmarks/ontology_reasoning_diagnostics.py",
    "internal/scripts/run_ontology_reasoning_diagnostics.py", "tests/test_ontology_reasoning_diagnostics.py",
    "internal/planning/ontology-reasoning-diagnostics-2026-10-12.md")


def encode(tok, context, job, cfg):
    if job["endpoint"] == "direct":
        text, ids, labels = native.encoded(tok, diagnostic.direct_messages(context, job["query"]), cfg["assistant_prefix"], cfg["value_prefix"])
        return text, ids, labels
    text = tok.apply_chat_template(diagnostic.trace_messages(context), tokenize=False, add_generation_prompt=True) + cfg["assistant_prefix"] + '{"steps":['
    ids = tok.encode(text, add_special_tokens=False)
    if len(ids) > 4096:
        raise ValueError("input overflow; no truncation")
    return text, ids, {}


def prepare(run):
    from transformers import AutoTokenizer
    old = json.loads((PARENT / "execution-plan.json").read_text())
    for path, expected in old["sources"].items():
        assert parent.digest(ROOT / path) == expected, path
    data = json.loads((PARENT / "dataset.json").read_text())
    contexts = diagnostic.contexts(data)
    assert len(contexts) == 40
    plan = {"declared_at_utc": datetime.now(timezone.utc).isoformat(), "post_hoc": True, "fresh_confirmation": False,
        "parent_plan_sha256": parent.digest(PARENT / "execution-plan.json"),
        "sources": dict(old["sources"], **{p: parent.digest(ROOT / p) for p in SOURCES}),
        "contexts": contexts, "jobs_per_model": 240,
        "settings": {"seed": 20261012, "max_input_tokens": 4096, "max_new_tokens": 160, "batch_size": 1,
            "dtype": "bfloat16", "device": "mps", "attention": "eager", "do_sample": False,
            "direct_cache": False, "trace_cache": True, "trace_prefix": '{"steps":['}, "models": {}}
    for name, previous in old["models"].items():
        cfg = {key: previous[key] for key in ("id", "revision", "snapshot", "assistant_prefix", "value_prefix")}
        cfg["artifacts"] = parent.artifacts(cfg["snapshot"])
        assert cfg["artifacts"] == previous["artifacts"], f"checkpoint changed: {name}"
        tok = AutoTokenizer.from_pretrained(cfg["snapshot"], local_files_only=True, trust_remote_code=False)
        cfg["inventory"] = []
        by_id = {c["context_id"]: c for c in contexts}
        for job in diagnostic.jobs(contexts):
            context = diagnostic.renamed(by_id[job["context_id"]], job["naming"])
            text, ids, labels = encode(tok, context, job, cfg)
            truth = diagnostic.gold(context)
            assert diagnostic.verify_trace(context, diagnostic.oracle_trace(context))["valid"]
            cfg["inventory"].append({"job": job, "prompt_sha256": native.original.sha(text),
                "input_ids_sha256": native.original.sha(native.original.canonical(ids)), "input_tokens": len(ids),
                "labels": labels, "gold": truth})
        plan["models"][name] = cfg
    run.mkdir(parents=True, exist_ok=False)
    parent.write_json(run / "execution-plan.json", plan)
    parent.emit("diagnostic_frozen", plan_sha256=parent.digest(run / "execution-plan.json"), requests=480)


def validate(run):
    plan = json.loads((run / "execution-plan.json").read_text())
    for path, expected in plan["sources"].items():
        assert parent.digest(ROOT / path) == expected, path
    return plan


def execute(run, name):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    plan = validate(run)
    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS unavailable")
    cfg = plan["models"][name]
    tok = AutoTokenizer.from_pretrained(cfg["snapshot"], local_files_only=True, trust_remote_code=False)
    out = run / name
    out.mkdir(exist_ok=False)
    started = time.monotonic()
    torch.manual_seed(plan["settings"]["seed"])
    model = AutoModelForCausalLM.from_pretrained(cfg["snapshot"], local_files_only=True, trust_remote_code=False,
        dtype=torch.bfloat16, attn_implementation="eager").to("mps").eval()
    model.requires_grad_(False)
    by_id = {c["context_id"]: c for c in plan["contexts"]}
    rows = []
    with (out / "records.jsonl").open("x") as handle, torch.inference_mode():
        for i, receipt in enumerate(cfg["inventory"], 1):
            job = receipt["job"]
            context = diagnostic.renamed(by_id[job["context_id"]], job["naming"])
            text, ids, labels = encode(tok, context, job, cfg)
            assert native.original.sha(text) == receipt["prompt_sha256"]
            assert native.original.sha(native.original.canonical(ids)) == receipt["input_ids_sha256"]
            inputs = torch.tensor([ids], dtype=torch.long, device="mps")
            row = dict(job, gold=receipt["gold"], prompt_sha256=receipt["prompt_sha256"],
                input_ids_sha256=receipt["input_ids_sha256"], input_tokens=len(ids))
            t0 = time.monotonic()
            if job["endpoint"] == "direct":
                output = model(input_ids=inputs, attention_mask=torch.ones_like(inputs), use_cache=False, logits_to_keep=1)
                logits = output.logits[0, -1].float().cpu()
                logps = torch.log_softmax(logits.double(), dim=0)
                scores = {word: float(logps[token]) for word, token in labels.items()}
                row.update(prediction={job["query"]: scores["true"] >= scores["false"]}, word_logprobs=scores, labels=labels,
                    full_logits_sha256=hashlib.sha256(logits.numpy().tobytes()).hexdigest(),
                    allowed_probability_mass=sum(float(torch.exp(logps[t])) for t in labels.values()),
                    unconstrained_top_token_id=int(torch.argmax(logits)))
                del output, logits, logps
            else:
                output = model.generate(input_ids=inputs, attention_mask=torch.ones_like(inputs), do_sample=False,
                    max_new_tokens=160, use_cache=True, pad_token_id=tok.eos_token_id)
                generated = output[0, len(ids):].cpu().tolist()
                continuation = tok.decode(generated, skip_special_tokens=True)
                complete = '{"steps":[' + continuation
                obj = diagnostic.parse_trace(complete)
                verification = diagnostic.verify_trace(context, obj)
                row.update(prediction=None if obj is None else {key: obj[key] for key in ("derived", "effective")},
                    continuation=continuation, complete_object=complete, parsed=obj, verification=verification,
                    generated_token_ids=generated, output_tokens=len(generated), hit_cap=len(generated) == 160)
                del output
            row["seconds"] = time.monotonic() - t0
            handle.write(native.original.canonical(row) + "\n")
            handle.flush()
            rows.append(row)
            del inputs
            if i == 1 or i % 12 == 0 or i == len(cfg["inventory"]):
                parent.emit("diagnostic_progress", model=name, completed=i, total=240,
                    seconds=round(time.monotonic() - started, 2))
    parent.write_json(out / "summary.json", diagnostic.summarize(rows))
    parent.write_json(out / "completion.json", {"completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": time.monotonic() - started, "plan_sha256": parent.digest(run / "execution-plan.json"),
        "records_sha256": parent.digest(out / "records.jsonl")})
    parent.emit("diagnostic_complete", model=name, seconds=round(time.monotonic() - started, 2))


def audit(run, preflight):
    from transformers import AutoTokenizer
    plan = validate(run)
    by_id = {c["context_id"]: c for c in plan["contexts"]}
    jobs = diagnostic.jobs(plan["contexts"])
    result = {"status": "PASS", "preflight_only": preflight, "plan_sha256": parent.digest(run / "execution-plan.json"),
        "limits": "Reference answers use independent closure and canonical oracle. Proof/summary replay shares implementation. No independent GPU replay or execution attestation.", "models": {}}
    for name, cfg in plan["models"].items():
        assert [r["job"] for r in cfg["inventory"]] == jobs
        tok = AutoTokenizer.from_pretrained(cfg["snapshot"], local_files_only=True, trust_remote_code=False)
        raw = {}
        if not preflight:
            complete = json.loads((run / name / "completion.json").read_text())
            assert complete["plan_sha256"] == result["plan_sha256"]
            path = run / name / "records.jsonl"
            assert parent.digest(path) == complete["records_sha256"]
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            assert len(rows) == 240 and len({r["job_id"] for r in rows}) == 240
            assert diagnostic.summarize(rows) == json.loads((run / name / "summary.json").read_text())
            raw = {r["job_id"]: r for r in rows}
        for receipt in cfg["inventory"]:
            job = receipt["job"]
            context = diagnostic.renamed(by_id[job["context_id"]], job["naming"])
            text, ids, labels = encode(tok, context, job, cfg)
            assert native.original.sha(text) == receipt["prompt_sha256"]
            assert native.original.sha(native.original.canonical(ids)) == receipt["input_ids_sha256"]
            assert diagnostic.gold(context) == receipt["gold"]
            assert labels == receipt["labels"] and len(ids) == receipt["input_tokens"]
            if preflight:
                continue
            row = raw[job["job_id"]]
            assert all(row[k] == v for k, v in job.items())
            assert all(row[k] == receipt[k] for k in ("gold", "prompt_sha256", "input_ids_sha256", "input_tokens"))
            if job["endpoint"] == "direct":
                assert row["prediction"] == {job["query"]: row["word_logprobs"]["true"] >= row["word_logprobs"]["false"]}
            else:
                assert row["continuation"] == tok.decode(row["generated_token_ids"], skip_special_tokens=True)
                assert row["complete_object"] == '{"steps":[' + row["continuation"]
                obj = diagnostic.parse_trace(row["complete_object"])
                assert row["parsed"] == obj
                assert row["verification"] == diagnostic.verify_trace(context, obj)
                assert row["prediction"] == (None if obj is None else {k: obj[k] for k in ("derived", "effective")})
                if row["verification"]["valid"]:
                    assert row["prediction"] == diagnostic.gold(context)
        result["models"][name] = {"packets": 240, "records": len(raw)}
    parent.write_json(run / ("preflight-audit.json" if preflight else "postflight-audit.json"), result)
    parent.emit("diagnostic_audit", **result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "audit"))
    parser.add_argument("--run-dir", type=Path, default=RUN)
    parser.add_argument("--model", choices=("mistral", "qwen3"), default="mistral")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.run_dir)
    elif args.action == "run":
        execute(args.run_dir, args.model)
    else:
        audit(args.run_dir, args.preflight)
