"""Native-field diagnostic removes code mapping without changing semantic gold."""
import copy
import json
from pathlib import Path

import pytest
from internal.scripts import run_ontology_boundary_native_boolean as native
from internal.benchmarks import ontology_boundary_robustness as coded


@pytest.fixture(scope="module")
def data():
    return json.loads((Path(__file__).resolve().parents[1] / "internal/research/ontology-boundary-dataset.json").read_text())["dataset"]


def test_every_case_and_control_is_retained(data):
    jobs = native.tasks(data)
    assert len(jobs) == 280
    assert len({j["job_id"] for j in jobs}) == 280
    assert sum(j["split"] == "dev" for j in jobs) == 40
    assert sum(j["split"] == "test" for j in jobs) == 240


def test_letter_mapping_has_no_effect_on_native_request(data):
    cases = {c["base_id"]: c for split in ("dev", "test") for c in data[split]}
    for job in native.tasks(data):
        case = cases[job["base_id"]]
        altered = copy.deepcopy(case)
        altered["encoding_index"] += 1
        packet = native.messages(case, job)
        assert packet == native.messages(altered, job)
        assert all("Code mapping:" not in p["content"] for p in packet)
        assert 'native Boolean value' in packet[1]["content"]


def test_new_representation_preserves_reference_truth(data):
    cases = {c["base_id"]: c for split in ("dev", "test") for c in data[split]}
    for job in native.tasks(data):
        case = cases[job["base_id"]]
        reference_job = dict(job, variant=0) if job["task"] == "local" else job
        assert native.gold(case, job) == coded.truth(case, reference_job)


def test_native_verified_is_only_additional_facts(data):
    for case in data["dev"] + data["test"]:
        job = {"task": "semantic", "arm": "raw"}
        raw = native.messages(case, job)
        verified = native.messages(case, dict(job, arm="verified"))
        table = coded.render_certificate(coded.certificate(case)) + "\n\n"
        assert raw[0] == verified[0]
        assert verified[1]["content"].replace(table, "", 1) == raw[1]["content"]


def test_pipeline_requires_correct_semantics_even_with_exact_authority(data):
    cases = {c["base_id"]: c for c in data["dev"]}
    rows = []
    for job in native.tasks(data):
        if job["split"] != "dev":
            continue
        truth = native.gold(cases[job["base_id"]], job)
        rows.append(dict(job, gold=truth, prediction=truth, correct=True))
    row = next(r for r in rows if r["task"] == "semantic" and r["arm"] == "verified" and r["gold"])
    row.update(prediction=False, correct=False)
    result = native.summarize(rows, cases)
    assert result["pipeline"]["raw"]["correct"] == 28
    assert result["pipeline"]["verified"]["unsafe"] == 6
    assert result["pipeline"]["verified"]["correct"] == 22
    assert result["paired"] == {"n": 4, "rescues": 0, "harms": 1}
    assert result["controls"]["derived"]["balanced_accuracy"] == 1
