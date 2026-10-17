"""In-memory field-complete artifact adapter and independent reachability baseline.

This module does not import the ontology oracle or infer any ontology facts.
Caller-supplied eligibility, tool ACLs, task identity, adapter visibility and
external flow grants are separate inputs. The records contain local test values;
there is no network, filesystem sink, actual Artifactory integration, or claim
about unmodeled channels. A permission projection is not a physical contract.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import json
from typing import Iterable


FIELDS = frozenset(("body", "metadata"))


def _fields(values: Iterable[str]) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError("fields must be a collection")
    result = frozenset(values)
    if not result.issubset(FIELDS):
        raise ValueError("only body and metadata fields are modeled")
    return result


def _field(value: str) -> str:
    if value not in FIELDS:
        raise ValueError("only body and metadata fields are modeled")
    return value


def _digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Principal:
    actor: str
    task: str

    def __post_init__(self) -> None:
        if any(not isinstance(x, str) or not x for x in (self.actor, self.task)):
            raise ValueError("trusted actor and task identifiers must be nonempty")


@dataclass(frozen=True)
class Eligibility:
    """Trusted input to this adapter test, not inferred by the store itself."""
    write_fields: frozenset[str] = frozenset()
    read_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "write_fields", _fields(self.write_fields))
        object.__setattr__(self, "read_fields", _fields(self.read_fields))


@dataclass(frozen=True)
class ToolACL:
    write_artifact: bool = True
    read_artifact: bool = True
    list_artifacts: bool = True

    def __post_init__(self) -> None:
        if any(type(x) is not bool for x in (self.write_artifact, self.read_artifact, self.list_artifacts)):
            raise ValueError("tool ACL entries must be boolean")

    def permits_observation(self, field: str) -> bool:
        return self.read_artifact if _field(field) == "body" else self.list_artifacts

    @property
    def sha256(self) -> str:
        return _digest({"write_artifact": self.write_artifact,
                        "read_artifact": self.read_artifact,
                        "list_artifacts": self.list_artifacts})


@dataclass(frozen=True)
class AdapterContract:
    """Same-task fields are private to that task; named foreign fields are visible.

    Descriptive annotations do not change the executable visibility contract.
    The operational hash deliberately excludes annotations. This is a declared
    simulator projection, not a hash policy for arbitrary production adapters.
    """
    foreign_visible_fields: frozenset[str] = frozenset(("metadata",))
    annotations: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "foreign_visible_fields", _fields(self.foreign_visible_fields))
        annotations = tuple(self.annotations)
        if any(len(x) != 2 or any(not isinstance(y, str) for y in x) for x in annotations):
            raise ValueError("annotations must be string key/value pairs")
        object.__setattr__(self, "annotations", annotations)

    def visible_to(self, owner: Principal, reader: Principal, field: str) -> bool:
        return owner.task == reader.task or _field(field) in self.foreign_visible_fields

    @property
    def operational_sha256(self) -> str:
        return _digest({"same_task_visible_fields": sorted(FIELDS),
                        "foreign_visible_fields": sorted(self.foreign_visible_fields)})


@dataclass(frozen=True)
class FlowGrant:
    """External actor/task/field grant; this is not ontology-release ratification."""
    source: Principal
    destination: Principal
    fields: frozenset[str]
    approved: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.source, Principal) or not isinstance(self.destination, Principal):
            raise ValueError("grant endpoints must be trusted Principal objects")
        object.__setattr__(self, "fields", _fields(self.fields))
        if not self.fields or type(self.approved) is not bool:
            raise ValueError("grant must select fields and boolean approval")

    def matches(self, source: Principal, destination: Principal, field: str) -> bool:
        return self.approved and self.source == source and self.destination == destination and _field(field) in self.fields


def task_authorized(source: Principal, destination: Principal, field: str,
                    grants: Iterable[FlowGrant] = ()) -> bool:
    _field(field)
    records = tuple(grants)
    if any(not isinstance(x, FlowGrant) for x in records):
        raise ValueError("flow grants must be externally supplied FlowGrant records")
    return source.task == destination.task or any(g.matches(source, destination, field) for g in records)


@dataclass(frozen=True)
class StoreEvent:
    tool: str
    field: str
    tool_permitted: bool
    ontology_eligible: bool
    adapter_visible: bool
    task_authorized: bool
    admitted: bool
    reason: str


@dataclass(frozen=True)
class Observation:
    value: str | None
    event: StoreEvent

    @property
    def unauthorized_delivery(self) -> bool:
        return self.event.admitted and not self.event.task_authorized


class ArtifactStore:
    """A tiny executable adapter; resource IDs and owner scopes are trusted.

    Each Principal owns one internal record. The actor cannot pick a resource ID
    or reassign ownership, so those fields are intentionally not tested channels.
    Raw mode exposes the declared adapter surface, including unauthorized flows.
    Enforced mode mediates every modeled observation with the trusted task grant.
    """

    def __init__(self, contract: AdapterContract, *, enforce_task_boundary: bool = False):
        if not isinstance(contract, AdapterContract) or type(enforce_task_boundary) is not bool:
            raise ValueError("store requires a trusted adapter contract and boolean mediation mode")
        self.contract = contract
        self.enforce_task_boundary = enforce_task_boundary
        self._records: dict[Principal, dict[str, str]] = {}
        self.events: list[StoreEvent] = []

    def write_field(self, owner: Principal, acl: ToolACL, eligibility: Eligibility,
                    field: str, value: str) -> StoreEvent:
        _field(field)
        if not isinstance(value, str):
            raise ValueError("test record values must be strings")
        eligible = field in eligibility.write_fields
        admitted = acl.write_artifact and eligible
        if admitted:
            self._records.setdefault(owner, {})[field] = value
        reason = "written" if admitted else "tool_acl" if not acl.write_artifact else "write_ineligible"
        event = StoreEvent("write_artifact", field, acl.write_artifact, eligible, True, True, admitted, reason)
        self.events.append(event)
        return event

    def observe_field(self, owner: Principal, reader: Principal, acl: ToolACL,
                      eligibility: Eligibility, field: str,
                      grants: Iterable[FlowGrant] = ()) -> Observation:
        _field(field)
        tool = "read_artifact" if field == "body" else "list_artifacts"
        tool_permitted = acl.permits_observation(field)
        eligible = field in eligibility.read_fields
        visible = self.contract.visible_to(owner, reader, field)
        authorized = task_authorized(owner, reader, field, grants)
        stored = field in self._records.get(owner, {})
        admitted = stored and tool_permitted and eligible and visible and (authorized or not self.enforce_task_boundary)
        if not stored:
            reason = "no_record_field"
        elif not tool_permitted:
            reason = "tool_acl"
        elif not eligible:
            reason = "read_ineligible"
        elif not visible:
            reason = "adapter_private"
        elif self.enforce_task_boundary and not authorized:
            reason = "task_boundary"
        else:
            reason = "observed"
        event = StoreEvent(tool, field, tool_permitted, eligible, visible, authorized, admitted, reason)
        self.events.append(event)
        return Observation(self._records[owner][field] if admitted else None, event)


@dataclass(frozen=True)
class ReachabilityResult:
    """Path over the fully declared adapter graph, independent of Horn inference."""
    route_exists: bool
    task_authorized: bool
    unauthorized_route: bool
    witness_path: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]


def field_complete_reachability(source: Principal, destination: Principal, field: str, *,
                                source_acl: ToolACL, destination_acl: ToolACL,
                                source_eligibility: Eligibility, destination_eligibility: Eligibility,
                                contract: AdapterContract, grants: Iterable[FlowGrant] = (),
                                enforce_task_boundary: bool = False) -> ReachabilityResult:
    """BFS over one fixed record field; assumes a write of some test value occurs.

    Edges include tool permission, field-specific eligibility, adapter visibility
    and optional observation mediation. Authorization is reported separately in
    raw mode. This finite graph says nothing about undeclared adapter fields.
    """
    _field(field)
    if type(enforce_task_boundary) is not bool:
        raise ValueError("mediation mode must be boolean")
    authorized = task_authorized(source, destination, field, grants)
    start, stored, end = "source", "artifact:" + field, "destination"
    edges = set()
    if source_acl.write_artifact and field in source_eligibility.write_fields:
        edges.add((start, stored))
    if (destination_acl.permits_observation(field) and field in destination_eligibility.read_fields
            and contract.visible_to(source, destination, field)
            and (authorized or not enforce_task_boundary)):
        edges.add((stored, end))
    adjacency = {}
    for left, right in sorted(edges):
        adjacency.setdefault(left, []).append(right)
    pending = deque(((start, (start,)),))
    seen = {start}
    witness = ()
    while pending:
        node, path = pending.popleft()
        if node == end:
            witness = path
            break
        for successor in adjacency.get(node, ()):
            if successor not in seen:
                seen.add(successor)
                pending.append((successor, path + (successor,)))
    return ReachabilityResult(bool(witness), authorized, bool(witness) and not authorized,
                              witness, tuple(sorted(edges)))
