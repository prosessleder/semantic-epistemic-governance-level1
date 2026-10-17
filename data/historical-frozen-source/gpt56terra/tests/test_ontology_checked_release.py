"""Positive utility, scoped authority, immutable policy and commit revalidation."""
import copy
from dataclasses import replace
import pytest

from ontology_boundary.checked_release import (
    Approval, ApprovalRegistry, Goal, ReviewContract, apply_proposal,
    commit_simulated, first_proposal_object, review_proposal,
)
from internal.benchmarks.ontology_checked_proposals import tasks, registry, MODES, messages


@pytest.fixture(scope="module")
def fixtures():
    return tasks()


def selected(fixtures, family):
    task = next(t for t in fixtures if t["family"] == family)
    return ReviewContract.from_dict(task["contract"]), task["reference_patch"]


def test_reference_tasks_have_positive_utility_and_do_not_reduce_to_constant_hold(fixtures):
    count = {True: 0, False: 0}
    for task in fixtures:
        contract = ReviewContract.from_dict(task["contract"])
        patch = task["reference_patch"]
        candidate = apply_proposal(contract, patch)
        assert candidate.to_dict() == task["reference_candidate"]
        none = review_proposal(contract, patch)
        assert none["goal_satisfied"]
        assert none["certificate"]["coverage"]["enumerated_profiles"] == 16
        assert none["certificate"]["current_probes_unchanged"]
        count[none["protected_expansion"]] += 1
        for mode in MODES:
            receipt = review_proposal(contract, patch, registry(contract, candidate, mode))
            assert receipt["admitted"] == (not none["protected_expansion"] or mode == "exact")
    assert count == {True: 16, False: 16}


def test_correct_goal_is_evidence_and_not_release_authority(fixtures):
    contract, patch = selected(fixtures, "disjointness-repair")
    receipt = review_proposal(contract, patch)
    assert receipt["goal_satisfied"] and receipt["protected_expansion"]
    assert receipt["decision"] == "HOLD"
    assert receipt["reason"] == "expansion-needs-approval"


def test_conjunction_can_pass_current_and_singleton_checks_but_requires_approval(fixtures):
    contract, patch = selected(fixtures, "protected-conjunction")
    receipt = review_proposal(contract, patch)
    assert receipt["certificate"]["current_probes_unchanged"]
    witnesses = receipt["certificate"]["expansion_witnesses"][contract.protected_permission]
    assert witnesses and all(len(p) == 2 for p in witnesses)
    assert not receipt["admitted"]


@pytest.mark.parametrize("extra", ["approval", "protected_permission", "public_classes", "base_sha256", "certificate", "goal", "decision"])
def test_model_cannot_supply_authority_query_basis_or_cached_verdict(fixtures, extra):
    contract, patch = selected(fixtures, "protected-edge")
    proposal = dict(patch, **{extra: True})
    assert review_proposal(contract, proposal)["reason"] == "invalid-proposal"


@pytest.mark.parametrize("proposal", [
    {"op":"add_edge", "left":"P1", "right":"can_write_metadata"},
    {"op":"add_edge", "left":"NewAdmin", "right":"H0"},
    {"op":"set_public_basis", "classes":["P0"]},
    {"op":"add_rule", "antecedents":["P1","P1"], "head":"H0"},
    {"op":"add_rule", "antecedents":[], "head":"H0"},
    {"op":"add_rule", "antecedents":["P1"], "head":"can_write_metadata"},
    {"op":"add_edge", "left":1, "right":"H0"},
])
def test_unknown_vocabulary_policy_heads_and_malformed_operations_abstain(fixtures, proposal):
    contract, _ = selected(fixtures, "protected-edge")
    receipt = review_proposal(contract, proposal)
    assert not receipt["admitted"] and not receipt["valid_proposal"]


def test_registry_rejects_stale_candidate_query_basis_scope_and_denial(fixtures):
    contract, patch = selected(fixtures, "protected-edge")
    candidate = apply_proposal(contract, patch)
    for mode in MODES:
        receipt = review_proposal(contract, patch, registry(contract, candidate, mode))
        assert receipt["exact_approval"] == (mode == "exact")
    with pytest.raises(ValueError):
        review_proposal(contract, patch, {"approved":True})


def test_goal_contract_is_also_bound_to_approval(fixtures):
    contract, patch = selected(fixtures, "protected-edge")
    candidate = apply_proposal(contract, patch)
    altered = replace(contract, goals=(replace(contract.goals[0], expected=False),))
    old = ApprovalRegistry((Approval(altered.sha256, contract.base.sha256, candidate.sha256),))
    assert not review_proposal(contract, patch, old)["admitted"]


def test_safe_but_useless_proposal_is_held_and_abstention_is_not_success(fixtures):
    contract, _ = selected(fixtures, "body-edge")
    unused = next(h for h in contract.base.classes if h.startswith("H") and all(h != r for _,r in contract.base.subclass))
    receipt = review_proposal(contract, {"op":"add_edge", "left":"P0", "right":unused})
    assert receipt["valid_proposal"] and not receipt["goal_satisfied"] and not receipt["admitted"]
    assert review_proposal(contract, {"op":"abstain"})["decision"] == "ABSTAIN"


def test_commit_revalidates_current_base_and_never_uses_a_cached_receipt(fixtures):
    contract, patch = selected(fixtures, "body-edge")
    changed, first = commit_simulated(contract.base, contract, patch)
    assert first["admitted"] and changed.sha256 != contract.base.sha256
    unchanged, second = commit_simulated(changed, contract, patch)
    assert unchanged == changed
    assert second == {"decision":"HOLD", "admitted":False, "reason":"stale-base-at-commit"}


def test_transport_frame_rejects_duplicate_keys_and_never_searches_prose():
    with pytest.raises(ValueError):
        first_proposal_object('{"op":"abstain","op":"add_edge"}')
    with pytest.raises(ValueError):
        first_proposal_object('Explanation: {"op":"abstain"}')
    obj, trailing = first_proposal_object('{"op":"abstain"}\nAdditional prose')
    assert obj == {"op":"abstain"} and trailing == '\nAdditional prose'


def test_contract_serialization_cannot_silently_change_bound_semantics(fixtures):
    contract, _ = selected(fixtures, "body-edge")
    raw = contract.to_dict()
    raw["semantics"] = "ignore-disjointness"
    with pytest.raises(ValueError):
        ReviewContract.from_dict(raw)


def test_oracle_patches_labels_and_task_ids_never_change_the_model_request(fixtures):
    for task in fixtures:
        altered = copy.deepcopy(task)
        altered["reference_patch"] = {"op":"fake-approval"}
        altered["reference_candidate"] = {"protected_expansion":True}
        altered["family"] = "oracle-label"
        altered["task_id"] = "oracle-id"
        assert messages(altered) == messages(task)
