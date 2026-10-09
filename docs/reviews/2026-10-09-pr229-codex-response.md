# Response to the Codex review of PR #229

**Date:** 2026-10-09. **Responds to:** `2026-10-09-codex-pr229-review.md` (Codex, at PR head `ad6fb25`).
**Written by:** Claude (Opus 5.5) for Marine Denolle. **Branch:** `docs/physics-backlog-audit-2026-10-08`.
**Code checked:** twin origin/main `435445f` (unchanged since the audit), rainier3d `d61305c` (detached worktree), local branch `work/storage-conservation-2026-09-10` at `1f93f15`, open PR #272 at `618fea9`, live GitHub issues fetched 2026-10-09.

## Verdict

All seven Codex findings are correct. Each was checked by rerunning a probe or computing the cited quantity, not only by reading. The archive is corrected in place on this branch. Every changed recommendation carries a **[Corrected 2026-10-09, Cn]** marker, and the original text is struck through rather than deleted. The larger problem is that the flawed recommendations had already been copied into live issues #164, #176, #198, #232, #249, #251, #265, #266 and #267 before this review. Those issue edits are listed below as proposals. They have not been applied.

## Finding-by-finding verification

| ID | Codex finding | How verified | Result | Archive change |
|---|---|---|---|---|
| C1 | Required architecture exceeds the objective (2D Boussinesq, Richards at every sensor) | Read README:123-130, :224-227 | Confirmed. Conservation of a compartment model needs neither solver | README §1, §3.4, §4, §6, §7, §9.3 rewritten around shared stores, capacity-limited transfers, outlet closure and native-support operators; solvers moved to advisory |
| C2 | Contradictory dependency recommendations create cycles | Read README §9.4, `issues/water-budget-core.md:88`, `issue_verdicts.json`; cycle check by script | Confirmed. 176→198 (README) vs 198→176 (family file, JSON); 100→137 (JSON) vs 137→100 (README) | 198 split into 198a/198b/198c in the README table; family file struck; JSON 100 → `[70]`, 198 → `[187]`. README table plus JSON blockers: 38 nodes, no cycle |
| C3 | Shallow dv/v "zero sensitivity" is a grid artefact | **Rerun** `probes/memory/probe.py` (codameter from the project pixi env) | Confirmed. First kernel nodes at 5, 15, 25 m; top-1 m weight 0.0000 in all four bands; top-1 m perturbation returns 0.000% in every band | README §5 band prescription struck; `lenses/hydromechanics.md` item 3 and two passages in `issues/hydromech-dvv-memory.md` struck and rescoped |
| C4 | Water creation conflated with drainage and equilibration | **Rerun** with capillary rise on and off; linear-reservoir recursion | Confirmed (numbers below) | README §1 and §3.1 table gain a Diagnosis column; `lenses/geohydrology-budget.md` "unstable unless" struck |
| C5 | Groundwater identifiability probe not archived | **Ran** `verify-da-physics-coupling/sub.py`; read `probes/da/ident.py` | Confirmed. `FileNotFoundError: ../wf/da/ident.py`. Two auditors wrote scratch files named `wf/da/ident.py`; the archived one is the #169 healing-basis probe | Condition numbers marked unreproduced in README §3.2 and the DA lens; analytic R/S_y scaling kept; header comments on both probe files |
| C6 | Non-zero innovation mean rewards bias | Read `issues/hydromech-dvv-memory.md:168` | Confirmed | Acceptance criterion replaced |
| C7 | Correlated-observation test is unsatisfiable and its 1/N is wrong | **Computed** (B = 1, r = 0.25, N = 5) | Confirmed. Cholesky raises on the rank-1 R. Redundant: 0.2000; five independent: 0.0476; ratio 0.238, not 1/N = 0.200. A pseudo-inverse solve on the redundant case returns 0.2000 | Test replaced in `issues/da-estimator.md:53` |
| C8 | NaN in benchmark JSON; prose in verdict actions | `json.load(..., parse_constant=raise)` | Confirmed: 3 NaN in `bench_365.json`; 3 non-enum `final_verdict` values | `null` plus `failure_reason`; probe writer uses `allow_nan=False`; `final_verdict` restricted to 8 values with `final_verdict_note`; counts unchanged (68 rewrite, 7 defer) |
| C9 | Fixed 10⁻⁶ mm tolerance (Codex instruction 4) | `np.spacing(np.float32(1000))` | 6.1×10⁻⁵ mm. `coupled_water_budget` saves fluxes as float32 (`water_budget.py:284`), so a ledger computed from saved fields cannot reach 10⁻⁶ mm over 1,000 mm inventories | README §3.4 gate rewritten: tolerance follows the arithmetic used |

### C4 numbers (rerun 2026-10-09, `src/models/water_budget.py` at `435445f`)

| Case | Capillary rise | Σ cap rise (mm) | Ledger residual (mm) | Water table |
|---|---|---|---|---|
| Zero forcing, 30 d, wt0 1.2 m, HAND 30 m | on (30 mm/month) | 9.55 (4.266 over days 2–30) | +4.266 over days 2–30, equal to Σ cap over the same days | 1.210 → 1.498 m |
| Same | off | 0.00 | 0.000 | 1.210 → 1.498 m (identical) |
| Wet year, P 1,269 mm, HAND 0 m, d0 0.5 m | on | 278.4 | +278.0 | 0.50 → −0.06 m |
| Same | off | 0.0 | 0.0 | 0.50 → −0.04 m, zero baseflow |
| Linear reservoir, head0 10 m, R_ref 3 mm/d | n/a | n/a | n/a | R̄ = 1, 3, 5 mm/d settle at 3.33, 10.0, 16.7 m |

Capillary rise is the only creation term. The valley cell without capillary rise conserves water and still floods to the surface, which is the missing outlet. The ridge drain is a stable reservoir relaxing from an initial state above head0·R̄/R_ref. These three take separate acceptance tests. The capillary repair already exists as `1f93f15` ("fix: conserve capillary exchange across water stores", 2026-09-10) on the local branch `work/storage-conservation-2026-09-10`, which has never been pushed. Live #232 asks for that repair again without citing it.

## Probe census

All 29 archived probes were executed on 2026-10-09 with the project pixi Python, twin worktree at `435445f` and rainier3d at `d61305c`.

| Status | Count | Probes |
|---|---|---|
| Executes | 28 | All others. `geohydro/probe_budget.py` and `verify-geohydrology-budget/probe_copy.py` reproduce their committed JSON to 5×10⁻¹³ mm. `scale/bench_richards.py 365` reproduces `bench_365.json`, including the `30m_free` failure |
| Fails | 1 | `verify-da-physics-coupling/sub.py`: its input file was never archived (C5) |

Invocation is not uniform. `verify-scale-up-from-rainier/p1b.py`, `p2.py` and `p5.py` take the rainier3d checkout as `argv[1]` and their own directory as `argv[2]`. `scale/bench_richards.py` takes the rainier3d checkout and a day count. Seven probes hard-code `scratchpad/main` for the twin checkout.

## Propagation into live issues (proposed edits, not applied)

The live dependency graph is acyclic. It contains 155 open issues and was built from PR #272's `BLOCKED_BY` table plus the "Blocked by" lines in issue bodies. Every blocker names a real issue, and no epic is used as a blocker. The cycle in C2 is latent: #198's body already describes a 198b blocked by #176, and #176 is blocked by the whole of #198.

| Issue | Defect inherited from the archive | Proposed edit |
|---|---|---|
| #198 | Split described in prose but not done; would close the 176 ↔ 198 cycle | Create 198b (hysteretic mode; blocked by #176 and 198a) and 198c (DA through the operator; blocked by #187, #188, #164, #165, 198a). Keep #198 as 198a. Add both edges to `BLOCKED_BY` in the same PR #272 update |
| #176 | Body line 16 still says "#198 depends on it" | Strike line 16; state that only 198b depends on #176. Keep "Blocked by: #172, #131, #198" (198 = 198a after the split) |
| #164 | Perfectly-correlated test that Cholesky cannot pass, and 1/N | Replace with the three tests in C7 |
| #249 | "the innovation mean is non-zero" | Replace with the C6 criterion |
| #251 | "no kernel node lies above 5 m … needs ≳10-50 Hz or DAS" stated as physics; acquisition framed as the outcome | Rewrite Why from C3. Scope becomes: kernels for the observed bands on a grid with cm-to-dm nodes in the top 2 m; forward sensitivity per layer against dv/v noise; recoverable state combinations. Acquisition becomes an advisory follow-up, not the deliverable. Keep "Blocked by: #247" |
| #232 | Asks for the capillary repair already made in `1f93f15`; fixed 10⁻⁶ mm tolerance | Cite `1f93f15` as delivered work to review and port; tolerance per C9; separate forecast-step identity from analysis increments; list initial/final inventories and every boundary flux in the acceptance |
| #265 | Design record mandates 2D Boussinesq on the hydrogeologic grid | Mark the hydrogeologic-grid items advisory; minimum content is the C1 store list, transfer rules, outlet closure and operator supports |
| #266 | Boussinesq aquifer as the deliverable | Recast as an advisory refinement behind a measured deficiency (for example, residual well-head bias in convergent valleys after #233); not a blocker for #187/#188 |
| #267 | "Run at every assimilated sensor column" | Change to "optional benchmark column where a measured deficiency calls for it"; keep the specific-storage fix; tolerance per C9 |
| #130, #172 | 10⁻⁶ mm ledger tolerance on float32 outputs | Tolerance per C9 |

Issues #128, #200, #242 and #245 also use 10⁻⁶, but for algebraic identities or float64 sums, where it is attainable. Leave them. #233 (valley outlet) already reads as a drainage closure and needs no change.

## Queue (PR #272)

Checked against Codex's pre-dispatch list:

| Check | State on PR #272 at `618fea9` |
|---|---|
| Graph acyclic, topological order exists | Yes on live data (computed here), but nothing in the grouper checks it |
| Every hard blocker is a real issue | Yes |
| Holds enforced by the filter | Yes: `test_needs_human_decision_is_held`, `test_hold_survives_explicit_selection` |
| Epics are not blockers | Yes on live data (#171 removed from 187); no fixture |
| Split issues get edges in the same update | Not yet: 198a/198b/198c do not exist |
| Same-loop tasks sequenced | 172 → 131/173/174 → 130 → 133 chain is encoded; 175 depends on 232/233 only, so it can run beside #172 on the same loop |
| Dry-run record with hold reasons | Not recorded |

Proposed additions to PR #272: a cycle check that fails the run and names the cycle; fixtures for a cycle, an epic used as a blocker, a closed blocker releasing its dependant, and the 198a → 176 → 198b ordering; `175: [232, 233, 172]` so the four edits to `coupled_water_budget` serialise; and a committed dry run listing each held issue with its open blocker or hold label. This would not release any hold.

## What is left for Marine

1. Approve the live-issue edits above. Once approved, I apply them and push the PR #272 additions to its branch.
2. Decide whether `1f93f15` should be pushed and opened as the first #232 PR, or reviewed against #232's acceptance first.
3. The groundwater identifiability numbers can be recomputed with a new, pinned probe. The analytic argument does not need them, so this is optional.
