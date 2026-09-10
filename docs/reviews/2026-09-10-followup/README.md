# Evidence for the follow-up to Fable

Recorded on 10 September 2026 for the [follow-up response](../soil-twin-audit-followup-2026-09-10.md). Source: audit branch HEAD `509c3c6f6bc7b58f6af0f219943c88e6a9025cd0` plus Fable's uncommitted fixes. These files supplement the [original audit bundle](../2026-09-10-audit/README.md); historical outputs were not overwritten.

## Read first

- [Automation findings](automation/review-findings.md) and [panel-contract acceptance checklist](automation/panel-contract-checklist.md).
- [Dependency and sequencing review](dependencies/dependency-and-plan-review.md), [proposed registry](dependencies/typed-dependency-registry.proposed.json), [160-issue coverage](dependencies/issue-review-coverage.json) and [graph checks](dependencies/validation-summary.json).
- [Bibliography findings and all 107 entry dispositions](bibliography/bibliography-review.md), with [normalized primary evidence](bibliography/bibliography-entry-dispositions.json).

## Source and live-state evidence

| File | Meaning |
|---|---|
| [review-target.json](review-target.json) | Reviewed HEAD and exact hashes of Fable's inputs. |
| [fable-reviewed-changes.diff](fable-reviewed-changes.diff) | Tracked runner, grouper and documentation changes relative to that HEAD. |
| [test_group_issues.reviewed.py.txt](test_group_issues.reviewed.py.txt) | Snapshot of the new, uncommitted hold-label test file. Text suffix prevents duplicate test collection. |
| [fable-response-reviewed.md.txt](fable-response-reviewed.md.txt) | Immutable text snapshot of Fable's response; internal links are preserved as source text. |
| [protect-main-ruleset-prepared.json](protect-main-ruleset-prepared.json) | Snapshot of the proposed, unapplied API request. |
| [effective-main-rules.json](effective-main-rules.json), [live-protect-main.json](live-protect-main.json) | Fresh read-only GitHub responses: effective rules remain empty. |
| [issue-163-relevant-comments.json](issue-163-relevant-comments.json), [park-commit-api.json](park-commit-api.json) | Scope/status and invalid-review park comments; candidate SHA lookup returns 422. No deployed runner manifest was found in inspected artifacts. |
| [landlab-interface.json](landlab-interface.json) | Ten input fields, units and source positions extracted from a pinned upstream component, with source URL and hash. No adapter execution. |
| [evidence-manifest.json](evidence-manifest.json) | SHA-256 digest of every other file in this evidence directory and the main follow-up response. |

The ruleset was not applied. No live issue, label, PR or deployment was changed. The registry uses the original audit's issue snapshot; it is a scoped proposal, not a fresh full issue crawl or an executable scheduler. Its 125 edges classify all 24 existing hard-coded edges but do not exhaustively normalize the entire research program.

## Verification and limits

The existing Python 3.11.15 environment passed [36 automation tests](automation/automation-pytest.txt), including [four new tests](automation/group-issues-tests.txt); shell syntax passed. The [automation manifest](automation/manifest.json) identifies tested source hashes. This is not evidence of a clean-checkout installation.

The archived [automation rerun](automation/automation-working-tree-repros.json) changes only the held-issue result, as shown in the [comparison](automation/baseline-comparison.json). The [capillary rerun](automation/capillary-working-tree-repros.json) is unchanged. These old probes mix direct production-helper calls with a short control-flow illustration; they do not establish full runner acceptance.

The new [science-gate results](automation/science-gate-results.json) and [final-convergence results](automation/convergence-results.json) execute verbatim extracted production shell functions with offline substitutes for external calls. They demonstrate eight gate cases and five convergence cases, including positive controls and surviving defects. The [schema probes](automation/schema-probes.json) add direct validator cases. The portable harnesses were rerun from outside the repository, with identical case results and rejection of nonempty output directories ([portability verification](automation/portability-verification.json)). They do not execute the complete queue.

The [hypothetical capillary debit](capillary-debit-probe.py) modifies source only in memory; [its results](capillary-debit-probe.json) reveal a remaining signed-recession balance problem. No candidate physics fix was installed.

The bibliography review retrieved all 98 DOI records and assessed all nine non-DOI entries. Saved metadata and dispositions preserve URLs, retrieval dates and normalized hashes without copying large raw provider responses into the repository. [Checker replay](bibliography/existing-checker-cached-replay.txt) and [controlled gap probes](bibliography/checker-gap-probes.json) demonstrate missing author checks and successful exit with all metadata unavailable. Bibliographic identity is not scientific claim verification; unresolved records are reported explicitly.

## Reproduce locally

From the repository root, with the reviewed source state and existing environment, these commands are offline and leave existing evidence untouched. Harnesses choose fresh temporary output directories and report their locations. They need `bash`, `jq` and the repository's Python dependencies. The original scripts print results to stdout; preserve new outputs under a new path when comparing another revision.

```bash
.pixi/envs/default/bin/python -m pytest -q scripts/gaia-launch/tests
bash -n scripts/gaia_run_queue.sh
.pixi/envs/default/bin/python docs/reviews/2026-09-10-audit/automation-main-repros.py .
.pixi/envs/default/bin/python docs/reviews/2026-09-10-audit/reproduce_capillary_mass.py .
.pixi/envs/default/bin/python docs/reviews/2026-09-10-followup/automation/science-gate-harness.py --repo .
.pixi/envs/default/bin/python docs/reviews/2026-09-10-followup/automation/convergence-harness.py --repo .
.pixi/envs/default/bin/python docs/reviews/2026-09-10-followup/capillary-debit-probe.py .
PYTHONDONTWRITEBYTECODE=1 .pixi/envs/default/bin/python docs/reviews/2026-09-10-followup/bibliography/replay_metadata_gate.py --repo .
```

The probes intentionally expose failures; a zero harness process exit means the experiment executed, not that the production behavior passed the proposed contract. The archived capillary probe additionally asserts that its historical counterexample still exists and should fail after a successful physics repair. The hypothetical debit probe requires the exact old source line. Cached bibliography replay performs no new network verification and must not be presented as a fresh retrieval.
