from ontology_boundary.checked_release import ReviewContract
from internal.benchmarks import ontology_rigorous_proposals as cases
from internal.benchmarks import ontology_gemma_feedback as feedback
from internal.benchmarks.ontology_goal_feedback_text import render_states, render_attempts


def test_rule_feedback_names_unavailable_premise_for_the_other_cohort():
    task = cases.instance("strict-conjunction", "dev", 0)
    contract = ReviewContract.from_dict(task["contract"])
    proposal = dict(op="add_rule", antecedents=["P1", "P2"], head=contract.goals[0].target)
    diagnostic = feedback.diagnostic(contract, proposal)
    text = render_states(diagnostic["goal_states"], proposal)
    assert "CANNOT activate" in text and "P1 is absent" in text
    assert "Supplied facts {P2, P3}" in text and "computed value is False" in text
    assert "reference" not in text and "add_rule" not in text


def test_unproven_abstention_feedback_does_not_propose_a_replacement():
    task = cases.instance("strict-conjunction", "dev", 0)
    c = ReviewContract.from_dict(task["contract"])
    text = render_attempts([dict(proposal={"op":"abstain"}, parse_error=None,
        diagnostic=feedback.diagnostic(c,{"op":"abstain"}))])
    assert "NO certified obstruction" in text and "is allowed" in text
    assert "head" not in text and "antecedents" not in text


def test_diagnostic_text_is_invariant_to_proposal_dictionary_insertion_order():
    task=cases.instance("mission-chain","dev",0)
    c=ReviewContract.from_dict(task["contract"])
    target=next(a for a,b in c.base.subclass if b==c.goals[0].target)
    a=dict(op="add_edge",left="P1",right=target)
    b=dict(right=target,left="P1",op="add_edge")
    diagnostic=feedback.diagnostic(c,a)
    def item(proposal):return dict(proposal=proposal,parse_error=None,diagnostic=diagnostic)
    assert render_attempts([item(a)])==render_attempts([item(b)])
