import json
from copy import deepcopy
from pathlib import Path
import pytest
from internal.scripts import run_ontology_openai_three_check as runner
from internal.benchmarks import ontology_three_check as study


def plan(alias):
    c=runner.CONFIGS[alias]
    return dict(config=c,settings=runner.settings(c),model=dict(canonical_slug=c['model']+'-dated'))


@pytest.mark.parametrize('alias',['gpt61sol','gpt6luna','gpt56terra'])
def test_thinking_provider_and_allowance_frozen(alias):
    p=plan(alias);s=p['settings']
    assert s['max_tokens']==8192
    assert 'temperature' not in s
    assert s['reasoning'].get('enabled',True) and s['reasoning'].get('effort')!='none'
    assert s['reasoning']['exclude'] is False
    assert s['provider']==dict(only=[p['config']['tag']],allow_fallbacks=False,require_parameters=True)


def test_messages_match_glm_for_initial_and_both_histories():
    root=Path(__file__).resolve().parents[1]
    data=json.loads((root/'internal/research/glm-adjudication-receipts-2026-10-13/glm-adjudication-2026-10-13/dataset.json').read_text())
    u=data['units'][0];s=next(s for s in data['scenarios'] if s['unit_id']==u['unit_id'])
    packet=study.evidence(u,s)
    for alias in runner.CONFIGS:
        for arm in study.ARMS:
            history=[]
            for _ in range(3):
                assert runner.request(plan(alias),u,s,arm,history,packet)['messages']==study.request(u,s,arm,history,packet)['messages']
                history.append(dict(raw_response='{}',verdict=None,private_reasoning='MUST NOT APPEAR'))
            assert 'MUST NOT APPEAR' not in json.dumps(runner.request(plan(alias),u,s,arm,history[:2],packet))


def response(p):
    return dict(model=p['config']['model'],provider=p['config']['provider'],
        choices=[dict(message=dict(content='{}'))],usage=dict(prompt_tokens=3,completion_tokens=5,total_tokens=8,cost=.01))


def test_sole_fence_is_transport_and_content_is_never_repaired():
    raw=json.dumps(dict(goal_correct=True,protected_expansion=False,approval_matches=False,permission_authorized=True,release_allowed=True))
    bare=runner.parse_content(raw)
    fenced=runner.parse_content('```json\n'+raw+'\n```')
    assert bare['verdict']==fenced['verdict'] and fenced['sole_fence_removed']
    assert fenced['strict_parse_error'] is not None and fenced['parse_error'] is None
    for bad in ['Here is the answer:\n```json\n'+raw+'\n```','```json\n'+raw+'\n```\nExtra','```json\n'+raw[:-1]+',"goal_correct":false}\n```','```json\n'+raw+'\n'+raw+'\n```']:
        assert runner.parse_content(bad)['verdict'] is None


@pytest.mark.parametrize('alias',['gpt61sol','gpt6luna','gpt56terra'])
def test_response_identity_usage_and_no_provider_substitution(alias):
    p=plan(alias);v=response(p)
    assert runner.validate_response(v,p)[1]['total_tokens']==8
    dated=deepcopy(v);dated['model']=p['model']['canonical_slug'];runner.validate_response(dated,p)
    for key,value in [('provider','Another provider'),('model','another/model')]:
        bad=deepcopy(v);bad[key]=value
        with pytest.raises(ValueError):runner.validate_response(bad,p)
    for key,value in [('cost',float('nan')),('total_tokens',7),('prompt_tokens',True)]:
        bad=deepcopy(v);bad['usage'][key]=value
        with pytest.raises(ValueError):runner.validate_response(bad,p)


def test_native_schema_has_no_semantic_answers():
    s=runner.settings(runner.CONFIGS['gpt61sol'])
    schema=s['response_format']['json_schema']['schema']
    assert set(schema['required'])==set(runner.blind.FIELDS)
    assert schema['additionalProperties'] is False
    assert all(v==dict(type=['boolean','null']) for v in schema['properties'].values())
    assert s['reasoning']['enabled'] is True
