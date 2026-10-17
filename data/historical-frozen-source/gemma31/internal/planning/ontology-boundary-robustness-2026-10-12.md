# Frozen model-family and reasoner-assisted robustness follow-up

Declared on 12 October 2026, after the completed original pilot and endpoint
diagnostic. This is a post-hoc robustness investigation on the SAME four DEV
and 24 TEST pairs, not untouched confirmation. Original sources, plans and
results are unchanged. No activation steering, training, cloud inference,
autonomous agent action or actual ontology promotion is used.

## Questions

1. Do the release-review observations transfer to an independent model family?
2. Does supplying verified finite-profile permission facts improve review,
   relative to an otherwise identical raw-theory request?
3. Can each model solve the corresponding single-ontology deduction questions
   and remain consistent when response codes reverse?

## Models and execution

- Existing comparator: Qwen/Qwen3-4B-Instruct-2507, revision
  `cdbee75f17c01a7cc42f958dc650907174af0554`.
- Independent family: mistralai/Mistral-7B-Instruct-v0.3, revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`, published Apache 2.0 checkpoint.
  Primary card: https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3.
  It also differs in size and release date; outcomes cannot isolate architecture,
  model size or training-data effects. This is not a current-frontier comparison.
- The choice uses family independence, ungated access and fit within this
  48GiB laptop. No candidate model has been selected using study outputs.
- BF16 Apple MPS, eager attention, batch one, explicit unpadded all-ones mask,
  cache disabled, fixed seed 20261012, maximum input 4096 tokens. No truncation.
  All cells run regardless of DEV results; no prompt or parameter selection.
- Complete response strings must form a canonical one-token continuation.
  Before inference the tokenizer selects the first valid prefix in `""`, `" "`
  across ALL task packets. Mistral requires leading-space code strings at its
  native assistant boundary; Qwen uses bare letters. This choice depends only
  on token boundaries, not model likelihood or correctness. Record exact
  candidate strings and IDs. No greedy rationale generation is used.
- Downloaded weights remain ignored. New tokenizer dependencies are separately
  pinned; the original runtime and RDF lockfiles remain unchanged.

## Three fixed review arms

- **legacy:** original baseline (OLD/NEW-only) binary and joint prompt content.
  This is a measurement bridge to the original pilot, not a replication of the
  selected-profile/sham intervention. Qwen3 can additionally be checked against
  its saved exact original baseline packets/scores.
- **raw:** the same theories and current regression, with explicit existential
  wording and binary legend printed in A/B order. This counterbalances meaning
  position across code-balanced cases. The joint four-code mapping is unchanged.
- **verified:** exactly the raw request plus a complete table of 16 future seed
  profiles, with OLD/NEW derived protected head, consistency and effective
  eligibility. The table is computed from the exact displayed versions and
  independently crosschecked by OWL-RL. It supplies derived facts, not an
  aggregate expansion/admission verdict. It supplies NO approval or runtime grant.

The primary paired comparison is **verified versus raw**. Legacy/raw changes
wording and binary legend order together; it cannot isolate either mechanism.
The verified intervention changes available information and delegates deduction
to an external reasoner. A benefit would not establish improved unaided LLM
reasoning, a novel formal verifier, or real-world containment.

Each pair has one binary semantic question and seven joint questions, using
the original approval modes and exact simulated mandate. Thus each arm has
four DEV and 24 TEST semantic rows, and 28 DEV and 168 TEST joint rows.
Raw/verified/legacy arms are interleaved within each task.

## Single-ontology reasoning controls

For each pair, use both ontology versions and both selected/nonseparating seed
profiles. Ask separately whether the protected head is (a) positively derived
before inconsistency gating, and (b) effectively eligible after the declared
fail-closed gate. Prompts contain just one theory and seed context, without
version/selected/sham identifiers, approvals or cached gold/oracle receipts.

Every underlying question is asked with BOTH A/B meanings. The legend is always
alphabetical. There are 224 underlying questions per model (32 DEV, 192 TEST)
and 448 scoring rows (64 DEV, 384 TEST). Question types and profiles repeat
the same ontology structures; these are not independent samples.

TEST positive fractions before code repetition are 24/96 for derivation and
22/96 for effective eligibility. Always NO therefore has misleadingly high
ordinary accuracy. Report sensitivity, specificity, balanced accuracy, raw
counts, and same-question agreement across the two code encodings.

For interpreting capability (not selecting models or terminating runs), declare
80% balanced accuracy and 90% encoding agreement in BOTH control types as a
pragmatic competence screen. These thresholds are conventions, not population
significance tests. Failing controls limits revision-specific interpretation.

## Outcomes and reference baselines

Each model has 160 DEV and 960 TEST readouts, 1120 total; two models give 2240.
There are only 24 TEST pairs in six motifs. Every fixed cell is reported.

Primary outcomes: binary protected-expansion correctness; joint admission
correctness; unsafe activation among 72 forbidden opportunities and unnecessary
HOLD among 96 admissible opportunities. Report paired rescues and harms for
semantic, joint and admission outcomes, by motif where useful. No IID confidence
interval treats repeated arms, approvals or encodings as independent cases.

A promising *review* result requires semantic and admission accuracy to increase
under verified facts, with neither unsafe activation nor unnecessary holds
increasing. Report model-specific and mixed outcomes even if this criterion
fails; no arm becomes a replacement for the original primary result.

Secondary component baseline: combine the separately measured model binary
semantic judgment with the exact simulated approval validator. This removes
LLM approval interpretation and quantifies its effect without changing the
semantic predictions. The finite reasoner plus exact approval rule gives the
constructed reference outcomes by design. Neither reference is a novel method.
Trusted provenance remains a separately controlled simulator input, not JSON
authentication, signature verification or a production authorization service.

## Integrity and reporting

Before any task inference, freeze source/data/materialization/certificate hashes,
checkpoint artifact hashes, dependency versions, and every tokenized task packet.
Check certificate bindings to both ontology versions, protected query and complete
seed basis. Cached serialized gold, family and oracle metadata cannot enter the
model request. Binary and joint semantic codebooks remain balanced within the
original test strata; every local truth is balanced across code letters by repetition.

Save complete per-code full-vocabulary log probabilities, unrestricted top token,
allowed probability mass, last-logit hash, exact prompt/token hashes, decoded
judgments and all summaries. A separately implemented CPU audit replays closure,
ratification, coverage and arithmetic. Saved receipts do not externally attest
model execution or independently reproduce GPU logits.

The follow-up stays private. The existing editor source may be revised only
after all outcomes and limitations are available; preserve the original primary
tables and label follow-up results explicitly post hoc.
