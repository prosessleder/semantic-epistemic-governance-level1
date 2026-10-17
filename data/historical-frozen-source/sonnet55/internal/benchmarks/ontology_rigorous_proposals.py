"""Fresh structured instances, group-separated splits and paired name variants."""
from dataclasses import replace
import hashlib
from itertools import combinations
import json
import random
import warnings

import networkx as nx

from ontology_boundary.oracle import Ontology, HornRule, PERMISSIONS, compare_ontologies, seed_profiles
from ontology_boundary.checked_release import Goal, ReviewContract, apply_proposal, goals_satisfied
from internal.benchmarks import ontology_checked_proposals as historical
from internal.benchmarks import ontology_latent_proposals as old_stress

SEED = 2026101301
FAMILIES = (
    "mission-chain", "protected-chain", "strict-conjunction", "protected-conjunction",
    "permission-contraction", "conflict-repair", "latent-pair", "latent-triple",
    "latent-cycle", "latent-conflict-repair", "nonexpanding-conflict-decoy", "unsatisfiable-empty",
)
LATENT = {"latent-pair", "latent-triple", "latent-cycle", "latent-conflict-repair"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def structural_fingerprint(contract):
    """Name-invariant WL fingerprint of the input's context-connected graph.

    Equal hashes may be nonisomorphic; conservatively group them together.
    Isolated helper declarations and disconnected distractors are excluded.
    Reference edits, family names, task IDs and arbitrary class names are absent.
    """
    g = nx.DiGraph()
    def node(key, label): g.add_node(key, label=label); return key
    def edge(a, b, label): g.add_edge(a, b, label=label)
    node("ctx", "review-context")
    for c in contract.base.classes:
        node(("class", c), "public-class" if c in contract.public_classes else "helper-class")
    for p in PERMISSIONS: node(("class", p), "permission:" + p)
    node("basis", "seed-basis"); edge("ctx", "basis", "context")
    for c in contract.public_classes: edge("basis", ("class", c), "member")
    node("protected", "protected-query"); edge("ctx", "protected", "context")
    edge("protected", ("class", contract.protected_permission), "target")
    for i, profile in enumerate(contract.current_profiles):
        key = node(("current", i), "current-profile"); edge("ctx", key, "context")
        for c in profile: edge(("class", c), key, "seed")
    for i, goal in enumerate(contract.goals):
        key = node(("goal", i), f"goal:{goal.kind}:{goal.expected}"); edge("ctx", key, "context")
        for c in goal.profile: edge(("class", c), key, "seed")
        edge(key, ("class", goal.target), "target")
    for a, b in contract.base.subclass: edge(("class", a), ("class", b), "implies")
    for i, rule in enumerate(contract.base.rules):
        key = node(("rule", i), "conjunction")
        for c in rule.antecedents: edge(("class", c), key, "antecedent")
        edge(key, ("class", rule.head), "head")
    for i, pair in enumerate(contract.base.disjoint):
        key = node(("conflict", i), "disjoint")
        for c in pair: edge(("class", c), key, "member")
    keep = nx.node_connected_component(g.to_undirected(), "ctx")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="The hashes produced for directed graphs changed.*", category=UserWarning)
        return nx.weisfeiler_lehman_graph_hash(g.subgraph(keep).copy(), node_attr="label", edge_attr="label", iterations=16)


class Builder:
    def __init__(self, rng, public):
        self.rng, self.public = rng, public
        self.pool = list(range(80)); rng.shuffle(self.pool)
        self.helpers, self.edges, self.rules, self.disjoint = set(), [], [], []

    def h(self):
        name = "H" + str(self.pool.pop()); self.helpers.add(name); return name

    def path(self, start, end, length):
        route = [start] + [self.h() for _ in range(length-1)] + [end]
        self.edges.extend(zip(route, route[1:])); return route

    def broken_path(self, start, end, length):
        route = self.path(start, end, length)
        i = self.rng.randrange(len(route)-1)
        pair = (route[i], route[i+1]); self.edges.remove(pair)
        return dict(op="add_edge", left=pair[0], right=pair[1])

    def background(self, gateway, forbidden_witness, depth):
        choices = [frozenset(x) for k in (2, 3) for x in combinations(sorted(self.public-{"P1"}), k)
                   if not frozenset(x) <= forbidden_witness]
        self.rng.shuffle(choices)
        for ants in choices[:self.rng.randint(1, min(4, len(choices)))]:
            head = self.h(); self.rules.append(HornRule(ants, head))
            self.path(head, gateway, self.rng.randint(1, min(3, depth)))
        # Relevant inputs also contain branches which do not affect the goals.
        for _ in range(self.rng.randint(0, 2)):
            self.path(self.rng.choice(sorted(self.public)), self.h(), self.rng.randint(1, 3))

    def ontology(self):
        return Ontology(self.public | self.helpers, tuple(self.edges), tuple(self.rules), tuple(self.disjoint))


def instance(family, split, slot, attempt=0):
    fi = FAMILIES.index(family)
    rng = random.Random(SEED + fi*100000 + (0 if split == "dev" else 50000) + slot*1009 + attempt*7919)
    public_n = rng.choice((4, 5)) if split == "dev" else rng.choice((5, 6))
    if family in ("latent-triple", "nonexpanding-conflict-decoy"): public_n = max(5, public_n)
    public = frozenset(f"P{i}" for i in range(public_n))
    depth = rng.randint(1, 3) if split == "dev" else rng.randint(4, 6)
    protected = PERMISSIONS[slot % 4]
    mission = "can_write_body" if protected != "can_write_body" else "can_write_metadata"
    observer = next(p for p in PERMISSIONS if p not in (protected, mission))
    b = Builder(rng, public)
    gm, gb, gr = b.h(), b.h(), b.h()
    b.edges += [(gm, protected), (gb, mission), (gr, observer), ("P0", gr)]
    r, s, t = "P1", "P2", "P3"
    cohort = "P4" if family in ("latent-triple", "nonexpanding-conflict-decoy") else "P3"
    shared = b.h()
    b.edges += [(r,shared),(cohort,shared)]
    actors = (r,cohort)
    witness = frozenset({r})
    if family in ("mission-chain", "protected-chain"):
        gateway = gb if family == "mission-chain" else gm
        target = mission if family == "mission-chain" else protected
        patch = b.broken_path(shared, gateway, depth+1)
        goals = tuple(Goal(frozenset({a}), "effective", target) for a in actors)
    elif family in ("strict-conjunction", "protected-conjunction"):
        # P3 is the second cohort here; P4 supplies a third independent signal.
        arity = rng.choice((2, 3)) if public_n >= 5 else 2
        signals = [s,"P4"][:arity-1]
        ants = frozenset({shared}|set(signals)); witness = frozenset({r}|set(signals))
        head = b.h(); b.path(head, gb if family == "strict-conjunction" else gm, depth)
        patch = dict(op="add_rule", antecedents=sorted(ants), head=head)
        goals = []
        for actor in actors:
            seeds=frozenset({actor}|set(signals));goals.append(Goal(seeds,"class",head))
            for k in range(1,arity):
                goals += [Goal(frozenset(x),"class",head,False) for x in combinations(sorted(seeds),k)]
        goals = tuple(dict.fromkeys(goals))
    elif family == "permission-contraction":
        route = b.path(shared, gm, depth+1); b.path(shared, gb, max(1, depth-1))
        i = rng.randrange(len(route)-1)
        patch = dict(op="remove_edge", left=route[i], right=route[i+1])
        goals = tuple(g for a in actors for g in (Goal(frozenset({a}), "effective", protected, False), Goal(frozenset({a}), "effective", mission)))
    elif family in ("conflict-repair", "latent-conflict-repair"):
        clash = b.h(); b.path(shared, clash, depth); b.path(shared, gb, depth)
        b.disjoint.append((shared, clash)); patch = dict(op="remove_disjoint", left=shared, right=clash)
        if family == "conflict-repair": b.path(clash, gm, max(1, depth-1))
        else:
            b.rules.append(HornRule(frozenset({gb, s}), gm)); witness = frozenset({r, s})
        goals = tuple(g for a in actors for g in (Goal(frozenset({a}), "effective", mission), Goal(frozenset({a}), "class", clash)))
    elif family in ("latent-pair", "latent-triple", "nonexpanding-conflict-decoy"):
        signals = {s, t} if family in ("latent-triple", "nonexpanding-conflict-decoy") else {s}
        b.rules.append(HornRule(frozenset({gb} | signals), gm))
        witness = frozenset({r} | signals)
        patch = b.broken_path(shared, gb, depth+1)
        goals = tuple(Goal(frozenset({a}), "effective", mission) for a in actors)
        if family == "nonexpanding-conflict-decoy": b.disjoint.append((s, t))
    elif family == "latent-cycle":
        a, c = b.h(), b.h(); b.path(shared, a, depth)
        b.path(c, a, rng.randint(2, depth+2)); b.path(c, gb, depth)
        patch = dict(op="add_edge", left=a, right=c)
        b.rules.append(HornRule(frozenset({gb, s}), gm)); witness = frozenset({r, s})
        goals = tuple(Goal(frozenset({x}), "class", c) for x in actors)
    elif family == "unsatisfiable-empty":
        b.path(b.h(), gb, depth)
        patch = dict(op="abstain"); goals = (Goal(frozenset(), "class", gb),)
        witness = frozenset()
    else: raise ValueError(family)
    b.background(gm, witness-{"P1"}, depth)
    base = b.ontology(); c = ReviewContract(base, public, protected, goals)
    assert not goals_satisfied(c, base)
    candidate = apply_proposal(c, patch)
    impossible = family == "unsatisfiable-empty"
    if impossible: assert candidate is None
    else: assert candidate is not None and goals_satisfied(c, candidate)
    cert = compare_ontologies(base, candidate or base, public, protected_permissions=[protected], current_probes=c.current_profiles)
    expanded = not cert["protected_no_expansion"]
    expected = family in {"protected-chain", "protected-conjunction", "conflict-repair"} | LATENT
    assert expanded == expected
    index = {frozenset(x["seed_types"]):x for x in cert["profiles"]}
    probes = set(c.current_profiles) | {g.profile for g in goals}
    detected = any(protected in index[p]["gained_permissions"] for p in probes)
    if family in LATENT: assert not detected and protected in index[witness]["gained_permissions"]
    if family == "latent-triple":
        assert not any(protected in x["gained_permissions"] for x in cert["profiles"] if len(x["seed_types"]) <= 2)
    # Group by semantic profile/permission tables as well as input structure.
    signatures = [[x[side]["consistent"], x[side]["permissions"]] for x in cert["profiles"] for side in ("old", "new")]
    goal_tables = []
    for goal in goals:
        rows = []
        for x in cert["profiles"]:
            atoms = "class_types" if goal.kind == "class" else ("permissions" if goal.kind == "effective" else "derived_permissions")
            rows.append([goal.target in x[side][atoms] for side in ("old", "new")])
        goal_tables.append(dict(kind=goal.kind, expected=goal.expected, profile=sorted(goal.profile), values=rows))
    return dict(task_id=f"rigor-v2-{split}-{fi:02d}-{slot:02d}", family=family, split=split,
        contract=c.to_dict(), reference_patch=patch, reference_candidate=None if candidate is None else candidate.to_dict(),
        expected_abstain=impossible, reference_expansion=expanded, reference_off_probe=expanded and not detected,
        structural_fingerprint=structural_fingerprint(c), semantic_fingerprint=digest([protected, signatures, goal_tables]),
        depth=depth, public_n=public_n, generation_attempt=attempt)


def dataset():
    prior = historical.tasks() + old_stress.tasks()
    seen = {structural_fingerprint(ReviewContract.from_dict(t["contract"])) for t in prior}
    semantic_seen = set(); result = dict(dev=[], test=[])
    for split, n in (("dev", 4), ("test", 16)):
        for family in FAMILIES:
            for slot in range(n):
                for attempt in range(300):
                    task = instance(family, split, slot, attempt)
                    a, b = task["structural_fingerprint"], task["semantic_fingerprint"]
                    if a not in seen and b not in semantic_seen:
                        seen.add(a); semantic_seen.add(b); result[split].append(task); break
                else: raise RuntimeError("failed to draw a fresh structure and semantic signature")
    assert len(result["dev"]) == 48 and len(result["test"]) == 192
    return result


def renamed(task):
    c = ReviewContract.from_dict(task["contract"])
    roles = ("ObserverRole", "ContributorRole", "ApprovedRole", "ReviewerRole", "ServiceRole", "AuditRole")
    mapping = {p:roles[i] for i,p in enumerate(sorted(c.public_classes))}
    mapping.update({h:f"ClassificationStage{i}" for i,h in enumerate(sorted(c.base.classes-c.public_classes))})
    atom = lambda x:mapping.get(x,x)
    base = Ontology(frozenset(atom(x) for x in c.base.classes), tuple((atom(a),atom(b)) for a,b in c.base.subclass),
        tuple(HornRule(frozenset(atom(a) for a in r.antecedents),atom(r.head)) for r in c.base.rules),
        tuple((atom(a),atom(b)) for a,b in c.base.disjoint))
    other = replace(c,base=base,public_classes=frozenset(atom(x) for x in c.public_classes),
        goals=tuple(Goal(frozenset(atom(x) for x in g.profile),g.kind,atom(g.target),g.expected) for g in c.goals),
        current_profiles=tuple(frozenset(atom(x) for x in p) for p in c.current_profiles))
    patch = dict(task["reference_patch"])
    for k in ("left","right","head"):
        if k in patch:patch[k]=atom(patch[k])
    if "antecedents" in patch:patch["antecedents"]=sorted(atom(x) for x in patch["antecedents"])
    candidate = apply_proposal(other,patch)
    assert structural_fingerprint(c) == structural_fingerprint(other)
    return dict(task,task_id=task["task_id"]+"-alias",contract=other.to_dict(),reference_patch=patch,
        reference_candidate=None if candidate is None else candidate.to_dict(),alias_of=task["task_id"],alias_mapping=mapping)


def subsets(tasks, per_family=4):
    return [t for f in FAMILIES for t in sorted([t for t in tasks if t["family"]==f],key=lambda t:digest(t["task_id"]))[:per_family]]


def messages(task):
    result = historical.messages(task)
    result[-1]["content"] = result[-1]["content"].replace(
        "Return one proposal JSON object only, without prose or extra fields.",
        "If no permitted single edit can satisfy all checks, return {\"op\":\"abstain\"}. "
        "Return one proposal JSON object only, without prose or extra fields.")
    return result
