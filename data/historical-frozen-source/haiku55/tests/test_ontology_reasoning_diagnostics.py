"""Fault injection for the proof checker and semantic name invariance."""
import copy
import json
from pathlib import Path

from internal.benchmarks import ontology_reasoning_diagnostics as diagnostic


def data():
    return json.loads((Path(__file__).resolve().parents[1] / "internal/research/ontology-boundary-dataset.json").read_text())["dataset"]


def test_name_ablation_preserves_both_reference_answers_and_rule_structure():
    contexts = diagnostic.contexts(data())
    assert len(contexts) == 40
    assert len(diagnostic.jobs(contexts)) == 240
    for context in contexts:
        short = diagnostic.renamed(context, "short")
        assert diagnostic.gold(context) == diagnostic.gold(short)
        assert len(diagnostic.rules(context)) == len(diagnostic.rules(short))
        assert diagnostic.verify_trace(short, diagnostic.oracle_trace(context))["valid"]


def test_complete_reference_proofs_are_accepted_in_both_representations():
    for context in diagnostic.contexts(data()):
        for naming in ("opaque", "short"):
            context = diagnostic.renamed(context, naming)
            result = diagnostic.verify_trace(context, diagnostic.oracle_trace(context))
            assert result["valid"]
            assert result["answers"] == diagnostic.gold(context)


def test_incomplete_negative_and_unsupported_positive_certificates_are_rejected():
    cases = {c["motif"]: c for c in diagnostic.microcases()}
    complete = diagnostic.oracle_trace(cases["chain"])
    missing = dict(complete, steps=complete["steps"][:-1])
    assert diagnostic.verify_trace(cases["chain"], missing)["reason"] == "incomplete-closure"
    # The reverse-rule program cannot start its helper from the public seed.
    assert diagnostic.verify_trace(cases["reverse"], {"steps": ["R2"], "derived": True, "effective": True})["reason"] == "unsupported-step"
    # Missing conjuncts cannot be inferred or silently inserted.
    assert diagnostic.verify_trace(cases["and-off"], {"steps": ["R2"], "derived": True, "effective": True})["reason"] == "unsupported-step"


def test_wrong_permission_and_inconsistency_claims_cannot_pass():
    cases = {c["motif"]: c for c in diagnostic.microcases()}
    for name, key in (("other-permission", "derived"), ("active-conflict", "effective")):
        proof = diagnostic.oracle_trace(cases[name])
        proof[key] = not proof[key]
        assert diagnostic.verify_trace(cases[name], proof)["reason"] == "wrong-final-claim"


def test_unknown_redundant_and_malformed_steps_fail_closed():
    case = diagnostic.microcases()[0]
    assert diagnostic.verify_trace(case, {"steps": ["R999"], "derived": True, "effective": True})["reason"] == "unknown-rule"
    assert diagnostic.verify_trace(case, {"steps": ["R1", "R1"], "derived": True, "effective": True})["reason"] == "redundant-step"
    assert diagnostic.parse_trace('{"steps": [], "derived": 1, "effective": true}') is None
    assert diagnostic.parse_trace('{"steps": []') is None
    assert diagnostic.parse_trace('```json\n{"steps": [], "derived": false, "effective": false}\n```') is None


def test_summaries_keep_invalid_answers_in_the_denominator():
    case = diagnostic.microcases()[0]
    row = {"group": "micro", "naming": "short", "endpoint": "trace", "gold": diagnostic.gold(case),
           "prediction": None, "verification": {"valid": False, "reason": "format"}}
    result = diagnostic.summarize([row])["micro"]["short"]["trace"]
    assert result["derived"]["n"] == 1
    assert result["derived"]["correct"] == 0
    assert result["certificates"]["valid"] == 0
