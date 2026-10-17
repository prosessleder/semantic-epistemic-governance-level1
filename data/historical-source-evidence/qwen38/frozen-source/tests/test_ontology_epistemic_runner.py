"""Transport and accounting checks for the separate epistemic-source study."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import io
import json
import urllib.error

import pytest

from internal.scripts import run_ontology_epistemic_sources as runner


def plan(alias="qwen38", budget=8):
    config = deepcopy(runner.CONFIGS[alias])
    return dict(config=config, model=dict(canonical_slug=config["model"] + "-dated"),
                settings=runner.settings(config), total_budget_usd=budget,
                endpoint=dict(pricing=dict(prompt="0.000001", completion="0.000001")),
                transport_retries=2, timeout_seconds=600)


def response(p, cost=0.001):
    return dict(model=p["config"]["model"], provider=p["config"]["provider"],
                choices=[dict(message=dict(content='{"decision":"deny"}', reasoning="native thoughts"), finish_reason="stop")],
                usage=dict(prompt_tokens=10, completion_tokens=20, total_tokens=30, cost=cost))


def body(p):
    return dict(model=p["config"]["model"], messages=[dict(role="user", content="fixed prompt")], **p["settings"])


@pytest.mark.parametrize("alias", ["qwen38", "gemma31"])
def test_model_endpoint_and_thinking_match_prior_hosted_configuration(alias):
    from internal.scripts import run_ontology_hosted_three_check as prior
    config = runner.CONFIGS[alias]
    assert all(config[k] == prior.CONFIGS[alias][k] for k in config)
    assert runner.settings(config) == prior.settings(prior.CONFIGS[alias])


def test_request_only_uses_benchmark_messages_and_never_reference(monkeypatch):
    message = [dict(role="system", content="governance rules"), dict(role="user", content="public evidence")]
    monkeypatch.setattr(runner, "study", lambda: SimpleNamespace(request=lambda case: message))
    case = dict(input={}, reference="PRIVATE_REFERENCE", condition="PRIVATE_CONDITION", hidden="PRIVATE_ONTOLOGY")
    request = runner.request(plan(), case)
    assert request["messages"] == message
    assert "PRIVATE" not in runner.canonical(request)
    assert set(request) == {"model", "messages", "temperature", "max_tokens", "reasoning", "provider", "stream"}


def test_response_identity_and_finite_usage():
    p = plan()
    value = response(p)
    runner.validate_response(value, p)
    for key, replacement in [("provider", "Other"), ("model", "other/model")]:
        bad = deepcopy(value)
        bad[key] = replacement
        with pytest.raises(ValueError):
            runner.validate_response(bad, p)
    for key, replacement in [("cost", float("nan")), ("prompt_tokens", True), ("total_tokens", 99)]:
        bad = deepcopy(value)
        bad["usage"][key] = replacement
        with pytest.raises(ValueError):
            runner.validate_response(bad, p)


def test_exact_raw_response_is_saved_and_resume_does_not_resubmit(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "load_key", lambda: "test-secret")
    p = plan()
    raw = json.dumps(response(p), indent=3).encode()
    calls = []

    def send(req, timeout):
        calls.append(req.data)
        return io.BytesIO(raw)

    monkeypatch.setattr(runner.urllib.request, "urlopen", send)
    client = runner.Client(tmp_path, p)
    result = client.call("dev-case", body(p))
    assert result == json.loads(raw)
    assert (tmp_path / "raw-responses/dev-case--0.body").read_bytes() == raw
    assert client.call("dev-case", body(p)) == result
    assert len(calls) == 1
    assert calls[0] == runner.canonical(body(p)).encode()
    assert client.spent == 0.001
    assert client.unknown_bound == 0
    assert client.reserved == 0
    resumed = runner.Client(tmp_path, p)
    assert resumed.spent == 0.001
    assert resumed.unknown_bound == 0


def test_retry_is_identical_and_failed_attempt_conservatively_accounted(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "load_key", lambda: "test-secret")
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    p = plan()
    calls = []

    def send(req, timeout):
        calls.append(req.data)
        if len(calls) == 1:
            raise urllib.error.HTTPError("https://example.test", 429, "busy", {}, io.BytesIO(b"busy"))
        return io.BytesIO(runner.canonical(response(p)).encode())

    monkeypatch.setattr(runner.urllib.request, "urlopen", send)
    client = runner.Client(tmp_path, p)
    client.call("test-case", body(p))
    assert len(calls) == 2 and calls[0] == calls[1]
    assert client.unknown_bound > 0
    assert client.spent == 0.001
    assert runner.read(tmp_path / "attempts/test-case/0.end.json")["billing"] == "unknown"
    resumed = runner.Client(tmp_path, p)
    assert resumed.unknown_bound == client.unknown_bound
    assert resumed.spent == client.spent


def test_budget_covers_dev_test_and_every_transport_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "load_key", lambda: "test-secret")
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    p = plan(budget=0.015)
    calls = []

    def send(req, timeout):
        calls.append(req.data)
        raise urllib.error.HTTPError("https://example.test", 429, "busy", {}, io.BytesIO(b"busy"))

    monkeypatch.setattr(runner.urllib.request, "urlopen", send)
    client = runner.Client(tmp_path, p)
    with pytest.raises(RuntimeError, match="budget reservation"):
        client.call("dev-case", body(p))
    assert len(calls) == 1
    with pytest.raises(RuntimeError, match="budget reservation"):
        runner.Client(tmp_path, p).call("test-case", body(p))
    assert len(calls) == 1


def test_interrupted_request_is_not_silently_repeated(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "load_key", lambda: "test-secret")
    p = plan()
    runner.write(tmp_path / "requests/case.json", body(p))
    runner.write(tmp_path / "attempts/case/0.begin.json", dict(cost_reservation_usd=0.1))
    monkeypatch.setattr(runner.urllib.request, "urlopen", lambda *_args, **_kwargs: pytest.fail("must not send"))
    with pytest.raises(RuntimeError, match="unknown outcome"):
        runner.Client(tmp_path, p).call("case", body(p))


def test_decision_scoring_penalizes_both_overclaiming_and_refusing_everything(monkeypatch):
    monkeypatch.setattr(runner, "study", lambda: SimpleNamespace(FIELDS=("decision",)))
    cases = {str(i): dict(reference=dict(decision=d), condition="same")
             for i, d in enumerate(("allow", "deny", "undetermined"))}
    rows = [dict(id=str(i), condition="same", parsed=dict(answer=dict(decision="allow"), parse_error=None)) for i in range(3)]
    result = runner.score(rows, cases)
    assert result["all_fields_correct"] == 1
    assert result["wrongly_allowed"] == 2
    assert result["unwarranted_allow_on_undetermined"] == 1
    for row in rows:
        row["parsed"]["answer"]["decision"] = "undetermined"
    result = runner.score(rows, cases)
    assert result["wrongly_allowed"] == 0
    assert result["all_fields_correct"] == 1
    assert result["unnecessary_abstentions"] == 2


def test_native_thinking_is_observation_not_zero_subtotal_inference():
    value = response(plan())
    value["usage"]["completion_tokens_details"] = dict(reasoning_tokens=0)
    assert runner.has_reasoning(value)
    value["choices"][0]["message"].pop("reasoning")
    assert not runner.has_reasoning(value)


def test_source_selection_counts_wrong_extra_missing_and_exact(monkeypatch):
    monkeypatch.setattr(runner, "study", lambda: SimpleNamespace(FIELDS=("decision", "admitted_report_ids")))
    cases = {"x": dict(condition="source", reference=dict(decision="deny", admitted_report_ids=["a", "b"])),
             "y": dict(condition="source", reference=dict(decision="allow", admitted_report_ids=[]))}
    rows = [dict(id="x", condition="source", parsed=dict(parse_error=None,
                    answer=dict(decision="allow", admitted_report_ids=["b", "rogue"]))),
            dict(id="y", condition="source", parsed=dict(parse_error=None,
                    answer=dict(decision="allow", admitted_report_ids=[])))]
    scored = runner.score(rows, cases)
    assert scored["source_selection"] == dict(micro_tp=1, micro_fp=1, micro_fn=1,
        exact=1, cases=2, micro_precision=0.5, micro_recall=0.5)
    assert scored["wrongly_allowed_on_deny"] == 1
    assert scored["deny_denominator"] == 1
    assert scored["completed"] == 2


def test_prepare_requires_independent_pass_on_exact_dataset_before_network(tmp_path, monkeypatch):
    dataset = tmp_path / "data.json"
    audit = tmp_path / "audit.json"
    runner.write(dataset, dict(cases=[dict(id="a")]))
    runner.write(audit, dict(status="PASS", dataset_sha256="wrong", case_receipts=[]))
    monkeypatch.setattr(runner, "metadata", lambda *_: pytest.fail("no network before audit validation"))
    with pytest.raises(ValueError, match="exact dataset bytes"):
        runner.prepare(tmp_path / "run", "qwen38", dataset, audit)
