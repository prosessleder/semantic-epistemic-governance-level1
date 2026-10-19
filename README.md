# Semantic and Epistemic Governance: Ten-Run Results on the Basic Level 1 Tests

**Paper 2: Basic Level 1. Public preprint, version `0.2.0-preprint`, released 19 October 2026. Not peer reviewed.** [Download the manuscript and scientific supplement](https://github.com/prosessleder/semantic-epistemic-governance-level1/releases/tag/v0.2.0-preprint). The original fixed benchmark identifier remains `level1-fixed-2026-10-16`.

The paper now reports all ten nominal passes for six hosted configurations on 48 semantic DEV cases and 96 epistemic DEV packets per pass. The principal result view is explicitly **post-hoc amended**: 8,630 original received finals plus ten later fresh generations linked to the original unknown slots yield 8,640 observed finals and twelve complete model-tracks. The original primary study remains incomplete, with ten unknown outcomes and five unavailable full-ten model-track summaries. No received answer was replaced, no answer was chosen by correctness, and every failed/unknown attempt reservation remains retained.

All configurations requested medium native reasoning with a 32,768 combined reasoning/output-token cap. Strict typed bare JSON is primary; sole-outer-fence normalization is a separate sensitivity. The twelve semantic construction groups and twelve epistemic units remain correlated inspected DEV material. Repetition adds no independent task units. Scheduling amendments, later follow-up timing/load and missingness limit exchangeability; there is no equal-compute, population-reliability, held-out or containment claim.

## Manuscript and ten-round results

- [Canonical manuscript](paper/paper.tex), [readable companion](paper/paper.md), and [typeset PDF](output/pdf/semantic-epistemic-governance-level1.pdf).
- [Self-contained ten-round scientific projection](results/ten-pass-amended-v1/README.md), including exact cases/scorers, original and follow-up final projections, declared native usage/attempt accounting, preserved incomplete-primary statistics and full amended statistics.
- [All round results](results/ten-pass-amended-v1/tables/rounds.csv), [complete-track summaries](results/ten-pass-amended-v1/tables/summary.csv), [per-case consistency](results/ten-pass-amended-v1/tables/per-case-consistency.csv), [components](results/ten-pass-amended-v1/tables/components.csv) and [exclusive outcome categories](results/ten-pass-amended-v1/tables/native-outcomes.csv).

The manuscript includes every nominal round under both parsers, sample SD/ranges, case-consistency distributions, whole-answer components, distinct generation/unit intervals and the immutable original-cohort comparison. Nominal rounds are slot labels, not synchronized independent experimental blocks. Original pass 2/pass 5 gaps were filled later, as disclosed in the methods and round tables.

## Reproduce offline

Python 3.11–3.13 is sufficient for score replay; no model, GPU, API key or network is required. The ten-round full statistical replay uses Python 3.12 and the standard library.

```sh
python -I reproduce.py verify
python -I reproduce.py replay
python -I results/ten-pass-amended-v1/replay.py verify
python -I results/ten-pass-amended-v1/replay.py replay
python scripts/ten_pass_publication_tables.py check
python scripts/audit_manuscript.py
```

The historical `reproduce.py replay` command retains its original six-configuration single-pass and eleven-model feedback scope. The separate ten-round replay checks 150 original reference cases, 17,260 original strict/fence scores and 20 follow-up scores, exact original/follow-up mapping, partitions, billing and **both full original and amended analyses**. Both unchanged statistical algorithms use 20,000 draws, with generation seed 2026101803 and separate unit-sensitivity seed 2026101804. Frozen JSON integer-key normalization changes representation only.

Public projection metadata omits private author/planning records and documents a host-specific interpreter-path redaction. Cases, scorers, final text, scores, usage, attempt accounting and statistical analysis payloads preserve the scientific source bytes. Full native HTTP/reasoning/partial/error bodies remain in the private archive. Portable final-projection replay is not independent raw-HTTP authentication or regeneration of hosted-model answers.

## Historical cohorts

The original single-pass comparison has 48 semantic DEV + 96 epistemic DEV judgments and six separate TRAIN interface observations per model. The eleven-model feedback cohort has 480 scenarios from 96 underlying units, an 8,192 combined-token allowance and reference-guided stopping; its cumulative retained answers are not fresh judgments at each checkpoint. The earlier two-model source-evidence study has 384 views from 24 units under its own policy. All remain separate from the ten-round cohort. Existing original cases, request bodies, source snapshots, saved outputs and reports remain unchanged.

## Build and package the scientific supplement

Optional authoring dependencies are Pandoc, Tectonic and matplotlib. The canonical TeX is self-contained; the built-in desktop LaTeX compiler can compile it independently. The readable companion and embedded-figure HTML are generated from that source.

```sh
python scripts/build_paper.py --figures --pdf
python scripts/audit_manuscript.py
python scripts/package_publication.py
```

The publication ZIP uses a scientific allowlist. It excludes authoring instructions, private review/planning, live runs, native HTTP/reasoning, credentials and compiler scratch files. Its manifests bind exact included bytes. Older release manifests remain historical; document/package version changes do not regenerate the benchmark.

## Authorship and rights

Timothy O’Brien is the sole author, an independent researcher without institutional affiliation. No external funding was received. Codex assisted research and manuscript preparation; accountability remains with the author. The author confirms no competing interests. A venue-specific submission must also follow that venue's current instructions.

Code is MIT; author-generated data/documentation are CC BY 4.0. Saved final model responses support offline reproduction; third-party sources retain their rights. This is a public preprint with no assigned DOI. No journal submission, acceptance or independent external peer review is claimed.
