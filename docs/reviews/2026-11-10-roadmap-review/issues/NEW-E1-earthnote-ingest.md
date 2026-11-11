# NEW-E1: Ingest the Earthnote event record as a forcing-verification and consequence data source

Milestone: v0.7 Probabilistic nowcast and ensemble forecast. Labels: P1, validation, atmospheric, needs-human-decision.
Needs Maleen Kidiwela's agreement before any work starts.

## Purpose
`maleenkidiwela/Earthnote` (MIT; read 2026-11-10) records, hourly, the 2026-11-07 to 2026-11-15
atmospheric rivers: MRMS rain, HRRR analysis wind, gust and 2 m temperature, every 6-hourly HRRR
and ECMWF IFS forecast run, National Water Model reach flows, SNOTEL and real-time wells, and three
consequence feeds that cannot be backfilled (WSDOT and DriveBC road alerts, utility outage maps,
combined-sewer overflow status). The roadmap has no dated consequence labels at this density and
no kept forecast runs for an issue-time-frozen evaluation (#305).

## Deliverable
`src/data/fetch_earthnote.py` and a data card `docs/data-cards/earthnote.md`: a read-only reader of
the event record into typed tables (`incidents`, `outages`, `overflows`, `reach_flow`, `forcing_index`)
with provenance per row.

## Inputs and conventions
- Quantitative fields come from the raw archive (cluster-side gzip responses) or from a re-fetch of
  the primary source. The public R2 frames are 8-bit display encodings (rain as PNG, reach flow as
  one byte with Q = 0.05 (10^(q/40) - 1) m3/s) and are used only as an index and for cross-checks.
- Every incident row keeps: source feed, source id, first-seen and last-seen snapshot hour,
  reported start and end where the feed gives them, category as reported, geometry, and the raw text.
- Nothing is written to the bucket. Credentials are never requested; the public base URL is config.

## Acceptance
- The reader returns the November 2026 event with row counts per feed stated in the data card, and
  a test pins them against a small committed fixture (first 6 hours).
- Time semantics are explicit: an incident absent from snapshot k+1 "ended within hour k+1";
  first-seen is an upper bound on onset. The data card gives the resulting timing uncertainty.
- Decoding the one-byte reach flow reproduces the raw NWM value within the quantisation step at 20
  reaches, and the card states that step in percent.
- Licence and terms of each upstream feed are listed, with "redistribution allowed: yes / no / unknown".

## Hard blockers
Blocked by: none.

## Advisory
Ask Maleen whether the raw archive can be mirrored to the project bucket (`s3://cresst`).
