# Level 1 Semantic and Epistemic Governance

Public independent research package, version 0.1.6-dev. This is a standalone copy, not a submodule or a pointer to the original research checkout. The repository is public; the manuscript remains a working draft, not peer reviewed.

Version 0.1.6-dev revises the working manuscript for publication review: explicit inference settings, corrected corpus/DEV labels, self-contained figures, narrower evidentiary scope, and confirmed independent authorship and no external funding. The fixed benchmark version, cases, frozen requests, model outputs, scorers and reported scores are unchanged. `release-manifests/0.1.5-dev.json` preserves the preceding package manifest.

The original problem bytes, model-facing requests and scorer sources are copied with origin hashes. They are never regenerated from a newer generator. Native source code is unchanged; only minimal package namespace initializers and an offline CLI are new. Original experiment history remains in the research archive.

## Reproduce offline

Use Python3.11–3.13. Level1 uses only the standard library for these replay commands. No neural model, GPU, API key or network is used by reproduction.

```sh
python -I reproduce.py verify
python -I reproduce.py replay
python -I reproduce.py score --responses new-predictions.jsonl
```

For Level1 the historical full constructed data contains96 semantic and144 epistemic examples; the six-model measured subset has48semanticDEV+96epistemicDEV and six TRAIN delivery observations per model. Keep those splits. Historical eleven-model feedback is a separate96-unit/480-scenario cohort with reference-guided stopping. Supporting two-model source-evidence reports are separate and their full native audit remains in the archive; the CLI currently replays the main and eleven-model feedback scores.

Level 2 is still under development; preliminary results are not yet available. This repository documents the Level 1 study only.

`origins.json` records original source paths and hashes; `release-manifest.json` binds this package's actual files. A future rerun uses a new result directory and explicit model settings, never overwrites a prior record. Model-facing inputs exclude reference and construction fields. Exact frozen request bodies are retained for later authorized inference, but this package does not automatically send them.

Code is MIT; author-generated benchmark data and documentation are CC BY4.0. Saved final model responses are included for offline reproduction. Full native HTTP and reasoning archives remain in the private research archive. The paper under paper/ is a working draft, not a submission-ready publication. These are LLM reasoning measurements, not agent architecture or containment tests.

## Manuscript review and build

The current [typeset draft](output/pdf/semantic-epistemic-governance-level1.pdf), [readable manuscript](paper/paper.md), and [publication review](review/publication-review-2026-10-18.md) are distinct from the immutable benchmark data. The current draft remains a descriptive development study with one judgment per case. No ten-pass replication has been launched.

Optional authoring dependencies are Pandoc, Tectonic and matplotlib; they are not required by offline benchmark replay.

```sh
python3 scripts/build_paper.py --figures --pdf
python3 scripts/audit_manuscript.py
```

The HTML view embeds its figures. The TeX source retains vector plots whose numerical coordinates are checked by the manuscript audit. The author has no institutional affiliation and confirms no external funding. Competing interests and venue-specific submission requirements remain to be finalized.
