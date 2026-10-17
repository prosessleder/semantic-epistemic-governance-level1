"""Gemma proposes every edit; deterministic execution supplies diagnostic feedback.

No candidate enumeration, reference patch, task family, or expected answer is
provided to the proposer. The response explanation has no release authority.
"""
from ontology_boundary.checked_release import ReviewContract, apply_proposal, first_proposal_object
from ontology_boundary.oracle import closure
from internal.benchmarks import ontology_rigorous_proposals as cases

PREFIX = '{"explanation":'


def parse(raw):
    try:
        envelope, trailing = first_proposal_object(PREFIX + raw)
        cases.canonical(envelope)
        if set(envelope) != {"explanation", "proposal"}:
            raise ValueError("response needs exactly explanation and proposal")
        if not isinstance(envelope["explanation"], str) or type(envelope["proposal"]) is not dict:
            raise ValueError("explanation must be text and proposal must be an object")
        if trailing.strip():
            raise ValueError("extra content after response object")
        return dict(envelope=envelope, proposal=envelope["proposal"], parse_error=None,
                    complete_frame=cases.canonical(envelope["proposal"]), trailing_text=trailing)
    except (ValueError, TypeError) as error:
        return dict(envelope=None, proposal=None, parse_error=str(error), complete_frame=None, trailing_text=None)


def goal_states(contract, ontology):
    results = []
    for goal in contract.goals:
        state = closure(ontology, goal.profile)
        atoms = state.class_types if goal.kind == "class" else (
            state.permissions if goal.kind == "effective" else state.derived_permissions)
        actual = goal.target in atoms
        results.append(dict(goal=goal.to_dict(), actual=actual, passed=actual == goal.expected,
                            derived_classes=sorted(state.class_types), derived_permissions=sorted(state.derived_permissions),
                            effective_permissions=sorted(state.permissions), inconsistent_pairs=[list(p) for p in state.inconsistencies]))
    return results


def diagnostic(contract, proposal):
    try:
        candidate = apply_proposal(contract, proposal)
    except (ValueError, TypeError) as error:
        return dict(status="invalid-edit", error=str(error))
    if candidate is None:
        return dict(status="abstained")
    states = goal_states(contract, candidate)
    return dict(status="goals-met" if all(x["passed"] for x in states) else "goals-failed", goal_states=states)


def messages(task, attempts):
    contract = ReviewContract.from_dict(task["contract"])
    result = cases.messages(task)
    result[0]["content"] += (
        " Explain your proposed edit briefly, checking all supplied positive and negative goals. "
        "Computed execution facts are diagnostic data; only the independent release checker can authorize a change.")
    result[-1]["content"] = result[-1]["content"].replace(
        "Return one proposal JSON object only, without prose or extra fields.",
        'Return exactly one JSON response {"explanation":"brief explanation, at most 100 words",'
        '"proposal":{one allowed edit or abstain}}. Do not include fences or text outside that response.')
    result[-1]["content"] += (
        "\nProcedure: identify which existing classifications both requested groups share; "
        "check all goals, including expected-false goals. If an effective permission is absent because "
        "the profile is inconsistent, adding another path will not repair the conflict. Permission heads "
        "are NOT legal edit endpoints. Public seed vocabulary lists allowable input types, not facts "
        "present in every profile. An empty profile stays empty under all allowed edits because every "
        "implication needs at least one premise; abstain if an empty profile must gain a class. "
        "A proposed permission expansion can be valid but needs independent approval.\n"
        "Computed states BEFORE any edit:\n" + cases.canonical(goal_states(contract, contract.base)))
    if attempts:
        history = [dict(proposal=a["proposal"], parse_error=a["parse_error"], diagnostic=a["diagnostic"]) for a in attempts]
        result[-1]["content"] += (
            "\nPrevious attempts and their computed execution results:\n" + cases.canonical(history)
            + "\nRevise the proposal against the ORIGINAL ontology. The edits above were not committed. "
            "Return a different single edit correcting the reported failures; all goals must pass. "
            "Do not combine earlier edits or claim release approval.")
    return result


def encode(tok, task, attempts):
    msgs = messages(task, attempts)
    text = tok.apply_chat_template(msgs + [{"role": "assistant", "content": PREFIX}],
        tokenize=False, continue_final_message=True, enable_thinking=False)
    ids = tok.encode(text, add_special_tokens=False)
    native = tok.apply_chat_template(msgs + [{"role": "assistant", "content": PREFIX}],
        tokenize=True, continue_final_message=True, enable_thinking=False, return_dict=False)
    assert native == ids and msgs[0]["content"] in text
    assert len(ids) <= 8192, "context overflow; never truncate"
    return text, ids
