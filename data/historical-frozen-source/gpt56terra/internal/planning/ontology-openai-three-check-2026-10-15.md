# OpenAI hosted Three Check continuation

The author requested openai/gpt-6.1-sol, openai/gpt-6-luna and openai/gpt-5.6-terra on 2026-10-15. Live OpenRouter catalog and endpoint metadata establish routing availability. Official model documentation was searched and opened to verify medium reasoning and structured-output support:
https://developers.openai.com/api/docs/models/gpt-6.1-sol
https://developers.openai.com/api/docs/models/gpt-6-luna
https://developers.openai.com/api/docs/models/gpt-5.6-terra

Pin the OpenAI provider tag openai (standard tier), with no fallback or tools. Use explicitly enabled medium thinking, reasoning.exclude false, 8192 combined reasoning/output tokens, and the existing strict native JSON schema of exactly five Boolean/null fields. Omit unsupported temperature. Retain every completed response; never repair content or extract verdicts from reasoning/prose. Hidden reasoning may be observable only through provider token subtotals; distinguish requested and observed delivery. These native format/compute configurations differ from historical prompt-only runs.

Use the same 480 scenarios over 96 previously inspected semantic units, identical messages and evidence, shared initial judgment, independent evidence/reflection branches and externally controlled stop at all-five-field correctness or three total judgments. New model calls do not create a new structural holdout. No model response enacts a commit or creates trusted approval.

Six development calls (three separate cases with a forced evidence turn) check transport, final format and thinking delivery. Require all finals parse and at least one observed native reasoning receipt or mandatory-thinking model metadata. Record actual coverage, not an assertion that every response exposes thought. Changes prompted by development occur before primary freeze and preserve earlier receipts. Freeze all sources and per-run metadata before primary inference. Each model has exclusive launch ownership and separate reporting, so a provider failure does not stop other jobs.

Cost ceilings including development are USD20 for GPT-6.1 Sol, USD5 for GPT-6 Luna and USD20 for GPT-5.6 Terra. Each reserves USD0.50 for development, leaving primary caps of USD19.50/4.50/19.50. In-flight and failed-attempt conservative reservations count against the guards; billing of any lost response remains unknown. Stop at the guard rather than silently increase it. Ceilings are not forecasts or guarantees of completion. Do not change providers or weaken scoring to fit cost.

After completion recompute raw history scores and feedback, replay each independent commit decision, preserve all stages of the four fixed-denominator measures plus all-five correctness, conditional correction, regressions, parse/length failures and reasoning coverage. Report tokens and costs without double-counting reasoning. Hash and credential-check the private receipt archive. The finite checker supplies scoped authorization under trusted inputs, not general legality or arbitrary agent containment.
