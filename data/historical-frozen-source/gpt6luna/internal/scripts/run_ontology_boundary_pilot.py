#!/usr/bin/env python3
"""Freeze and run the private finite ontology-release admission pilot."""
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
from internal.benchmarks import ontology_boundary_runner as runner
from ontology_boundary import dataset

DEFAULT_RUN = ROOT / "runs/ontology-boundary-pilot-2026-10-10"
MODELS = {
    "qwen2": {"id": "Qwen/Qwen2.5-3B-Instruct", "revision": "aa8e72537993ba99e69dfaafa59ed015b17504d1",
              "snapshot": str(ROOT / "runs/hf-cache/models--Qwen--Qwen2.5-3B-Instruct/snapshots/aa8e72537993ba99e69dfaafa59ed015b17504d1")},
    "qwen3": {"id": "Qwen/Qwen3-4B-Instruct-2507", "revision": "cdbee75f17c01a7cc42f958dc650907174af0554",
              "snapshot": str(Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen3-4B-Instruct-2507/snapshots/cdbee75f17c01a7cc42f958dc650907174af0554")},
}
SOURCES = (
    "src/ontology_boundary/__init__.py", "src/ontology_boundary/oracle.py", "src/ontology_boundary/rdf_adapter.py",
    "src/ontology_boundary/dataset.py", "src/ontology_boundary/store_simulator.py",
    "internal/benchmarks/ontology_boundary_runner.py", "internal/scripts/run_ontology_boundary_pilot.py",
    "internal/scripts/summarize_ontology_boundary_pilot.py",
    "internal/planning/ontology-boundary-protocol-2026-10-10.md",
    "internal/planning/ontology-boundary-requirements.lock",
    "internal/planning/ontology-boundary-requirements.txt",
    "internal/research/ontology-boundary-preflight-audit-2026-10-10.md",
    "internal/research/ontology-boundary-contribution-audit-2026-10-10.md",
    "tests/test_ontology_boundary_oracle.py", "tests/test_ontology_boundary_dataset.py",
    "tests/test_ontology_boundary_runner.py", "tests/test_ontology_boundary_store.py",
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    return {name: digest(ROOT / name) for name in SOURCES}


def write_json(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def emit(event, **values):
    print(runner.canonical({"event": event, **values}), flush=True)


def model_hashes(snapshot):
    snapshot = Path(snapshot)
    paths = [p for p in snapshot.iterdir() if p.name.endswith((".json", ".txt", ".safetensors"))]
    if not any(p.suffix == ".safetensors" for p in paths):
        raise ValueError("Pinned local model weights absent")
    return {p.name: digest(p) for p in sorted(paths)}


def preflight(tokenizer, data):
    results = []
    max_tokens = 0
    for split in ("dev", "test"):
        for index, case in enumerate(data[split]):
            for mode in runner.MODES:
                for condition in runner.CONDITIONS:
                    text, ids, labels = runner.encoded(tokenizer, runner.prompt(case, mode, condition, index))
                    max_tokens = max(max_tokens, len(ids))
                    results.append({"base_id": case["base_id"], "split": split, "mode": mode, "condition": condition,
                                    "prompt_sha256": runner.sha(text), "input_tokens": len(ids), "labels": labels})
            for condition in runner.CONDITIONS:
                text, ids, labels = runner.encoded(tokenizer, runner.semantic_prompt(case, condition, index))
                max_tokens = max(max_tokens, len(ids))
                results.append({"base_id": case["base_id"], "split": split, "mode": "expansion-only", "condition": condition,
                                "prompt_sha256": runner.sha(text), "input_tokens": len(ids), "labels": {c: labels[c] for c in "AB"}})
    return {"passed": True, "max_input_tokens": max_tokens, "n": len(results),
            "response_scoring": "One-token complete binary A/B or joint A/B/C/D responses; full-vocabulary next-token log probabilities, argmax restricted to task codes.",
            "prompts": results}


def prepare(run_dir):
    import torch
    import transformers
    from transformers import AutoTokenizer
    from ontology_boundary.rdf_adapter import dependency_versions
    data = dataset.generate_cases(seed=runner.SEED)
    sources = source_hashes()
    model_receipts = {}
    for name, config in MODELS.items():
        snapshot = Path(config["snapshot"])
        if snapshot.name != config["revision"]:
            raise ValueError("Wrong checkpoint revision")
        tok = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
        model_receipts[name] = {**config, "artifact_sha256": model_hashes(snapshot), "tokenizer_preflight": preflight(tok, data)}
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "dataset.json", data)
    plan = {"declared_at_utc": datetime.now(timezone.utc).isoformat(), "seed": runner.SEED,
            "source_sha256": sources, "data_sha256": digest(run_dir / "dataset.json"), "models": model_receipts,
            "versions": {"torch": torch.__version__, "transformers": transformers.__version__, **dependency_versions()},
            "conditions": list(runner.CONDITIONS), "approval_modes": list(runner.MODES),
            "device": "mps", "dtype": "bfloat16", "attn_implementation": "eager", "batch_size": 1,
            "context_limit": runner.MAX_TOKENS, "truncate": False, "code_mapping": "Four ABCD rotations balanced equally across expanding/nonexpanding pairs; identical in matched arms.",
            "prompt_selection": "None. DEV is a formatting/comprehension diagnostic only; no prompt or parameter selection.",
            "primary_outcomes": ["separately asked binary protected expansion", "joint-code trusted release activation", "unsafe activation", "unnecessary hold"],
            "evidence": "Profile contains seed types only; no derived truth values, expansion flags, families or gold outcomes.",
            "scope": "Synthetic restricted finite Horn ontology release decisions; no activation steering or autonomous agent execution.",
            "independent_units": "24 test ontology pairs in six motifs; seven approval modes and three evidence arms are repeated observations.",
            "uncertainty": "Descriptive paired counts by family. No iid confidence interval or all-LLM generalization."}
    write_json(run_dir / "execution-plan.json", plan)
    emit("prepared", run_dir=str(run_dir), plan_sha256=digest(run_dir / "execution-plan.json"),
         counts={split: len(data[split]) for split in ("dev", "test")},
         max_tokens={name: receipt["tokenizer_preflight"]["max_input_tokens"] for name, receipt in model_receipts.items()})


def execute(run_dir, name):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    plan = json.loads((run_dir / "execution-plan.json").read_text())
    if source_hashes() != plan["source_sha256"] or digest(run_dir / "dataset.json") != plan["data_sha256"]:
        raise ValueError("Source or dataset changed after freeze")
    data = json.loads((run_dir / "dataset.json").read_text())
    config = plan["models"][name]
    snapshot = Path(config["snapshot"])
    if snapshot.name != config["revision"] or model_hashes(snapshot) != config["artifact_sha256"]:
        raise ValueError("Model artifacts changed")
    out = run_dir / name
    out.mkdir(exist_ok=False)
    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS unavailable; no silent CPU fallback")
    torch.manual_seed(runner.SEED)
    tok = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
    if preflight(tok, data) != config["tokenizer_preflight"]:
        raise ValueError("Tokenizer prompts changed")
    started = time.monotonic()
    emit("loading", model=config["id"], revision=config["revision"])
    model = AutoModelForCausalLM.from_pretrained(snapshot, dtype=torch.bfloat16, attn_implementation="eager",
                                               local_files_only=True, trust_remote_code=False).to("mps").eval()
    model.requires_grad_(False)
    emit("loaded", seconds=round(time.monotonic() - started, 2))
    for split in ("dev", "test"):
        semantic_rows = runner.evaluate_semantics(model, tok, data[split], output_path=out / f"{split}-semantic-records.jsonl",
                                                 progress=lambda v: emit("semantic_progress", model=name, split=split, **v))
        write_json(out / f"{split}-semantic-summary.json", runner.summarize_semantics(semantic_rows))
        rows = runner.evaluate(model, tok, data[split], output_path=out / f"{split}-records.jsonl",
                               progress=lambda v: emit("progress", model=name, split=split, **v))
        write_json(out / f"{split}-summary.json", runner.summarize(rows))
        emit("split_complete", model=name, split=split, summary=runner.summarize(rows))
    write_json(out / "completion.json", {"completed_at_utc": datetime.now(timezone.utc).isoformat(),
              "elapsed_seconds": time.monotonic() - started, "plan_sha256": digest(run_dir / "execution-plan.json"),
              "raw_sha256": {name: digest(out / name) for name in
                  ("dev-records.jsonl", "test-records.jsonl", "dev-semantic-records.jsonl", "test-semantic-records.jsonl")}})
    emit("complete", model=name, elapsed_seconds=round(time.monotonic() - started, 2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--model", choices=MODELS, default="qwen2")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.run_dir)
    else:
        execute(args.run_dir, args.model)


if __name__ == "__main__":
    main()
