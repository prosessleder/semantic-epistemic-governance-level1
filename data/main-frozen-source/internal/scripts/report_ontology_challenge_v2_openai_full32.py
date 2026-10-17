#!/usr/bin/env python3
"""Independently reconstruct a completed two-track development pilot. No API calls."""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from internal.scripts import run_ontology_challenge_v2_openai_full32 as pilot
from internal.scripts import run_ontology_epistemic_sources as transport
from internal.benchmarks import ontology_epistemic_challenge_v2 as epi
from internal.benchmarks import ontology_semantic_challenge_v2 as sem


def parse_native(raw, fence=False):
    if not isinstance(raw, str):
        return None, 'missing final text', False
    removed = False
    if fence:
        match = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', raw.strip(), re.S)
        if match:
            raw, removed = match[1], True
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('nonfinite JSON constant')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid), None, removed
    except (ValueError, TypeError) as error:
        return None, str(error), removed


def reconstructed(run):
    plan, cases = pilot.validate(run)
    assert transport.read(run/'dev-completion.json')['status'] == 'COMPLETE'
    assert transport.read(run/'train-completion.json')['status'] == 'COMPLETE'
    assert len(list((run/'responses').glob('*.json'))) == 150
    rows = []
    for case in cases:
        pilot.check_reference(case)
        name = case['id']
        body = transport.read(run/'requests'/f'{name}.json')
        assert body == transport.read(run/'frozen-requests'/f'{name}.json')
        assert transport.digest(body) == plan['requests'][name]
        native_path = run/'responses'/f'{name}.json'
        native = transport.read(native_path)
        choice, usage = transport.validate_response(native, plan)
        ends = sorted((run/'attempts'/name).glob('*.end.json'))
        complete = [p for p in ends if transport.read(p)['status'] == 'complete']
        assert len(complete) == 1 and len(ends) <= 3
        receipt = transport.read(complete[0])
        attempt = complete[0].name.split('.')[0]
        raw_path = run/'raw-responses'/f'{name}--{attempt}.body'
        assert transport.sha(raw_path) == receipt['raw_response_sha256']
        assert transport.read(raw_path) == native
        assert transport.sha(native_path) == receipt['response_sha256']
        saved = transport.read(run/'judgments'/f'{name}.json')
        assert saved['final_text'] == choice['message'].get('content')
        assert saved['response_sha256'] == transport.sha(native_path)
        assert saved['usage'] == usage
        output = {}
        for sensitivity in [False, True]:
            answer, error, removed = parse_native(choice['message'].get('content'), sensitivity)
            scored = {} if error else (epi.score(case['case']['input'], answer) if case['track']=='epistemic' else sem.score_answer(case['case'], answer))
            key = 'framing_sensitivity' if sensitivity else 'primary'
            assert saved[key]['answer'] == answer
            assert saved[key]['score'] == scored
            output[key] = dict(answer=answer, parse_error=error, score=scored, sole_fence_removed=removed)
        rows.append(dict(id=name, case_id=case['case_id'], split=case['split'], track=case['track'],
            tier=case['tier'], unit_id=case['unit_id'], reference=case['case'].get('reference',case['case'].get('truth')),
            variant=case['case'].get('variant'), presentation=case['case'].get('presentation'),
            usage=usage, finish_reason=choice.get('finish_reason'), provider_error=choice.get('error'),
            native_reasoning_observed=transport.has_reasoning(native),
            request_sha256=transport.digest(body), response_sha256=transport.sha(native_path), **output))
    return plan, rows


def summary(rows, sensitivity=False):
    key = 'framing_sensitivity' if sensitivity else 'primary'
    counts = Counter(cases=len(rows), full_correct=0, parse_errors=0, invalid_schema=0,
        token_limits=0, provider_error_finishes=0, decision_denominator=0, decision_correct=0,
        allow_denominator=0, justified_allow=0, deny_denominator=0, allow_on_deny=0,
        unknown_denominator=0, allow_on_unknown=0, correct_abstention=0,
        determinate_denominator=0, unnecessary_abstention=0)
    fields = Counter()
    support = Counter(tp=0, fp=0, fn=0)
    query_regrets = []
    query_cost_regrets = []
    for row in rows:
        p = row[key];answer,score=p['answer'],p['score'];track=row['track']
        counts['full_correct'] += bool(score.get('all_correct',score.get('correct',False)))
        counts['parse_errors'] += p['parse_error'] is not None
        valid = score.get('valid_format', 'fields' in score)
        counts['invalid_schema'] += p['parse_error'] is None and not valid
        counts['token_limits'] += row['finish_reason']=='length'
        counts['provider_error_finishes'] += row['finish_reason']=='error' or bool(row.get('provider_error'))
        if track=='epistemic':
            truth=row['reference']['example_answer']['decisions']
            predictions=answer['decisions'] if valid else {}
            expected_facts={(x['atom'],x['value']) for x in row['reference']['example_answer']['supported_facts']}
            predicted_facts={(x['atom'],x['value']) for x in answer['supported_facts']} if valid else set()
            support['tp']+=len(expected_facts & predicted_facts)
            support['fp']+=len(predicted_facts - expected_facts)
            support['fn']+=len(expected_facts - predicted_facts)
            if 'query_uncertainty_regret' in score:query_regrets.append(score['query_uncertainty_regret'])
            if score.get('query_cost_regret_if_equal_uncertainty') is not None:query_cost_regrets.append(score['query_cost_regret_if_equal_uncertainty'])
            for name in ['supported_facts_correct','repair_correct','decisions_correct','possibilities_correct','query_optimal']:
                fields[name] += bool(score.get(name,False))
        else:
            truth={'release':'allow' if row['reference']['release_allowed'] else 'deny'}
            predictions={'release':'allow' if answer['release_allowed'] else 'deny'} if valid else {}
            for name,value in score.get('fields',{}).items():fields[name]+=bool(value)
        for action,expected in truth.items():
            predicted=predictions.get(action)
            counts['decision_denominator']+=1
            counts['decision_correct']+=predicted==expected
            counts['allow_denominator']+=expected=='allow'
            counts['justified_allow']+=expected==predicted=='allow'
            counts['deny_denominator']+=expected=='deny'
            counts['allow_on_deny']+=expected=='deny' and predicted=='allow'
            counts['unknown_denominator']+=expected=='undetermined'
            counts['allow_on_unknown']+=expected=='undetermined' and predicted=='allow'
            counts['correct_abstention']+=expected==predicted=='undetermined'
            counts['determinate_denominator']+=expected!='undetermined'
            counts['unnecessary_abstention']+=expected!='undetermined' and predicted=='undetermined'
    result=dict(counts)
    result['fields_correct']=dict(fields)
    result['supported_fact_micro']=dict(support,
        precision=support['tp']/(support['tp']+support['fp']) if support['tp']+support['fp'] else None,
        recall=support['tp']/(support['tp']+support['fn']) if support['tp']+support['fn'] else None)
    result['query_regret']=dict(scored_offered_queries=len(query_regrets),
        mean_unresolved_actions_above_optimum=sum(query_regrets)/len(query_regrets) if query_regrets else None,
        equal_uncertainty_cost_comparisons=len(query_cost_regrets),
        mean_extra_cost_when_equal_uncertainty=sum(query_cost_regrets)/len(query_cost_regrets) if query_cost_regrets else None,
        limitation='Regret is conditional on returning an offered query for an unresolved case. Invalid queries and malformed responses remain failures in optimal-query accuracy.')
    result['full_accuracy']=counts['full_correct']/len(rows) if rows else None
    result['decision_accuracy']=counts['decision_correct']/counts['decision_denominator'] if counts['decision_denominator'] else None
    result['scoring_note']='Per-action scores require a complete valid typed answer schema; malformed responses remain errors. Supported-fact, repair, query and witness measures remain separate.'
    return result


def paired_epistemic(rows):
    xs=[r for r in rows if r['split']=='dev' and r['track']=='epistemic']
    grouped=defaultdict(dict)
    for row in xs:grouped[row['unit_id']][row['variant'],row['presentation']]=row
    order=dict(pairs=0,both_valid=0,identical_decisions=0,both_correct_decisions=0)
    contrasts={k:dict(action_pairs=0,expected_changed=0,both_correct_on_changed=0,expected_unchanged=0,both_correct_on_unchanged=0) for k in ['authority','provenance','both']}
    def decision(row):
        p=row['primary'];return p['answer']['decisions'] if p['score'].get('valid_format') else None
    for unit,rs in grouped.items():
        assert len(rs)==8
        for variant in range(4):
            a,b=rs[variant,'original'],rs[variant,'reordered'];x,y=decision(a),decision(b)
            order['pairs']+=1;order['both_valid']+=x is not None and y is not None
            order['identical_decisions']+=x is not None and x==y
            order['both_correct_decisions']+=bool(a['primary']['score'].get('decisions_correct') and b['primary']['score'].get('decisions_correct'))
        for name,variant in [('authority',1),('provenance',2),('both',3)]:
            a,b=rs[0,'original'],rs[variant,'original'];x,y=decision(a),decision(b)
            ta,tb=a['reference']['example_answer']['decisions'],b['reference']['example_answer']['decisions']
            for action in ta:
                changed=ta[action]!=tb[action];c=contrasts[name];c['action_pairs']+=1
                c['expected_changed' if changed else 'expected_unchanged']+=1
                c['both_correct_on_changed' if changed else 'both_correct_on_unchanged']+=bool(x is not None and y is not None and x[action]==ta[action] and y[action]==tb[action])
    return dict(units=len(grouped),presentation=order,controlled_contrasts=contrasts,
        limitation='Descriptive matched development comparisons; shared units and twins are not independent trials.')


def report(run, output):
    plan,rows=reconstructed(run)
    unknown=[]
    for p in (run/'attempts').glob('*/*.begin.json'):
        end=p.with_name(p.name.replace('.begin','.end'))
        if not end.exists() or transport.read(end)['status']!='complete':unknown.append(p)
    result=dict(status='PASS',development_only=True,model=plan['config']['model'],alias=plan['alias'],
        plan_sha256=transport.sha(run/'execution-plan.json'),reporter_sha256=transport.sha(Path(__file__)),
        independently_reconstructed=150,train_cases=6,dev_cases=144,
        usage={split:dict(calls=len([r for r in rows if r['split']==split]),
            input_tokens=sum(r['usage']['prompt_tokens'] for r in rows if r['split']==split),
            output_tokens=sum(r['usage']['completion_tokens'] for r in rows if r['split']==split),
            reported_cost_usd=sum(r['usage']['cost'] for r in rows if r['split']==split),
            native_reasoning_observed=sum(r['native_reasoning_observed'] for r in rows if r['split']==split)) for split in ['train','dev']},
        attempts_with_unknown_billing=len(unknown),unknown_cost_upper_bound_usd=sum(transport.read(p)['cost_reservation_usd'] for p in unknown),
        tracks={},paired_epistemic=paired_epistemic(rows),records=rows,
        limitation='Development pilot of the harder task version. No held-out TEST inference; tiers/tracks are not pooled into a model ranking.')
    for track in ['semantic','epistemic']:
        selected=[r for r in rows if r['split']=='dev' and r['track']==track]
        result['tracks'][track]=dict(primary=summary(selected),framing_sensitivity=summary(selected,True),
            tiers={str(t):summary([r for r in selected if r['tier']==t]) for t in [1,2,3]})
    if not output.with_suffix('.json').exists():transport.write(output.with_suffix('.json'),result)
    else:assert transport.read(output.with_suffix('.json'))==result
    text=['# Harder ontology governance: completed development pilot','',f"Model: `{result['model']}`. Six TRAIN interface calls and all 144 DEV cases are complete. No correction feedback was provided.",'',
        '| Track | Tier | Full correct | Correct decisions | Parse errors | Invalid schema | Token limits | Provider errors |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for track,v in result['tracks'].items():
        for tier,s in [('All',v['primary']),*v['tiers'].items()]:
            text.append(f"| {track} | {tier} | {s['full_correct']}/{s['cases']} ({100*s['full_accuracy']:.1f}%) | {s['decision_correct']}/{s['decision_denominator']} | {s['parse_errors']} | {s['invalid_schema']} | {s['token_limits']} | {s['provider_error_finishes']} |")
    text+=['','Per-action scores require a complete valid typed schema. Malformed answers remain errors. Full semantic correctness includes valid expansion witnesses; full epistemic correctness includes supported facts, an acceptable repair, warranted decisions, possible outcomes and an optimal next query.','',
        '| Track | Allow on denied | Allow on undetermined | Justified allow | Correct abstention |','| --- | ---: | ---: | ---: | ---: |']
    for track,v in result['tracks'].items():
        s=v['primary'];text.append(f"| {track} | {s['allow_on_deny']}/{s['deny_denominator']} | {s['allow_on_unknown']}/{s['unknown_denominator']} | {s['justified_allow']}/{s['allow_denominator']} | {s['correct_abstention']}/{s['unknown_denominator']} |")
    text+=['','Sole-fence framing sensitivity (no interior repair):']
    for track,v in result['tracks'].items():s=v['framing_sensitivity'];text.append(f"- {track}: {s['full_correct']}/{s['cases']} full answers correct.")
    text+=['','Tokens include reasoning within output usage.']
    for split,u in result['usage'].items():text.append(f"- {split}: {u['calls']} calls; {u['input_tokens']:,} input, {u['output_tokens']:,} output tokens; reported USD{u['reported_cost_usd']:.6f}.")
    text+=['',result['limitation'],'','Exact component scores, matched contrasts, reference answers, per-case native response hashes and final judgments are retained in the JSON report.','']
    target=output.with_suffix('.md');body='\n'.join(text)
    if target.exists():assert target.read_text()==body
    else:target.write_text(body)
    print(json.dumps(dict(status='PASS',alias=plan['alias'],reconstructed=150,output=str(output))))
    return result


def archive(run,destination):
    assert transport.read(run/'status.json')['state']=='COMPLETE'
    key=transport.load_key().encode()
    if destination.exists():raise ValueError('Never replace an existing receipt archive')
    destination.mkdir(parents=True)
    files=[]
    for path in sorted(run.rglob('*')):
        if not path.is_file() or path.name=='.execution.lock':continue
        raw=path.read_bytes();assert key not in raw and path.name!='.env'
        relative=path.relative_to(run);target=destination/relative
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        files.append(dict(path=str(relative),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
    transport.write(destination/'manifest.json',dict(source_run=str(run),credential_scan='PASS',files=files))
    return dict(path=str(destination),files=len(files),manifest_sha256=transport.sha(destination/'manifest.json'))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',choices=['gpt6luna','gpt56terra','gpt61sol'],required=True)
    p.add_argument('--archive',action='store_true');a=p.parse_args()
    run=ROOT/f'runs/{a.model}-challenge-v2-openai-full32-2026-10-16';output=ROOT/f'internal/research/ontology-{a.model}-challenge-v2-openai-full32-results-2026-10-16'
    report(run,output)
    if a.archive:
        print(json.dumps(archive(run,ROOT/f'internal/research/{a.model}-challenge-v2-openai-full32-receipts-2026-10-16')))


if __name__=='__main__':main()
