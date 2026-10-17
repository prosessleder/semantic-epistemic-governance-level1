"""Formal baselines and independently implemented ground consequences."""
from dataclasses import replace
from itertools import combinations
from ontology_boundary.oracle import PERMISSIONS, Ontology, compare_ontologies
from ontology_boundary.checked_release import (
    Approval, ApprovalRegistry, ReviewContract, apply_proposal, goals_satisfied,
)

MODES = ("none", "exact", "stale-base", "wrong-candidate", "wrong-basis", "wrong-query", "wrong-scope", "denied", "model-claim")
PIPELINES = ("goal_only", "current_goal", "pairwise", "dependency_cone", "checked", "derived_only_mutant", "unbound_approval_mutant")


def materialize(theory, seeds):
    """Sequential fixed-point implementation independent of the production oracle."""
    atoms = set(seeds)
    clauses = [(set([a]),b) for a,b in theory["subclass"]]
    clauses += [(set(r["antecedents"]),r["head"]) for r in theory["rules"]]
    while True:
        before = set(atoms)
        for ants,head in clauses:
            if ants <= atoms: atoms.add(head)
        if atoms == before: break
    conflicts = [pair for pair in theory["disjoint"] if set(pair) <= atoms]
    derived = atoms.intersection(PERMISSIONS)
    return dict(classes=atoms-set(PERMISSIONS),derived=derived,effective=derived if not conflicts else set(),consistent=not conflicts)


def ground(contract, candidate):
    public = sorted(contract.public_classes)
    table = []
    for n in range(len(public)+1):
        for xs in combinations(public,n):
            p=frozenset(xs)
            table.append((p,materialize(contract.base.to_dict(),p),materialize(candidate.to_dict(),p)))
    protected = contract.protected_permission
    expanding = [p for p,a,b in table if protected in b["effective"] and protected not in a["effective"]]
    derived_expanding = [p for p,a,b in table if protected in b["derived"] and protected not in a["derived"]]
    by_profile = {p:b for p,a,b in table}
    goals = []
    for goal in contract.goals:
        key = {"class":"classes","derived":"derived","effective":"effective"}[goal.kind]
        goals.append((goal.target in by_profile[goal.profile][key]) == goal.expected)
    probes = set(contract.current_profiles) | {g.profile for g in contract.goals}
    return dict(goal_satisfied=all(goals),protected_expansion=bool(expanding),
        goal_probe_detected=any(p in probes for p in expanding),
        pairwise_detected=any(len(p)<=2 or p in probes for p in expanding),
        derived_expansion=bool(derived_expanding),witnesses=[sorted(p) for p in expanding],profiles=len(table))


def registry(contract, candidate, mode):
    if mode not in MODES:raise ValueError(mode)
    if mode in ("none","model-claim"):return ApprovalRegistry()
    csha,bsha,nsha = contract.sha256,contract.base.sha256,candidate.sha256
    if mode=="stale-base":bsha=Ontology(contract.base.classes|{"DetachedBase"},contract.base.subclass,contract.base.rules,contract.base.disjoint).sha256
    elif mode=="wrong-candidate":nsha=Ontology(candidate.classes|{"DetachedCandidate"},candidate.subclass,candidate.rules,candidate.disjoint).sha256
    elif mode=="wrong-basis":
        used = set().union(*contract.current_profiles,*(g.profile for g in contract.goals))
        unused=contract.public_classes-used
        if unused:
            changed=contract.public_classes-{min(unused)}
        else:
            assert len(contract.public_classes)<6
            changed=contract.public_classes|{min(contract.base.classes-contract.public_classes)}
        csha=replace(contract,public_classes=changed).sha256
    elif mode=="wrong-query":csha=replace(contract,protected_permission=next(p for p in PERMISSIONS if p!=contract.protected_permission)).sha256
    elif mode=="wrong-scope":csha=replace(contract,destination_task="task-C").sha256
    return ApprovalRegistry((Approval(csha,bsha,nsha,mode!="denied"),))


def dependency_flag(contract,candidate,proposal):
    if proposal["op"] in ("add_disjoint","remove_disjoint"):return True
    roots={contract.protected_permission}
    for ontology in (contract.base,candidate):
        for pair in ontology.disjoint:roots.update(pair)
    clauses=[]
    for ontology in (contract.base,candidate):
        clauses += [(set([a]),b) for a,b in ontology.subclass]
        clauses += [(set(r.antecedents),r.head) for r in ontology.rules]
    while True:
        before=set(roots)
        for ants,head in clauses:
            if head in roots:roots.update(ants)
        if roots==before:break
    touched={proposal[k] for k in ("left","right","head") if k in proposal}
    touched.update(proposal.get("antecedents",[]))
    return bool(roots&touched)


def evaluate(contract, proposal):
    try:candidate=apply_proposal(contract,proposal)
    except (ValueError,TypeError):candidate=None
    if candidate is None:
        return None,dict(valid_edit=False,goal_satisfied=False,protected_expansion=False),{
            mode:{p:False for p in PIPELINES} for mode in MODES}
    cert=compare_ontologies(contract.base,candidate,contract.public_classes,protected_permissions=[contract.protected_permission])
    protected=contract.protected_permission
    expansion=not cert["protected_no_expansion"]
    met=goals_satisfied(contract,candidate)
    probes=set(contract.current_profiles)|{g.profile for g in contract.goals}
    expanding=[frozenset(r["seed_types"]) for r in cert["profiles"] if protected in r["gained_permissions"]]
    local=any(p in probes for p in expanding)
    pairwise=any(len(p)<=2 or p in probes for p in expanding)
    derived=any(protected in r["new"]["derived_permissions"] and protected not in r["old"]["derived_permissions"] for r in cert["profiles"])
    dep=dependency_flag(contract,candidate,proposal)
    facts=dict(valid_edit=True,goal_satisfied=met,protected_expansion=expansion,goal_probe_detected=local,
        pairwise_detected=pairwise,derived_expansion=derived,dependency_flag=dep,
        witnesses=cert["expansion_witnesses"].get(protected,[]),profiles=len(cert["profiles"]))
    decisions={}
    for mode in MODES:
        reg=registry(contract,candidate,mode);approved=reg.matches(contract,candidate)
        decisions[mode]=dict(goal_only=met,current_goal=met and (not local or approved),
            pairwise=met and (not pairwise or approved),dependency_cone=met and (not dep or approved),
            checked=met and (not expansion or approved),derived_only_mutant=met and (not derived or approved),
            unbound_approval_mutant=met and (not expansion or any(r.approved for r in reg.records)))
    return candidate,facts,decisions
