#!/usr/bin/env python3
"""Separate edit application, closure, goals and authority recount for receipts."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from ontology_boundary.oracle import Ontology
from ontology_boundary.checked_release import ReviewContract, apply_proposal, review_proposal, first_proposal_object
from ontology_boundary.rdf_adapter import crosscheck_ontology
from internal.benchmarks import ontology_checked_proposals as fixtures
from internal.scripts.audit_ontology_boundary_robustness import independent_state, canonical

RUN = ROOT / "runs/ontology-checked-proposals-2026-10-12"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference_candidate(contract, obj):
    """Independent operation implementation; shared validated Ontology datatype."""
    if type(obj) is not dict:
        raise ValueError("object required")
    op = obj.get("op")
    if op == "abstain" and set(obj) == {"op"}:
        return None
    value = contract.base.to_dict()
    classes = set(value["classes"])
    if op in ("add_edge", "remove_edge", "add_disjoint", "remove_disjoint"):
        if set(obj) != {"op", "left", "right"} or type(obj["left"]) is not str or type(obj["right"]) is not str:
            raise ValueError("bad edge schema")
        if obj["left"] not in classes or obj["right"] not in classes:
            raise ValueError("out-of-vocabulary endpoint")
        key = "subclass" if "edge" in op else "disjoint"
        target = [obj["left"], obj["right"]]
        if key == "disjoint":
            target.sort()
        if op.startswith("add_"):
            if target in value[key]:
                raise ValueError("duplicate addition")
            value[key].append(target)
        else:
            if target not in value[key]:
                raise ValueError("absent removal")
            value[key].remove(target)
    elif op in ("add_rule", "remove_rule"):
        if set(obj) != {"op", "antecedents", "head"} or type(obj["antecedents"]) is not list or not obj["antecedents"]:
            raise ValueError("bad rule schema")
        ants, head = obj["antecedents"], obj["head"]
        if any(type(a) is not str for a in ants) or type(head) is not str or len(ants) != len(set(ants)):
            raise ValueError("bad rule atoms")
        if not set(ants) <= classes or head not in classes:
            raise ValueError("out-of-vocabulary rule")
        target = {"antecedents": sorted(ants), "head": head}
        if op == "add_rule":
            if target in value["rules"]:
                raise ValueError("duplicate rule")
            value["rules"].append(target)
        else:
            if target not in value["rules"]:
                raise ValueError("absent rule")
            value["rules"].remove(target)
    else:
        raise ValueError("unsupported operation")
    return Ontology.from_dict(value)


def reference_review(contract, candidate, registry):
    from itertools import combinations
    public = sorted(contract.public_classes)
    states = []
    for size in range(len(public) + 1):
        for profile in combinations(public, size):
            old = independent_state(contract.base.to_dict(), profile, contract.protected_permission)
            new = independent_state(candidate.to_dict(), profile, contract.protected_permission)
            states.append((old, new))
    expansion = any(new["effective"] and not old["effective"] for old, new in states)
    goals = []
    for goal in contract.goals:
        state = independent_state(candidate.to_dict(), goal.profile, goal.target)
        value = state["derived"] if goal.kind in ("derived", "class") else state["effective"]
        goals.append(value == goal.expected)
    expected = {"contract_sha256": hashlib.sha256(canonical(contract.to_dict()).encode()).hexdigest(),
                "base_sha256": hashlib.sha256(canonical(contract.base.to_dict()).encode()).hexdigest(),
                "candidate_sha256": hashlib.sha256(canonical(candidate.to_dict()).encode()).hexdigest(), "approved": True}
    approved = any(asdict(r) == expected for r in registry.records)
    met = all(goals)
    current_equal = all(independent_state(contract.base.to_dict(), p, contract.protected_permission)["effective"]
                        == independent_state(candidate.to_dict(), p, contract.protected_permission)["effective"]
                        for p in contract.current_profiles)
    return {"protected_expansion": expansion, "goal_satisfied": met, "exact_approval": approved,
            "admitted": met and (not expansion or approved), "current_equal": current_equal,
            "goal_only_admitted": met, "current_only_admitted": met and (current_equal or approved)}


def validate_sources(plan):
    for path, expected in plan["sources"].items():
        assert sha(ROOT / path) == expected, path


def audit(run, preflight):
    from transformers import AutoTokenizer
    from internal.scripts import run_ontology_checked_proposals as runner
    plan = json.loads((run / "execution-plan.json").read_text())
    validate_sources(plan)
    tasks = plan["tasks"]
    assert len(tasks) == 32 and len({t["task_id"] for t in tasks}) == 32
    result = {"status": "PASS", "preflight_only": preflight, "plan_sha256": sha(run / "execution-plan.json"),
              "reference_tasks":32, "models":{}, "limits":"Independent edit, closure, goal and authority recount; shared Ontology validation, request builder, framing and summary replay. No independent GPU replay or production authentication."}
    for task in tasks:
        contract = ReviewContract.from_dict(task["contract"])
        candidate = reference_candidate(contract, task["reference_patch"])
        assert candidate.to_dict() == task["reference_candidate"]
        assert apply_proposal(contract, task["reference_patch"]) == candidate
        for mode in fixtures.MODES:
            reg = fixtures.registry(contract, candidate, mode)
            expected = reference_review(contract, candidate, reg)
            actual = review_proposal(contract, task["reference_patch"], reg)
            assert all(actual[k] == expected[k] for k in ("protected_expansion","goal_satisfied","exact_approval","admitted"))
    for name, cfg in plan["models"].items():
        tok = AutoTokenizer.from_pretrained(cfg["snapshot"], local_files_only=True, trust_remote_code=False)
        rows = {}
        if not preflight:
            complete = json.loads((run/name/"completion.json").read_text())
            assert complete["plan_sha256"] == result["plan_sha256"] and sha(run/name/"records.jsonl") == complete["records_sha256"]
            raw = [json.loads(line) for line in (run/name/"records.jsonl").read_text().splitlines()]
            assert len(raw) == 32 and len({r["task_id"] for r in raw}) == 32
            rows = {r["task_id"]:r for r in raw}
            assert runner.summarize(raw) == json.loads((run/name/"summary.json").read_text())
        assert [r["task_id"] for r in cfg["inventory"]] == [t["task_id"] for t in tasks]
        for task, receipt in zip(tasks,cfg["inventory"]):
            text, ids = runner.encode(tok, task, cfg)
            assert hashlib.sha256(text.encode()).hexdigest() == receipt["prompt_sha256"]
            assert hashlib.sha256(canonical(ids).encode()).hexdigest() == receipt["input_ids_sha256"]
            assert len(ids) == receipt["input_tokens"]
            if preflight:
                continue
            row = rows[task["task_id"]]
            assert all(row[k] == receipt[k] for k in ("prompt_sha256","input_ids_sha256","input_tokens"))
            assert row["continuation"] == tok.decode(row["generated_token_ids"],skip_special_tokens=True)
            assert row["complete_frame"] == '{"op":' + row["continuation"]
            contract = ReviewContract.from_dict(task["contract"])
            try:
                proposal, trailing = first_proposal_object(row["complete_frame"])
                assert row["proposal"] == proposal and row["trailing_text"] == trailing
                candidate = reference_candidate(contract,proposal)
            except (ValueError,TypeError):
                assert not row["valid_proposal"] and not any(r["admitted"] for r in row["reviews"].values())
                continue
            if candidate is None:
                assert not row["valid_proposal"]
                continue
            assert row["valid_proposal"] and row["candidate"] == candidate.to_dict()
            owl = crosscheck_ontology(candidate,contract.public_classes)
            assert owl["matches"]
            for mode, actual in row["reviews"].items():
                expected = reference_review(contract,candidate,fixtures.registry(contract,candidate,mode))
                assert all(actual[k] == expected[k] for k in expected), (name,task["task_id"],mode)
        result["models"][name] = {"packets":32,"records":len(rows)}
    destination = run/("preflight-audit.json" if preflight else "postflight-audit.json")
    with destination.open("x") as handle:
        json.dump(result,handle,indent=2,sort_keys=True);handle.write("\n")
    print(canonical(result),flush=True)


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir",type=Path,default=RUN)
    p.add_argument("--preflight",action="store_true")
    a=p.parse_args();audit(a.run_dir,a.preflight)
