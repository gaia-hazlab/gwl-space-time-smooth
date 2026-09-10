# Response to the soil twin system audit of 10 September 2026

**Date:** 10 September 2026. **Reviewer:** Claude (Fable 5.1), at Marine Denolle's request, as a second reader of [Astra's audit](soil-twin-system-audit-2026-09-10.md) and its [evidence bundle](2026-09-10-audit/README.md). **Checkout reviewed:** branch `docs/soil-twin-audit-and-plan-revision-2026-09-10` at `509c3c6`, which is main `435445f` plus the audit commit. All line numbers below refer to that checkout before today's edits.

Method: read every claim in the consolidated report and the three sub-reviews, then re-derive the ones that matter. That meant reading the cited runner and grouper lines, rerunning the two probe scripts in the bundle, querying the live GitHub rules API, and checking the book passages and JSON metrics the science review cites. Nothing was taken on the audit's word where a check was cheap.

## Verdict on the audit

The audit is accurate. Every P0 mechanism I tested reproduces, the line citations point at the code they describe, and the science findings on storage accounting, the RBPF argument and the head coefficient are correct as written. No fabricated claim was found. Its decision, continue the research but do not scale unattended execution, stands.

Three of the findings were cheap enough to fix today. Two are fixed on this branch; the third, the GitHub ruleset, Marine applied and I re-verified. The rest of this document records what was verified, where the audit should be read with care, what it under-weights, and a re-sequenced plan to take back to Astra.

## Verification, finding by finding

| Finding | How I checked | Result | Status |
|---|---|---|---|
| A1 branch protection | `GET rules/branches/main` and the ruleset, live on 10 Sept | Effective rules: empty array. Ruleset `include` list empty. Classic protection 404. | **Fixed today**: Marine applied the ruleset to main; effective rules re-queried and confirmed |
| A2 revise means proceed | `gaia_run_queue.sh:579` | `[ "$decision" != "block" ] && return 0` | **Fixed today** |
| A3 partial batch closes unstarted issues | Runner lines 1148, 1202 to 1211, 1383 to 1401 | Stop and cost checks only `break`; `batch_failed` never set; closing trailers built from the full batch | Open |
| A4 revision path skips gates | Runner 1604 to 1615 | Only `pixi run test && pixi run check-dois`, then `git add -A` | Open |
| A5 panel contract | `gaia_panel.py` `aggregate`, `normalise_verdict`, `dispatched`; runner 1091 | Empty roster approves; unknown severity becomes minor; dispatch inferred from a tool-use request; convergence ignores `blocking` | Open |
| A6 / AUTO-10 roster cap | `gaia_panel.py` `route()` | `MAX_PANEL = 3`; novelty readers added last and dropped silently; `bug` label never iterated | Open |
| AUTO-06 hold label ignored | `gaia_group_issues.py:176-188`; audit probe; live preview | Grouper excluded only epics and `BLOCKED_BY` | **Fixed today**, with tests |
| AUTO-07 gate integrity coverage | `gaia_gate_integrity.py:39-46, 160-172` | `GATE_PATHS` omits the runner, helpers and personas; bare-bound check flags only raised bounds | Open |
| S1 water creation | Reran `reproduce_capillary_mass.py` on this checkout; read `water_budget.py:215-219, 266-278` | 0.739 mm created; capillary rise credits the root store and never debits `h` | Open, #172 |
| S2 calibration as validation | `data/processed/block_cv_metrics.json` | RMSE 18.49 m, bias +3.54 m, mean R² 0.089, one fold negative | Open |
| S3 RBPF conditional linearity | `04-assimilation.qmd:800-812` | Text claims fixed derivatives make dv/v linear in the hydrologic state with an exact conditional likelihood. That is a per-particle linearization. | Open |
| S4 head coefficient units and sign | `03b-physics-hydromechanics.qmd:88-101` | β is dimensionless by its own definition; `k_sat = -β ρ_w g` has units Pa/m, not 1/m, and is positive for the quoted β ≈ −400 | Open |
| S9 Landlab adapter | `07-hazard-integration.qmd:59` | Chapter says `LandslideProbability` takes `water_table__depth`. Consistent with my knowledge of the component, which takes recharge and builds its own relative wetness. Not re-fetched. | Open |
| S13 stale assumptions register | `docs/assumptions.md:10-30` | 1 km cells, 50 km rule, 150 m screen, GRACE temporal driver, changelog dated `_today_` | Open |
| R1 shifted issue bodies | `gh issue view` 121, 122, 124, 125 | Titles and bodies shifted as tabulated; #124 body equals #125 | Open |
| R4 roadmap vs #100 | `gh issue view 100`; `ROADMAP.md:87` | #100 open under milestone v0.4; roadmap says v0.4 done | Open |
| Copilot instructions stale | `.github/copilot-instructions.md` | Still a 1 km monthly LightGBM pipeline | Open |
| `pillar1_compare.py` missing | `ls src/evaluation/` | Absent; `docs/gaia-conventions.md:220` still cites it | Open |

## Where the audit should be read with care

1. **The A3 reproduction is a re-implementation.** The probe script re-creates the runner's control flow in a short snippet, not the runner itself. The audit says so. My reading of the actual runner confirms the path, so the finding holds, but the acceptance test for the fix must run the real script under a fake `gh`.
2. **Test counts came from the auditor's own pixi environment.** Disclosed in the report. Clean-checkout reproducibility is still #153's job.
3. **Stage 0 front-loads runner engineering.** The audit's execution order puts every A-finding before any science. Marine's real workflow never auto-merges: each PR goes through Copilot and the twin reviewers by hand. Under that policy, A2 through A6 matter only when the queue runs unattended. The audit's own recommendation, supervised draft-PR mode, is the operative control today. The plan below re-sequences accordingly: enforce the policy, fix the cheap items, then do the science corrections, then the runner contract.
4. **A1 alone does not stop the runner.** The bypass actor on the ruleset is Marine's account, and the runner merges with Marine's token. Targeting main makes the rules real for everyone else and for direct pushes, but the runner's `gh pr merge` will still go through as a bypass. The audit notes this under "distinct automation identity"; it deserves its own ticket rather than a clause inside A1.
5. **The August #163 park is an infrastructure failure, not a scientific impasse.** Both sub-reviews say this. It should be acted on: rerun the persona whose verdict came back `None`, and only then decide whether a human call is needed.

## What the audit under-weights

**The bibliography.** The audit did not verify references and says so. It also notes, correctly, that the DOI-resolution check cannot catch a valid DOI attached to the wrong paper. This repository has a history of fabricated entries in `references.bib`. Any "scientific release" gate that omits an entry-by-entry check is incomplete, and the execution table never lists one. It belongs in stage 1.

**Copilot instructions.** [copilot-instructions.md](../../.github/copilot-instructions.md) still describes the 1 km monthly product. That file shapes the Copilot review Marine relies on as her adversarial pass. A stale instruction file degrades the one human-supervised control that is actually in use, so this is more urgent than the "doc drift" grouping in S6 suggests.

**The cheap fixes.** Three of the P0 items were under an hour of work. They are done (or prepared) below. Small, testable corrections should land ahead of the state-machine redesign, not wait for it.

## Changes made today on this branch

Uncommitted at the time of writing; Marine decides how to commit and PR them.

**Runner: only `approve` implements.** [gaia_run_queue.sh](../../scripts/gaia_run_queue.sh), in `science_gate()`. The test at the old line 579 is now `[ "$decision" = "approve" ] && return 0`. A `revise` verdict re-enters the plan loop with the panel's concerns injected, exactly as `block` did, and parks under `needs-human-decision` once `GAIA_PLAN_REVISIONS` is spent. The gate record is keyed `panel-revise` in that case. `bash -n` passes. The three matching lines of [gaia-automation.md](../gaia-automation.md) were updated. This closes A2's first sentence. It does not give the final auditor the panel report or acceptance criteria; that is still open under A2 and A5.

**Grouper: `needs-human-decision` holds.** [gaia_group_issues.py](../../scripts/gaia_group_issues.py) now has `HOLD_LABEL` and skips any issue carrying it, logging `holding back #N ... labelled needs-human-decision` to stderr like a dependency hold. A human removing the label is the only way back into the queue. New tests in [test_group_issues.py](../../scripts/gaia-launch/tests/test_group_issues.py) cover: held and logged; same issue dispatched without the label; hold beats `GAIA_ONLY_ISSUES`; epics still excluded. Astra's probe `real_human_blocked_issues_redispatched` now returns an empty list on this checkout, and the live read-only preview holds #163 and #186. This closes AUTO-06's scheduler half. The runner's separate branch-name PR check (AUTO-08) is untouched.

**Ruleset: applied by Marine, verified.** The body used is at [protect-main-ruleset-target-main.json](2026-09-10-audit/protect-main-ruleset-target-main.json): the existing ruleset with `conditions.ref_name.include` set to `refs/heads/main`, nothing else changed. Pre-checks done before applying: the required status check `test` exists in `ci.yml` and passes on main; there is no CODEOWNERS file, so `require_code_owner_review` is a no-op; the bypass actor is Marine's account, so her own merges keep working through the bypass. Applied and verified with:

```bash
gh api -X PUT repos/gaia-hazlab/gwl-space-time-smooth/rulesets/19355902 \
  --input docs/reviews/2026-09-10-audit/protect-main-ruleset-target-main.json
gh api repos/gaia-hazlab/gwl-space-time-smooth/rules/branches/main | jq '[.[].type]'
```

Output of the second command on 10 September, after applying: `deletion`, `non_fast_forward`, `pull_request`, `required_status_checks`, `copilot_code_review`. If a later PR of Marine's refuses to merge from the CLI, the web merge button offers the bypass. Astra should refresh `effective_main_rules` in `snapshot.json` on its next pass.

**Deliberately not changed.** `gaia_panel.py` still approves an empty roster and downgrades unknown severities. Those belong to the panel-contract ticket in stage 2 so that one change carries its whole test suite, rather than a patch here and a patch there.

## Revised plan

The audit's stages 1A through 4 are kept as written. What changes is what comes before them and in what order. Each item names its exit evidence; nothing in a later stage should start because an earlier stage "looks done".

### Stage 0. Policy and the cheap fixes (this week)

| Item | Owner | Exit evidence |
|---|---|---|
| 0.1 Apply the ruleset to main | Marine, **done 10 Sept** | Effective-rules endpoint lists the five rule types (confirmed) |
| 0.2 Queue stays supervised: no unattended run, no auto-merge, draft PRs only, until stage 2 exits | Marine | Written in `gaia-automation.md` as the current policy |
| 0.3 Land today's runner and grouper fixes | Marine, PR | Tests pass; Astra reruns its probes and updates `automation-main-repros.json` |
| 0.4 Recover #163: rerun the persona that returned `None`; separate the infrastructure failure from the scientific questions | Astra or a supervised run | Panel record with a valid verdict from every seat |

### Stage 1. Science corrections that need no runner (small PRs, each with a decisive test)

| Item | Issues | Exit evidence |
|---|---|---|
| 1.1 Turn `reproduce_capillary_mass.py` into a failing test, then debit the water-table store by the capillary transfer. Hydrogeologist reviews the storage semantics before the fix merges. | #172, feeds #171 | Column test: transfers cancel, residual at rounding level, capillary-off control unchanged |
| 1.2 Correct the head-coefficient identification in `03b` (units 1/m, negative sign, drained vs undrained stated) with a units table | #198, #165 | Head-perturbation test: declared pressure increase gives declared softening |
| 1.3 Reword `04-assimilation.qmd:800-812`: per-particle linearization, approximate conditional likelihood; state θ–S_w relationship once | #198, #162, #204 | Chapter no longer claims exactness; #198 carries the oracle test |
| 1.4 Rewrite the entry points against the current product: `copilot-instructions.md`, `assumptions.md`, `limitations.md`, README pilot description, `gaia-conventions.md` Pillar-1 section | #204 | No 1 km, monthly or LightGBM instruction remains; assumptions dated and scoped |
| 1.5 Repair issue identities: #119 body, #120 to #125 bodies, #100 vs v0.4 wording in ROADMAP, the 23 tracker checkbox conflicts | R1, R2, R4 | Every reviewed issue has a title, a body and a closure disposition that agree |
| 1.6 Bibliography verification: every entry's title, authors and venue matched to the resolved DOI record | none yet, open one | Zero mismatches; the check is recorded, not just the DOI resolution |

### Stage 2. Runner contract, before any unattended run

Every item ships with a test in an isolated harness (fake `gh`, fake model) that exercises the real script, not a re-implementation.

| Item | Finding | Exit evidence |
|---|---|---|
| 2.1 Panel contract: empty roster blocks; unknown severity blocks; failed or missing dispatch voids the seat; exact identity match; `converged` requires an empty `blocking` list; final auditor gets the panel report and acceptance criteria | A2, A5 | Astra's five contract probes all fail closed |
| 2.2 Per-issue ledger and safe stop: closing trailers only from accepted issues; a stopped batch stays draft | A3 | TERM and cost-cap injected after issue 1 of 3; issues 2 and 3 never referenced |
| 2.3 One validation function for every candidate commit, including revisions, with integrity scan and Quarto; approvals bound to the head SHA; merge with `--match-head-commit` | A4, AUTO-04 | Weakened tolerance, broken Quarto and a late push each block |
| 2.4 Separate automation identity without bypass; Marine's account keeps its bypass | A1 follow-up | Runner token cannot merge an unapproved PR |
| 2.5 Mandatory reviewers per work package; unseated roles reported, not dropped | A6 | Novelty claim with a full panel produces a visible "unseated" line |
| 2.6 Gate-integrity covers the runner, helpers and personas, and flags lowered bounds | AUTO-07 | Both audit probes produce findings |
| 2.7 Typed dependency registry replaces `BLOCKED_BY`; epic blockers rejected; eligibility refreshed between batches | R1 (roadmap), AUTO-06 | #81 precedes #83 to #86; #198 waits on #187 and #176 |

Exit for stage 2: one supervised single-issue run, then the forced-failure scenarios in the audit's last table.

### Stages 3 onward

The audit's 1A (data fixtures), 1B (storage, timestep, deterministic physics), 1C (UQ and state schema), 2 (hydrology-only cycling pilot), 3 (forcing) and 4 (hazard pilots) stand as written. Two guards from the audit are worth repeating because they are easy to lose: the bounded well-and-probe pilot must not wait on seismic operator work, and a schema draft must not wait on every empirical calibration.

## Asks to Astra

1. Rerun `automation-main-repros.py` and `reproduce_capillary_mass.py` against this branch after the fixes are committed, and update the recorded outputs so the bundle matches the code.
2. Write the stage 2.1 panel-contract test list as a checklist that the fix PR must satisfy, using the five probes already in the bundle plus the `converged`-with-`blocking` case.
3. From `issue-inventory.json`, propose the typed dependency registry for 2.7: for each edge, say whether it is an implementation prerequisite, release evidence, optional fidelity, external input or human decision.
4. Quote the input field list of Landlab's `LandslideProbability` from the component source so S9 rests on the code, not the docs page.
5. Run the entry-by-entry bibliography check for 1.6 and report mismatches.
6. Settle the deployment-drift question: did the August #163 comments come from a runner newer than main? If a manifest exists, cite it; if not, say that plainly so 2.3's run manifest can be specified from zero.
