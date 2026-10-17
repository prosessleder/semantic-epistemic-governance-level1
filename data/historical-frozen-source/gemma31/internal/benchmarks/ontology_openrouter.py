"""OpenRouter transport and strict final-content reader; no model judgment here."""
import json
from pathlib import Path
from ontology_boundary.checked_release import first_proposal_object
from internal.benchmarks import ontology_gemma_feedback as feedback
from internal.benchmarks import ontology_rigorous_proposals as cases

MODEL = "z-ai/glm-5.3-flash"
PROVIDER = "Z.AI"
SETTINGS = dict(temperature=0, max_tokens=4096, reasoning=dict(effort="low", exclude=False),
    provider=dict(only=["z-ai/fp8"], allow_fallbacks=False, require_parameters=True), stream=False)


def load_key(path):
    values = [x.split("=", 1)[1].strip().strip('"\'') for x in Path(path).read_text().splitlines()
              if x.startswith("OPENROUTER_API_KEY=")]
    if len(values) != 1 or not values[0]:
        raise ValueError("Need one OPENROUTER_API_KEY in the local ignored env file")
    return values[0]


def request(task, arm, attempts):
    if arm not in ("baseline", "assisted"):
        raise ValueError("unknown arm")
    if arm == "baseline" and attempts:
        raise ValueError("baseline has one attempt")
    msgs = cases.messages(task) if arm == "baseline" else feedback.messages(task, attempts)
    # Hosted chat APIs receive complete messages, without local token-template
    # bytes or an unfinished assistant prefix. All semantic instructions match.
    return dict(model=MODEL, messages=msgs, **SETTINGS)


def parse(arm, content):
    try:
        if not isinstance(content, str):
            raise ValueError("no final content")
        obj, trailing = first_proposal_object(content.strip())
        cases.canonical(obj)  # reject NaN/Infinity, duplicate keys are rejected above
        if trailing.strip():
            raise ValueError("extra text after response object")
        if arm == "assisted":
            if set(obj) != {"explanation", "proposal"} or not isinstance(obj["explanation"], str) or type(obj["proposal"]) is not dict:
                raise ValueError("response needs explanation text and one proposal object")
            proposal, envelope = obj["proposal"], obj
        elif arm == "baseline":
            proposal, envelope = obj, None
        else:
            raise ValueError("unknown arm")
        return dict(proposal=proposal, envelope=envelope, parse_error=None,
            complete_frame=cases.canonical(proposal), trailing_text=trailing)
    except (ValueError, TypeError) as error:
        return dict(proposal=None, envelope=None, parse_error=str(error), complete_frame=None, trailing_text=None)


def validate_response(value):
    if value.get("model") not in (MODEL, "z-ai/glm-5.3-flash-20260826") or value.get("provider") != PROVIDER:
        raise ValueError("provider or model differs from frozen configuration")
    choices = value.get("choices", [])
    if len(choices) != 1 or not isinstance(choices[0].get("message"), dict):
        raise ValueError("missing single completion")
    usage = value.get("usage", {})
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if type(usage.get(key)) is not int or usage[key] < 0:
            raise ValueError("missing API token usage")
    if usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
        raise ValueError("API token total mismatch")
    if not isinstance(usage.get("cost"), (int, float)) or usage["cost"] < 0:
        raise ValueError("missing API cost")
    return choices[0], usage
