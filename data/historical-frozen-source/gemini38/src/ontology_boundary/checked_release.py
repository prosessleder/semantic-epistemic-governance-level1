"""Untrusted single-edit proposals, exact semantic review and separate approval.

This finite prototype performs no real release or runtime action. The registry
is an independently supplied trusted simulator input, not authentication of
model JSON. No model judgment or cached semantic receipt is accepted as truth.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable

from .oracle import HornRule, Ontology, PERMISSIONS, closure, compare_ontologies, seed_profiles

SEMANTICS = "positive-unary-horn-disjoint-fail-closed-v1"
POLICY = "goal-satisfied-and-no-protected-expansion-or-exact-approval-v1"


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class Goal:
    profile: frozenset[str]
    kind: str
    target: str
    expected: bool = True

    def __post_init__(self):
        if isinstance(self.profile, (str, bytes)):
            raise ValueError("goal profile must be a collection")
        object.__setattr__(self, "profile", frozenset(self.profile))
        if self.kind not in ("class", "derived", "effective") or type(self.expected) is not bool:
            raise ValueError("unsupported goal kind or value")

    def to_dict(self):
        return {"profile": sorted(self.profile), "kind": self.kind, "target": self.target, "expected": self.expected}


@dataclass(frozen=True)
class ReviewContract:
    base: Ontology
    public_classes: frozenset[str]
    protected_permission: str
    goals: tuple[Goal, ...]
    source_task: str = "task-A"
    destination_task: str = "task-B"
    current_profiles: tuple[frozenset[str], ...] = (frozenset({"P0"}),)

    def __post_init__(self):
        if not isinstance(self.base, Ontology) or isinstance(self.public_classes, (str, bytes)):
            raise ValueError("invalid base or public signature")
        object.__setattr__(self, "public_classes", frozenset(self.public_classes))
        object.__setattr__(self, "goals", tuple(self.goals))
        object.__setattr__(self, "current_profiles", tuple(frozenset(p) for p in self.current_profiles))
        seed_profiles(self.public_classes)  # Applies the declared finite bound.
        if not self.public_classes <= self.base.classes or self.protected_permission not in PERMISSIONS:
            raise ValueError("unsupported signature or protected query")
        if not self.goals or not all(isinstance(g, Goal) for g in self.goals):
            raise ValueError("a contract needs independently supplied goals")
        for g in self.goals:
            targets = self.base.classes if g.kind == "class" else frozenset(PERMISSIONS)
            if not g.profile <= self.public_classes or g.target not in targets:
                raise ValueError("goal outside the declared contract")
        if any(not p <= self.public_classes for p in self.current_profiles):
            raise ValueError("current profile outside the declared basis")
        if any(not isinstance(x, str) or not x for x in (self.source_task, self.destination_task)):
            raise ValueError("task identifiers must be nonempty strings")

    def to_dict(self):
        return {"schema_version": 1, "base": self.base.to_dict(), "base_sha256": self.base.sha256,
            "public_classes": sorted(self.public_classes), "protected_permission": self.protected_permission,
            "goals": [g.to_dict() for g in self.goals], "source_task": self.source_task,
            "destination_task": self.destination_task, "current_profiles": [sorted(p) for p in self.current_profiles],
            "semantics": SEMANTICS, "admission_policy": POLICY,
            "mutation_scope": "one-class-edge-rule-or-disjointness-edit; fixed-vocabulary-and-permission-heads"}

    @property
    def sha256(self):
        return digest(self.to_dict())

    @classmethod
    def from_dict(cls, obj):
        contract = cls(Ontology.from_dict(obj["base"]), frozenset(obj["public_classes"]), obj["protected_permission"],
            tuple(Goal(frozenset(g["profile"]), g["kind"], g["target"], g["expected"]) for g in obj["goals"]),
            obj["source_task"], obj["destination_task"], tuple(frozenset(p) for p in obj["current_profiles"]))
        if contract.to_dict() != obj:
            raise ValueError("noncanonical or modified review contract")
        return contract


@dataclass(frozen=True)
class Approval:
    contract_sha256: str
    base_sha256: str
    candidate_sha256: str
    approved: bool = True

    def __post_init__(self):
        hashes = (self.contract_sha256, self.base_sha256, self.candidate_sha256)
        if any(not isinstance(x, str) or len(x) != 64 or any(c not in "0123456789abcdef" for c in x) for x in hashes):
            raise ValueError("approval must bind canonical hashes")
        if type(self.approved) is not bool:
            raise ValueError("approval decision must be Boolean")


@dataclass(frozen=True)
class ApprovalRegistry:
    """Trusted caller-owned register; never constructed from proposal fields."""
    records: tuple[Approval, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "records", tuple(self.records))
        if any(not isinstance(r, Approval) for r in self.records):
            raise ValueError("trusted registry needs typed approval records")

    def matches(self, contract, candidate):
        return any(r.approved and r.contract_sha256 == contract.sha256 and r.base_sha256 == contract.base.sha256
                   and r.candidate_sha256 == candidate.sha256 for r in self.records)


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key")
        obj[key] = value
    return obj


def first_proposal_object(text):
    """First complete object at offset zero; explicit transport framing only.

    Trailing material is returned for logging. No search through prose, syntax
    repair, key insertion, or semantics/approval extraction is performed.
    """
    if not isinstance(text, str) or not text.startswith("{"):
        raise ValueError("proposal frame must start with an object")
    obj, end = json.JSONDecoder(object_pairs_hook=_unique_object).raw_decode(text)
    if type(obj) is not dict:
        raise ValueError("proposal must be an object")
    return obj, text[end:]


def apply_proposal(contract: ReviewContract, proposal: dict) -> Ontology | None:
    if type(proposal) is not dict or not isinstance(proposal.get("op"), str):
        raise ValueError("proposal needs one operation")
    op = proposal["op"]
    if op == "abstain":
        if set(proposal) != {"op"}:
            raise ValueError("unexpected abstention fields")
        return None
    base = contract.base
    edges, rules, disjoint = list(base.subclass), list(base.rules), list(base.disjoint)
    if op in ("add_edge", "remove_edge", "add_disjoint", "remove_disjoint"):
        if set(proposal) != {"op", "left", "right"}:
            raise ValueError("unexpected proposal fields")
        a, b = proposal["left"], proposal["right"]
        if not isinstance(a, str) or not isinstance(b, str) or a not in base.classes or b not in base.classes:
            raise ValueError("edge endpoints must be existing classes; policy heads are immutable")
        container = edges if op.endswith("edge") else disjoint
        item = (a, b) if op.endswith("edge") else tuple(sorted((a, b)))
    elif op in ("add_rule", "remove_rule"):
        if set(proposal) != {"op", "antecedents", "head"}:
            raise ValueError("unexpected rule fields")
        antecedents, head = proposal["antecedents"], proposal["head"]
        if (type(antecedents) is not list or not antecedents or any(not isinstance(a, str) for a in antecedents)
            or len(antecedents) != len(set(antecedents)) or not set(antecedents) <= base.classes
            or not isinstance(head, str) or head not in base.classes):
            raise ValueError("rule must use existing classes, unique antecedents and a fixed-vocabulary head")
        container, item = rules, HornRule(frozenset(antecedents), head)
    else:
        raise ValueError("unsupported operation")
    if op.startswith("add_"):
        if item in container:
            raise ValueError("edit adds an already present item")
        container.append(item)
    else:
        if item not in container:
            raise ValueError("edit removes an absent item")
        container.remove(item)
    return Ontology(base.classes, tuple(edges), tuple(rules), tuple(disjoint))


def goals_satisfied(contract, candidate):
    outcomes = []
    for goal in contract.goals:
        state = closure(candidate, goal.profile)
        atoms = state.class_types if goal.kind == "class" else (state.derived_permissions if goal.kind == "derived" else state.permissions)
        outcomes.append((goal.target in atoms) == goal.expected)
    return all(outcomes)


def review_proposal(contract, proposal, registry=ApprovalRegistry()):
    if not isinstance(contract, ReviewContract) or not isinstance(registry, ApprovalRegistry):
        raise ValueError("contract and trusted registry must be supplied independently")
    binding = {"contract_sha256": contract.sha256, "base_sha256": contract.base.sha256}
    try:
        candidate = apply_proposal(contract, proposal)
    except (ValueError, TypeError) as error:
        return dict(binding, decision="ABSTAIN", reason="invalid-proposal", detail=str(error), valid_proposal=False,
                    goal_satisfied=False, admitted=False)
    if candidate is None:
        return dict(binding, decision="ABSTAIN", reason="model-abstained", valid_proposal=False,
                    goal_satisfied=False, admitted=False)
    certificate = compare_ontologies(contract.base, candidate, contract.public_classes,
        protected_permissions=[contract.protected_permission], current_probes=contract.current_profiles)
    met = goals_satisfied(contract, candidate)
    expansion = not certificate["protected_no_expansion"]
    approved = registry.matches(contract, candidate)
    authorized = not expansion or approved
    admitted = met and authorized
    reason = "goal-not-satisfied" if not met else ("expansion-needs-approval" if not authorized else "authorized")
    return dict(binding, candidate_sha256=candidate.sha256, valid_proposal=True, goal_satisfied=met,
        protected_expansion=expansion, exact_approval=approved, authorized=authorized, admitted=admitted,
        decision="ADMIT" if admitted else "HOLD", reason=reason, certificate=certificate)


def commit_simulated(current, contract, proposal, registry=ApprovalRegistry()):
    """Recompute against the current base; returns state, performs no I/O/action."""
    if not isinstance(current, Ontology):
        raise ValueError("current state must be a validated ontology")
    if current.sha256 != contract.base.sha256:
        return current, {"decision": "HOLD", "admitted": False, "reason": "stale-base-at-commit"}
    receipt = review_proposal(contract, proposal, registry)
    return (apply_proposal(contract, proposal) if receipt["admitted"] else current), receipt
