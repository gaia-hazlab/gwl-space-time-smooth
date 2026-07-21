# Strategy review: from DA-correctness backlog to a probabilistic, multi-hazard digital twin

**Date:** 2026-07-21
**Model base:** Claude Sonnet 5 (claude-sonnet-5)
**Reviewer role:** cross-reading the two most recent reviewer documents against the live GitHub issue/milestone graph and `ROADMAP.md`, to decide what changes in the plan — not to re-review the code a third time.

**Inputs synthesized:**
- [`docs/reviews/codex-review-0721.md`](codex-review-0721.md) — editorial framework for the Quarto book, written after a seminar forced a cleaner narrative arc.
- [`docs/reviews/sensor-uncertainty-covariance-review.md`](sensor-uncertainty-covariance-review.md) — per-sensor error, cross-sensor covariance, temporal error, and resolution-as-a-dial.
- `ROADMAP.md` and the live milestones/issues (`gh issue list`, `gh api .../milestones`, 11 milestones, ~140 open issues as of this review).

---

## 1. What these two reviews actually are, and why they don't conflict

The codex review is a **narrative** review: it does not dispute any physics or math, it disputes the *order in which a reader meets it*. Its central move — six stages (**represent → advance → observe → correct → propagate → evaluate → act**), one state vector, one implemented/demonstrated/planned status box per chapter — is a documentation contract, not a code change. Where it does touch code, it points at things that already have issues: the capillary-rise conservation debt (#172), the shared forward/inverse petrophysical operator (#198), and the gap between snapshot BLUE and a cycling filter (#188/#191). Its real contribution is a **project-wide labeling discipline** ("implemented" vs "demonstrated" vs "planned") that the issue graph already practices informally (P0/P1/P2, epics, "MVP" language) but the *book* does not yet practice consistently, and that is currently missing as a tracked deliverable anywhere.

The sensor-uncertainty review is a **technical audit** of one subsystem (`observability.py`, `dvv.py`, `anchor.py`) against the specific probabilistic claims the codex framework will make in Chapter 7. It does not propose a different roadmap — it re-derives, from the code, the same priority order the DA milestone (#160 and children) has already staked out, and in two places it **sharpens** an existing issue rather than opening a new gap:

- **#164** ("Diagonal R for dv/v double-counts correlated coda errors") is not just "cross-sensor correlation is unmodeled." Tracing all five `blue_update` call sites shows dv/v's dense, ensemble-derived `Cd` is *computed and then discarded* before every one of them. That is a stronger, more actionable finding than the issue text currently states.
- **#189** ("Operationalize ground-sensor observation records...") does not currently name the concrete defect the review found: two independently invented, undocumented, mutually inconsistent placeholder sigmas per non-dv/v sensor (one in `observability.py`'s design catalog, one in `notebooks/make_twin_gif.py`'s demo constants), neither traced to a real instrument spec.

Both of these are "modify the issue," not "open a new issue" — the scaffolding is already correct; it needs the sharper finding written into it so the next agent doesn't have to re-derive it.

**Net read:** the issue graph is unusually well-organized for a project at this stage — DA correctness (#160), water-budget physics (#171), landslide (#127), liquefaction (#139), memory/disturbance (#119), software hardening (#150), and forecast (#73/#191) already form a dependency-annotated web that both reviews mostly confirm rather than contradict. The gaps worth acting on are not inside that web — they are at its **edges**: places the user's stated destination (LandLab, liquefaction, floods, Earth2Studio, appropriate per-hazard scale) touches the plan but has no tracked issue at all.

---

## 2. Gaps found at the edges of the current plan

### 2.1 There is no flood epic

Landslide has an epic (#127, 6 sub-issues) and a milestone. Liquefaction has an epic (#139, 8 sub-issues) and a milestone. **Flood has neither.** The only flood-adjacent issue is #55 (closed) — "Reframe the forecast path as antecedent-state; require an external runoff+routing model" — which correctly punted routing to LandLab *and then nothing tracked what LandLab needs from us or what "external runoff+routing model" means concretely*. #39 flags that the current Earth2Studio subsection *implies* a flood forecast it cannot deliver (no routing), but that issue's job is disclaiming a wrong claim, not scoping the right one.

This matters because flood is explicitly one of the four target applications in the user's ask, and it is structurally different from the other two hazards: landslide and liquefaction consume the soil state **at the same 90 m grid cell** where the state lives; flood consumes **routed discharge along a channel network**, which is a different spatial object (reach/link, not cell) fed by the soil state's runoff and interflow *source terms*, not by the state itself. Leaving this un-scoped risks the same failure mode #39 already caught once (implying a capability the architecture cannot yet produce) recurring silently in the twin/book rewrite the codex review proposes, and it means the "appropriate scale for each hazard" requirement in the user's ask has no owner for the flood case.

### 2.2 Earth2Studio compatibility is half-tracked

#112 covers the **data-source side**: wrapping Kopah Zarr stores as `earth2studio.data.DataSource`. There is no issue for the **model-structure side** — exposing `SoilStateForecast` / the cycling nowcast (#188/#191) as something Earth2Studio's own ensemble/workflow tooling could drive (a `Prognostic`/`Diagnostic`-shaped `__call__(state) -> state` with a coords/dims contract), and no issue for the **assimilation side** — making the analysis step (#187's ensemble contract) expose a `member` dimension in a form that composes with Earth2Studio-style ensemble workflows rather than only with this repo's own BLUE call sites. #191 already asks for an `ensemble_member` dimension on internal forecast outputs; the missing piece is making that dimension speak Earth2Studio's own conventions, which is what makes "Earth2Studio compatibility" true in the sense the user means it (data structure *and* model structure *and* assimilation), not just the data-source adapter that exists today.

### 2.3 The book rewrite itself is not a tracked deliverable

The codex review is an 11-chapter, title-changing, notation-unifying editorial plan. Nothing in the issue graph tracks it. Given how much weight "Now/Next" and "implemented/demonstrated/planned" labeling carries for scientific honesty in this project (the whole peer-review-remediation epic, #60, exists because claims outran implementation once already), the rewrite should be a tracked epic with the same discipline as #150 or #160, not a one-off doc edit that happens to get done or not.

### 2.4 Two sharpenings, not gaps (see §1) — #164 and #189 need their bodies updated, not new issues.

### 2.5 One issue is now partially stale

#161 ("Temporal model: proper space-time covariance or a Kalman propagation") describes the OU lag treatment as unfixed (`1/exp(-dt/2tau)`, unit gain). The sensor-uncertainty review confirms the code now implements the corrected `ρ·g` gain and `σ²(1-ρ²)` drift term, and even preserves the old-wrong version in the docstring as a documented correction. #188's own dependency note already says "OU lag treatment is landed; dynamic propagation remains" — the dependency graph knows this, but #161's own issue body still describes the pre-fix state. This should be edited so the issue reflects what remains (the space-time `B`/Kalman propagation) rather than re-describing a bug that is gone.

---

## 3. Scale check, per hazard (the user's explicit ask)

| Hazard | Native scale needed | Current twin grid | Status |
|---|---|---|---|
| Liquefaction | ~90 m susceptibility screen, Vs30-driven, explicitly *not* a CPT-resolution LPI (#147 already states this) | 90 m | Matches — scope is honest (#147, #140) |
| Landslide | ≤10 m slope + cut-slope layer for shallow failures (#135); colluvium/root-cohesion at hillslope scale | 90 m soil-state, but LandLab component can run finer | Gap already tracked (#135) — worth flagging in the flood epic write-up as the precedent to follow |
| Flood | Channel/reach network (HAND/LandLab `OverlandFlow`/routing-model links), not the 90 m soil-state grid | 90 m (source terms only) | **Untracked** — this review's main structural finding |

The pattern from landslide (#135: "the state grid is not the hazard-model grid; specify the finer one explicitly") is the right template for the flood epic: don't try to make the 90 m grid do routing; make the interface explicit about what leaves the twin (runoff + interflow + baseflow source terms, with uncertainty) and what a routing model must supply.

---

## 4. Plan

### 4.1 Modify existing issues/milestones

1. **#164** — rewrite body to state the sharper finding: dv/v's dense `Cd` (`dvv.py:222-281`) is computed and discarded at all five current `blue_update` call sites (`make_twin_gif.py:197,213`; `make_checkerboard_test.py:138`; `test_observability.py:273,282`); add "blocks a trustworthy #192 posterior variance for any dv/v-informed cell" as an explicit blocking note toward #188/#192.
2. **#189** — add an explicit task: source one physical, documented sigma per non-dv/v sensor (USGS reading precision/datum uncertainty for NWIS; SNOTEL/SCAN/USCRN probe accuracy spec; SMAP published ubRMSE ≈0.04 m³/m³; USGS discharge/rating-curve error) and retire the two independently-invented, mutually inconsistent placeholder sets in `observability.py`'s catalog and `notebooks/make_twin_gif.py`'s demo constants.
3. **#161** — rewrite body to reflect that the OU lag gain/drift fix (`ρ·g`, `σ²(1-ρ²)`) has landed in `observability.py`; narrow remaining scope to the space-time `B` / Kalman propagation, and note the regime-switching `τ` extension (§4.2 below) as a follow-on, not part of this issue.
4. **#18** (EPIC gaia-soil-reanalysis) and **#73** (EPIC forecast forcing) — add a line noting the new flood epic (§4.2) as the third hazard consumer, alongside landslide/liquefaction, so the epic-of-epics structure stays complete.

### 4.2 New issues/milestone to add

1. **New milestone: "Hazard: flood / inundation handoff"** (parallel to the landslide and liquefaction milestones), with an epic issue **"[epic] Flood/inundation handoff — from soil-state source terms to routed discharge"**, scoping:
   - what the twin exports (runoff, interflow, baseflow source terms + uncertainty, at the 90 m grid) vs. what a routing model consumes (reach/link discharge);
   - candidate routing components (LandLab `OverlandFlow`/`FlowAccumulator`, or an external HAND-based inundation model);
   - validation against USGS gauge hydrographs (reusing the existing BFI/Q-P calibration from D7, #98) and, where available, observed inundation extent;
   - explicit non-claim: the twin does not produce flood extent on its own grid, matching the disclaimer already established for #39/#55.
2. **New issue: "Earth2Studio model-structure and assimilation compatibility"** (DA/forecast milestone), complementing #112: wrap the cycling nowcast/forecast (#188/#191) in an Earth2Studio-shaped `Prognostic`/`Diagnostic` `__call__(state) -> state` contract, and expose the ensemble analysis (#187) with an Earth2Studio-conventions `member`/`lead_time` dimension so the twin can be driven by, and feed into, Earth2Studio ensemble workflows rather than only its own BLUE call sites.
3. **New epic: "Book/twin documentation rewrite (codex editorial framework)"**, tracking `docs/reviews/codex-review-0721.md` chapter-by-chapter, with the six-stage framework, unified notation, per-chapter implemented/demonstrated/planned status boxes, and the title change as acceptance criteria. Link #172/#198/#164/#188/#191 as the code-side prerequisites the rewrite must accurately reflect (not duplicate).
4. **New issue (light, DA milestone): "Diagnostic-gated regime-switching τ for the OU temporal model"** — not urgent, explicitly deferred by `04-assimilation.qmd` and by the sensor-uncertainty review until the innovation-heteroscedasticity diagnostic fires; tracked so it isn't lost, and wired as a named follow-on of #194 (the value-added/diagnostic issue that would trigger it) rather than #161 (which should stay scoped to space-time `B`).

### 4.3 Sequencing note

Nothing above reorders the DA milestone's own priority (#164 → sourced sigmas in #189 → #188 cycling → #192 B/Q/R → #191 ensemble forecast → #193 joint hazard ensembles), which both reviews independently confirm is correct. The new flood epic and the Earth2Studio model/assimilation issue are **parallel-track**, not blocking — they can be scoped now and built once #191/#193 land, the same way the liquefaction and landslide epics were scoped ahead of the physics that now feeds them.

---

## 5. Execution log

GitHub issue/milestone edits made following this review are recorded in the commit that adds this file; see the linked issue numbers above for the live state.
