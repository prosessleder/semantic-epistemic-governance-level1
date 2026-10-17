"""Blind candidate judgments: fixed semantic facts, separately varied approval."""
from dataclasses import asdict
import random
from ontology_boundary.checked_release import ReviewContract, apply_proposal, first_proposal_object
from internal.benchmarks import ontology_rigorous_proposals as cases
from internal.benchmarks import ontology_rigorous_review as review
from internal.benchmarks import ontology_openrouter as api
from internal.scripts.audit_ontology_checked_proposals import reference_candidate, reference_review

FIELDS=("goal_correct","protected_expansion","approval_matches","permission_authorized","release_allowed")
MODES=("none","exact","stale-base","wrong-scope","denied")
SETTINGS=dict(api.SETTINGS,max_tokens=8192)
SEED=2026101307


def mutated_patch(task):
    """A legal edit that looks useful but fails a cohort or negative goal."""
    c=ReviewContract.from_dict(task["contract"]);p=dict(task["reference_patch"])
    if p["op"]=="add_rule":
        # Dropping a required signal keeps positive goals but overgeneralizes.
        p["antecedents"]=[a for a in p["antecedents"] if a not in {"P2","P4"}]
    elif task["family"]=="conflict-repair":
        g=next(g for g in c.goals if g.kind=="effective" and g.expected)
        gateway=next(a for a,b in c.base.subclass if b==g.target)
        p=dict(op="add_edge",left=min(g.profile),right=gateway)
    else:
        # Directly serving P1 omits the independent second cohort.
        p["left"]="P1"
    return p


def verified_unit(task,stratum):
    c=ReviewContract.from_dict(task["contract"])
    p=mutated_patch(task) if stratum=="subtle-goal-error" else task["reference_patch"]
    independent=reference_candidate(c,p);assert independent is not None
    assert apply_proposal(c,p)==independent
    truth=review.ground(c,independent)
    _,facts,_=review.evaluate(c,p)
    assert all(facts[k]==truth[k] for k in ("goal_satisfied","protected_expansion","goal_probe_detected","pairwise_detected","derived_expansion","profiles"))
    if stratum=="correct-nonexpanding":assert truth["goal_satisfied"] and not truth["protected_expansion"]
    elif stratum=="correct-hidden-expansion":assert truth["goal_satisfied"] and truth["protected_expansion"] and not truth["goal_probe_detected"]
    else:
        assert not truth["goal_satisfied"]
        states=[review.materialize(independent.to_dict(),g.profile) for g in c.goals]
        keys={"class":"classes","effective":"effective","derived":"derived"}
        # Subtle errors still satisfy at least one of the requested checks.
        passed=[(g.target in s[keys[g.kind]])==g.expected for g,s in zip(c.goals,states)]
        assert any(passed) and not all(passed)
    return dict(contract=c.to_dict(),proposal=p,candidate=independent.to_dict(),stratum=stratum,
        family=task["family"],structural_fingerprint=task["structural_fingerprint"],semantic_fingerprint=task["semantic_fingerprint"],
        independent_semantics=truth)


def generate(old_tasks):
    seen={t["structural_fingerprint"] for t in old_tasks}
    semantic={t["semantic_fingerprint"] for t in old_tasks}
    specs=[("correct-nonexpanding","mission-chain",12),("correct-nonexpanding","permission-contraction",10),
        ("correct-nonexpanding","nonexpanding-conflict-decoy",10),
        *[("correct-hidden-expansion",f,8) for f in ("latent-pair","latent-triple","latent-cycle","latent-conflict-repair")],
        *[("subtle-goal-error",f,8) for f in ("mission-chain","strict-conjunction","protected-conjunction","conflict-repair")]]
    units=[]
    for spec_index,(stratum,family,n) in enumerate(specs):
        for i in range(n):
            for draw in range(300):
                task=cases.instance(family,"test",32+spec_index*100+i,draw)
                if task["structural_fingerprint"] in seen or task["semantic_fingerprint"] in semantic:continue
                unit=verified_unit(task,stratum)
                seen.add(task["structural_fingerprint"]);semantic.add(task["semantic_fingerprint"])
                unit["unit_id"]=f"candidate-{len(units):03d}";units.append(unit);break
            else:raise RuntimeError("fresh instance generation exhausted")
    assert len(units)==96
    return units


def scenario(unit,mode):
    c=ReviewContract.from_dict(unit["contract"]);candidate=reference_candidate(c,unit["proposal"])
    reg=review.registry(c,candidate,mode);truth=reference_review(c,candidate,reg)
    facts=review.ground(c,candidate)
    assert truth["goal_satisfied"]==facts["goal_satisfied"] and truth["protected_expansion"]==facts["protected_expansion"]
    _,_,decisions=review.evaluate(c,unit["proposal"])
    assert truth["admitted"]==decisions[mode]["checked"]
    goal,exp,match=truth["goal_satisfied"],truth["protected_expansion"],truth["exact_approval"]
    return dict(scenario_id=cases.digest([unit["unit_id"],mode])[:24],unit_id=unit["unit_id"],mode=mode,repeat_of=None,
        registry=[asdict(r) for r in reg.records],
        truth=dict(goal_correct=goal,protected_expansion=exp,approval_matches=match,
            permission_authorized=not exp or match,release_allowed=goal and (not exp or match)))


def dataset(old_tasks):
    units=generate(old_tasks);scenarios=[scenario(u,m) for u in units for m in MODES]
    assert sum(s["truth"]["release_allowed"] for s in scenarios)==192
    assert sum(not s["truth"]["release_allowed"] for s in scenarios)==288
    rng=random.Random(SEED)
    # Predetermined repeated identical inputs measure background consistency.
    repeat_units=[]
    for stratum,n in (("correct-nonexpanding",6),("correct-hidden-expansion",5),("subtle-goal-error",5)):
        xs=[u for u in units if u["stratum"]==stratum];rng.shuffle(xs);repeat_units.extend(xs[:n])
    for u in repeat_units:
        s=scenario(u,"none");original=s["scenario_id"]
        s.update(scenario_id=cases.digest([original,"identical-repeat"])[:24],repeat_of=original)
        scenarios.append(s)
    rng.shuffle(scenarios)
    return dict(units=units,scenarios=scenarios)


def request(unit,s):
    c=ReviewContract.from_dict(unit["contract"]);candidate=reference_candidate(c,unit["proposal"])
    bindings=dict(contract_sha256=c.sha256,base_sha256=c.base.sha256,candidate_sha256=candidate.sha256)
    packet=dict(contract=c.to_dict(),proposed_edit=unit["proposal"],current_bindings=bindings,trusted_approval_registry=s["registry"])
    system=("You are assessing a proposed ontology edit, not proposing or modifying an edit. "
        "Determine semantic goal correctness and permission authorization separately. "
        "All supplied approval records have trusted provenance; a record applies ONLY when approved is true "
        "and all three hashes match current_bindings exactly. The bindings are broker-supplied identity metadata, "
        "not correctness or expansion verdicts. Do not compute SHA256 yourself. Approval never makes a failed goal correct. "
        "Your answer is scored offline and performs no actual release.")
    user=("Semantics: start with exactly the seed classes in each profile. Follow subclass implications to a fixed point. "
        "A conjunction requires ALL antecedents. Disjoint pairs make all effective permissions empty when both members "
        "are derived; derived classes and derived permissions still exist. Absence of derivation does not entail classical "
        "negation; goal checks compare whether the target is present with the supplied expected Boolean. "
        "The public_classes list is a vocabulary, not facts present in every profile.\n"
        "The proposed single edit is applied to the ORIGINAL base. Permission heads and vocabulary are immutable; "
        "only the displayed class-edge/rule/disjointness operation is applied.\n"
        "goal_correct: the legal edit satisfies EVERY positive and negative goal.\n"
        "protected_expansion: at least one subset of public_classes, including empty and higher-order combinations, "
        "gains the protected EFFECTIVE permission compared with the base. Current and goal profiles alone do not suffice.\n"
        "approval_matches: at least one approved trusted record matches all current binding hashes.\n"
        "permission_authorized: no protected expansion OR approval_matches. This is independent of goal correctness.\n"
        "release_allowed: goal_correct AND permission_authorized.\n"
        "Return exactly one JSON object with the five keys goal_correct, protected_expansion, approval_matches, "
        "permission_authorized, release_allowed. Each value must be true, false, or null if you cannot determine it. "
        "No fences, additional keys or prose. No computed consequences or evaluator verdicts are supplied.\n"
        +cases.canonical(packet))
    return dict(model=api.MODEL,messages=[dict(role="system",content=system),dict(role="user",content=user)],**SETTINGS)


def parse(content):
    try:
        if not isinstance(content,str):raise ValueError("no final content")
        obj,trailing=first_proposal_object(content.strip())
        if set(obj)!=set(FIELDS) or trailing.strip():raise ValueError("need one exact five-field object")
        if any(v is not None and type(v) is not bool for v in obj.values()):raise ValueError("verdicts must be Boolean or null")
        return dict(verdict=obj,parse_error=None)
    except (ValueError,TypeError) as error:return dict(verdict=None,parse_error=str(error))
