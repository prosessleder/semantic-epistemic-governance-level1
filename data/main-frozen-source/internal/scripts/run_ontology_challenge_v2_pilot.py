#!/usr/bin/env python3
"""Frozen two-track DEVELOPMENT pilot; reuse audited hosted transport receipts."""
from concurrent.futures import ThreadPoolExecutor, as_completed
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
PROTOCOL = f'internal/planning/ontology-challenge-v2-hosted-pilot-{DATE}.md'
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


def inference_settings(config):
    return dict(temperature=0, max_tokens=16384, reasoning=config['reasoning'],
        provider=dict(only=[config['tag']], allow_fallbacks=False, require_parameters=True),
        response_format={'type': 'json_object'}, stream=False)


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
    config = transport.CONFIGS[alias]
    endpoint = metadata['endpoint']
    assert endpoint['tag'] == config['tag'] and endpoint['status'] == 0
    assert endpoint['max_completion_tokens'] >= 16384
    assert {'response_format', 'reasoning'} <= set(endpoint['supported_parameters'])
    sources = [Path(__file__).resolve(), Path(epi.__file__), Path(sem.__file__),
               Path(transport.__file__), ROOT / 'internal/scripts/audit_ontology_epistemic_challenge_v2.py',
               ROOT / 'src/ontology_boundary/oracle.py', ROOT / PROTOCOL]
    plan = dict(alias=alias, config=config, model=metadata['model'], endpoint=endpoint,
        settings=inference_settings(config), total_budget_usd=8.0, workers=4,
        timeout_seconds=900, transport_retries=2, judgments_per_case=1,
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
    write(run / 'execution-plan.json', plan)
    write(run / 'preflight.json', dict(status='PASS', independent_references=150,
        plan_sha256=sha(run / 'execution-plan.json')))
    transport.emit(event='v2_pilot_frozen', alias=alias, planned=plan['planned_calls'],
        max_tokens=16384, budget_usd=8, plan_sha256=sha(run / 'execution-plan.json'))


def validate(run):
    plan = read(run / 'execution-plan.json')
    assert read(run / 'preflight.json')['plan_sha256'] == sha(run / 'execution-plan.json')
    assert plan['settings'] == inference_settings(transport.CONFIGS[plan['alias']])
    assert plan['config'] == transport.CONFIGS[plan['alias']] and plan['total_budget_usd'] == 8
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
    plan, rows = validate(run)
    with (run / '.execution.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        client = transport.Client(run, plan)
        started = time.monotonic()

        def worker(row):
            output = run / 'judgments' / (row['id'] + '.json')
            if output.exists():
                return read(output)
            body = read(run / 'frozen-requests' / (row['id'] + '.json'))
            value = client.call(row['id'], body)
            choice, usage = transport.validate_response(value, plan)
            raw = choice['message'].get('content')
            result = dict(id=row['id'], case_id=row['case_id'], track=row['track'], split=row['split'],
                tier=row['tier'], unit_id=row['unit_id'], request_sha256=digest(body),
                response_sha256=sha(run / 'responses' / (row['id'] + '.json')),
                finish_reason=choice.get('finish_reason'), final_text=raw, usage=usage,
                native_reasoning_observed=transport.has_reasoning(value),
                primary=parsed_score(row, raw), framing_sensitivity=parsed_score(row, raw, True))
            write(output, result)
            return result

        try:
            for split in ['train', 'dev']:
                selected = [r for r in rows if r['split'] == split]
                if split == 'dev':
                    train = [read(run / 'judgments' / (r['id'] + '.json')) for r in rows if r['split'] == 'train']
                    assert len(train) == 6 and all(r['native_reasoning_observed'] for r in train), 'Native reasoning delivery check failed'
                    for track in ['semantic', 'epistemic']:
                        assert any(r['track'] == track and isinstance(r['primary']['answer'], dict) for r in train), 'No bare JSON object delivered for track'
                with ThreadPoolExecutor(max_workers=plan['workers']) as pool:
                    futures = [pool.submit(worker, row) for row in selected]
                    for done, future in enumerate(as_completed(futures), 1):
                        future.result()
                        status = dict(state='RUNNING', alias=plan['alias'], split=split,
                            completed=done, expected=len(selected), elapsed_seconds=round(time.monotonic()-started, 1),
                            reported_cost_usd=client.spent, unknown_cost_upper_bound_usd=client.unknown_bound,
                            updated_utc=transport.now(), pid=os.getpid())
                        atomic(run / 'status.json', status)
                        transport.emit(event='v2_pilot_progress', **status)
                completion = run / (split + '-completion.json')
                if not completion.exists():
                    write(completion, dict(status='COMPLETE', cases=len(selected), split=split,
                        plan_sha256=sha(run / 'execution-plan.json')))
            atomic(run / 'status.json', dict(state='COMPLETE', alias=plan['alias'],
                completed=150, expected=150, elapsed_seconds=round(time.monotonic()-started,1),
                reported_cost_usd=client.spent, unknown_cost_upper_bound_usd=client.unknown_bound,
                updated_utc=transport.now()))
        except Exception as error:
            client.stop.set()
            atomic(run / 'status.json', dict(state='STOPPED', alias=plan['alias'],
                reason=type(error).__name__ + ': ' + str(error), reported_cost_usd=client.spent,
                unknown_cost_upper_bound_usd=client.unknown_bound, updated_utc=transport.now()))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'execute'])
    parser.add_argument('--model', choices=sorted(transport.CONFIGS), required=True)
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--prepared', type=Path, default=ROOT/'runs/challenge-v2-development')
    parser.add_argument('--metadata', type=Path, default=Path('/tmp/challenge-v2-provider-metadata-2026-10-16.json'))
    args = parser.parse_args()
    run = args.run_dir or ROOT/f'runs/{args.model}-challenge-v2-pilot-{DATE}'
    if args.command == 'prepare':
        prepare(run.resolve(), args.model, args.prepared.resolve(), args.metadata.resolve())
    else:
        execute(run.resolve())


if __name__ == '__main__':
    main()
