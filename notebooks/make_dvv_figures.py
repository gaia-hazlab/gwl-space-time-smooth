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

mpl.use("Agg")
OUT = Path("figures/demo"); OUT.mkdir(parents=True, exist_ok=True)
ASSETS = Path("docs/assets"); ASSETS.mkdir(parents=True, exist_ok=True)
PROC = Path("data/processed")
INK, MUTED, GRID = "#1a1a2e", "#5a5a6e", "#d9d9e0"
OI = {"uw": "#0072B2", "cc": "#D55E00", "sm": "#E69F00", "wtd": "#009E73", "band": "#CC79A7"}
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.titlecolor": INK, "axes.titleweight": "bold",
                     "axes.edgecolor": MUTED, "figure.dpi": 130})
WATER_TABLE_KM = 0.03          # 30 m nominal vadose/saturated boundary for the demo


def _synthetic(n_epoch=36, sr=25.0, maxlag=60.0, noise=0.15, seed=0):
    rng = np.random.RandomState(seed)
    lags = np.arange(-int(maxlag * sr), int(maxlag * sr) + 1) / sr
    env = np.exp(-np.abs(lags) / 20.0)
    sos = signal.butter(4, [0.1, 8.0], btype="band", fs=sr, output="sos")
    ref = signal.sosfiltfilt(sos, rng.randn(lags.size)) * env
    t = np.arange(n_epoch, dtype=float)
    # deep (WTD) drying trend + shallow (SM) seasonal, imposed as one bulk dv/v for the demo
    dvv_true = -1.5e-3 * (t / n_epoch) + 2.0e-3 * np.sin(2 * np.pi * t / 12.0)
    series = np.array([np.interp(lags, lags * (1 + e), ref) for e in dvv_true])
    series = series + noise * np.array(
        [signal.sosfiltfilt(sos, rng.randn(lags.size)) * env for _ in range(n_epoch)])
    return lags, ref, series, dvv_true, t, sr


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


def panel_banded_dvv(ax, banded, ens, dvv_true):
    fcs = sorted(ens)
    for bi, fc in enumerate(fcs):
        E = ens[fc]["ensemble"]
        m, sd = E.mean * 100, E.total_std * 100     # percent
        col = plt.cm.viridis(bi / (len(fcs) - 1))
        ax.fill_between(banded.times, m - sd, m + sd, color=col, alpha=0.18)
        ax.plot(banded.times, m, color=col, lw=1.4, label=f"{fc:.2f} Hz")
    ax.plot(banded.times, (dvv_true - dvv_true[0]) * 100, color=INK, lw=1.0, ls=":",
            label="imposed")
    ax.set_xlabel("epoch (day)"); ax.set_ylabel("dv/v (%)")
    ax.set_title("Banded dv/v with processing-ensemble UQ")
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


def main():
    lags, ref, series, dvv_true, t, sr = _synthetic()
    banded = dvv.measure_banded_dvv(series, ref, lags, sr, coda_s=(5.0, 30.0), times=t)
    ens = dvv.processing_ensemble_dvv(series, lags, sr, times_days=t)
    prof = dvv.pnw_velocity_profile(vs30_ms=400.0)

    fig, ax = plt.subplots(2, 2, figsize=(13, 10))
    n_sta = panel_stations(ax[0, 0])
    panel_kernels(ax[0, 1], ens, prof)
    panel_banded_dvv(ax[1, 0], banded, ens, dvv_true)
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
    (PROC / "dvv_summary.json").write_text(json.dumps(summary, indent=2))
    print("wrote", OUT / "dvv_module.png", "and", PROC / "dvv_summary.json")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
