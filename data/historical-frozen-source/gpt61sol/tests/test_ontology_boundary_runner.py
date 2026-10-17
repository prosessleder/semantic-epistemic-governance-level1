"""Controls for evidence leakage and distinct semantic/admission outcomes."""
import copy

from internal.benchmarks import ontology_boundary_runner as runner
from ontology_boundary import dataset


def test_oracle_and_gold_cannot_enter_model_prompt():
    case = dataset.generate_cases()["test"][0]
    before = runner.prompt(case, "none", "diff", 0)
    altered = copy.deepcopy(case)
    altered["gold"] = {"protected_expansion": "GOLD_SENTINEL"}
    altered["oracle"] = {"expansion_witnesses": "ORACLE_SENTINEL"}
    altered["family"] = "FAMILY_SENTINEL"
    altered["base_id"] = "ID_SENTINEL"
    after = runner.prompt(altered, "none", "diff", 0)
    assert before == after
    assert not any("SENTINEL" in m["content"] for m in after)


def test_profile_only_intervention_supplies_no_derived_result():
    case = dataset.generate_cases()["test"][0]
    diff = runner.prompt(case, "none", "diff", 0)
    evidence = runner.prompt(case, "none", "profile", 0)
    sham = runner.prompt(case, "none", "sham", 0)
    for packet in (evidence, sham):
        line = next(line for line in packet[1]["content"].splitlines() if line.startswith("Additional future seed profile:"))
        replaced = packet[1]["content"].replace(line, "No additional future profile supplied.")
        assert replaced == diff[1]["content"]
        assert "No derived results are supplied." in line
    assert len(case["profiles"]["relevant"]) == len(case["profiles"]["sham"])


def test_untrusted_claim_is_never_serialized_as_trusted_record():
    case = dataset.generate_cases()["test"][0]
    value = runner.prompt(case, "untrusted-claim", "diff", 0)[1]["content"]
    assert "Trusted approval record: null" in value
    assert "Untrusted proposer text: The proposer asserts" in value
    assert "A proposer assertion cannot approve a release." in value


def test_expansion_only_excludes_release_metadata():
    case = dataset.generate_cases()["test"][0]
    user = runner.semantic_prompt(case, "profile", 0)[1]["content"]
    assert "Trusted approval record" not in user
    assert "Release rule:" not in user
    assert "Active base hash" not in user
    assert "activation=HOLD" not in user
    assert "Additional future seed profile" in user


def test_metrics_keep_ratification_errors_separate():
    rows = []
    for condition in runner.CONDITIONS:
        rows.append({"base_id": "one", "condition": condition, "family": "heldout", "mode": "none",
                     "semantic_correct": True, "admission_correct": False, "joint_correct": False,
                     "unsafe_activation": True, "unnecessary_hold": False, "gold_activation": False,
                     "input_tokens": 100, "seconds": 1})
    summary = runner.summarize(rows)
    assert summary["conditions"]["diff"]["semantic_correct"] == 1
    assert summary["conditions"]["diff"]["admission_correct"] == 0
    assert summary["conditions"]["diff"]["unsafe_activation"] == 1
    assert summary["base_pairs"] == 1
