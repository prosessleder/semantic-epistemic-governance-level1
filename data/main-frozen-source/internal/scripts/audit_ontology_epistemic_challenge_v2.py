"""Independent, bounded repair-first audit of the development challenge.

No model calls. Authority uses graph states, provenance uses topological
propagation, support uses combinations, and repairs use subset-first SAT masks.
The benchmark's reference helpers are never used by the independent oracle.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import hashlib
from itertools import combinations
import json
from pathlib import Path
import time

MAX_ATOMS = 12
MAX_SUBSETS = 262144


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def encoded_facts(facts):
    return [{"atom": atom, "value": value} for atom, value in sorted(facts)]


def current_for(obj, atom, packet):
    resource = packet["atoms"][atom]["resource"]
    return (obj["verified"] is True and obj["revoked"] is False
            and obj["versions"].get(resource) == packet["current_versions"][resource])


def reachable_authority(packet):
    outgoing = defaultdict(list)
    for grant in packet["grants"]:
        outgoing[grant["issuer"]].append(grant)
    reached = {(root, atom, packet["root_budget"])
               for root in packet["trust_roots"] for atom in packet["atoms"]}
    pending = deque(sorted(reached))
    while pending:
        source, atom, budget = pending.popleft()
        for grant in outgoing[source]:
            child_budget = grant["remaining_depth"]
            if (atom not in grant["atoms"] or not current_for(grant, atom, packet)
                    or not 0 <= child_budget < budget):
                continue
            state = (grant["subject"], atom, child_budget)
            if state not in reached:
                reached.add(state)
                pending.append(state)
    return {(source, atom) for source, atom, _ in reached}


def iterative_leaves(graph):
    if any(parent not in graph for parents in graph.values() for parent in parents):
        raise ValueError("undeclared provenance ancestor")
    leaves = {node: frozenset((node,)) for node, parents in graph.items() if not parents}
    unresolved = set(graph) - set(leaves)
    while unresolved:
        ready = {node for node in unresolved if all(parent in leaves for parent in graph[node])}
        if not ready:
            raise ValueError("cyclic provenance")
        for node in ready:
            leaves[node] = frozenset().union(*(leaves[parent] for parent in graph[node]))
        unresolved -= ready
    return leaves


def sufficient_disjoint_reports(origins, threshold):
    if threshold < 1:
        raise ValueError("positive quorum required")
    # Do not reuse the production backtracking/set-packing implementation.
    for choice in combinations(origins, threshold):
        if sum(map(len, choice)) == len(set().union(*choice)):
            return True
    return False


def independently_supported(packet):
    rights = reachable_authority(packet)
    ancestry = iterative_leaves(packet["provenance"])
    by_fact = defaultdict(list)
    admitted = []
    for report in packet["reports"]:
        for claim in report["claims"]:
            atom, value = claim["atom"], claim["value"]
            if type(value) is not bool:
                raise ValueError("claim must be Boolean")
            if atom not in packet["atoms"]:
                continue
            if current_for(report, atom, packet) and (report["source"], atom) in rights:
                by_fact[atom, value].append(ancestry[report["provenance"]])
                admitted.append((report["id"], atom, value))
    supported = {fact for fact, origins in by_fact.items()
                 if sufficient_disjoint_reports(origins, packet["quorum"][fact[0]])}
    return supported, sorted(admitted)


def sat_assignments(packet):
    """Translate constraints to clauses and evaluate small integer assignments."""
    atoms = sorted(packet["atoms"])
    if len(atoms) > MAX_ATOMS:
        raise ValueError("independent audit atom cap exceeded")
    positions = {atom: index for index, atom in enumerate(atoms)}
    clauses = []
    for rule in packet["constraints"]:
        if rule["type"] == "implies":
            clause = [(positions[item["atom"]], not item["value"]) for item in rule["if"]]
            clause.append((positions[rule["then"]["atom"]], rule["then"]["value"]))
        elif rule["type"] == "disjoint":
            clause = [(positions[atom], False) for atom in rule["atoms"]]
        else:
            raise ValueError("unknown hard constraint")
        clauses.append(clause)
    assignments = [bits for bits in range(1 << len(atoms))
                   if all(any(bool(bits & (1 << pos)) == value for pos, value in clause)
                          for clause in clauses)]
    if not assignments:
        raise ValueError("inconsistent hard constraints")
    return positions, assignments


def subset_first_repairs(packet, supported):
    """Enumerate consistent fact subsets before selecting maximal repairs.

    A bitset is the SAT witness set for a subset; intersecting one literal's
    witness set is an independent satisfiability check. No maximal world/fact
    intersections or production reference functions are used.
    """
    facts = sorted(supported)
    if (1 << len(facts)) > MAX_SUBSETS:
        raise ValueError("independent audit subset cap exceeded")
    positions, assignments = sat_assignments(packet)
    literal_masks = []
    for atom, value in facts:
        literal_masks.append(sum(1 << index for index, bits in enumerate(assignments)
                                 if bool(bits & (1 << positions[atom])) == value))
    repairs, union_witnesses = [], 0
    full_mask = (1 << len(assignments)) - 1
    visited = 0

    def visit(index, selection, witnesses):
        nonlocal union_witnesses, visited
        visited += 1
        if index == len(facts):
            if any(not selection & (1 << omitted) and witnesses & literal_masks[omitted]
                   for omitted in range(len(facts))):
                return
            repair = frozenset(fact for i, fact in enumerate(facts) if selection & (1 << i))
            repairs.append(repair)
            union_witnesses |= witnesses
            return
        visit(index + 1, selection, witnesses)
        included = witnesses & literal_masks[index]
        if included:
            visit(index + 1, selection | (1 << index), included)

    visit(0, 0, full_mask)
    worlds = [bits for index, bits in enumerate(assignments) if union_witnesses & (1 << index)]
    return positions, worlds, sorted(repairs, key=lambda repair: sorted(repair)), visited


def independent_reference(packet):
    facts, admitted = independently_supported(packet)
    positions, worlds, repairs, visited = subset_first_repairs(packet, facts)

    def value(bits, atom):
        return bool(bits & (1 << positions[atom]))

    def allowed(bits, action):
        if any(not value(bits, goal) for goal in action["goals"]):
            return False
        return value(bits, action["approval"]) or not value(bits, action["expansion"])

    possible = {name: sorted({allowed(bits, action) for bits in worlds})
                for name, action in packet["actions"].items()}
    decisions = {name: {1: "allow", 0: "deny"}[outcomes[0]] if len(outcomes) == 1 else "undetermined"
                 for name, outcomes in possible.items()}
    query_scores = {}
    for query in packet["queries"]:
        partitions = defaultdict(list)
        for bits in worlds:
            partitions[tuple(value(bits, atom) for atom in query["atoms"])].append(bits)
        worst = 0
        for group in partitions.values():
            unresolved = sum(any(allowed(bits, action) for bits in group)
                             and not all(allowed(bits, action) for bits in group)
                             for action in packet["actions"].values())
            worst = max(worst, unresolved)
        query_scores[query["id"]] = (worst, query["cost"])
    if all(len(outcomes) == 1 for outcomes in possible.values()):
        best = [None]
    else:
        if not query_scores:
            raise ValueError("undetermined packet requires offered queries")
        optimum = min(query_scores.values())
        best = sorted(query for query, cost in query_scores.items() if cost == optimum)
    return dict(example_answer=dict(supported_facts=encoded_facts(facts),
                selected_repair=encoded_facts(repairs[0]), decisions=decisions,
                possible_release=possible, next_query=best[0]),
                acceptable_repairs=[encoded_facts(repair) for repair in repairs],
                acceptable_queries=best, query_scores=query_scores,
                compatible_world_count=len(worlds), admitted_claims=admitted,
                independent_subset_nodes=visited)


def audit_dataset(data):
    rows = []
    mismatches = []
    for case in data["cases"]:
        actual = independent_reference(case["input"])
        expected = case["reference"]
        fields = sorted(set(actual) - {"independent_subset_nodes"})
        failed = [field for field in fields if canonical(actual[field]) != canonical(expected[field])]
        if failed:
            mismatches.append(dict(id=case["id"], fields=failed))
        rows.append(dict(id=case["id"], tier=case["tier"], unit_id=case["unit_id"],
                         decisions=actual["example_answer"]["decisions"],
                         supported_facts=len(actual["example_answer"]["supported_facts"]),
                         repair_count=len(actual["acceptable_repairs"]),
                         repair_sizes=sorted({len(repair) for repair in actual["acceptable_repairs"]}),
                         optimal_query_count=len(actual["acceptable_queries"]),
                         compatible_worlds=actual["compatible_world_count"],
                         subset_nodes=actual["independent_subset_nodes"]))
    return dict(status="PASS" if not mismatches else "FAIL", cases=len(rows),
                mismatch_count=len(mismatches), mismatches=mismatches,
                per_tier={str(tier): dict(cases=sum(row["tier"] == tier for row in rows),
                    decisions=dict(Counter(decision for row in rows if row["tier"] == tier
                                           for decision in row["decisions"].values())),
                    multiple_repairs=sum(row["tier"] == tier and row["repair_count"] > 1 for row in rows),
                    unequal_maximal_sizes=sum(row["tier"] == tier and len(row["repair_sizes"]) > 1 for row in rows))
                    for tier in sorted({row["tier"] for row in rows})}, rows=rows,
                methodology="Independent authority-state traversal, iterative DAG leaves, exact combinations support, clause SAT masks and exhaustive repair-first subsets.",
                limits=dict(max_atoms=MAX_ATOMS, max_fact_subsets=MAX_SUBSETS))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    raw = args.dataset.read_bytes()
    result = audit_dataset(json.loads(raw))
    result.update(dataset=str(args.dataset), dataset_sha256=hashlib.sha256(raw).hexdigest(),
                  auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  elapsed_seconds=time.monotonic() - started)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "cases", "mismatch_count", "per_tier", "elapsed_seconds")}))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
