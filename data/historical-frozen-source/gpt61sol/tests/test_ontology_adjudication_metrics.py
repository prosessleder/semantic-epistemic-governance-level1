from internal.benchmarks import ontology_adjudication_metrics as metrics
from internal.benchmarks import ontology_adjudication as study


def row(truth,verdict,unit):
    return dict(truth={k:truth for k in study.FIELDS},verdict=verdict,unit_id=unit,scenario_id=unit)


def test_no_answer_does_not_count_as_correct_rejection():
    rs=[row(False,None,"forbidden"),row(True,None,"allowed")]
    release=metrics.release_metrics(rs);field=metrics.field_metrics(rs,"release_allowed")
    assert release["false_approvals"]==0 and release["operational_holds_on_allowed"]==1
    assert field["accuracy"]==0 and field["balanced_accuracy"]==0 and field["determinate"]==0


def test_always_reject_has_zero_false_approval_but_half_balanced_accuracy():
    verdict={k:False for k in study.FIELDS}
    rs=[row(False,verdict,"forbidden"),row(True,verdict,"allowed")]
    assert metrics.release_metrics(rs)["explicit_false_rejections"]==1
    assert metrics.field_metrics(rs,"release_allowed")["balanced_accuracy"]==.5


def test_explicit_false_approval_counts_even_if_components_disagree():
    verdict={k:False for k in study.FIELDS};verdict["release_allowed"]=True
    rs=[row(False,verdict,"forbidden")]
    result=metrics.release_metrics(rs)
    assert result["false_approvals"]==1 and result["false_approval_rate"]==1
    assert result["units_with_false_approval"]==1
