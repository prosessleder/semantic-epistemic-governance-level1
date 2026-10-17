"""Meaningful transport rejection and task-preservation checks for new models."""
import pytest
from internal.scripts.run_ontology_modern_models import final_frame, jobs, strip_terminal_ids, checkpoint_artifacts
from internal.benchmarks.ontology_checked_proposals import tasks
from ontology_boundary.checked_release import first_proposal_object


def test_qwen_requires_complete_reasoning_boundary():
    with pytest.raises(ValueError):
        final_frame("qwen35", "reasoned", 'thought: {"op":"abstain"}')
    frame = final_frame("qwen35", "reasoned", 'bad draft {"op":"evil"}</think>\n{"op":"abstain"}')
    assert first_proposal_object(frame)[0] == {"op": "abstain"}


def test_gemma_ignores_only_complete_native_thought_channel():
    raw = '<|channel>thought\n{"op":"evil"}\n<channel|>\n{"op":"abstain"}'
    assert first_proposal_object(final_frame("gemma4", "reasoned", raw))[0] == {"op": "abstain"}
    with pytest.raises(ValueError):
        final_frame("gemma4", "reasoned", '<|channel>thought\n{"op":"abstain"}')


def test_prose_and_duplicate_keys_are_not_repaired():
    with pytest.raises(ValueError):
        final_frame("gemma4", "reasoned", 'Here is the answer: {"op":"abstain"}')
    with pytest.raises(ValueError):
        first_proposal_object(final_frame("qwen35", "reasoned", '</think>{"op":"abstain","op":"add_edge"}'))


def test_only_terminal_special_tokens_are_removed():
    assert strip_terminal_ids([10, 20, 30, 20], {20}) == [10, 20, 30]


def test_task_and_control_inventory_preserves_all_cases():
    source = tasks()
    planned = jobs(source)
    assert len(planned) == 96 and len({j["job_id"] for j in planned}) == 96
    for arm in ("direct", "reasoned"):
        assert [j["task"] for j in planned if j["kind"] == "proposal" and j["arm"] == arm] == source
    controls = [j for j in planned if j["kind"] == "control"]
    assert len(controls) == 32
    assert sum(j["expected"] for j in controls if j["query"] == "derived") == 8
    assert sum(j["expected"] for j in controls if j["query"] == "effective") == 7


def test_checkpoint_verification_rejects_missing_indexed_shard(tmp_path):
    (tmp_path / "present.safetensors").write_bytes(b"example")
    (tmp_path / "model.safetensors.index.json").write_text(
        '{"weight_map":{"p":"present.safetensors","q":"missing.safetensors"}}')
    with pytest.raises(ValueError, match="incomplete pinned checkpoint"):
        checkpoint_artifacts(tmp_path)
