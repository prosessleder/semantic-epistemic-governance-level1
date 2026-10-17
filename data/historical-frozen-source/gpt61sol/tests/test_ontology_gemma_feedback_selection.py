from internal.benchmarks import ontology_rigorous_proposals as cases
from internal.scripts.run_ontology_gemma_feedback import fresh_tasks


def test_fresh_feedback_holdout_excludes_prior_structures_and_semantic_tables():
    old = cases.dataset()
    fresh = fresh_tasks(old, n=2)
    previous = old["dev"] + old["test"]
    assert len(fresh) == 24
    for field in ("structural_fingerprint", "semantic_fingerprint"):
        assert len({t[field] for t in fresh}) == 24
        assert not {t[field] for t in fresh} & {t[field] for t in previous}
    assert all(sum(t["family"] == f for t in fresh) == 2 for f in cases.FAMILIES)
