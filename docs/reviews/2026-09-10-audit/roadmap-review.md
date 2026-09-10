# Independent audit of the GitHub roadmap and dispatch specification

Audit date: 2026-09-10. Repository: `gaia-hazlab/gwl-space-time-smooth`. Main snapshot: `435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f`. No GitHub mutation was made. This review read every one of the 160 issue bodies, including all 126 open issues, all 12 milestone descriptions, both roadmaps, selected full implementation/status comments, and the actual current-main grouping code. It includes the existence and outcomes of the substantial science-panel records on #163 and #186; it does not independently adjudicate every scientific statement in those long reviews. Code-physics and execution-governance verification are separate companion audits.

Artifacts: `issue-inventory.json` contains every issue with a manually reviewed disposition for every open issue; `roadmap-queue-simulation.jsonl` is an offline execution of the current-main grouper with the issue snapshot injected into `fetch_issues`; `roadmap-queue-held.txt` lists the held issues. The two roadmap files were identical between the workspace branch and downloaded main; code citations to the grouper refer to downloaded current main.

## Overall finding

The roadmap contains most of the necessary scientific work, and the newer probabilistic issues are much better specified than the older scaffold-era issues. The central failure is that the plan is not yet an unambiguous dispatch contract. Titles, bodies, comments, milestones, prose dependency graphs, and executable dependency lists disagree. An agent can faithfully implement its assigned issue and still build the wrong component, violate a prerequisite, or certify a claim that another part of the plan explicitly withholds.

This is a readiness problem, not evidence that all planned scientific capabilities should already exist. In particular, real cyclic assimilation, ensemble forecasting, memory attribution, and three hazard pathways are correctly recorded as future work in many issues. Fix the executable plan and its evidence semantics before increasing autonomous concurrency.

## Inventory and strengths

- 160 issues: 126 open, 34 closed. Twelve open milestones; 35 open issues have no milestone.
- 114 open non-epic work items; 44 have no canonical P0/P1/P2 label. Zero assignees. All GitHub native dependency and native sub-issue counts are zero; dependencies exist in prose and a separate Python dictionary instead.
- Sixty of the 114 open non-epic bodies have an acceptance/done-when heading. This is a documentation-format statistic, not a finding that the other 54 lack every useful criterion.
- Twenty-three checkbox/state discrepancies across #1, #60, #127, and #150. One null epic body (#119), four open title/body shifts (#121–#124), one closed shift (#120), and an exact duplicate body (#124/#125).
- The storage-first state contract (#187), explicit physical mass ledger versus DA inference increment, joint-member identity, native observation support, calibration/assimilation/test separation, and open-loop versus DA comparison (#194) are strong design choices.
- The plan explicitly permits a small hydrologic pilot before full-domain or mechanical completion; #205 is appropriately diagnostic-gated; #146 is explicitly future triggering work; #147 correctly limits the initial liquefaction product to susceptibility.
- Human review is real, not merely aspirational: #163 and #186 contain pre-registered plans, reviewer objections, and blocking outcomes. Recent comments also improve well-target semantics, state vocabulary, conditional pressure closures, and data-based covariance fitting.

## Ranked findings

### R1 — Blocking: issue identity corruption can commission the wrong implementation

[#119](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/119) has no body. The memory epic's numbered children are shifted:

| Issue | Title promises | Body requests |
|---|---|---|
| [#120](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/120), closed | capillary hysteresis | earthquake damage/healing |
| [#121](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/121) | earthquake damage/healing | wildfire/tillage/landslide disturbance |
| [#122](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/122) | surface disturbance | augmented BLUE attribution |
| [#123](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/123) | attribution | event catalog |
| [#124](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/124) | event catalog | report chapter, identical to #125 |

The durable mapping in [ROADMAP.md:146](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/ROADMAP.md#L146) matches the titles. Existing queue-cleanup prose notices only #121–#123 ([probabilistic roadmap:177](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/docs/probabilistic-nowcast-forecast-roadmap.md#L177)), missing closed #120 and open #124. Downstream references such as #169's event-catalog prerequisite currently lead to a chapter-writing task. The real #120 closure comments describe observable hysteresis, with water dynamics deferred; do not transform that closed issue into a claim that earthquake damage has shipped.

Repair all five bodies, create the epic's actual acceptance/children, and record which former scope is retained under each existing number. Validate title/body/topic consistency before dispatch. This is a concrete prerequisite to safe autonomous work, not routine cosmetic cleanup.

### R2 — Blocking: the executable dependency graph admits work its own issues prohibit

The grouper contains only 14 keyed prerequisite lists ([current-main gaia_group_issues.py:86](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/scripts/gaia_group_issues.py#L86)). [#198](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/198) explicitly depends on #187 and #176, but is absent from that dictionary. The snapshot-fed grouper emits it in batch 2, alongside #163/#162/#161, while both prerequisites are open. The same simulation emits final Vs30 modeling/validation #86/#85/#84/#83 in batch 13 and its explicit measured-profile prerequisite #81 only in batch 14. [#81](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/81) says it gates every other issue in that milestone.

Likewise, #173 uses a placeholder `#...` for the unsaturated store it needs; #129's end-to-end landslide score needs #128 and suitable terrain/head inputs; #203's model wrapper needs actual #188/#191 interfaces, not only a schema. Several are coupled tasks that might safely share a deliberately ordered integration batch, but current grouping by milestone/labels does not declare that order.

Use one typed dependency registry shared by issue rendering and scheduler: `implementation prerequisite`, `release evidence`, `optional fidelity`, `external input`, and `human decision`. Enforce ordinary prerequisites before grouping. Add contract tests for the exact examples above and a cycle/missing-issue check. Do not simply turn every prose reference into a hard edge; that would introduce unnecessary stalls.

The offline simulation produced 38 batches with 100 non-epic issues emitted and 14 held. These are candidate batches, not proof every item would execute: the runner may apply additional parked-item checks. The companion automation audit owns that distinction.

### R3 — High: release gates are used as coding prerequisites, while critical foundations are scheduled late

[#187](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/187) explicitly allows a prototype using the calibrated daily skeleton and treats #171/#172/#137 as operational-release dependencies. The roadmap likewise permits a limited #188 pilot before production water/scale closure ([probabilistic roadmap:211](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/docs/probabilistic-nowcast-forecast-roadmap.md#L211)). But the executable graph blocks #187 on the entire open water epic #171 as well as individual storage issues. Because #171 encompasses all eight water-review tasks, the whole probabilistic schema/nowcast chain waits for a broad epic closure.

Meanwhile, [#52](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/52) (state definition) and [#89](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/89) (daily/monthly consistency), which the scheduler itself calls foundational blockers, have no milestone. Current main sorts nonmilestoned work after all listed milestones ([grouper:49](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/scripts/gaia_group_issues.py#L49)): snapshot batches 25 and 35 respectively, after advanced Vs30, memory, and hazard work. Shared FuXi execution #136 is placed in the landslide milestone after the v0.7 forcing milestone.

Separate schema design/pilot authorization from production-release qualification. Put #52/#89 and the shared forcing work in the correct foundation lanes, and define specific acceptance evidence that releases the next lane rather than using an entire broad epic's open/closed state. Keep source generation, numerical kernel development, and full observational qualification independently reviewable.

### R4 — High: ROADMAP's next milestone bypasses an intentionally unresolved acceptance criterion

[ROADMAP.md:53](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/ROADMAP.md#L53) says magnitude and phase pass; [line 87](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/ROADMAP.md#L87) declares v0.4 done; [line 122](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/ROADMAP.md#L122) names Stehekin next. However, #100's latest [status comment](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/100#issuecomment-4961852376) intentionally keeps it open: the required April water-table peak is May, and a multi-year daily spin-up experiment is still needed. Milestone 3 remains open with that one open child. [#99](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/99) explicitly says not to start before v0.4 closes.

The problem is not that #100 was accidentally left open. It is the opposite: the prose summary dropped a real unresolved acceptance gate. Record "domain and daily calibration delivered; seasonal phase qualification open" and either honor #99's gate or explicitly narrow its next authorized scope to an independent scoping study. Preserve the distinction between a seasonal phase explanation and #131's genuine event-scale transit/storage question.

### R5 — High: the filter/memory architecture is inconsistent across issues and roadmap

[#162](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/162) mandates an augmented Kalman/RTS smoother over hydrology, damage, and disturbance. [#190](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/190) specifies an exponential relaxation transition for each mechanical state and neither names the RBPF design nor declares #188/#198 as prerequisites. The roadmap instead mandates an RBPF conditional on #188 and #198 ([probabilistic roadmap:267](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/docs/probabilistic-nowcast-forecast-roadmap.md#L267)). Its own text says not to build particle machinery before #198 at line 275 but allows particle mechanics/resampling ahead of #198 at lines 387–389. #121's intended earthquake process is log-linear healing, not the generic exponential in #190.

A second conflict: #198 calls itself a blocker for #191, #194, and #195, while the roadmap's execution order places #194 and #191 before #198 ([line 377](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/docs/probabilistic-nowcast-forecast-roadmap.md#L377)). This is resolvable by explicitly qualifying the dependency as the full seismic operator/fidelity gate; it should not stop a well/probe-only hydrologic pilot.

Before implementation, publish one bounded architecture decision with state ownership, exact/approximate likelihood assumptions, process-specific transition laws, and fidelity-specific dependencies. Split #190 into synthetic transition/particle research and conditioning with the common physical operator. The companion scientific audit should adjudicate whether the claimed conditional linearity is mathematically justified; a roadmap choice is not a proof.

### R6 — High: open/closed cannot serve as the book's implementation truth

[#204](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/204) proposes deriving chapter status from issue states. But [#110](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/110) closed because its scope was absorbed by [#29's comment](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/29#issuecomment-4977262561); #114 closed as a duplicate of [#72](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/72#issuecomment-4977262112). Those closures do not establish delivered SMAP/ERA5 evaluation. #120's closure is narrower than "hysteresis changes hydrologic fluxes," correctly retained in #176. #86 explicitly permits a negative finding and retaining the original SVM. Conversely, #45/#51/#54 have implementation comments and #60 checks them off while GitHub still marks them open.

Define closure dispositions: `implemented`, `validated`, `superseded`, `duplicate`, `negative result`, `scope withdrawn`, with linked acceptance evidence. Separate implementation, exercised-on-real-data, calibrated, and externally validated status. Preserve the proposed `uncalibrated assumption` label in #204's August comment. Generate documentation from these evidence records, not from bare closed/open counts.

This would also reduce repeated agent work on stale #20 (still described as a scaffold), #40 (body literally says addressed), #28 (all original tasks checked in comments; refinements remain), #82 (covariates fetched by #94), and #70 (daily PRISM forcing already part of the calibration narrative). Verify remaining scope before closing; do not bulk-close from this inventory alone.

### R7 — High: the three hazard lanes are recognized but their shared contract and acceptance are incomplete

Flood is now present: [#199–#202](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/199). Do not describe it as missing. The gap is integration: #199 says it is a consumer of #193, while [#193](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/193) specifies only landslide and liquefaction tasks. The scheduler lets #200 proceed after #187/#191 without #193, contradicting the epic's stated relationship. The main probabilistic roadmap's hazard phase also omits flood.

Define the common joint-member export in #187/#193 so each hazard can consume it independently. Give each lane a concrete integration/validation gate:

- **Flood:** #200 must define flux ownership, time-interval integration, cell-to-reach volume conservation, and what happens to the interflow routed within the soil model by #133/#174, so the same transferred water is not also counted as outlet discharge. #201/#202 then test routed timing/peaks and probabilistic skill on held-out periods. Inundation extent remains a separate conditional claim with observed extent where available. A basin-integrated source flux in #189 is not automatically a routed time-resolved discharge operator.
- **Landslide:** incorporate #128's [August pressure-closure comment](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/128#issuecomment-5351359241) into acceptance. Share the perched/interflow state across #130/#133/#174, add the observation plan for the poorly observed shallow store, and ensure #135's fine slope contract precedes shallow-failure validation. Separate the shallow infinite-slope pilot from a claim of validated deep-seated failure physics.
- **Liquefaction:** #141 must pin a specific published model/version/coefficient set and make the probability semantics explicit. Comparison with a WA DNR/Palmer susceptibility map is a useful benchmark; it does not by itself calibrate an earthquake-event probability. #142's [August comment](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/142#issuecomment-5351359070) correctly demands water-table-only truth and validation of the seasonal tail actually consumed. Decide between the title's sub-1.5 m gate and the body's sub-metre wording.

The v0.7 definition appropriately allows one initial hazard pathway ([probabilistic roadmap:416](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/docs/probabilistic-nowcast-forecast-roadmap.md#L416)); add a later program-level definition for all three hazards so "v0.7 complete" is not mistaken for the user's entire soil-twin objective achieved.

### R8 — Medium/high: the forecast plan preserves members but does not clearly commission their meteorological construction

[#191](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/191) requires calibrated FuXi ensembles and paired precipitation/temperature members. That is a good interface requirement. But #32 currently asks for method spread across GWL kriging/climate methods; #136 asks for one real FuXi run and bias correction; #71 still calls for GraphCast/ACE2. None of those bodies clearly assigns a calibrated meteorological-member source, perturbation/reforecast experiment, or required ensemble-size/compute decision.

Add a bounded task under the common forcing lane specifying how atmospheric members are obtained, how joint P/T spatial and temporal dependence is preserved, which retrospective archive calibrates spread and bias, and which held-out forecasts evaluate it. Keep #58's explicitly deferred Penman–Monteith enhancement optional when the chosen forcing contract supports the documented fallback. Update #71/#56/#73 to the actual intended FuXi/daily or subdaily path before agents execute old instructions.

### R9 — Medium/high: priority and work-unit shape reflect review history more than risk or deliverable ownership

[#177](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/177) bundles rain-on-snow, product inconsistency, unused Ksat, ET, and valley baseflow under "minor/P2"; #138 and #149 similarly contain substantive operator/tail-validation requirements. Meanwhile #40's addressed correlation wording is still global P0. #59's named atmospheric-river hindcast is a forecast claim gate but remains unmilestoned P2. The milestone-based queue can therefore do a broad P2 scientific bundle before a critical unmilestoned foundation.

Reprioritize by the next declared release's blocking risk, and split unrelated review bullets into coherent deliverables. Consolidate overlapping pairs/groups: #8/#23; #9/#46/#189; #45/#50/#165/#198; #64/#65/#187/#193/#200; #87/#131/#172; #130/#133/#174; #121–#124/#134/#143/#190; #71/#136. Some are legitimate foundation-versus-integration splits, not duplicates; assign one authoritative implementation owner and explicit reuse edges.

Keep Vs30 densification's user-recorded pause ([ROADMAP.md:129](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/ROADMAP.md#L129)) and #146's deferred full-triggering scope machine-readable. Mere placement after water work does not guarantee water acceptance passed, especially when a panel parks an item and the batch continues.

### R10 — Medium: human decisions and reviewer additions need durable incorporation into issue scope

Recent substantive comments are high-quality amendments, but older issue bodies remain independently executable instructions. Examples include #128's named pressure closure, #142's seasonal-tail criterion, #187's head/storage vocabulary, #189's classifier and already-landed operator, #192's out-of-fold residual/data requirements, and #205's baseline-tau estimate before switching. Those amendments should become versioned acceptance criteria, with the approving decision and the remaining unresolved point explicit.

The actual #163 latest parking record cites `unrecognised verdict None` for a persona. That is an automation/schema failure, not by itself a scientific question requiring the user to rule on anisotropy. Preserve real reviewer concerns while separating technical retry from scientific judgment. #186 does contain substantial substantive blocked design questions; do not erase that review or automatically restart the old plan.

For every dispatchable issue/group, require: bounded outcome/non-goals; implementation/acceptance dependencies; data availability and license/access status; allowed scientific choices versus human decisions; designated panel expertise; named falsification and acceptance artifacts; closure disposition; and exact accepted plan revision. This can be inherited from a shared template, not copied verbatim into every issue. No new contact with outside parties is authorized by this audit.

## Proposed practical critical path

1. **Repair the instruction surface and actual gates.** Correct #119–#125, incorporate accepted comments, reconcile #100/v0.4, mark true deferments, normalize priority/milestones, and make one dependency/evidence registry drive docs and scheduler. Resolve/retry parked panel cases by their actual cause.
2. **Run four independent foundation lanes.** (a) #186 uncertainty correctness with bounded human-reviewed scope; (b) #52/#187 canonical storage and observation schema design; (c) #89/#172/#137 with coordinated #131/#173/#174 physics and a multi-year spin-up/held-out experiment, rather than independent edits to the same reservoir; (d) #153/#155/#156 reproducible data fixtures and scalable-backend evidence, using existing #154/#163 progress rather than redoing it. Draft the schema while scientific release decisions remain open.
3. **Complete one observed hydrologic cycle on a bounded pilot.** Existing well/probe records → #189 → #188 → #192 → #194, with fixed station/time holdouts, member persistence, explicit analysis increments, and measured calibration/skill. No full seismic attribution or all-domain run is needed to establish this vertical slice.
4. **Build meteorological forcing and forecast in parallel with pilot evaluation.** Unify #71/#136/#32 into a commissioned member source and bias/uncertainty experiment, then #191 and the state/forecast portion of #195. Document cost and working spatial/cadence scale.
5. **Integrate hazard pilots independently through the same members.** Flood #200→#201→#202; landslide #128 plus appropriate pressure/terrain/storage, then #129; liquefaction #141/#143/#144 plus #142 truth/tail gate. Publish the implemented scope and unsupported regions explicitly. Failure of one research lane need not prevent validation of another.
6. **Add the distinct seismic/memory research lane.** Real #30 data and shared #198 operator after the hydrologic hysteresis requirement; #164/#165/#168/#169; repaired event/damage/disturbance issues; then explicitly selected #190 conditional inference architecture. #205 remains contingent on diagnostics. Stehekin, Vs30 refinement, deep-triggering, and extra PET fidelity follow evidence and declared priorities.

The next meaningful demonstration should be a reproducible, held-out, member-preserving water-state pilot feeding one hazard at its actual support. This gives every later modeling layer a fixed reference and a testable reason to exist.
