# Reporting correction: outer code fences

Version 0.2.1-preprint, 19 October 2026, reports complete-answer correctness
after removing a sole outer Markdown code fence. This is the already computed
`framing_sensitivity` view in the unchanged scientific projection. It is now the
main reporting view because a presentation wrapper should not count as a task
error. Version 0.2.0 treated bare JSON as primary and reported this same
normalized view separately.

No model was called again for this correction. No received response, answer
value, case, scorer, request setting, bootstrap algorithm or seed changed.
No response was dropped or correctness-retried. All 480 semantic and 960
epistemic responses per configuration remain in the amended denominators.
Normalization does not extract JSON from prose, repair malformed objects,
reorder facts or change substantive checks. Other parse/schema failures remain
observed failures, separately categorized from completed task errors.

The abstract, headline table, conditional intervals, interval figure and
case-consistency summaries now consistently use the normalized view. All
round/component tables retain their stated parser labels. Both original parser
outputs, strict serialization results and the separately preserved original
8,630-response incomplete cohort remain available unchanged. The ten later
unknown-outcome follow-ups remain separately identified.

| Configuration | Semantic correct / 480 | Epistemic correct / 960 |
| --- | ---: | ---: |
| GPT-6.1-Sol | 480 (100.000%) | 958 (99.792%) |
| GPT-5.6-Terra | 450 (93.750%) | 501 (52.188%) |
| Qwen3.8-27B | 464 (96.667%) | 420 (43.750%) |
| GPT-6-Luna | 341 (71.042%) | 323 (33.646%) |
| Sonnet-5.5 | 149 (31.042%) | 847 (88.229%) |
| Haiku-5.5 | 236 (49.167%) | 700 (72.917%) |

The corrected paper is DOI 10.5281/zenodo.23487873. The preceding deposit,
10.5281/zenodo.23482583, remains the immutable version 0.2.0 record. Both belong
to the existing all-versions DOI 10.5281/zenodo.23482582.
