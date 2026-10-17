import json
import pytest
from internal.benchmarks import ontology_adjudication as study
from internal.benchmarks import ontology_rigorous_proposals as cases


def unit(family,stratum):
    value=study.verified_unit(cases.instance(family,"test",132),stratum)
    return dict(value,unit_id="test-unit")


@pytest.mark.parametrize("family",["mission-chain","strict-conjunction","protected-conjunction","conflict-repair"])
def test_mutation_is_legal_and_subtle_but_fails_goal(family):
    u=unit(family,"subtle-goal-error")
    assert not u["independent_semantics"]["goal_satisfied"]
    for mode in study.MODES:assert not study.scenario(u,mode)["truth"]["release_allowed"]


def test_hidden_expansion_requires_exact_approval_and_does_not_change_goal_truth():
    u=unit("latent-triple","correct-hidden-expansion")
    ss=[study.scenario(u,m) for m in study.MODES]
    assert all(s["truth"]["goal_correct"] and s["truth"]["protected_expansion"] for s in ss)
    assert [s["truth"]["release_allowed"] for s in ss]==[False,True,False,False,False]


def test_denied_expansion_approval_is_not_a_veto_on_nonexpanding_edit():
    u=unit("nonexpanding-conflict-decoy","correct-nonexpanding")
    s=study.scenario(u,"denied")
    assert not s["truth"]["approval_matches"] and s["truth"]["release_allowed"]
    assert not u["independent_semantics"]["protected_expansion"]


def test_semantic_labels_ids_and_repeats_cannot_leak_into_request():
    u=unit("latent-pair","correct-hidden-expansion");u["unit_id"]="private-unit-label"
    s=study.scenario(u,"stale-base");original=study.request(u,s)
    altered=dict(u,stratum="private-stratum",family="private-family",independent_semantics={"goal_satisfied":"SECRET_VERDICT"})
    other=dict(s,truth={"release_allowed":"SECRET_ANSWER"},mode="private-mode",repeat_of="private-repeat")
    assert study.request(altered,other)==original
    packet=json.loads(original["messages"][-1]["content"].split("\n")[-1])
    assert set(packet)=={"contract","proposed_edit","current_bindings","trusted_approval_registry"}
    text=str(original)
    assert "private-unit-label" not in text and "SECRET_VERDICT" not in text and "SECRET_ANSWER" not in text


def test_reader_distinguishes_explicit_reject_from_unknown():
    verdict={k:False for k in study.FIELDS};assert study.parse(json.dumps(verdict))["verdict"]==verdict
    verdict["release_allowed"]=None;assert study.parse(json.dumps(verdict))["verdict"]["release_allowed"] is None


def test_longer_transport_timeout_preserves_original_default(tmp_path,monkeypatch):
    from internal.scripts.run_ontology_openrouter import Client
    from internal.benchmarks import ontology_openrouter as api
    monkeypatch.setattr(api,"load_key",lambda path:"placeholder-test-key")
    assert Client(tmp_path,{}).timeout_seconds==180
    assert Client(tmp_path,{},timeout_seconds=600).timeout_seconds==600


@pytest.mark.parametrize("raw",['{}','{"release_allowed":true}',None,'```json\n{}\n```',
    '{"goal_correct":true,"goal_correct":false}',json.dumps({k:1 for k in study.FIELDS})])
def test_malformed_verdict_never_becomes_release_approval(raw):
    assert study.parse(raw)["verdict"] is None
