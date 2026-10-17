# Independent pre-inference audit of the finite release-admission pilot

Local date: 2026-10-10. Machine review timestamp: 2026-10-11 00:49:40 UTC. **No model outputs were inspected by this reviewer.** This audit concerns the saved generator, prompt builders and deterministic local store, rather than empirical model performance. The pilot may proceed within its declared discovery scope; the previously identified profile/codebook shortcuts were corrected before this receipt.

Machine receipt: `runs/ontology-boundary-preflight-review-2026-10-10/receipt.json` (ignored generated artifact), SHA256 `d6aa4e62a025ac51b1e5869d5adb68ead4df374e95c562aff1b3f101c4a6a995`. It captures the inspected source hashes and generated-data hashes below. The experiment owner must freeze its execution plan and tokenizer receipts separately. A later source change requires checking whether this review still covers it.

## What was inspected

Reviewed `src/ontology_boundary/dataset.py`, `internal/benchmarks/ontology_boundary_runner.py`, `internal/scripts/run_ontology_boundary_pilot.py`, `internal/planning/ontology-boundary-protocol-2026-10-10.md`, and corresponding tests. The store implementation and its independent field-complete graph baseline are documented in [the store audit](ontology-boundary-store-audit.md). This reviewer implemented only that store/test pair and research audit files, not the dataset, Horn/RDF engine, prompts, or model runner.

The protected question is whether NEW effective `can_write_metadata` expands relative to OLD over the declared public seed signature. It is not a blanket prohibition on metadata eligibility. The release question permits supported non-expanding revisions and requires exact trusted ratification for expanding revisions. Release ratification does not authorize cross-task information flow; that needs the separate runtime flow grant. These distinctions are stated in the actual prompt and protocol.

## Independent checks and results

The reviewer replayed the serialized rules with a separate forward-chaining routine, without calling `closure` or `compare_ontologies`. It repeatedly applied subclass implications and conjunction rules, tested declared disjoint pairs, and projected effective permissions according to the declared fail-closed convention. This was an independent serialization/fixture check of the same restricted semantics, not a separate proof of that convention's normative legitimacy.

| Preflight check | Result |
| --- | --- |
| Old/new versions over all 16 public seed profiles, 28 pairs | 896 version/profile checks; zero semantic-gold mismatches |
| Current probe `{P0}` | Unchanged in every pair |
| Relevant/sham profiles | Equal cardinality; distinct; sham nonseparating for the protected head |
| Joint prompt mutations replacing gold, oracle, family, IDs, split and diagnostic receipts | All 588 joint packets unchanged; no sentinel serialized |
| Binary prompt mutations and release-field exclusion | All 84 binary packets passed |
| Joint `(motif, relevant profile, sham profile, rotation)` strata | 12 distinct test tuples; each has one expanding and one safe pair |
| Lookup using only that tuple | Maximum descriptive accuracy 12/24 = 50% |
| Correct joint code distribution, each of seven approval modes | A=6, B=6, C=6, D=6 |
| Correct semantic-only code distribution | A=12, B=12 |
| Stale/wrong-candidate hash controls | 56 checks; valid-looking canonical 64-hex hashes, all nonmatching |

Dataset hashes, using the generator's canonical serialization:

- DEV: `d76d8ac0a95858bf1fbefec5d55617655c21f681263721e251d906c961115ba5`.
- TEST: `3dcab8343cba5417ecb028fcb446f3d288cba37318ade518ce174879fcc49363`.

The reviewed generator hash is `ee3bca2b0b2aeec69118a11bb6d07289d9dc8bfde35bbf8c07a3ce852bae2b31`; runner hash is `aadc81e6ada3cad40a81a26ce712d3791da350a108efcdde9208463ca1bb80e3`; protocol hash is `2e4b0e15f26ecd42621448073e6b5e4308735207640b9efbffdf6e7f200cdd7d`. All exact source hashes, including store files, are in the receipt.

The targeted runner test command passed **5 tests in 0.44s** during review. The standalone store test command passed **9 tests in 0.02s**, including operational/BFS agreement across 256 contexts. The generator owner's separate CPU receipt, `internal/research/ontology-boundary-dataset.json`, SHA256 `d636c3994fc3611b99c9d51c4a48bd665dea5c3b54a4e15adacab6cd71d1c09f`, was also inspected: it records 56 old/new versions, 896 matching OWL-RL profile crosschecks, supported syntax conformance and no model-output selection. This reviewer did not duplicate that entire dependency-specific run or execute any model/GPU code. The experiment owner subsequently reported **42 focused tests passing in 17.84s** before inference.

## Corrections completed before this audit

An early draft used base-pair position to rotate codes, yielding unequal gold-code frequencies. The saved draft now has a predeclared slot rotation with six occurrences of each gold joint code in every approval mode. The same rotation remains fixed across matched evidence arms and approval modes for a pair.

An early draft's expanding singleton relevant profiles never used P1, while safe profiles often did. A post-hoc profile-string lookup could classify 17/24 cases. This was corrected with deterministic variant slots: within each motif, expanding/safe counterparts have identical relevant-profile, sham-profile and rotation tuples. Matching the joint tuple matters because balancing its components separately can leave a combined shortcut. Fresh opaque helper names remain distinct across cases. The fix used predeclared slots, not model-success sampling.

The original stale/wrong-candidate hashes were all-zero/all-f sentinels. They are now hashes of actual other ontology versions with one extra dormant nonpublic helper. The model sees only the resulting hash, with the same format as valid records; the exact matcher rejects it. This tests revision identity even when the protected projection happens to agree, not cryptographic authenticity.

A saved runner/dataset constant mismatch was corrected before prompt execution. The added semantic-only task now removes release rule, trusted issuer/mandate/scope bindings, hashes, approval record and proposer text. Its binary codebook is balanced. It supplies the same full old/new theories, current probe and optional future profile as the joint task, so semantic measurement no longer relies solely on the joint output's approval-dependent answer distribution.

## Evidence interface and output interpretation

The additional packet contains seed type names only. It supplies no derived permissions, consistency result, old/new truth values, `witness_found` field, gold answer, category label, template name or case ID. Expanding cases use an oracle-selected minimal support; controls use the edited route's support; sham profiles are nonseparating and have the same cardinality. The selection itself is oracle-assisted and is not being learned or evaluated as a deployable witness generator.

The baseline labeled `diff` in code actually displays the complete OLD and NEW theories, rather than a unified patch. In paper prose, describe it as the **old/new-theory baseline**. Relevant-versus-sham is the stronger evidence comparison because it controls the addition of a similarly formatted future profile. Relevant-versus-baseline measures the whole context-selection intervention. Same cardinality is a useful format control, not proof of equal semantic difficulty.

The model readout is first-token likelihood restricted to declared A/B or A/B/C/D codes. No explanations or autonomous tool actions are generated. Conditional probabilities among those codes are not calibrated authorization confidence, and they do not measure free-generation formatting compliance. The runner retains full-vocabulary code log probabilities and the unconstrained top token to make this limitation visible. A one-token code endpoint does not score an end-of-turn token or longer generated behavior.

Under the declared release rule, NO expansion implies ACTIVATE, so `(NO,HOLD)` is never a gold state; it is an inconsistency distractor. Pure semantic results should come from the separate binary task. Joint semantic bits can vary with approval instructions or the codebook's competing activation choices; report them as joint-task components. Wrong approval on a non-expanding candidate does not require HOLD because that scope does not require approval for neutral or contracting changes.

## Remaining limitations and claim boundaries

The 24 test ontology pairs contain only six construction motifs, with four lexical variants per motif. Templates are held out from the four direct/transitive DEV fixtures, while rule primitives and ordinary subgraphs necessarily overlap. All cases are constructed to preserve the current probe. Snapshot invisibility is therefore a generator property, not measured prevalence of unsafe revisions. The two checkpoints are related Qwen models; any empirical result is checkpoint- and synthetic-task-specific.

The permission projection, seed signature, inconsistency gate and trusted provenance are assumptions of the experiment. All 16 profiles are admitted as modeled future inputs, including profiles inconsistent under OLD. Disjointness repair can restore effective permissions without adding a positive permission entailment. SHACL checks supported structure; neither a SHACL pass nor OWL-RL agreement establishes organizational authority. The bounded oracle is exact only for this declared projection and basis.

The trusted register is a simulator input, not signature verification of arbitrary JSON. Wrong-scope mode alters protected permission/field; model evaluation does not cover every possible issuer, agent, task, delegation or cryptographic forgery. Separate deterministic matcher tests cover additional malformed bindings. A real deployment would need trustworthy issuer authentication and record admission outside candidate/model text.

Old profiles can already be eligible for foreign-visible metadata without any task-flow grant. A no-expansion release screen therefore cannot replace a field-complete runtime monitor. The independent store demonstrates both raw delivery and complete observation mediation for declared body/metadata fields; it omits resource IDs, timing, errors, other metadata types and uncontrolled channels. No claim of real Artifactory prevention or physical channel discovery follows.

The oracle defines the reference outcomes. A perfect oracle score is construction/implementation evidence, not discovery of a superior guard. A future empirical contribution must be result-led: nontrivial and repeatable expansion/admission errors or a useful relevant-profile effect that survives the sham control, with safe-case utility retained. Prior art already establishes semantic difference, all-context preservation, ontology guards, information-flow mediation and independent approval. This preflight supports running the pilot; it does not certify a novel publishable result.
