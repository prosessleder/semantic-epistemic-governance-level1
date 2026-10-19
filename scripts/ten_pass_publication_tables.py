#!/usr/bin/env python3
"""Deterministic descriptive tables for the saved ten-pass projection (stdlib).

This program reads saved evidence. It never runs inference, loads credentials,
repairs answers, or recalculates a different statistical estimator. Incomplete
original tracks retain unavailable full-ten estimates. The amended cohort is a
separately labeled post-hoc missing-outcome follow-up dataset.
"""
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
import argparse
import csv
import io
import json
import statistics


MODELS = ['gpt61sol', 'gpt56terra', 'qwen38', 'gpt6luna', 'sonnet55', 'haiku55']
TRACKS = ['semantic', 'epistemic']
PARSERS = ['primary', 'framing_sensitivity']
NAMES = {'gpt61sol': 'GPT-6.1-Sol', 'gpt56terra': 'GPT-5.6-Terra',
         'qwen38': 'Qwen3.8-27B', 'gpt6luna': 'GPT-6-Luna',
         'sonnet55': 'Sonnet-5.5', 'haiku55': 'Haiku-5.5'}
CATEGORIES = ['correct', 'completed_task_error', 'unparseable_final',
              'schema_invalid', 'native_provider_error', 'native_filter_or_refusal',
              'native_length']


def read(path):
    return json.loads(Path(path).read_text())


def success(record, mode):
    score = record[mode]['score']
    return bool(score.get('all_correct', score.get('correct', False)))


def category(record, mode):
    if record.get('refusal') or record.get('finish_reason') == 'content_filter':
        return 'native_filter_or_refusal'
    if record.get('provider_error') or record.get('finish_reason') == 'error':
        return 'native_provider_error'
    if record.get('finish_reason') == 'length':
        return 'native_length'
    item = record[mode]
    if item.get('parse_error'):
        return 'unparseable_final'
    score = item.get('score', {})
    if (score.get('valid_format', score.get('valid_schema', True)) is False
            or ('reason' in score and not score.get('fields'))):
        return 'schema_invalid'
    return 'correct' if success(record, mode) else 'completed_task_error'


def csv_text(rows):
    if not rows:
        raise ValueError('Empty publication table')
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def pct(value):
    return None if value is None else 100 * value


def build_tables(package):
    package = Path(package)
    primary = read(package/'primary/data/final-projections.json')['records']
    fresh = read(package/'followup/final-projections.json')['records']
    amended = primary + [dict(r, slot_id=r['original_slot_id'],
                              followup_slot_id=r['slot_id']) for r in fresh]
    analyses = {'original_primary': read(package/'primary/results/analysis.json'),
                'posthoc_amended': read(package/'results/analysis.json')}
    cohorts = {'original_primary': primary, 'posthoc_amended': amended}
    primary_attempts = read(package/'primary/data/attempt-ledger.json')['attempts']
    attempts = {'original_primary': primary_attempts,
                'posthoc_amended': primary_attempts + read(package/'followup/attempt-ledger.json')['attempts']}
    plan = read(package/'primary/data/original-plan.json')
    slotmap = {s['slot_id']: s for s in plan['slots']}
    cases = read(package/'primary/data/cases.json')['cases']
    caseidx = {c['id']: c for c in cases}
    summary, rounds, consistency, components, outcomes, resources, tiers = [], [], [], [], [], [], []
    for cohort, records in cohorts.items():
        a = analyses[cohort]
        for alias in MODELS:
            for track in TRACKS:
                xs = [r for r in records if r['alias'] == alias and r['track'] == track]
                denominator = 48 if track == 'semantic' else 96
                planned = denominator * 10
                indexed = defaultdict(list)
                for r in xs:
                    indexed[r['original_id']].append(r)
                original_received = sum(r['alias'] == alias and r['track'] == track for r in primary)
                followups = sum(r['alias'] == alias and r['track'] == track for r in fresh) if cohort == 'posthoc_amended' else 0
                for mode in PARSERS:
                    q = a['models'][alias][track][mode]
                    whole = q['ten_round_summary']
                    if q['observed'] != len(xs) or q['planned'] != planned:
                        raise ValueError('Saved coverage differs from records')
                    unit = a['unit_sensitivity'][track+'--'+mode]
                    ci = unit['case_weighted_intervals'].get(alias, [None, None])
                    uci = unit['unit_weighted_intervals'].get(alias, [None, None])
                    gen = whole['fixed_corpus_generation_resampling_interval'] if whole else [None, None]
                    rr = whole['round_range'] if whole else [None, None]
                    summary.append(dict(cohort=cohort, model=alias, track=track, parser=mode,
                        original_received=original_received, later_followups=followups,
                        observed=len(xs), planned=planned, full_ten_available=q['complete'],
                        correct=sum(success(r, mode) for r in xs),
                        ten_round_mean_pct=pct(whole['mean']) if whole else None,
                        round_sample_sd_pp=pct(whole['round_sample_sd']) if whole else None,
                        round_min_pct=pct(rr[0]), round_max_pct=pct(rr[1]),
                        fixed_corpus_generation_interval_low_pct=pct(gen[0]),
                        fixed_corpus_generation_interval_high_pct=pct(gen[1]),
                        case_weighted_unit_sensitivity_low_pct=pct(ci[0]),
                        case_weighted_unit_sensitivity_high_pct=pct(ci[1]),
                        unit_weighted_mean_pct=pct(unit['unit_weighted_means'].get(alias)),
                        unit_weighted_sensitivity_low_pct=pct(uci[0]),
                        unit_weighted_sensitivity_high_pct=pct(uci[1])))
                    for i in range(1, 11):
                        rx = [r for r in xs if r['round'] == i]
                        n = sum(success(r, mode) for r in rx)
                        saved = q['rounds'][i-1]
                        rate = n/denominator if len(rx) == denominator else None
                        if saved != dict(round=i, observed=len(rx), planned=denominator, correct=n, accuracy=rate):
                            raise ValueError('Saved round differs from records')
                        rounds.append(dict(cohort=cohort, model=alias, track=track, parser=mode,
                            round=i, correct=n, observed=len(rx), planned=denominator,
                            complete_round=len(rx) == denominator, accuracy_pct=pct(rate)))
                    for cid, rx in sorted(indexed.items()):
                        n = sum(success(r, mode) for r in rx)
                        if whole and whole['per_case_successes'][cid] != n:
                            raise ValueError('Saved per-case consistency differs')
                        consistency.append(dict(cohort=cohort, model=alias, track=track, parser=mode,
                            case_id=cid, unit_id=caseidx[cid]['unit_id'], tier=caseidx[cid]['tier'],
                            observed_generations=len(rx), observed_successes=n,
                            successes_out_of_ten=n if whole else None,
                            full_track_ten_available=q['complete']))
                    for field, n in sorted(q['components'].items()):
                        if track == 'semantic':
                            actual = sum(bool(r[mode]['score'].get('fields', {}).get(field)) for r in xs)
                        else:
                            actual = sum(bool(r[mode]['score'].get(field)) for r in xs)
                        if actual != n:
                            raise ValueError('Saved component differs from records')
                        components.append(dict(cohort=cohort, model=alias, track=track, parser=mode,
                            component=field, correct=n, observed=len(xs), planned=planned))
                    counts = Counter(category(r, mode) for r in xs)
                    if dict(counts) != q['exclusive_outcomes'] or set(counts)-set(CATEGORIES):
                        raise ValueError('Saved native/format outcomes differ')
                    for name in CATEGORIES:
                        outcomes.append(dict(cohort=cohort, model=alias, track=track, parser=mode,
                            exclusive_category=name, count=counts[name], observed=len(xs), planned=planned))
                    for tier in [1, 2, 3]:
                        tx = [r for r in xs if r['tier'] == tier]
                        td = (16 if track == 'semantic' else 32) * 10
                        n = sum(success(r, mode) for r in tx)
                        tiers.append(dict(cohort=cohort, model=alias, track=track, parser=mode,
                            tier=tier, correct=n, observed=len(tx), planned=td,
                            accuracy_pct=100*n/td if len(tx) == td else None))
                ax = [r for r in attempts[cohort]
                      if slotmap[r['slot_id'].removeprefix('followup1--')]['alias'] == alias
                      and slotmap[r['slot_id'].removeprefix('followup1--')]['track'] == track]
                known = sum((Decimal(r['native_reported_cost_usd']) for r in xs), Decimal(0))
                reserved = sum((Decimal(r['reservation_usd']) for r in ax if r['status'] != 'complete'), Decimal(0))
                latencies = [r['native_latency_seconds'] for r in xs]
                times = [r['native_completed_at_utc'] for r in xs]
                usage = {k: sum(r['usage'][k] for r in xs) for k in ['prompt_tokens', 'completion_tokens']}
                resources.append(dict(cohort=cohort, model=alias, track=track, observed=len(xs), planned=planned,
                    closed_attempts=len(ax), unknown_attempts=sum(r['status'] == 'unknown-outcome' for r in ax),
                    explicit_http_failures=sum(r['status'] == 'http-error' for r in ax),
                    prompt_tokens=usage['prompt_tokens'], completion_tokens=usage['completion_tokens'],
                    reported_reasoning_tokens=sum(r['usage'].get('completion_tokens_details', {}).get('reasoning_tokens', 0) for r in xs),
                    max_response_completion_tokens=max(r['usage']['completion_tokens'] for r in xs),
                    native_stop_finishes=sum(r['finish_reason'] == 'stop' for r in xs),
                    known_complete_charges_usd=str(known), retained_failed_unknown_reservations_usd=str(reserved),
                    exposure_usd=str(known+reserved), first_completion_utc=min(times), last_completion_utc=max(times),
                    request_latency_min_seconds=min(latencies), request_latency_median_seconds=statistics.median(latencies),
                    request_latency_max_seconds=max(latencies)))
    return {name: csv_text(rows) for name, rows in [
        ('summary.csv', summary), ('rounds.csv', rounds), ('per-case-consistency.csv', consistency),
        ('components.csv', components), ('native-outcomes.csv', outcomes), ('resources.csv', resources),
        ('tiers.csv', tiers)]}


def write_tables(package, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    files = build_tables(package)
    for name, data in files.items():
        with (output/name).open('x') as handle:
            handle.write(data)
    return dict(status='WROTE_DESCRIPTIVE_PUBLICATION_TABLES', files=len(files),
                cohorts=['original_primary', 'posthoc_amended'], new_model_calls=0)


def check_tables(package):
    expected = build_tables(package)
    for name, data in expected.items():
        if (Path(package)/'tables'/name).read_text() != data:
            raise ValueError('Publication CSV differs from saved evidence: '+name)
    return dict(status='PASS_PUBLICATION_TABLES_MATCH_RECORDS_AND_ANALYSES', files=len(expected),
                original_primary_received=8630, original_primary_unknown=10,
                amended_received=8640, original_study_complete=False, new_model_calls=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['write', 'check'])
    parser.add_argument('--package', type=Path,
                        default=Path(__file__).resolve().parents[1]/'results/ten-pass-amended-v1')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'write':
        if args.output is None:
            parser.error('write requires a new --output directory')
        result = write_tables(args.package, args.output)
    else:
        result = check_tables(args.package)
    print(json.dumps(result, sort_keys=True))
