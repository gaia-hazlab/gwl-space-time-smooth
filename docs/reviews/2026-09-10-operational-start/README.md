# Accepted plan and first work package — 10 September 2026

Marine accepted the two narrow fixes and requested a revised operational plan and
implementation start. The [active plan](../../soil-twin-operational-plan.md) adopts
concurrent scientific work and automation commissioning. Work in this session used
local interactive agents and independent review; no live queue was invoked.

## Delivered scope

- **Accepted fixes:** `98d2c36` contains the repaired `revise` transition and held-issue
  snapshot filter. The [source check](accepted-fix-source-check.json) confirms the
  implementation is byte-identical to the previously tested version. The prior 36-test
  result and focused probes remain applicable; they do not commission the whole queue.
- **D1, partial #204:** updated active Copilot instructions, README product claims,
  roadmap precedence and automation policy. Removed the obsolete instruction to grant
  automation a bypass; marked legacy launch examples uncommissioned. The broader book,
  assumptions register and issue-status reconciliation remain open.
- **B1, partial #25:** corrected exactly eight bibliography entries using the audit's
  recorded primary evidence. Five author records were repaired; Jasechko's issue and
  the linked DNR edition's year were corrected; McKee's erroneous volume/issue were
  removed. All citation keys and DOI values are preserved. No issue was closed.

## Evidence and review

The [review record](review-record.json) names actual local reviewer tasks, records
candidate-file hashes, and preserves D1's initial revision verdict and subsequent
acceptance. The two raised concerns were misleading README capability claims and
obsolete queue/bypass guidance; both were resolved and re-reviewed. The operational
plan also received an independent reader's approval.

[Implementation verification](bibliography-verification.json) checks the eight changed
records and preservation of unrelated text. [Independent Pandoc verification](bibliography-pandoc-verification.json)
converts both baseline and candidate BibTeX to CSL JSON, checks all 107 entries, verifies
99 unchanged entries and 98 unchanged DOI values, and compares every author in the five
changed lists with the saved primary records. The other three field corrections pass.
The normalized primary-source evidence remains in the [original bibliography review](../2026-09-10-followup/bibliography/bibliography-review.md).
No source metadata was guessed for the unresolved manuscript or software citation.

Verification used the installed Pandoc, with:

```bash
pandoc docs/references.bib --from=bibtex --to=csljson --output=/tmp/references.csl.json
git diff --check
```

The recorded comparison also parses the bibliography from base commit `98d2c36` and
checks the exact changed-key set and saved author sequences. The metadata checker was
not treated as an integrity certificate: its fail-open lookup behavior remains open.
No model/numerical implementation changed, and no full book execution or fresh
bibliography network crawl was needed for this scoped patch.

## Current GitHub state

[Read-only observations](github-state.json) record endpoint URLs and retrieval times.
The [effective-main rules](effective-main-rules.json) now contain the five expected
types. The [ruleset](protect-main.json) targets `refs/heads/main` and still lists the
human pull-request bypass. #25 is open; #163 and #186 are open and held. The earlier
audit's empty-rule snapshots remain unchanged as historical evidence.

Remote scheduler state and deployed credentials were not inspected. These reads and
document approvals do not authorize live queue operation, release holds, or certify
hazard readiness. Human PR review and full-issue acceptance remain separate next steps.
