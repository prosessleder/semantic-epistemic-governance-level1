#!/usr/bin/env python3
"""Separately frozen stress cases; do not alter the primary modern-model run."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from internal.benchmarks import ontology_latent_proposals as fixtures
from internal.benchmarks import ontology_checked_proposals as original
from internal.scripts import run_ontology_modern_models as modern
from internal.scripts import run_ontology_checked_proposals as previous
from internal.scripts.audit_ontology_checked_proposals import reference_candidate, reference_review, validate_sources, sha
from ontology_boundary.checked_release import ReviewContract, first_proposal_object
from ontology_boundary.proposal_commit import commit_frame
from ontology_boundary.rdf_adapter import crosscheck_ontology

RUN = ROOT / "runs/ontology-latent-proposals-2026-10-12"
PARENT = modern.RUN
SOURCES = ("internal/benchmarks/ontology_latent_proposals.py", "internal/scripts/run_ontology_latent_proposals.py",
           "internal/planning/ontology-latent-proposals-2026-10-12.md", "tests/test_ontology_latent_proposals.py")


def evaluate(contract, proposal):
    candidate, reviews = previous.evaluate(contract, proposal)
    detected = fixtures.probed_expansion(contract, candidate) if candidate is not None else False
    for r in reviews.values():
        r["goal_profile_expansion_detected"] = detected
        r["goal_profile_admitted"] = r["goal_satisfied"] and (not detected or r.get("exact_approval", False))
    return candidate, reviews


def summarize(rows):
    result = previous.summarize(rows)
    observations = [r for row in rows for r in row["reviews"].values()]
    result["pipelines"]["goal_profile"] = dict(n=len(observations),
        admitted=sum(r["goal_profile_admitted"] for r in observations),
        unsafe=sum(r["goal_profile_admitted"] and not r["reference_admitted"] for r in observations),
        unnecessary_hold=sum(not r["goal_profile_admitted"] and r["reference_admitted"] for r in observations),
        authorized_opportunities=sum(r["reference_admitted"] for r in observations),
        forbidden_expansion_opportunities=sum(r["goal_satisfied"] and r.get("protected_expansion", False)
            and not r.get("exact_approval", False) for r in observations))
    result["by_family"] = {f: dict(n=len(sub), valid=sum(r["valid_proposal"] for r in sub),
        goal_satisfied=sum(r["reviews"]["none"]["goal_satisfied"] for r in sub))
        for f in fixtures.FAMILIES for sub in [[r for r in rows if r["family"] == f]]}
    result["token_caps"] = sum(r["hit_cap"] for r in rows)
    return result


def prepare(run):
    from transformers import AutoTokenizer
    parent = json.loads((PARENT / "execution-plan.json").read_text())
    validate_sources(parent)
    tasks = fixtures.tasks()
    plan = dict(declared_at_utc=datetime.now(timezone.utc).isoformat(), exploratory=True,
        constructed_after_primary_direct_results=True, parent_plan_sha256=sha(PARENT / "execution-plan.json"),
        dependency_versions=modern.versions(), settings=parent["settings"], tasks=tasks,
        jobs=[dict(job_id=t["task_id"], arm="direct", kind="proposal", task=t) for t in tasks],
        models={}, sources=dict(parent["sources"], **{p: sha(ROOT/p) for p in SOURCES}))
    reference = []
    for t in tasks:
        c = ReviewContract.from_dict(t["contract"])
        candidate, reviews = evaluate(c, t["reference_patch"])
        assert candidate.to_dict() == t["reference_candidate"]
        assert reviews["none"]["goal_satisfied"] and reviews["none"]["protected_expansion"]
        assert not reviews["none"]["goal_profile_expansion_detected"]
        for o in (c.base, candidate):
            assert crosscheck_ontology(o, c.public_classes)["matches"]
        reference.append(dict(task_id=t["task_id"], valid_proposal=True, family=t["family"],
                              proposal=t["reference_patch"], reviews=reviews, hit_cap=False))
    for name, old in parent["models"].items():
        cfg = {k: v for k, v in old.items() if k != "inventory"}
        tok = AutoTokenizer.from_pretrained(cfg["snapshot"], local_files_only=True, trust_remote_code=False)
        cfg["inventory"] = []
        for job in plan["jobs"]:
            text, ids = modern.encode(tok, job)
            cfg["inventory"].append(dict(job_id=job["job_id"], prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),
                input_ids_sha256=modern.digest_value(ids), input_tokens=len(ids)))
        plan["models"][name] = cfg
    run.mkdir(exist_ok=False)
    modern.write(run / "reference-preflight.json", dict(summary=summarize(reference), cases=reference))
    modern.write(run / "execution-plan.json", plan)
    modern.emit("latent_study_frozen", requests=24, plan_sha256=sha(run / "execution-plan.json"))


def execute(run, name):
    import torch
    plan = json.loads((run / "execution-plan.json").read_text())
    validate_sources(plan)
    assert modern.versions() == plan["dependency_versions"]
    out = run / name
    out.mkdir(exist_ok=False)
    start = time.monotonic()
    torch.manual_seed(plan["settings"]["seed"])
    tok, model = modern.load(plan["models"][name])
    rows = []
    with (out / "records.jsonl").open("x") as handle:
        for job, packet in zip(plan["jobs"], plan["models"][name]["inventory"]):
            text, ids = modern.encode(tok, job)
            assert hashlib.sha256(text.encode()).hexdigest() == packet["prompt_sha256"]
            assert modern.digest_value(ids) == packet["input_ids_sha256"]
            row = dict(packet, task_id=job["task"]["task_id"], family=job["task"]["family"],
                       **modern.generate(tok, model, name, job, ids, 96))
            contract = ReviewContract.from_dict(job["task"]["contract"])
            candidate, reviews = evaluate(contract, row["proposal"])
            row.update(valid_proposal=candidate is not None, candidate=None if candidate is None else candidate.to_dict(), reviews=reviews)
            handle.write(modern.canonical(row) + "\n"); handle.flush(); rows.append(row)
            modern.emit("latent_progress", model=name, completed=len(rows), total=12)
    modern.write(out / "summary.json", summarize(rows))
    modern.write(out / "completion.json", dict(plan_sha256=sha(run / "execution-plan.json"),
        records_sha256=sha(out / "records.jsonl"), elapsed_seconds=time.monotonic() - start,
        completed_at_utc=datetime.now(timezone.utc).isoformat()))
    modern.emit("latent_complete", model=name, summary=summarize(rows))


def audit(run):
    from transformers import AutoTokenizer
    plan = json.loads((run / "execution-plan.json").read_text()); validate_sources(plan)
    result = dict(status="PASS", plan_sha256=sha(run / "execution-plan.json"), models={})
    for name, cfg in plan["models"].items():
        tok = AutoTokenizer.from_pretrained(cfg["snapshot"], local_files_only=True, trust_remote_code=False)
        out = run / name; complete = json.loads((out / "completion.json").read_text())
        assert complete["plan_sha256"] == result["plan_sha256"] and complete["records_sha256"] == sha(out / "records.jsonl")
        rows = [json.loads(l) for l in (out / "records.jsonl").read_text().splitlines()]
        assert len(rows) == 12 and [r["job_id"] for r in rows] == [j["job_id"] for j in plan["jobs"]]
        assert summarize(rows) == json.loads((out / "summary.json").read_text())
        commits = valid_n = 0
        for job, row in zip(plan["jobs"], rows):
            text, ids = modern.encode(tok, job)
            assert row["prompt_sha256"] == hashlib.sha256(text.encode()).hexdigest()
            assert row["input_ids_sha256"] == modern.digest_value(ids)
            raw = tok.decode(modern.strip_terminal_ids(row["generated_token_ids"], set(row["terminal_token_ids"])), skip_special_tokens=False)
            assert raw == row["raw_response"]
            frame = modern.final_frame(name, "direct", raw)
            try: obj, trailing = first_proposal_object(frame)
            except ValueError: obj, trailing = None, None
            assert obj == row["proposal"] and trailing == row["trailing_text"]
            c = ReviewContract.from_dict(job["task"]["contract"])
            try: candidate = reference_candidate(c, obj)
            except (ValueError, TypeError): candidate = None
            assert row["valid_proposal"] == (candidate is not None)
            if candidate is None:
                assert not any(r["admitted"] for r in row["reviews"].values()); continue
            valid_n += 1
            assert candidate.to_dict() == row["candidate"] and crosscheck_ontology(candidate, c.public_classes)["matches"]
            detected = fixtures.probed_expansion(c, candidate)
            for mode in original.MODES:
                reg = original.registry(c, candidate, mode); expected = reference_review(c, candidate, reg)
                expected["goal_profile_expansion_detected"] = detected
                expected["goal_profile_admitted"] = expected["goal_satisfied"] and (not detected or expected["exact_approval"])
                assert all(row["reviews"][mode][k] == expected[k] for k in expected)
                state, receipt = commit_frame(c.base, c, frame, reg)
                assert receipt["admitted"] == expected["admitted"]
                assert state == (candidate if expected["admitted"] else c.base); commits += 1
        result["models"][name] = dict(records=12, owl_candidates=valid_n, commit_replays=commits)
    modern.write(run / "postflight-audit.json", result); modern.emit("latent_audit", **result)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("prepare", "run", "audit"))
    p.add_argument("--model", choices=("qwen35", "gemma4"), default="qwen35")
    p.add_argument("--run-dir", type=Path, default=RUN)
    a = p.parse_args()
    if a.action == "prepare": prepare(a.run_dir)
    elif a.action == "run": execute(a.run_dir, a.model)
    else: audit(a.run_dir)
