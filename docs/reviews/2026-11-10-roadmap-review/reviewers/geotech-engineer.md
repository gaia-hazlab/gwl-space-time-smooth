# Reviewer round: twin-geotech-engineer (2026-11-11)

Read-only agent report, transcribed. "#N" = read from that issue in the 2026-11-09 snapshot;
`file:line` = the agent opened that file; "est." = the agent's arithmetic, in no issue. Nothing was
rerun by the agent. My check of each probe is in `adopt-reject.md`.

## Verdict

Coupling in the open roadmap runs one way: hydrology drives stress. The hazard-facing mechanical
products (u(z,t), sigma'(z,t), P(FS<1)) are P2 and wait on the dv/v operator. No unit in the
structural model carries a strength or density parameter. Three of five decisions below would
receive a quantity they cannot use.

## Leads

| Lead | Status | Evidence |
|---|---|---|
| L1 one-way coupling | confirmed | #190 original body keeps damage "separate from hydrologic storage while being able to modify hydraulic and strength parameters"; #50, #248 add Skempton-B loading inside the dv/v operator only; #291 treats deformation as an observation of head; no compaction package (CSUB) in any issue |
| L2 sigma'(z,t), u(z,t) products | confirmed, plus a dependency error | `soil_mechanics.py:64-67` raises; `dvv_coupling.py:48,89` SIGMA0 = 10 kPa; #250 delivers "Vs(z,t), Vs30(t), sigma'(z,t)" with no u and is blocked by #198; pore pressure from MODFLOW heads needs no dv/v operator |
| L3 suction in #128 | partly | the "In plain words" line says "with suction"; acceptance tests only `{'hydrostatic','slope_parallel'}`; `hydro_state.py:221-223` returns suction "as zero"; no issue has an unsaturated-strength acceptance |
| L4 Landlab export | confirmed, plus one | 2-D AAIGrid, sigma sidecar, no member or depth dimension; recharge sigma = 0.1 x mean (`landlab_export.py:319`); the seasonal-high DTW field is exported with no sigma (`:217-218`) |
| L5 deep-seated | confirmed | #252 is P2; its input "#130's regional store" is a stale pointer (#130 is now the perched cap layer); no 3-D head export |
| L6 liquefaction DTW | confirmed, plus an inconsistency | #261 "annual P10 over at least N water years"; #138 m2 "annual-minimum DTW with a GEV return level": two definitions of seasonal high; #146 P2 and held; #81 paused so #144 has no anchor |
| L7 structure versus mechanics | confirmed | #276 carries elevation, thickness, mask, sigma only; its top unit merges "Holocene alluvium / Vashon recessional outwash", the distinction #84 calls first-order |
| L8 post-fire debris flow | confirmed | #132: "State explicitly that I15 is out of reach of the forcing products"; MTBS/dNBR ingest sits inside #255, blocked by #134 |

## What each decision needs and gets

| Decision | Quantity, units | Depth | Resolution | Uncertainty form | Issues | Usable as delivered? |
|---|---|---|---|---|---|---|
| Storm shallow-landslide triggering | u or psi at the slip surface (kPa), suction included | 0.5-3 m | 1-10 m, hourly | P(FS<1) per member | #128, #130, #133, #135 | No: 90 m DTW gives h_w near 0 on most hillslopes (#128) |
| Regional susceptibility | recharge + interflow (mm/d) as a distribution; transmissivity | soil column | 10-30 m, annual | sampled distribution | #254, #129 | No until #254: export omits interflow; sigma = 0.1 x mean is a convention |
| Liquefaction screen | seasonal-high DTW (m) in liquefiable units | 0-10 m | 100 m-1 km | P(DTW<d*) | #261, #142, #141 | No: published model static in DTW (#260); rerun gated by #270 |
| Site class | Vs30 (m/s) | 0-30 m | 200 m | P(NEHRP class) | #144 | Partly: sigma has no measured anchor (#81 paused) |
| Post-fire debris flow | I15 (mm/h), dNBR, erodibility | surface | basin | logistic P | #255 | The twin contributes nothing; its soil moisture is "exploratory" |

## Coupling (agent estimate)

State one-way coupling as a design decision with validity bound skeletal strain
eps_v ~ S_ske x dh <= 1e-2. Kozeny-Carman gives dlnK ~ 7.6 eps_v at porosity 0.35, so the bound caps
induced dlnK near 0.08. Glacial units (S_s 1e-5 to 1e-4 /m, dh 5 m) give eps_v <= 5e-4. Peat,
organic tideflat and fill (S_ske near 1e-2 /m) violate it; those are the liquefiable units.
Shaking-induced pore pressure is the triggering itself and belongs to the hazard model (#145).
Test: the #291 arithmetic extended to report eps_v per hydrostratigraphic unit.

## Minimal parameter set per unit (each with prior and sigma)

Moist and saturated unit weight; phi' and c'; van Genuchten alpha and n; Vs(z) parameters; fines
content; (N1)60 or q_c1N; overconsolidation ratio; S_ske. Candidate Washington sources named by the
agent, none opened: DNR geology and boring databases, WSDOT borings, GeoMapNW, CPT archives. No
issue ingests them: #277 brings lithology text only, #146 is deferred.

## Proposals

1. New: geotechnical parameter table per hydrostratigraphic unit on #276. Acceptance: held-out
   boreholes inside the 90 % interval for unit weight and phi' at a rate >= 0.8. Blocked by #276, #277.
2. Amend #128: third closure `suction_stress` (Lu-Likos). Acceptance: at h_w = 0,
   FS - FS_dry = sigma_s tan(phi') / (gamma z sin(beta) cos(beta)) to 1e-6; at S_e = 1 equals the saturated closure.
3. Amend #250: u(z,t) in kPa and sigma'(z,t) on (member, time, depth, y, x) at 0.5, 1, 2, 3, 5, 10 m.
   Acceptance: hydrostatic column u = gamma_w (z - DTW) to 1e-6 kPa. Blocked by #187 only; drop #198; raise to P1.
4. Amend #252: per-member MODFLOW layer heads and geometry readable by Scoops3D.
5. Amend #261, #142: P(DTW < d*) for d* in {1, 2, 3} m plus a GEV annual-minimum return level.
   Acceptance: Brier skill > 0 against climatology on held-out water-table wells.
6. Amend #255: design-storm I15 in place of forcing (values recalled by the agent, not from an issue).
