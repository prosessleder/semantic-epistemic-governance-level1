"""Exact finite oracle for a declared unary Horn fragment.

The class theory is open world. Authorization is an application convention:
only an entailed fixed permission head permits an operation, and inconsistent
profiles fail closed. Exhaustion is over the supplied public seed signature,
not all OWL models, all future inputs, or physical network channels.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
import hashlib
import json
import re
from typing import Iterable, Mapping


PERMISSIONS = (
    "can_write_body", "can_read_body",
    "can_write_metadata", "can_read_metadata",
)
FIELDS = ("body", "metadata")
MAX_PUBLIC_CLASSES = 6
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


def _name(value: object) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError(f"invalid class/head name: {value!r}")
    return value


def _names(values: Iterable[str]) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError("expected a collection of names, not one string")
    try:
        return frozenset(_name(x) for x in values)
    except TypeError as error:
        raise ValueError("expected an iterable collection of names") from error


def _pair(value: Iterable[str]) -> tuple[str, str]:
    if isinstance(value, (str, bytes)):
        raise ValueError("an edge must have exactly two names")
    try:
        items = tuple(value)
    except TypeError as error:
        raise ValueError("an edge must have exactly two names") from error
    if len(items) != 2:
        raise ValueError("an edge must have exactly two names")
    return _name(items[0]), _name(items[1])


@dataclass(frozen=True)
class HornRule:
    antecedents: frozenset[str]
    head: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "antecedents", _names(self.antecedents))
        object.__setattr__(self, "head", _name(self.head))
        if not self.antecedents:
            raise ValueError("unconditional rules are outside this fragment")

    def to_dict(self) -> dict:
        return {"antecedents": sorted(self.antecedents), "head": self.head}

    @classmethod
    def from_dict(cls, value: Mapping) -> "HornRule":
        if not isinstance(value, Mapping) or set(value) != {"antecedents", "head"}:
            raise ValueError("a rule accepts only antecedents and head")
        return cls(value["antecedents"], value["head"])


@dataclass(frozen=True)
class Ontology:
    classes: frozenset[str]
    subclass: tuple[tuple[str, str], ...] = ()
    rules: tuple[HornRule, ...] = ()
    disjoint: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        classes = _names(self.classes)
        if classes.intersection(PERMISSIONS):
            raise ValueError("permission heads cannot be declared seedable classes")
        subclass = tuple(sorted(set(_pair(e) for e in self.subclass)))
        rules = tuple(self.rules)
        if any(not isinstance(r, HornRule) for r in rules):
            raise ValueError("rules must be HornRule objects")
        rules = tuple(sorted(set(rules), key=lambda r: (tuple(sorted(r.antecedents)), r.head)))
        disjoint = tuple(sorted(set(tuple(sorted(_pair(e))) for e in self.disjoint)))
        for sub, sup in subclass:
            if sub not in classes or sup not in classes.union(PERMISSIONS):
                raise ValueError("subclass endpoints must be declared classes or a fixed permission head")
        for rule in rules:
            if not rule.antecedents.issubset(classes) or rule.head not in classes.union(PERMISSIONS):
                raise ValueError("rule uses an undeclared class or unsupported policy head")
        for left, right in disjoint:
            if left not in classes or right not in classes:
                raise ValueError("disjointness endpoints must be declared classes")
        object.__setattr__(self, "classes", classes)
        object.__setattr__(self, "subclass", subclass)
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "disjoint", disjoint)

    def to_dict(self) -> dict:
        return {
            "classes": sorted(self.classes),
            "subclass": [list(x) for x in self.subclass],
            "rules": [r.to_dict() for r in self.rules],
            "disjoint": [list(x) for x in self.disjoint],
        }

    @classmethod
    def from_dict(cls, value: Mapping) -> "Ontology":
        required = {"classes"}
        allowed = required | {"subclass", "rules", "disjoint"}
        if not isinstance(value, Mapping) or not required.issubset(value) or not set(value).issubset(allowed):
            raise ValueError("ontology schema accepts only classes, subclass, rules and disjoint")
        return cls(value["classes"], value.get("subclass", ()),
                   tuple(HornRule.from_dict(r) for r in value.get("rules", ())),
                   value.get("disjoint", ()))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Closure:
    seed_types: frozenset[str]
    class_types: frozenset[str]
    derived_permissions: frozenset[str]
    permissions: frozenset[str]
    inconsistencies: tuple[tuple[str, str], ...]
    rounds: int

    @property
    def consistent(self) -> bool:
        return not self.inconsistencies

    def to_dict(self) -> dict:
        return {
            "seed_types": sorted(self.seed_types), "class_types": sorted(self.class_types),
            "derived_permissions": sorted(self.derived_permissions),
            "permissions": sorted(self.permissions), "consistent": self.consistent,
            "inconsistencies": [list(x) for x in self.inconsistencies], "rounds": self.rounds,
        }


def closure(ontology: Ontology, seed_types: Iterable[str]) -> Closure:
    """Least positive Horn closure; never infer a grant from absent information."""
    seeds = _names(seed_types)
    if not seeds.issubset(ontology.classes):
        raise ValueError("seed profile contains an undeclared class or permission")
    atoms = set(seeds)
    rules = [HornRule(frozenset((a,)), b) for a, b in ontology.subclass] + list(ontology.rules)
    rounds = 0
    while True:
        additions = {r.head for r in rules if r.antecedents.issubset(atoms)} - atoms
        if not additions:
            break
        atoms.update(additions)
        rounds += 1
    conflicts = tuple((a, b) for a, b in ontology.disjoint if a in atoms and b in atoms)
    derived = frozenset(atoms.intersection(PERMISSIONS))
    return Closure(seeds, frozenset(atoms.intersection(ontology.classes)), derived,
                   derived if not conflicts else frozenset(), conflicts, rounds)


def seed_profiles(public_classes: Iterable[str]) -> tuple[frozenset[str], ...]:
    """Cardinality then lexical enumeration of the complete declared signature."""
    names = tuple(sorted(_names(public_classes)))
    if len(names) > MAX_PUBLIC_CLASSES:
        raise ValueError(f"public seed signature exceeds {MAX_PUBLIC_CLASSES} classes")
    if set(names).intersection(PERMISSIONS):
        raise ValueError("permission heads are not public seed classes")
    return tuple(frozenset(xs) for n in range(len(names) + 1) for xs in combinations(names, n))


def _signature(old: Ontology, new: Ontology, public_classes: Iterable[str]) -> tuple[frozenset[str], ...]:
    profiles = seed_profiles(public_classes)
    public = frozenset().union(*profiles)
    if not public.issubset(old.classes) or not public.issubset(new.classes):
        raise ValueError("all public seed classes must be declared in both versions")
    return profiles


def _minimal(profiles: Iterable[frozenset[str]]) -> list[list[str]]:
    values = set(profiles)
    return [sorted(p) for p in sorted(values, key=lambda p: (len(p), tuple(sorted(p))))
            if not any(q < p for q in values)]


def compare_ontologies(old: Ontology, new: Ontology, public_classes: Iterable[str], *,
                       protected_permissions: Iterable[str] = PERMISSIONS,
                       current_probes: Iterable[Iterable[str]] = ()) -> dict:
    """Exhaustive effective-permission delta, including inconsistency repair.

    A witness is inclusion minimal separately for each permission. Its profile
    need not be consistent under the old version; both consistency bits are
    retained. The certificate concerns exactly these finite profiles and this
    closed-world permission/fail-closed convention.
    """
    profiles = _signature(old, new, public_classes)
    protected = _names(protected_permissions)
    if not protected.issubset(PERMISSIONS):
        raise ValueError("unsupported protected permission")
    inventory = []
    gained = {p: [] for p in PERMISSIONS}
    lost = {p: [] for p in PERMISSIONS}
    by_seed = {}
    for profile in profiles:
        left, right = closure(old, profile), closure(new, profile)
        gain, loss = right.permissions - left.permissions, left.permissions - right.permissions
        row = {"seed_types": sorted(profile), "old": left.to_dict(), "new": right.to_dict(),
               "gained_permissions": sorted(gain), "lost_permissions": sorted(loss)}
        inventory.append(row)
        by_seed[profile] = row
        for permission in gain:
            gained[permission].append(profile)
        for permission in loss:
            lost[permission].append(profile)
    probes = []
    for seed in current_probes:
        key = _names(seed)
        if key not in by_seed:
            raise ValueError("current probe lies outside the declared public seed signature")
        probes.append(by_seed[key])
    expansion = {p: _minimal(ps) for p, ps in gained.items() if ps}
    contraction = {p: _minimal(ps) for p, ps in lost.items() if ps}
    empty = by_seed[frozenset()]
    return {
        "schema_version": 1, "old_sha256": old.sha256, "new_sha256": new.sha256,
        "public_classes": sorted(frozenset().union(*profiles)),
        "coverage": {"enumerated_profiles": len(profiles), "expected_profiles": 2 ** len(frozenset().union(*profiles)),
                     "exhaustive_declared_signature": True,
                     "both_consistent_profiles": sum(r["old"]["consistent"] and r["new"]["consistent"] for r in inventory)},
        "certificate_scope": "finite declared seed signature; positive unary Horn plus pairwise disjointness; effective permissions fail closed",
        "physical_channel_claim": False, "universal_owl_claim": False,
        "profiles": inventory, "expansion_witnesses": expansion, "contraction_witnesses": contraction,
        "affected_fields": [f for f in FIELDS if any(p.endswith("_" + f) for p in expansion)],
        "permission_preserving": not expansion and not contraction,
        "no_expansion": not expansion,
        "protected_permissions": sorted(protected),
        "protected_no_expansion": not any(p in protected for p in expansion),
        "empty_probe_unchanged": not empty["gained_permissions"] and not empty["lost_permissions"],
        "current_probes": probes,
        "current_probes_unchanged": all(not r["gained_permissions"] and not r["lost_permissions"] for r in probes),
    }


@dataclass(frozen=True)
class ExternalGrant:
    """Trusted approval record supplied by the caller, never by ontology rules."""
    grant_id: str
    source_agent: str
    destination_agent: str
    source_task: str
    destination_task: str
    fields: frozenset[str]
    approved: bool = True

    def __post_init__(self) -> None:
        for name in ("grant_id", "source_agent", "destination_agent", "source_task", "destination_task"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError("grant identities/scopes must be nonempty strings")
        fields = frozenset(self.fields)
        if not fields or not fields.issubset(FIELDS) or type(self.approved) is not bool:
            raise ValueError("grant fields must be body/metadata and approval must be a boolean")
        object.__setattr__(self, "fields", fields)

    def to_dict(self) -> dict:
        return {"grant_id": self.grant_id, "source_agent": self.source_agent,
                "destination_agent": self.destination_agent, "source_task": self.source_task,
                "destination_task": self.destination_task, "fields": sorted(self.fields), "approved": self.approved}

    @classmethod
    def from_dict(cls, value: Mapping) -> "ExternalGrant":
        allowed = {"grant_id", "source_agent", "destination_agent", "source_task", "destination_task", "fields", "approved"}
        if not isinstance(value, Mapping) or not set(value).issubset(allowed) or not (allowed - {"approved"}).issubset(value):
            raise ValueError("invalid external grant schema")
        return cls(**dict(value))


def flow_decision(source: Closure, destination: Closure, field: str, *,
                  source_task: str, destination_task: str,
                  source_agent: str = "source", destination_agent: str = "destination",
                  visibility: Mapping[str, bool] | None = None,
                  external_grant: ExternalGrant | None = None) -> dict:
    """Evaluate one modeled route without confusing eligibility with approval.

    Visibility is a trusted simulator/adapter mask supplied independently of
    ontology or LLM text. It describes the modeled adapter only, not a measured
    physical channel. Missing field entries deny visibility.
    """
    if field not in FIELDS:
        raise ValueError("field must be body or metadata")
    if not isinstance(source, Closure) or not isinstance(destination, Closure):
        raise ValueError("source/destination must be oracle Closure objects")
    for value in (source_task, destination_task, source_agent, destination_agent):
        if not isinstance(value, str) or not value:
            raise ValueError("agent/task identities must be nonempty strings")
    if visibility is None:
        visibility = {f: True for f in FIELDS}
    if not isinstance(visibility, Mapping) or not set(visibility).issubset(FIELDS) or any(type(x) is not bool for x in visibility.values()):
        raise ValueError("visibility is a trusted body/metadata boolean mask")
    if external_grant is not None and not isinstance(external_grant, ExternalGrant):
        raise ValueError("external_grant must be an ExternalGrant supplied outside the ontology")
    write, read = "can_write_" + field, "can_read_" + field
    ontology_eligible = write in source.permissions and read in destination.permissions
    same_task = source_task == destination_task
    grant_matches = bool(external_grant is not None and external_grant.approved
                         and external_grant.source_agent == source_agent
                         and external_grant.destination_agent == destination_agent
                         and external_grant.source_task == source_task
                         and external_grant.destination_task == destination_task
                         and field in external_grant.fields)
    authorized = same_task or grant_matches
    visible = visibility.get(field, False)
    possible = ontology_eligible and visible
    return {"field": field, "source_task": source_task, "destination_task": destination_task,
            "source_agent": source_agent, "destination_agent": destination_agent,
            "source_consistent": source.consistent, "destination_consistent": destination.consistent,
            "source_write_eligible": write in source.permissions,
            "destination_read_eligible": read in destination.permissions,
            "ontology_eligible": ontology_eligible, "tcb_visible": visible,
            "same_task": same_task, "external_grant_matches": grant_matches,
            "external_grant_id": external_grant.grant_id if grant_matches else None,
            "task_authorized": authorized, "mediated_flow_possible": possible,
            "authorized_flow_possible": possible and authorized,
            "unauthorized_flow_possible": possible and not authorized,
            "physical_channel_claim": False}


def compare_flow_eligibility(old: Ontology, new: Ontology, public_classes: Iterable[str], *,
                             source_task: str, destination_task: str,
                             source_agent: str = "source", destination_agent: str = "destination",
                             visibility: Mapping[str, bool] | None = None,
                             external_grant: ExternalGrant | None = None,
                             fields: Iterable[str] = FIELDS,
                             current_probes: Iterable[tuple[Iterable[str], Iterable[str]]] = ()) -> dict:
    """Exhaust source/destination profiles and retain minimal joint witnesses.

    Minimality is componentwise seed inclusion, separately by field. The same
    ontology version is applied to each actor but their profiles, task scopes,
    and trusted visibility/grant records remain independently fixed.
    """
    profiles = _signature(old, new, public_classes)
    selected_fields = tuple(sorted(set(fields)))
    if not selected_fields or not set(selected_fields).issubset(FIELDS):
        raise ValueError("fields must select body and/or metadata")
    left = {p: closure(old, p) for p in profiles}
    right = {p: closure(new, p) for p in profiles}
    options = {"source_task": source_task, "destination_task": destination_task,
               "source_agent": source_agent, "destination_agent": destination_agent,
               "visibility": visibility, "external_grant": external_grant}
    # Validate trusted context even if no field permissions are derivable.
    flow_decision(left[profiles[0]], left[profiles[0]], selected_fields[0], **options)
    gains = {f: [] for f in selected_fields}
    losses = {f: [] for f in selected_fields}
    lookup = {}
    for src, dst, field in product(profiles, profiles, selected_fields):
        before = flow_decision(left[src], left[dst], field, **options)
        after = flow_decision(right[src], right[dst], field, **options)
        key = (src, dst, field)
        row = {"source_seed_types": sorted(src), "destination_seed_types": sorted(dst),
               "field": field, "old": before, "new": after}
        lookup[key] = row
        if after["mediated_flow_possible"] and not before["mediated_flow_possible"]:
            gains[field].append((src, dst))
        if before["mediated_flow_possible"] and not after["mediated_flow_possible"]:
            losses[field].append((src, dst))

    def minimal_rows(values: dict) -> dict:
        result = {}
        for field, entries in values.items():
            if not entries:
                continue
            # Any dominating strict-subset pair is earlier in this order, and
            # has a minimal ancestor. This avoids quadratic work on every gain.
            minimal = []
            for s, d in sorted(entries, key=lambda pair: (len(pair[0]) + len(pair[1]),
                                                          tuple(sorted(pair[0])), tuple(sorted(pair[1])))):
                if not any(s2.issubset(s) and d2.issubset(d) for s2, d2 in minimal):
                    minimal.append((s, d))
            result[field] = [lookup[s, d, field] for s, d in minimal]
        return result

    probes = []
    for src, dst in current_probes:
        src, dst = _names(src), _names(dst)
        if src not in left or dst not in left:
            raise ValueError("flow probe lies outside declared signature")
        probes.extend(lookup[src, dst, f] for f in selected_fields)
    expansion = minimal_rows(gains)
    contraction = minimal_rows(losses)
    return {"schema_version": 1, "old_sha256": old.sha256, "new_sha256": new.sha256,
            "public_classes": sorted(frozenset().union(*profiles)),
            "coverage": {"source_profiles": len(profiles), "destination_profiles": len(profiles),
                         "profile_pairs": len(profiles) ** 2, "field_evaluations": len(lookup),
                         "exhaustive_declared_signature": True},
            "certificate_scope": "finite profile pairs, fixed trusted task/grant/visibility context; counterfactual adapter eligibility",
            "physical_channel_claim": False, "universal_owl_claim": False,
            "visibility": dict(visibility) if visibility is not None else {f: True for f in FIELDS},
            "external_grant": external_grant.to_dict() if external_grant else None,
            "expansion_witnesses": expansion, "contraction_witnesses": contraction,
            "newly_possible_counts": {f: len(gains[f]) for f in selected_fields},
            "newly_unauthorized_counts": {f: sum(lookup[s, d, f]["new"]["unauthorized_flow_possible"] for s, d in gains[f]) for f in selected_fields},
            "no_expansion": not expansion,
            "current_probes": probes,
            "current_probes_unchanged": all(r["old"]["mediated_flow_possible"] == r["new"]["mediated_flow_possible"] for r in probes)}
