# Separately frozen native-Boolean diagnostic

12 October 2026. Mistral development controls in the frozen robustness run
showed answer changes under code reversal. While its TEST run continued, this
diagnostic was declared before observing ANY native-Boolean model output.
It is post hoc, reuses all 4 DEV and 24 TEST pairs, and is not confirmation.
The complete coded experiment continues unchanged, regardless of its outcomes.

## Endpoint and approach

Use the same two pinned Qwen3/Mistral checkpoints and BF16 MPS execution settings.
Remove the letter codebook from raw/verified semantic and single-ontology
requests. Ask for a native Boolean answer field. Teacher-force the partial
assistant JSON prefix `{"answer":` at each model's published assistant boundary.
Score the complete lexical values `true` and `false` as canonical one-token
continuations. Select whitespace only through all-packet tokenizer checks,
never likelihood or task correctness. Retain unrestricted top tokens, both
word likelihoods and allowed probability mass.

This scores a field value AFTER a forced prefix. It does not generate a whole
JSON response, assess format compliance, produce a rationale or verify a proof.
Native/coded endpoints differ in instructions, lexical answers and prefill
together; an effect does not isolate a causal letter-codebook mechanism.

The native raw/verified comparison retains the same underlying theories and
question; the verified arm adds only the independently checked 16-profile
reasoner facts. Those facts are information assistance, not release approval.

For release admission, combine each native semantic judgment with the exact
simulated approval validator over the seven original modes. This is a
decomposed, tool-assisted approach: the model judges expansion, and a deterministic
component handles the declared approval match. It does not test the model's
own approval interpretation or execute any release or autonomous operation.

## Fixed coverage and interpretation

Each pair supplies two global semantic questions (raw/verified) and eight local
questions (OLD/NEW x selected/sham x derived/effective). There are 280 forwards
per model, 40 DEV and 240 TEST, giving 560 total. Native local questions have
no code-reversal duplication: 96 TEST contexts per query, 192 local questions
per model. Positive counts remain 24/96 derived and 22/96 effective.

Report all-case semantic correct/missed/spurious, sensitivity/specificity and
balanced local accuracy, matched raw/verified rescues/harms, and pipeline admission
correct/unsafe/unnecessary-HOLD counts. Reuse the pragmatic 80% balanced-control
screen as an interpretation aid, never as model/prompt/arm selection. There is
no independent-sample population test over repeated motifs/approvals.

Every frozen arm is reported even if worse. No endpoint replaces the original
pilot or the complete coded follow-up. Fresh data, independent natural-language
encodings and actual deployment controls remain separate future work.

Freeze parent/source/model/data/tokenizer/settings bindings before native
inference. CPU auditing reuses the separate independent closure implementation
and explicitly recounts primary outcomes. It is not numerical GPU replication
or external execution attestation. Store all records privately and retain
the original unchanged study artifacts.
