"""Independent reference checks for the frozen epistemic source corpus."""
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import pytest
from internal.scripts import audit_ontology_epistemic_sources as audit

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'internal/research/ontology-epistemic-sources-dataset-2026-10-15.json'


@pytest.fixture(scope='module')
def corpus():
    return json.loads(DATASET.read_text())


def test_complete_dataset_independent_reference_and_hidden_semantics(corpus):
    result = audit.audit_dataset(corpus, project_root=ROOT)
    assert result['status'] == 'PASS'
    assert result['cases'] == 432 and result['units'] == 27
    assert result['decisions']['test'] == {'allow': 48, 'deny': 104, 'undetermined': 232}
    for receipt in result['case_receipts']:
        answer = receipt['independent_reference']
        if answer['decision'] == 'undetermined' and answer['evidence_integrity'] == 'consistent':
            assert set(receipt['compatible_release_witnesses']) == {'true', 'false'}


def test_all_units_excluded_from_prior_archived_fingerprints(corpus):
    result = audit.check_exclusions(corpus, ROOT)
    assert result['datasets'] > 0 and result['structural_fingerprints'] > 0
    changed = deepcopy(corpus)
    old = json.loads((ROOT / corpus['exclusion_datasets'][0]['path']).read_text())
    queue = [old]
    while queue:
        obj = queue.pop()
        if isinstance(obj, dict):
            if 'structural_fingerprint' in obj:
                changed['units'][0]['structural_fingerprint'] = obj['structural_fingerprint']
                break
            queue.extend(obj.values())
        elif isinstance(obj, list):
            queue.extend(obj)
    else:
        raise AssertionError('first archived dataset has no unit fingerprint')
    with pytest.raises(AssertionError):
        audit.check_exclusions(changed, ROOT)


def test_tampered_reference_rejected(corpus):
    changed = deepcopy(corpus)
    changed['cases'][0]['reference']['decision'] = 'tampered'
    with pytest.raises(AssertionError, match='reference disagreement'):
        audit.audit_dataset(changed, project_root=ROOT)


def test_semantic_tamper_rejected_even_if_reference_is_recomputed(corpus):
    changed = deepcopy(corpus)
    case = next(c for c in changed['cases'] if c['condition'] == 'complete-direct')
    claim = next(x for x in case['input']['reports'][0]['claims'] if x['atom'].startswith('g:'))
    claim['value'] = not claim['value']
    case['reference'] = audit.independently_review(case['input'])[0]
    with pytest.raises(AssertionError, match='admissible semantic lie'):
        audit.audit_dataset(changed, project_root=ROOT)


def test_candidate_graph_must_be_result_of_the_proposed_edit(corpus):
    changed = deepcopy(corpus['units'][0])
    changed['candidate'] = deepcopy(changed['contract']['base'])
    with pytest.raises(AssertionError, match='candidate does not implement'):
        audit.check_candidate(changed)


@pytest.mark.parametrize('mutation', ['integer_claim', 'string_verified', 'boolean_budget', 'unknown_kind'])
def test_generated_packet_type_errors_rejected(corpus, mutation):
    case = deepcopy(next(c for c in corpus['cases'] if c['condition'] == 'complete-direct'))
    p = case['input']
    if mutation == 'integer_claim':
        p['reports'][0]['claims'][0]['value'] = 1
    elif mutation == 'string_verified':
        p['reports'][0]['signature_verified'] = 'true'
    elif mutation == 'boolean_budget':
        p['grants'][0]['remaining_depth'] = True
    else:
        p['grants'][0]['kinds'] = ['approvals']
    with pytest.raises(AssertionError):
        audit.independently_review(p)


def test_constructive_worlds_match_every_small_atomic_completion():
    packet = {'goal_ids': ['0', '1'], 'profile_ids': ['0']}
    atoms = sorted(audit.atom_inventory(packet))
    for values in product((None, False, True), repeat=len(atoms)):
        known = {a: v for a, v in zip(atoms, values) if v is not None}
        unknown = [a for a in atoms if a not in known]
        exact = {tuple(audit.formula(packet, dict(known, **dict(zip(unknown, xs)))).values())
                 for xs in product((False, True), repeat=len(unknown))}
        got = {tuple(w['fields'].values()) for w in audit.completion_witnesses(packet, known)}
        assert got == exact
