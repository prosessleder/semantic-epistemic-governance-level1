#!/usr/bin/env python3
"""Independent source-policy and hidden-ontology audit; no benchmark imports.

Authority uses explicit rooted path enumeration, ontology consequences use an
agenda, and warrant uses constructive Boolean completions. This audit verifies
the declared synthetic contract; it does not authenticate real-world sources.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict, deque
from copy import deepcopy
import hashlib
from itertools import combinations, product
import json
from pathlib import Path

FIELDS = ('goal_correct', 'protected_expansion', 'approval_matches',
          'permission_authorized', 'release_allowed')
KINDS = ('goal', 'profile', 'approval')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def kind_of(atom):
    return {'g': 'goal', 'b': 'profile', 'n': 'profile', 'a': 'approval'}[atom.partition(':')[0]]


def atom_inventory(packet):
    return {'g:' + x for x in packet['goal_ids']} | {
        prefix + ':' + x for x in packet['profile_ids'] for prefix in ('b', 'n')
    } | {'a:match'}


def authentic_current(obj, packet):
    return (obj['signature_verified'] is True and obj['revoked'] is False
            and obj['binding'] == packet['current_binding'])


def path_authority(packet):
    """Enumerate bounded rooted grant paths, retaining kind with each budget."""
    paths = {}
    outgoing = defaultdict(list)
    for i, grant in enumerate(packet['grants']):
        if authentic_current(grant, packet):
            outgoing[grant['issuer']].append((i, grant))
    for root in packet['trust_roots']:
        for kind in KINDS:
            stack = [(root, 3, ())]
            while stack:
                source, budget, path = stack.pop()
                key = (source, kind)
                if key not in paths or budget > paths[key]['budget']:
                    paths[key] = {'budget': budget, 'grant_indices': path, 'root': root}
                for i, grant in outgoing[source]:
                    depth = grant['remaining_depth']
                    if kind in grant['kinds'] and type(depth) is int and 0 <= depth < budget:
                        stack.append((grant['subject'], depth, path + (i,)))
    return paths


def collect(packet):
    assert type(packet) is dict
    binding_keys = {'contract', 'base', 'candidate', 'approval_epoch'}
    def check_binding(binding):
        assert type(binding) is dict and set(binding) == binding_keys
        assert all(isinstance(binding[k], str) and binding[k] for k in ('contract', 'base', 'candidate'))
        assert type(binding['approval_epoch']) is int and binding['approval_epoch'] >= 0
    check_binding(packet['current_binding'])
    assert type(packet['trust_roots']) is list and packet['trust_roots']
    assert all(isinstance(x, str) and x for x in packet['trust_roots'])
    assert len(packet['trust_roots']) == len(set(packet['trust_roots']))
    for key in ('goal_ids', 'profile_ids'):
        assert type(packet[key]) is list and all(isinstance(x, str) and x for x in packet[key])
    assert type(packet['grants']) is list and type(packet['reports']) is list
    for grant in packet['grants']:
        assert type(grant) is dict
        assert all(isinstance(grant[k], str) and grant[k] for k in ('issuer', 'subject'))
        assert type(grant['remaining_depth']) is int and grant['remaining_depth'] >= 0
        assert type(grant['kinds']) is list and grant['kinds']
        assert set(grant['kinds']) <= set(KINDS) and len(set(grant['kinds'])) == len(grant['kinds'])
        assert type(grant['signature_verified']) is bool and type(grant['revoked']) is bool
        check_binding(grant['binding'])
    for report in packet['reports']:
        assert type(report) is dict and type(report['claims']) is list
        assert all(isinstance(report[k], str) and report[k] for k in ('id', 'source', 'origin_id'))
        assert report['channel'] in ('agent', 'tool', 'memory')
        assert type(report['quoted_payload']) is str
        check_binding(report['binding'])
        assert type(report['signature_verified']) is bool and type(report['revoked']) is bool
        for claim in report['claims']:
            assert type(claim) is dict and set(claim) == {'atom', 'value'}
            assert isinstance(claim['atom'], str) and claim['atom']
            assert type(claim['value']) is bool
    atoms = atom_inventory(packet)
    assert packet['goal_ids'] and packet['profile_ids']
    assert len(packet['goal_ids']) == len(set(packet['goal_ids']))
    assert len(packet['profile_ids']) == len(set(packet['profile_ids']))
    assert set(packet['support_threshold']) == set(KINDS)
    assert all(type(x) is int and x >= 1 for x in packet['support_threshold'].values())
    reports = packet['reports']
    assert len({r['id'] for r in reports}) == len(reports), 'duplicate report identity'
    paths = path_authority(packet)
    support = {atom: {False: set(), True: set()} for atom in atoms}
    admitted = []
    for report in reports:
        assert isinstance(report['origin_id'], str) and report['origin_id']
        assert type(report['signature_verified']) is bool and type(report['revoked']) is bool
        if not authentic_current(report, packet):
            continue
        used = False
        for claim in report['claims']:
            atom = claim['atom']
            assert type(claim['value']) is bool
            if atom in atoms and (report['source'], kind_of(atom)) in paths:
                support[atom][claim['value']].add(report['origin_id'])
                used = True
        if used:
            admitted.append(report['id'])
    conflicts = sorted(a for a, v in support.items() if v[False] and v[True])
    known = {}
    if not conflicts:
        for atom, values in support.items():
            for value, origins in values.items():
                if len(origins) >= packet['support_threshold'][kind_of(atom)]:
                    known[atom] = value
    return paths, support, known, conflicts, sorted(admitted)


def formula(packet, assignment):
    goal = all(assignment['g:' + g] for g in packet['goal_ids'])
    expansion = any(not assignment['b:' + p] and assignment['n:' + p]
                    for p in packet['profile_ids'])
    approval = assignment['a:match']
    authorized = not expansion or approval
    return dict(zip(FIELDS, (goal, expansion, approval, authorized, goal and authorized)))


def completion_witnesses(packet, known):
    """Construct each reachable G,D,R combination without enumerating 2^atoms.

    Every returned witness assigns every raw atom and is checked explicitly.
    The G and D blocks are disjoint, making this Cartesian construction exact.
    """
    atoms = atom_inventory(packet)
    def values(atom):
        return (known[atom],) if atom in known else (False, True)
    goal_options = {}
    for desired in (False, True):
        chosen = {('g:' + g): True for g in packet['goal_ids']}
        if desired:
            if all(True in values(a) for a in chosen):
                goal_options[desired] = chosen
        else:
            false_atom = next((a for a in chosen if False in values(a)), None)
            if false_atom is not None:
                chosen = {a: values(a)[0] for a in chosen}
                chosen[false_atom] = False
                goal_options[desired] = chosen
    profile_choices = {}
    for profile in packet['profile_ids']:
        profile_choices[profile] = list(product(values('b:' + profile), values('n:' + profile)))
    expansion_options = {}
    for desired in (False, True):
        options = {p: [pair for pair in pairs if pair != (False, True)]
                   for p, pairs in profile_choices.items()}
        if not desired:
            if not all(options.values()):
                continue
            selected = {p: pairs[0] for p, pairs in options.items()}
        else:
            witness_profile = next((p for p, pairs in profile_choices.items()
                                    if (False, True) in pairs), None)
            if witness_profile is None:
                continue
            selected = {p: pairs[0] for p, pairs in profile_choices.items()}
            selected[witness_profile] = (False, True)
        expansion_options[desired] = {prefix + ':' + p: pair[i]
                                     for p, pair in selected.items()
                                     for i, prefix in enumerate(('b', 'n'))}
    witnesses = []
    for (g, goals), (d, profiles), approval in product(goal_options.items(), expansion_options.items(), values('a:match')):
        assignment = dict(goals, **profiles, **{'a:match': approval})
        assert set(assignment) == atoms
        assert all(assignment[a] == v for a, v in known.items())
        outputs = formula(packet, assignment)
        assert (outputs['goal_correct'], outputs['protected_expansion'], outputs['approval_matches']) == (g, d, approval)
        witnesses.append({'assignment': assignment, 'fields': outputs})
    assert witnesses
    return witnesses


def independently_review(packet):
    paths, support, known, conflicts, admitted = collect(packet)
    witnesses = [] if conflicts else completion_witnesses(packet, known)
    answer = {}
    for field in FIELDS:
        values = {w['fields'][field] for w in witnesses}
        answer[field] = next(iter(values)) if len(values) == 1 else None
    answer.update(evidence_integrity='conflicting' if conflicts else 'consistent',
                  decision={True: 'allow', False: 'deny', None: 'undetermined'}[answer['release_allowed']],
                  admitted_report_ids=admitted)
    if not conflicts and answer['release_allowed'] is None:
        assert {w['fields']['release_allowed'] for w in witnesses} == {False, True}
    return answer, dict(known_atoms=known, conflicts=conflicts, witnesses=witnesses,
                        authority=paths, support=support)


def consequences(theory, seeds):
    """Agenda-based Horn closure, independent of benchmark materialization."""
    clauses = [(frozenset([a]), b) for a, b in theory['subclass']]
    clauses += [(frozenset(r['antecedents']), r['head']) for r in theory['rules']]
    uses = defaultdict(list)
    pending = [len(ants) for ants, head in clauses]
    for index, (ants, head) in enumerate(clauses):
        for atom in ants:
            uses[atom].append(index)
    derived = set(seeds)
    agenda = deque(derived)
    for i, (ants, head) in enumerate(clauses):
        if not ants and head not in derived:
            derived.add(head)
            agenda.append(head)
    while agenda:
        atom = agenda.popleft()
        for i in uses[atom]:
            pending[i] -= 1
            head = clauses[i][1]
            if pending[i] == 0 and head not in derived:
                derived.add(head)
                agenda.append(head)
    consistent = not any(set(pair) <= derived for pair in theory['disjoint'])
    return derived, consistent


def independent_hidden_atoms(unit):
    contract = unit['contract']
    public = sorted(contract['public_classes'])
    profiles = [xs for n in range(len(public) + 1) for xs in combinations(public, n)]
    atoms = {}
    for index, goal in enumerate(contract['goals']):
        derived, consistent = consequences(unit['candidate'], goal['profile'])
        actual = goal['target'] in derived
        if goal['kind'] == 'effective':
            actual = actual and consistent
        atoms['g:' + str(index)] = actual == goal['expected']
    for index, profile in enumerate(profiles):
        for prefix, theory in (('b', contract['base']), ('n', unit['candidate'])):
            derived, consistent = consequences(theory, profile)
            atoms[prefix + ':' + str(index)] = consistent and contract['protected_permission'] in derived
    return atoms


def check_candidate(unit):
    """Apply the one edit to a JSON copy and compare normalized graph contents."""
    graph = deepcopy(unit['contract']['base'])
    edit = unit['proposal']
    operation = edit['op']
    if operation in ('add_edge', 'remove_edge', 'add_disjoint', 'remove_disjoint'):
        assert set(edit) == {'op', 'left', 'right'}
        key = 'subclass' if operation.endswith('edge') else 'disjoint'
        target = [edit['left'], edit['right']]
        assert set(target) <= set(graph['classes'])
        if key == 'disjoint':
            target.sort()
    else:
        assert operation in ('add_rule', 'remove_rule')
        assert set(edit) == {'op', 'antecedents', 'head'}
        assert edit['antecedents'] and len(set(edit['antecedents'])) == len(edit['antecedents'])
        assert set(edit['antecedents']) | {edit['head']} <= set(graph['classes'])
        key = 'rules'
        target = {'antecedents': sorted(edit['antecedents']), 'head': edit['head']}
    if operation.startswith('add_'):
        assert target not in graph[key]
        graph[key].append(target)
    else:
        assert target in graph[key]
        graph[key].remove(target)
    def normalized(theory):
        return dict(classes=sorted(theory['classes']), subclass=sorted(theory['subclass']),
                    disjoint=sorted(sorted(p) for p in theory['disjoint']),
                    rules=sorted((sorted(r['antecedents']), r['head']) for r in theory['rules']))
    assert normalized(graph) == normalized(unit['candidate']), 'candidate does not implement proposed edit'


def check_exclusions(data, project_root):
    old_structural, old_semantic = set(), set()
    for entry in data['exclusion_datasets']:
        rel = Path(entry['path'])
        assert not rel.is_absolute() and '..' not in rel.parts
        previous = json.loads((project_root / rel).read_text())
        assert digest(previous) == entry['sha256'], ('exclusion dataset changed', entry['path'])
        queue = [previous]
        while queue:
            value = queue.pop()
            if isinstance(value, dict):
                if 'structural_fingerprint' in value:
                    old_structural.add(value['structural_fingerprint'])
                if 'semantic_fingerprint' in value:
                    old_semantic.add(value['semantic_fingerprint'])
                queue.extend(value.values())
            elif isinstance(value, list):
                queue.extend(value)
    assert not old_structural.intersection(u['structural_fingerprint'] for u in data['units'])
    assert not old_semantic.intersection(u['semantic_fingerprint'] for u in data['units'])
    return dict(datasets=len(data['exclusion_datasets']), structural_fingerprints=len(old_structural),
                semantic_fingerprints=len(old_semantic))


def audit_dataset(data, dataset_sha256=None, project_root=None):
    units = {u['unit_id']: u for u in data['units']}
    assert len(units) == len(data['units'])
    assert len({c['id'] for c in data['cases']}) == len(data['cases'])
    assert len({u['structural_fingerprint'] for u in units.values()}) == len(units)
    assert len({u['semantic_fingerprint'] for u in units.values()}) == len(units)
    for unit in units.values():
        check_candidate(unit)
    exclusions = check_exclusions(data, project_root or Path(__file__).resolve().parents[2])
    hidden = {uid: independent_hidden_atoms(u) for uid, u in units.items()}
    counts = defaultdict(Counter)
    condition_counts = Counter()
    receipts = []
    for case in data['cases']:
        packet = case['input']
        expected, evidence = independently_review(packet)
        assert expected == case['reference'], ('reference disagreement', case['id'], expected, case['reference'])
        assert case['split'] == units[case['unit_id']]['split']
        atoms = hidden[case['unit_id']]
        assert set(atoms) == atom_inventory(packet) - {'a:match'}
        latent = case['hidden_semantic_truth']
        assert type(latent['approval_matches']) is bool
        hidden_assignment = dict(atoms, **{'a:match': latent['approval_matches']})
        assert formula(packet, hidden_assignment) == latent, 'hidden semantic label disagreement'
        if not evidence['conflicts']:
            # Check all current, authorized raw semantic claims, even below quorum.
            for atom, supports in evidence['support'].items():
                if atom == 'a:match':
                    continue
                for value, origins in supports.items():
                    if origins:
                        assert value == atoms[atom], ('admissible semantic lie', case['id'], atom)
        assert not any(k in packet for k in ('reference', 'condition', 'stratum', 'candidate', 'base', 'contract'))
        counts[case['split']][expected['decision']] += 1
        condition_counts[(case['split'], case['condition'])] += 1
        opposite = {}
        for witness in evidence['witnesses']:
            opposite.setdefault(str(witness['fields']['release_allowed']).lower(), witness)
        receipts.append(dict(id=case['id'], split=case['split'], condition=case['condition'],
                             independent_reference=expected, established_atoms=len(evidence['known_atoms']),
                             conflicting_atoms=evidence['conflicts'],
                             compatible_release_witnesses=opposite))
    assert set(data['dev_call_ids']) <= {c['id'] for c in data['cases'] if c['split'] == 'dev'}
    return dict(status='PASS', dataset_sha256=dataset_sha256, units=len(units), cases=len(receipts),
                decisions={k: dict(v) for k, v in counts.items()},
                condition_counts=[dict(split=s, condition=c, count=n) for (s, c), n in sorted(condition_counts.items())],
                excluded_prior_fingerprints=exclusions,
                independent_methods=['rooted grant path enumeration', 'independent edit application', 'agenda Horn closure',
                                     'constructive raw-atom Boolean completions'],
                scope='Checks a simulated source-policy contract, not real authentication or factual source reliability.',
                case_receipts=receipts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    result = audit_dataset(json.loads(raw), hashlib.sha256(raw).hexdigest())
    if args.output:
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('case_receipts', 'condition_counts')}, sort_keys=True))


if __name__ == '__main__':
    main()
