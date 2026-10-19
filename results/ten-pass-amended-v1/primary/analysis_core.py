"""Portable extraction of frozen v3 statistical algorithms; stdlib only."""
from collections import Counter,defaultdict
from decimal import Decimal
from itertools import combinations
from types import SimpleNamespace
import random,statistics
def money(value):
    if isinstance(value,bool): raise ValueError('Boolean money')
    value=Decimal(str(value))
    if not value.is_finite() or value<0: raise ValueError('Invalid money')
    return value
r=SimpleNamespace(money=money)
def success(score):return bool(score.get('all_correct',score.get('correct',False)))

def category(record,mode):
    if record.get('refusal') or record.get('finish_reason')=='content_filter':return 'native_filter_or_refusal'
    if record.get('provider_error') or record.get('finish_reason')=='error':return 'native_provider_error'
    if record.get('finish_reason')=='length':return 'native_length'
    value=record[mode]
    if value.get('parse_error'):return 'unparseable_final'
    score=value.get('score',{})
    if score.get('valid_format',score.get('valid_schema',True)) is False or ('reason' in score and not score.get('fields')):return 'schema_invalid'
    return 'correct' if success(score) else 'completed_task_error'

def percentile(values,q):
    xs=sorted(values);x=(len(xs)-1)*q;lo=int(x);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(x-lo)

def interval(values):return [percentile(values,.025),percentile(values,.975)]

def summaries(records,track,mode):
    selected=[v for v in records if v['track']==track];denom=48 if track=='semantic' else 96;by_case=defaultdict(list);rounds=[]
    for v in selected:by_case[v['original_id']].append(int(success(v[mode]['score'])))
    for n in range(1,11):
        rows=[v for v in selected if v['round']==n];complete=len(rows)==denom
        rounds.append(dict(round=n,observed=len(rows),planned=denom,correct=sum(success(v[mode]['score']) for v in rows),accuracy=sum(success(v[mode]['score']) for v in rows)/denom if complete else None))
    complete=len(selected)==10*denom and len(by_case)==denom and all(len(v)==10 for v in by_case.values())
    full=None
    if complete:
        rates=[v['accuracy'] for v in rounds];rng=random.Random(2026101803);draws=[]
        for _ in range(20000):draws.append(sum(rng.choice(v) for v in by_case.values() for _ in range(10))/(10*denom))
        full=dict(mean=statistics.mean(rates),round_sample_sd=statistics.stdev(rates),round_range=[min(rates),max(rates)],
                  per_case_successes={k:sum(v) for k,v in sorted(by_case.items())},success_count_distribution=dict(sorted(Counter(sum(v) for v in by_case.values()).items())),
                  fixed_corpus_generation_resampling_interval=interval(draws),generation_draws=20000,generation_seed=2026101803)
    def components(v):
        s=v[mode]['score'];return s.get('fields',s)
    fields=sorted({k for v in selected for k,value in components(v).items() if type(value) is bool})
    return dict(observed=len(selected),planned=10*denom,complete=complete,rounds=rounds,ten_round_summary=full,
                exclusive_outcomes=dict(Counter(category(v,mode) for v in selected)),components={k:sum(bool(components(v).get(k,False)) for v in selected) for k in fields},
                usage=dict(prompt_tokens=sum(v['usage']['prompt_tokens'] for v in selected),completion_tokens=sum(v['usage']['completion_tokens'] for v in selected),reported_complete_cost_usd=str(sum((r.money(v['native_reported_cost_usd']) for v in selected),Decimal(0)))),
                native_latency_seconds=[v['native_latency_seconds'] for v in selected],native_completion_times_utc=[v['native_completed_at_utc'] for v in selected])

def analyze(records,aliases):
    models={};unit_sensitivity={}
    for alias in aliases:models[alias]={track:{mode:summaries([v for v in records if v['alias']==alias],track,mode) for mode in ['primary','framing_sensitivity']} for track in ['semantic','epistemic']}
    for track in ['semantic','epistemic']:
        for mode in ['primary','framing_sensitivity']:
            complete=[a for a in aliases if models[a][track][mode]['complete']]
            units=sorted({v['unit_id'] for v in records if v['track']==track});draws={a:[] for a in complete};unit_draws={a:[] for a in complete};pairs={a+'--'+b:[] for a,b in combinations(complete,2)}
            totals={a:{u:(sum(success(v[mode]['score']) for v in records if v['alias']==a and v['track']==track and v['unit_id']==u),sum(v['alias']==a and v['track']==track and v['unit_id']==u for v in records)) for u in units} for a in complete}
            if complete:
                rng=random.Random(2026101804)
                for _ in range(20000):
                    sampled=rng.choices(units,k=len(units));rates={a:sum(totals[a][u][0] for u in sampled)/sum(totals[a][u][1] for u in sampled) for a in complete}
                    for a in complete:draws[a].append(rates[a]);unit_draws[a].append(statistics.mean(totals[a][u][0]/totals[a][u][1] for u in sampled))
                    for a,b in combinations(complete,2):pairs[a+'--'+b].append(rates[a]-rates[b])
            unit_sensitivity[track+'--'+mode]=dict(units=len(units),complete_configurations=complete,draws=20000 if complete else 0,seed=2026101804,
                    case_weighted_intervals={a:interval(v) for a,v in draws.items()},unit_weighted_means={a:statistics.mean(n/d for n,d in totals[a].values()) for a in complete},unit_weighted_intervals={a:interval(v) for a,v in unit_draws.items()},
                    secondary_exploratory_paired_difference_intervals={k:interval(v) for k,v in pairs.items()},multiplicity='15 comparisons per track if all six complete; no significance-selected headline',scope='Conditional unit-resampling sensitivity, not generation uncertainty or a population guarantee')
    return models,unit_sensitivity
