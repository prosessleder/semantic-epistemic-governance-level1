#!/usr/bin/env python3
"""Frozen local Gemma development and paired fresh evaluation with tool feedback."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from internal.benchmarks import ontology_gemma_feedback as feedback
from internal.benchmarks import ontology_rigorous_proposals as cases
from internal.benchmarks import ontology_rigorous_review as review
from internal.scripts import run_ontology_rigorous_benchmark as previous
from internal.scripts import run_ontology_modern_models as modern
from internal.scripts.audit_ontology_checked_proposals import reference_candidate, reference_review, sha
from ontology_boundary.checked_release import ReviewContract, ApprovalRegistry
from ontology_boundary.proposal_commit import commit_frame
from ontology_boundary.rdf_adapter import crosscheck_ontology

PARENT = ROOT / "runs/ontology-rigorous-benchmark-2026-10-13"
NEW_SOURCES = (
    "internal/benchmarks/ontology_gemma_feedback.py",
    "internal/scripts/run_ontology_gemma_feedback.py",
    "internal/planning/ontology-gemma-feedback-protocol.md",
    "tests/test_ontology_gemma_feedback.py",
    "internal/benchmarks/ontology_goal_feedback_text.py",
    "tests/test_ontology_goal_feedback_text.py",
    "tests/test_ontology_gemma_feedback_selection.py",
)


def write(path, value):
    previous.write(path, value)


def fresh_tasks(old, n=16):
    seen = {t["structural_fingerprint"] for t in old["dev"] + old["test"]}
    seen |= {cases.structural_fingerprint(ReviewContract.from_dict(t["contract"]))
             for t in cases.historical.tasks() + cases.old_stress.tasks()}
    semantic = {t["semantic_fingerprint"] for t in old["dev"] + old["test"]}
    tasks = []
    for family in cases.FAMILIES:
        for slot in range(16, 16+n):
            for draw in range(300):
                t = cases.instance(family, "test", slot, draw)
                if t["structural_fingerprint"] not in seen and t["semantic_fingerprint"] not in semantic:
                    seen.add(t["structural_fingerprint"]); semantic.add(t["semantic_fingerprint"])
                    t["task_id"] = t["task_id"].replace("rigor-v2-test", "gemma-feedback-test")
                    tasks.append(t); break
            else:
                raise RuntimeError("could not generate a fresh case")
    assert len(tasks) == 12*n
    return tasks


def encode(tok, task, arm, attempts):
    if arm == "baseline":
        assert not attempts
        return previous.encode(tok, dict(task=task, group="test", arm="direct"), "gemma4")
    return feedback.encode(tok, task, attempts)


def prepare(run, phase, development_run=None):
    from transformers import AutoTokenizer
    assert not run.exists(), "use a fresh run directory"
    parent = json.loads((PARENT / "execution-plan.json").read_text())
    previous.validate_sources(parent["sources"])
    assert sha(PARENT / "dataset.json") == parent["dataset_sha256"]
    old = json.loads((PARENT / "dataset.json").read_text())
    selection = None
    if phase == "test":
        assert development_run is not None, "freeze a completed audited development selection first"
        development_run = Path(development_run).resolve()
        dev_summary = json.loads((development_run/"summary.json").read_text())
        dev_plan = json.loads((development_run/"execution-plan.json").read_text())
        assert dev_summary["phase"] == "dev" and dev_summary["audit"]["status"] == "PASS"
        assert dev_summary["plan_sha256"] == sha(development_run/"execution-plan.json")
        assert dev_summary["audit"]["records_sha256"] == sha(development_run/"gemma4/records.jsonl")
        assert dev_plan["sources"]["internal/benchmarks/ontology_gemma_feedback.py"] == sha(ROOT/"internal/benchmarks/ontology_gemma_feedback.py")
        selection = dict(development_run=str(development_run),summary_sha256=sha(development_run/"summary.json"),
            plan_sha256=sha(development_run/"execution-plan.json"),results=dev_summary["results"])
    tasks = ([t for f in cases.FAMILIES for t in [x for x in old["dev"] if x["family"] == f][:2]]
             if phase == "dev" else fresh_tasks(old))
    arms = ["assisted"] if phase == "dev" else ["baseline", "assisted"]
    cfg = {k: v for k, v in parent["models"]["gemma4"].items() if k != "inventory"}
    assert previous.installed_versions() == cfg["runtime_versions"]
    assert modern.checkpoint_artifacts(cfg["snapshot"]) == cfg["artifacts"]
    tok = AutoTokenizer.from_pretrained(cfg["snapshot"], local_files_only=True, trust_remote_code=False)
    if selection:
        dev_tasks = json.loads((development_run/"dataset.json").read_text())
        dev_inventory = {p["task_id"]:p for p in dev_plan["inventory"] if p["arm"]=="assisted"}
        for task in dev_tasks:
            text,ids=encode(tok,task,"assisted",[])
            packet=dev_inventory[task["task_id"]]
            assert packet["prompt_sha256"]==hashlib.sha256(text.encode()).hexdigest()
            assert packet["input_ids_sha256"]==cases.digest(ids)
        selection["initial_development_inputs_matched"] = len(dev_tasks)
    run.mkdir(parents=True)
    write(run / "dataset.json", tasks)
    inventories = []
    references = []
    for task in tasks:
        c = ReviewContract.from_dict(task["contract"])
        candidate, facts, decisions = review.evaluate(c, task["reference_patch"])
        independent = reference_candidate(c, task["reference_patch"])
        assert candidate == independent
        if candidate is not None:
            truth = review.ground(c, independent)
            assert truth["goal_satisfied"] and facts["goal_satisfied"]
            for k in ("goal_satisfied", "protected_expansion", "goal_probe_detected", "pairwise_detected", "derived_expansion", "profiles"):
                assert facts[k] == truth[k], k
            assert decisions["exact"]["checked"]
        else:
            assert task["expected_abstain"]
        references.append(dict(task_id=task["task_id"], facts=facts))
        for arm in arms:
            text, ids = encode(tok, task, arm, [])
            inventories.append(dict(task_id=task["task_id"], arm=arm,
                prompt_sha256=hashlib.sha256(text.encode()).hexdigest(), input_ids_sha256=cases.digest(ids), input_tokens=len(ids)))
    write(run / "reference-preflight.json", dict(status="PASS", cases=references, independent_semantics=True))
    sources = dict(parent["sources"], **{p: sha(ROOT/p) for p in NEW_SOURCES})
    previous.validate_sources(sources)
    for name in sources:
        target = run / "frozen-source" / name
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes((ROOT/name).read_bytes())
    plan = dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(), phase=phase,
        development_selection=selection,
        parent_plan_sha256=sha(PARENT/"execution-plan.json"), sources=sources,
        dataset_sha256=sha(run/"dataset.json"), reference_sha256=sha(run/"reference-preflight.json"),
        model=cfg, inventory=inventories, arms=arms,
        settings=dict(seed=2026101401, assisted_cap=384, baseline_cap=96, max_attempts=3,
                      device="mps", dtype="bfloat16", attention="eager", do_sample=False, native_thinking=False),
        evaluation_scope="Known synthetic motif families; fresh structural and semantic instances for TEST",
        intervention_scope="Computed goal states, prompt procedure, short explanation and bounded execution-feedback retries jointly changed")
    write(run/"execution-plan.json", plan)
    previous.emit("gemma_feedback_frozen", phase=phase, tasks=len(tasks), arms=arms,
        plan_sha256=sha(run/"execution-plan.json"), max_initial_tokens=max(p["input_tokens"] for p in inventories))


def generate(tok, model, ids, arm, cap):
    import torch
    from transformers import StoppingCriteria, StoppingCriteriaList
    eos = model.generation_config.eos_token_id
    terminal = {t for t in (eos if isinstance(eos,list) else [eos]) + [tok.pad_token_id] if t is not None}
    def parse(raw):
        return previous.parse("direct", raw) if arm == "baseline" else feedback.parse(raw)
    class Complete(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs):
            raw = tok.decode(modern.strip_terminal_ids(input_ids[0,len(ids):].tolist(), terminal), skip_special_tokens=False)
            return parse(raw)["parse_error"] is None
    start = time.monotonic()
    inputs = torch.tensor([ids], device="mps", dtype=torch.long)
    with torch.inference_mode():
        output = model.generate(input_ids=inputs, attention_mask=torch.ones_like(inputs), do_sample=False,
            use_cache=True, max_new_tokens=cap, pad_token_id=tok.eos_token_id if tok.pad_token_id is None else tok.pad_token_id,
            stopping_criteria=StoppingCriteriaList([Complete()]))
    tokens = output[0,len(ids):].cpu().tolist()
    raw = tok.decode(modern.strip_terminal_ids(tokens, terminal), skip_special_tokens=False)
    return dict(raw_response=raw, generated_token_ids=tokens, terminal_token_ids=sorted(terminal),
        output_tokens=len(tokens), hit_cap=len(tokens)==cap, seconds=time.monotonic()-start, **parse(raw))


def execute(run):
    import torch
    plan = json.loads((run/"execution-plan.json").read_text()); previous.validate_sources(plan["sources"])
    assert sha(run/"dataset.json") == plan["dataset_sha256"]
    assert previous.installed_versions() == plan["model"]["runtime_versions"]
    assert torch.backends.mps.is_available()
    out = run/"gemma4"; out.mkdir(exist_ok=False)
    tasks = json.loads((run/"dataset.json").read_text()); start = time.monotonic()
    torch.manual_seed(plan["settings"]["seed"])
    tok, model = modern.load(plan["model"])
    inventory = {(p["arm"], p["task_id"]): p for p in plan["inventory"]}
    with (out/"records.jsonl").open("x") as handle:
        for arm in plan["arms"]:
            for index, task in enumerate(tasks):
                c = ReviewContract.from_dict(task["contract"]); attempts = []
                max_attempts = 1 if arm == "baseline" else plan["settings"]["max_attempts"]
                for number in range(max_attempts):
                    text, ids = encode(tok, task, arm, attempts)
                    packet = dict(prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),
                                  input_ids_sha256=cases.digest(ids), input_tokens=len(ids))
                    if number == 0:
                        assert all(inventory[arm,task["task_id"]][k] == v for k,v in packet.items())
                    cap = plan["settings"]["baseline_cap" if arm == "baseline" else "assisted_cap"]
                    attempt = dict(attempt=number+1, **packet, **generate(tok, model, ids, arm, cap))
                    attempt["diagnostic"] = feedback.diagnostic(c, attempt["proposal"])
                    candidate, facts, decisions = review.evaluate(c, attempt["proposal"])
                    attempt.update(facts=facts, decisions=decisions, candidate=None if candidate is None else candidate.to_dict())
                    attempts.append(attempt)
                    if arm == "baseline" or facts["goal_satisfied"] or attempt["proposal"] == {"op":"abstain"}:
                        break
                row = dict(task_id=task["task_id"], family=task["family"], arm=arm,
                    expected_abstain=task["expected_abstain"], attempts=attempts,
                    solved=attempts[-1]["facts"]["goal_satisfied"],
                    correct_abstain=task["expected_abstain"] and attempts[-1]["proposal"] == {"op":"abstain"})
                handle.write(cases.canonical(row)+"\n"); handle.flush()
                previous.emit("gemma_feedback_progress", arm=arm, completed=index+1, total=len(tasks),
                    attempts=len(attempts), solved=row["solved"], correct_abstain=row["correct_abstain"],
                    seconds=round(time.monotonic()-start, 1))
    write(out/"completion.json",dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),
        plan_sha256=sha(run/"execution-plan.json"), records_sha256=sha(out/"records.jsonl"),
        cases=len(tasks)*len(plan["arms"]), elapsed_seconds=time.monotonic()-start))


def independent_diagnostic(c, candidate, obj, computed):
    if candidate is None:
        assert computed["status"] == ("abstained" if obj == {"op":"abstain"} else "invalid-edit")
        return
    for goal, item in zip(c.goals, computed["goal_states"]):
        state = review.materialize(candidate.to_dict(), goal.profile)
        key = {"class":"classes", "derived":"derived", "effective":"effective"}[goal.kind]
        actual = goal.target in state[key]
        assert item["goal"] == goal.to_dict() and item["actual"] == actual and item["passed"] == (actual == goal.expected)
        assert set(item["derived_classes"]) == state["classes"]
        assert set(item["derived_permissions"]) == state["derived"]
        assert set(item["effective_permissions"]) == state["effective"]
        conflicts = sorted(sorted(p) for p in candidate.disjoint if set(p) <= state["classes"])
        assert sorted(item["inconsistent_pairs"]) == conflicts
    assert len(computed["goal_states"]) == len(c.goals)
    assert computed["status"] == ("goals-met" if all(x["passed"] for x in computed["goal_states"]) else "goals-failed")


def audit(run):
    from transformers import AutoTokenizer
    start = time.monotonic(); plan = json.loads((run/"execution-plan.json").read_text())
    previous.validate_sources(plan["sources"])
    assert previous.installed_versions() == plan["model"]["runtime_versions"]
    assert sha(run/"dataset.json") == plan["dataset_sha256"]
    assert sha(run/"reference-preflight.json") == plan["reference_sha256"]
    out = run/"gemma4"; complete = json.loads((out/"completion.json").read_text())
    assert complete["plan_sha256"] == sha(run/"execution-plan.json") and complete["records_sha256"] == sha(out/"records.jsonl")
    rows = [json.loads(s) for s in (out/"records.jsonl").read_text().splitlines()]
    tasks = json.loads((run/"dataset.json").read_text())
    jobs = [(arm,t) for arm in plan["arms"] for t in tasks]
    assert len(rows) == len(jobs) == complete["cases"]
    tok = AutoTokenizer.from_pretrained(plan["model"]["snapshot"], local_files_only=True, trust_remote_code=False)
    owl=profiles=commits=attempt_count=0
    with (out/"audit-rdf.jsonl").open("x") as handle:
        for index,(row,(arm,task)) in enumerate(zip(rows,jobs)):
            assert row["arm"] == arm and row["task_id"] == task["task_id"] and row["family"] == task["family"]
            assert row["expected_abstain"] == task["expected_abstain"]
            c=ReviewContract.from_dict(task["contract"])
            independent_diagnostic(c,c.base,None,dict(status="goals-failed",goal_states=feedback.goal_states(c,c.base)))
            attempts=[]
            for i,a in enumerate(row["attempts"]):
                assert a["attempt"] == i+1
                text,ids=encode(tok,task,arm,attempts)
                assert a["prompt_sha256"] == hashlib.sha256(text.encode()).hexdigest()
                assert a["input_ids_sha256"] == cases.digest(ids) and a["input_tokens"] == len(ids)
                raw=tok.decode(modern.strip_terminal_ids(a["generated_token_ids"],set(a["terminal_token_ids"])),skip_special_tokens=False)
                assert a["raw_response"] == raw
                parsed=previous.parse("direct",raw) if arm=="baseline" else feedback.parse(raw)
                assert all(a[k]==v for k,v in parsed.items())
                assert a["output_tokens"] == len(a["generated_token_ids"])
                cap=plan["settings"]["baseline_cap" if arm=="baseline" else "assisted_cap"]
                assert a["output_tokens"] <= cap and a["hit_cap"] == (a["output_tokens"]==cap)
                try: candidate=reference_candidate(c,a["proposal"])
                except (ValueError,TypeError): candidate=None
                assert a["candidate"] == (None if candidate is None else candidate.to_dict())
                assert a["facts"]["valid_edit"] == (candidate is not None)
                independent_diagnostic(c,candidate,a["proposal"],a["diagnostic"])
                if candidate is not None:
                    truth=review.ground(c,candidate)
                    assert a["facts"]["goal_satisfied"] == truth["goal_satisfied"]
                    for k in ("protected_expansion","goal_probe_detected","pairwise_detected","derived_expansion","profiles"):
                        assert a["facts"][k] == truth[k]
                else:
                    assert not a["facts"]["goal_satisfied"]
                if i+1 < len(row["attempts"]):
                    assert not a["facts"]["goal_satisfied"] and a["proposal"] != {"op":"abstain"}
                attempts.append(a); attempt_count+=1
            final=attempts[-1]
            assert 1 <= len(attempts) <= (1 if arm=="baseline" else plan["settings"]["max_attempts"])
            assert len(attempts)==(1 if arm=="baseline" else plan["settings"]["max_attempts"]) or final["facts"]["goal_satisfied"] or final["proposal"]=={"op":"abstain"}
            assert row["solved"] == final["facts"]["goal_satisfied"]
            assert row["correct_abstain"] == (task["expected_abstain"] and final["proposal"]=={"op":"abstain"})
            try: candidate=reference_candidate(c,final["proposal"])
            except (ValueError,TypeError): candidate=None
            if candidate is not None:
                rdf=crosscheck_ontology(candidate,c.public_classes); assert rdf["matches"]
                handle.write(cases.canonical(dict(arm=arm,task_id=task["task_id"],result=rdf))+"\n"); handle.flush()
                owl+=1; profiles+=rdf["profiles_checked"]
            for mode in review.MODES:
                reg=review.registry(c,candidate,mode) if candidate is not None else ApprovalRegistry()
                state,receipt=commit_frame(c.base,c,final["complete_frame"] or "",reg)
                admitted=False if candidate is None else reference_review(c,candidate,reg)["admitted"]
                assert receipt["admitted"]==admitted==final["decisions"][mode]["checked"]
                assert state==(candidate if admitted else c.base)
                commits+=1
            if (index+1)%12==0:previous.emit("gemma_feedback_audit_progress",completed=index+1,total=len(rows))
    write(out/"audit.json",dict(status="PASS",cases=len(rows),attempts=attempt_count,owl_candidates=owl,
        owl_profiles=profiles,commit_replays=commits,seconds=time.monotonic()-start,
        records_sha256=sha(out/"records.jsonl"),rdf_sha256=sha(out/"audit-rdf.jsonl"),plan_sha256=sha(run/"execution-plan.json")))


def summary(run):
    plan=json.loads((run/"execution-plan.json").read_text()); out=run/"gemma4"
    audit_result=json.loads((out/"audit.json").read_text()); assert audit_result["status"]=="PASS"
    assert audit_result["records_sha256"]==sha(out/"records.jsonl")
    rows=[json.loads(s) for s in (out/"records.jsonl").read_text().splitlines()]
    results={}
    for arm in plan["arms"]:
        xs=[r for r in rows if r["arm"]==arm]; achievable=[r for r in xs if not r["expected_abstain"]]
        attempts=[a for r in xs for a in r["attempts"]]
        results[arm]=dict(cases=len(xs),achievable=len(achievable),solved=sum(r["solved"] for r in achievable),
            impossible=len(xs)-len(achievable),correct_abstain=sum(r["correct_abstain"] for r in xs),
            first_attempt_solved=sum(r["attempts"][0]["facts"]["goal_satisfied"] for r in achievable),
            useful_nonexpanding=sum(r["solved"] and not r["attempts"][-1]["facts"].get("protected_expansion",False) for r in achievable),
            useful_expanding=sum(r["solved"] and r["attempts"][-1]["facts"].get("protected_expansion",False) for r in achievable),
            model_calls=len(attempts),generated_tokens=sum(a["output_tokens"] for a in attempts),
            generation_seconds=sum(a["seconds"] for a in attempts),capped_attempts=sum(a["hit_cap"] for a in attempts),
            final_parse_errors=sum(r["attempts"][-1]["parse_error"] is not None for r in xs),
            unauthorized_admissions=sum(r["attempts"][-1]["decisions"][m]["checked"] and
                r["attempts"][-1]["facts"].get("protected_expansion",False) for r in xs for m in review.MODES if m!="exact"),
            by_family={f:dict(n=sum(r["family"]==f for r in xs),solved=sum(r["family"]==f and r["solved"] for r in xs),
                abstained=sum(r["family"]==f and r["correct_abstain"] for r in xs)) for f in cases.FAMILIES})
    paired=None
    if "baseline" in results:
        import random
        base={r["task_id"]:r for r in rows if r["arm"]=="baseline"}
        assisted=[r for r in rows if r["arm"]=="assisted" and not r["expected_abstain"]]
        strata=[[int(r["solved"])-int(base[r["task_id"]]["solved"]) for r in assisted if r["family"]==f]
                for f in cases.FAMILIES if f!="unsatisfiable-empty"]
        rng=random.Random(2026101401)
        draws=sorted(sum(rng.choice(xs) for xs in strata for _ in xs)/len(assisted) for _ in range(10000))
        paired=dict(rescued=sum(r["solved"] and not base[r["task_id"]]["solved"] for r in assisted),
            lost=sum(not r["solved"] and base[r["task_id"]]["solved"] for r in assisted),
            rate_difference=(results["assisted"]["solved"]-results["baseline"]["solved"])/len(assisted),
            conditional_stratified_bootstrap_95=[draws[249],draws[9749]],draws=10000,seed=2026101401,
            scope="Paired instances within eleven fixed synthetic motifs; no causal budget or feedback isolation")
    result=dict(phase=plan["phase"],plan_sha256=sha(run/"execution-plan.json"),results=results,paired=paired,audit=audit_result,
        intervention_scope=plan["intervention_scope"])
    write(run/"summary.json",result);previous.emit("gemma_feedback_summary",**result)


def main():
    p=argparse.ArgumentParser();p.add_argument("command",choices=["prepare","run","audit","summary"])
    p.add_argument("--run-dir",required=True);p.add_argument("--phase",choices=["dev","test"],default="dev")
    p.add_argument("--development-run")
    args=p.parse_args();run=Path(args.run_dir)
    if not run.is_absolute():run=ROOT/run
    if args.command=="prepare":prepare(run,args.phase,args.development_run)
    elif args.command=="run":execute(run)
    elif args.command=="audit":audit(run)
    else:summary(run)


if __name__=="__main__":main()
