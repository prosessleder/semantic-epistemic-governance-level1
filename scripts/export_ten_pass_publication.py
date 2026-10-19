#!/usr/bin/env python3
"""Create a new curated scientific projection; never change its source capsule.

Usage: python -B scripts/export_ten_pass_publication.py --source CAPSULE --output NEWDIR
No inference, credentials, networking, publication, or existing-file replacement.
The source is an already audited final-projection capsule, not a native archive.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys


OMIT = {'followup/direct-human-authorization.json', 'followup/protocol.md'}
METADATA = {'README.md', 'manifest.json', 'provenance.json',
            'primary/README.md', 'primary/manifest.json', 'primary/provenance.json'}
REDACTED_PLAN = 'primary/data/original-plan.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    with Path(path).open('x') as handle:
        json.dump(value, handle, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        handle.write('\n')


def text(path, value):
    with Path(path).open('x') as handle:
        handle.write(value)


def files(root):
    return {str(p.relative_to(root)): p for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def manifest(root):
    return dict(version='publication-final-projection-manifest-v1', files=[
        dict(path=name, bytes=p.stat().st_size, sha256=sha(p))
        for name, p in files(root).items() if name != 'manifest.json'])


def check_manifest(root):
    declared = {r['path']: r for r in read(root/'manifest.json')['files']}
    actual = files(root)
    actual.pop('manifest.json')
    if set(declared) != set(actual):
        raise ValueError('Source manifest inventory mismatch')
    for name, row in declared.items():
        p = actual[name]
        if p.is_symlink() or p.stat().st_size != row['bytes'] or sha(p) != row['sha256']:
            raise ValueError('Source manifest byte mismatch: '+name)


PRIMARY_README = '''# Original primary ten-round study: incomplete

This publication projection preserves 8,630 received/scored finals from 8,640
planned identities, ten attempted unknown outcomes, zero never-submitted slots,
and 8,643 closed attempts across four execution legs. Seven model-tracks have
complete ten-round summaries; five retain unavailable full-ten estimates.
The ten later generations in the parent capsule do not alter this original study.

All cases, scorer dependencies, finals, scores, usage, attempt accounting and
statistical results are byte-identical to the audited source capsule. Metadata is
curated: this README and manifests/provenance were regenerated, and one original
plan host interpreter path was replaced by `python3.12`. The original plan hash
and exact single-field change are recorded in the parent provenance.

From this directory use Python 3.12, standard library only:

```
python -B replay.py verify
python -B replay.py replay
```

Full replay checks 150 references, 17,260 strict/fence scores, partition and
declared billing, and the original full statistics under both frozen 20,000-draw
seeds. Scorer dependencies retain historical client definitions for exact source
binding; this reader never calls inference or credential loaders. Native HTTP,
reasoning and partial/error bodies are excluded. Hash links to private native
proofs provide provenance, not a portable independent HTTP-authenticity audit.
'''

README = '''# Level 1 ten-round post-hoc amended results

This curated publication projection contains the complete amended dataset:
8,630 original received finals plus ten later fresh generations for the ten
original unknown slots. It covers 8,640 planned case/model/round identities.
The original primary experiment remains incomplete at 8,630/8,640. Its ten
unknown outcomes, full failed/unknown reservations and five unavailable full-ten
estimates remain preserved in `primary/`.

No received answer was replaced or selected by correctness. Follow-ups retain
new `followup1--` identities and explicit original-slot links. This is a post-hoc
amended result, not an uninterrupted completed original experiment. See
`scientific-protocol.md` for design, scheduling and inference limitations.

Python 3.12, standard library only; from the repository root:

```
python -B results/ten-pass-amended-v1/replay.py verify
python -B results/ten-pass-amended-v1/replay.py replay
python -B scripts/ten_pass_publication_tables.py check
```

The first command verifies bytes, mapping, coverage, categories and declared
billing. Full replay additionally checks all 150 references and 17,280 strict/
fence scores, then independently regenerates both complete saved statistical
analyses with the frozen algorithms and seeds. No inference or credential is
required. A full replay can take several minutes.

`tables/` contains original-primary and amended round, consistency, component,
tier, native-category and resource CSVs. Blank full-ten fields mean unavailable,
not zero. All percentage columns are explicitly named; SD is in percentage
points. Latencies include transport/system interruption and are not pure
reasoning time. Reservations are conservative exposure bounds, not known bills.

The scientific payload is exact. README/manifests/provenance are curated public
metadata, one non-scientific interpreter host path is redacted, and private
authorization/planning documents are omitted. Every source-byte comparison and
the exact redaction are declared in `provenance.json`. The original private
capsule is unchanged. No raw HTTP, exposed reasoning, private host path or
credential is included. Hash-linked native proofs remain outside portable scope.
'''

PROTOCOL = '''# Scientific protocol and interpretation

## Cohorts and execution

Six configurations each received 48 semantic DEV cases and 96 epistemic DEV
packets in ten fresh repetitions: 8,640 planned scored generations. Historical
single-pass, eleven-model feedback, two-model source-evidence and interface
cohorts are excluded from these denominators. The 150 retained reference cases
also include three TRAIN interface cases per track; these are checked offline
but are not ten-round accuracy observations.

All configurations requested native medium reasoning and 32,768 combined
reasoning/output tokens with their original model/provider and prompt settings.
There was no feedback, answer repair, majority vote, best-answer choice or
correctness retry. Exact request hashes, settings, cases, source bindings and
slot orders are retained in execution plans. A shared label/token cap does not
establish equal realized compute.

The original experiment used four disjoint execution legs. Scheduling changed
from the initial arrangement to independent model queues, with at most four
requests per model and 24 overall. The later recovery legs admitted only exact
never-attempted complements, preserving all prior deliveries and unknowns.
Original round labels do not denote simultaneous model sessions. Ten transport
outcomes remained unknown. Three explicit transient HTTP failures received the
allowed identical retries; their full failure reserves remain recorded.

After the original experiment closed, ten fresh generations were collected in a
separate follow-up namespace: four Qwen (one semantic, three epistemic) and two
epistemic each for Terra, Luna and Haiku. Original bodies/settings/scorers were
retained; received answers were never replaced. All ten follow-ups delivered,
with no new transport loss or transient retry. The amended projection maps them
to the ten previously missing original case/model/round identities while keeping
both attempt histories. Later timing/load and missingness may violate generation
exchangeability. There were 8,653 closed attempts across the two namespaces.

## Outcomes and dependence

Strict typed bare JSON is primary. A separately labeled sensitivity removes only
a sole outer fence; it performs no prose extraction, interior repair or fact-order
relaxation. Delivered malformed, schema-invalid, filtered, provider-error or
length-limited outputs are observed outcomes. An unknown transport outcome is
missing rather than a fabricated answer. Provider/filter/length/format losses
remain separate from demonstrated completed task errors. The two tracks are not
pooled into an overall model ranking.

Semantic DEV has twelve underlying groups: six with six cases and six with two.
Epistemic DEV has twelve units with eight correlated packets each (four matched
authority/provenance conditions and two orders), comprising 224 actions per
repetition. Repetition creates no new independent task units.

## Statistical estimands

For complete model-tracks, report all ten round rates, their mean, sample SD and
range, and per-case success counts out of ten. The fixed-corpus generation
interval resamples the ten generations within each case, using 20,000 draws and
seed 2026101803. It describes conditional generation variation on this fixed
corpus and assumes within-case exchangeability; time/provider/load dependence
can violate that assumption.

A distinct unit-resampling sensitivity uses 20,000 draws and seed 2026101804,
keeping all variants and rounds from a sampled unit together. Both case-weighted
and unit-weighted estimands are retained. These conditional percentile intervals
are not interchangeable or population guarantees. All fifteen within-track
pairwise contrasts are exploratory; no significance-selected ranking is claimed.
The frozen statistical algorithms and JSON key normalization are unchanged.

Original-primary incomplete tracks retain null full-ten summaries and intervals.
Their observed round counts remain available without denominator repair. All
twelve amended model-tracks are complete, including five whose full-ten summaries
exist only in this explicitly post-hoc amended dataset. This does not amend the
original completion claim. All-success conditional intervals do not establish
perfect reliability on new tasks.

## Resources and reproducibility scope

Reported complete charges across original and follow-up attempts total
USD134.006024705. Full failed/unknown reservations of USD1.947109186 are retained,
giving USD135.953133891 exposure under the same USD200 cap. Follow-up complete
charges total USD0.167018389. Reservations are not asserted actual billing.
No account/cap increase was needed. Per-track token, latency and completion-time
summaries are in the resource CSV; latency is not pure model reasoning time.

The study concerns inspected synthetic DEV constructions and supplied finite
governance rules. It does not establish held-out generalization, real source
reliability, a causal effort effect, equal time/compute, feedback effectiveness,
autonomous release behavior or general containment. Independent implementations
check the finite references, not the adequacy of a real authority policy.

The portable package verifies final projections, original scores, mappings,
partitions, declared billing and the entire original and amended statistics.
Native HTTP/reasoning/partial/error bodies remain private; their proof hashes
are provenance links, not an independent portable HTTP-authenticity audit.
Private operational documents are excluded. Scientific payload bytes are retained;
curated metadata and the single host-path redaction are explicitly declared.
'''


def export(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or source in output.parents:
        raise ValueError('Publication output must be outside its immutable source capsule')
    if output.exists():
        raise ValueError('Output already exists; use a new projection directory')
    check_manifest(source)
    check_manifest(source/'primary')
    source_files = files(source)
    source_hashes = {name: sha(path) for name, path in source_files.items()}
    output.mkdir(parents=True)
    exact = {}
    for name, path in source_files.items():
        if name in OMIT | METADATA | {REDACTED_PLAN}:
            continue
        destination = output/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        if sha(path) != sha(destination):
            raise ValueError('Scientific payload copy differs: '+name)
        exact[name] = sha(path)
    original = read(source/REDACTED_PLAN)
    public = json.loads(json.dumps(original))
    old_executable = public['runtime']['executable']
    if not isinstance(old_executable, str) or not old_executable.startswith('/Users/'):
        raise ValueError('Expected exactly the declared non-scientific host path')
    public['runtime']['executable'] = 'python3.12'
    reverted = json.loads(json.dumps(public))
    reverted['runtime']['executable'] = old_executable
    if reverted != original:
        raise ValueError('Non-redacted execution-plan field changed')
    write(output/REDACTED_PLAN, public)
    text(output/'README.md', README)
    text(output/'primary/README.md', PRIMARY_README)
    text(output/'scientific-protocol.md', PROTOCOL)
    primary_provenance = read(source/'primary/provenance.json')
    primary_provenance.update(publication_metadata_derivative=True,
        scientific_payload_byte_exact=True, original_private_capsule_unchanged=True,
        original_plan_source_sha256=sha(source/REDACTED_PLAN),
        host_path_redaction=dict(json_pointer='/runtime/executable', replacement='python3.12',
                                 all_other_json_fields_exact=True),
        source_metadata_sha256={name: sha(source/name) for name in sorted(METADATA) if name.startswith('primary/')})
    write(output/'primary/provenance.json', primary_provenance)
    write(output/'primary/manifest.json', manifest(output/'primary'))
    provenance = read(source/'provenance.json')
    provenance.update(version='level1-ten-pass-publication-projection-v1',
        original_primary_capsule_byte_for_byte=False, scientific_payload_byte_exact=True,
        publication_metadata_derivative=True, original_private_capsule_unchanged=True,
        source_capsule_manifest_sha256=sha(source/'manifest.json'),
        exact_source_payload_files=exact,
        omitted_private_metadata={name: sha(source/name) for name in sorted(OMIT)},
        regenerated_metadata_source_sha256={name: sha(source/name) for name in sorted(METADATA)},
        redacted_execution_plan=dict(path=REDACTED_PLAN, original_sha256=sha(source/REDACTED_PLAN),
            publication_sha256=sha(output/REDACTED_PLAN), json_pointer='/runtime/executable',
            replacement='python3.12', all_other_json_fields_exact=True),
        original_primary_files={name: sha(path) for name, path in files(output/'primary').items()},
        metadata_scope='README, manifests and provenance are curated derivatives; scientific payload exact; one host interpreter path redacted; private authorization/planning omitted')
    write(output/'provenance.json', provenance)
    spec = importlib.util.spec_from_file_location('publication_tables', Path(__file__).with_name('ten_pass_publication_tables.py'))
    tables = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tables)
    tables.write_tables(output, output/'tables')
    for name, path in files(output).items():
        raw = path.read_bytes()
        if re.search(rb'/Users/|/private/tmp/|PRIVATE REVIEW COPY|sk-or-v1-[A-Za-z0-9]{12}', raw):
            raise ValueError('Private host path/review marker/credential pattern in public projection: '+name)
    write(output/'manifest.json', manifest(output))
    if {name: sha(path) for name, path in files(source).items()} != source_hashes:
        raise ValueError('Source capsule changed during export')
    return dict(status='CURATED_PUBLICATION_PROJECTION_CREATED', source_scientific_payload_exact=len(exact),
        metadata_derivative=True, single_plan_host_path_redacted=True,
        original_primary_received=8630, original_primary_unknown=10, original_study_complete=False,
        amended_received=8640, new_model_calls=0, publication=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.source, args.output), sort_keys=True))
