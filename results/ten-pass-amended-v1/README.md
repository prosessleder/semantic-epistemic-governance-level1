# Level 1 ten-round post-hoc amended results

This curated publication projection contains the complete amended dataset:
8,630 original received finals plus ten later fresh generations for the ten
original unknown slots. It covers 8,640 planned case/model/round identities.
The original primary experiment remains incomplete at 8,630/8,640. Its ten
unknown outcomes, full failed/unknown reservations and five unavailable full-ten
estimates remain preserved in `primary/`.

No received answer was replaced or selected by correctness. Follow-ups retain
new `followup1--` identities and explicit original-slot links. This is a post-hoc
amended result, not an uninterrupted completed original experiment. See
`scientific-protocol.md` for design, scheduling and inference limitations.

Python 3.12, standard library only; from the repository root:

```
python -B results/ten-pass-amended-v1/replay.py verify
python -B results/ten-pass-amended-v1/replay.py replay
python -B scripts/ten_pass_publication_tables.py check
```

The first command verifies bytes, mapping, coverage, categories and declared
billing. Full replay additionally checks all 150 references and 17,280 strict/
fence scores, then independently regenerates both complete saved statistical
analyses with the frozen algorithms and seeds. No inference or credential is
required. A full replay can take several minutes.

`tables/` contains original-primary and amended round, consistency, component,
tier, native-category and resource CSVs. Blank full-ten fields mean unavailable,
not zero. All percentage columns are explicitly named; SD is in percentage
points. Latencies include transport/system interruption and are not pure
reasoning time. Reservations are conservative exposure bounds, not known bills.

The scientific payload is exact. README/manifests/provenance are curated public
metadata, one non-scientific interpreter host path is redacted, and private
authorization/planning documents are omitted. Every source-byte comparison and
the exact redaction are declared in `provenance.json`. The original private
capsule is unchanged. No raw HTTP, exposed reasoning, private host path or
credential is included. Hash-linked native proofs remain outside portable scope.
