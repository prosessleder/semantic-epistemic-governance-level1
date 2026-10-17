from dataclasses import replace
import pytest
from ontology_boundary.checked_release import ReviewContract, apply_proposal, goals_satisfied
from ontology_boundary.oracle import PERMISSIONS, closure, seed_profiles
from ontology_boundary.proposal_commit import commit_frame
from internal.benchmarks.ontology_rigorous_proposals import dataset, instance, renamed, canonical, FAMILIES
from internal.benchmarks.ontology_rigorous_review import evaluate, ground, registry, MODES
from internal.benchmarks.ontology_rigorous_lifecycle import sequences


def test_fresh_splits_group_by_input_structure_and_semantic_tables():
    data=dataset();all_cases=data["dev"]+data["test"]
    assert len(data["dev"])==48 and len(data["test"])==192
    assert len({t["structural_fingerprint"] for t in all_cases})==240
    assert len({t["semantic_fingerprint"] for t in all_cases})==240
    assert {t["family"] for t in all_cases}==set(FAMILIES)
    assert max(t["depth"] for t in data["dev"]) < min(t["depth"] for t in data["test"])


@pytest.mark.parametrize("family",FAMILIES)
def test_references_have_independent_ground_agreement_and_alias_invariance(family):
    t=instance(family,"test",1);c=ReviewContract.from_dict(t["contract"])
    candidate,facts,decisions=evaluate(c,t["reference_patch"])
    if candidate is None:
        assert t["expected_abstain"] and not any(decisions[m]["checked"] for m in MODES)
    else:
        other=ground(c,candidate)
        for key in ("goal_satisfied","protected_expansion","goal_probe_detected","pairwise_detected","derived_expansion","profiles"):
            assert facts[key]==other[key]
        assert facts["goal_satisfied"] and decisions["exact"]["checked"]
    aliased=renamed(t);a=ReviewContract.from_dict(aliased["contract"]);mapping=aliased["alias_mapping"]
    for p in seed_profiles(c.public_classes):
        for old,new in ((c.base,a.base),(candidate,apply_proposal(a,aliased["reference_patch"]))):
            if old is None:continue
            x,y=closure(old,p),closure(new,{mapping[x] for x in p})
            assert x.permissions==y.permissions and x.consistent==y.consistent


def test_pairwise_probes_miss_three_type_expansion_but_full_guard_holds_it():
    t=instance("latent-triple","test",0);c=ReviewContract.from_dict(t["contract"])
    _,facts,decisions=evaluate(c,t["reference_patch"])
    assert facts["protected_expansion"] and not facts["pairwise_detected"]
    assert decisions["none"]["pairwise"] and not decisions["none"]["checked"]


def test_dependency_cone_can_overhold_a_nonexpanding_change():
    t=instance("nonexpanding-conflict-decoy","test",0);c=ReviewContract.from_dict(t["contract"])
    _,facts,decisions=evaluate(c,t["reference_patch"])
    assert not facts["protected_expansion"] and facts["derived_expansion"]
    assert decisions["none"]["checked"] and not decisions["none"]["dependency_cone"]


def test_derived_only_mutant_misses_effective_permission_restored_by_repair():
    t=instance("conflict-repair","test",0);c=ReviewContract.from_dict(t["contract"])
    _,facts,d=evaluate(c,t["reference_patch"])
    assert facts["protected_expansion"] and not facts["derived_expansion"]
    assert d["none"]["derived_only_mutant"] and not d["none"]["checked"]


@pytest.mark.parametrize("slot",range(4))
def test_wrong_query_binding_is_rejected_for_every_rotated_permission(slot):
    t=instance("protected-chain","test",slot);c=ReviewContract.from_dict(t["contract"])
    candidate,facts,d=evaluate(c,t["reference_patch"])
    assert c.protected_permission==PERMISSIONS[slot]
    assert not registry(c,candidate,"wrong-query").matches(c,candidate)
    assert not d["wrong-query"]["checked"] and d["wrong-query"]["unbound_approval_mutant"]


def test_empty_seed_goal_cannot_be_repaired_by_positive_nonempty_rules():
    t=instance("unsatisfiable-empty","test",0);c=ReviewContract.from_dict(t["contract"])
    atoms=sorted(c.base.classes)
    for obj in [dict(op="add_edge",left=atoms[0],right=atoms[1]),
                dict(op="add_rule",antecedents=[atoms[0]],head=atoms[1]),
                dict(op="add_disjoint",left=atoms[0],right=atoms[1])]:
        try:candidate=apply_proposal(c,obj)
        except ValueError:continue
        assert not goals_satisfied(c,candidate) and not closure(candidate,set()).class_types


def test_safe_isolated_edits_can_expand_when_composed_and_stale_commit_rejects():
    samples=sequences()
    for family in {x["family"] for x in samples}:
        t=next(x for x in samples if x["family"]==family)
        a=ReviewContract.from_dict(t["first_contract"]);b=ReviewContract.from_dict(t["second_contract"])
        state,first=commit_frame(a.base,a,canonical(t["first_patch"]))
        assert first["admitted"]
        unchanged,stale=commit_frame(state,b,canonical(t["second_patch"]))
        assert not stale["admitted"] and unchanged==state
        fresh=replace(b,base=state);candidate,facts,decisions=evaluate(fresh,t["second_patch"])
        assert facts["protected_expansion"]==t["expected_composed_expansion"]
        assert decisions["none"]["checked"]==(not t["expected_composed_expansion"])
        final,receipt=commit_frame(state,fresh,canonical(t["second_patch"]),registry(fresh,candidate,"exact"))
        assert receipt["admitted"] and final==candidate


@pytest.mark.parametrize("raw",['"abstain","extra":NaN}', '"abstain","op":"add_edge"}', '"abstain"'])
def test_direct_transport_rejects_nonfinite_duplicate_or_incomplete_objects(raw):
    from internal.scripts.run_ontology_rigorous_benchmark import parse
    assert parse("direct",raw)["proposal"] is None


def test_native_partial_continuation_retains_system_instruction():
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import WhitespaceSplit
    from transformers import PreTrainedTokenizerFast
    from internal.scripts.run_ontology_rigorous_benchmark import encode
    engine=Tokenizer(WordLevel({"[UNK]":0,"<s>":1,"</s>":2},unk_token="[UNK]"));engine.pre_tokenizer=WhitespaceSplit()
    tok=PreTrainedTokenizerFast(tokenizer_object=engine,unk_token="[UNK]",bos_token="<s>",eos_token="</s>")
    # Minimal fixture reproducing the observed template's last-user condition.
    tok.chat_template="""{% if messages[0]['role']=='system' %}{% set system=messages[0]['content'] %}{% set rest=messages[1:] %}{% else %}{% set system='' %}{% set rest=messages %}{% endif %}<s>{% for m in rest %}{% if m['role']=='user' %}[INST]{% if loop.last %}{{system}}\n\n{% endif %}{{m['content']}}[/INST]{% else %} {{m['content']}}</s>{% endif %}{% endfor %}"""
    job=dict(group="dev",arm="direct",task=instance("mission-chain","dev",0))
    with pytest.raises(AssertionError,match="dropped the system"):
        encode(tok,job)
    text,ids=encode(tok,job,"mistral")
    assert "You have no approval or release authority." in text and ids


@pytest.mark.parametrize("family",["mission-chain","protected-chain","latent-pair","latent-triple","latent-cycle"])
def test_direct_single_actor_shortcut_does_not_satisfy_both_cohorts(family):
    t=instance(family,"test",0);c=ReviewContract.from_dict(t["contract"])
    target=c.goals[0].target
    if c.goals[0].kind=="effective":target=next(a for a,b in c.base.subclass if b==target)
    candidate=apply_proposal(c,dict(op="add_edge",left="P1",right=target))
    assert not goals_satisfied(c,candidate)


def test_impossible_controls_and_replayed_approval_modes_do_not_inflate_utility():
    from internal.scripts.summarize_ontology_rigorous_benchmark import summarize,resampled_means
    rows=[]
    for task in dataset()["dev"]:
        _,facts,decisions=evaluate(ReviewContract.from_dict(task["contract"]),task["reference_patch"])
        rows.append(dict(expected_abstain=task["expected_abstain"],facts=facts,decisions=decisions,
            parse_error=None,hit_cap=False,correct_abstain=task["expected_abstain"],family=task["family"],seconds=0))
    result=summarize(rows)
    assert result["requests"]==48 and result["achievable_n"]==44 and result["useful_edits"]==44
    assert result["impossible_n"]==result["correct_abstentions"]==4
    assert result["pipelines"]["checked"]["observations"]==432
    assert all(resampled_means(rows)==1)


def test_wrong_basis_stays_invalid_when_every_current_public_type_is_in_goals():
    for slot in range(40):
        task=instance("strict-conjunction","test",slot);c=ReviewContract.from_dict(task["contract"])
        used=set().union(*c.current_profiles,*(g.profile for g in c.goals))
        if used==c.public_classes:break
    else:raise AssertionError("full-basis fixture absent")
    candidate=apply_proposal(c,task["reference_patch"])
    assert not registry(c,candidate,"wrong-basis").matches(c,candidate)
