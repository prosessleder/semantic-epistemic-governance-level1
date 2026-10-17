#!/usr/bin/env python3
"""Preregister and execute a blind GLM ontology-approval challenge."""
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime,timezone
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"src")]
from internal.benchmarks import ontology_adjudication as study
from internal.benchmarks import ontology_adjudication_metrics as metrics
from internal.benchmarks import ontology_rigorous_review as review
from internal.benchmarks import ontology_openrouter as api
from internal.scripts import run_ontology_openrouter as previous
from internal.scripts.audit_ontology_checked_proposals import reference_candidate,reference_review,sha
from ontology_boundary.checked_release import ReviewContract
from ontology_boundary.proposal_commit import commit_frame
from ontology_boundary.rdf_adapter import crosscheck_ontology
from ontology_boundary.oracle import Ontology

RESEARCH=ROOT/"internal/research"
PREFLIGHT=ROOT/"runs/glm-adjudication-preflight-2026-10-13"
SOURCES=("internal/benchmarks/ontology_adjudication.py","internal/scripts/run_ontology_adjudication.py",
    "internal/planning/ontology-glm-adjudication-protocol.md","tests/test_ontology_adjudication.py",
    "internal/benchmarks/ontology_adjudication_metrics.py","tests/test_ontology_adjudication_metrics.py")


def rdf_unit(unit):
    c=ReviewContract.from_dict(unit["contract"]);candidate=reference_candidate(c,unit["proposal"])
    outputs=[]
    for name,ontology in (("base",c.base),("candidate",candidate)):
        result=crosscheck_ontology(ontology,c.public_classes);assert result["matches"]
        outputs.append(dict(kind=name,ontology_sha256=ontology.sha256,result=result))
    return dict(unit_id=unit["unit_id"],checks=outputs)


def prepare(run):
    assert not run.exists(),"use a fresh directory"
    parent=RESEARCH/"glm-openrouter-receipts-2026-10-13/glm-openrouter-benchmark-2026-10-13"
    parent_plan=json.loads((parent/"execution-plan.json").read_text())
    # Transport gains a configurable timeout; evaluator/semantic dependencies
    # must still match the preceding frozen study.
    for name,digest in parent_plan["sources"].items():
        if name!="internal/scripts/run_ontology_openrouter.py":assert sha(ROOT/name)==digest,name
    corpus=json.loads((parent/"dataset.json").read_text());old=corpus["dev"]+corpus["test"]
    prior=json.loads((RESEARCH/"ontology-rigorous-receipts-2026-10-13/completed-v2/dataset.json").read_text())
    old+=prior["dev"]+prior["test"]
    old+=[dict(structural_fingerprint=study.cases.structural_fingerprint(ReviewContract.from_dict(t["contract"])),semantic_fingerprint="")
          for t in study.cases.historical.tasks()+study.cases.old_stress.tasks()]
    data=study.dataset(old);run.mkdir(parents=True)
    previous.write(run/"dataset.json",data)
    sources={name:sha(ROOT/name) for name in parent_plan["sources"]}
    sources.update({name:sha(ROOT/name) for name in SOURCES})
    for name in sources:
        p=run/"frozen-source"/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
    model=json.loads((PREFLIGHT/"model.json").read_text())
    eps=json.loads((PREFLIGHT/"endpoints.json").read_text())["data"]["endpoints"]
    endpoint=next(e for e in eps if e["tag"]=="z-ai/fp8")
    assert model["id"]==api.MODEL and model["reasoning"]["mandatory"]
    units={u["unit_id"]:u for u in data["units"]}
    inventory=[dict(scenario_id=s["scenario_id"],request_sha256=study.cases.digest(study.request(units[s["unit_id"]],s))) for s in data["scenarios"]]
    plan=dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(),model=model,endpoint=endpoint,settings=study.SETTINGS,
        workers=4,timeout_seconds=600,reported_budget_usd=5,http_transient_retries=2,
        source_commit="recorded in private Git history before inference",sources=sources,dataset_sha256=sha(run/"dataset.json"),inventory=inventory,
        runtime_versions=previous.local.previous.installed_versions(),
        semantic_units=96,primary_scenarios=480,repeat_controls=16,model_calls=496,
        reference_policy="goal_correct AND (NOT protected_expansion OR exact_matching_trusted_approval)",
        limitations="Known finite motifs; five approval variants share units; no real authentication or tool release")
    previous.write(run/"execution-plan.json",plan)
    profiles=0
    with ProcessPoolExecutor(max_workers=4) as pool,(run/"preflight-rdf.jsonl").open("x") as handle:
        fs=[pool.submit(rdf_unit,u) for u in data["units"]]
        for i,future in enumerate(as_completed(fs),1):
            value=future.result();profiles+=sum(x["result"]["profiles_checked"] for x in value["checks"])
            handle.write(study.cases.canonical(value)+"\n");handle.flush()
            if i%12==0:previous.emit(event="independent_rdf_preflight",done=i,total=96)
    previous.write(run/"preflight.json",dict(status="PASS",units=96,ontology_states=192,profiles=profiles,
        dataset_sha256=sha(run/"dataset.json"),plan_sha256=sha(run/"execution-plan.json"),rdf_sha256=sha(run/"preflight-rdf.jsonl")))
    previous.emit(event="adjudication_frozen",plan_sha256=sha(run/"execution-plan.json"),requests=len(inventory))


def validate(run):
    plan=json.loads((run/"execution-plan.json").read_text());preflight=json.loads((run/"preflight.json").read_text())
    assert preflight["status"]=="PASS" and preflight["plan_sha256"]==sha(run/"execution-plan.json")
    assert plan["dataset_sha256"]==sha(run/"dataset.json")==preflight["dataset_sha256"]
    assert preflight["rdf_sha256"]==sha(run/"preflight-rdf.jsonl")
    assert plan["settings"]==study.SETTINGS
    assert plan["runtime_versions"]==previous.local.previous.installed_versions()
    assert all(sha(ROOT/name)==digest for name,digest in plan["sources"].items())
    return plan,json.loads((run/"dataset.json").read_text())


def execute(run):
    plan,data=validate(run);client=previous.Client(run,plan,timeout_seconds=plan["timeout_seconds"])
    units={u["unit_id"]:u for u in data["units"]};inventory={p["scenario_id"]:p for p in plan["inventory"]};start=time.monotonic()
    def worker(s):
        out=run/"judgments"/(s["scenario_id"]+".json")
        if out.exists():return json.loads(out.read_text())
        body=study.request(units[s["unit_id"]],s)
        assert study.cases.digest(body)==inventory[s["scenario_id"]]["request_sha256"]
        value=client.call(s["scenario_id"],body);choice,usage=api.validate_response(value)
        raw=choice["message"].get("content")
        row=dict(scenario_id=s["scenario_id"],response_sha256=sha(run/"responses"/(s["scenario_id"]+".json")),
            request_sha256=study.cases.digest(body),raw_response=raw,finish_reason=choice.get("finish_reason"),usage=usage,**study.parse(raw))
        previous.write(out,row);return row
    with ThreadPoolExecutor(max_workers=plan["workers"]) as pool:
        fs=[pool.submit(worker,s) for s in data["scenarios"]]
        for i,future in enumerate(as_completed(fs),1):
            row=future.result()
            previous.emit(event="judgment_progress",done=i,total=496,parsed=row["verdict"] is not None,
                finish_reason=row["finish_reason"],seconds=round(time.monotonic()-start,1),reported_cost=round(client.spent,6))
    previous.write(run/"completion.json",dict(status="COMPLETE",requests=496,seconds=time.monotonic()-start,plan_sha256=sha(run/"execution-plan.json")))


def audit(run):
    plan,data=validate(run);complete=json.loads((run/"completion.json").read_text());assert complete["status"]=="COMPLETE"
    units={u["unit_id"]:u for u in data["units"]};rows=[];commits=0
    for s in data["scenarios"]:
        u=units[s["unit_id"]];recomputed=study.scenario(u,s["mode"])
        assert s["registry"]==recomputed["registry"] and s["truth"]==recomputed["truth"]
        c=ReviewContract.from_dict(u["contract"]);candidate=reference_candidate(c,u["proposal"])
        assert candidate.to_dict()==u["candidate"]
        reg=review.registry(c,candidate,s["mode"])
        state,receipt=commit_frame(c.base,c,study.cases.canonical(u["proposal"]),reg)
        independent=reference_review(c,candidate,reg)
        assert receipt["admitted"]==independent["admitted"]==s["truth"]["release_allowed"]
        assert state==(candidate if receipt["admitted"] else c.base);commits+=1
        p=run/"judgments"/(s["scenario_id"]+".json");row=json.loads(p.read_text())
        body=study.request(u,s)
        assert json.loads((run/"requests"/(s["scenario_id"]+".json")).read_text())==body
        assert row["request_sha256"]==study.cases.digest(body)
        response=run/"responses"/(s["scenario_id"]+".json")
        assert row["response_sha256"]==sha(response)
        choice,usage=api.validate_response(json.loads(response.read_text()))
        assert row["raw_response"]==choice["message"].get("content") and row["usage"]==usage and row["finish_reason"]==choice.get("finish_reason")
        assert all(row[k]==v for k,v in study.parse(row["raw_response"]).items())
        rows.append(dict(row,unit_id=s["unit_id"],mode=s["mode"],repeat_of=s["repeat_of"],truth=s["truth"],stratum=u["stratum"],family=u["family"]))
    assert len(rows)==496==len(list((run/"responses").glob("*.json")))
    with (run/"records.jsonl").open("x") as h:
        for r in rows:h.write(study.cases.canonical(r)+"\n")
    previous.write(run/"audit.json",dict(status="PASS",calls=len(rows),semantic_units=96,commit_replays=commits,
        records_sha256=sha(run/"records.jsonl"),plan_sha256=sha(run/"execution-plan.json"),preflight_sha256=sha(run/"preflight.json")))
    previous.emit(event="adjudication_audit_complete",calls=len(rows),commits=commits)


def summary(run):
    plan,data=validate(run);audit_result=json.loads((run/"audit.json").read_text())
    assert audit_result["status"]=="PASS" and audit_result["records_sha256"]==sha(run/"records.jsonl")
    rows=[json.loads(x) for x in (run/"records.jsonl").read_text().splitlines()]
    score=metrics.score(rows)
    usage=dict(calls=len(rows),input_tokens=sum(r["usage"]["prompt_tokens"] for r in rows),
        output_tokens=sum(r["usage"]["completion_tokens"] for r in rows),
        reasoning_tokens=sum(r["usage"].get("completion_tokens_details",{}).get("reasoning_tokens",0) for r in rows),
        reported_cost_usd=sum(r["usage"]["cost"] for r in rows),
        length_finishes=sum(r["finish_reason"]=="length" for r in rows),parse_errors=sum(r["parse_error"] is not None for r in rows))
    previous.write(run/"summary.json",dict(model=api.MODEL,provider=api.PROVIDER,plan_sha256=sha(run/"execution-plan.json"),
        score=score,usage=usage,audit=audit_result))
    previous.emit(event="adjudication_summary",release=score["primary_release"],fields=score["fields"],usage=usage)


def main():
    p=argparse.ArgumentParser();p.add_argument("command",choices=["prepare","run","audit","summary"]);p.add_argument("--run-dir",required=True,type=Path)
    a=p.parse_args();run=a.run_dir.resolve()
    if a.command=="prepare":prepare(run)
    elif a.command=="run":execute(run)
    elif a.command=="audit":audit(run)
    else:summary(run)


if __name__=="__main__":main()
