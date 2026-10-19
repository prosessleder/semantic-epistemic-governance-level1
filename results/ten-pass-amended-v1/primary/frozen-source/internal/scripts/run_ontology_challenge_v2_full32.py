#!/usr/bin/env python3
"""Full harder DEVELOPMENT evaluation at 32K; fresh independent calls, no feedback."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections import Counter
from pathlib import Path
import argparse
import fcntl
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from internal.benchmarks import ontology_epistemic_challenge_v2 as epi
from internal.benchmarks import ontology_semantic_challenge_v2 as sem
from internal.scripts import run_ontology_epistemic_sources as transport
from internal.scripts.audit_ontology_epistemic_challenge_v2 import independent_reference

DATE = '2026-10-16'
PROTOCOL = f'internal/planning/ontology-challenge-v2-full32-{DATE}.md'
read, write, sha, digest = transport.read, transport.write, transport.sha, transport.digest


def atomic(path, value):
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(transport.canonical(value) + '\n')
    temporary.replace(path)


def tier(case, track):
    return int(case['tier']) if track == 'epistemic' else int(case['tier'].split('-')[-1])


def selection(prepared):
    manifest = read(prepared / 'manifest.json')
    for name in ['semantic-cases.json', 'epistemic-cases.json']:
        if sha(prepared / name) != manifest['files'][name]:
            raise ValueError('Prepared corpus bytes changed')
    for name, expected in manifest['source_sha256'].items():
        if sha(ROOT / name) != expected:
            raise ValueError('Prepared corpus source changed: ' + name)
    e = read(prepared / 'epistemic-cases.json')['cases']
    s = read(prepared / 'semantic-cases.json')
    rows = []
    for track, cases in [('semantic', s['train'] + s['dev']), ('epistemic', e)]:
        for split in ['train', 'dev']:
            xs = [c for c in cases if c['split'] == split]
            if split == 'train':
                xs = [min((c for c in xs if tier(c, track) == t),
                          key=lambda c: c.get('id', c.get('case_id'))) for t in [1, 2, 3]]
            for c in xs:
                ident = c.get('id', c.get('case_id'))
                rows.append(dict(id=track + '--' + ident, case_id=ident, track=track,
                    split=split, tier=tier(c, track), unit_id=c.get('unit_id', c.get('group_id')),
                    case=c))
    rows.sort(key=lambda x: (x['split'] != 'train', x['tier'], x['track'], x['id']))
    assert Counter((r['split'], r['track']) for r in rows) == {
        ('train', 'semantic'): 3, ('train', 'epistemic'): 3,
        ('dev', 'semantic'): 48, ('dev', 'epistemic'): 96}
    return rows, manifest


def messages(row):
    return epi.request(row['case']) if row['track'] == 'epistemic' else sem.request(row['case'])['messages']


CONFIGS = {
    'qwen38': dict(model='qwen/qwen3.8-27b', provider='Chutes', tag='chutes/fp8', reasoning=dict(effort='medium', exclude=False), budget=8.),
    'sonnet55': dict(model='anthropic/claude-sonnet-5.5', provider='Anthropic', tag='anthropic', reasoning=dict(enabled=True, effort='medium', exclude=False), budget=60.),
}
net = transport

def inference_settings(config):
    value = dict(max_tokens=32768, reasoning=config['reasoning'],
        provider=dict(only=[config['tag']], allow_fallbacks=False, require_parameters=True), stream=False)
    if config['provider'] != 'Anthropic': value['temperature'] = 0
    return value


def check_reference(row):
    c = row['case']
    if row['track'] == 'epistemic':
        expected = independent_reference(c['input'])
        assert all(epi.canonical(expected[k]) == epi.canonical(v) for k, v in c['reference'].items())
    else:
        truth, diagnostics = sem.solve(c['contract'], c['proposal'], c['approvals'], check_independent=True)
        assert truth == c['truth'] and diagnostics['independent_agreement']


def prepare(run, alias, prepared, metadata_path):
    if run.exists():
        raise ValueError('Existing run must be inspected, never replaced')
    rows, manifest = selection(prepared)
    for row in rows:
        check_reference(row)
    metadata = read(metadata_path)[alias]
    config = CONFIGS[alias]
    endpoint = metadata['endpoint']
    assert endpoint['tag'] == config['tag'] and endpoint['status'] == 0
    assert endpoint['max_completion_tokens'] >= 32768
    assert {'reasoning'} <= set(endpoint['supported_parameters'])
    sources = [Path(__file__).resolve(), ROOT / 'internal/scripts/run_ontology_challenge_v2_pilot.py', ROOT / 'internal/scripts/report_ontology_challenge_v2_full32.py', Path(epi.__file__), Path(sem.__file__),
               Path(transport.__file__), ROOT / 'internal/scripts/audit_ontology_epistemic_challenge_v2.py',
               ROOT / 'src/ontology_boundary/oracle.py', ROOT / PROTOCOL]
    plan = dict(alias=alias, config=config, model=metadata['model'], endpoint=endpoint,
        settings=inference_settings(config), total_budget_usd=config['budget'], workers=4,
        timeout_seconds=1800, transport_retries=2, judgments_per_case=1,
        frozen_at_utc=transport.now(), development_only=True,
        source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        runtime=dict(python=sys.version, platform=platform.platform()),
        sources={str(p.relative_to(ROOT)): sha(p) for p in sources},
        prepared_manifest=manifest, planned_calls={'train': 6, 'dev': 144})
    run.mkdir(parents=True)
    write(run / 'dataset.json', {'cases': rows})
    write(run / 'provider-metadata.json', metadata)
    plan['dataset_sha256'] = sha(run / 'dataset.json')
    plan['provider_metadata_sha256'] = sha(run / 'provider-metadata.json')
    for name in plan['sources']:
        dest = run / 'frozen-source' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    plan['requests'] = {}
    for row in rows:
        body = dict(model=config['model'], messages=messages(row), **plan['settings'])
        write(run / 'frozen-requests' / (row['id'] + '.json'), body)
        plan['requests'][row['id']] = digest(body)
    prices=endpoint['pricing']
    bounds=[]
    for row in rows:
        body=read(run/'frozen-requests'/(row['id']+'.json'))
        bounds.append((len(transport.canonical(body).encode())+1024)*float(prices['prompt'])+32768*float(prices['completion'])+float(prices.get('request',0)))
    plan['no_retry_reservation_usd']=sum(bounds)
    write(run / 'execution-plan.json', plan)
    write(run / 'preflight.json', dict(status='PASS', independent_references=150,
        plan_sha256=sha(run / 'execution-plan.json')))
    transport.emit(event='v2_pilot_frozen', alias=alias, planned=plan['planned_calls'],
        max_tokens=32768, budget_usd=config['budget'], plan_sha256=sha(run / 'execution-plan.json'))


def validate(run):
    plan = read(run / 'execution-plan.json')
    assert read(run / 'preflight.json')['plan_sha256'] == sha(run / 'execution-plan.json')
    assert plan['settings'] == inference_settings(CONFIGS[plan['alias']])
    assert plan['config'] == CONFIGS[plan['alias']] and plan['total_budget_usd'] == CONFIGS[plan['alias']]['budget']
    assert plan['dataset_sha256'] == sha(run / 'dataset.json')
    assert plan['provider_metadata_sha256'] == sha(run / 'provider-metadata.json')
    for name, expected in plan['sources'].items():
        assert sha(ROOT / name) == sha(run / 'frozen-source' / name) == expected
    rows = read(run / 'dataset.json')['cases']
    assert len(rows) == 150
    for row in rows:
        body = dict(model=plan['config']['model'], messages=messages(row), **plan['settings'])
        assert read(run / 'frozen-requests' / (row['id'] + '.json')) == body
        assert digest(body) == plan['requests'][row['id']]
    return plan, rows


def parsed_score(row, raw, framing=False):
    removed = False
    if framing and isinstance(raw, str):
        fence = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', raw.strip(), re.S)
        if fence:
            raw, removed = fence[1], True
    parsed = epi.parse(raw)
    if parsed['parse_error']:
        return dict(answer=None, parse_error=parsed['parse_error'], score={}, sole_fence_removed=removed)
    answer = parsed['answer']
    score = epi.score(row['case']['input'], answer) if row['track'] == 'epistemic' else sem.score_answer(row['case'], answer)
    return dict(answer=answer, parse_error=None, score=score, sole_fence_removed=removed)


def execute(run):
    plan,rows=validate(run)
    with (run/'.execution.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);client=net.Client(run,plan);start=time.monotonic()
        def worker(row):
            if (run/'STOP').exists():raise RuntimeError('Author requested stop')
            path=run/'judgments'/f"{row['id']}.json"
            if path.exists():return net.read(path)
            body=net.read(run/'frozen-requests'/f"{row['id']}.json");value=client.call(row['id'],body);choice,usage=net.validate_response(value,plan);raw=choice['message'].get('content')
            result=dict(id=row['id'],case_id=row['case_id'],track=row['track'],tier=row['tier'],split=row['split'],request_sha256=net.digest(body),
                response_sha256=net.sha(run/'responses'/f"{row['id']}.json"),finish_reason=choice.get('finish_reason'),provider_error=choice.get('error'),
                final_text=raw,usage=usage,native_reasoning_observed=net.has_reasoning(value),primary=parsed_score(row,raw),framing_sensitivity=parsed_score(row,raw,True))
            net.write(path,result);return result
        try:
            for split in ('train','dev'):
                if split=='dev':
                    train=[net.read(run/'judgments'/f"{r['id']}.json") for r in rows if r['split']=='train']
                    assert len(train)==6 and all(r['native_reasoning_observed'] for r in train),'Native reasoning delivery gate failed'
                    for track in ('semantic','epistemic'):
                        assert any(r['track']==track and isinstance(r['primary']['answer'],dict) for r in train),'No bare JSON delivered for track'
                todo=iter(r for r in rows if r['split']==split);completed=0
                with ThreadPoolExecutor(max_workers=4) as pool:
                    pending={}
                    def fill():
                        while len(pending)<4 and not (run/'STOP').exists():
                            r=next(todo,None)
                            if r is None:break
                            pending[pool.submit(worker,r)]=r
                    fill()
                    while pending:
                        done,_=wait(pending,return_when=FIRST_COMPLETED)
                        for future in done:
                            pending.pop(future);future.result();completed+=1
                            state=dict(state='RUNNING',alias=plan['alias'],split=split,completed=completed,expected=plan['planned_calls'][split],reported_cost_usd=client.spent,
                                unknown_cost_upper_bound_usd=client.unknown_bound,elapsed_seconds=round(time.monotonic()-start,1),updated_utc=net.now(),pid=os.getpid())
                            atomic(run/'status.json',state);print(net.canonical(state),flush=True)
                        fill()
                if (run/'STOP').exists():raise RuntimeError('Author requested stop; current calls drained')
                completion=run/(split+'-completion.json')
                if not completion.exists():net.write(completion,dict(status='COMPLETE',split=split,cases=completed))
            atomic(run/'status.json',dict(state='COMPLETE',alias=plan['alias'],completed=150,reported_cost_usd=client.spent,unknown_cost_upper_bound_usd=client.unknown_bound,updated_utc=net.now()))
        except Exception as error:
            client.stop.set();atomic(run/'status.json',dict(state='STOPPED',alias=plan['alias'],reason=type(error).__name__+': '+str(error),updated_utc=net.now()));raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'execute'])
    parser.add_argument('--model', choices=sorted(CONFIGS), required=True)
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--prepared', type=Path, default=ROOT/'runs/challenge-v2-development')
    parser.add_argument('--metadata', type=Path, default=Path('/tmp/ontology-v2-full-metadata-2026-10-16.json'))
    args = parser.parse_args()
    run = args.run_dir or ROOT/f'runs/{args.model}-challenge-v2-full32-{DATE}'
    if args.command == 'prepare':
        prepare(run.resolve(), args.model, args.prepared.resolve(), args.metadata.resolve())
    else:
        execute(run.resolve())


if __name__ == '__main__':
    main()
