"""The observing system on BOTH axes: spatial support x temporal revisit, per state.

Run: ``pixi run spacetime-figure``

The spatial resolution maps show WHERE each stream constrains the state. This shows the other half:
a state that changes fast is observed well only by a stream that samples fast. Soil moisture decorrelates
in days, so a weekly satellite ALIASES it however fine its pixels; the water table integrates months, so
a coarse revisit is fine for it. The same sensor is therefore worth different amounts for the two states.
"""
from __future__ import annotations

import shutil
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    try:
        from src.viz.fonts import register_inter
        register_inter()
    except Exception:
        pass
    from src.models.observability import STREAMS, TEMPORAL_TAU_DAYS, temporal_resolution

    OUT = Path("figures/demo/observing_spacetime.png")
    KIND_C = {"point": "#2E86AB", "volume": "#E84855", "satellite": "#F6AE2D",
              "channel": "#7B2D8B", "flux": "#3BB273"}

    fig, ax = plt.subplots(1, 2, figsize=(15.5, 6.4), constrained_layout=True,
                           gridspec_kw={"width_ratios": [1.25, 1]})

    # --- panel 1: the space-time plane -----------------------------------------------------------
    a = ax[0]
    # manual label offsets (points, pt) + a small x-jitter for streams that share a location, so the
    # dense point cluster does not overprint itself
    LAB = {  # name: (dx_km_factor, dy_pt, ha, va)
        "NWIS wells":               (1.0, 10, "center", "bottom"),
        "SNOTEL / SCAN θ":          (0.72, -7, "right", "top"),
        "USCRN θ":                  (1.45, -7, "left", "top"),
        "Seismic dv/v":             (1.0, 12, "center", "bottom"),
        "SMAP (retrieval)":         (1.0, 11, "center", "bottom"),
        "NISAR Beta SM v1 (retrieval)": (1.0, -11, "center", "top"),
        "Sentinel surface water":   (0.55, 11, "right", "bottom"),
        "USGS gauges":              (1.0, -8, "center", "top"),
        "GHCN-Daily weather stations": (1.35, 9, "left", "bottom"),
        "GNSS-IR / GNSS-TEC precipitable water": (2.0, -9, "left", "top"),
        "NOAA Stage IV radar precip (gridded)": (1.0, 10, "center", "bottom"),
    }
    DEFAULT_LAB = (1.0, 9, "center", "bottom")
    for s in STREAMS:
        rev = max(s.revisit_days, 0.02)                       # continuous -> plot near the axis
        fx, dy, ha, va = LAB.get(s.name, DEFAULT_LAB)
        mk = "o" if s.is_measurement else "D"                 # diamond = retrieval / model estimate
        a.scatter(s.support_km * fx, rev, s=190, c=KIND_C[s.kind], marker=mk,
                  edgecolors="k", linewidths=.7, zorder=3)
        a.annotate(s.name, (s.support_km * fx, rev), fontsize=12, ha=ha, va=va,
                   xytext=(0, dy), textcoords="offset points", zorder=4)
    # the soil-moisture "must sample faster than this" line: revisit = tau_SM
    a.axhline(TEMPORAL_TAU_DAYS["soil_moisture"], color="#3BB273", ls="--", lw=1.3)
    a.text(3.2, TEMPORAL_TAU_DAYS["soil_moisture"] * 1.15, "soil-moisture decorrelation (~5 d):\n"
           "streams above this ALIAS the storm signal", color="#3BB273", fontsize=11, ha="center")
    a.axhspan(TEMPORAL_TAU_DAYS["soil_moisture"], 30, color="#3BB273", alpha=.05)
    a.set_xscale("log"); a.set_yscale("log")
    a.set_xlabel("spatial support  (km)  →  coarser"); a.set_ylabel("revisit interval  (days)  →  slower")
    a.set_xlim(0.055, 22); a.set_ylim(0.015, 45)
    a.set_title("The observing system on both axes", fontweight="bold")
    from matplotlib.lines import Line2D
    leg = [Line2D([], [], marker="o", ls="", mfc="w", mec="k", label="measurement"),
           Line2D([], [], marker="D", ls="", mfc="w", mec="k", label="retrieval / model estimate")]
    leg += [Line2D([], [], marker="s", ls="", mfc=c, mec="k", label=k) for k, c in KIND_C.items()]
    # Fully outside the axes (below), not overlapping the now-denser point cloud.
    a.legend(handles=leg, fontsize=10.5, loc="upper center", bbox_to_anchor=(0.5, -0.16),
             ncol=4, framealpha=.96)
    a.grid(alpha=.25, which="both")

    # --- panel 2: effective observability for SOIL MOISTURE (fast state) --------------------------
    b = ax[1]
    sm = [s for s in STREAMS if "soil_moisture" in s.states]
    tau = TEMPORAL_TAU_DAYS["soil_moisture"]
    names = [s.name for s in sm]
    temporal = np.array([float(temporal_resolution(s.revisit_days, tau)) for s in sm])
    y = np.arange(len(sm))
    b.barh(y, np.ones_like(temporal), color="#dddddd", label="spatial coverage (idealised)")
    b.barh(y, temporal, color=[KIND_C[s.kind] for s in sm],
           label="× temporal resolution (fast state)")
    for i, s in enumerate(sm):
        b.text(temporal[i] + .02, i, "%.2f" % temporal[i], va="center", fontsize=13)
    b.set_yticks(y); b.set_yticklabels(names, fontsize=13); b.invert_yaxis()
    b.set_xlim(0, 1.25); b.set_xlabel("temporal resolution of soil moisture (fraction)")
    b.set_title("Why coverage is not enough for a FAST state", fontweight="bold")
    b.text(0.5, -0.16, "A weekly satellite's fine pixels are discounted to near zero for soil moisture;\n"
           "the continuous seismic array and hourly probes keep their temporal information.",
           transform=b.transAxes, ha="center", fontsize=12, style="italic", color="#555")

    fig.suptitle("Observing-system design — spatial coverage AND temporal revisit\n"
                 "Satellites are RETRIEVALS (model estimates), fine in space but coarse in time; "
                 "ground/seismic streams are sparse in space but continuous in time",
                 fontsize=15, fontweight="bold")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    (assets := Path("docs/twin/assets")).mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=125, bbox_inches="tight", facecolor="white")
    shutil.copy(OUT, assets / OUT.name)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
