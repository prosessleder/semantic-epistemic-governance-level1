# Fresh ontology-evolution robustness evaluation

This follow-up is designed after the exploratory 32-case and twelve-case pilots.
It supplies new generated instances, not independent discovery of the research
idea or a preregistration in an external registry. Freeze every dataset, prompt,
model input, checkpoint, source and operating point before benchmark inference.
Preserve previous scores. Keep research and raw records private.

## Dataset and separation

- 48 DEV cases and 192 TEST cases: twelve motifs, four DEV and sixteen TEST each.
- DEV chain lengths 1–3; TEST lengths 4–6. DEV has four/five public seed types;
  TEST has five/six, requiring 32/64 combinations instead of the earlier sixteen.
- Rotate the protected query across all four fixed permission heads. Each
  contract still governs one query; this is not simultaneous multi-query safety.
- Generate varying dependency chains, cycles, two/three-way conjunctions,
  existing protected-permission backgrounds, conflicts, branches and negative
  goals. Exclude duplicated context-connected WL fingerprints and duplicated
  profile/permission/goal truth tables across the splits. Also exclude the
  earlier 44 cases' structural fingerprints. WL equality is conservative grouping,
  not a complete isomorphism algorithm or proof of logical novelty.
- Before model inference, a benchmark-design review found that single-actor
  positive goals could allow a direct shortcut to a permission gateway without
  using the shared ontology structure. Preserve all version-one data, CPU checks,
  inventories and source snapshots under `runs/*-v1-preinference`. Version two
  requires every achievable edit to serve two independent actor cohorts through
  a shared classification; strict conjunction goals also preserve all proper
  subset negatives for both cohorts. Single-cohort shortcuts fail regression
  controls. Rebuild and revalidate all data and token inventories before any
  model generation. No new model outputs informed this refinement.
- Motifs: mission/protected chains, strict mission/protected conjunctions,
  permission contraction, conflict repair, latent pair/triple/cycle/repair,
  nonexpanding conflict decoys and impossible empty-seed goals.
- Impossible goals have no legal single-edit solution because positive rules
  require nonempty antecedents and the profile has no seeds. Correct abstention
  is scored separately. TEST edit utility has denominator 176 achievable cases;
  sixteen impossible controls are a separate endpoint.
- Fix 48 paired descriptive-name variants of TEST cases, four per motif, selected
  by deterministic task-ID hash. Names such as ApprovedRole confer no approval.
  Verify complete OLD/NEW permission-table congruence under the bijection. These
  are paired perturbations, not another 48 independent ontology instances.

## Model endpoints

Primary: all four previously pinned checkpoints, native direct mode, identical
case contents, 96 output tokens, JSON assistant prefill, greedy BF16, eager
attention, batch one, MPS, seed 20261013 and maximum 4096 input tokens without
truncation. Use the original isolated runtimes for older and newer checkpoints;
record each runtime's complete versions. No remote repository code or inference
API is used. Every model gets 48 DEV + 192 TEST + 48 paired alias requests.

Secondary: Gemma's fixed native-reasoned endpoint on the same 48 hashed TEST
subset, 2048 output tokens, no prefill, completed native final channel and sole
JSON fence normalization. This interface was chosen from earlier evidence before
new TEST outputs. It jointly changes mode, prefill, instruction and budget; do
not infer isolated reasoning efficacy or equal-budget model superiority. Qwen3.5's
known capped reasoned endpoint is not rerun. There are 1200 fresh-case model calls.

Tokenizer preflight found that Mistral's official assistant continuation inserts
a separator omitted by manually concatenating the JSON prefix. Before inference,
use the native `continue_final_message` text and tokenization for every direct
endpoint. Preserve the failed preflight and earlier inventories, verify that the
other three models' input inventories remain unchanged, and add 32 original-case
Mistral replays with unmodified historical messages and the same 96-token budget.
This diagnostic changes the assistant boundary only; it is not fresh test evidence
or a replacement for the original 0/32 result. Provisional scheduled calls: 1232.

The native continuation API also omits this Mistral template's separate system
message when the final message is assistant content. Preserve the original system
instruction by merging it with the first user message using the template's normal
system/user separator. Assert that the full system instruction is present in every
rendered request. This reproduces the original instruction text while retaining
the native assistant separator. Record character/token differences explicitly;
do not attribute earlier failure to the boundary without the paired diagnostic.

Final pre-inference resolution: all 32 canonical historical prompt hashes and
input-token hashes match the original Mistral inventory, whose stored assistant
prefix already contains the separator. Preserve this complete packet parity
receipt and cancel the identical replay before any new model generation. The
earlier 0/32 result remains correctly bound. Final schedule returns to 1200 calls.

DEV is for execution/transport diagnostics, not selecting a winning model or
discarding hard TEST cases. No prompt, budget, model selection or primary scorer
changes after seeing benchmark outputs. Any necessary implementation correction
gets a preserved incident receipt and refrozen plan; if TEST-dependent, label the
affected evidence exploratory and obtain fresh cases for confirmation.

## Comparators and metrics

Compare goal-only admission; current-plus-goal profiles; every profile of size
at most two plus current/goal probes; a syntactic dependency-cone flag including
consistency dependencies; and complete finite-signature review. Every valid
candidate is replayed under all nine authority modes. Count distinct useful
expanding proposals separately from repeated approval observations.

Report applicable edit delivery, all-goal utility, correct impossible abstention,
caps, invalid edits, protected expansions, missed off-probe/triple witnesses,
unauthorized admissions, unnecessary holds, useful authorized admissions and
latency. Positive controls prevent constant rejection from counting as success.
Known faulty derived-only and unbound-approval comparators are fault diagnostics,
not realistic complete alternative deployments.

Utility intervals and paired model differences use 10000 task-level bootstrap
resamples within the eleven achievable motif strata, seed 2026101302. They are
conditional on this synthetic generator and fixed motifs, not all tasks, agents
or architectures. Approval modes, aliases and reference patches are never counted
as additional independent model samples. Report subgroup counts without selecting
winners using TEST outcomes.

## Version/composition controls and independent checks

Add 48 new two-edit lifecycle sequences: sixteen pair expansions, sixteen triple
expansions and sixteen nonexpanding controls. Each edit independently meets its
mission and has no protected expansion on the original base. Compare unbound
cached patch-verdict replay, strict stale-base rejection, and properly rebased
complete review with absent/exact approval. These are constructed software/
semantic controls, not new LLM-produced attacks or a new TOCTOU theorem.

Before inference, validate all references with a separate fixed-point evaluator,
check immutable heads/vocabulary, all input token hashes and the structural/
semantic separation. Crosscheck each base/reference candidate with OWL-RL/SHACL.
After inference, independently recount every delivered edit and authority verdict,
crosscheck every valid candidate and replay every immutable commit, including
invalid frames. Use mutation/fault controls to demonstrate that the suite detects
missing triple coverage, ignored consistency and unbound approval.

## Scope and methodological sources

Authorization is an application policy: only entailed permission heads allow an
operation; inconsistent profiles fail closed. This convention is not standard
OWL entailment of negative facts. Vocabulary, input signature, protected query,
mission goals and approval provenance are externally supplied and fixed. Tool
mediation, real identities, autonomous actions, arbitrary OWL, new vocabulary and
physical channels are outside the study. Exact-reference agreement validates the
finite implementation; it is not empirical model reasoning or a solver novelty
claim. Same synthetic motif families remain a generalization limit.

Behavioral capabilities, invariance and negative controls follow the evaluation
principles of [CheckList](https://aclanthology.org/2020.acl-main.442/). Reporting
legitimate utility alongside adversarial failures is consistent with
[AgentDojo](https://arxiv.org/abs/2406.13352). Static synthetic cases are not an
adaptive-agent defense evaluation; [AutoDojo](https://arxiv.org/abs/2606.15057)
motivates keeping that limitation explicit. The restricted RDF crosscheck uses
[OWL 2 RL](https://www.w3.org/TR/owl2-profiles/) and a separate operational gate.
