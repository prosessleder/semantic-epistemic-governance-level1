"""Fixed name-ablation and checked-closure diagnostic, separate from old runs."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter

from internal.benchmarks import ontology_boundary_runner as original
from internal.scripts.audit_ontology_boundary_robustness import independent_state
from ontology_boundary.oracle import Ontology, closure

TARGET = "can_write_metadata"
OTHER = "can_write_body"


def microcases():
    """Sixteen declared sanity programs; not a new ontology-release benchmark."""
    h = ["C" + hashlib.sha256(f"reasoning-diagnostic-helper-{i}".encode()).hexdigest()[:14] for i in range(3)]
    a, b, c = h
    specs = [
        ("direct-on", ["P1"], [("P1", TARGET)], [], []),
        ("direct-off", ["P2"], [("P1", TARGET)], [], []),
        ("forward", ["P1"], [("P1", a), (a, TARGET)], [], []),
        ("reverse", ["P1"], [(a, "P1"), (a, TARGET)], [], []),
        ("chain", ["P1"], [("P1", a), (a, b), (b, TARGET)], [], []),
        ("disconnected", ["P1"], [("P1", a), (b, TARGET)], [], []),
        ("and-on", ["P1", "P2"], [(a, TARGET)], [(["P1", "P2"], a)], []),
        ("and-off", ["P1"], [(a, TARGET)], [(["P1", "P2"], a)], []),
        ("cycle-on", ["P1"], [("P1", a), (a, b), (b, a), (b, TARGET)], [], []),
        ("cycle-off", ["P1"], [(a, b), (b, a), (b, TARGET)], [], []),
        ("alternative", ["P1"], [("P1", TARGET), ("P2", TARGET)], [], []),
        ("other-permission", ["P1"], [("P1", OTHER)], [], []),
        ("active-conflict", ["P1"], [("P1", a), (a, TARGET), ("P1", b)], [], [(a, b)]),
        ("dormant-conflict", ["P2"], [("P1", a), (a, TARGET), ("P1", b)], [], [(a, b)]),
        ("irrelevant-conflict", ["P1"], [("P1", a), (a, TARGET), ("P1", b)], [], [("P2", "P3")]),
        ("empty-seeds", [], [("P1", a), (a, TARGET)], [], []),
    ]
    result = []
    for name, seeds, edges, rules, disjoint in specs:
        theory = {"classes": sorted(["P0", "P1", "P2", "P3", *h]), "subclass": [list(e) for e in edges],
                  "rules": [{"antecedents": ants, "head": head} for ants, head in rules],
                  "disjoint": [list(e) for e in disjoint]}
        result.append({"context_id": "micro-" + name, "group": "micro", "motif": name,
                       "theory": theory, "seeds": seeds, "target": TARGET})
    return result


def contexts(data):
    result = microcases()
    # Before inference: lexical-first case within each original TEST motif.
    for family in sorted({c["family"] for c in data["test"]}):
        case = min((c for c in data["test"] if c["family"] == family), key=lambda c: c["base_id"])
        for side in ("old", "new"):
            for role in ("relevant", "sham"):
                result.append({"context_id": f"reused-{case['base_id']}-{side}-{role}", "group": "reused",
                    "motif": family, "theory": copy.deepcopy(case[side]), "seeds": case["profiles"][role],
                    "target": case["protected_permission"], "base_id": case["base_id"], "side": side, "role": role})
    return result


def renamed(context, naming):
    value = copy.deepcopy(context)
    if naming not in ("opaque", "short"):
        raise ValueError("undeclared naming")
    if naming == "opaque":
        return value
    theory = value["theory"]
    mapping = {name: f"H{i}" for i, name in enumerate(sorted(n for n in theory["classes"] if not n.startswith("P")))}
    def name(atom):
        return mapping.get(atom, atom)
    theory["classes"] = [name(n) for n in theory["classes"]]
    theory["subclass"] = [[name(a), name(b)] for a, b in theory["subclass"]]
    theory["rules"] = [{"antecedents": [name(a) for a in r["antecedents"]], "head": name(r["head"])} for r in theory["rules"]]
    theory["disjoint"] = [[name(a), name(b)] for a, b in theory["disjoint"]]
    value["seeds"] = [name(n) for n in value["seeds"]]
    return value


def gold(context):
    independent = independent_state(context["theory"], context["seeds"], context["target"])
    state = closure(Ontology.from_dict(context["theory"]), context["seeds"])
    result = {"derived": context["target"] in state.derived_permissions, "effective": context["target"] in state.permissions}
    assert result == {k: independent[k] for k in result}
    return result


def rules(context):
    theory = context["theory"]
    return [{"id": f"R{i}", "antecedents": ants, "head": head} for i, (ants, head) in enumerate(
        [([a], b) for a, b in theory["subclass"]] + [(r["antecedents"], r["head"]) for r in theory["rules"]], 1)]


def direct_messages(context, query):
    question = ("Is the protected permission head DERIVED in the positive closure, BEFORE any inconsistency gate? "
        "For this question ignore disjointness when deciding derivation." if query == "derived" else
        "Is the protected permission EFFECTIVE? It must be derived AND the profile must be consistent. "
        "If any DISJOINT pair is jointly derived, ALL effective permissions are empty.")
    user = ("Single-ontology reasoning control. Start only from the supplied seed types. Repeatedly apply "
        "all implications to a least fixed point. A conjunction needs every antecedent. "
        "There is no negation or implicit class membership. Disjointness detects inconsistency, "
        "not extra positive consequences.\nOntology:\n" + original.render_ontology(context["theory"])
        + "\nSeed profile: {" + ", ".join(context["seeds"]) + "}.\nProtected permission: " + context["target"] + "\n"
        + question + '\nReturn a JSON object with only the key "answer" and a native Boolean value. True means YES to the question; false means NO. Do not explain.')
    return [{"role": "system", "content": 'Evaluate the supplied question. Answer using the native Boolean field "answer", without a letter codebook.'},
            {"role": "user", "content": user}]


def trace_messages(context):
    theory = context["theory"]
    lines = ["Vocabulary only (not initial facts): " + ", ".join(theory["classes"]),
             "Initial facts ONLY: {" + ", ".join(context["seeds"]) + "}.", "Rules:"]
    lines += [r["id"] + ": " + " & ".join(r["antecedents"]) + " -> " + r["head"] for r in rules(context)]
    lines += ["Disjoint pairs: " + (", ".join(f"({a}, {b})" for a, b in theory["disjoint"]) or "none"),
              "Protected head: " + context["target"]]
    procedure = ('Start with ONLY the initial facts. Vocabulary declarations are not facts. An implication works only forward. '
        'A rule can fire only when ALL its antecedents are already present and its head is absent. '
        'Append its rule ID to steps and add its head. Continue until no rule can add a head. '
        'Cycles do not start themselves. Disjointness does not add facts; if both members of any disjoint pair '
        'are present, effective is false. derived is true exactly when the protected head is present. '
        'effective is true exactly when derived is true and there is no disjoint conflict. '
        'Return only one JSON object with keys "steps" (ordered array of rule IDs), "derived" (Boolean), '
        'and "effective" (Boolean). Include every required rule firing, and no redundant firing. '
        'An empty steps array is valid when no rule can add a head. Do not include prose.')
    return [{"role": "system", "content": "Compute a complete forward-chaining certificate for the supplied finite Horn program."},
            {"role": "user", "content": "\n".join(lines) + "\n" + procedure}]


def parse_trace(text):
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return None
    if (not isinstance(obj, dict) or set(obj) != {"steps", "derived", "effective"}
        or not isinstance(obj["steps"], list) or any(not isinstance(x, str) for x in obj["steps"])
        or type(obj["derived"]) is not bool or type(obj["effective"]) is not bool):
        return None
    return obj


def verify_trace(context, obj):
    """Derivability plus fixed-point completeness, without trusting final claims."""
    if obj is None:
        return {"valid": False, "reason": "format"}
    available = set(context["seeds"])
    indexed = {r["id"]: r for r in rules(context)}
    for rid in obj["steps"]:
        if rid not in indexed:
            return {"valid": False, "reason": "unknown-rule"}
        r = indexed[rid]
        if not set(r["antecedents"]) <= available:
            return {"valid": False, "reason": "unsupported-step"}
        if r["head"] in available:
            return {"valid": False, "reason": "redundant-step"}
        available.add(r["head"])
    if any(set(r["antecedents"]) <= available and r["head"] not in available for r in indexed.values()):
        return {"valid": False, "reason": "incomplete-closure"}
    derived = context["target"] in available
    conflict = any(a in available and b in available for a, b in context["theory"]["disjoint"])
    result = {"derived": derived, "effective": derived and not conflict}
    if any(obj[k] != value for k, value in result.items()):
        return {"valid": False, "reason": "wrong-final-claim"}
    return {"valid": True, "reason": "verified", "answers": result, "atoms": sorted(available)}


def oracle_trace(context):
    """Constructed software reference only; never given to the LLM."""
    available, steps = set(context["seeds"]), []
    while True:
        eligible = next((r for r in rules(context) if set(r["antecedents"]) <= available and r["head"] not in available), None)
        if eligible is None:
            break
        available.add(eligible["head"])
        steps.append(eligible["id"])
    return dict(steps=steps, **gold(context))


def jobs(contexts):
    out = []
    for context in contexts:
        for naming in ("opaque", "short"):
            for endpoint, query in (("direct", "derived"), ("direct", "effective"), ("trace", "both")):
                out.append({"context_id": context["context_id"], "group": context["group"], "motif": context["motif"],
                            "naming": naming, "endpoint": endpoint, "query": query, "job_id": f"control-{len(out):04d}"})
    return out


def summarize(rows):
    result = {}
    for group in ("micro", "reused"):
        result[group] = {}
        for naming in ("opaque", "short"):
            result[group][naming] = {}
            for endpoint in ("direct", "trace"):
                subset = [r for r in rows if r["group"] == group and r["naming"] == naming and r["endpoint"] == endpoint]
                metrics = {}
                for query in ("derived", "effective"):
                    sub = subset if endpoint == "trace" else [r for r in subset if r["query"] == query]
                    positives = sum(r["gold"][query] for r in sub)
                    negatives = len(sub) - positives
                    correct = sum(r["prediction"] is not None and r["prediction"].get(query) == r["gold"][query] for r in sub)
                    tp = sum(r["gold"][query] and r["prediction"] is not None and r["prediction"].get(query) is True for r in sub)
                    tn = sum(not r["gold"][query] and r["prediction"] is not None and r["prediction"].get(query) is False for r in sub)
                    metrics[query] = {"n": len(sub), "correct": correct, "positive_n": positives, "negative_n": negatives,
                        "tp": tp, "tn": tn, "balanced_accuracy": (tp / positives + tn / negatives) / 2 if positives and negatives else None}
                if endpoint == "trace":
                    metrics["certificates"] = {"n": len(subset), "valid": sum(r["verification"]["valid"] for r in subset),
                        "reasons": dict(Counter(r["verification"]["reason"] for r in subset)),
                        "accepted_wrong": sum(r["verification"]["valid"] and r["prediction"] != r["gold"] for r in subset)}
                result[group][naming][endpoint] = metrics
    return result
