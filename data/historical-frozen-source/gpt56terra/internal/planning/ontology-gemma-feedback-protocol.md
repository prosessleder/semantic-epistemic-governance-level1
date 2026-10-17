# Improving Gemma ontology proposals with execution feedback

Gemma proposes edits and receives computed execution facts. The experiment tests
whether this workflow improves completion of all requested goals while retaining
the complete permission checker and exact approval requirements. A useful
expanding proposal can be correct: protected expansion requires matching approval.

## Development selection

Development uses the first two instances of each motif from the earlier DEV set,
24 cases with 22 achievable tasks and two impossible controls. The original TEST
outputs motivate development but are not the fresh evaluation. Preserve all
three attempted configurations, their frozen sources, output tokens and audits.

| Development configuration | Achieved goals | Correct impossible abstentions |
| --- | ---: | ---: |
| First execution feedback workflow | 16/22 | 2/2 |
| Additional shared classification guidance and challenged abstention | 16/22 | 1/2 |
| Readable diagnostics and explicit empty profile certificate | 15/22 | 2/2 |

The highest total of goal completions plus correct abstentions selects the first
workflow. Its proposer and tests are restored byte for byte from the frozen first
development source. The TEST preparation verifies its source hash and all 24
initial development prompt and token hashes against the selected inventory.
Development outcomes are exploratory and are excluded from holdout estimates.

The third configuration's original readable formatter used Python dictionary
representation, while record serialization sorted keys. Its first prompt audit
failed on a revision request. A declared post-inference audit adapter reconstructs
the original proposal key order from raw responses and tokens. The recovered
audit verifies exact prompt hashes and semantics without changing outputs or
scores. This adapter and the failed audit remain in the archive. The selected
first workflow uses canonical JSON feedback and passed its original audit.

## Fresh paired evaluation

Freeze 192 fresh cases, sixteen from each of the twelve existing motifs: 176
achievable and sixteen impossible. Use previously unused TEST slots 16 through
31. Exclude structural and semantic fingerprints from the earlier DEV and TEST,
and structural fingerprints from original pilots. Equal WL hashes are excluded
conservatively; hashing is not an isomorphism theorem. Keep TEST chains of four
to six steps. This is a new instance holdout within known synthetic motifs.

The corpus increased from the initial 96 case plan to 192 before TEST generation
or outputs, matching the earlier study size. The paired design and motif
proportions stay fixed. The TEST plan binds the selected audited development
summary, source hashes, input data, checkpoint, token inventory and settings.

## Selected proposal workflow

Use the pinned Gemma 4 E4B checkpoint with BF16 eager MPS inference. No training,
candidate search, reference edit, family label or expected answer is available to
the proposer. Each attempt operates on the ORIGINAL ontology in its case.

The revised input supplies calculated states for each goal profile before any
edit, distinguishes seed vocabulary from supplied facts, states the general
empty-profile obstruction, reminds the model about immutable permission heads
and conflicts, and requests a brief explanation and proposed edit in a strict
JSON envelope. Explanations do not establish correctness or confer approval.
Native thinking is disabled. Allow at most three attempts with 384 generated
tokens each. Preserve malformed, unfinished and unsuccessful responses.

Invalid edits and failed goals receive exact schema errors or computed goal
states. Software does not propose a corrected edit or replace a model answer.
Stop on a goal-satisfying proposal or explicit model abstention, or after three
attempts. Score every abstention against independently established truth; an
abstention on an achievable task fails. The selected workflow does not supply
the later version's per-case impossibility certificate or common-classification
intersection. Its general instruction about empty profiles remains assistance
and limits any claim about unaided model reasoning.

## Comparisons and measurements

Compare the selected workflow with the earlier direct interface on the SAME 192
fresh cases. That baseline gets one attempt and 96 generated tokens. Also report
the revised workflow's first attempt and incremental recovery. Prompting, supplied
execution states, explanation allowance and compute change together. This tests
an engineering workflow, not an isolated feedback effect or intrinsic capability.

Primary utility is goal completion over 176 achievable cases. Report correct
abstentions over sixteen impossible cases separately. Nonexpanding utility is a
yield, not a correctness denominator when expansion is part of a requested task.
Report tokens, calls, wall time, invalid output, goals, expansions and approval
outcomes. Count each task once; attempts, profiles and approval replays are not
independent tasks. Bootstrap the paired completion difference within the eleven
achievable motif strata with 10000 draws and seed 2026101401. Results are
conditional on the fixed synthetic motif distribution.

## Independent verification and scope

Complete review checks every 32 or 64 input profiles and one protected permission
per contract. Replay all nine hypothetical approval conditions. Reconstruct
proposals and feedback from recorded tokens and verify goals and permission
effects using a separate materializer. Crosscheck final applicable candidates
with OWL RL and SHACL and replay immutable commits. An audit does not provide an
independent GPU regeneration or authenticate a deployed approval authority.

Internal notes and experimental receipts remain private. Real agent actions,
unbounded new vocabulary, arbitrary OWL and adaptive attackers remain outside
this finite experiment. External execution feedback is established prior work,
including [CRITIC](https://arxiv.org/abs/2305.11738); the follow-up does not claim a
new general self-correction method. Prompts use the pinned native template and
[Google's formatting specification](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4),
with ordinary conversation messages rather than native function-call syntax.
