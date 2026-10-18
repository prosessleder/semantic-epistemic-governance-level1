# Level 1 Semantic and Epistemic Governance

Private independent research package, version0.1.4-dev. This is a standalone copy, not a submodule or a pointer to the original private checkout. No public release is implied.

Version 0.1.4-dev retains the documentation-only reasoning-setting clarification and explicitly marks Level 2 as unfinished, with preliminary results not yet available. The fixed benchmark version, cases, frozen requests, model outputs, scorers and reported scores are unchanged; `release-manifests/0.1.2-dev.json` preserves the preceding package manifest.

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

Code is MIT; author-generated benchmark data and documentation are CC BY4.0. Native model-generated material remains private pending redistribution review. The paper under paper/ is a working draft, not a submission-ready publication. These are LLM reasoning measurements, not agent architecture or containment tests.
