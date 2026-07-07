"""dv/v module showcase: stations -> freq/depth kernels -> banded dv/v (UQ) -> SM & WTD.

Four panels telling the whole measurement chain:

  1. UW + CC stations (real seisfetch inventory) over the Puget/Cascade pilot domain.
  2. Rayleigh frequency->depth sensitivity kernels G(f, z) (codameter/disba), peak depth ~ Vs/3f,
     with the water-table depth that splits vadose (soil moisture) from saturated (WTD).
  3. Banded dv/v(t) recovered by coda stretching, with the honest processing-ensemble
     uncertainty band (within + methodological), not the Weaver floor alone.
  4. Depth-separated result: dVs/Vs(z) posterior split at the water table into soil moisture
     (shallow) and RELATIVE water-table depth (deep), each with propagated uncertainty.

Panel 1 uses live metadata (cached). Panels 2-4 run the pipeline on a controlled synthetic with a
known imposed dv/v (compute-later policy); the same calls run on real NCFs once cached.

Run:  pixi run python notebooks/make_dvv_figures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal

from src.data.fetch_seismic import PUGET_CASCADES_BBOX, fetch_inventory
from src.models import dvv
from src.models.anchor import assimilate_points

mpl.use("Agg")
OUT = Path("figures/demo"); OUT.mkdir(parents=True, exist_ok=True)
ASSETS = Path("docs/assets"); ASSETS.mkdir(parents=True, exist_ok=True)
PROC = Path("data/processed")
INK, MUTED, GRID = "#1a1a2e", "#5a5a6e", "#d9d9e0"
OI = {"uw": "#0072B2", "cc": "#D55E00", "sm": "#E69F00", "wtd": "#009E73", "band": "#CC79A7"}
from src.viz.fonts import register_inter
register_inter(size=11)
plt.rcParams.update({"axes.titlecolor": INK, "axes.titleweight": "bold",
                     "axes.edgecolor": MUTED, "figure.dpi": 130})
WATER_TABLE_KM = 0.03          # 30 m nominal vadose/saturated boundary for the demo


def _synthetic(n_epoch=73, sr=25.0, maxlag=60.0, noise=0.05, seed=0):
    """Physically realistic band-dependent synthetic: low freq -> slow GWL, high freq -> fast ET/rain.

    Builds a depth-time truth m(z,t), forwards it through the band kernels, and synthesizes per-band
    NCFs so each band recovers its OWN dv/v. Returns (lags, ref, series, dvv_bands[n_band,n_epoch], t).
    """
    from codameter.uq_depth import band_sensitivity_matrix

    prof = dvv.pnw_velocity_profile(400.0)
    fc = np.sqrt(np.asarray(dvv.DEFAULT_BANDS)[:, 0] * np.asarray(dvv.DEFAULT_BANDS)[:, 1])
    K = band_sensitivity_matrix(prof, fc)
    m, t = dvv.synthetic_depth_time_truth(K.depths_km, n_epoch=n_epoch, dt_days=5.0)
    dvv_bands = dvv.forward_banded_dvv(m, K)
    lags, ref, series = dvv.synthesize_banded_ncfs(dvv_bands, sr=sr, maxlag=maxlag,
                                                   noise=noise, seed=seed + 1)
    return lags, ref, series, dvv_bands, t, sr


def panel_stations(ax):
    try:
        inv = fetch_inventory(PUGET_CASCADES_BBOX)
    except Exception as exc:
        ax.text(0.5, 0.5, f"inventory unavailable\n{exc}", ha="center", va="center",
                transform=ax.transAxes, fontsize=8); return 0
    w, s, e, n = PUGET_CASCADES_BBOX
    for net, col, mk in (("UW", OI["uw"], "^"), ("CC", OI["cc"], "s")):
        sub = inv[inv.network == net]
        ax.scatter(sub.lon, sub.lat, s=34, c=col, marker=mk, edgecolor="white", linewidth=0.5,
                   label=f"{net} ({len(sub)})", zorder=3)
    ax.set_xlim(w, e); ax.set_ylim(s, n)
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    ax.set_title("UW + CC stations (seisfetch inventory)")
    ax.legend(fontsize=8, loc="lower left", framealpha=0.9)
    ax.grid(color=GRID, lw=0.5)
    return len(inv)


def panel_kernels(ax, ens, prof):
    from codameter.uq_depth import band_sensitivity_matrix
    fcs = np.array(sorted(ens))
    K = band_sensitivity_matrix(prof, fcs)
    z = K.depths_km
    for bi, fc in enumerate(fcs):
        g = np.abs(K.G[bi]); g = g / g.max()
        ax.plot(g, z, color=plt.cm.viridis(bi / (len(fcs) - 1)), lw=1.6,
                label=f"{fc:.2f} Hz")
    ax.axhline(WATER_TABLE_KM, color=INK, ls="--", lw=1.2)
    ax.text(0.98, WATER_TABLE_KM, " water table", color=INK, fontsize=7.5, va="bottom", ha="right",
            transform=ax.get_yaxis_transform())
    ax.set_ylim(1.2, 0.0)          # shallow at top
    ax.set_xlabel("normalized sensitivity |K(z)|"); ax.set_ylabel("depth (km)")
    ax.set_title("Frequency -> depth kernels (L = Vs/3f)")
    ax.legend(fontsize=7.5, title="band", title_fontsize=7.5)
    return K


def panel_banded_dvv(ax, banded, ens, dvv_bands):
    """dv/v(t) per band with ensemble UQ; each band's own imposed truth overlaid (low->slow, high->fast)."""
    fcs = sorted(ens)
    for bi, fc in enumerate(fcs):
        E = ens[fc]["ensemble"]
        m, sd = E.mean * 100, E.total_std * 100     # percent
        col = plt.cm.viridis(bi / (len(fcs) - 1))
        ax.fill_between(banded.times, m - sd, m + sd, color=col, alpha=0.16)
        ax.plot(banded.times, m, color=col, lw=1.4, label=f"{fc:.2f} Hz")
        imposed = (dvv_bands[bi] - dvv_bands[bi, 0]) * 100
        ax.plot(banded.times, imposed, color=col, lw=0.9, ls=":")
    ax.set_xlabel("epoch (day)"); ax.set_ylabel("dv/v (%)")
    ax.set_title("Banded dv/v with processing-ensemble UQ (dotted = imposed)")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(color=GRID, lw=0.5)


def panel_separation(ax, ens, prof, epoch):
    post, part = dvv.separate_depth(ens, prof, WATER_TABLE_KM, epoch=epoch)
    z, m, sd = part["depths_km"], part["profile"] * 100, part["profile_std"] * 100
    ax.plot(m, z, color=INK, lw=1.6)
    ax.fill_betweenx(z, m - sd, m + sd, color=MUTED, alpha=0.25)
    ax.axhline(WATER_TABLE_KM, color=OI["wtd"], ls="--", lw=1.2)
    sm = z <= WATER_TABLE_KM
    ax.fill_between([m.min() - 0.05, m.max() + 0.05], 0, WATER_TABLE_KM,
                    color=OI["sm"], alpha=0.10)
    # axis is depth-inverted (0 km at top): shallow SM near top, deep WTD below.
    ax.text(0.02, 0.93, "soil moisture\n(vadose, shallow)", color=OI["sm"], fontsize=8,
            transform=ax.transAxes, va="top", fontweight="bold")
    ax.text(0.02, 0.45, "relative WTD\n(saturated, deep)", color=OI["wtd"], fontsize=8,
            transform=ax.transAxes, va="top", fontweight="bold")
    ax.set_ylim(1.0, 0.0)
    ax.set_xlabel("dVs/Vs (%)"); ax.set_ylabel("depth (km)")
    ax.set_title("Depth-separated dv/v at the water table")
    return part


def make_assimilation_figure(ens):
    """Assimilate dv/v-derived relative WTD and Δθ at the real UW/CC geometry (new data source).

    Demonstrates the operator that folds the dv/v estimates into the GWL and soil-moisture models
    the same way wells and SNOTEL are assimilated: a precision-weighted, uncertainty-aware update
    that reverts to the model where there is no station. Uses real station coordinates; the
    per-station dv/v values/uncertainties are the depth-separated synthetic estimates.
    """
    from pyproj import Transformer
    try:
        inv = fetch_inventory(PUGET_CASCADES_BBOX)
    except Exception:
        return None
    tf = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    sx, sy = tf.transform(inv.lon.values, inv.lat.values)
    rng = np.random.RandomState(1)

    # depth-separated dv/v per station (spatial pattern + noise), then -> state units + sigma.
    fcs = sorted(ens)
    sm_std = float(np.median(ens[fcs[-1]]["ensemble"].total_std))     # shallow band sigma
    wt_std = float(np.median(ens[fcs[0]]["ensemble"].total_std))      # deep band sigma
    lon0 = inv.lon.values
    dvv_wtd = 8e-4 * (lon0 - lon0.mean()) / (np.ptp(lon0) or 1) + rng.normal(0, wt_std, len(inv))
    dvv_sm = -2e-2 * (inv.lat.values - inv.lat.mean()) / (np.ptp(inv.lat.values) or 1) \
        + rng.normal(0, sm_std, len(inv))
    wtd, wtd_sig = dvv.dvv_to_wtd_change(dvv_wtd, np.full(len(inv), wt_std))
    dth, dth_sig = dvv.dvv_to_theta_change(dvv_sm, np.full(len(inv), sm_std))
    # representativeness floor: the nominal dv/v->state conversion sensitivity is itself uncertain,
    # so a single-season station estimate is not cm/0.001-tight. Honest per-station sigma.
    wtd_sig = np.maximum(wtd_sig, 0.4)          # m
    dth_sig = np.maximum(dth_sig, 0.02)         # m3/m3

    w, s, e, n = PUGET_CASCADES_BBOX
    xg = np.linspace(*tf.transform([w, e], [s, s])[0], 80)
    yg = np.linspace(*tf.transform([w, w], [s, n])[1], 80)
    GX, GY = np.meshgrid(xg, yg)

    wtd_f, wtd_sg = assimilate_points(GX, GY, sx, sy, wtd, wtd_sig,
                                      length_scale_m=25_000.0, prior_sigma=0.5)
    dth_f, dth_sg = assimilate_points(GX, GY, sx, sy, dth, dth_sig,
                                      length_scale_m=25_000.0, prior_sigma=0.05)

    fig, ax = plt.subplots(2, 2, figsize=(12, 9))
    ext = [xg.min(), xg.max(), yg.min(), yg.max()]
    specs = [(ax[0, 0], wtd_f, "RdBu_r", "assimilated relative WTD anomaly (m)", wtd, sx, sy),
             (ax[0, 1], wtd_sg, "viridis", "posterior sigma WTD (m)", None, sx, sy),
             (ax[1, 0], dth_f, "BrBG", "assimilated soil-moisture anomaly Δθ", dth, sx, sy),
             (ax[1, 1], dth_sg, "viridis", "posterior sigma θ", None, sx, sy)]
    for a, fld, cmap, title, vals, xx, yy in specs:
        vmax = np.nanmax(np.abs(fld)) if "anomaly" in title else None
        im = a.imshow(fld, extent=ext, origin="lower", cmap=cmap,
                      vmin=(-vmax if vmax else None), vmax=vmax, aspect="auto")
        a.scatter(xx, yy, s=10, c="k", alpha=0.5, marker="o", linewidths=0)
        fig.colorbar(im, ax=a, shrink=0.8)
        a.set_title(title, fontsize=10); a.set_xticks([]); a.set_yticks([])
    fig.suptitle("dv/v as a new assimilated observation: depth-separated relative water table and "
                 "soil moisture folded into the state models (precision-weighted, uncertainty-aware)",
                 fontsize=12, fontweight="bold", y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    for p in (OUT / "dvv_assimilation.png", ASSETS / "dvv_assimilation.png"):
        fig.savefig(p, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return dict(n_stations=int(len(inv)), wtd_sigma_reduction=float(1 - np.nanmin(wtd_sg) / 0.5),
                theta_sigma_reduction=float(1 - np.nanmin(dth_sg) / 0.05))


def main():
    lags, ref, series, dvv_bands, t, sr = _synthetic()
    banded = dvv.measure_banded_dvv(series, ref, lags, sr, coda_s=(5.0, 30.0), times=t)
    ens = dvv.processing_ensemble_dvv(series, lags, sr, times_days=t)
    prof = dvv.pnw_velocity_profile(vs30_ms=400.0)

    fig, ax = plt.subplots(2, 2, figsize=(13, 10))
    n_sta = panel_stations(ax[0, 0])
    panel_kernels(ax[0, 1], ens, prof)
    panel_banded_dvv(ax[1, 0], banded, ens, dvv_bands)
    part = panel_separation(ax[1, 1], ens, prof, epoch=len(t) - 1)

    fig.suptitle("dv/v module: ambient-noise correlation -> uncertainty-aware, depth-separated "
                 "soil moisture & relative water table", fontsize=13, fontweight="bold", y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    for p in (OUT / "dvv_module.png", ASSETS / "dvv_module.png"):
        fig.savefig(p, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    summary = dict(n_stations=int(n_sta), bands_hz=[float(f) for f in sorted(ens)],
                   peak_depths_km=[float(x) for x in part["peak_depths_km"]],
                   water_table_km=WATER_TABLE_KM,
                   soil_moisture_dvv=part["soil_moisture_dvv"],
                   soil_moisture_dvv_std=part["soil_moisture_dvv_std"],
                   wtd_relative_dvv=part["wtd_relative_dvv"],
                   wtd_relative_dvv_std=part["wtd_relative_dvv_std"])
    assim = make_assimilation_figure(ens)
    if assim:
        summary["assimilation"] = assim
    (PROC / "dvv_summary.json").write_text(json.dumps(summary, indent=2))
    print("wrote", OUT / "dvv_module.png", OUT / "dvv_assimilation.png", "and",
          PROC / "dvv_summary.json")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
