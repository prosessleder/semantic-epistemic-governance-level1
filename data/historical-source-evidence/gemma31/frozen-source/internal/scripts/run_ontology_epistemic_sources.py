#!/usr/bin/env python3
"""Frozen one-shot epistemic-source study, with auditable hosted receipts.

DEV and TEST share a single model-level budget. Transport retries repeat an
identical request and never provide semantic correction. No reference answer,
case condition, or private ontology is interpolated by this runner.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import argparse
import fcntl
import hashlib
import http.client
import importlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
ENV = ROOT.parent / "ontology-conditioned-steering-internal/.env"
CONFIGS = {
    "qwen38": dict(model="qwen/qwen3.8-27b", provider="Chutes", tag="chutes/fp8",
                   reasoning=dict(effort="medium", exclude=False)),
    "gemma31": dict(model="google/gemma-4-31b-it", provider="DeepInfra", tag="deepinfra/fp8",
                    reasoning=dict(enabled=True, exclude=False)),
}


def study():
    return importlib.import_module("internal.benchmarks.ontology_epistemic_sources")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    """Do not replace an existing immutable receipt, even on resume."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        handle.write(canonical(value) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def emit(**value):
    print(json.dumps(value), flush=True)


def now():
    return datetime.now(timezone.utc).isoformat()


def load_key():
    values = [line.split("=", 1)[1].strip().strip("\"'")
              for line in ENV.read_text().splitlines() if line.startswith("OPENROUTER_API_KEY=")]
    if len(values) != 1 or not values[0]:
        raise ValueError("Expected one OpenRouter credential in the ignored project environment")
    return values[0]


def settings(config):
    return dict(temperature=0, max_tokens=8192, reasoning=config["reasoning"],
                provider=dict(only=[config["tag"]], allow_fallbacks=False, require_parameters=True),
                stream=False)


def request(plan, case):
    messages = study().request(case)
    if isinstance(messages, dict):
        if set(messages) != {"messages"}:
            raise ValueError("Benchmark request must expose only messages")
        messages = messages["messages"]
    if not isinstance(messages, list) or not messages:
        raise ValueError("Benchmark request must provide a nonempty message list")
    return dict(model=plan["config"]["model"], messages=messages, **plan["settings"])


def read_url(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def metadata(config):
    catalog = read_url("https://openrouter.ai/api/v1/models")
    model = next(x for x in catalog["data"] if x["id"] == config["model"])
    endpoints = read_url("https://openrouter.ai/api/v1/models/" + config["model"] + "/endpoints")
    endpoint = next(x for x in endpoints["data"]["endpoints"] if x["tag"] == config["tag"])
    if endpoint["status"] != 0 or "reasoning" not in endpoint["supported_parameters"]:
        raise ValueError("Pinned endpoint is unavailable or does not support reasoning")
    if endpoint["max_completion_tokens"] < 8192:
        raise ValueError("Pinned endpoint does not support the frozen token cap")
    for field in ("prompt", "completion"):
        value = float(endpoint["pricing"][field])
        if not math.isfinite(value) or value < 0:
            raise ValueError("Missing finite endpoint prices")
    return model, endpoints, endpoint


def source_files(extra=()):
    study()
    paths = {Path(__file__).resolve()}
    # Include the actual dependency closure after corpus validation and message
    # rendering, plus explicitly named protocol and test files.
    for module in list(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if name:
            path = Path(name).resolve()
            if path.suffix == ".py" and path.is_relative_to(ROOT):
                paths.add(path)
    for name in extra:
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError("Additional frozen source must be an existing project file")
        paths.add(path)
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}


def reference_check(case):
    module = study()
    if hasattr(module, "audit_case"):
        result = module.audit_case(case)
        if result is False:
            raise ValueError("Benchmark reference audit failed")
    elif hasattr(module, "reference"):
        if module.reference(case["input"]) != case["reference"]:
            raise ValueError("Benchmark reference recomputation differs")
    else:
        raise ValueError("Benchmark must expose audit_case or reference for receipt auditing")


def prepare(run, alias, dataset_path, audit_path, extra=(), workers=4):
    if run.exists():
        raise ValueError("Run directory already exists")
    data = read(dataset_path)
    cases = data["cases"] if isinstance(data, dict) else data
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset must contain cases")
    independent = read(audit_path)
    if independent.get("status") != "PASS" or independent.get("dataset_sha256") != sha(dataset_path):
        raise ValueError("Independent PASS audit must bind the exact dataset bytes")
    independent_refs = {row["id"]: row["independent_reference"] for row in independent["case_receipts"]}
    if len(independent_refs) != len(cases) or set(independent_refs) != {case["id"] for case in cases}:
        raise ValueError("Independent audit does not cover the exact case inventory")
    ids = set()
    for case in cases:
        if not {"id", "split", "condition", "unit_id", "input", "reference"} <= set(case):
            raise ValueError("Missing required private corpus fields")
        if case["id"] in ids or case["split"] not in ("dev", "test"):
            raise ValueError("Duplicate case ID or invalid split")
        if not isinstance(case["id"], str) or not case["id"] or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in case["id"]):
            raise ValueError("Unsafe case identifier")
        ids.add(case["id"])
        if independent_refs[case["id"]] != case["reference"]:
            raise ValueError("Corpus reference differs from the independent audit")
        reference_check(case)
    if not all(any(c["split"] == split for c in cases) for split in ("dev", "test")):
        raise ValueError("Both development and test cases are required")
    dev_ids = data.get("dev_call_ids") if isinstance(data, dict) else None
    if not dev_ids or len(set(dev_ids)) != len(dev_ids):
        raise ValueError("Corpus must predeclare a unique nonempty dev_call_ids list")
    if any(not any(c["id"] == cid and c["split"] == "dev" for c in cases) for cid in dev_ids):
        raise ValueError("Development call IDs must refer to development cases")
    config = CONFIGS[alias]
    model, endpoints, endpoint = metadata(config)
    plan = dict(alias=alias, config=config, settings=settings(config), model=model,
                endpoint=endpoint, total_budget_usd=8.0, workers=workers,
                timeout_seconds=600, transport_retries=2, judgments_per_case=1,
                frozen_at_utc=now(), runtime=dict(python=sys.version, platform=platform.platform()),
                scope="One-shot source and evidence adjudication; no model correction or answer-based retry")
    bodies = {c["id"]: request(plan, c) for c in cases}
    required = ("internal/scripts/audit_ontology_epistemic_sources.py",
                "internal/planning/ontology-epistemic-sources-protocol.md",
                "tests/test_ontology_epistemic_sources.py", "tests/test_ontology_epistemic_runner.py")
    sources = source_files((*required, *extra))
    run.mkdir(parents=True)
    write(run / "dataset.json", data)
    write(run / "model.json", model)
    write(run / "endpoints.json", endpoints)
    shutil.copyfile(audit_path, run / "independent-audit.json")
    for name in sources:
        destination = run / "frozen-source" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    for cid, body in bodies.items():
        write(run / "frozen-requests" / (cid + ".json"), body)
    plan.update(dataset_sha256=sha(run / "dataset.json"), original_dataset_sha256=sha(dataset_path),
                independent_audit_sha256=sha(run / "independent-audit.json"), sources=sources,
                requests={cid: digest(body) for cid, body in bodies.items()},
                source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                dev_call_ids=dev_ids,
                cases={split: sum(c["split"] == split for c in cases) for split in ("dev", "test")},
                planned_calls=dict(dev=len(dev_ids), test=sum(c["split"] == "test" for c in cases)))
    write(run / "execution-plan.json", plan)
    write(run / "preflight.json", dict(status="PASS", cases=len(cases),
          plan_sha256=sha(run / "execution-plan.json"), reference_recomputations=len(cases)))
    emit(event="frozen", alias=alias, cases=plan["cases"], budget_usd=8,
         plan_sha256=sha(run / "execution-plan.json"))


def validate(run):
    plan = read(run / "execution-plan.json")
    if read(run / "preflight.json")["plan_sha256"] != sha(run / "execution-plan.json"):
        raise ValueError("Frozen plan changed")
    if plan["config"] != CONFIGS[plan["alias"]] or plan["settings"] != settings(plan["config"]):
        raise ValueError("Configuration changed")
    if plan["total_budget_usd"] != 8 or plan["judgments_per_case"] != 1:
        raise ValueError("Budget or design changed")
    if plan["dataset_sha256"] != sha(run / "dataset.json"):
        raise ValueError("Dataset changed")
    independent = read(run / "independent-audit.json")
    if sha(run / "independent-audit.json") != plan["independent_audit_sha256"] or independent["status"] != "PASS" or independent["dataset_sha256"] != plan["original_dataset_sha256"]:
        raise ValueError("Independent audit changed or does not bind the original corpus")
    for name, expected in plan["sources"].items():
        if sha(ROOT / name) != expected or sha(run / "frozen-source" / name) != expected:
            raise ValueError("Frozen source changed: " + name)
    cases = read(run / "dataset.json")["cases"]
    for case in cases:
        body = request(plan, case)
        if digest(body) != plan["requests"][case["id"]] or read(run / "frozen-requests" / (case["id"] + ".json")) != body:
            raise ValueError("Rendered request differs from freeze")
    return plan, cases


def validate_response(value, plan):
    accepted = {plan["config"]["model"], plan["model"].get("canonical_slug")}
    if value.get("model") not in accepted or value.get("provider") != plan["config"]["provider"]:
        raise ValueError("Response model or provider differs from frozen endpoint")
    choices = value.get("choices", [])
    if len(choices) != 1 or not isinstance(choices[0].get("message"), dict):
        raise ValueError("Missing single assistant completion")
    usage = value.get("usage", {})
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if type(usage.get(key)) is not int or usage[key] < 0:
            raise ValueError("Missing nonnegative integer token usage")
    if usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
        raise ValueError("Inconsistent token usage")
    if type(usage.get("cost")) not in (int, float) or not math.isfinite(usage["cost"]) or usage["cost"] < 0:
        raise ValueError("Missing finite response cost")
    return choices[0], usage


def has_reasoning(value):
    message = value["choices"][0]["message"]
    return bool(message.get("reasoning") or message.get("reasoning_content") or message.get("reasoning_details")
                or value["usage"].get("completion_tokens_details", {}).get("reasoning_tokens", 0))


class Client:
    """Reserve every attempt, account unknown billing, and preserve native bytes."""
    def __init__(self, run, plan):
        self.run, self.plan, self.key = run, plan, load_key()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.reserved = 0.0
        self.spent = sum(read(p)["usage"]["cost"] for p in (run / "responses").glob("*.json")
                         if "usage" in read(p) and "cost" in read(p)["usage"])
        self.unknown_bound = 0.0
        for begin in (run / "attempts").glob("*/*.begin.json"):
            end = begin.with_name(begin.name.replace(".begin.json", ".end.json"))
            # A complete response saved just before interruption still accounts
            # actual billing. An unidentified/malformed response remains unknown.
            saved = run / "responses" / (begin.parent.name + ".json")
            completed = end.exists() and read(end).get("status") == "complete"
            if not completed:
                latest = max(begin.parent.glob("*.begin.json"), key=lambda p: int(p.name.split(".")[0]))
                if saved.exists() and begin == latest:
                    try:
                        validate_response(read(saved), plan)
                        continue
                    except ValueError:
                        pass
                self.unknown_bound += read(begin)["cost_reservation_usd"]

    def reserve(self, body):
        prices = self.plan["endpoint"]["pricing"]
        # UTF-8 bytes upper-bound ordinary byte-level tokenization; include
        # message framing overhead and the complete output cap conservatively.
        amount = ((len(canonical(body).encode()) + 1024) * float(prices["prompt"])
                  + body["max_tokens"] * float(prices["completion"])
                  + float(prices.get("request", 0)))
        with self.lock:
            if self.spent + self.unknown_bound + self.reserved + amount > self.plan["total_budget_usd"]:
                raise RuntimeError("Combined DEV/TEST budget reservation reached; no further call submitted")
            self.reserved += amount
        return amount

    def call(self, name, body):
        request_path = self.run / "requests" / (name + ".json")
        response_path = self.run / "responses" / (name + ".json")
        if request_path.exists():
            if read(request_path) != body:
                raise ValueError("Resume request differs from saved bytes")
        else:
            write(request_path, body)
        if response_path.exists():
            value = read(response_path)
            validate_response(value, self.plan)
            return value
        directory = self.run / "attempts" / name
        directory.mkdir(parents=True, exist_ok=True)
        previous = sorted(directory.glob("*.begin.json"))
        if previous and not previous[-1].with_name(previous[-1].name.replace(".begin.json", ".end.json")).exists():
            raise RuntimeError("Interrupted attempt has unknown outcome; inspect receipts before resending")
        for attempt in range(len(previous), 1 + self.plan["transport_retries"]):
            if self.stop.is_set():
                raise RuntimeError("Run halted after an earlier transport failure")
            amount = self.reserve(body)
            prefix = directory / str(attempt)
            started = time.monotonic()
            write(prefix.with_suffix(".begin.json"), dict(at_utc=now(), request_sha256=digest(body),
                  cost_reservation_usd=amount))
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
                  data=canonical(body).encode(), headers={"Authorization": "Bearer " + self.key,
                  "Content-Type": "application/json", "X-OpenRouter-Cache": "false"})
            status = None
            retryable = False
            try:
                with urllib.request.urlopen(req, timeout=self.plan["timeout_seconds"]) as response:
                    raw = response.read()
                if self.key.encode() in raw:
                    raise RuntimeError("Credential appeared in response; unsafe response not saved")
                raw_path = self.run / "raw-responses" / (name + f"--{attempt}.body")
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                with raw_path.open("xb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                value = json.loads(raw)
                write(response_path, value)
                _, usage = validate_response(value, self.plan)
                status = dict(status="complete", seconds=time.monotonic() - started,
                              raw_response_sha256=sha(raw_path), response_sha256=sha(response_path),
                              reported_cost_usd=usage["cost"])
                with self.lock:
                    self.spent += usage["cost"]
                return value
            except urllib.error.HTTPError as error:
                detail = error.read().decode(errors="replace").replace(self.key, "[REDACTED]")
                status = dict(status="http-error", http_status=error.code, detail=detail, billing="unknown")
                retryable = error.code in (429, 502, 503, 504)
            except (urllib.error.URLError, TimeoutError, http.client.IncompleteRead, json.JSONDecodeError) as error:
                partial = getattr(error, "partial", b"")
                status = dict(status="lost-response", kind=type(error).__name__, billing="unknown",
                              partial=partial.decode(errors="replace").replace(self.key, "[REDACTED]") if isinstance(partial, bytes) else "")
                retryable = True
            except Exception as error:
                status = dict(status="validation-error", kind=type(error).__name__,
                              detail=str(error).replace(self.key, "[REDACTED]"), billing="unknown")
                self.stop.set()
                raise
            finally:
                if status is not None:
                    write(prefix.with_suffix(".end.json"), status)
                with self.lock:
                    self.reserved -= amount
                    if status is None or status["status"] != "complete":
                        self.unknown_bound += amount
            if not retryable:
                self.stop.set()
                raise RuntimeError("Nontransient transport failure; exact receipts preserved")
            if attempt < self.plan["transport_retries"]:
                time.sleep(2 * (attempt + 1))
        self.stop.set()
        raise RuntimeError("Transport retry allowance exhausted; receipts preserved")


def execute(run, split):
    with (run / ".execution.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another process already owns this model run") from None
        return execute_locked(run, split)


def execute_locked(run, split):
    plan, cases = validate(run)
    if split == "test":
        dev = read(run / "dev-completion.json")
        if dev["status"] != "COMPLETE" or not dev["native_reasoning_observed"]:
            raise ValueError("TEST requires completed DEV with observed native thinking")
    completion_path = run / (split + "-completion.json")
    if completion_path.exists():
        emit(event="already_complete", split=split, completion=read(completion_path))
        return
    selected = [c for c in cases if c["split"] == split and (split == "test" or c["id"] in plan["dev_call_ids"])]
    client = Client(run, plan)
    started = time.monotonic()

    def worker(case):
        name = case["id"]
        path = run / "judgments" / (name + ".json")
        if path.exists():
            return read(path)
        body = read(run / "frozen-requests" / (name + ".json"))
        value = client.call(name, body)
        choice, usage = validate_response(value, plan)
        raw = choice["message"].get("content")
        parsed = study().parse(raw, allow_fence=True)
        row = dict(id=name, split=split, condition=case["condition"], unit_id=case["unit_id"],
                   request_sha256=digest(body), response_sha256=sha(run / "responses" / (name + ".json")),
                   raw_response=raw, finish_reason=choice.get("finish_reason"), usage=usage,
                   native_reasoning_observed=has_reasoning(value), parsed=parsed)
        write(path, row)
        return row

    rows = []
    with ThreadPoolExecutor(max_workers=plan["workers"]) as pool:
        futures = [pool.submit(worker, case) for case in selected]
        for completed, future in enumerate(as_completed(futures), 1):
            rows.append(future.result())
            emit(event="epistemic_progress", model=plan["alias"], split=split, done=completed,
                 total=len(selected), seconds=round(time.monotonic() - started, 1),
                 reported_cost_usd=round(client.spent, 6), unknown_cost_upper_bound_usd=client.unknown_bound)
    write(completion_path, dict(status="COMPLETE", cases=len(selected), split=split,
          native_reasoning_observed=sum(r["native_reasoning_observed"] for r in rows),
          seconds=time.monotonic() - started, plan_sha256=sha(run / "execution-plan.json")))


def audit(run):
    plan, cases = validate(run)
    rows = []
    for case in cases:
        path = run / "judgments" / (case["id"] + ".json")
        if not path.exists():
            continue
        reference_check(case)
        row = read(path)
        body = request(plan, case)
        response_path = run / "responses" / (case["id"] + ".json")
        value = read(response_path)
        choice, usage = validate_response(value, plan)
        if read(run / "requests" / (case["id"] + ".json")) != body or digest(body) != row["request_sha256"]:
            raise ValueError("Exact request audit failed")
        if sha(response_path) != row["response_sha256"] or usage != row["usage"]:
            raise ValueError("Response hash or usage audit failed")
        if row["raw_response"] != choice["message"].get("content") or row["parsed"] != study().parse(row["raw_response"], allow_fence=True):
            raise ValueError("Final-content parsing audit failed")
        if row["native_reasoning_observed"] != has_reasoning(value):
            raise ValueError("Reasoning delivery audit failed")
        if (row["id"], row["split"], row["condition"], row["unit_id"]) != (case["id"], case["split"], case["condition"], case["unit_id"]):
            raise ValueError("Judgment corpus identity mismatch")
        completed = []
        begins = list((run / "attempts" / case["id"]).glob("*.begin.json"))
        if len(begins) > 1 + plan["transport_retries"]:
            raise ValueError("Transport retry count exceeds frozen allowance")
        for begin in begins:
            if read(begin)["request_sha256"] != digest(body):
                raise ValueError("Transport retry did not submit the identical frozen request")
        for end in (run / "attempts" / case["id"]).glob("*.end.json"):
            receipt = read(end)
            if receipt["status"] == "complete":
                raw_path = run / "raw-responses" / (case["id"] + "--" + end.name.split(".")[0] + ".body")
                if sha(raw_path) != receipt["raw_response_sha256"] or json.loads(raw_path.read_bytes()) != value:
                    raise ValueError("Native raw response audit failed")
                completed.append(receipt)
        if len(completed) != 1:
            raise ValueError("Expected exactly one complete transport receipt")
        rows.append(row)
    if len(rows) != len(list((run / "judgments").glob("*.json"))):
        raise ValueError("Unexpected judgment outside frozen corpus")
    return plan, cases, rows


def report(run):
    plan, cases, rows = audit(run)
    by_id = {c["id"]: c for c in cases}
    summary = dict(model=plan["config"]["model"], alias=plan["alias"],
                   audit=dict(status="PASS", audited_judgments=len(rows), plan_sha256=sha(run / "execution-plan.json")),
                   planned_calls=plan["planned_calls"], splits={})
    for split in ("dev", "test"):
        selected = [r for r in rows if r["split"] == split]
        summary["splits"][split] = score(selected, by_id)
    attempts = list((run / "attempts").glob("*/*.begin.json"))
    failed = [p for p in attempts if not p.with_name(p.name.replace(".begin.json", ".end.json")).exists()
              or read(p.with_name(p.name.replace(".begin.json", ".end.json")))["status"] != "complete"]
    saved = [read(p) for p in (run / "responses").glob("*.json")]
    metered = [r for r in saved if type(r.get("usage", {}).get("cost")) in (int, float)
               and math.isfinite(r["usage"]["cost"]) and r["usage"]["cost"] >= 0]
    summary["usage"] = dict(saved_calls=len(saved), scored_calls=len(rows),
                            unscored_saved_responses=len(saved) - len(rows),
                            input_tokens=sum(r["usage"].get("prompt_tokens", 0) for r in metered),
                            output_tokens=sum(r["usage"].get("completion_tokens", 0) for r in metered),
                            reported_reasoning_tokens=sum(r["usage"].get("completion_tokens_details", {}).get("reasoning_tokens", 0) for r in metered),
                            native_reasoning_observed=sum(r["native_reasoning_observed"] for r in rows),
                            reported_cost_usd=sum(r["usage"]["cost"] for r in metered),
                            attempts=len(attempts), attempts_with_unknown_billing=len(failed),
                            unknown_cost_upper_bound_usd=sum(read(p)["cost_reservation_usd"] for p in failed))
    # Immutable snapshots make partial and complete reports separately reviewable.
    target = run / ("summary-" + str(len(rows)) + ".json")
    if target.exists():
        if read(target) != summary:
            raise ValueError("Existing summary differs")
    else:
        write(target, summary)
    emit(event="report", summary=str(target), **summary)
    return summary


def score(rows, by_id):
    conditions = sorted({by_id[r["id"]]["condition"] for r in rows})
    answer = lambda r: r["parsed"].get("answer")
    exact = lambda r: answer(r) == by_id[r["id"]]["reference"]
    fields = tuple(study().FIELDS)

    def subset(selected):
        matrix = {ref: {pred: 0 for pred in ("allow", "deny", "undetermined", "malformed")}
                  for ref in ("allow", "deny", "undetermined")}
        for row in selected:
            pred = answer(row)
            matrix[by_id[row["id"]]["reference"]["decision"]][pred["decision"] if pred else "malformed"] += 1
        reference_counts = {key: sum(value.values()) for key, value in matrix.items()}
        tp = fp = fn = exact_sources = 0
        for row in selected:
            expected = set(by_id[row["id"]]["reference"].get("admitted_report_ids", []))
            actual = set(answer(row).get("admitted_report_ids", [])) if answer(row) else set()
            tp += len(expected & actual)
            fp += len(actual - expected)
            fn += len(expected - actual)
            exact_sources += answer(row) is not None and actual == expected
        return dict(completed=len(selected), all_fields_correct=sum(exact(r) for r in selected),
                    parse_errors=sum(r["parsed"].get("parse_error") is not None for r in selected),
                    decision_matrix=matrix, reference_counts=reference_counts,
                    correct_decisions=sum(matrix[key][key] for key in matrix),
                    wrongly_allowed=matrix["deny"]["allow"] + matrix["undetermined"]["allow"],
                    wrongly_allowed_on_deny=matrix["deny"]["allow"],
                    deny_denominator=reference_counts["deny"],
                    not_allowed_denominator=reference_counts["deny"] + reference_counts["undetermined"],
                    unwarranted_allow_on_undetermined=matrix["undetermined"]["allow"],
                    undetermined_denominator=reference_counts["undetermined"],
                    wrongly_denied_allowed=matrix["allow"]["deny"],
                    unsupported_deny_on_undetermined=matrix["undetermined"]["deny"],
                    correct_abstentions=matrix["undetermined"]["undetermined"],
                    unnecessary_abstentions=matrix["allow"]["undetermined"] + matrix["deny"]["undetermined"],
                    source_selection=dict(micro_tp=tp, micro_fp=fp, micro_fn=fn,
                        exact=exact_sources, cases=len(selected),
                        micro_precision=tp / (tp + fp) if tp + fp else None,
                        micro_recall=tp / (tp + fn) if tp + fn else None),
                    fields_correct={key: sum(answer(r) is not None and answer(r).get(key) == by_id[r["id"]]["reference"].get(key) for r in selected) for key in fields})

    return dict(**subset(rows), by_condition={condition: subset([r for r in rows if r["condition"] == condition])
                                             for condition in conditions})


def archive(run, destination):
    with (run / ".execution.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Cannot archive while this model is still writing receipts") from None
        return archive_locked(run, destination)


def archive_locked(run, destination):
    summary = report(run)
    if destination.exists():
        raise ValueError("Archive destination already exists")
    key = load_key().encode()
    files = []
    for source in sorted(run.rglob("*")):
        if not source.is_file() or source.name == ".execution.lock":
            continue
        raw = source.read_bytes()
        if key in raw or source.name == ".env" or source.suffix == ".pyc":
            raise ValueError("Unexpected sensitive or runtime file in receipts")
        relative = source.relative_to(run)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        files.append(dict(path=str(relative), bytes=len(raw), sha256=sha(target)))
    write(destination / "manifest.json", dict(scope="Private epistemic-source experiment; raw requests and responses; no credentials",
          files=files, source_run=str(run), plan_sha256=summary["audit"]["plan_sha256"]))
    emit(event="archived", destination=str(destination), files=len(files))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "dev", "run", "report", "archive"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--model", choices=CONFIGS)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    if args.command == "prepare":
        if args.model is None or args.dataset is None or args.audit is None or not 1 <= args.workers <= 4:
            parser.error("prepare requires --model, --dataset, --audit and 1–4 workers")
        prepare(run, args.model, args.dataset, args.audit, args.source, args.workers)
    elif args.command == "dev":
        execute(run, "dev")
    elif args.command == "run":
        execute(run, "test")
    elif args.command == "report":
        report(run)
    elif args.command == "archive":
        if args.destination is None:
            parser.error("archive requires --destination")
        archive(run, args.destination.resolve())


if __name__ == "__main__":
    main()
