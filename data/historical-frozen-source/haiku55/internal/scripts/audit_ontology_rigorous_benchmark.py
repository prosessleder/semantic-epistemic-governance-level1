#!/usr/bin/env python3
"""Independent semantic/authority recount and actual immutable commit replay."""
from dataclasses import replace
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"src")]
from internal.scripts import run_ontology_rigorous_benchmark as runner
from internal.benchmarks import ontology_rigorous_proposals as cases
from internal.benchmarks import ontology_rigorous_review as review
from internal.scripts import run_ontology_modern_models as modern
from internal.scripts.audit_ontology_checked_proposals import reference_candidate,sha
from ontology_boundary.checked_release import ReviewContract,ApprovalRegistry,goals_satisfied
from ontology_boundary.proposal_commit import commit_frame
from ontology_boundary.rdf_adapter import crosscheck_ontology


def dependency_independent(contract,candidate,obj):
    if obj["op"] in ("add_disjoint","remove_disjoint"):return True
    reverse={}
    roots={contract.protected_permission}
    for o in (contract.base,candidate):
        for a,b in o.subclass:reverse.setdefault(b,set()).add(a)
        for rule in o.rules:reverse.setdefault(rule.head,set()).update(rule.antecedents)
        for pair in o.disjoint:roots.update(pair)
    todo=list(roots)
    while todo:
        head=todo.pop()
        for x in reverse.get(head,set())-roots:roots.add(x);todo.append(x)
    touched=set(obj.get("antecedents",[]))|{obj[k] for k in ("left","right","head") if k in obj}
    return bool(touched&roots)


def lifecycle(run):
    data=json.loads((run/"dataset.json").read_text());result=[];owl=profiles=0
    with (run/"lifecycle-rdf.jsonl").open("x") as handle:
        for i,t in enumerate(data["lifecycle"]):
            first=ReviewContract.from_dict(t["first_contract"]);second=ReviewContract.from_dict(t["second_contract"])
            a=reference_candidate(first,t["first_patch"]);b=reference_candidate(second,t["second_patch"])
            old_first,old_second=review.ground(first,a),review.ground(second,b)
            assert old_first["goal_satisfied"] and old_second["goal_satisfied"]
            assert not old_first["protected_expansion"] and not old_second["protected_expansion"]
            current,receipt1=commit_frame(first.base,first,cases.canonical(t["first_patch"]))
            assert receipt1["admitted"] and current==a
            state,stale=commit_frame(current,second,cases.canonical(t["second_patch"]))
            assert not stale["admitted"] and state==current
            fresh=replace(second,base=current);merged=reference_candidate(fresh,t["second_patch"])
            truth=review.ground(fresh,merged)
            assert truth["goal_satisfied"] and truth["protected_expansion"]==t["expected_composed_expansion"]
            assert goals_satisfied(first,merged)
            state,unapproved=commit_frame(current,fresh,cases.canonical(t["second_patch"]))
            assert unapproved["admitted"]==(not t["expected_composed_expansion"])
            assert state==(merged if unapproved["admitted"] else current)
            state,ratified=commit_frame(current,fresh,cases.canonical(t["second_patch"]),review.registry(fresh,merged,"exact"))
            assert ratified["admitted"] and state==merged
            for tag,ontology in (("base",first.base),("first",a),("isolated-second",b),("composed",merged)):
                rdf=crosscheck_ontology(ontology,first.public_classes);assert rdf["matches"]
                handle.write(cases.canonical(dict(sequence_id=t["sequence_id"],state=tag,result=rdf))+"\n");handle.flush()
                owl+=1;profiles+=rdf["profiles_checked"]
            result.append(dict(sequence_id=t["sequence_id"],family=t["family"],composed_expansion=truth["protected_expansion"],
                cached_unbound_admitted=True,cached_unbound_unsafe=truth["protected_expansion"],stale_bound_admitted=False,
                fresh_unratified_admitted=unapproved["admitted"],fresh_exact_admitted=ratified["admitted"]))
            if (i+1)%4==0:runner.emit("lifecycle_progress",completed=i+1,total=48)
    runner.write(run/"lifecycle-results.json",dict(status="PASS",cases=result,owl_ontologies=owl,owl_profiles=profiles,
        rdf_sha256=sha(run/"lifecycle-rdf.jsonl"),constructed_controls=True,
        summary=dict(n=48,cached_unbound_unsafe=sum(r["cached_unbound_unsafe"] for r in result),
            stale_bound_admitted=0,fresh_unratified_admitted=sum(r["fresh_unratified_admitted"] for r in result),
            fresh_exact_admitted=sum(r["fresh_exact_admitted"] for r in result))))
    runner.emit("lifecycle_complete",sequences=48,owl_profiles=profiles)


def audit_model(run,name):
    from transformers import AutoTokenizer
    plan=json.loads((run/"execution-plan.json").read_text());runner.validate_sources(plan["sources"])
    assert sha(run/"dataset.json")==plan["dataset_sha256"]
    selected=[j for j in plan["jobs"] if (j["arm"]=="direct" or name=="gemma4") and (j["group"]!="historical-native" or name=="mistral")]
    cfg=plan["models"][name];out=run/name
    assert runner.installed_versions()==cfg["runtime_versions"],"use the matching model/tokenizer runtime for its audit"
    complete=json.loads((out/"completion.json").read_text())
    assert complete["plan_sha256"]==sha(run/"execution-plan.json") and complete["records_sha256"]==sha(out/"records.jsonl")
    rows=[json.loads(l) for l in (out/"records.jsonl").read_text().splitlines()]
    assert len(rows)==len(selected)==len(cfg["inventory"])
    tok=AutoTokenizer.from_pretrained(cfg["snapshot"],local_files_only=True,trust_remote_code=False)
    count=owl=profiles=0;start=time.monotonic()
    with (out/"audit-rdf.jsonl").open("x") as handle:
        for job,packet,row in zip(selected,cfg["inventory"],rows):
            assert row["job_id"]==job["job_id"]==packet["job_id"]
            assert all(row[k]==v for k,v in packet.items())
            text,ids=runner.encode(tok,job,name)
            assert row["prompt_sha256"]==hashlib.sha256(text.encode()).hexdigest()
            assert row["input_ids_sha256"]==cases.digest(ids)
            raw=tok.decode(modern.strip_terminal_ids(row["generated_token_ids"],set(row["terminal_token_ids"])),skip_special_tokens=False)
            assert row["raw_response"]==raw
            assert all(row[k]==v for k,v in runner.parse(job["arm"],raw).items())
            c=ReviewContract.from_dict(job["task"]["contract"])
            try:candidate=reference_candidate(c,row["proposal"])
            except (ValueError,TypeError):candidate=None
            assert row["facts"]["valid_edit"]==(candidate is not None)
            assert row["candidate"]==(None if candidate is None else candidate.to_dict())
            if candidate is None:
                assert not any(row["decisions"][m][p] for m in review.MODES for p in review.PIPELINES)
            else:
                truth=review.ground(c,candidate)
                for key in ("goal_satisfied","protected_expansion","goal_probe_detected","pairwise_detected","derived_expansion","profiles"):
                    assert row["facts"][key]==truth[key]
                dep=dependency_independent(c,candidate,row["proposal"]);assert dep==row["facts"]["dependency_flag"]
                rdf=crosscheck_ontology(candidate,c.public_classes);assert rdf["matches"]
                handle.write(cases.canonical(dict(job_id=job["job_id"],result=rdf))+"\n");handle.flush()
                owl+=1;profiles+=rdf["profiles_checked"]
                for mode in review.MODES:
                    approved=mode=="exact";reg=review.registry(c,candidate,mode)
                    assert reg.matches(c,candidate)==approved
                    met,exp=truth["goal_satisfied"],truth["protected_expansion"]
                    expected=dict(goal_only=met,current_goal=met and (not truth["goal_probe_detected"] or approved),
                        pairwise=met and (not truth["pairwise_detected"] or approved),dependency_cone=met and (not dep or approved),
                        checked=met and (not exp or approved),derived_only_mutant=met and (not truth["derived_expansion"] or approved),
                        unbound_approval_mutant=met and (not exp or mode in ("exact","stale-base","wrong-candidate","wrong-basis","wrong-query","wrong-scope")))
                    assert row["decisions"][mode]==expected
            for mode in review.MODES:
                reg=ApprovalRegistry() if candidate is None else review.registry(c,candidate,mode)
                state,receipt=commit_frame(c.base,c,row["complete_frame"] or "",reg)
                assert receipt["admitted"]==row["decisions"][mode]["checked"]
                assert state==(candidate if receipt["admitted"] else c.base);count+=1
            assert row["correct_abstain"]==(job["task"].get("expected_abstain",False) and row["proposal"]=={"op":"abstain"})
            if count%(12*9)==0:runner.emit("model_audit_progress",model=name,completed=count//9,total=len(rows))
    result=dict(status="PASS",model=name,records=len(rows),owl_candidates=owl,owl_profiles=profiles,commit_replays=count,
        elapsed_seconds=time.monotonic()-start,records_sha256=sha(out/"records.jsonl"),rdf_sha256=sha(out/"audit-rdf.jsonl"),
        plan_sha256=sha(run/"execution-plan.json"),auditor_sha256=sha(__file__),
        limits="Independent edits/fixed point/goals/authority/baseline recount; shared datatypes, framing and tokenization; no independent GPU execution or deployed action.")
    runner.write(out/"audit.json",result);runner.emit("model_audit_complete",**result)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("lifecycle","model"))
    p.add_argument("--run-dir",type=Path,default=runner.RUN);p.add_argument("--model",choices=runner.NAMES,default="gemma4")
    a=p.parse_args();lifecycle(a.run_dir) if a.action=="lifecycle" else audit_model(a.run_dir,a.model)
