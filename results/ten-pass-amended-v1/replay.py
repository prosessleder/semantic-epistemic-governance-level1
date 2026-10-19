#!/usr/bin/env python3
"""Offline replay of an explicitly post-hoc amended final-projection capsule.

The nested original primary capsule is immutable and remains incomplete.
No network, credential loading, native client, or empirical writer is used.
"""
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
import argparse
import importlib.util
import json
import sys


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def followup_partition(plan, primary, primary_scope, records, attempts):
    """Keep old unknown attempts and new generations as distinct identities."""
    slots = {s['slot_id']: s for s in plan['slots']}
    targets = set(primary_scope['unknown_slots'])
    received = {v['slot_id'] for v in primary}
    if len(slots) != len(plan['slots']) or len(slots) != 10:
        raise ValueError('Exactly ten unique fresh follow-up identities required')
    if {s['original_slot_id'] for s in slots.values()} != targets or len(targets) != 10:
        raise ValueError('Follow-up must map exactly to ten original unknowns')
    for sid, s in slots.items():
        if sid != 'followup1--' + s['original_slot_id'] or s['original_slot_id'] in received:
            raise ValueError('New namespace required; received primary final cannot be replaced')
        if s['cohort_role'] != 'posthoc_unknown_outcome_followup':
            raise ValueError('Follow-up cohort label missing')
    fresh = {v['slot_id']: v for v in records}
    if len(fresh) != len(records) or not set(fresh) <= set(slots):
        raise ValueError('Duplicate or unauthorized fresh final')
    for sid, v in fresh.items():
        if not all(v.get(k) == x for k, x in slots[sid].items()):
            raise ValueError('Fresh final/slot mapping changed')
    grouped = defaultdict(list)
    known = Decimal(0)
    failed = Decimal(0)
    seen = set()
    for a in attempts:
        sid = a['slot_id']
        key = (sid, a['attempt'])
        if sid not in slots or key in seen:
            raise ValueError('Duplicate or unauthorized follow-up attempt')
        seen.add(key)
        binding = plan['requests'][slots[sid]['request_key']]
        if a['request_sha256'] != binding['body_sha256'] or Decimal(a['reservation_usd']) != Decimal(binding['reservation_usd']):
            raise ValueError('Original request/reservation binding changed')
        grouped[sid].append(a)
        if a['status'] == 'complete':
            if sid not in fresh or Decimal(a['reported_cost_usd']) != Decimal(fresh[sid]['native_reported_cost_usd']):
                raise ValueError('Fresh settlement differs from final')
            known += Decimal(a['reported_cost_usd'])
        elif a['status'] in ['http-error', 'unknown-outcome']:
            failed += Decimal(a['reservation_usd'])
        else:
            raise ValueError('Unsupported follow-up attempt category')
    for sid, xs in grouped.items():
        xs.sort(key=lambda a: a['attempt'])
        if [a['attempt'] for a in xs] != list(range(len(xs))) or len(xs) > 3:
            raise ValueError('Follow-up retry sequence changed')
        for a in xs[:-1]:
            if not (a['status'] == 'http-error' and a['http_status'] in [429, 502, 503, 504] and a['retryable'] is True):
                raise ValueError('A delivered/unknown outcome was retried')
        if sum(a['status'] == 'complete' for a in xs) != int(sid in fresh):
            raise ValueError('Duplicate or missing fresh completion')
        if sid not in fresh and xs[-1]['status'] != 'unknown-outcome':
            raise ValueError('Missing fresh final is not declared unknown')
    if not set(fresh) <= set(grouped):
        raise ValueError('Fresh final without a native attempt')
    if (Decimal(plan['predecessor_known_cost_usd']) != Decimal(primary_scope['known_cost_usd']) or
            Decimal(plan['predecessor_unknown_cost_usd']) != Decimal(primary_scope['unknown_cost_upper_bound_usd'])):
        raise ValueError('Original complete charges or failed/unknown reserves changed')
    full_known = Decimal(primary_scope['known_cost_usd']) + known
    full_failed = Decimal(primary_scope['unknown_cost_upper_bound_usd']) + failed
    if full_known + full_failed > Decimal(200):
        raise ValueError('Same global cap exceeded')
    union = list(primary) + [dict(v, slot_id=v['original_slot_id'], followup_slot_id=v['slot_id']) for v in records]
    if len({v['slot_id'] for v in union}) != len(union):
        raise ValueError('Primary final was replaced')
    scope = dict(original_primary_received=len(primary), original_primary_unknown=10,
                 original_primary_closed_attempts=primary_scope['closed_attempts'], original_study_complete=False,
                 followup_received=len(records), followup_unknown=len(set(grouped) - set(fresh)),
                 followup_never_submitted=len(set(slots) - set(grouped)), followup_closed_attempts=len(attempts),
                 amended_received=len(union), amended_missing=8640-len(union), original_planned=8640,
                 amended_complete=len(union) == 8640, total_closed_attempts=primary_scope['closed_attempts'] + len(attempts),
                 known_cost_usd=str(full_known), unknown_cost_upper_bound_usd=str(full_failed),
                 exposure_usd=str(full_known + full_failed), retained_original_unknown_slots=sorted(targets),
                 followup_complete_cost_usd=str(known), followup_failed_reserved_usd=str(failed),
                 cohort_role='POSTHOC_MISSING_OUTCOME_FOLLOWUP_AMENDED_DATASET')
    return union, scope


def verify(root, replay=False):
    root = Path(root).resolve()
    old = module('primary_capsule_reader', root/'primary/replay.py')
    manifest = old.read(root/'manifest.json')
    names = set()
    for f in manifest['files']:
        rel = Path(f['path'])
        old.require(not rel.is_absolute() and '..' not in rel.parts and str(rel) not in names, 'Unsafe/duplicate capsule member')
        names.add(str(rel)); p = root/rel
        old.require(p.is_file() and not p.is_symlink() and p.stat().st_size == f['bytes'] and old.sha(p) == f['sha256'], 'Changed capsule member: '+str(rel))
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p != root/'manifest.json' and '__pycache__' not in p.parts and '.git' not in p.parts}
    old.require(actual == names, 'Unlisted/missing capsule member')
    provenance = old.read(root/'provenance.json')
    for name, expected in provenance['original_primary_files'].items():
        old.require(old.sha(root/'primary'/name) == expected, 'Original primary capsule byte changed')
    primary_result = old.verify(root/'primary', replay)
    old.require(primary_result['full_original_study_complete'] is False and primary_result['delivered'] == 8630 and primary_result['attempted_unknown'] == 10, 'Original primary completion claim changed')
    primary = old.read(root/'primary/data/final-projections.json')['records']
    primary_scope = old.read(root/'primary/results/scope-and-accounting.json')
    plan = old.read(root/'followup/execution-plan.json')
    original_plan = old.read(root/'primary/data/original-plan.json')
    original_slots = {s['slot_id']: s for s in original_plan['slots']}
    for s in plan['slots']:
        expected = original_slots[s['original_slot_id']]
        old.require(all(s.get(k) == v for k, v in expected.items() if k != 'slot_id'), 'Original case/model/round binding changed')
        key = s['request_key']
        old.require(plan['requests'][key] == original_plan['requests'][key], 'Exact original request contract changed')
    fresh = old.read(root/'followup/final-projections.json')['records']
    attempts = old.read(root/'followup/attempt-ledger.json')['attempts']
    union, scope = followup_partition(plan, primary, primary_scope, fresh, attempts)
    old.require(old.canonical(scope) == old.canonical(old.read(root/'results/scope-and-accounting.json')), 'Amended mapping/partition/billing differs')
    a = old.read(root/'results/analysis.json')
    old.require(a['status'] == 'COMPLETE_AMENDED_COHORT' and a['original_study_complete'] is False and a['original_primary_observed'] == 8630 and a['original_primary_unknown_outcomes'] == 10, 'Cohort completion labels changed')
    old.require(a['cohort_role'] == scope['cohort_role'] and a['observed'] == len(union) == 8640 and a['planned'] == 8640, 'Amended analysis coverage changed')
    old.require(a['known_cost_usd'] == scope['known_cost_usd'] and a['unknown_cost_upper_bound_usd'] == scope['unknown_cost_upper_bound_usd'], 'Amended analysis money changed')
    old.require(old.sha(root/'results/analysis.json') == provenance['amended_analysis_sha256'] and a['native_proof_sha256'] == provenance['amended_proof_sha256'], 'Amended analysis source link changed')
    old.require(a['original_primary_proof_sha256'] == provenance['original_primary_proof_sha256'], 'Original primary proof link changed')
    core = module('amended_analysis_core', root/'primary/analysis_core.py')
    complete = 0
    primary_analysis = old.read(root/'primary/results/analysis.json')
    for alias in original_plan['models']:
        for track in ['semantic', 'epistemic']:
            xs = [v for v in union if v['alias'] == alias and v['track'] == track]
            denom = 480 if track == 'semantic' else 960
            counts = Counter(v['original_id'] for v in xs)
            old.require(len(xs) == denom and all(v == 10 for v in counts.values()), 'Amended track not complete')
            complete += 1
            for mode in ['primary', 'framing_sensitivity']:
                q = a['models'][alias][track][mode]
                old.require(q['complete'] is True and q['ten_round_summary'] is not None, 'Missing amended full-ten summary')
                old.require(q['exclusive_outcomes'] == dict(Counter(core.category(v, mode) for v in xs)), 'Native delivery categories changed')
                oldq = primary_analysis['models'][alias][track][mode]
                if oldq['complete']:
                    old.require(q == oldq, 'An already complete primary track was altered')
                else:
                    old.require(oldq['ten_round_summary'] is None, 'Primary null estimate was rewritten')
    replayed = 0
    if replay:
        # old.verify already checked all 150 references, 17,260 original scores
        # and the entire original statistical analysis under both frozen seeds.
        scoring = sys.modules['internal.scripts.run_ontology_challenge_v2_full32']
        cases = {v['id']: v for v in old.read(root/'primary/data/cases.json')['cases']}
        for v in fresh:
            old.require(cases[v['original_id']]['split'] == 'dev', 'Non-DEV follow-up')
            for mode, fence in [('primary', False), ('framing_sensitivity', True)]:
                old.require(old.canonical(scoring.parsed_score(cases[v['original_id']], v['final_text'], fence)) == old.canonical(v[mode]), 'Fresh original-scorer replay differs')
                replayed += 1
        models, units = core.analyze(union, original_plan['models'])
        old.require(old.json_equivalent(models, a['models']) and old.json_equivalent(units, a['unit_sensitivity']), 'FULL amended statistical replay differs')
    return dict(status='PASS_POSTHOC_AMENDED_FULL_REPLAY' if replay else 'PASS_POSTHOC_AMENDED_BYTES_MAPPING_PARTITION_BILLING',
                files=len(names), original_primary_received=8630, original_primary_unknown=10, original_study_complete=False,
                followup_received=len(fresh), amended_received=len(union), amended_complete=True, complete_amended_model_tracks=complete,
                original_references_checked=primary_result['original_references_checked'],
                original_scores_replayed=primary_result['strict_and_fence_scores_replayed'], followup_scores_replayed=replayed,
                strict_and_fence_scores_replayed=primary_result['strict_and_fence_scores_replayed']+replayed,
                full_original_analysis_replayed=replay, full_amended_analysis_replayed=replay,
                known_cost_usd=scope['known_cost_usd'], unknown_cost_upper_bound_usd=scope['unknown_cost_upper_bound_usd'], exposure_usd=scope['exposure_usd'],
                native_http_reaudit=False, new_model_calls=0,
                scope='Final projections and declared metadata; original primary remains incomplete; ten later generations form an explicit post-hoc amended dataset')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['verify', 'replay'])
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    result = verify(args.package, args.command == 'replay')
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
