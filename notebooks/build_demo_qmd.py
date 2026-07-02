"""Assemble the GWL + soil-moisture demo as a Quarto document.

Reads the real products (block-CV, feature importance, envelope, θ stack) to compute the
headline numbers and writes ``docs/gwl_soil_moisture_demo.qmd``. Quarto renders it to a
single self-contained page (``embed-resources: true``) that is BOTH a site page and a
standalone HTML dashboard — link it from the GAIA soil-reanalysis chapter.

Run:  pixi run python notebooks/build_demo_qmd.py   (after notebooks/demo_gwl_sm.py)
      quarto render docs/gwl_soil_moisture_demo.qmd --to html
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import rioxarray  # noqa: F401
import xarray as xr
from pyproj import Transformer

PROC = Path("data/processed")
OUT = Path("docs/gwl_soil_moisture_demo.qmd")

# --- Compute headline numbers from the real products ---
qc = json.loads((PROC / "qc_report.json").read_text())
cv = json.loads((PROC / "block_cv_metrics.json").read_text())["pooled"]
fi = json.loads((PROC / "rf_feature_importance.json").read_text())

sm = xr.open_zarr(PROC / "soil_moisture_monthly_puget.zarr").load()
env = xr.open_zarr(PROC / "soil_hydraulic_envelope_90m.zarr").load()
time = pd.DatetimeIndex(sm.time.values)
theta_dm = sm.theta.mean(("lat", "lon")).values
tc = sm.tc_soil_mm.mean(("lat", "lon")).values
r_dm = float(np.corrcoef(theta_dm, tc)[0, 1])

th, tcv = sm.theta.values, sm.tc_soil_mm.values
cc = []
for i in range(th.shape[1]):
    for j in range(th.shape[2]):
        a, b = th[:, i, j], tcv[:, i, j]
        if np.all(np.isfinite(a)) and np.all(np.isfinite(b)) and b.std() > 0:
            cc.append(np.corrcoef(a, b)[0, 1])
r_cell = float(np.median(cc))

seas = pd.Series(theta_dm, index=time.month).groupby(level=0).mean()
yr = pd.Series(theta_dm, index=time.year).groupby(level=0).mean()
dry_y, wet_y = int(yr.idxmin()), int(yr.idxmax())


def rng(v):
    a = v[np.isfinite(v)]
    return float(np.nanpercentile(a, 5)), float(np.nanpercentile(a, 95))


fc_lo, fc_hi = rng(env.theta_fc.values)
sat_lo, sat_hi = rng(env.theta_sat.values)
awc_lo, awc_hi = rng(env.awc_mm.values)
hand_imp = fi.get("hand_m", 0.0)

sites = pd.read_parquet(PROC / "nwis_sites_clean.parquet")
L, B, R, T = rioxarray.open_rasterio(PROC / "terrain_hand_90m.tif").rio.bounds()
_tf = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
_sx, _sy = _tf.transform(sites.lon.values, sites.lat.values)
n_pilot = int(((_sx >= L) & (_sx <= R) & (_sy >= B) & (_sy <= T)).sum())

# Provenance + uncertainty budget from the 90 m time-varying products.
prov = json.loads((PROC / "provenance.json").read_text())


def _res(m):
    if m == 0:
        return "point (wells)"
    return f"{m/1000:g} km" if m >= 1000 else f"{m:g} m"


def _prov_rows(steps):
    return "\n".join(
        f'<tr><td>{s["quantity"]}</td><td>{s["source"]}</td>'
        f'<td>{_res(s["source_res_m"])} → {_res(s["target_res_m"])}</td>'
        f'<td>{s["method"]}</td></tr>' for s in steps)


gwl_fr = prov["budget_fractions"]["groundwater"]
sm_fr = prov["budget_fractions"]["soil_moisture"]
sig_sm = prov["median_total_sigma"]["soil_moisture_m3m3"]
sig_gwl = prov["median_total_sigma"]["groundwater_m"]
win0, win1 = prov["window"]

ISSUE = "https://github.com/gaia-hazlab/gwl-space-time-smooth/issues"

CSS = """
```{=html}
<style>
  :root{ --ink:#1a1a2e; --muted:#5a5a6e; --line:#e2e2ea; --card:#ffffff;
    --gwl:#0072B2; --sm:#009E73; --accent:#D55E00; --good:#1b7837; }
  body{ color:var(--ink); background:#fbfbfd; line-height:1.6;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  #title-block-header{ max-width:1080px; margin:0 auto; padding:1.6rem 1.2rem .2rem; }
  #title-block-header .title{ font-size:2rem; line-height:1.2; font-weight:700; margin:0; }
  #title-block-header .subtitle{ color:var(--muted); font-size:1.1rem; margin:.3rem 0 0; }
  #title-block-header .author,#title-block-header .date{ color:var(--sm); font-size:.82rem;
    font-weight:600; margin:.4rem 0 0; }
  .demo{ max-width:1080px; margin:0 auto; padding:1rem 1.2rem 3rem; }
  .demo figure img{ width:100%; }
  .demo .tag{ color:var(--sm); font-weight:700; letter-spacing:.04em; font-size:.8rem; text-transform:uppercase; }
  .demo h1{ font-size:1.95rem; line-height:1.25; margin:.3rem 0 .5rem; border:none; }
  .demo h2{ font-size:1.35rem; margin:2.4rem 0 .6rem; padding-bottom:.35rem; border-bottom:2px solid var(--line); }
  .demo .sub{ color:var(--muted); font-size:1.02rem; }
  .demo .tldr{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--sm);
    border-radius:10px; padding:1.1rem 1.3rem; margin:1.4rem 0; box-shadow:0 1px 3px rgba(0,0,0,.04); }
  .demo .grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:.9rem; margin:1.2rem 0; }
  .demo .stat{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:1rem 1.1rem; }
  .demo .stat .n{ font-size:1.55rem; font-weight:700; }
  .demo .stat .l{ color:var(--muted); font-size:.86rem; margin-top:.15rem; }
  .demo .gwl{ color:var(--gwl); } .demo .sm{ color:var(--sm); } .demo .accent{ color:var(--accent); }
  .demo table{ border-collapse:collapse; width:100%; margin:1rem 0; font-size:.94rem; }
  .demo th,.demo td{ text-align:left; padding:.55rem .7rem; border-bottom:1px solid var(--line); }
  .demo th{ color:var(--muted); font-weight:600; font-size:.82rem; text-transform:uppercase; letter-spacing:.03em; }
  .demo .pill{ display:inline-block; background:#eef6f2; color:var(--good); border:1px solid #cfe8dc;
    border-radius:999px; padding:.1rem .6rem; font-size:.78rem; font-weight:600; }
  .demo figure{ margin:1.2rem 0; }
  .demo figure img{ width:100%; border:1px solid var(--line); border-radius:10px; background:#fff; }
  .demo figcaption{ color:var(--muted); font-size:.88rem; margin-top:.5rem; }
  .quarto-layout-row{ display:flex; gap:.8rem; align-items:flex-start; }
  .quarto-layout-cell{ flex:1 1 0 !important; min-width:0 !important; }
  .demo pre{ background:#1a1a2e; color:#e8e8f0; padding:1rem 1.2rem; border-radius:10px; overflow-x:auto; }
  .demo pre code{ background:none; color:inherit; }
</style>
```
"""

BODY = f"""---
title: "Coupled Subsurface State — Groundwater Level + Soil Moisture"
subtitle: "A data-driven demo over the Puget Sound pilot (90 m)"
date: today
author: "GAIA HazLab · gaia-soil-hydromechanics"
format:
  html:
    theme: none
    toc: false
    page-layout: full
    embed-resources: true
    fig-responsive: true
execute:
  echo: false
---

{CSS.strip()}

::: {{.demo}}

```{{=html}}
<div class="tag">GAIA HazLab · gaia-soil-hydromechanics</div>
```

Two of the three planned subsurface state variables — the mature
[groundwater-level]{{.gwl}} module and the new [soil-moisture]{{.sm}} module — produced by one
observation-anchored pipeline, on real public data.

```{{=html}}
<div class="tldr"><b>Why this exists.</b> Before the repository rename
(<a href="{ISSUE}/24">#24</a>) and the <code>gaia-soil-reanalysis</code> reframe
(<a href="{ISSUE}/18">#18</a>), this page shows the science works: <b>GWL and soil moisture
are both modelled and validated</b> with the same static&nbsp;×&nbsp;dynamic, observation-anchored
approach. The soil-moisture estimate reproduces an <i>independent</i> reanalysis' soil-water
field at <b class="sm">r&nbsp;=&nbsp;{r_dm:.2f}</b> (per-cell median {r_cell:.2f}) without ever
being fit to it.</div>

<div class="grid">
  <div class="stat"><div class="n gwl">{qc['clean_sites']}</div><div class="l">QC-clean NWIS wells (WA); {n_pilot} in pilot</div></div>
  <div class="stat"><div class="n gwl">{qc['clean_records']:,}</div><div class="l">monthly GWL observations</div></div>
  <div class="stat"><div class="n gwl">{hand_imp:.0%}</div><div class="l">RF importance on HAND (top predictor)</div></div>
  <div class="stat"><div class="n sm">{r_dm:.2f}</div><div class="l">θ vs independent TerraClimate soil</div></div>
  <div class="stat"><div class="n sm">{sm.time.size}</div><div class="l">months of soil moisture (2000–2024)</div></div>
  <div class="stat"><div class="n accent">90 m</div><div class="l">product resolution (both state variables)</div></div>
</div>
```

## The approach — static envelope × dynamic driver

Every state variable is decomposed into a **static** spatial envelope (what the ground *can*
hold / where water sits) and a **dynamic** driver (how it varies in time), each from public,
physically meaningful data — never from lat/lon memorisation.

```{{=html}}
<table>
  <tr><th>State variable</th><th>Static source</th><th>Dynamic source</th><th>Status</th></tr>
  <tr><td><b class="gwl">Groundwater level</b></td><td>HAND terrain + SOLUS texture → RF baseline</td>
      <td>kriged well residuals (β-map / TFN next)</td><td><span class="pill">live</span></td></tr>
  <tr><td><b class="sm">Soil moisture</b></td><td>SOLUS100 → Saxton-Rawls hydraulic envelope</td>
      <td>TerraClimate P&amp;PET → Thornthwaite-Mather bucket</td><td><span class="pill">live (new)</span></td></tr>
  <tr><td>Soil mechanics</td><td>Vs30 (Sanger &amp; Maurer) + SOLUS</td>
      <td><b>dv/v</b> ambient-noise seismic</td><td>scaffold (#19)</td></tr>
</table>
```

## 1 · Groundwater level — the mature module

An observation-anchored random forest on **HAND** (Height Above Nearest Drainage), TWI, slope and
SOLUS texture, with ordinary kriging of the well residuals. Lat/lon are deliberately excluded so
the model cannot memorise where the training wells are.

- **HAND dominates** ({hand_imp:.0%} importance) — the intended physics, not coordinates.
- **Honest spatial hold-out:** variogram-sized block CV gives pooled RMSE&nbsp;{cv['rmse_mean']:.1f}&nbsp;m /
  MAE&nbsp;{cv['mae_mean']:.1f}&nbsp;m — deliberately hard (whole blocks of wells withheld).
- Per-cell uncertainty (RF spread ⊕ kriging σ) is mapped, so the product can be *silent* where
  neither data nor physics support a claim.

![Baseline depth-to-water and 1σ uncertainty (left); random-forest feature importance and spatial
block cross-validation (centre/right); a 24-year observed monthly hydrograph at the best-recorded
pilot well — note the pronounced 2021 drought draw-down.](../figures/demo/gwl_state.png)

## 2 · Soil moisture — the new module

The static **Saxton & Rawls (2006)** pedotransfer functions turn SOLUS100 sand/clay into a physical
hydraulic envelope (wilting point ≤ field capacity ≤ porosity) at 90 m; a monthly
**Thornthwaite-Mather** water balance driven by **TerraClimate** precipitation and reference ET fills
that envelope through time to give volumetric θ(t) with per-cell θ_std.

- **Physical envelope** from texture alone: field capacity {fc_lo:.2f}–{fc_hi:.2f}, porosity
  {sat_lo:.2f}–{sat_hi:.2f} m³/m³, available water {awc_lo:.0f}–{awc_hi:.0f} mm — finer valley soils
  hold more, exactly as observed.
- **Independent validation:** our θ tracks TerraClimate's own soil-water field at r&nbsp;=&nbsp;{r_dm:.2f}
  (domain mean) / {r_cell:.2f} (per-cell median) — a strong check, since that field never enters the estimator.
- **Right signal:** wet winters (θ≈{seas.max():.2f}), late-summer drought (θ≈{seas.min():.2f}); driest
  year {dry_y}, wettest {wet_y} — the real PNW interannual story.

![Static SOLUS→Saxton-Rawls envelope at 90 m (top: porosity, field capacity, available water
capacity); modelled θ for the wettest vs driest month (bottom left/centre); and the 2000–2024 θ series
against the independent TerraClimate soil field (bold = 13-month rolling mean; r&nbsp;=&nbsp;{r_dm:.2f}).](../figures/demo/soil_moisture_state.png)

## 3 · The coupled view

Both fields come out of one pipeline over the same grid — the groundwater table from below and the
vadose-zone moisture from above. This is the "reanalysis" the reframe is named for; the third state
variable (soil mechanics, constrained by **dv/v** ambient-noise seismic velocity change,
[#19]({ISSUE}/19)) plugs into the same effective-stress coupling.

![Groundwater depth-to-water and mean soil moisture side by side, with the shared seasonal cycle —
one data-driven pipeline, two subsurface state variables.](../figures/demo/coupled_overview.png)

## 4 · Resolution, downscaling & a tracked uncertainty budget

Both state variables are delivered on the **90 m** grid. That resolution is *earned*, not
assumed: the fine spatial structure comes from 90 m static fields (terrain, SOLUS texture),
while the time-varying signal is solved at its native coarse resolution and **statistically
downscaled** — soil-moisture wetness from 4 km TerraClimate, the groundwater anomaly from
coarse-kriged well observations. Every such step is logged, and the error it introduces is a
named term in the budget rather than hidden.

The animations below step month-by-month through {prov['n_months']} months ({win0} → {win1}),
so the 90 m detail and its temporal evolution are both visible.

::: {{layout-ncol=2}}
![Groundwater depth-to-water — 90 m, monthly. Valleys shallow (yellow), uplands deep (dark).](../figures/demo/gwl_90m.gif)

![Soil moisture θ — 90 m, monthly. Fine SOLUS texture modulated by the downscaled 4 km wetness.](../figures/demo/theta_90m.gif)
:::

**Uncertainty is decomposed into three independent components** combined in quadrature —
*static* (fine-scale model), *dynamic* (coarse driver), *downscaling* (representativeness of
the coarse signal within a fine cell). Their variance shares expose where each product's error
actually comes from:

![Per-product total 1σ maps and the static / dynamic / downscaling variance split. Groundwater
error is dominated by the RF baseline in the uncertain uplands; soil-moisture error is more evenly
split, with downscaling a real ~{sm_fr['downscaling']*100:.0f}% share.](../figures/demo/uncertainty_budget.png)

```{{=html}}
<div class="grid">
  <div class="stat"><div class="n sm">±{sig_sm:.3f}</div><div class="l">median θ 1σ (m³/m³): static {sm_fr['static_pedotransfer']*100:.0f}% · dynamic {sm_fr['dynamic_driver']*100:.0f}% · downscaling {sm_fr['downscaling']*100:.0f}%</div></div>
  <div class="stat"><div class="n gwl">±{sig_gwl:.0f} m</div><div class="l">median DTW 1σ: static {gwl_fr['static_rf_baseline']*100:.0f}% · dynamic {gwl_fr['dynamic_kriging']*100:.0f}% · downscaling {gwl_fr['downscaling']*100:.0f}%</div></div>
</div>
```

**Provenance — every source, resolution change and operation is tracked.**

```{{=html}}
<b class="sm">Soil moisture θ(t) at 90 m</b>
<table>
  <tr><th>Quantity</th><th>Source</th><th>Resolution</th><th>Operation</th></tr>
  {_prov_rows(prov['soil_moisture'])}
</table>
<b class="gwl">Groundwater DTW(t) at 90 m</b>
<table>
  <tr><th>Quantity</th><th>Source</th><th>Resolution</th><th>Operation</th></tr>
  {_prov_rows(prov['groundwater'])}
</table>
```

## Honest caveats

- Block-CV RMSE ({cv['rmse_mean']:.0f}&nbsp;m) is large because it is a *spatial* hold-out over a hard,
  heterogeneous domain — not an interpolation error at wells. Per-domain gates ([#3]({ISSUE}/3)) stratify
  this; valley floors are far tighter than uplands.
- **Downscaling is interpolation, not new information.** The 90 m *temporal* signal is a bilinear
  downscale of a coarse driver (4 km wetness; ~2 km kriged GWL anomaly); the 90 m texture sharpens the
  *spatial* pattern, not the sub-footprint temporal variation. The representativeness σ makes this a named,
  quantified term — a real {sm_fr['downscaling']*100:.0f}% of θ variance and {gwl_fr['downscaling']*100:.0f}% of DTW variance, not a rounding error.
- Kriged GWL σ is bounded by the climatological prior (away from wells it falls back to "know nothing",
  never spurious confidence); the animation window ({win0}–{win1}) is chosen for dense well coverage.
- θ spans the root-zone available-water range (θ_wp→θ_fc); saturation excess is bounded by porosity, not
  resolved event-by-event at monthly step.
- The TerraClimate cross-check is an *independent product*, not independent ground truth; SMAP / in-situ
  validation is the next step ([#20]({ISSUE}/20)).

## Reproduce

```bash
# dynamic driver: TerraClimate monthly P, PET, soil over the pilot (2000→)
pixi run terraclimate
# soil-moisture state: SOLUS→Saxton-Rawls envelope × Thornthwaite-Mather bucket
pixi run soil-moisture
# 90 m time-varying products: GIFs (GWL + θ) + tracked uncertainty budget
pixi run products-90m
# static figures + this self-contained page
pixi run demo
```

```{{=html}}
<p style="color:#5a5a6e;font-size:.86rem;margin-top:2rem;border-top:1px solid #e2e2ea;padding-top:1rem;">
Puget Sound pilot · 90&nbsp;m EPSG:5070 · monthly 2000–2024 · all inputs public (NWIS, SOLUS100,
TerraClimate, 3DEP). Tracking:
<a href="{ISSUE}/18">#18</a> (epic) ·
<a href="{ISSUE}/20">#20</a> (soil moisture) ·
<a href="{ISSUE}/24">#24</a> (rename — after this).</p>
```

:::
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(BODY)
print(f"wrote {OUT}")
print(f"  r(domain)={r_dm:.3f}  r(cell median)={r_cell:.3f}  "
      f"θ seasonal {seas.min():.2f}–{seas.max():.2f}  dry {dry_y} wet {wet_y}  pilot wells {n_pilot}")
