#!/usr/bin/env python3
"""Four-leg recovery final-projection replay v3; no inference or credentials.

Separately versioned adaptation of the preserved interrupted-study reader.
"""
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
import argparse
import hashlib
import json
import sys


def read(path):
    return json.loads(Path(path).read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def json_equivalent(left, right):
    # JSON object keys are strings after loading. Normalize this representation
    # before comparison; every scalar value and statistical algorithm stays exact.
    return canonical(json.loads(canonical(left))) == canonical(json.loads(canonical(right)))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(test, message):
    if not test:
        raise ValueError(message)


def partition(slots, records, attempts):
    planned = {s['slot_id']: s for s in slots}
    require(len(planned) == len(slots) == 8640, 'Original slot inventory changed')
    delivered = {r['slot_id']: r for r in records}
    require(len(delivered) == len(records), 'Duplicate delivered slot')
    grouped = defaultdict(list)
    known = Decimal(0)
    unknown = Decimal(0)
    seen = set()
    for a in attempts:
        key = (a['slot_id'], a['attempt'])
        require(key not in seen and a['slot_id'] in planned, 'Duplicate/out-of-plan attempt')
        seen.add(key)
        grouped[a['slot_id']].append(a)
        require(Decimal(a['reservation_usd']) >= 0, 'Negative reservation')
        if a['status'] == 'complete':
            require(a['slot_id'] in delivered, 'Unscored delivered attempt')
            r = delivered[a['slot_id']]
            require(Decimal(a['reported_cost_usd']) == Decimal(r['native_reported_cost_usd']), 'Final cost differs from settlement')
            known += Decimal(a['reported_cost_usd'])
        else:
            require(a['status'] in ['http-error', 'unknown-outcome'], 'Unsupported attempt category')
            unknown += Decimal(a['reservation_usd'])
    for sid, xs in grouped.items():
        xs.sort(key=lambda a: a['attempt'])
        require([a['attempt'] for a in xs] == list(range(len(xs))) and len(xs) <= 3, 'Retry sequence changed')
        for a in xs[:-1]:
            require(a['status'] == 'http-error' and a['http_status'] in [429, 502, 503, 504] and a['retryable'] is True, 'Delivered or unknown outcome retried')
        require(sum(a['status'] == 'complete' for a in xs) == int(sid in delivered), 'Duplicate/missing completion')
        if sid not in delivered:
            require(xs[-1]['status'] == 'unknown-outcome', 'Missing final is not declared unknown')
    require(set(delivered) <= set(grouped), 'Final without an attempt')
    for r in records:
        require(all(r[k] == v for k, v in planned[r['slot_id']].items()), 'Final/slot binding changed')
    unknown_slots = sorted(set(grouped) - set(delivered))
    never = sorted(set(planned) - set(grouped))
    require(not (set(delivered) & set(unknown_slots) or set(delivered) & set(never) or set(unknown_slots) & set(never)), 'Partition overlap')
    return dict(planned=len(planned), delivered=len(delivered), attempted_unknown=len(unknown_slots), never_submitted=len(never),
                closed_attempts=len(attempts), known_cost_usd=str(known), unknown_cost_upper_bound_usd=str(unknown),
                exposure_usd=str(known + unknown), unknown_slots=unknown_slots, never_submitted_slots=never)


def category(r, mode):
    if r.get('refusal') or r.get('finish_reason') == 'content_filter':
        return 'native_filter_or_refusal'
    if r.get('provider_error') or r.get('finish_reason') == 'error':
        return 'native_provider_error'
    if r.get('finish_reason') == 'length':
        return 'native_length'
    v = r[mode]
    if v.get('parse_error'):
        return 'unparseable_final'
    s = v.get('score', {})
    if s.get('valid_format', s.get('valid_schema', True)) is False or ('reason' in s and not s.get('fields')):
        return 'schema_invalid'
    return 'correct' if s.get('all_correct', s.get('correct', False)) else 'completed_task_error'


def verify(root, replay=False):
    root = Path(root).resolve()
    manifest = read(root / 'manifest.json')
    names = set()
    for f in manifest['files']:
        rel = Path(f['path'])
        require(not rel.is_absolute() and '..' not in rel.parts and str(rel) not in names, 'Unsafe/duplicate member')
        names.add(str(rel))
        p = root / rel
        require(p.is_file() and not p.is_symlink() and len(p.read_bytes()) == f['bytes'] and sha(p) == f['sha256'], 'Member bytes changed: ' + str(rel))
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts and p != root / 'manifest.json'}
    require(actual == names, 'Unlisted/missing capsule member')
    data = read(root / 'data/final-projections.json')
    records = data['records']
    attempts = read(root / 'data/attempt-ledger.json')['attempts']
    plan = read(root / 'data/original-plan.json')
    continuation = read(root / 'data/async-plan.json')
    recovery = read(root / 'data/recovery-plan.json')
    fourth = read(root / 'data/recovery-v4-plan.json')
    provenance = read(root / 'provenance.json')
    prior_attempted = {a['slot_id'] for a in attempts if a['leg'] in ['original', 'async']}
    require(len(prior_attempted) == 1222 and len(recovery['slots']) == 7418, 'Recovery scope changed')
    require({s['slot_id'] for s in recovery['slots']} == {s['slot_id'] for s in plan['slots']} - prior_attempted, 'Recovery is not exact never-attempted complement')
    require(not {a['slot_id'] for a in attempts if a['leg'] == 'recovery'} & prior_attempted, 'Prior answer or unknown outcome resent')
    require({r['slot_id'] for r in records if r['slot_id'] in prior_attempted} == set(recovery['predecessor_observed_slots']), 'Prior received answers were changed or omitted')
    require(data['native_proof_sha256'] == provenance['combined_native_proof_sha256'], 'Private native proof link changed')
    preceding = {a['slot_id'] for a in attempts if a['leg'] in ['original', 'async', 'recovery']}
    fresh = {a['slot_id'] for a in attempts if a['leg'] == 'fourth'}
    require(len(preceding) == 7898 and len(fourth['slots']) == 742, 'Fourth-leg predecessor inventory changed')
    require({s['slot_id'] for s in fourth['slots']} == {s['slot_id'] for s in plan['slots']} - preceding, 'Fourth leg is not exact never-attempted complement')
    require(not fresh & preceding and fresh == {s['slot_id'] for s in fourth['slots']}, 'Fourth leg repeated a prior attempt or omitted an authorized slot')
    require({r['slot_id'] for r in records if r['slot_id'] in preceding} == set(fourth['predecessor_observed_slots']) and len(fourth['predecessor_observed_slots']) == 7888, 'Prior finals omitted or substituted')
    original_attempted = {a['slot_id'] for a in attempts if a['leg'] == 'original'}
    require(len(original_attempted) == 765 and len(continuation['slots']) == 7875, 'Handoff partition changed')
    require({s['slot_id'] for s in continuation['slots']} == {s['slot_id'] for s in plan['slots']} - original_attempted, 'Continuation is not exact unattempted complement')
    slotmap = {s['slot_id']: s for s in plan['slots']}
    for a in attempts:
        require(a['leg'] in ['original', 'async', 'recovery', 'fourth'], 'Unknown native leg')
        binding = {'original':plan, 'async':continuation, 'recovery':recovery, 'fourth':fourth}[a['leg']]['requests'][slotmap[a['slot_id']]['request_key']]
        require(a['request_sha256'] == binding['body_sha256'] and Decimal(a['reservation_usd']) == Decimal(binding['reservation_usd']), 'Request hash/reservation differs from frozen leg')
    result = partition(plan['slots'], records, attempts)
    declared = read(root / 'results/scope-and-accounting.json')
    require(canonical(result) == canonical(declared), 'Partition/billing replay differs')
    require(all(result[k] == v for k,v in provenance['expected_scope'].items()), 'Scope differs from audited terminal study')
    require(Decimal(result['exposure_usd']) <= Decimal(200), 'Global cap exceeded')
    require(result['delivered'] == 8630 and result['attempted_unknown'] == 10 and result['never_submitted'] == 0 and result['closed_attempts'] == 8643, 'Final four-leg scope changed')
    cases_path = root / 'data/cases.json'
    require(sha(cases_path) == data['cases_sha256'], 'Original case bytes changed')
    rows = read(cases_path)['cases']
    require(Counter((c['track'], c['split']) for c in rows) == {('semantic', 'train'): 3, ('epistemic', 'train'): 3, ('semantic', 'dev'): 48, ('epistemic', 'dev'): 96}, 'Case inventory changed')
    cases = {c['id']: c for c in rows}
    summary = read(root / 'results/analysis.json')
    require(sha(root / 'results/analysis.json') == provenance['analysis_sha256'] and summary['native_proof_sha256'] == data['native_proof_sha256'], 'Frozen analysis/proof link changed')
    complete_tracks = 0
    require(summary['status'] == 'INCOMPLETE' and summary['observed'] == len(records) and summary['planned'] == 8640, 'False completion claim')
    for alias in plan['models']:
        for track in ['semantic', 'epistemic']:
            for mode in ['primary', 'framing_sensitivity']:
                xs = [r for r in records if r['alias'] == alias and r['track'] == track]
                q = summary['models'][alias][track][mode]
                denom = 48 if track == 'semantic' else 96
                counts = Counter(r['original_id'] for r in xs)
                complete = len(xs) == 10*denom and len(counts) == denom and all(n == 10 for n in counts.values())
                require(q['complete'] is complete and (q['ten_round_summary'] is not None) is complete, 'False complete-track estimate')
                if mode == 'primary': complete_tracks += complete
                if complete:
                    import statistics
                    rates = [v['accuracy'] for v in q['rounds']]
                    whole = q['ten_round_summary']
                    require(whole['mean'] == statistics.mean(rates) and whole['round_sample_sd'] == statistics.stdev(rates) and whole['round_range'] == [min(rates),max(rates)], 'Ten-round moments changed')
                    per_case = {cid:sum(bool(v[mode]['score'].get('all_correct',v[mode]['score'].get('correct',False))) for v in xs if v['original_id']==cid) for cid in counts}
                    require(whole['per_case_successes'] == per_case, 'Per-case consistency changed')
                require(q['observed'] == len(xs) and q['exclusive_outcomes'] == dict(Counter(category(r, mode) for r in xs)), 'Outcome table changed')
                require(Decimal(q['usage']['reported_complete_cost_usd']) == sum((Decimal(r['native_reported_cost_usd']) for r in xs), Decimal(0)), 'Track cost changed')
                for field in ['prompt_tokens', 'completion_tokens']:
                    require(q['usage'][field] == sum(r['usage'][field] for r in xs), 'Usage changed')
                for n in range(1, 11):
                    rr = [r for r in xs if r['round'] == n]
                    item = q['rounds'][n-1]
                    correct = sum(bool(r[mode]['score'].get('all_correct', r[mode]['score'].get('correct', False))) for r in rr)
                    require(item['observed'] == len(rr) and item['correct'] == correct, 'Round inventory changed')
                    require(item['planned'] == denom and item['accuracy'] == (correct/denom if len(rr)==denom else None), 'Round accuracy changed or imputed')
    replayed = references = 0
    if replay:
        source = root / 'frozen-source'
        provenance = read(root / 'provenance.json')
        for name, expected in provenance['exact_frozen_sources'].items():
            require(sha(source / name) == expected == plan['sources'][name], 'Scorer differs from original frozen closure')
        sys.path[:0] = [str(source), str(source / 'src')]
        from internal.scripts import run_ontology_challenge_v2_full32 as scoring
        for row in rows:
            scoring.check_reference(row)
            references += 1
        for r in records:
            require(cases[r['original_id']]['split'] == 'dev', 'Historical/interface row in primary')
            for mode, framing in [('primary', False), ('framing_sensitivity', True)]:
                v = scoring.parsed_score(cases[r['original_id']], r['final_text'], framing)
                require(canonical(v) == canonical(r[mode]), 'Original score replay differs: ' + r['slot_id'])
                replayed += 1
        import importlib.util
        spec = importlib.util.spec_from_file_location('recovery_analysis_core',root/'analysis_core.py')
        core = importlib.util.module_from_spec(spec); spec.loader.exec_module(core)
        actual_models,actual_units = core.analyze(records,plan['models'])
        require(json_equivalent(actual_models,summary['models']) and json_equivalent(actual_units,summary['unit_sensitivity']), 'Frozen full analysis replay differs')
    return dict(status='PASS_INCOMPLETE_FINAL_PROJECTION_REPLAY' if replay else 'PASS_INCOMPLETE_CAPSULE_BYTES_PARTITION_BILLING',
                files=len(names), planned=8640, delivered=len(records), attempted_unknown=result['attempted_unknown'], never_submitted=result['never_submitted'],
                original_references_checked=references, strict_and_fence_scores_replayed=replayed,
                known_cost_usd=result['known_cost_usd'], unknown_cost_upper_bound_usd=result['unknown_cost_upper_bound_usd'], exposure_usd=result['exposure_usd'],
                complete_ten_pass_model_tracks=complete_tracks, full_original_study_complete=False, full_analysis_replayed=replay, native_http_reaudit=False,
                scope='Final projections and declared native metadata; full HTTP/reasoning and lost outcomes are outside portable scope', new_model_calls=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['verify', 'replay'])
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parent)
    a = parser.parse_args()
    print(canonical(verify(a.package, a.command == 'replay')))
