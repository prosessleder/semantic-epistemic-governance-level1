#!/usr/bin/env python3
"""Separate CPU closure/authority/coverage audit; no model execution."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from itertools import combinations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def independent_state(theory, seeds, permission):
    atoms = set(seeds)
    clauses = [(set([a]), b) for a, b in theory["subclass"]]
    clauses += [(set(r["antecedents"]), r["head"]) for r in theory["rules"]]
    while True:
        before = set(atoms)
        for antecedents, head in clauses:
            if antecedents <= atoms:
                atoms.add(head)
        if atoms == before:
            break
    consistent = not any(a in atoms and b in atoms for a, b in theory["disjoint"])
    return {"derived": permission in atoms, "consistent": consistent,
            "effective": permission in atoms and consistent}


def independent_certificate(case):
    signature = sorted(case["public_classes"])
    profiles = [list(seed) for size in range(len(signature) + 1) for seed in combinations(signature, size)]
    rows = [{"seed_types": seed, **{side: independent_state(case[side], seed, case["protected_permission"])
             for side in ("old", "new")}} for seed in profiles]
    return {"base_sha256": hashlib.sha256(canonical(case["old"]).encode()).hexdigest(),
            "candidate_sha256": hashlib.sha256(canonical(case["new"]).encode()).hexdigest(),
            "permission": case["protected_permission"], "public_classes": signature, "profiles": rows}


def independent_approval(prompt, cert):
    marker = "Trusted approval record: "
    record = json.loads(next(line[len(marker):] for line in prompt.splitlines() if line.startswith(marker)))
    expected = {"schema_version": 1, "provenance": "trusted-release-register", "issuer": "tcb-release-authority",
        "mandate": "ontology-metadata-boundary-release", "decision": "approved",
        "scope": {"permission": "can_write_metadata", "field": "metadata", "source_task": "task-A", "destination_task": "task-B"},
        "base_sha256": cert["base_sha256"], "candidate_sha256": cert["candidate_sha256"]}
    return type(record) is dict and type(record.get("schema_version")) is int and record == expected


def independent_book(case, job):
    if job["task"] == "joint":
        choices = ([False, True], [False, False], [True, True], [True, False])
        return {c: choices[(i + case["encoding_index"]) % 4] for i, c in enumerate("ABCD")}
    yes = "AB"[job["variant"] if job["task"] == "local" else case["encoding_index"] % 2]
    return {c: c == yes for c in "AB"}


def check_summary(rows, supplied):
    for arm in ("legacy", "raw", "verified"):
        semantic = [r for r in rows if r["task"] == "semantic" and r["arm"] == arm]
        joint = [r for r in rows if r["task"] == "joint" and r["arm"] == arm]
        values = {"semantic_n": len(semantic), "semantic_correct": sum(r["prediction"] == r["gold"] for r in semantic),
            "semantic_yes": sum(r["prediction"] for r in semantic),
            "missed_expansions": sum(r["gold"] and r["prediction"] is False for r in semantic),
            "spurious_expansions": sum(not r["gold"] and r["prediction"] is True for r in semantic),
            "joint_n": len(joint), "joint_correct": sum(r["prediction"] == r["gold"] for r in joint),
            "joint_semantic_correct": sum(r["prediction"][0] == r["gold"][0] for r in joint),
            "admission_correct": sum(r["prediction"][1] == r["gold"][1] for r in joint),
            "unsafe": sum(r["prediction"][1] and not r["gold"][1] for r in joint),
            "unsafe_opportunities": sum(not r["gold"][1] for r in joint),
            "unnecessary_hold": sum(not r["prediction"][1] and r["gold"][1] for r in joint),
            "admissible_opportunities": sum(r["gold"][1] for r in joint)}
        for key, value in values.items():
            assert supplied["review"][arm][key] == value, (arm, key)
        for family, item in supplied["review"][arm]["by_family"].items():
            group = [r for r in semantic if r["family"] == family]
            assert item == {"n": len(group), "correct": sum(r["correct"] for r in group)}
        predictions = {r["base_id"]: r["prediction"] for r in semantic}
        pairs = [(not predictions[r["base_id"]] or r["exact_approval"], r["gold"][1]) for r in joint]
        assert supplied["semantic_then_exact_approval"][arm] == {"n": len(pairs),
            "correct": sum(a == b for a, b in pairs), "unsafe": sum(a and not b for a, b in pairs),
            "unnecessary_hold": sum(not a and b for a, b in pairs)}
    for query in ("derived", "effective"):
        group = [r for r in rows if r["task"] == "local" and r["query"] == query]
        positives = [r for r in group if r["gold"]]
        negatives = [r for r in group if not r["gold"]]
        tpr = sum(r["prediction"] for r in positives) / len(positives)
        tnr = sum(not r["prediction"] for r in negatives) / len(negatives)
        paired = {}
        for r in group:
            paired.setdefault((r["base_id"], r["side"], r["role"]), []).append(r["prediction"])
        assert all(len(v) == 2 for v in paired.values())
        assert supplied["controls"][query] == {"n": len(group), "correct": sum(r["correct"] for r in group),
            "positive_n": len(positives), "negative_n": len(negatives), "true_positive_rate": tpr,
            "true_negative_rate": tnr, "balanced_accuracy": (tpr + tnr) / 2,
            "encoding_pairs": len(paired), "encoding_disagreements": sum(a != b for a, b in paired.values()),
            "correct_code_counts": dict(Counter(r["gold_code"] for r in group))}
    for kind in ("semantic", "joint", "admission"):
        task = "joint" if kind == "admission" else kind
        raw = {r["job_key"]: r for r in rows if r["task"] == task and r["arm"] == "raw"}
        new = {r["job_key"]: r for r in rows if r["task"] == task and r["arm"] == "verified"}
        assert raw.keys() == new.keys()
        good = lambda r: r["prediction"][1] == r["gold"][1] if kind == "admission" else r["correct"]
        assert supplied["paired"][kind] == {"n": len(raw),
            "rescues": sum(not good(raw[k]) and good(new[k]) for k in raw),
            "harms": sum(good(raw[k]) and not good(new[k]) for k in raw)}


def audit(run_dir, preflight):
    from transformers import AutoTokenizer
    from internal.benchmarks import ontology_boundary_robustness as builder
    plan = json.loads((run_dir / "execution-plan.json").read_text())
    for name, expected in plan["sources"].items():
        assert sha(ROOT / name) == expected, name
    for filename, key in (("dataset.json", "data_sha256"), ("certificates.json", "certificates_sha256"), ("materialization.json", "materialization_sha256")):
        assert sha(run_dir / filename) == plan[key]
    data = json.loads((run_dir / "dataset.json").read_text())
    cases = {c["base_id"]: c for split in ("dev", "test") for c in data[split]}
    certs = {key: independent_certificate(case) for key, case in cases.items()}
    assert certs == json.loads((run_dir / "certificates.json").read_text())
    checks = json.loads((run_dir / "materialization.json").read_text())
    assert len(checks) == 56 and all(c["result"]["matches"] and c["result"]["profiles_checked"] == 16 for c in checks)
    for check in checks:
        cert = certs[check["base_id"]]
        for profile, observed in zip(cert["profiles"], check["result"]["profiles"]):
            assert observed["matches"] and observed["owlrl"]["seed_types"] == profile["seed_types"]
            bits = profile[check["side"]]
            p = cert["permission"]
            owl = observed["owlrl"]
            assert bits == {"derived": p in owl["derived_permissions"], "consistent": owl["consistent"], "effective": p in owl["permissions"]}
    report = {"status": "PASS", "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "plan_sha256": sha(run_dir / "execution-plan.json"), "auditor_sha256": sha(__file__),
        "preflight_only": preflight, "independent_profile_states": 896, "models": {},
        "limitations": ["post hoc reused cases; not fresh confirmation", "requests recreated using frozen builder; closure/authority/code decoding and arithmetic implemented separately", "no GPU inference or external execution attestation", "symbolic evidence changes information; improved results do not demonstrate better unaided deduction"]}
    for name, config in plan["models"].items():
        tok = AutoTokenizer.from_pretrained(config["snapshot"], local_files_only=True, trust_remote_code=False)
        rows_by_id = {}
        summaries = {}
        if not preflight:
            complete = json.loads((run_dir / name / "completion.json").read_text())
            assert complete["plan_sha256"] == report["plan_sha256"]
            for split in ("dev", "test"):
                path = run_dir / name / f"{split}-records.jsonl"
                assert sha(path) == complete["raw_sha256"][split]
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                assert len(rows) == plan["counts_per_model"][split]
                assert len({r["job_id"] for r in rows}) == len(rows)
                summaries[split] = json.loads((run_dir / name / f"{split}-summary.json").read_text())
                check_summary(rows, summaries[split])
                rows_by_id.update({r["job_id"]: r for r in rows})
        for item in config["tokenizer"]["rows"]:
            job = item["job"]
            case, cert = cases[job["base_id"]], certs[job["base_id"]]
            messages = builder.packet(case, job)
            text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            ids = tok.encode(text, add_special_tokens=False)
            assert len(ids) <= 4096 and len(ids) == item["input_tokens"]
            assert hashlib.sha256(text.encode()).hexdigest() == item["prompt_sha256"]
            assert hashlib.sha256(canonical(ids).encode()).hexdigest() == item["input_ids_sha256"]
            book = independent_book(case, job)
            assert book == item["codebook"]
            for code, token in item["labels"].items():
                candidate = tok.encode(config["tokenizer"]["response_prefix"] + code, add_special_tokens=False)
                assert candidate == [token]
                assert tok.encode(text + config["tokenizer"]["response_prefix"] + code, add_special_tokens=False) == ids + candidate
            if job["task"] == "local":
                gold = independent_state(case[job["side"]], case["profiles"][job["role"]], case["protected_permission"])[job["query"]]
            else:
                expansion = any(p["new"]["effective"] and not p["old"]["effective"] for p in cert["profiles"])
                gold = expansion if job["task"] == "semantic" else [expansion, not expansion or independent_approval(messages[1]["content"], cert)]
            assert gold == item["gold"]
            if not preflight:
                row = rows_by_id[job["job_id"]]
                assert all(row[k] == v for k, v in job.items())
                assert row["labels"] == item["labels"] and row["codebook"] == book and row["gold"] == gold
                assert row["prompt_sha256"] == item["prompt_sha256"] and row["input_ids_sha256"] == item["input_ids_sha256"]
                assert row["input_tokens"] == item["input_tokens"] and row["response_prefix"] == config["tokenizer"]["response_prefix"]
                chosen = max(item["labels"], key=row["code_logprobs"].get)
                assert row["response_code"] == chosen and row["prediction"] == book[chosen]
                assert row["correct"] == (row["prediction"] == gold)
                assert row["gold_code"] == next(c for c, v in book.items() if v == gold)
                if job["task"] == "joint":
                    assert row["exact_approval"] == independent_approval(messages[1]["content"], cert)
        report["models"][name] = {"packets": len(config["tokenizer"]["rows"]), "records": len(rows_by_id), "summaries": summaries}
    destination = run_dir / ("preflight-audit.json" if preflight else "postflight-audit.json")
    with destination.open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(canonical({"status": report["status"], "receipt": str(destination), "sha256": sha(destination),
        "profile_states": 896, "packets": sum(m["packets"] for m in report["models"].values()),
        "records": sum(m["records"] for m in report["models"].values())}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", type=Path, default=ROOT / "runs/ontology-boundary-robustness-2026-10-12")
    p.add_argument("--preflight", action="store_true")
    args = p.parse_args()
    audit(args.run_dir, args.preflight)
