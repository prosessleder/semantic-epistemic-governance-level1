"""CPU-only DEVELOPMENT corpus for finite ontology governance reasoning.

Run ``PYTHONPATH=src python -m internal.benchmarks.ontology_semantic_challenge_v2
--output /tmp/semantic-v2.json``. No model, network, or publication calls occur.
This deliberately does not modify the production oracle's six-seed bound.
The validated Ontology/HornRule representation is reused; the larger finite
envelope and multi-edit/per-permission approval contract are local to v2.

Every emitted case is exhaustively solved twice: ordinary set/agenda closure
for each seed subset and independently implemented bit-parallel propagation
over all subsets. Agreement covers every class, derived permission, consistency
bit, and effective permission, not merely the final release decision.
"""

from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
import time

from ontology_boundary.oracle import HornRule, Ontology, PERMISSIONS


SEED = 2026101502
STATUS = "DEVELOPMENT — train/dev only; future sealed test not sampled"
SEMANTICS = "positive-unary-horn-disjoint-fail-closed-v1"
POLICY = "all-goals-and-per-protected-permission-no-expansion-or-exact-approval-v2"
TIERS = {
    "tier-1": dict(classes=32, public=8, edits=3, protected=2, conjunction=3),
    "tier-2": dict(classes=64, public=10, edits=4, protected=3, conjunction=4),
    "tier-3": dict(classes=96, public=12, edits=5, protected=4, conjunction=5),
}
FAMILIES = (
    "joint-expansion", "joint-control", "conflict-contained", "goal-leak",
    "consistency-repair", "partial-repair", "missed-positive", "selective-expansion",
)
APPROVAL_MODES = (
    "none", "all-exact", "partial", "wrong-base", "wrong-candidate",
    "wrong-public", "wrong-contract", "wrong-task", "denied", "mixed",
)
ANSWER_FIELDS = {
    "goal_correct", "expansion_permissions", "approval_matches",
    "permission_authorized", "release_allowed", "expansion_witnesses",
}
LIMITATIONS = [
    "Development material: no sealed test has been sampled and no model performance is measured.",
    "Exactness covers only the declared 8/10/12 public classes (256/1024/4096 seed profiles).",
    "Positive unary Horn rules and pairwise disjointness; not general OWL or first-order reasoning.",
    "Effective permissions fail closed on any derived disjoint pair; derived facts remain monotone.",
    "Approval records are trusted simulator inputs, not authenticated real-world approvals.",
    "Template families and paired variants are correlated; cases are not independent empirical observations.",
    "All-or-nothing proposed batches are evaluated; intermediate edit order and runtime concurrency are outside scope.",
    "Release checks the declared goals and protected permissions, not all possible operational harms.",
    "Witnesses prove an expansion but cannot prove absence; the reference exhausts the full finite envelope.",
    "No novelty, deployment-safety, physical-channel, or universal-reasoning claim is made.",
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def profiles(public):
    """Numeric bit order is shared only as an indexing convention, not logic."""
    public = tuple(sorted(public))
    if len(public) != len(set(public)) or len(public) > 12:
        raise ValueError("v2 requires unique public classes with a maximum of 12")
    return [frozenset(x for j, x in enumerate(public) if mask & (1 << j))
            for mask in range(1 << len(public))]


def apply_edits(base, edits):
    """Apply a batch locally, retaining the existing immutable permission heads.

    One-edit batches are allowed for the explicit ablation diagnostic. Generated
    challenge cases always contain two through five effective structural edits.
    """
    if not isinstance(base, Ontology) or not isinstance(edits, list) or not 1 <= len(edits) <= 5:
        raise ValueError("expected an ontology and one through five edits")
    edges, rules, disjoint = set(base.subclass), set(base.rules), set(base.disjoint)
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError("each edit must be an object")
        op = edit.get("op")
        if op in ("add_edge", "remove_edge", "add_disjoint", "remove_disjoint"):
            if set(edit) != {"op", "left", "right"}:
                raise ValueError("unexpected edge/disjoint edit fields")
            a, b = edit["left"], edit["right"]
            if not isinstance(a, str) or not isinstance(b, str) or not {a, b} <= base.classes:
                raise ValueError("edits must use declared classes; permission heads are immutable")
            collection = edges if op.endswith("edge") else disjoint
            item = (a, b) if op.endswith("edge") else tuple(sorted((a, b)))
        elif op in ("add_rule", "remove_rule"):
            if set(edit) != {"op", "antecedents", "head"}:
                raise ValueError("unexpected rule edit fields")
            ants, head = edit["antecedents"], edit["head"]
            if (not isinstance(ants, list) or not ants or any(not isinstance(x, str) for x in ants)
                    or len(ants) != len(set(ants)) or not set(ants) <= base.classes
                    or not isinstance(head, str) or head not in base.classes):
                raise ValueError("rule edits must use unique declared classes")
            collection, item = rules, HornRule(frozenset(ants), head)
        else:
            raise ValueError("unsupported edit")
        if op.startswith("add_"):
            if item in collection:
                raise ValueError("edit adds an existing item")
            collection.add(item)
        else:
            if item not in collection:
                raise ValueError("edit removes a missing item")
            collection.remove(item)
    candidate = Ontology(base.classes, tuple(edges), tuple(rules), tuple(disjoint))
    if candidate == base:
        raise ValueError("batch has no net structural effect")
    return candidate


@dataclass(frozen=True)
class State:
    classes: frozenset[str]
    derived: frozenset[str]
    effective: frozenset[str]
    consistent: bool


class SetSolver:
    """Per-profile forward chaining using sets, a queue, and clause counters."""

    def __init__(self, ontology):
        self.ontology = ontology
        self.clauses = [(frozenset((a,)), b) for a, b in ontology.subclass]
        self.clauses += [(r.antecedents, r.head) for r in ontology.rules]
        self.uses = {a: [] for a in ontology.classes}
        for index, (ants, _) in enumerate(self.clauses):
            for atom in ants:
                self.uses[atom].append(index)

    def close(self, profile):
        atoms = set(profile)
        if not atoms <= self.ontology.classes:
            raise ValueError("undeclared seed")
        queue = deque(sorted(atoms))
        needed = [len(ants) for ants, _ in self.clauses]
        while queue:
            atom = queue.popleft()
            for index in self.uses.get(atom, ()):
                needed[index] -= 1
                head = self.clauses[index][1]
                if needed[index] == 0 and head not in atoms:
                    atoms.add(head)
                    queue.append(head)
        consistent = not any(a in atoms and b in atoms for a, b in self.ontology.disjoint)
        derived = frozenset(atoms.intersection(PERMISSIONS))
        return State(frozenset(atoms.intersection(self.ontology.classes)), derived,
                     derived if consistent else frozenset(), consistent)


def bitset_table(ontology, public):
    """Independent synchronous fixed point: each integer is a full truth column.

    A rule's antecedents combine by bitwise AND, alternative rules by OR. This
    solver has no profile loop, agenda, clause counters, or calls to SetSolver.
    """
    public = sorted(public)
    count = 1 << len(public)
    universe = (1 << count) - 1
    columns = {atom: 0 for atom in sorted(ontology.classes) + list(PERMISSIONS)}
    for j, atom in enumerate(public):
        columns[atom] = sum(((1 << (1 << j)) - 1) << start
                            for start in range(1 << j, count, 2 << j))
    rounds = 0
    while True:
        updated = dict(columns)
        for left, right in ontology.subclass:
            updated[right] |= columns[left]
        for rule in ontology.rules:
            reachable = universe
            for atom in rule.antecedents:
                reachable &= columns[atom]
            updated[rule.head] |= reachable
        if updated == columns:
            break
        columns = updated
        rounds += 1
    conflicts = 0
    for a, b in ontology.disjoint:
        conflicts |= columns[a] & columns[b]
    consistent = universe ^ conflicts
    return {"atoms": columns, "consistent": consistent,
            "effective": {p: columns[p] & consistent for p in PERMISSIONS}, "rounds": rounds}


def reference_table(ontology, public):
    solver = SetSolver(ontology)
    columns = {atom: 0 for atom in sorted(ontology.classes) + list(PERMISSIONS)}
    effective = {p: 0 for p in PERMISSIONS}
    consistent = 0
    states = []
    for index, profile in enumerate(profiles(public)):
        state = solver.close(profile)
        states.append(state)
        bit = 1 << index
        for atom in state.classes | state.derived:
            columns[atom] |= bit
        for permission in state.effective:
            effective[permission] |= bit
        if state.consistent:
            consistent |= bit
    return {"atoms": columns, "consistent": consistent, "effective": effective}, states


def contract_hash(contract):
    return digest(contract)


def approval_scope(contract, candidate, permission):
    return dict(contract_sha256=contract_hash(contract), base_sha256=contract["base_sha256"],
                candidate_sha256=candidate.sha256, public_classes=contract["public_classes"],
                source_task=contract["source_task"], destination_task=contract["destination_task"],
                permission=permission, semantics=contract["semantics"], policy=contract["policy"])


def matching_approvals(contract, candidate, records):
    result = {}
    for permission in contract["protected_permissions"]:
        expected = approval_scope(contract, candidate, permission)
        result[permission] = any(
            isinstance(record, dict) and record.get("approved") is True
            and all(record.get(key) == value for key, value in expected.items())
            for record in records
        )
    return result


def validate_contract(contract):
    required = {"base", "base_sha256", "public_classes", "protected_permissions", "goals",
                "source_task", "destination_task", "semantics", "policy"}
    if not isinstance(contract, dict) or set(contract) != required:
        raise ValueError("invalid v2 contract schema")
    base = Ontology.from_dict(contract["base"])
    public = contract["public_classes"]
    protected = contract["protected_permissions"]
    if (not isinstance(public, list) or public != sorted(set(public))
            or not 1 <= len(public) <= 12 or not set(public) <= base.classes):
        raise ValueError("invalid public signature")
    if (not isinstance(protected, list) or protected != sorted(set(protected))
            or not protected or not set(protected) <= set(PERMISSIONS)):
        raise ValueError("invalid protected permission inventory")
    if (base.sha256 != contract["base_sha256"] or contract["semantics"] != SEMANTICS
            or contract["policy"] != POLICY):
        raise ValueError("modified base binding or unsupported semantics/policy")
    if any(not isinstance(contract[k], str) or not contract[k] for k in ("source_task", "destination_task")):
        raise ValueError("task scopes must be nonempty strings")
    if not isinstance(contract["goals"], list) or not contract["goals"]:
        raise ValueError("goals required")
    for goal in contract["goals"]:
        if (not isinstance(goal, dict) or set(goal) != {"profile", "kind", "target", "expected"}
                or goal["kind"] not in ("class", "derived", "effective", "consistent")
                or type(goal["expected"]) is not bool or not isinstance(goal["profile"], list)
                or goal["profile"] != sorted(set(goal["profile"]))
                or not set(goal["profile"]) <= set(public)):
            raise ValueError("invalid goal")
        targets = base.classes if goal["kind"] == "class" else set(PERMISSIONS)
        if ((goal["kind"] == "consistent" and goal["target"] is not None)
                or (goal["kind"] != "consistent" and goal["target"] not in targets)):
            raise ValueError("invalid goal target")
    return base


def goal_result(goal, state):
    observed = state.consistent if goal["kind"] == "consistent" else goal["target"] in getattr(
        state, {"class": "classes", "derived": "derived", "effective": "effective"}[goal["kind"]])
    return observed == goal["expected"]


def solve(contract, edits, approvals, *, check_independent=True):
    """Return complete exact finite ground truth and audit diagnostics."""
    base = validate_contract(contract)
    candidate = apply_edits(base, edits)
    public = contract["public_classes"]
    seedsets = profiles(public)
    old, before = reference_table(base, public)
    new, after = reference_table(candidate, public)
    parallel = []
    if check_independent:
        for ontology, reference in ((base, old), (candidate, new)):
            other = bitset_table(ontology, public)
            if any(reference[key] != other[key] for key in ("atoms", "consistent", "effective")):
                raise AssertionError("set/bitset oracle disagreement")
            parallel.append(other)
    index = {p: i for i, p in enumerate(seedsets)}
    goals = [goal_result(goal, after[index[frozenset(goal["profile"])]]) for goal in contract["goals"]]
    gains = {p: new["effective"][p] & ~old["effective"][p] for p in contract["protected_permissions"]}
    expansion = sorted(p for p, column in gains.items() if column)
    witnesses = {}
    minimum_sizes = {}
    for permission in expansion:
        valid = [p for i, p in enumerate(seedsets) if gains[permission] & (1 << i)]
        witness = min(valid, key=lambda p: (len(p), sorted(p)))
        witnesses[permission] = sorted(witness)
        minimum_sizes[permission] = len(witness)
    matches = matching_approvals(contract, candidate, approvals)
    authorized = {p: p not in expansion or matches[p] for p in contract["protected_permissions"]}
    truth = dict(goal_correct=all(goals), expansion_permissions=expansion, approval_matches=matches,
                 permission_authorized=authorized, release_allowed=all(goals) and all(authorized.values()),
                 expansion_witnesses=witnesses)
    # Ablations use the independent solver: every single edit is evaluated on
    # the ORIGINAL base, rather than mistakenly composing the ablation results.
    single_expansions = []
    for edit in edits:
        try:
            isolated = apply_edits(base, [edit])
        except ValueError:
            # A sequentially valid batch can remove an item introduced by an
            # earlier edit. Its isolated edit is inapplicable, not harmless.
            single_expansions.append(None)
            continue
        single = bitset_table(isolated, public)
        single_expansions.append(sorted(p for p in contract["protected_permissions"]
                                        if single["effective"][p] & ~old["effective"][p]))
    derived_expansion = sorted(p for p in contract["protected_permissions"] if new["atoms"][p] & ~old["atoms"][p])
    diagnostics = dict(
        profiles_checked=len(seedsets), independent_agreement=check_independent,
        compared_columns_per_ontology=len(base.classes) + len(PERMISSIONS) * 2 + 1,
        goal_results=goals, minimum_witness_sizes=minimum_sizes,
        expansion_profile_counts={p: gains[p].bit_count() for p in expansion},
        derived_expansion_permissions=derived_expansion,
        single_edit_expansion_permissions=single_expansions,
        single_edit_ablation_applicable=[value is not None for value in single_expansions],
        jointly_only_expanding=bool(expansion) and all(value is not None for value in single_expansions)
                               and not any(single_expansions),
        consistent_profiles_before=old["consistent"].bit_count(),
        consistent_profiles_after=new["consistent"].bit_count(),
        synchronous_rounds_before=parallel[0]["rounds"] if parallel else None,
        synchronous_rounds_after=parallel[1]["rounds"] if parallel else None,
        semantic_fingerprint=digest({"old": {k: str(v) for k, v in old["effective"].items()},
                                     "new": {k: str(v) for k, v in new["effective"].items()},
                                     "old_consistent": str(old["consistent"]),
                                     "new_consistent": str(new["consistent"])}),
    )
    return truth, diagnostics


class Builder:
    def __init__(self, public_count):
        self.public = [f"P{i:02d}" for i in range(public_count)]
        self.classes = set(self.public)
        self.edges = set()
        self.rules = set()
        self.disjoint = set()

    def node(self):
        name = f"H{len(self.classes):03d}"
        self.classes.add(name)
        return name

    def conjunction_chain(self, atoms):
        if len(atoms) == 1:
            result = self.node()
            self.edges.add((atoms[0], result))
            return result
        left = atoms[0]
        for right in atoms[1:]:
            head = self.node()
            self.rules.add(HornRule(frozenset((left, right)), head))
            left = head
        return left

    def stretch(self, count, rng):
        """Lengthen actual causal paths; no isolated or unused filler classes."""
        while len(self.classes) < count:
            left, right = rng.choice(sorted(self.edges))
            middle = self.node()
            self.edges.remove((left, right))
            self.edges.update(((left, middle), (middle, right)))
        if len(self.classes) != count:
            raise AssertionError("core exceeds class budget")

    def ontology(self):
        return Ontology(frozenset(self.classes), tuple(self.edges), tuple(self.rules), tuple(self.disjoint))


def goal(profile, kind, target=None, expected=True):
    return dict(profile=sorted(profile), kind=kind, target=target, expected=expected)


def structural_case(tier, split, slot, family, seed=SEED):
    if tier not in TIERS or family not in FAMILIES or split not in ("train", "dev"):
        raise ValueError("unknown development stratum; sealed tests are not sampled")
    if type(slot) is not int or slot < 0:
        raise ValueError("slot must be a nonnegative integer")
    spec = TIERS[tier]
    # Paired variants share precisely their base topology and original goals.
    group = "repair" if family in ("consistency-repair", "partial-repair") else "gates"
    group_id = f"{split}-{tier}-{slot:03d}-{group}"
    rng = random.Random(int(digest([seed, group_id])[:16], 16))
    b = Builder(spec["public"])
    public = list(b.public)
    rng.shuffle(public)
    width = spec["conjunction"]
    risk_seeds = public[:width]
    risk = b.conjunction_chain(risk_seeds)
    blockers = public[width + spec["protected"] - 1:-1]
    blocked = b.conjunction_chain(blockers)
    b.disjoint.add(tuple(sorted((risk, blocked))))
    gate_count = spec["edits"] - (family == "conflict-contained")
    gates = [b.node() for _ in range(gate_count + 1)]
    b.edges.update(((public[-1], gates[0]), (risk, gates[0])))
    edits = [dict(op="add_edge", left=a, right=z) for a, z in zip(gates, gates[1:])]
    permission_order = list(PERMISSIONS)
    rng.shuffle(permission_order)
    protected = sorted(permission_order[:spec["protected"]])
    for j, permission in enumerate(protected):
        token = b.node()
        ants = {risk, gates[-1]}
        if family == "selective-expansion" and permission == permission_order[0]:
            # One protected permission already has exactly this eligibility
            # envelope in the base; the other permissions still need all gates.
            ants.remove(gates[-1])
        if j:
            ants.add(public[width + j - 1])
        b.rules.add(HornRule(frozenset(ants), token))
        b.edges.add((token, permission))
    leak = b.node()
    b.rules.add(HornRule(frozenset((gates[-1], risk, public[width])), leak))
    if group == "repair":
        b.edges.update((e["left"], e["right"]) for e in edits)
        edits = []
        for _ in range(spec["edits"]):
            conflict = b.node()
            b.edges.add((risk, conflict))
            pair = tuple(sorted((risk, conflict)))
            b.disjoint.add(pair)
            edits.append(dict(op="remove_disjoint", left=pair[0], right=pair[1]))
    goals = [goal([public[-1]], "class", gates[-2]), goal([], "class", gates[-1], False),
             goal(risk_seeds[:-1], "class", gates[-1], False),
             goal(risk_seeds[:-1] + [public[width]], "class", leak, False),
             goal([public[-1]], "consistent")]
    goals.extend(goal([public[-1]], "effective", permission, False) for permission in protected)
    if family in ("joint-control", "partial-repair", "missed-positive"):
        edits = edits[:-1]
    if family == "conflict-contained":
        edits.append(dict(op="add_disjoint", left=risk, right=gates[-1]))
    if family == "goal-leak":
        goals.append(goal(risk_seeds + [public[width]], "class", leak, False))
    if family == "missed-positive":
        goals.append(goal([public[-1]], "class", gates[-1]))
    b.stretch(spec["classes"], rng)
    # Opaque seeded aliases and shuffled rule inputs remove descriptive clues.
    hidden = sorted(b.classes - set(b.public))
    labels = [f"C{i:03d}" for i in range(len(hidden))]
    rng.shuffle(labels)
    aliases = dict(zip(hidden, labels))
    aliases.update({p: p for p in b.public})
    aliases.update({p: p for p in PERMISSIONS})
    base = b.ontology()
    base = Ontology(frozenset(aliases[x] for x in base.classes),
                    tuple((aliases[a], aliases[z]) for a, z in base.subclass),
                    tuple(HornRule(frozenset(aliases[x] for x in r.antecedents), aliases[r.head]) for r in base.rules),
                    tuple((aliases[a], aliases[z]) for a, z in base.disjoint))
    for edit in edits:
        edit["left"], edit["right"] = aliases[edit["left"]], aliases[edit["right"]]
    for item in goals:
        if item["target"] is not None:
            item["target"] = aliases[item["target"]]
    contract = dict(base=base.to_dict(), base_sha256=base.sha256, public_classes=sorted(b.public),
                    protected_permissions=protected, goals=goals, source_task=f"source-{split}-{slot}",
                    destination_task=f"destination-{tier}-{slot}", semantics=SEMANTICS, policy=POLICY)
    return dict(case_id=f"{split}-{tier}-{slot:03d}-{family}", split=split, tier=tier, family=family,
                group_id=group_id, contract=contract, proposal=edits)


def make_approvals(contract, candidate, mode):
    if mode not in APPROVAL_MODES:
        raise ValueError(mode)
    if mode == "none":
        return []
    records = []
    protected = contract["protected_permissions"]
    for j, permission in enumerate(protected):
        record = dict(record_id=f"approval-{j}", approved=True, **approval_scope(contract, candidate, permission))
        selected = mode
        if mode == "partial":
            selected = "all-exact" if j == 0 else "denied"
        elif mode == "mixed":
            selected = ("all-exact", "wrong-candidate", "wrong-task", "denied")[j]
        field = {"wrong-base": "base_sha256", "wrong-candidate": "candidate_sha256",
                 "wrong-contract": "contract_sha256"}.get(selected)
        if field:
            record[field] = digest(["different", record[field]])
        elif selected == "wrong-public":
            record["public_classes"] = contract["public_classes"][:-1]
        elif selected == "wrong-task":
            record["destination_task"] += "-other"
        elif selected == "denied":
            record["approved"] = False
        records.append(record)
    return records


def instance(tier="tier-1", split="dev", slot=0, family="joint-expansion", approval_mode="none", seed=SEED):
    case = structural_case(tier, split, slot, family, seed)
    candidate = apply_edits(Ontology.from_dict(case["contract"]["base"]), case["proposal"])
    case["candidate_sha256"] = candidate.sha256
    case["approval_mode"] = approval_mode
    case["approvals"] = make_approvals(case["contract"], candidate, approval_mode)
    case["truth"], case["diagnostics"] = solve(case["contract"], case["proposal"], case["approvals"])
    return case


def dataset(cases_per_family=2, seed=SEED):
    if type(cases_per_family) is not int or cases_per_family < 1:
        raise ValueError("cases_per_family must be positive")
    data = dict(schema_version=2, status=STATUS, seed=seed, tiers=TIERS,
                semantics=SEMANTICS, policy=POLICY, limitations=LIMITATIONS, train=[], dev=[])
    for split in ("train", "dev"):
        for t, tier in enumerate(TIERS):
            for slot in range(cases_per_family):
                for f, family in enumerate(FAMILIES):
                    mode = APPROVAL_MODES[(t * len(FAMILIES) + slot * 3 + f + (split == "dev")) % len(APPROVAL_MODES)]
                    data[split].append(instance(tier, split, slot, family, mode, seed))
    data["corpus_sha256"] = digest(data)
    return data


def validate_witness(case, permission, witness):
    """Accept ANY valid expanding public profile, including nonminimal ones."""
    if (permission not in case["contract"]["protected_permissions"] or not isinstance(witness, list)
            or any(not isinstance(x, str) for x in witness) or len(set(witness)) != len(witness)
            or not set(witness) <= set(case["contract"]["public_classes"])):
        return False
    base = Ontology.from_dict(case["contract"]["base"])
    candidate = apply_edits(base, case["proposal"])
    return (permission not in SetSolver(base).close(witness).effective
            and permission in SetSolver(candidate).close(witness).effective)


def score_answer(case, answer):
    """Strict typed decision scoring, with semantic rather than string witnesses."""
    if not isinstance(answer, dict) or set(answer) != ANSWER_FIELDS:
        return dict(correct=False, reason="invalid-answer-schema")
    protected = set(case["contract"]["protected_permissions"])
    if any(type(answer[k]) is not bool for k in ("goal_correct", "release_allowed")):
        return dict(correct=False, reason="decision-fields-must-be-boolean")
    for key in ("approval_matches", "permission_authorized"):
        if (not isinstance(answer[key], dict) or set(answer[key]) != protected
                or any(type(v) is not bool for v in answer[key].values())):
            return dict(correct=False, reason="invalid-permission-map")
    expansion = answer["expansion_permissions"]
    if (not isinstance(expansion, list) or any(not isinstance(p, str) for p in expansion)
            or len(expansion) != len(set(expansion)) or not set(expansion) <= protected):
        return dict(correct=False, reason="invalid-expansion-inventory")
    truth = case["truth"]
    fields = {key: answer[key] == truth[key] for key in ANSWER_FIELDS - {"expansion_permissions", "expansion_witnesses"}}
    fields["expansion_permissions"] = set(expansion) == set(truth["expansion_permissions"])
    witnesses = answer["expansion_witnesses"]
    fields["expansion_witnesses"] = (
        isinstance(witnesses, dict) and set(witnesses) == set(truth["expansion_permissions"])
        and all(validate_witness(case, p, witness) for p, witness in witnesses.items())
    )
    return dict(correct=all(fields.values()), fields=fields)


def request(case):
    """Model-facing payload excludes family, reference answers and diagnostics."""
    prompt = (
        "Evaluate this fixed proposed batch under the supplied contract. Compute least positive Horn closure "
        "for each public seed subset. Subclass [a,b] means a implies b; every rule requires ALL antecedents. "
        "Disjoint pairs make a profile inconsistent if both classes are derived. Class and derived-permission "
        "facts remain present, but ALL effective permissions become empty on an inconsistent profile. "
        "Apply the entire batch to the original base. Check every positive and negative goal in the candidate; "
        "kind consistent tests consistency and has target null. G is true exactly when all goals pass. "
        "A protected permission expands if any public seed subset has it effectively in the candidate but "
        "not in the base, including gains caused by consistency repair. Return the complete expansion set. "
        "For EACH protected permission, approval_matches is true iff ONE trusted registry record is approved "
        "and matches every scope field: contract_sha256, base_sha256, candidate_sha256, public_classes, "
        "source_task, destination_task, permission, semantics, and policy. Records cannot be combined to "
        "assemble a scope. Current hashes below are authoritative adapter bindings. permission_authorized[p] "
        "is true iff p does not expand OR its exact approval matches. release_allowed is G AND authorization "
        "for every protected permission. Approval never repairs a failed goal. Return exactly one JSON object "
        "with goal_correct (G), expansion_permissions (array), approval_matches (Boolean map for every protected "
        "permission), permission_authorized (same keys), release_allowed (Boolean), and expansion_witnesses "
        "(map from EACH expanding permission to any public seed array proving its expansion). Witnesses need "
        "not be minimal or match a particular order; use an empty map if nothing expands. No other keys."
    )
    packet = dict(contract=case["contract"], contract_sha256=contract_hash(case["contract"]),
                  candidate_sha256=case["candidate_sha256"], proposed_batch=case["proposal"],
                  trusted_approval_registry=case["approvals"])
    return dict(messages=[dict(role="system", content=prompt), dict(role="user", content=canonical(packet))])


def summary(data):
    cases = data["train"] + data["dev"]
    by_tier = {}
    for tier in TIERS:
        rows = [c for c in cases if c["tier"] == tier]
        def bounds(values):
            return [min(values), max(values)]
        by_tier[tier] = dict(
            cases=len(rows), classes=TIERS[tier]["classes"], public=TIERS[tier]["public"],
            exhaustive_profiles_per_case=1 << TIERS[tier]["public"],
            edits=bounds([len(c["proposal"]) for c in rows]),
            subclass_edges=bounds([len(c["contract"]["base"]["subclass"]) for c in rows]),
            conjunction_rules=bounds([len(c["contract"]["base"]["rules"]) for c in rows]),
            candidate_closure_rounds=bounds([c["diagnostics"]["synchronous_rounds_after"] for c in rows]),
            minimum_expansion_witness_size=bounds([v for c in rows for v in c["diagnostics"]["minimum_witness_sizes"].values()]),
            protected_permissions=TIERS[tier]["protected"],
            jointly_only_expanding=sum(c["diagnostics"]["jointly_only_expanding"] for c in rows),
        )
    semantic_by_split = {s: {c["diagnostics"]["semantic_fingerprint"] for c in data[s]} for s in ("train", "dev")}
    return dict(status=STATUS, corpus_sha256=data["corpus_sha256"], seed=data["seed"], cases=len(cases),
                splits={s: len(data[s]) for s in ("train", "dev")}, by_tier=by_tier,
                generation_groups=len({c["group_id"] for c in cases}),
                unique_semantic_tables={s: len(v) for s, v in semantic_by_split.items()},
                shared_train_dev_semantic_tables=len(semantic_by_split["train"] & semantic_by_split["dev"]),
                total_profile_pairs_checked=sum(c["diagnostics"]["profiles_checked"] for c in cases),
                all_cases_independently_checked=all(c["diagnostics"]["independent_agreement"] for c in cases),
                goal_failures=sum(not c["truth"]["goal_correct"] for c in cases),
                expanding_cases=sum(bool(c["truth"]["expansion_permissions"]) for c in cases),
                allowed_cases=sum(c["truth"]["release_allowed"] for c in cases),
                approval_modes=dict(Counter(c["approval_mode"] for c in cases)), limitations=LIMITATIONS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional generated DEVELOPMENT corpus JSON")
    parser.add_argument("--report", type=Path, help="Optional compact development report JSON")
    parser.add_argument("--cases-per-family", type=int, default=2)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    start = time.perf_counter()
    data = dataset(args.cases_per_family, args.seed)
    elapsed = time.perf_counter() - start
    report = summary(data)
    report["generation_and_dual_solver_seconds"] = round(elapsed, 6)
    report["module_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["source_files"] = ["internal/benchmarks/ontology_semantic_challenge_v2.py",
                              "tests/test_ontology_semantic_challenge_v2.py"]
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(data, indent=2) + "\n")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
