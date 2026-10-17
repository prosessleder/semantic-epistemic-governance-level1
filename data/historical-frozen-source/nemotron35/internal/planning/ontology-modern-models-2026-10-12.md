# Modern-model replication of checked ontology proposals

Exploratory follow-up requested on 12 October 2026. It reuses the 32 fixed
proposal tasks and their reference patches from the completed division-of-work
experiment. These cases are not new held-out confirmation. No outcome-driven
prompt search, training, semantic repair, retries or best-of selection is used.
Earlier model runs and all frozen sources remain unchanged.

## Models and local execution

- Qwen/Qwen3.5-4B, revision 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a.
- google/gemma-4-E4B-it, revision ee0ef6023621cff504d758262d4e04895a5af4a2.

Public weights are downloaded into an ignored private run directory. A separate
environment uses modern Transformers and PyTorch, with exact installed versions
recorded before inference. Use full BF16 weights, eager attention, batch one,
greedy decoding, seed 20261012 and one loaded model at a time. Input limit is
4096 tokens, without truncation. Local MPS execution is attempted first; any
compatibility failure, fallback or change to runtime is recorded explicitly.
No remote inference or downloaded repository code is executed.
Public immutable HF LFS SHA256/size records may pin weights before the second
download finishes. All actual checkpoint files must match their frozen hashes
before that model is loaded; neither requests nor source choices depend on the
other model's output.
Runtime preflight amendment, before any benchmark generation: stream checkpoint
hashes to keep host memory bounded and explicitly move the loaded BF16 model
to MPS, verifying every parameter's device. Direct device-map loading produced
native process aborts/segfaults in non-benchmark diagnostics. Their root cause
has not been isolated; preserve the first frozen plan and failed attempt log.

## Fixed endpoints

1. **direct**: unchanged proposal instructions, native template with thinking
   disabled, followed by the partial assistant object `{"op":`. Cap 96 generated
   tokens, as in the prior experiment. Stop at the first complete framed object.
2. **reasoned**: the same ontology, goals and operation schema, with native
   thinking enabled. The final instruction permits private reasoning and asks
   for a single final proposal object. No partial JSON prefill. Cap 2048
   generated tokens including reasoning. Stop at the first complete object in
   the final response channel. This jointly changes reasoning mode, framing,
   output allowance and the final output instruction; it is an interface
   comparison, not an isolated causal effect of reasoning.

All 32 proposals are run in each endpoint for each model (128 generations).
Additionally, each model answers both derived and effective questions on all
16 existing micro reasoning controls, using the direct endpoint's Boolean
object prefill and 96-token limit (64 control generations). Controls are scored
and reported separately; they never change the proposal prompt or admission
policy. Total planned benchmark generations: 192.

Non-benchmark transport smokes may check a fixed color JSON response in each
endpoint, capped at 256 tokens. They are compatibility checks, not reasoning
or proposal-efficacy measurements. Freeze all benchmark request tokens and
source hashes before any model generation. Preserve attempted runtime errors.
Before the first benchmark request, clarify the execution gate: both smoke
generations must execute and produce tokens, but correct color JSON is not a
model-selection criterion. Qwen's direct color output succeeded and its native
reasoning output was incomplete at the smoke's 256-token cap. Preserve both;
do not alter either benchmark endpoint or its already-declared token allowance.

## Framing and analysis

Only terminal EOS/padding tokens may be removed from decoded output. In Qwen's
reasoned endpoint, require the native closing `</think>` delimiter and take its
following content. In Gemma's reasoned endpoint, remove an initial complete
`<|channel>thought` block ending with `<channel|>`; an immediate JSON response is
also allowed. Do not search reasoning text or explanatory prose for a convenient
JSON object. Leading final-channel whitespace is transport only. The first
object begins at offset zero and duplicate keys are rejected. Schema validation,
immutable permission policy, mission goals, finite closure, approval binding
and commit checking are exactly those of the earlier experiment.

Record every prompt hash, token hash, generated token sequence, raw response,
final frame, parse error, token cap, elapsed time and semantic decision. Invalid,
abstained, incomplete or unmet-goal proposals remain failures in the denominator.
Replay every proposal across the same nine authority scenarios and through the
immutable commit-frame adapter; these are repeated simulator observations, not
independent model generations. Independently recount edits, goals, closure and
authority, and crosscheck valid candidates with OWL-RL/SHACL. Constructed reference
patches remain software controls, not model success.

Report both endpoints without picking a winner post hoc. Results cannot establish
deployment containment, production identity verification, model-family-wide
capability, or causal attribution to release age. No new manuscript claim is
made before completion and audit.
