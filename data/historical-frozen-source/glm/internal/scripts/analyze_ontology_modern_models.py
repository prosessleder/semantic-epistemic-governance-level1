#!/usr/bin/env python3
"""Post hoc diagnostics from preserved outputs; no further model inference."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from internal.scripts import run_ontology_modern_models as modern
from internal.scripts import run_ontology_latent_proposals as latent
from internal.scripts import run_ontology_checked_proposals as previous
from internal.scripts.audit_ontology_checked_proposals import reference_candidate, reference_review, sha, validate_sources
from internal.benchmarks import ontology_checked_proposals as fixtures
from internal.benchmarks.ontology_latent_proposals import probed_expansion
from ontology_boundary.checked_release import ReviewContract, first_proposal_object, ApprovalRegistry
from ontology_boundary.proposal_commit import commit_frame
from ontology_boundary.rdf_adapter import crosscheck_ontology


def normalize(name, raw):
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
        raise ValueError("undeclared model")
    raw = raw.strip()
    fenced = False
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) < 3 or lines[0] not in ("```json", "```") or lines[-1] != "```" or raw.count("```") != 2:
            raise ValueError("not a sole declared JSON fence")
        raw = "\n".join(lines[1:-1]).strip(); fenced = True
    obj, trailing = first_proposal_object(raw)
    if trailing.strip():
        raise ValueError("more than one final object or extra content")
    return raw, obj, fenced


def rows(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines()]


def stronger_rows(tasks, raw):
    result = []
    for task, row in zip(tasks, raw):
        contract = ReviewContract.from_dict(task["contract"])
        candidate, reviews = latent.evaluate(contract, row["proposal"])
        result.append(dict(task_id=task["task_id"], family=task["family"], proposal=row["proposal"],
                           valid_proposal=candidate is not None, reviews=reviews, hit_cap=row.get("hit_cap", False)))
    value = latent.summarize(result)
    value["by_family"] = previous.summarize(result)["by_family"]
    return value


def analyze():
    main = modern.RUN; stress = latent.RUN
    plan = json.loads((main / "execution-plan.json").read_text()); validate_sources(plan)
    stress_plan = json.loads((stress / "execution-plan.json").read_text()); validate_sources(stress_plan)
    result = dict(scope="Completed local exploratory follow-up; post hoc framing and stronger-baseline diagnostics separately labelled",
        created_at_utc=datetime.now(timezone.utc).isoformat(), primary_plan_sha256=sha(main / "execution-plan.json"),
        stress_plan_sha256=sha(stress / "execution-plan.json"), posthoc=True,
        posthoc_sources={p: sha(ROOT/p) for p in ("internal/scripts/analyze_ontology_modern_models.py",
            "internal/planning/ontology-modern-framing-diagnostic-2026-10-12.md")}, models={},
        primary_audit=json.loads((main / "postflight-audit.json").read_text()),
        stress_audit=json.loads((stress / "postflight-audit.json").read_text()))
    refs = [dict(proposal=t["reference_patch"], hit_cap=False) for t in plan["tasks"]]
    result["original_reference_stronger_baseline"] = stronger_rows(plan["tasks"], refs)
    for name in ("qwen35", "gemma4"):
        primary = rows(main / name / "records.jsonl")
        complete = json.loads((main/name/"completion.json").read_text())
        assert len(primary) == 96 and complete["records_sha256"] == sha(main/name/"records.jsonl")
        summary = json.loads((main/name/"summary.json").read_text())
        for arm in ("direct", "reasoned"):
            sub = [r for r in primary if r["kind"] == "proposal" and r["arm"] == arm]
            expected = previous.summarize(sub)
            assert all(summary[arm][k] == v for k, v in expected.items())
        for q in ("derived", "effective"):
            sub = [r for r in primary if r["kind"] == "control" and r["query"] == q]
            assert modern.control_summary(sub) == summary["controls"][q]
        invalid_commits = 0
        for arm in ("direct", "reasoned"):
            sub = [r for r in primary if r["kind"] == "proposal" and r["arm"] == arm]
            for task, row in zip(plan["tasks"], sub):
                if row["valid_proposal"]:
                    continue
                c = ReviewContract.from_dict(task["contract"])
                for mode in fixtures.MODES:
                    state, receipt = commit_frame(c.base, c, row["complete_frame"], ApprovalRegistry())
                    assert not receipt["admitted"] and state == c.base
                    invalid_commits += 1
        reasoning = [r for r in primary if r["kind"] == "proposal" and r["arm"] == "reasoned"]
        recovered = []; commits = owl_n = 0
        for task, raw in zip(plan["tasks"], reasoning):
            c = ReviewContract.from_dict(task["contract"])
            try:
                frame, obj, fenced = normalize(name, raw["raw_response"]); error = None
            except ValueError as exc:
                frame, obj, fenced, error = None, None, False, str(exc)
            candidate, reviews = latent.evaluate(c, obj)
            if candidate is not None:
                independent = reference_candidate(c, obj)
                assert candidate == independent
                assert crosscheck_ontology(candidate, c.public_classes)["matches"]; owl_n += 1
                detected = probed_expansion(c, candidate)
                for mode in fixtures.MODES:
                    registry = fixtures.registry(c, candidate, mode)
                    expected = reference_review(c, candidate, registry)
                    expected["goal_profile_expansion_detected"] = detected
                    expected["goal_profile_admitted"] = expected["goal_satisfied"] and (not detected or expected["exact_approval"])
                    assert all(reviews[mode][k] == expected[k] for k in expected)
                    state, receipt = commit_frame(c.base, c, frame, registry)
                    assert receipt["admitted"] == expected["admitted"]
                    assert state == (candidate if expected["admitted"] else c.base); commits += 1
            recovered.append(dict(task_id=task["task_id"], family=task["family"], proposal=obj, normalized_frame=frame,
                valid_proposal=candidate is not None, candidate=None if candidate is None else candidate.to_dict(),
                normalization_error=error, fence_removed=fenced, hit_cap=raw["hit_cap"], reviews=reviews))
        value = latent.summarize(recovered)
        value["by_family"] = previous.summarize(recovered)["by_family"]
        value.update(fences_removed=sum(r["fence_removed"] for r in recovered), owl_candidates=owl_n, commit_replays=commits)
        modern.write(main / name / "posthoc-normalized-reasoned.json", dict(summary=value, cases=recovered))
        result["models"][name] = dict(checkpoint={k:plan["models"][name][k] for k in ("id", "revision")},
            primary=summary, primary_elapsed_seconds=complete["elapsed_seconds"],
            primary_stronger_baseline={arm: stronger_rows(plan["tasks"], [r for r in primary
                if r["kind"] == "proposal" and r["arm"] == arm]) for arm in ("direct", "reasoned")},
            normalized_reasoned=value, latent_stress=json.loads((stress/name/"summary.json").read_text()),
            additional_invalid_primary_commit_replays=invalid_commits,
            stress_elapsed_seconds=json.loads((stress/name/"completion.json").read_text())["elapsed_seconds"])
    modern.write(main / "combined-results.json", result)
    modern.emit("combined_analysis_complete", destination=str(main / "combined-results.json"))


if __name__ == "__main__":
    analyze()
