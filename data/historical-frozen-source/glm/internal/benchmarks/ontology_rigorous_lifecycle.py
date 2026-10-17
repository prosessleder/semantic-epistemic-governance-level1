"""Two edits safe on one snapshot can expand authority when composed."""
from dataclasses import replace
import random
from ontology_boundary.oracle import PERMISSIONS, HornRule, compare_ontologies
from ontology_boundary.checked_release import ReviewContract, Goal, apply_proposal, goals_satisfied
from internal.benchmarks.ontology_rigorous_proposals import Builder, SEED, structural_fingerprint, digest

FAMILIES = ("composed-pair-expansion", "composed-triple-expansion", "composed-nonexpanding-control")


def sequences():
    result=[];seen=set()
    for fi,family in enumerate(FAMILIES):
        for slot in range(16):
            for attempt in range(300):
                rng=random.Random(SEED+10000000+fi*100000+slot*1009+attempt*7919)
                public=frozenset(f"P{i}" for i in range(rng.choice((5,6))))
                b=Builder(rng,public);gm,gb,ga,gr=b.h(),b.h(),b.h(),b.h()
                protected=PERMISSIONS[slot%4]
                mission="can_write_body" if protected!="can_write_body" else "can_write_metadata"
                observer=next(p for p in PERMISSIONS if p not in (protected,mission))
                b.edges += [(gm,protected),(gb,mission),(gr,observer),("P0",gr)]
                extra={"P3"} if family=="composed-triple-expansion" else set()
                b.rules.append(HornRule(frozenset({gb,ga}|extra),gm))
                first=b.broken_path("P1",gb,rng.randint(4,6))
                second=b.broken_path("P2",ga,rng.randint(4,6))
                witness=frozenset({"P1","P2"}|extra)
                if family=="composed-nonexpanding-control":b.disjoint.append(("P1","P2"))
                b.background(gm,witness-{"P1"},4)
                base=b.ontology()
                c1=ReviewContract(base,public,protected,(Goal(frozenset({"P1"}),"effective",mission),))
                c2=ReviewContract(base,public,protected,(Goal(frozenset({"P2"}),"class",ga),))
                a,b2=apply_proposal(c1,first),apply_proposal(c2,second)
                assert goals_satisfied(c1,a) and goals_satisfied(c2,b2)
                assert compare_ontologies(base,a,public,protected_permissions=[protected])["protected_no_expansion"]
                assert compare_ontologies(base,b2,public,protected_permissions=[protected])["protected_no_expansion"]
                fresh=replace(c2,base=a);merged=apply_proposal(fresh,second)
                cert=compare_ontologies(a,merged,public,protected_permissions=[protected])
                expected=family!="composed-nonexpanding-control"
                assert (not cert["protected_no_expansion"])==expected
                assert goals_satisfied(c1,merged) and goals_satisfied(fresh,merged)
                fp=digest([structural_fingerprint(c1),structural_fingerprint(c2)])
                if fp in seen:continue
                seen.add(fp)
                result.append(dict(sequence_id=f"sequence-{fi:02d}-{slot:02d}",family=family,
                    first_contract=c1.to_dict(),second_contract=c2.to_dict(),first_patch=first,second_patch=second,
                    expected_composed_expansion=expected,structural_fingerprint=fp))
                break
            else:raise RuntimeError("lifecycle grouping exhausted")
    assert len(result)==48
    return result
