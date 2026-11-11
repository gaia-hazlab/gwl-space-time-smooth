# Reviewer round: twin-atmospheric-scientist (2026-11-11)

Read-only agent report, transcribed. Tags are the agent's: "#N" issue body in the 2026-11-09
snapshot; `file:line` opened; "online" = page the agent fetched on 2026-11-11 (URLs at the end; I
did not re-fetch them); "recalled" = from the agent's memory, unverified. My check of the issue and
code probes is in `adopt-reject.md`.

## Verdict

The forecast path produces a deterministic, daily, precipitation plus mean-temperature antecedent
state. It is not an ensemble. The roadmap has no wildfire consumer, no hourly forcing record, no
physics ensemble baseline, and no hindcast wind, humidity or radiation. The ensemble work does not
need the GPU run of #136 if an operational ensemble is taken as the member source.

## Leads

| Lead | Verdict | Evidence |
|---|---|---|
| L1 wind, humidity, radiation | partly | nothing in `src/` ingests them; Hargreaves-Samani at `fetch_prism_daily.py:42-56`; #58 deferred and held; #243 owns forecast PET; #234 needs wind with no source |
| L2 deterministic forecast path | confirmed | `deterministic([str(start_time)], nsteps, model, GFS(), None)` at `fetch_earth2studio.py:149`; outputs `precip_mm`, `tmean_c` only (`:164`); daily resample `:156-157` discards Tmax/Tmin and wind |
| L3 ensemble construction | partly | #241 "Fix N_members against the Tillicum H200 budget"; #241 blocked by #136 and #187; #242, #243 blocked by #136 |
| L4 model coverage | partly | code wires FuXi and GraphCastSmall (`:54`); #195 scores against climatology and persistence; no numerical-weather-prediction baseline anywhere |
| L5 forecast downscaling | confirmed | #263 "Downscale tmean from the PRISM cell-mean elevation to the 90 m DEM"; no reference elevation for FuXi orography; wind and humidity have no issue |
| L6 hourly forcing | partly | MRMS appears in #132, #224, #99 as event or comparison only; zero hits for AORC, HRRR, Stage IV |
| L7 wildfire consumer | confirmed | zero hits for fuel moisture, VPD, ERC, NFDRS, KBDI |

## Forcing variables

| Variable | Hindcast | Forecast | To 90 m | Bias correction | Owner |
|---|---|---|---|---|---|
| Precipitation | PRISM daily 4 km | FuXi 0.25 degrees, daily | #242 | #136, #241 | #242, #241, all blocked |
| 2 m temperature, mean | PRISM 4 km | FuXi daily mean | #263, PRISM only | none | #263, partial |
| Tmax, Tmin | PRISM 4 km | none | none | #243 | #243 |
| 10 m wind, gust | none | none | none | none | #58 deferred; gust no owner |
| Dewpoint, vapour-pressure deficit | none | none | none | none | #58 deferred; no owner |
| Shortwave, longwave | none | none | none | none | #58 deferred, hindcast only |
| Snow level | implicit 0 to 4 degC ramp (`forecast.py:58-60`) | same | none | none | no owner |

## AI ensembles

Online (agent, 2026-11-11): the earth2studio prognostic list includes AIFSENS, AIFS2ENS, FCN3,
AtlasCRPS, Aurora1p5Ensemble, GenCastMini, StormCastCONUS, StormScopeMRMS, with no precipitation
information on that page; ECMWF's AIFS ENS became operational on 2025-07-01 with 51 members at 31 km
against 9 km for the physics ensemble; WeatherNext 2 produces "hundreds" of outcomes at 0 to 15 days.
Recalled, unverified: GenCast at 0.25 degrees with 12-hour steps includes precipitation; no AI model
gives calibrated kilometre-scale precipitation at 1 to 15 days; StormCast emulates HRRR for hours.

Requirements proposed: at least 50 members (at 20 the smallest non-zero tail probability is 0.05);
physics baselines ECMWF ENS and GEFS, HRRR for 0 to 48 h; verification on the #305 events against
MRMS and gauges, not PRISM, with basin-mean 24 h and 72 h thresholds at 50, 100, 150 mm,
freezing-level error, landfall timing of integrated vapour transport, CRPSS against ECMWF ENS by
lead, Brier skill and reliability, then Brier skill on soil-saturation thresholds. Decisive test:
AI CRPSS for 72 h precipitation against ECMWF ENS >= 0 at leads 1 to 5, otherwise use ENS directly.

## Wildfire

Export from the twin: root-zone moisture percentile, cumulative AET minus PET deficit, SWE melt-out
date. Atmospheric side only: 1, 10, 100, 1000-hour dead fuel moisture, vapour-pressure deficit,
wind, energy release component. Soil limitation is not established for the west side: for the 2020
western Oregon fires "wind was the major driver" under record fuel aridity (online, Evers et al.
2022, Fire 5:41). Decisive test: late-summer soil-moisture percentile adds AUC over an
energy-release-component-only model for west-side fires on held-out years. Validation data
(recalled): RAWS 10-hour fuel sticks, the National Fuel Moisture Database, MTBS, satellite live fuel
moisture (Rao et al. 2020), gridMET fm100, fm1000, ERC.

## National Water Model (NWM)

Online (water.noaa.gov/about/nwm): MRMS precipitation for the analysis, HRRR/RAP short range, GFS
medium range; "streamflow observations are assimilated", plus reservoirs; Noah-MP land model with
"saturated subsurface flow routing on a 250m grid"; short range 18 h deterministic. Recalled,
unverified: four soil layers to 2 m, a conceptual exponential groundwater bucket, no soil-moisture
or snow assimilation.

Experiment: identical forcing and routing in two arms; arm A open-loop NWM initial states, arm B
Noah-MP soil layers and SWE replaced at initialisation by the twin's state with a volume-conserving
map; score event volume, peak and timing on >= 10 #305 events at gauges excluded from nudging;
skill shown if the block-bootstrap interval of the KGE difference excludes 0.

## Earthnote (agent read of its code, online)

ECMWF data is `oper` only, no ensemble, capped at 144 h; HRRR wind and temperature regridded to
0.1 degrees; rain frames are uint8 on a square-root scale saturating near 103 mm; no humidity or
radiation; the code notes NWS keeps "only about 30 days" of gauge observations. Use for event
indexing, consequence labels and a deterministic baseline; re-fetch native GRIB before any use as forcing.

## Proposals

1. Freeze the November 2026 event from Earthnote with native GRIB and checksums; manifest frozen within 30 days of the event.
2. Hourly observed forcing record (MRMS Pass 2, AORC) aggregated to the 12-12 UTC day, mass conserved to 1e-6.
3. Amend #58: hindcast wind, vapour-pressure deficit, radiation from gridMET or ERA5-Land.
4. Amend #241: >= 50 members; AIFS-ENS against ECMWF ENS and GEFS; drop the #136 blocker.
5. Forecast forcing extension: Tmax/Tmin, wind, dewpoint, freezing level; lapse rate to model orography.
6. Wildfire consumer gate: AUC gain over ERC-only > 0 on held-out years, otherwise "not a claim".
7. NWM state-swap experiment.

Decision raised: whether an operational ensemble (ECMWF ENS or AIFS-ENS) replaces FuXi as the member source.

Sources fetched by the agent: nvidia.github.io/earth2studio/main/modules/models_px/;
ecmwf.int/en/about/media-centre/news/2025/ecmwfs-ensemble-ai-forecasts-become-operational;
blog.google/technology/google-deepmind/weathernext-2/; water.noaa.gov/about/nwm;
par.nsf.gov/biblio/10353231; raw.githubusercontent.com/maleenkidiwela/Earthnote (weather.py, event.py, rivers.py).
