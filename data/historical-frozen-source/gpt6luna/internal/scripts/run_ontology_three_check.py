#!/usr/bin/env python3
"""Fresh shared first pass, paired correction conditions, exact receipt audit."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import argparse
import http.client
import json
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from internal.benchmarks import ontology_three_check as study
from internal.benchmarks import ontology_adjudication as blind
from internal.benchmarks import ontology_openrouter as api
from internal.benchmarks import ontology_rigorous_review as review
from internal.scripts import run_ontology_openrouter as old
from internal.scripts.audit_ontology_checked_proposals import reference_candidate,reference_review,sha
from ontology_boundary.checked_release import ReviewContract
from ontology_boundary.proposal_commit import commit_frame
from ontology_boundary.oracle import closure

PARENT=ROOT/'internal/research/glm-adjudication-receipts-2026-10-13/glm-adjudication-2026-10-13'
SOURCES=('internal/benchmarks/ontology_three_check.py','internal/scripts/run_ontology_three_check.py',
    'internal/planning/ontology-three-check-protocol.md','tests/test_ontology_three_check.py')


def write(p,x):old.write(p,x)
def read(p):return json.loads(p.read_text())


def prepare(run):
    assert not run.exists()
    parent=read(PARENT/'execution-plan.json');audit=read(PARENT/'audit.json');preflight=read(PARENT/'preflight.json')
    assert audit['status']==preflight['status']=='PASS'
    assert audit['records_sha256']==sha(PARENT/'records.jsonl')
    assert preflight['plan_sha256']==sha(PARENT/'execution-plan.json')
    # Archived RDF receipts are gzip-compressed, with their original hash in the manifest.
    import gzip,hashlib
    assert hashlib.sha256(gzip.decompress((PARENT/'preflight-rdf.jsonl.gz').read_bytes())).hexdigest()==preflight['rdf_sha256']
    assert parent['dataset_sha256']==sha(PARENT/'dataset.json')
    assert all(sha(ROOT/name)==digest for name,digest in parent['sources'].items())
    assert old.local.previous.installed_versions()==parent['runtime_versions']
    data=read(PARENT/'dataset.json');data['scenarios']=[s for s in data['scenarios'] if s['repeat_of'] is None]
    assert len(data['scenarios'])==480 and len(data['units'])==96
    units={u['unit_id']:u for u in data['units']};packets={};inventory=[];profiles=0
    for s in data['scenarios']:
        u=units[s['unit_id']];assert blind.scenario(u,s['mode'])==s
        packet=study.evidence(u,s);packets[s['scenario_id']]=packet
        c=ReviewContract.from_dict(u['contract']);candidate=reference_candidate(c,u['proposal'])
        for row in packet['goal_observations']:
            state=closure(candidate,row['seed_types'])
            assert row['derived_classes']==sorted(state.class_types)
            assert row['derived_permissions']==sorted(state.derived_permissions)
            assert row['effective_permissions']==sorted(state.permissions)
            assert row['consistent']==(not state.inconsistencies)
        for row in packet['complete_public_subset_table']:
            for key,o in [('base_has_protected',c.base),('candidate_has_protected',candidate)]:
                assert row[key]==(c.protected_permission in closure(o,row['seed_types']).permissions)
            profiles+=1
        inventory.append(dict(scenario_id=s['scenario_id'],first_request_sha256=blind.cases.digest(blind.request(u,s)),
            feedback_sha256=blind.cases.digest(packet)))
    run.mkdir(parents=True);write(run/'dataset.json',data);write(run/'feedback.json',packets)
    # Public metadata refresh contains no credential and performs no inference.
    models=read_url('https://openrouter.ai/api/v1/models')['data']
    model=next(m for m in models if m['id']==api.MODEL)
    eps=read_url('https://openrouter.ai/api/v1/models/'+api.MODEL+'/endpoints')
    endpoint=next(e for e in eps['data']['endpoints'] if e['tag']=='z-ai/fp8')
    assert model['reasoning']['mandatory'] and 'reasoning' in endpoint['supported_parameters']
    write(run/'model.json',model);write(run/'endpoints.json',eps)
    sources=dict(parent['sources']);sources.update({name:sha(ROOT/name) for name in SOURCES})
    for name in sources:
        dest=run/'frozen-source'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/name).read_bytes())
    plan=dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(),settings=blind.SETTINGS,stages=study.STAGES,arms=study.ARMS,
        workers=4,timeout_seconds=600,reported_budget_usd=5,transport_retries=2,sources=sources,
        runtime_versions=parent['runtime_versions'],dataset_sha256=sha(run/'dataset.json'),feedback_sha256=sha(run/'feedback.json'),
        inventory=inventory,model=model,endpoint=endpoint,parent_plan_sha256=sha(PARENT/'execution-plan.json'),
        parent_preflight_sha256=sha(PARENT/'preflight.json'),scenarios=480,semantic_units=96,
        stop_rule='all five fields exactly reference-correct, or three judgments',
        source_commit='private Git receipt recorded before new inference',scope='Fresh inference on previously inspected corpus; shared initial pass; reference-stopped correction trajectories')
    write(run/'execution-plan.json',plan)
    write(run/'preflight.json',dict(status='PASS',scenarios=480,units=96,feedback_profile_comparisons=profiles,
        parent_rdf_profiles=preflight['profiles'],parent_rdf_ontology_states=preflight['ontology_states'],
        plan_sha256=sha(run/'execution-plan.json')))
    print(json.dumps(dict(event='three_check_frozen',plan_sha256=sha(run/'execution-plan.json'),feedback_profiles=profiles)),flush=True)


def read_url(url):
    with urllib.request.urlopen(url,timeout=60) as r:return json.load(r)


def validate(run):
    plan=read(run/'execution-plan.json');data=read(run/'dataset.json');packets=read(run/'feedback.json')
    assert read(run/'preflight.json')['plan_sha256']==sha(run/'execution-plan.json')
    assert plan['settings']==blind.SETTINGS and plan['stages']==study.STAGES and tuple(plan['arms'])==study.ARMS
    assert plan['dataset_sha256']==sha(run/'dataset.json') and plan['feedback_sha256']==sha(run/'feedback.json')
    assert all(sha(ROOT/name)==digest for name,digest in plan['sources'].items())
    assert plan['runtime_versions']==old.local.previous.installed_versions()
    return plan,data,packets


class Client:
    """Preserve the first complete response; budget failed attempts conservatively."""
    def __init__(self,run,plan):
        self.run,self.plan,self.key=run,plan,api.load_key(old.ENV)
        self.lock=threading.Lock();self.stop=threading.Event();self.reserved=0.
        self.spent=sum(read(p)['usage']['cost'] for p in (run/'responses').glob('*.json'))
        self.unknown_bound=0.
        for p in (run/'attempts').glob('*/*.begin.json'):
            end=p.with_name(p.name.replace('.begin.json','.end.json'))
            if not end.exists() or read(end)['status']!='complete':self.unknown_bound+=read(p)['cost_reservation_usd']
    def call(self,name,body):
        rp=self.run/'requests'/(name+'.json');sp=self.run/'responses'/(name+'.json')
        if rp.exists():assert read(rp)==body
        else:write(rp,body)
        if sp.exists():return read(sp)
        if self.stop.is_set():raise RuntimeError('run stopped')
        quoted=self.plan['endpoint']['pricing']
        reserve=len(blind.cases.canonical(body))*float(quoted['prompt'])+body['max_tokens']*float(quoted['completion'])
        with self.lock:
            if self.spent+self.reserved+self.unknown_bound+reserve>self.plan['reported_budget_usd']:raise RuntimeError('budget reached')
            self.reserved+=reserve
        try:
            ad=self.run/'attempts'/name;ad.mkdir(parents=True,exist_ok=True)
            prior=len(list(ad.glob('*.begin.json')))
            for attempt in range(prior,1+self.plan['transport_retries']):
                start=time.monotonic();prefix=ad/str(attempt)
                write(prefix.with_suffix('.begin.json'),dict(at_utc=datetime.now(timezone.utc).isoformat(),request_sha256=blind.cases.digest(body),cost_reservation_usd=reserve))
                req=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=blind.cases.canonical(body).encode(),
                    headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json','X-OpenRouter-Cache':'false'})
                try:
                    with urllib.request.urlopen(req,timeout=self.plan['timeout_seconds']) as r:value=json.load(r)
                    assert self.key not in blind.cases.canonical(value)
                    write(sp,value);api.validate_response(value)
                    with self.lock:self.spent+=value['usage']['cost']
                    write(prefix.with_suffix('.end.json'),dict(status='complete',seconds=time.monotonic()-start))
                    return value
                except urllib.error.HTTPError as err:
                    detail=err.read().decode(errors='replace').replace(self.key,'[REDACTED]')
                    write(prefix.with_suffix('.end.json'),dict(status='http-error',http_status=err.code,detail=detail))
                    with self.lock:self.unknown_bound+=reserve
                    if err.code not in (429,502,503,504):raise RuntimeError('nontransient API HTTP '+str(err.code)) from None
                except (urllib.error.URLError,TimeoutError,http.client.IncompleteRead,json.JSONDecodeError) as err:
                    partial=getattr(err,'partial',b'')
                    write(prefix.with_suffix('.end.json'),dict(status='lost-response',kind=type(err).__name__,billing='unknown',
                        partial=partial.decode(errors='replace').replace(self.key,'[REDACTED]') if isinstance(partial,bytes) else ''))
                    with self.lock:self.unknown_bound+=reserve
                if attempt<self.plan['transport_retries']:time.sleep(2*(attempt+1))
            raise RuntimeError('transport retry allowance exhausted; receipts preserved')
        except Exception:self.stop.set();raise
        finally:
            with self.lock:self.reserved-=reserve


def execute(run):
    plan,data,packets=validate(run);client=Client(run,plan);units={u['unit_id']:u for u in data['units']}
    def judgment(s,arm,history):
        stage=len(history)+1;name=('shared' if stage==1 else arm)+'--'+s['scenario_id']+'--'+str(stage)
        p=run/'judgments'/(name+'.json')
        if p.exists():return read(p)
        body=study.request(units[s['unit_id']],s,arm,history,packets[s['scenario_id']])
        value=client.call(name,body);choice,usage=api.validate_response(value);raw=choice['message'].get('content')
        row=dict(name=name,stage=stage,request_sha256=blind.cases.digest(body),response_sha256=sha(run/'responses'/(name+'.json')),
            raw_response=raw,finish_reason=choice.get('finish_reason'),usage=usage,**blind.parse(raw))
        write(p,row);return row
    def worker(s):
        out=run/'trajectories'/(s['scenario_id']+'.json')
        if out.exists():return read(out)
        first=judgment(s,study.ARMS[0],[]);arms={}
        for arm in study.arm_order(s):
            history=[first]
            while len(history)<study.STAGES and not study.complete(history[-1],s):history.append(judgment(s,arm,history))
            arms[arm]=history
        row=dict(scenario_id=s['scenario_id'],arms=arms);write(out,row);return row
    start=time.monotonic()
    with ThreadPoolExecutor(max_workers=plan['workers']) as pool:
        fs=[pool.submit(worker,s) for s in data['scenarios']]
        for i,f in enumerate(as_completed(fs),1):
            row=f.result();print(json.dumps(dict(event='three_check_progress',done=i,total=480,calls=len(list((run/'responses').glob('*.json'))),
                rounds={a:len(h) for a,h in row['arms'].items()},seconds=round(time.monotonic()-start,1),reported_cost=round(client.spent,6))),flush=True)
    write(run/'completion.json',dict(status='COMPLETE',scenarios=480,plan_sha256=sha(run/'execution-plan.json'),seconds=time.monotonic()-start))


def audit(run):
    plan,data,packets=validate(run);assert read(run/'completion.json')['status']=='COMPLETE'
    units={u['unit_id']:u for u in data['units']};trajectories={};names=set();replays=0
    for s in data['scenarios']:
        sid=s['scenario_id'];u=units[s['unit_id']];assert study.evidence(u,s)==packets[sid]
        c=ReviewContract.from_dict(u['contract']);candidate=reference_candidate(c,u['proposal']);reg=review.registry(c,candidate,s['mode'])
        truth=reference_review(c,candidate,reg);assert truth['admitted']==s['truth']['release_allowed']
        arms=read(run/'trajectories'/(sid+'.json'))['arms'];assert arms[study.ARMS[0]][0]==arms[study.ARMS[1]][0]
        for arm,history in arms.items():
            for i,row in enumerate(history):
                assert row['stage']==i+1 and (i==0 or not study.complete(history[i-1],s))
                body=study.request(u,s,arm,history[:i],packets[sid]);name=row['name']
                assert read(run/'requests'/(name+'.json'))==body and blind.cases.digest(body)==row['request_sha256']
                sp=run/'responses'/(name+'.json');assert sha(sp)==row['response_sha256']
                choice,usage=api.validate_response(read(sp));assert usage==row['usage'] and choice['message'].get('content')==row['raw_response']
                assert choice.get('finish_reason')==row['finish_reason'] and all(row[k]==v for k,v in blind.parse(row['raw_response']).items())
                names.add(name)
                state,receipt=commit_frame(c.base,c,blind.cases.canonical(u['proposal']),reg)
                assert receipt['admitted']==truth['admitted'] and state==(candidate if truth['admitted'] else c.base);replays+=1
            assert study.complete(history[-1],s) or len(history)==study.STAGES
        trajectories[sid]=arms
    assert len(names)==len(list((run/'responses').glob('*.json')))==len(list((run/'judgments').glob('*.json')))
    assert replays-480==len(names)
    write(run/'audited-trajectories.json',trajectories)
    write(run/'audit.json',dict(status='PASS',unique_complete_responses=len(names),trajectory_commit_replays=replays,
        unique_commit_replays=replays-480,plan_sha256=sha(run/'execution-plan.json'),trajectories_sha256=sha(run/'audited-trajectories.json')))
    print(json.dumps(read(run/'audit.json')),flush=True)


def summarize(run):
    plan,data,packets=validate(run);audit=read(run/'audit.json');assert audit['status']=='PASS'
    trajectories=read(run/'audited-trajectories.json');assert audit['trajectories_sha256']==sha(run/'audited-trajectories.json')
    score=study.score(trajectories,data['scenarios'],data['units'])
    rows=[read(p) for p in (run/'judgments').glob('*.json')]
    attempts=list((run/'attempts').glob('*/*.begin.json'));failed=[]
    for p in attempts:
        end=p.with_name(p.name.replace('.begin.json','.end.json'))
        if not end.exists() or read(end)['status']!='complete':failed.append(str(p.relative_to(run)))
    usage=dict(saved_calls=len(rows),submitted_attempts=len(attempts),unreported_attempts=len(failed),unreported_attempt_files=failed,
        input_tokens=sum(r['usage']['prompt_tokens'] for r in rows),output_tokens=sum(r['usage']['completion_tokens'] for r in rows),
        reasoning_tokens=sum(r['usage'].get('completion_tokens_details',{}).get('reasoning_tokens',0) for r in rows),
        reported_cost_usd=sum(r['usage']['cost'] for r in rows),length_finishes=sum(r['finish_reason']=='length' for r in rows),
        parse_errors=sum(r['parse_error'] is not None for r in rows))
    write(run/'summary.json',dict(score=score,usage=usage,audit=audit,model=api.MODEL,plan_sha256=sha(run/'execution-plan.json')))
    print(json.dumps(dict(event='three_check_summary',usage=usage,stages={a:[dict(stage=x['stage'],false_approvals=x['primary_release']['false_approvals'],
        hidden_false_approvals=x['hidden_expansions']['false_approvals'],goal_failure_false_approvals=x['goal_failures']['false_approvals'],correct_allowed=x['correct_allowed']) for x in ss] for a,ss in score['arms'].items()})),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run','audit','summary']);p.add_argument('--run-dir',type=Path,required=True)
    a=p.parse_args();run=a.run_dir.resolve();dict(prepare=prepare,run=execute,audit=audit,summary=summarize)[a.command](run)
if __name__=='__main__':main()
