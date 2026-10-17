#!/usr/bin/env python3
"""Freeze and run the larger local evaluation without altering older studies."""
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"src")]
ORIGINAL=Path("/Users/tobrien/gitw/prosessleder/ontology-conditioned-steering-internal")
RUN=ROOT/"runs/ontology-rigorous-benchmark-2026-10-13"
from internal.benchmarks import ontology_rigorous_proposals as cases
from internal.benchmarks import ontology_rigorous_lifecycle as life
from internal.benchmarks import ontology_rigorous_review as review
from internal.benchmarks import ontology_checked_proposals as historical
from internal.scripts import run_ontology_modern_models as modern
from internal.scripts.analyze_ontology_modern_models import normalize
from internal.scripts.audit_ontology_checked_proposals import reference_candidate,sha
from ontology_boundary.checked_release import ReviewContract,first_proposal_object,ApprovalRegistry
from ontology_boundary.oracle import closure,seed_profiles
from ontology_boundary.rdf_adapter import crosscheck_ontology
from ontology_boundary.proposal_commit import commit_frame

NAMES=("mistral","qwen3","qwen35","gemma4")
NEW_SOURCES=("internal/benchmarks/ontology_rigorous_proposals.py","internal/benchmarks/ontology_rigorous_review.py",
    "internal/benchmarks/ontology_rigorous_lifecycle.py","internal/scripts/run_ontology_rigorous_benchmark.py",
    "internal/scripts/audit_ontology_rigorous_benchmark.py","internal/scripts/summarize_ontology_rigorous_benchmark.py",
    "internal/planning/ontology-rigorous-benchmark-2026-10-13.md","tests/test_ontology_rigorous_benchmark.py",
    "internal/scripts/analyze_ontology_modern_models.py","internal/scripts/run_ontology_latent_proposals.py",
    "internal/benchmarks/ontology_latent_proposals.py")


def write(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with Path(path).open("x") as f:json.dump(value,f,sort_keys=True,indent=2,allow_nan=False);f.write("\n")


def emit(event,**values):print(cases.canonical(dict(event=event,**values)),flush=True)


def installed_versions():
    return dict(python=sys.version,packages={d.metadata["Name"]:d.version for d in metadata.distributions() if d.metadata["Name"]})


def validate_sources(expected):
    for name,value in expected.items():assert sha(ROOT/name)==value,name


def jobs(data):
    result=[dict(job_id="direct/"+t["task_id"],arm="direct",group=t["split"],task=t) for s in ("dev","test") for t in data[s]]
    result += [dict(job_id="alias/"+t["task_id"],arm="direct",group="alias",task=t) for t in data["aliases"]]
    result += [dict(job_id="reasoned/"+t["task_id"],arm="reasoned",group="reasoned",task=t) for t in data["reasoned_subset"]]
    return result


def encode(tok,job,name=None):
    messages=historical.messages(job["task"]) if job["group"]=="historical-native" else cases.messages(job["task"])
    system_text=messages[0]["content"]
    if name=="mistral":
        # This checkpoint's template drops a separate system message when the
        # final message is an assistant continuation. Its normal user rendering
        # combines system and user contents with exactly this separator.
        assert [m["role"] for m in messages]==["system","user"]
        messages=[dict(role="user",content=system_text+"\n\n"+messages[1]["content"])]
    reasoned=job["arm"]=="reasoned"
    if reasoned:
        messages[-1]["content"]=messages[-1]["content"].replace(
            "Return one proposal JSON object only, without prose or extra fields.",
            "You may reason in your native thinking channel. In the final response return one proposal JSON object only, without prose or extra fields.")
    if reasoned:
        text=tok.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=True)
    else:
        text=tok.apply_chat_template(messages+[{"role":"assistant","content":'{"op":'}],tokenize=False,
            continue_final_message=True,enable_thinking=False)
    ids=tok.encode(text,add_special_tokens=False)
    assert system_text in text,"native rendering dropped the system instruction"
    assert len(ids)<=4096,"input overflow; truncation forbidden"
    if reasoned:
        native=tok.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,enable_thinking=True,return_dict=False)
    else:
        native=tok.apply_chat_template(messages+[{"role":"assistant","content":'{"op":'}],tokenize=True,
            continue_final_message=True,enable_thinking=False,return_dict=False)
    assert ids==native,"native template continuation mismatch"
    return text,ids


def parse(arm,raw):
    try:
        if arm=="reasoned":frame,obj,fenced=normalize("gemma4",raw);trailing=""
        else:frame='{"op":'+raw;obj,trailing=first_proposal_object(frame);fenced=False
        cases.canonical(obj)  # Reject non-finite JSON constants; preserve raw text.
        return dict(complete_frame=frame,proposal=obj,trailing_text=trailing,fence_removed=fenced,parse_error=None)
    except ValueError as error:
        return dict(complete_frame=None,proposal=None,trailing_text=None,fence_removed=False,parse_error=str(error))


def prepare_data(run):
    run.mkdir(exist_ok=False,parents=True)
    data=cases.dataset();subset=cases.subsets(data["test"])
    data.update(aliases=[cases.renamed(t) for t in subset],reasoned_subset=subset,lifecycle=life.sequences())
    write(run/"dataset.json",data)
    source_names=("internal/benchmarks/ontology_rigorous_proposals.py","internal/benchmarks/ontology_rigorous_review.py",
        "internal/benchmarks/ontology_rigorous_lifecycle.py","src/ontology_boundary/oracle.py",
        "src/ontology_boundary/checked_release.py","src/ontology_boundary/proposal_commit.py","src/ontology_boundary/rdf_adapter.py")
    write(run/"data-declaration.json",dict(declared_at_utc=datetime.now(timezone.utc).isoformat(),
        dataset_sha256=sha(run/"dataset.json"),sources={p:sha(ROOT/p) for p in source_names},
        generation_versions=installed_versions(),counts={k:len(v) for k,v in data.items()}))
    emit("rigorous_data_frozen",counts={k:len(v) for k,v in data.items()})


def reference_preflight(run):
    declaration=json.loads((run/"data-declaration.json").read_text());validate_sources(declaration["sources"])
    assert sha(run/"dataset.json")==declaration["dataset_sha256"]
    data=json.loads((run/"dataset.json").read_text());results=[];owl=profiles=0
    with (run/"reference-rdf.jsonl").open("x") as raw:
        for i,t in enumerate(data["dev"]+data["test"]):
            c=ReviewContract.from_dict(t["contract"]);candidate,facts,decisions=review.evaluate(c,t["reference_patch"])
            assert (candidate is None)==t["expected_abstain"]
            if candidate is not None:
                independent=reference_candidate(c,t["reference_patch"]);assert independent==candidate
                ground=review.ground(c,candidate)
                for key in ("goal_satisfied","protected_expansion","goal_probe_detected","pairwise_detected","derived_expansion","profiles"):
                    assert facts[key]==ground[key]
                assert facts["goal_satisfied"] and facts["protected_expansion"]==t["reference_expansion"]
            for side,ontology in (("base",c.base),("candidate",candidate)):
                if ontology is None:continue
                result=crosscheck_ontology(ontology,c.public_classes);assert result["matches"]
                raw.write(cases.canonical(dict(task_id=t["task_id"],side=side,result=result))+"\n");raw.flush()
                owl+=1;profiles+=result["profiles_checked"]
            results.append(dict(task_id=t["task_id"],expected_abstain=t["expected_abstain"],facts=facts,decisions=decisions))
            if (i+1)%12==0:emit("reference_preflight_progress",completed=i+1,total=240,owl_ontologies=owl)
    for alias in data["aliases"]:
        primary=next(t for t in data["test"] if t["task_id"]==alias["alias_of"])
        c,a=ReviewContract.from_dict(primary["contract"]),ReviewContract.from_dict(alias["contract"])
        x,y=apply_reference(c,primary["reference_patch"]),apply_reference(a,alias["reference_patch"])
        mapping=alias["alias_mapping"]
        for profile in seed_profiles(c.public_classes):
            for before,after in ((c.base,a.base),(x,y)):
                if before is None:continue
                p=closure(before,profile);q=closure(after,{mapping[z] for z in profile})
                assert p.permissions==q.permissions and p.consistent==q.consistent
    write(run/"reference-preflight.json",dict(status="PASS",cases=results,owl_ontologies=owl,
        owl_profiles=profiles,rdf_records_sha256=sha(run/"reference-rdf.jsonl"),alias_pairs=48))
    emit("reference_preflight_complete",owl_ontologies=owl,owl_profiles=profiles,alias_pairs=48)


def apply_reference(c,patch):
    return reference_candidate(c,patch)


def inventory(run,name):
    from transformers import AutoTokenizer
    old_run="ontology-checked-proposals-2026-10-12" if name in ("mistral","qwen3") else "ontology-modern-models-2026-10-12"
    old_path=ORIGINAL/"runs"/old_run/"execution-plan.json"
    old=json.loads(old_path.read_text());cfg={k:v for k,v in old["models"][name].items() if k not in ("inventory","assistant_prefix")}
    artifacts=modern.checkpoint_artifacts(cfg["snapshot"])
    assert all(artifacts[k]==v for k,v in cfg["artifacts"].items()),"historical checkpoint artifact changed"
    assert {k for k in artifacts if k.endswith(".safetensors")}=={k for k in cfg["artifacts"] if k.endswith(".safetensors")}
    cfg["artifacts"]=artifacts;cfg["parent_plan_sha256"]=sha(old_path)
    tok=AutoTokenizer.from_pretrained(cfg["snapshot"],local_files_only=True,trust_remote_code=False)
    data=json.loads((run/"dataset.json").read_text());cfg["inventory"]=[]
    for job in jobs(data):
        if job["arm"]=="reasoned" and name!="gemma4":continue
        if job["group"]=="historical-native" and name!="mistral":continue
        text,ids=encode(tok,job,name)
        cfg["inventory"].append(dict(job_id=job["job_id"],prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),
            input_ids_sha256=cases.digest(ids),input_tokens=len(ids)))
    cfg["runtime_versions"]=installed_versions()
    write(run/"inventories"/(name+".json"),cfg)
    emit("inventory_complete",model=name,requests=len(cfg["inventory"]),max_input_tokens=max(p["input_tokens"] for p in cfg["inventory"]))


def freeze(run):
    declaration=json.loads((run/"data-declaration.json").read_text());validate_sources(declaration["sources"])
    assert sha(run/"dataset.json")==declaration["dataset_sha256"]
    assert json.loads((run/"reference-preflight.json").read_text())["status"]=="PASS"
    assert json.loads((run/"lifecycle-results.json").read_text())["status"]=="PASS"
    modern_parent=json.loads((ORIGINAL/"runs/ontology-modern-models-2026-10-12/execution-plan.json").read_text())
    sources=dict(modern_parent["sources"],**{p:sha(ROOT/p) for p in NEW_SOURCES})
    validate_sources(sources)
    data=json.loads((run/"dataset.json").read_text())
    plan=dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(),exploratory_design_after_pilots=True,
        dataset_sha256=sha(run/"dataset.json"),reference_preflight_sha256=sha(run/"reference-preflight.json"),
        lifecycle_preflight_sha256=sha(run/"lifecycle-results.json"),
        sources=sources,jobs=jobs(data),models={n:json.loads((run/"inventories"/(n+".json")).read_text()) for n in NAMES},
        settings=dict(seed=20261013,historical_seed=20261012,device="mps",dtype="bfloat16",attention="eager",do_sample=False,
            batch_size=1,use_cache=True,max_input_tokens=4096,direct_cap=96,reasoned_cap=2048))
    assert sum(len(c["inventory"]) for c in plan["models"].values())==1200
    write(run/"execution-plan.json",plan)
    emit("rigorous_execution_frozen",plan_sha256=sha(run/"execution-plan.json"),requests=1200)


def load(cfg,name):
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM
    if name in ("qwen35","gemma4"):return modern.load(cfg)
    assert modern.checkpoint_artifacts(cfg["snapshot"])==cfg["artifacts"]
    tok=AutoTokenizer.from_pretrained(cfg["snapshot"],local_files_only=True,trust_remote_code=False)
    model=AutoModelForCausalLM.from_pretrained(cfg["snapshot"],local_files_only=True,trust_remote_code=False,
        dtype=torch.bfloat16,attn_implementation="eager").to("mps").eval()
    model.requires_grad_(False);assert all(p.device.type=="mps" for p in model.parameters())
    emit("rigorous_model_loaded",model=name,parameters=sum(p.numel() for p in model.parameters()),mps_driver_bytes=torch.mps.driver_allocated_memory())
    return tok,model


def generate(tok,model,arm,ids,cap):
    import torch
    from transformers import StoppingCriteria,StoppingCriteriaList
    eos=model.generation_config.eos_token_id
    terminal={t for t in (eos if isinstance(eos,list) else [eos])+[tok.pad_token_id] if t is not None}
    class Complete(StoppingCriteria):
        def __call__(self,input_ids,scores,**kwargs):
            raw=tok.decode(modern.strip_terminal_ids(input_ids[0,len(ids):].tolist(),terminal),skip_special_tokens=False)
            return parse(arm,raw)["parse_error"] is None
    start=time.monotonic();inputs=torch.tensor([ids],device="mps",dtype=torch.long)
    with torch.inference_mode():
        output=model.generate(input_ids=inputs,attention_mask=torch.ones_like(inputs),do_sample=False,use_cache=True,
            max_new_tokens=cap,pad_token_id=tok.eos_token_id if tok.pad_token_id is None else tok.pad_token_id,
            stopping_criteria=StoppingCriteriaList([Complete()]))
    tokens=output[0,len(ids):].cpu().tolist()
    raw=tok.decode(modern.strip_terminal_ids(tokens,terminal),skip_special_tokens=False)
    del output,inputs
    return dict(raw_response=raw,generated_token_ids=tokens,terminal_token_ids=sorted(terminal),output_tokens=len(tokens),
        hit_cap=len(tokens)==cap,seconds=time.monotonic()-start,**parse(arm,raw))


def execute(run,name):
    import torch
    plan=json.loads((run/"execution-plan.json").read_text());validate_sources(plan["sources"])
    assert sha(run/"dataset.json")==plan["dataset_sha256"]
    cfg=plan["models"][name];assert installed_versions()==cfg["runtime_versions"]
    assert torch.backends.mps.is_available(),"MPS unavailable"
    selected=[j for j in plan["jobs"] if (j["arm"]=="direct" or name=="gemma4") and (j["group"]!="historical-native" or name=="mistral")]
    assert len(selected)==len(cfg["inventory"])
    out=run/name;out.mkdir(exist_ok=False);start=time.monotonic();torch.manual_seed(plan["settings"]["seed"])
    tok,model=load(cfg,name);rows=[]
    with (out/"records.jsonl").open("x") as handle:
        for job,packet in zip(selected,cfg["inventory"]):
            if job["group"]=="historical-native":torch.manual_seed(plan["settings"]["historical_seed"])
            text,ids=encode(tok,job,name)
            assert packet["job_id"]==job["job_id"]
            assert hashlib.sha256(text.encode()).hexdigest()==packet["prompt_sha256"]
            assert cases.digest(ids)==packet["input_ids_sha256"]
            cap=plan["settings"]["direct_cap" if job["arm"]=="direct" else "reasoned_cap"]
            row=dict(packet,group=job["group"],arm=job["arm"],task_id=job["task"]["task_id"],family=job["task"]["family"],
                expected_abstain=job["task"].get("expected_abstain",False),alias_of=job["task"].get("alias_of"),**generate(tok,model,job["arm"],ids,cap))
            c=ReviewContract.from_dict(job["task"]["contract"]);candidate,facts,decisions=review.evaluate(c,row["proposal"])
            row.update(facts=facts,decisions=decisions,candidate=None if candidate is None else candidate.to_dict(),
                correct_abstain=row["expected_abstain"] and row["proposal"]=={"op":"abstain"})
            handle.write(cases.canonical(row)+"\n");handle.flush();rows.append(row)
            if len(rows)%12==0 or job["arm"]=="reasoned":
                emit("rigorous_progress",model=name,completed=len(rows),total=len(selected),group=job["group"],
                    goal_satisfied=facts["goal_satisfied"],seconds=round(time.monotonic()-start,2))
    write(out/"completion.json",dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),
        plan_sha256=sha(run/"execution-plan.json"),records_sha256=sha(out/"records.jsonl"),requests=len(rows),
        elapsed_seconds=time.monotonic()-start,mps_driver_bytes=torch.mps.driver_allocated_memory()))
    emit("rigorous_model_complete",model=name,requests=len(rows),seconds=round(time.monotonic()-start,2))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("prepare-data","reference-preflight","inventory","freeze","run"))
    p.add_argument("--run-dir",type=Path,default=RUN);p.add_argument("--model",choices=NAMES,default="gemma4")
    a=p.parse_args()
    if a.action=="prepare-data":prepare_data(a.run_dir)
    elif a.action=="reference-preflight":reference_preflight(a.run_dir)
    elif a.action=="inventory":inventory(a.run_dir,a.model)
    elif a.action=="freeze":freeze(a.run_dir)
    else:execute(a.run_dir,a.model)
