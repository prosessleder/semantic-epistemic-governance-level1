"""Snapshot an immutable proposal frame before simulated commit.

The frozen study's object API is preserved. This integration entry point parses
an immutable string into privately owned data and returns the candidate captured
before review, checking its hash against the fresh receipt. It performs no I/O.
"""
from .checked_release import (
    ApprovalRegistry, ReviewContract, apply_proposal, first_proposal_object, review_proposal,
)
from .oracle import Ontology


def commit_frame(current: Ontology, contract: ReviewContract, proposal_frame: str,
                 registry: ApprovalRegistry = ApprovalRegistry()):
    if not isinstance(current, Ontology) or not isinstance(contract, ReviewContract) or not isinstance(registry, ApprovalRegistry):
        raise ValueError("current state, contract and registry are independently validated inputs")
    if current.sha256 != contract.base.sha256:
        return current, {"decision": "HOLD", "admitted": False, "reason": "stale-base-at-commit"}
    try:
        proposal, trailing = first_proposal_object(proposal_frame)
    except ValueError as error:
        return current, {"decision": "ABSTAIN", "admitted": False, "reason": "invalid-frame", "detail": str(error)}
    try:
        candidate = apply_proposal(contract, proposal)
    except (ValueError, TypeError):
        candidate = None
    receipt = review_proposal(contract, proposal, registry)
    receipt["trailing_frame_text"] = trailing
    if not receipt["admitted"]:
        return current, receipt
    if candidate is None or candidate.sha256 != receipt["candidate_sha256"]:
        return current, {"decision": "HOLD", "admitted": False, "reason": "candidate-binding-mismatch"}
    # Do not reapply caller-owned mutable proposal data after authorization.
    return candidate, receipt
