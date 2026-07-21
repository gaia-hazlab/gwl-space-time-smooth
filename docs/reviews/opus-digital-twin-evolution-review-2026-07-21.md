# Strategy review: the operating loop as the project's spine, and what the plan is still missing

**Date:** 2026-07-21
**Model base:** Claude Opus 4.8 (`claude-opus-4-8[1m]`)
**Reviewer role:** third-pass strategy synthesis. I am not re-reviewing the code (the sensor-uncertainty
review did that) or the book prose (the codex review did that). I am deciding what changes in the
*plan* — the milestones and issue graph — so the multi-stage evolution toward a probabilistic,
multi-hazard, Earth2Studio-compatible digital twin has an owner for every step and no silent holes.

**Inputs synthesized:**
- [`codex-review-0721.md`](codex-review-0721.md) — the editorial framework distilled from a seminar: one
  repeating operating loop, one state vector, one implemented/demonstrated/planned status discipline.
- [`sensor-uncertainty-covariance-review.md`](sensor-uncertainty-covariance-review.md) — a subsystem
  audit of per-sensor error, cross-sensor covariance, temporal error, and resolution-as-a-dial.
- [`digital-twin-strategy-review-2026-07-21.md`](digital-twin-strategy-review-2026-07-21.md) — the prior
  **Sonnet 5** graph-gap review. Its flood-milestone recommendation was partially executed: milestone
  "Hazard: flood / inundation handoff" now exists but is **empty** (0 issues).
- [`../probabilistic-nowcast-forecast-roadmap.md`](../probabilistic-nowcast-forecast-roadmap.md), the
  live milestones/issues (`gh` — 12 milestones, ~140 open issues), and [`../../ROADMAP.md`](../../ROADMAP.md).

I agree with the Sonnet review's four findings and do not repeat them at length; §5 says where I confirm
it, where I go further, and the one place I would sequence differently. My distinct contribution is §2–§3.

---

## 1. The three reviews are one argument at three altitudes

They do not conflict; they are the same claim seen from the book, the subsystem, and the graph.

- **Codex (narrative altitude):** the twin is *one repeating loop* — **represent → advance → observe →
  correct → propagate → evaluate → act** — and the scientific claim is "*the state lives at 90 m; every
  observation retains its own footprint.*" This is presented as a book reorganization. It is more than
  that, which is the subject of §2.
- **Sensor-uncertainty (subsystem altitude):** the *observe* and *correct* stages have real machinery
  (OU temporal discounting, Matérn terrain-aware prior, dv/v processing-ensemble covariance) but two
  concrete defects — dv/v's dense `Cd` is built then discarded before every `blue_update`, and per-sensor
  sigmas are inconsistent placeholders never traced to instrument specs.
- **Sonnet (graph altitude):** the issue web is unusually well-organized; the real gaps are at its
  *edges* — flood has no epic, Earth2Studio is half-tracked (data-source only), the book rewrite is
  untracked, and #164/#189/#161 need their bodies sharpened.

The user's steer — that the codex review gives "a more natural storytelling arc" — is the key. The other
two reviews tell you the plan is *correct*. The codex review tells you how to *order* it. That ordering
is worth more than a book edit, and §2 is why.

---

## 2. The operating loop is not a table of contents — it is the milestone spine

The codex review's deepest move is easy to miss because it is framed editorially. Its own words:

> The current list is accurate but organizes the book as an inventory. Replace it with the operating loop.

**The same sentence is true of the milestones.** The milestone graph today is organized by *subsystem* —
DA correctness, water-budget physics, memory/disturbance, one milestone per hazard, software hardening.
That is an inventory. It is a good inventory, and I am not proposing to demolish it. But it means the
project's *spine* — the thing a newcomer, a reviewer, or the next agent should read the plan against —
lives only in the book, while the execution graph is organized by a different axis entirely. The two
should be reconciled, because the loop is simultaneously a narrative arc **and** a capability-maturity
ladder. Mapping every milestone onto its loop stage is the single most clarifying thing the plan can do:

| Loop stage | What it means | Milestones / issues that serve it | Hole? |
|---|---|---|---|
| **Represent** | state at the scale the hazard needs; prior uncertainty | v0.3 Vs30 densification; v0.4/v0.5 domain; #187 contract; #163 prior | — |
| **Advance** | evolve water & stiffness, conserving mass | Water-budget (#171–#177); #172 conservation; snow; v0.6 dynamics | — |
| **Observe** | predict each sensor at its native support | #189 obs records; #164/#165/#168 operators; #198 petrophysics | — |
| **Correct** | data update the state, reduce uncertainty | #188 cycling EnKF; #192 B/Q/R | — |
| **Propagate** | posterior distribution → forecast | #191 ensemble forecast; v0.7 | — |
| **Evaluate** | score in observation space, held-out | #194 withheld value; #195 lead-time validation | — |
| **Act** | state distribution → hazard probability | landslide (#127); liquefaction (#139); **flood** | **flood unowned** |
| *(interop)* | speak Earth2Studio in *and* out | #112 (data-source only) | **model + DA side unowned** |

The loop is complete except in exactly the two places the Sonnet review found at the graph's edge — the
**act** stage for floods, and the **interop** boundary on the model/assimilation side. That is not a
coincidence; it is the same finding arrived at from the narrative rather than the graph, which is why I
trust it. The recommendation that follows (§4) is therefore not "reorganize 11 milestones" — it is
**overlay the loop as a cross-cut** (a labeled stage per milestone + an ASCII map in `ROADMAP.md`) so the
book's spine and the execution graph are the same object, and then **fill the two holes**.

This overlay also makes the codex review's status discipline *free*. A per-chapter
implemented/demonstrated/planned box is exactly the roll-up of its loop stage's issue states. The book's
honesty claim ("the present system is a strong digital shadow moving toward a probabilistic twin") becomes
a *derived* statement about which loop stages are closed, not a prose assertion that can drift from the
code — the failure mode that created the whole peer-review-remediation epic (#60) in the first place.

---

## 3. Scale-per-hazard is one symmetric principle, not three special cases

The user asks for "the appropriate scales for each hazard." The codex review already states half of the
principle — *observations retain their native support on the way in*. The other half, which no document
states as a principle, is its mirror:

> **Native support in (observations), native support out (hazards). The 90 m state grid is neither the
> finest observation nor the finest hazard product — it is the common ledger both are reconciled against.**

Making this symmetric is what turns "appropriate scale per hazard" from a caption into an enforceable
interface contract. Landslide already discovered this edge (#135: the state grid is not the hazard grid;
specify the finer one). It should be promoted from a landslide sub-issue to a book-level principle and
applied to all three hazards:

| Hazard | Consumes from the twin | Native hazard scale | Interface object | Owner |
|---|---|---|---|---|
| **Liquefaction** | Vs30 + seasonal-high depth-to-water | ~90 m susceptibility **screen** — explicitly *not* a CPT-resolution LPI | per-cell P(NEHRP class), susceptibility | #139 (honest scope in #147/#140) ✅ |
| **Landslide** | soil-state pore pressure + finer slope | **≤10 m** slope + cut-slope layer for shallow failures | per-cell factor-of-safety, P(FS<1) | #127 (#135 tracks the finer grid) ✅ |
| **Flood** | runoff + interflow + baseflow **source terms** | **channel reach / link network** — a different spatial object entirely | routed discharge → inundation | **unowned** |
| *(Earth2Studio)* | forcing in, ensemble state out | global 0.25° down to 90 m; state at member/lead_time coords | `DataSource` + `Prognostic` + member dim | #112 data-side only |

Flood is structurally unlike the other two: landslide and liquefaction consume the state *at the cell
where it lives*; flood consumes it *as a source term routed along a network that is not the state grid*.
That is why leaving it unscoped is dangerous — #39 already caught the twin *implying* a flood forecast it
cannot produce once. The flood epic's job is to make the non-claim explicit and hand the source terms off
with uncertainty, exactly as landslide handed off to LandLab.

---

## 4. Where I confirm Sonnet, where I go further, and the one resequencing

I confirm the Sonnet review's core: the DA priority chain (#164 → sourced sigmas in #189 → #188 cycling →
#192 B/Q/R → #191 ensemble → #193 joint hazard) is correct and untouched; the gaps are flood, Earth2Studio
model/DA, the untracked book rewrite, and the #164/#189/#161 sharpenings. Three amplifications and one
change:

**(a) Fold the Earth2Studio coords/dims convention into #187 *now* — do not defer it to a late issue.**
This is my one real disagreement with the Sonnet plan, which treats Earth2Studio model/DA compatibility
as a "parallel-track, build later" issue. The ensemble contract (#187) is being designed *now*, and it is
the single artifact that decides whether `member` / `lead_time` / `variable` / spatial coords speak
Earth2Studio's conventions. If #187 adopts those conventions as an acceptance criterion, interop on the
model and assimilation sides is nearly free; if #187 ships with a bespoke schema, every later adapter pays
to retrofit it. So: add an Earth2Studio-conventions acceptance criterion to #187, and let the *separate*
model-structure issue (the `Prognostic`/`Diagnostic` `__call__(state)->state` wrapper) build later against
a contract that was interop-shaped from day one. Interop is cheapest as a *constraint on the contract*,
most expensive as an *adapter on top of it*.

**(b) The book epic is the narrative projection of the milestone graph, not a parallel deliverable.**
Sonnet proposes tracking the codex rewrite as a new epic — correct. I would additionally require its
acceptance criteria to *derive* the per-chapter status boxes from the loop-stage overlay (§2), so the book
and the graph cannot drift. One source of truth, two renderings.

**(c) The flood epic is a #193 consumer, not a standalone.** Its members must be the *same* joint
ensemble members #193 passes to landslide and liquefaction, so cross-cell spatial correlation in the
runoff source term is preserved through routing. Scope it as the third branch of #193, sharing the
member-identity contract, not as an independent pathway.

**(d) On the title.** The codex review proposes **"The GAIA State2Hazard Twin."** I recommend adopting it.
It is not cosmetic: "State2Hazard" *names the act stage as the destination*, which is exactly the axis the
user's ask is organized around (landslide, liquefaction, flood, interop). "Digital Twin of Soil"
undersells the vadose/saturated/velocity/memory state and hides the hazard handoff that is the whole
point. Track the rename inside the book epic.

---

## 5. Plan

Nothing here reorders the DA milestone's internal priority. Everything is either a body-sharpening of an
existing issue, a loop-stage overlay, or a fill for one of the two structural holes.

### 5.1 Modify milestones (loop overlay — low churn)

1. Add a one-line **loop-stage tag** to each milestone description per the §2 table (e.g. prepend
   `[Correct]` / `[Act]`), and add the loop-as-spine ASCII map + the "native support in and out" symmetric
   principle (§3) to `ROADMAP.md`. No milestone is renamed or deleted.
2. Keep the empty **"Hazard: flood / inundation handoff"** milestone; §5.3 populates it.

### 5.2 Modify existing issues (sharpen bodies — confirmed by the audits)

1. **#164** — rewrite to the sharper finding: dv/v's dense `Cd` (`dvv.py:222-281`) is *computed and then
   discarded* at all five `blue_update` call sites (`make_twin_gif.py:197,213`;
   `make_checkerboard_test.py:138`; `test_observability.py:273,282`); add the blocking note "no
   dv/v-informed posterior variance is trustworthy until `Cd` reaches the estimator" toward #192/#188.
2. **#189** — add an explicit task: source **one** physical, documented sigma per non-dv/v sensor (USGS
   reading precision + datum uncertainty for NWIS; SNOTEL/SCAN/USCRN probe-accuracy spec; SMAP published
   ubRMSE ≈0.04 m³/m³; USGS rating-curve error) and retire the two mutually inconsistent placeholder sets
   in `observability.py`'s catalog and `notebooks/make_twin_gif.py`'s demo constants.
3. **#161** — rewrite to reflect that the OU lag fix (`ρ·g` gain, `σ²(1−ρ²)` drift) has **landed**; narrow
   the remaining scope to the space-time `B` / Kalman propagation. Note the regime-switching `τ` extension
   (§5.3.4) as a diagnostic-gated follow-on, not part of this issue.
4. **#187** — add an acceptance criterion: the canonical state/forcing/observation Zarr contract exposes
   `member` / `lead_time` / `variable` / spatial coords in **Earth2Studio conventions**, so the interop
   adapters (§5.3.2) are a wrapper over the contract, not a retrofit of it. *(This is amplification (a).)*
5. **#18** (EPIC gaia-soil-reanalysis) and **#73** (EPIC forecast) — add a line registering the new flood
   epic as the third hazard consumer alongside landslide/liquefaction, so the epic-of-epics stays complete.

### 5.3 Add new issues / epics

1. **[epic] Flood/inundation handoff — soil-state source terms → routed discharge** (flood milestone):
   - exports: runoff + interflow + baseflow **source terms with per-cell uncertainty**, at 90 m, as the
     *same joint ensemble members* #193 uses (amplification (c));
   - candidate routing: LandLab `OverlandFlow`/`FlowAccumulator`, or an external HAND-based inundation model;
   - validation: against USGS gauge hydrographs (reuse the D7 BFI/Q–P calibration, #98) and, where
     available, observed inundation extent;
   - **explicit non-claim:** the twin does not produce flood extent on its own grid (matches #39/#55).
   - Split 2–3 sub-issues (source-term export contract; routing-component selection + pilot; gauge-hydrograph
     validation) once the epic body is agreed.
2. **Earth2Studio model-structure & assimilation compatibility** (v0.7 / DA milestone), complementing #112:
   wrap the cycling nowcast/forecast (#188/#191) in a `Prognostic`/`Diagnostic` `__call__(state)->state`
   contract, consuming the Earth2Studio-conventions member/lead_time dimension that #187 now guarantees.
3. **[epic] Book/twin rewrite — the codex editorial framework** (new light epic): six-stage loop opener per
   chapter, unified state-vector notation, per-chapter status boxes **derived from the loop-stage overlay**
   (§5.1), and the **"GAIA State2Hazard Twin"** rename. Link #172/#198/#164/#188/#191 as code-side
   prerequisites the prose must reflect, not duplicate.
4. **Diagnostic-gated regime-switching τ for the OU temporal model** (light, DA milestone): explicitly
   deferred until the innovation-heteroscedasticity diagnostic fires; wired as a named follow-on of #194,
   tracked so it is not lost. *(Splits cleanly out of #161 per §5.2.3.)*

### 5.4 Immediate next actions (what to do first)

1. **#164** — wire dv/v's existing dense `Cd` into `blue_update`. It is built, correct, and thrown away;
   this is the highest value-per-effort item in the entire graph and gates any trustworthy posterior
   variance in the *correct* stage.
2. **#189** — collapse the placeholder sigmas into one sourced obs-error config. Cheap, unblocks #187/#192.
3. **#187** — with the Earth2Studio coords criterion (§5.2.4) baked in, since it is being designed now.

Everything else in §5.3 is parallel-track scoping that can be built once #191/#193 land, the same way the
landslide and liquefaction epics were scoped ahead of the physics that now feeds them.

---

## 6. Execution note

Per this project's PR/issue workflow, I have **not** created or edited any GitHub issue or milestone from
this review. §5 is written as an executable plan (exact issue numbers, titles, bodies, milestone
placements). I recommend it be run *after* the adversarial re-review this project applies to plan changes,
and I will execute the `gh` edits on request. No issue is closed or auto-closed by anything here.
