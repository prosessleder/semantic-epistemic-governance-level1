#!/usr/bin/env python3
"""Frozen, resumable hosted-model replication of the ontology feedback study."""
import argparse
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"src")]
from internal.benchmarks import ontology_openrouter as api
from internal.benchmarks import ontology_gemma_feedback as feedback
from internal.benchmarks import ontology_rigorous_proposals as cases
from internal.benchmarks import ontology_rigorous_review as review
from internal.scripts import run_ontology_gemma_feedback as local
from internal.scripts.audit_ontology_checked_proposals import reference_candidate, reference_review, sha
from ontology_boundary.checked_release import ReviewContract, ApprovalRegistry
from ontology_boundary.proposal_commit import commit_frame
from ontology_boundary.oracle import Ontology
from ontology_boundary.rdf_adapter import crosscheck_ontology

ARCHIVE=ROOT/"internal/research/gemma-feedback-receipts-2026-10-13"
PREFLIGHT=ROOT/"runs/glm-openrouter-preflight-2026-10-13"
ENV=ROOT.parent/"ontology-conditioned-steering-internal/.env"
SOURCES=("internal/benchmarks/ontology_openrouter.py","internal/scripts/run_ontology_openrouter.py",
    "internal/planning/ontology-glm-openrouter-protocol.md","tests/test_ontology_openrouter.py")


def canonical(value):return cases.canonical(value)
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x") as h:h.write(canonical(value)+"\n")
def emit(**value):print(json.dumps(value),flush=True)
def now():return datetime.now(timezone.utc).isoformat()
def identifier(group,arm,task_id,attempt=None):
    return "--".join(str(x) for x in (group,arm,task_id,attempt) if x is not None)


def prepare(run):
    assert not run.exists()
    dev=ARCHIVE/"gemma-feedback-dev-v1-2026-10-13"
    test=ARCHIVE/"gemma-feedback-test-2026-10-13"
    parent=json.loads((test/"execution-plan.json").read_text())
    sources={p:sha(ROOT/p) for p in parent["sources"]}
    assert sources==parent["sources"],"parent evaluator has changed"
    sources.update({p:sha(ROOT/p) for p in SOURCES})
    dataset=dict(dev=json.loads((dev/"dataset.json").read_text()),test=json.loads((test/"dataset.json").read_text()))
    assert len(dataset["dev"])==24 and len(dataset["test"])==192
    assert sum(not t["expected_abstain"] for t in dataset["test"])==176
    model=json.loads((PREFLIGHT/"model.json").read_text())
    endpoints=json.loads((PREFLIGHT/"endpoints.json").read_text())
    assert model["id"]==api.MODEL and model["reasoning"]["mandatory"]
    endpoint=next(e for e in endpoints["data"]["endpoints"] if e["tag"]==api.SETTINGS["provider"]["only"][0])
    jobs=[]
    for group,arms in (("dev",["assisted"]),("test",["baseline","assisted"])):
        for arm in arms:
            for t in dataset[group]:
                body=api.request(t,arm,[])
                jobs.append(dict(group=group,arm=arm,task_id=t["task_id"],initial_request_sha256=cases.digest(body)))
    for ts in dataset.values():
        for t in ts:
            c=ReviewContract.from_dict(t["contract"])
            candidate=reference_candidate(c,t["reference_patch"])
            if candidate is None:assert t["expected_abstain"]
            else:assert review.ground(c,candidate)["goal_satisfied"]
    run.mkdir(parents=True)
    write(run/"dataset.json",dataset)
    for p in sources:
        target=run/"frozen-source"/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/p).read_bytes())
    plan=dict(frozen_at_utc=now(),model=model,endpoint=endpoint,settings=api.SETTINGS,
        workers=4,max_attempts=3,reported_budget_usd=5,http_transient_retries=2,
        parent_plan_sha256=sha(test/"execution-plan.json"),dataset_sha256=sha(run/"dataset.json"),sources=sources,jobs=jobs,
        scope="Reused 24 DEV and 192 paired TEST cases; mandatory reasoning, hosted format and larger total cap differ from Gemma",
        smoke_request_sha256=sha(PREFLIGHT/"smoke-request.json"),smoke_response_sha256=sha(PREFLIGHT/"smoke-response.json"))
    write(run/"execution-plan.json",plan)
    emit(event="frozen",cases=len(jobs),plan_sha256=sha(run/"execution-plan.json"))


def validate(run):
    p=json.loads((run/"execution-plan.json").read_text())
    assert p["settings"]==api.SETTINGS and p["dataset_sha256"]==sha(run/"dataset.json")
    assert all(sha(ROOT/name)==digest for name,digest in p["sources"].items())
    return p,json.loads((run/"dataset.json").read_text())


class Client:
    def __init__(self,run,plan,timeout_seconds=180):
        self.run,self.plan,self.key=run,plan,api.load_key(ENV)
        self.timeout_seconds=timeout_seconds
        self.lock=threading.Lock();self.reserved=0.;self.stop=threading.Event()
        self.spent=sum(json.loads(p.read_text())["usage"]["cost"] for p in (run/"responses").glob("*.json"))
    def call(self,name,body):
        rp=self.run/"requests"/(name+".json");sp=self.run/"responses"/(name+".json")
        if rp.exists():
            assert json.loads(rp.read_text())==body
            if sp.exists():
                value=json.loads(sp.read_text());api.validate_response(value);return value
            # A restart cannot safely resend a request with an unknown outcome.
            raise RuntimeError("Pending request without a saved response; inspect failure receipts before resending")
        if self.stop.is_set():raise RuntimeError("run stopped")
        quoted=self.plan["endpoint"]["pricing"]
        reserve=len(canonical(body))*float(quoted["prompt"])+body["max_tokens"]*float(quoted["completion"])
        with self.lock:
            if self.spent+self.reserved+reserve>self.plan["reported_budget_usd"]:raise RuntimeError("reported budget reached")
            self.reserved+=reserve
        write(rp,body)
        try:
            for retry in range(self.plan["http_transient_retries"]+1):
                started=time.monotonic()
                req=urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",data=canonical(body).encode(),
                    headers={"Authorization":"Bearer "+self.key,"Content-Type":"application/json","X-OpenRouter-Cache":"false"})
                try:
                    with urllib.request.urlopen(req,timeout=self.timeout_seconds) as response:value=json.load(response)
                    if self.key in canonical(value):raise RuntimeError("credential appeared in response")
                    # Preserve complete responses, including unexpected provider errors,
                    # before validation; do not silently count them as model mistakes.
                    write(sp,value)
                    choice,usage=api.validate_response(value)
                    with self.lock:self.spent+=usage["cost"]
                    write(self.run/"transport"/(name+".json"),dict(seconds=time.monotonic()-started,retries=retry))
                    return value
                except urllib.error.HTTPError as error:
                    text=error.read().decode(errors="replace").replace(self.key,"[REDACTED]")
                    write(self.run/"errors"/(name+f"--{retry}.json"),dict(status=error.code,error=text,at_utc=now()))
                    if error.code not in (429,502,503,504) or retry==self.plan["http_transient_retries"]:
                        raise RuntimeError(f"API HTTP {error.code}; response preserved") from None
                    time.sleep(2*(retry+1))
                except (urllib.error.URLError,TimeoutError) as error:
                    write(self.run/"errors"/(name+f"--{retry}.json"),dict(kind=type(error).__name__,outcome="unknown",at_utc=now()))
                    raise RuntimeError("Ambiguous API transport failure; request not automatically repeated") from None
        except Exception:
            self.stop.set();raise
        finally:
            with self.lock:self.reserved-=reserve


def execute(run,group):
    plan,data=validate(run);client=Client(run,plan);start=time.monotonic()
    tasks={t["task_id"]:t for t in data[group]};jobs=[j for j in plan["jobs"] if j["group"]==group]
    def worker(job):
        name=identifier(group,job["arm"],job["task_id"]);out=run/"cases"/(name+".json")
        if out.exists():return json.loads(out.read_text())
        t=tasks[job["task_id"]];c=ReviewContract.from_dict(t["contract"]);attempts=[]
        for number in range(1,1+(1 if job["arm"]=="baseline" else plan["max_attempts"])):
            body=api.request(t,job["arm"],attempts)
            if number==1:assert cases.digest(body)==job["initial_request_sha256"]
            response_name=identifier(group,job["arm"],t["task_id"],number)
            value=client.call(response_name,body);choice,usage=api.validate_response(value)
            raw=choice["message"].get("content")
            a=dict(attempt=number,request_sha256=cases.digest(body),response_file=f"responses/{response_name}.json",
                response_sha256=sha(run/"responses"/(response_name+".json")),raw_response=raw,
                finish_reason=choice.get("finish_reason"),usage=usage,**api.parse(job["arm"],raw))
            a["diagnostic"]=feedback.diagnostic(c,a["proposal"])
            candidate,facts,decisions=review.evaluate(c,a["proposal"])
            a.update(candidate=None if candidate is None else candidate.to_dict(),facts=facts,decisions=decisions)
            attempts.append(a)
            if facts["goal_satisfied"] or a["proposal"]=={"op":"abstain"}:break
        row=dict(group=group,arm=job["arm"],task_id=t["task_id"],family=t["family"],expected_abstain=t["expected_abstain"],
            solved=attempts[-1]["facts"]["goal_satisfied"],correct_abstain=t["expected_abstain"] and attempts[-1]["proposal"]=={"op":"abstain"},attempts=attempts)
        write(out,row);return row
    with ThreadPoolExecutor(max_workers=plan["workers"]) as pool:
        futures=[pool.submit(worker,j) for j in jobs]
        for index,future in enumerate(as_completed(futures),1):
            row=future.result()
            emit(event="progress",group=group,arm=row["arm"],done=index,total=len(jobs),solved=row["solved"],
                attempts=len(row["attempts"]),seconds=round(time.monotonic()-start,1),reported_cost=round(client.spent,6))
    write(run/(group+"-completion.json"),dict(status="COMPLETE",cases=len(jobs),plan_sha256=sha(run/"execution-plan.json"),seconds=time.monotonic()-start))


def rdf_worker(item):
    name,ontology,basis=item
    result=crosscheck_ontology(Ontology.from_dict(ontology),frozenset(basis));assert result["matches"]
    return dict(key=name,result=result)


def audit(run):
    plan,data=validate(run);rows=[];rdf_inputs={};commits=attempt_count=0
    for group in ("dev","test"):assert json.loads((run/(group+"-completion.json")).read_text())["status"]=="COMPLETE"
    for job in plan["jobs"]:
        t=next(t for t in data[job["group"]] if t["task_id"]==job["task_id"])
        row=json.loads((run/"cases"/(identifier(job["group"],job["arm"],t["task_id"])+".json")).read_text())
        assert all(row[k]==job[k] for k in ("group","arm","task_id"))
        assert row["family"]==t["family"] and row["expected_abstain"]==t["expected_abstain"]
        c=ReviewContract.from_dict(t["contract"]);history=[]
        if row["arm"]=="assisted":local.independent_diagnostic(c,c.base,None,dict(status="goals-failed",goal_states=feedback.goal_states(c,c.base)))
        for i,a in enumerate(row["attempts"],1):
            assert a["attempt"]==i
            body=api.request(t,row["arm"],history);name=identifier(row["group"],row["arm"],t["task_id"],i)
            assert json.loads((run/"requests"/(name+".json")).read_text())==body
            assert cases.digest(body)==a["request_sha256"]
            value=json.loads((run/a["response_file"]).read_text());assert sha(run/a["response_file"])==a["response_sha256"]
            choice,usage=api.validate_response(value)
            assert a["usage"]==usage and a["finish_reason"]==choice.get("finish_reason") and a["raw_response"]==choice["message"].get("content")
            parsed=api.parse(row["arm"],a["raw_response"]);assert all(a[k]==v for k,v in parsed.items())
            try:candidate=reference_candidate(c,a["proposal"])
            except (ValueError,TypeError):candidate=None
            assert a["candidate"]==(None if candidate is None else candidate.to_dict())
            assert a["facts"]["valid_edit"]==(candidate is not None)
            local.independent_diagnostic(c,candidate,a["proposal"],a["diagnostic"])
            if candidate is not None:
                truth=review.ground(c,candidate)
                assert all(a["facts"][k]==truth[k] for k in ("goal_satisfied","protected_expansion","goal_probe_detected","pairwise_detected","derived_expansion","profiles"))
            else:assert not a["facts"]["goal_satisfied"]
            if i<len(row["attempts"]):assert not a["facts"]["goal_satisfied"] and a["proposal"]!={"op":"abstain"}
            history.append(a);attempt_count+=1
        final=history[-1]
        limit=1 if row["arm"]=="baseline" else plan["max_attempts"]
        assert 1<=len(history)<=limit
        assert len(history)==limit or final["facts"]["goal_satisfied"] or final["proposal"]=={"op":"abstain"}
        assert row["solved"]==final["facts"]["goal_satisfied"]
        assert row["correct_abstain"]==(t["expected_abstain"] and final["proposal"]=={"op":"abstain"})
        if candidate is not None:
            key=cases.digest(dict(ontology=candidate.to_dict(),basis=sorted(c.public_classes)))
            rdf_inputs[key]=(key,candidate.to_dict(),sorted(c.public_classes))
        for mode in review.MODES:
            reg=review.registry(c,candidate,mode) if candidate is not None else ApprovalRegistry()
            state,receipt=commit_frame(c.base,c,final["complete_frame"] or "",reg)
            admitted=False if candidate is None else reference_review(c,candidate,reg)["admitted"]
            assert receipt["admitted"]==admitted==final["decisions"][mode]["checked"]
            assert state==(candidate if admitted else c.base);commits+=1
        rows.append(row)
    record_file=run/"records.jsonl"
    with record_file.open("x") as h:
        for r in rows:h.write(canonical(r)+"\n")
    profiles=0
    with ProcessPoolExecutor(max_workers=4) as pool,(run/"audit-rdf.jsonl").open("x") as h:
        fs=[pool.submit(rdf_worker,v) for v in rdf_inputs.values()]
        for index,future in enumerate(as_completed(fs),1):
            result=future.result();profiles+=result["result"]["profiles_checked"];h.write(canonical(result)+"\n");h.flush()
            if index%24==0:emit(event="rdf_progress",done=index,total=len(fs))
    response_files=list((run/"responses").glob("*.json"))
    assert len(response_files)==attempt_count
    write(run/"audit.json",dict(status="PASS",cases=len(rows),model_calls=attempt_count,commit_replays=commits,
        unique_rdf_inputs=len(rdf_inputs),rdf_profiles=profiles,records_sha256=sha(record_file),rdf_sha256=sha(run/"audit-rdf.jsonl"),plan_sha256=sha(run/"execution-plan.json")))
    emit(event="audit_complete",cases=len(rows),calls=attempt_count,commits=commits)


def summary(run):
    plan,data=validate(run);audit_result=json.loads((run/"audit.json").read_text())
    assert audit_result["status"]=="PASS" and audit_result["records_sha256"]==sha(run/"records.jsonl")
    rows=[json.loads(x) for x in (run/"records.jsonl").read_text().splitlines()];results={}
    for group,arm in (("dev","assisted"),("test","baseline"),("test","assisted")):
        xs=[r for r in rows if r["group"]==group and r["arm"]==arm];possible=[r for r in xs if not r["expected_abstain"]]
        attempts=[a for r in xs for a in r["attempts"]]
        rounds=[];cumulative=0
        for i in range(1,1+(1 if arm=="baseline" else plan["max_attempts"])):
            reached=[r for r in possible if len(r["attempts"])>=i]
            wins=[r for r in reached if r["attempts"][i-1]["facts"]["goal_satisfied"]];cumulative+=len(wins)
            rounds.append(dict(attempt=i,reached=len(reached),new_successes=len(wins),cumulative=cumulative,
                percent_of_all=100*len(wins)/len(possible),conditional_percent=None if not reached else 100*len(wins)/len(reached)))
        results[group+"/"+arm]=dict(cases=len(xs),achievable=len(possible),solved=sum(r["solved"] for r in possible),
            impossible=len(xs)-len(possible),correct_abstain=sum(r["correct_abstain"] for r in xs),rounds=rounds,
            nonexpanding=sum(r["solved"] and not r["attempts"][-1]["facts"]["protected_expansion"] for r in possible),
            expanding=sum(r["solved"] and r["attempts"][-1]["facts"]["protected_expansion"] for r in possible),
            calls=len(attempts),input_tokens=sum(a["usage"]["prompt_tokens"] for a in attempts),
            output_tokens=sum(a["usage"]["completion_tokens"] for a in attempts),
            reasoning_tokens=sum(a["usage"].get("completion_tokens_details",{}).get("reasoning_tokens",0) for a in attempts),
            reported_cost_usd=sum(a["usage"]["cost"] for a in attempts),
            length_finishes=sum(a["finish_reason"]=="length" for a in attempts),
            final_parse_errors=sum(r["attempts"][-1]["parse_error"] is not None for r in xs),
            unauthorized_admissions=sum(r["attempts"][-1]["decisions"][m]["checked"] and r["attempts"][-1]["facts"]["protected_expansion"] for r in xs for m in review.MODES if m!="exact"),
            by_family={f:dict(n=sum(r["family"]==f for r in xs),solved=sum(r["family"]==f and r["solved"] for r in xs)) for f in cases.FAMILIES})
    write(run/"summary.json",dict(model=api.MODEL,provider=api.PROVIDER,results=results,audit=audit_result,scope=plan["scope"]))
    emit(event="summary",results={k:{a:b for a,b in v.items() if a!="by_family"} for k,v in results.items()})


def main():
    p=argparse.ArgumentParser();p.add_argument("command",choices=["prepare","run","audit","summary"])
    p.add_argument("--run-dir",required=True,type=Path);p.add_argument("--group",choices=["dev","test"],default="dev")
    a=p.parse_args();run=a.run_dir.resolve()
    if a.command=="prepare":prepare(run)
    elif a.command=="run":execute(run,a.group)
    elif a.command=="audit":audit(run)
    else:summary(run)


if __name__=="__main__":main()
