#!/usr/bin/env python3
"""Build an allowlisted scientific supplement. No upload or inference.

Historical scientific files come from the saved 0.1.6 inventory and must remain
byte-identical. The added ten-round projection has its own complete manifest.
Only ordinary manuscript/build metadata are regenerated for this new candidate.
"""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
OLD = 'release-manifests/0.1.6-dev.json'
OLD_SHA = '64cbea47ae59ebc99d73b40dd1008ad959cdd4879642a15a1185ac48c42c85d7'
CAPSULE = 'results/ten-pass-amended-v1'
FROZEN_PREFIXES = ('data/', 'results/', 'internal/', 'ontology_boundary/')
AUTHORING = [
    'README.md', 'CITATION.cff', 'LICENSE', 'LICENSE-CODE',
    'LICENSE-DOCUMENTATION.md', 'pyproject.toml', 'requirements.txt',
    'reproduce.py', 'paper/paper.tex', 'paper/paper.md',
    'paper/ten-pass-generated.json',
    'paper/figures/ten-pass-intervals.png',
    'paper/figures/ten-pass-format-sensitivity.png',
    'paper/figures/ten-pass-provenance.json',
    'output/paper.html', 'output/pdf/semantic-epistemic-governance-level1.tex',
    'output/pdf/semantic-epistemic-governance-level1.pdf',
    'scripts/audit_manuscript.py', 'scripts/build_paper.py',
    'scripts/build_ten_pass_figures.py', 'scripts/sync_manuscript.py',
    'scripts/ten_pass_publication_tables.py',
    'scripts/export_ten_pass_publication.py', 'scripts/package_publication.py',
    'scripts/package_publication_v021.py', 'CORRECTION-0.2.1.md',
    'release-manifests/0.2.0-preprint.json',
]
TARGET = ROOT/'release/semantic-epistemic-governance-level1-0.2.1-preprint.zip'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def payload(name):
    path = ROOT/name
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing or symlinked supplement member: '+name)
    if Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('Unsafe relative member name: '+name)
    return path.read_bytes()


def main():
    old_bytes = payload(OLD)
    if sha(old_bytes) != OLD_SHA:
        raise ValueError('Historical release inventory changed')
    historical = json.loads(old_bytes)
    frozen = {}
    for row in historical['files']:
        name = row['path']
        if not name.startswith(FROZEN_PREFIXES):
            continue
        data = payload(name)
        if sha(data) != row['sha256'] or len(data) != row['bytes']:
            raise ValueError('Historical scientific payload changed: '+name)
        frozen[name] = data
    capsule_manifest = payload(CAPSULE+'/manifest.json')
    capsule_rows = json.loads(capsule_manifest)['files']
    capsule = {CAPSULE+'/manifest.json': capsule_manifest}
    for row in capsule_rows:
        name = CAPSULE+'/'+row['path']
        data = payload(name)
        if sha(data) != row['sha256'] or len(data) != row['bytes']:
            raise ValueError('Ten-round projection changed: '+name)
        capsule[name] = data
    if len(capsule) != len(capsule_rows)+1 or set(frozen) & set(capsule):
        raise ValueError('Duplicate or overlapping supplement inventory')
    authoring = {name: payload(name) for name in AUTHORING}
    configured_host_prefix = (str(Path.home())+'/').encode()
    for name, data in authoring.items():
        if configured_host_prefix in data:
            raise ValueError('Host-specific path in new authoring file: '+name)
    members = {**frozen, **capsule, **authoring, OLD: old_bytes}
    provenance = dict(
        version='level1-publication-candidate-provenance-v1',
        historical_public_baseline='dbb691fdee34afaec921130ccc34563ad0c09e88',
        historical_release_manifest_sha256=OLD_SHA,
        historical_scientific_files_byte_exact=len(frozen),
        ten_round_projection_manifest_sha256=sha(capsule_manifest),
        ten_round_scientific_provenance=CAPSULE+'/provenance.json',
        original_primary_received=8630, original_primary_unknown=10,
        original_study_complete=False, amended_received=8640,
        amended_complete_model_tracks=12, new_model_calls_by_packaging=0,
        scope='Paper 2 public preprint; original incomplete study preserved; '
              'later follow-ups explicitly post hoc. No journal submission or peer-review claim.',
        omitted='Agent instructions, private review/planning and operational origin '
                'metadata, live runs, native HTTP/reasoning and compiler scratch files.',
        historical_source_scope='Byte-exact older public scientific source snapshots '
                'can retain inert historical host-path strings. New ten-round '
                'projection redactions are declared in its own provenance.'
    )
    provenance_bytes = json_bytes(provenance)
    (ROOT/'SOURCE_PROVENANCE.json').write_bytes(provenance_bytes)
    members['SOURCE_PROVENANCE.json'] = provenance_bytes
    rows = [dict(path=name, bytes=len(data), sha256=sha(data))
            for name, data in sorted(members.items())]
    manifest = dict(version='0.2.1-preprint', level=1,
        benchmark_version='level1-fixed-2026-10-16',
        status='PUBLIC_PREPRINT',
        reporting_parser='framing_sensitivity',
        reporting_correction='Ignore a sole outer Markdown fence; no data, denominator, scorer, algorithm or seed change',
        previous_public_version='0.2.0-preprint',
        new_model_calls_by_export=0,
        previous_manifest_sha256=OLD_SHA,
        original_study_complete=False, original_primary_received=8630,
        original_primary_unknown=10, post_hoc_amended_received=8640,
        complete_amended_model_tracks=12,
        packaging_note='New manuscript and scientific supplement. Historical '
          'cases, requests, scorer sources and saved outputs remain byte exact. '
          'The added scientific projection retains original and amended analyses; '
          'its metadata curation is separately declared.',
        files=rows)
    manifest_bytes = json_bytes(manifest)
    (ROOT/'release-manifest.json').write_bytes(manifest_bytes)
    members['release-manifest.json'] = manifest_bytes
    members['SHA256SUMS.json'] = json_bytes({name:sha(data)
                                           for name,data in sorted(members.items())})
    for name in members:
        if '__pycache__' in Path(name).parts or Path(name).name == 'AGENTS.md':
            raise ValueError('Non-scientific supplement member: '+name)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(TARGET, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(members.items()):
            info = ZipInfo(name, date_time=(2026,10,19,0,0,0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with ZipFile(TARGET) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('Duplicate ZIP member')
        sums = json.loads(archive.read('SHA256SUMS.json'))
        if set(sums) != set(archive.namelist())-{'SHA256SUMS.json'}:
            raise ValueError('ZIP inventory differs from its hash receipt')
        for name, digest in sums.items():
            if sha(archive.read(name)) != digest:
                raise ValueError('ZIP byte verification failed: '+name)
    print(json.dumps(dict(status='LOCAL_SUPPLEMENT_BYTE_CHECK_PASS',
        target=str(TARGET), files=len(members),
        historical_scientific_files_byte_exact=len(frozen),
        ten_round_projection_files=len(capsule),
        zip_bytes=TARGET.stat().st_size, zip_sha256=sha(TARGET.read_bytes()),
        manifest_sha256=sha(manifest_bytes), new_model_calls=0,
        publication=False),sort_keys=True))


if __name__ == '__main__':
    main()
