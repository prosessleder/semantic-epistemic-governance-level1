import pytest
from internal.benchmarks import ontology_openrouter as api
from internal.benchmarks import ontology_rigorous_proposals as cases


@pytest.mark.parametrize("text", ['```json\n{"op":"abstain"}\n```', 'Draft: {"op":"abstain"}',
    '{"op":"abstain","op":"add_edge"}', '{"op":"abstain"} extra', '{"op":NaN}', None])
def test_drafts_ambiguous_and_unfinished_outputs_fail(text):
    assert api.parse("baseline", text)["proposal"] is None


def test_reader_requires_complete_envelope_and_ignores_reasoning():
    assert api.parse("baseline", ' {"op":"abstain"}\n')["proposal"] == {"op":"abstain"}
    raw='{"explanation":"Cannot seed empty facts","proposal":{"op":"abstain"}}'
    assert api.parse("assisted",raw)["proposal"] == {"op":"abstain"}
    assert api.parse("assisted",'{"op":"abstain"}')["proposal"] is None


def test_request_preserves_feedback_and_hides_reference():
    task=cases.instance("mission-chain","dev",0)
    body=api.request(task,"assisted",[])
    text=str(body["messages"])
    assert "Computed states BEFORE" in text
    assert "reference_patch" not in text and task["task_id"] not in text and task["family"] not in text
    assert body["reasoning"]["effort"]=="low" and body["provider"]["only"]==["z-ai/fp8"]
    assert body["provider"]["allow_fallbacks"] is False
    with pytest.raises(ValueError):api.request(task,"baseline",[{}])


def test_model_switch_and_missing_usage_fail():
    value=dict(model=api.MODEL,provider=api.PROVIDER,choices=[dict(message=dict(content='{"op":"abstain"}'))],
        usage=dict(prompt_tokens=1,completion_tokens=2,total_tokens=3,cost=.001))
    api.validate_response(value)
    with pytest.raises(ValueError):api.validate_response(dict(value,provider="Other"))
    with pytest.raises(ValueError):api.validate_response(dict(value,model="Another"))
    with pytest.raises(ValueError):api.validate_response(dict(value,usage={}))
