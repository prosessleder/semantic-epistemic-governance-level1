import json
from copy import deepcopy
from pathlib import Path
from collections import Counter
import pytest
from internal.benchmarks import ontology_three_check as study
from internal.benchmarks import ontology_adjudication as blind
from internal.benchmarks import ontology_adjudication_metrics as metrics

PARENT=Path(__file__).resolve().parents[1]/'internal/research/glm-adjudication-receipts-2026-10-13/glm-adjudication-2026-10-13'

@pytest.fixture(scope='module')
def corpus():
    data=json.loads((PARENT/'dataset.json').read_text())
    data['scenarios']=[s for s in data['scenarios'] if s['repeat_of'] is None]
    return data

def row(truth):return dict(verdict=deepcopy(truth),raw_response=blind.cases.canonical(truth))

def correct_trajectories(data):
    return {s['scenario_id']:{a:[row(s['truth'])] for a in study.ARMS} for s in data['scenarios']}

def test_first_pass_blind_and_condition_order_balanced(corpus):
    units={u['unit_id']:u for u in corpus['units']}
    assert Counter(study.arm_order(s)[0] for s in corpus['scenarios'])=={a:240 for a in study.ARMS}
    for s in corpus['scenarios']:
        u=units[s['unit_id']]
        for arm in study.ARMS:assert study.request(u,s,arm,[],{'fake':'must not appear'})==blind.request(u,s)

def test_evidence_is_complete_and_does_not_supply_verdict_fields(corpus):
    for u in corpus['units']:
        s=next(s for s in corpus['scenarios'] if s['unit_id']==u['unit_id'] and s['mode']=='none')
        p=study.evidence(u,s)
        assert p['profiles_checked']==2**len(u['contract']['public_classes'])
        assert len({tuple(r['seed_types']) for r in p['complete_public_subset_table']})==p['profiles_checked']
        assert not set(blind.FIELDS).intersection(p)
        assert any(r['candidate_has_protected'] and not r['base_has_protected'] for r in p['complete_public_subset_table'])==s['truth']['protected_expansion']

def test_correction_conditions_do_not_cross_contaminate(corpus):
    u=corpus['units'][0];s=next(s for s in corpus['scenarios'] if s['unit_id']==u['unit_id'])
    p=study.evidence(u,s);h=[row(s['truth'])]
    a=study.request(u,s,'checker-evidence',h,p);b=study.request(u,s,'reflection-only',h,p)
    assert a['messages'][:3]==b['messages'][:3]
    assert blind.cases.canonical(p) in a['messages'][-1]['content']
    assert blind.cases.canonical(p) not in b['messages'][-1]['content']
    assert 'complete_public_subset_table' not in blind.cases.canonical(b)

def test_missing_content_is_explicit_and_not_repaired(corpus):
    u=corpus['units'][0];s=next(s for s in corpus['scenarios'] if s['unit_id']==u['unit_id'])
    h=[dict(verdict=None,raw_response=None)]
    p=study.request(u,s,'reflection-only',h,{})
    assert p['messages'][2]['content']=='No usable final judgment was returned.'

def test_fixed_denominators_recovery_and_regression(corpus):
    ts=correct_trajectories(corpus)
    s=next(s for s in corpus['scenarios'] if not s['truth']['release_allowed'] and s['truth']['goal_correct'])
    bad=row(s['truth']);bad['verdict']['protected_expansion']=False;bad['verdict']['permission_authorized']=True;bad['verdict']['release_allowed']=True
    ts[s['scenario_id']]={'checker-evidence':[bad,row(s['truth'])],'reflection-only':[bad,bad,bad]}
    allowed=next(s for s in corpus['scenarios'] if s['truth']['release_allowed'])
    missing=dict(verdict=None,raw_response=None)
    ts[allowed['scenario_id']]={a:[missing,row(allowed['truth'])] for a in study.ARMS}
    x=study.score(ts,corpus['scenarios'],corpus['units'],draws=100)
    assert x['arms']['checker-evidence'][0]['primary_release']['false_approvals']==1
    assert x['arms']['checker-evidence'][0]['correct_allowed']==191
    assert x['arms']['checker-evidence'][1]['primary_release']['false_approvals']==0
    assert x['arms']['checker-evidence'][1]['correct_allowed']==192
    assert x['arms']['checker-evidence'][1]['reached']==2
    assert x['arms']['checker-evidence'][1]['newly_complete']==2
    assert x['arms']['reflection-only'][2]['primary_release']['false_approvals']==1
    assert x['arms']['reflection-only'][2]['reached']==1
    for stages in x['arms'].values():
        for stage in stages:
            assert stage['primary_release']['forbidden']==288 and stage['primary_release']['allowed']==192
            assert stage['hidden_expansions']['forbidden']==128 and stage['goal_failures']['forbidden']==160

def test_reference_stopped_correct_answers_cannot_be_overwritten(corpus):
    ts=correct_trajectories(corpus);s=corpus['scenarios'][0]
    ts[s['scenario_id']]['checker-evidence'].append(row(s['truth']))
    with pytest.raises(AssertionError):study.score(ts,corpus['scenarios'],corpus['units'],draws=100)

def test_component_regressions_are_recorded(corpus):
    ts=correct_trajectories(corpus);s=next(s for s in corpus['scenarios'] if s['truth']['release_allowed'])
    first=row(s['truth']);first['verdict']['protected_expansion']=not first['verdict']['protected_expansion']
    second=row(s['truth']);second['verdict']['release_allowed']=False
    ts[s['scenario_id']]={a:[first,second,row(s['truth'])] for a in study.ARMS}
    x=study.score(ts,corpus['scenarios'],corpus['units'],draws=100)
    assert x['arms']['checker-evidence'][1]['correct_allowed']==191
    assert x['arms']['checker-evidence'][1]['regressed_scenarios']==1
    assert x['arms']['checker-evidence'][2]['correct_allowed']==192

def test_parent_four_measures_reconstruct(corpus):
    rows=[json.loads(x) for x in (PARENT/'records.jsonl').read_text().splitlines()];rows=[r for r in rows if r['repeat_of'] is None]
    assert metrics.release_metrics(rows)['false_approvals']==31
    assert metrics.release_metrics([r for r in rows if r['stratum']=='correct-hidden-expansion'])['false_approvals']==25
    assert metrics.release_metrics([r for r in rows if r['stratum']=='subtle-goal-error'])['false_approvals']==6
    assert sum(r['truth']['release_allowed'] and metrics.predicted(r,'release_allowed') is True for r in rows)==171

def test_lost_transport_repeats_identical_input_and_preserves_first_complete(tmp_path,monkeypatch):
    import io,http.client
    from internal.scripts import run_ontology_three_check as runner
    monkeypatch.setattr(runner.api,'load_key',lambda _: 'test-credential')
    monkeypatch.setattr(runner.time,'sleep',lambda _:None)
    sent=[]
    value=dict(model=runner.api.MODEL,provider=runner.api.PROVIDER,choices=[dict(message=dict(content='not-json'))],
        usage=dict(prompt_tokens=3,completion_tokens=10,total_tokens=13,cost=.0001))
    def call(req,timeout):
        sent.append(req.data)
        if len(sent)==1:raise http.client.IncompleteRead(b' ')
        return io.BytesIO(json.dumps(value).encode())
    monkeypatch.setattr(runner.urllib.request,'urlopen',call)
    plan=dict(endpoint=dict(pricing=dict(prompt=.00000015,completion=.0000005)),reported_budget_usd=1,transport_retries=2,timeout_seconds=600)
    client=runner.Client(tmp_path,plan);body=dict(max_tokens=8192,messages=[])
    assert client.call('one',body)==value
    assert sent[0]==sent[1] and len(sent)==2 and client.unknown_bound>0
    assert client.call('one',body)==value and len(sent)==2
    assert runner.read(tmp_path/'attempts/one/0.end.json')['status']=='lost-response'
    assert runner.read(tmp_path/'attempts/one/1.end.json')['status']=='complete'
    assert blind.parse(value['choices'][0]['message']['content'])['verdict'] is None

def test_transport_resume_cannot_replace_a_complete_model_answer(tmp_path,monkeypatch):
    from internal.scripts import run_ontology_three_check as runner
    monkeypatch.setattr(runner.api,'load_key',lambda _: 'test-credential')
    value=dict(usage=dict(cost=.1));body=dict(max_tokens=8192,messages=[])
    runner.write(tmp_path/'requests/one.json',body);runner.write(tmp_path/'responses/one.json',value)
    client=runner.Client(tmp_path,dict())
    assert client.call('one',body)==value
    with pytest.raises(AssertionError):client.call('one',dict(body,max_tokens=4096))
