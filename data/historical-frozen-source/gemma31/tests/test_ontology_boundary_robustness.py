"""Meaningful checks of the new information intervention and measurement controls."""
import copy
import json
from pathlib import Path
from collections import Counter

import pytest

from internal.benchmarks import ontology_boundary_robustness as followup
from internal.benchmarks import ontology_boundary_runner as original


@pytest.fixture(scope="module")
def data():
    path = Path(__file__).resolve().parents[1] / "internal/research/ontology-boundary-dataset.json"
    return json.loads(path.read_text())["dataset"]


def test_verified_is_the_same_request_plus_facts(data):
    for case in data["dev"] + data["test"]:
        table = followup.render_certificate(followup.certificate(case)) + "\n\n"
        for task, mode in [("semantic", "none")] + [("joint", m) for m in original.MODES]:
            raw = followup.review_prompt(case, "raw", task, mode)
            verified = followup.review_prompt(case, "verified", task, mode)
            assert raw[0] == verified[0]
            assert verified[1]["content"].replace(table, "", 1) == raw[1]["content"]
            assert "NOT release approval" in table
            assert "AT LEAST ONE" in raw[1]["content"]


def test_legacy_prompt_contents_are_unchanged(data):
    for case in data["dev"] + data["test"]:
        assert followup.review_prompt(case, "legacy", "semantic") == original.semantic_prompt(case, "diff", 0)
        for mode in original.MODES:
            assert followup.review_prompt(case, "legacy", "joint", mode) == original.prompt(case, mode, "diff", 0)


def test_cached_verdicts_never_enter_new_prompts(data):
    case = data["test"][0]
    altered = copy.deepcopy(case)
    for key in ("gold", "oracle", "family", "base_id"):
        altered[key] = "POISONED_METADATA"
    for arm in followup.ARMS:
        for task in ("semantic", "joint"):
            assert followup.review_prompt(case, arm, task) == followup.review_prompt(altered, arm, task)
    for query in followup.QUERIES:
        assert followup.local_prompt(case, "old", "relevant", query, 0) == followup.local_prompt(altered, "old", "relevant", query, 0)


def test_certificate_binds_every_fact_and_version(data):
    case = data["test"][0]
    cert = followup.certificate(case)
    assert followup.verify_certificate(case, cert)
    assert len(cert["profiles"]) == 16
    for mutation in ("base_sha256", "permission", "public_classes", "profiles"):
        altered = copy.deepcopy(cert)
        altered[mutation] = None
        assert not followup.verify_certificate(case, altered)
    altered = copy.deepcopy(cert)
    altered["profiles"][0]["new"]["effective"] = not altered["profiles"][0]["new"]["effective"]
    assert not followup.verify_certificate(case, altered)


def test_repair_control_distinguishes_derivation_from_permission(data):
    case = next(c for c in data["test"] if c["family"] == "disjointness-repair" and c["gold"]["protected_expansion"])
    job = {"task": "local", "side": "old", "role": "relevant", "query": "derived"}
    assert followup.truth(case, job) is True
    assert followup.truth(case, dict(job, query="effective")) is False


def test_all_cells_and_balanced_local_encodings(data):
    for split, expected in (("dev", 160), ("test", 960)):
        tasks = followup.jobs(data[split])
        assert len(tasks) == expected
        assert len({j["job_id"] for j in tasks}) == expected
        cases = {c["base_id"]: c for c in data[split]}
        counts = Counter()
        for job in tasks:
            if job["task"] == "local":
                truth = followup.truth(cases[job["base_id"]], job)
                book = followup.codebook(cases[job["base_id"]], job)
                code = next(code for code, v in book.items() if v == truth)
                counts[job["query"], truth, code] += 1
        for query in followup.QUERIES:
            for truth in (False, True):
                assert counts[query, truth, "A"] == counts[query, truth, "B"]


def test_metrics_keep_component_failure_and_encoding_instability_visible(data):
    cases = {c["base_id"]: c for c in data["dev"]}
    rows = []
    for job in followup.jobs(data["dev"]):
        case = cases[job["base_id"]]
        truth = followup.truth(case, job)
        book = followup.codebook(case, job)
        key = "/".join(str(job.get(k, "")) for k in ("base_id", "task", "mode", "side", "role", "query"))
        row = dict(job, job_key=key, gold=truth, prediction=truth, correct=True,
                   gold_code=next(k for k, v in book.items() if v == truth))
        if job["task"] == "joint":
            row["exact_approval"] = job["mode"] == "valid"
        rows.append(row)
    target = next(r for r in rows if r["task"] == "semantic" and r["arm"] == "verified" and r["gold"])
    target.update(prediction=False, correct=False)
    target = next(r for r in rows if r["task"] == "local" and r["query"] == "derived")
    target.update(prediction=not target["gold"], correct=False)
    result = followup.summarize(rows)
    assert result["review"]["verified"]["admission_correct"] == 28
    assert result["semantic_then_exact_approval"]["verified"]["unsafe"] == 6
    assert result["semantic_then_exact_approval"]["verified"]["correct"] == 22
    assert result["paired"]["semantic"] == {"n": 4, "rescues": 0, "harms": 1}
    assert result["controls"]["derived"]["encoding_disagreements"] == 1
    assert result["controls"]["effective"]["balanced_accuracy"] == 1
