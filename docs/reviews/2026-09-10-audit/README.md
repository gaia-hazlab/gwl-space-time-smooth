# Audit evidence bundle

Read the [consolidated audit](../soil-twin-system-audit-2026-09-10.md) first.

- `science-review.md`: scientific findings, main-source citations, existing issue mappings and acceptance gates.
- `automation-review.md`: current runner failure paths, safe counterexamples and proposed lifecycle.
- `roadmap-review.md`: issue-family reconciliation and critical path.
- `issue-inventory.json`: all 160 issues, with reviewed dispositions, residual scope and queue position. Values imported from the working inventory remain strings.
- `snapshot.json`: source revisions, counts, live branch-rule responses, input hashes, tests and limitations.
- `issue-source-snapshot.json`: GitHub fields used to reproduce dispatch on the audit date; no issue writes occur.
- `roadmap-queue-simulation.jsonl` and `roadmap-queue-held.txt`: current-main candidate queue and held prerequisites. These are audit outputs, not an approved execution queue.
- `automation-main-repros.py`, `automation-main-repros.json`, `panel-root-probes.json`: isolated current-main control/contract probes and recorded outputs.
- `reproduce_capillary_mass.py`, `capillary-mass-result.json`: the dry-column conservation counterexample and capillary-off control.

The audited main commit is `435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f`. The workspace feature branch has an older base. For reproducibility, supply a separate checkout of the audited commit, with its scientific Python dependencies installed:

```bash
python reproduce_capillary_mass.py /path/to/audited-main-checkout
python automation-main-repros.py /path/to/audited-main-checkout issue-source-snapshot.json
```

Run those commands from this directory. The first script asserts the observed conservation defect as a counterexample; it is not a regression test that should keep passing after the physics is fixed. The second monkeypatches issue retrieval and executes only isolated helper functions, a fabricated transcript and a short control-flow snippet. It does not source the queue runner, call a model, or contact GitHub. Its output documents reachable defects, not historical proof that a bad merge occurred.

The archived scientific suite result was 217 passed with five warnings. The automation suite separately passed 32 tests. The full archive of downloaded main, raw GitHub responses and test logs remains in `/tmp/soil-twin-audit` for this session; this bundle retains durable summaries and focused reproductions rather than duplicating the repository or all public discussion text.

The scientific and automation reviewers checked the consolidated report after synthesis. Their corrections were incorporated: use the already-landed scalable backend for the hydrology pilot, keep remaining anisotropy research conditional, gate seismic assimilation on its proper operator/covariance work, and distinguish fixed diff-size caps from absent declared-plan enforcement.
