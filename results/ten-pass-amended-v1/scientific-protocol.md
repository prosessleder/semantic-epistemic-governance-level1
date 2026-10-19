# Scientific protocol and interpretation

## Cohorts and execution

Six configurations each received 48 semantic DEV cases and 96 epistemic DEV
packets in ten fresh repetitions: 8,640 planned scored generations. Historical
single-pass, eleven-model feedback, two-model source-evidence and interface
cohorts are excluded from these denominators. The 150 retained reference cases
also include three TRAIN interface cases per track; these are checked offline
but are not ten-round accuracy observations.

All configurations requested native medium reasoning and 32,768 combined
reasoning/output tokens with their original model/provider and prompt settings.
There was no feedback, answer repair, majority vote, best-answer choice or
correctness retry. Exact request hashes, settings, cases, source bindings and
slot orders are retained in execution plans. A shared label/token cap does not
establish equal realized compute.

The original experiment used four disjoint execution legs. Scheduling changed
from the initial arrangement to independent model queues, with at most four
requests per model and 24 overall. The later recovery legs admitted only exact
never-attempted complements, preserving all prior deliveries and unknowns.
Original round labels do not denote simultaneous model sessions. Ten transport
outcomes remained unknown. Three explicit transient HTTP failures received the
allowed identical retries; their full failure reserves remain recorded.

After the original experiment closed, ten fresh generations were collected in a
separate follow-up namespace: four Qwen (one semantic, three epistemic) and two
epistemic each for Terra, Luna and Haiku. Original bodies/settings/scorers were
retained; received answers were never replaced. All ten follow-ups delivered,
with no new transport loss or transient retry. The amended projection maps them
to the ten previously missing original case/model/round identities while keeping
both attempt histories. Later timing/load and missingness may violate generation
exchangeability. There were 8,653 closed attempts across the two namespaces.

## Outcomes and dependence

Strict typed bare JSON is primary. A separately labeled sensitivity removes only
a sole outer fence; it performs no prose extraction, interior repair or fact-order
relaxation. Delivered malformed, schema-invalid, filtered, provider-error or
length-limited outputs are observed outcomes. An unknown transport outcome is
missing rather than a fabricated answer. Provider/filter/length/format losses
remain separate from demonstrated completed task errors. The two tracks are not
pooled into an overall model ranking.

Semantic DEV has twelve underlying groups: six with six cases and six with two.
Epistemic DEV has twelve units with eight correlated packets each (four matched
authority/provenance conditions and two orders), comprising 224 actions per
repetition. Repetition creates no new independent task units.

## Statistical estimands

For complete model-tracks, report all ten round rates, their mean, sample SD and
range, and per-case success counts out of ten. The fixed-corpus generation
interval resamples the ten generations within each case, using 20,000 draws and
seed 2026101803. It describes conditional generation variation on this fixed
corpus and assumes within-case exchangeability; time/provider/load dependence
can violate that assumption.

A distinct unit-resampling sensitivity uses 20,000 draws and seed 2026101804,
keeping all variants and rounds from a sampled unit together. Both case-weighted
and unit-weighted estimands are retained. These conditional percentile intervals
are not interchangeable or population guarantees. All fifteen within-track
pairwise contrasts are exploratory; no significance-selected ranking is claimed.
The frozen statistical algorithms and JSON key normalization are unchanged.

Original-primary incomplete tracks retain null full-ten summaries and intervals.
Their observed round counts remain available without denominator repair. All
twelve amended model-tracks are complete, including five whose full-ten summaries
exist only in this explicitly post-hoc amended dataset. This does not amend the
original completion claim. All-success conditional intervals do not establish
perfect reliability on new tasks.

## Resources and reproducibility scope

Reported complete charges across original and follow-up attempts total
USD134.006024705. Full failed/unknown reservations of USD1.947109186 are retained,
giving USD135.953133891 exposure under the same USD200 cap. Follow-up complete
charges total USD0.167018389. Reservations are not asserted actual billing.
No account/cap increase was needed. Per-track token, latency and completion-time
summaries are in the resource CSV; latency is not pure model reasoning time.

The study concerns inspected synthetic DEV constructions and supplied finite
governance rules. It does not establish held-out generalization, real source
reliability, a causal effort effect, equal time/compute, feedback effectiveness,
autonomous release behavior or general containment. Independent implementations
check the finite references, not the adequacy of a real authority policy.

The portable package verifies final projections, original scores, mappings,
partitions, declared billing and the entire original and amended statistics.
Native HTTP/reasoning/partial/error bodies remain private; their proof hashes
are provenance links, not an independent portable HTTP-authenticity audit.
Private operational documents are excluded. Scientific payload bytes are retained;
curated metadata and the single host-path redaction are explicitly declared.
