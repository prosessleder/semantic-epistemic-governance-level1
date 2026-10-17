# Fixed control-failure diagnostic and checked-computation intervention

Declared after the complete robustness results, before any new diagnostic
model output. Post hoc and exploratory. Old datasets, sources and results
remain unchanged. No causal claim about training, model internals or general
inability follows from these finite tests.

## Evidence motivating the diagnostic

Mistral's coded derivation controls always choose literal A under reversed
meanings. Its native effective controls always choose true. Qwen3 often
predicts a protected derivation without one. Native allowed-value probability
mass is near one, so these failures cannot be explained solely by unsupported
first output tokens. Long opaque names, rule/seed confusion, and inability to
perform composed deductions remain hypotheses. The native direct endpoint
also provides no generated intermediate computation before its answer.

## Fixed inventory

Sixteen new sanity programs cover direct grants/non-grants, forward and
reverse implications, transitive and disconnected paths, complete/incomplete
conjunctions, anchored/unanchored cycles, alternative supports, wrong
permission, active/dormant/irrelevant disjointness and empty seeds. Eight of
sixteen have derived protected heads, six have effective protected heads.
These tiny programs are diagnostic checks, not a new release benchmark or
untouched confirmation.

Separately take the lexical-first original TEST case in each of the six
motifs, both versions and selected/sham seeds: 24 reused single-ontology
contexts. Selection uses only the declared case identifier, never model
correctness. Do not generalize this subset to all original cases.

Each of the 40 contexts has two semantically isomorphic renderings: existing
opaque helper names and H0, H1, ... aliases. Public seeds, permission heads,
rule order, seeds and logic remain identical under the bijection. Report both
groups and both naming conditions; no name version is selected after outcomes.

Each rendering has two direct native-Boolean questions (derived and effective)
and one generated rule-application certificate addressing both questions.
Thus there are 240 requests per model, 480 total: 320 direct one-forward
readouts and 160 bounded generations. Same pinned Qwen3 and Mistral checkpoints,
offline BF16 MPS/eager, batch one, maximum input 4096, fixed seed 20261012.

## Structured computation and checked claims

Direct questions preserve the earlier native local prompt, including forced
`{"answer":` prefix and exact true/false likelihoods. Short/opaque direct
requests differ only by bijective helper renaming. This is the cleanest name
ablation, though tokenization/length differences are part of the intervention.

The trace endpoint explains that declarations are vocabulary, not facts,
numbers the rules, requests complete forward chaining and returns ordered
rule IDs plus native derived/effective Booleans. Teacher-force `{"steps":[`
at the published assistant boundary, then greedily generate at most 160 new
tokens with KV cache enabled. No sampling, retry, output repair, extra example
or outcome-driven prompt refinement. This changes instruction, intermediate
computation and output format together, and therefore cannot isolate a pure
chain-of-thought effect. It does not freely generate the entire object.

A separate deterministic checker starts from seeds only, checks each supplied
rule exists and has every antecedent established, rejects redundant firings,
then verifies that no further rule can add an atom. This proves completeness
within this finite fragment and prevents unsupported negative claims. It
computes derivation and disjointness gating and rejects contradictory final
claims. Invalid certificates yield abstention; they never become no-expansion
or approval. The verifier receives the declared context; a real application
would additionally bind version, input basis and trusted provenance.

## Reporting and stopping

Run every cell on both models regardless of interim outputs. Retain full
continuations, cap/parse failures, raw predictions, checked-certificate
coverage and error reasons. Report all-case correctness, sensitivity,
specificity and balanced accuracy. Invalid formats remain incorrect in the
denominator. Report accepted-wrong count and abstention rather than calling
rejection a successful answer. The 80% balanced control screen is inherited
as a pragmatic reference, not a population significance test.

Record paired naming changes and direct/trace differences as exploratory.
Freeze source/checkpoint/data/request hashes before task inference; preserve
old receipts. No extra variant or model is added in response to results.

The intended engineering improvement is proof-carrying review: the model
proposes a checkable computation or witness, while an exact version-bound
reasoner controls semantic acceptance and a separate policy handles approval.
For no-expansion claims, completeness over the entire declared profile basis
is required. Mere failure to find a witness never authorizes a release.
This division of labor has precedents in LINC, Logic-LM and Faithful CoT;
the diagnostic claims no novel symbolic algorithm or deployed safety guarantee.

Primary research sources consulted: LINC (EMNLP 2023),
https://aclanthology.org/2023.emnlp-main.313/; Logic-LM (Findings EMNLP 2023),
https://aclanthology.org/2023.findings-emnlp.248/; Faithful Chain-of-Thought
Reasoning (IJCNLP-AACL 2023), https://aclanthology.org/2023.ijcnlp-main.20/.
