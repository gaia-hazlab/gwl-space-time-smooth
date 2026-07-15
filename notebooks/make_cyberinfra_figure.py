"""The data plane: how heterogeneous streams are fetched, homogenised, staged, and assimilated.

Run: ``pixi run cyberinfra-figure``

A schematic (no data reads) of the cyberinfrastructure the report describes in prose: sources at many
native resolutions -> fetchers -> forward-operator homogenisation (NOT regridding) -> Zarr staging on
Kopah in the earth2studio DataSource layout -> BLUE assimilation at native support -> products +
independent evaluation.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
OUT = Path("figures/demo/cyberinfra.png")
ASSETS = Path("docs/twin/assets")

# Okabe-Ito by data ROLE (identity, fixed order -- never cycled)
ROLE = {
    "forcing": "#0072B2", "state": "#009E73", "flux": "#E69F00",
    "static": "#56B4E9", "forecast": "#CC79A7", "eval": "#666666",
}
INK, MUTED, SURF = "#1a1a2e", "#5a5a6e", "#eef1f5"


def main():
    try:
        from src.viz.fonts import register_inter
        register_inter()
    except Exception:
        pass

    fig, ax = plt.subplots(figsize=(16.5, 9.2))
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")

    def box(x, y, w, h, text, fc="white", ec=INK, fs=8.5, lw=1.1, tc=INK, weight="normal"):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.35,rounding_size=1.2",
                                    fc=fc, ec=ec, lw=lw, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
                color=tc, zorder=3, weight=weight)

    def arrow(x1, y1, x2, y2, c=MUTED, lw=1.6):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=13,
                                     color=c, lw=lw, zorder=1, shrinkA=2, shrinkB=2))

    def colhead(x, w, t):
        ax.text(x + w / 2, 95.5, t, ha="center", va="center", fontsize=15, weight="bold", color=INK)

    # ---- column x-anchors ----
    cx = dict(src=1.0, fetch=22.5, homo=42.5, stage=63.0, assim=83.5)
    W = dict(src=18.5, fetch=17.0, homo=18.0, stage=18.0, assim=15.5)

    colhead(cx["src"], W["src"], "SOURCES\n(native resolution)")
    colhead(cx["fetch"], W["fetch"], "FETCH\nsrc/data/*")
    colhead(cx["homo"], W["homo"], "HOMOGENISE\nforward operator $g_i$")
    colhead(cx["stage"], W["stage"], "STAGE\nZarr on Kopah S3")
    colhead(cx["assim"], W["assim"], "ASSIMILATE\nBLUE, native support")

    # ---- sources (role-coloured), with native resolution ----
    sources = [
        ("PRISM daily  4 km", "forcing"),
        ("FuXi / earth2studio  0.25 deg", "forecast"),
        ("NWIS wells  point", "state"),
        ("SNOTEL / SCAN theta  point", "state"),
        ("seismic UW/CC dv/v  volume", "state"),
        ("USGS gauges  basin", "flux"),
        ("SMAP / NISAR  9 km / 0.2 km", "state"),
        ("SOLUS100 / 3DEP  100 m / 10 m", "static"),
        ("ERA5-Land / GRACE  9 km / 300 km", "eval"),
    ]
    n = len(sources); top = 90.0; gap = 9.3; hh = 6.6
    ys = [top - i * gap for i in range(n)]
    for (txt, role), y in zip(sources, ys):
        box(cx["src"], y - hh, W["src"], hh, txt, fc="white", ec=ROLE[role], lw=1.7, fs=8.0,
            tc=INK)
        arrow(cx["src"] + W["src"], y - hh / 2, cx["fetch"], 50, ROLE[role], lw=1.0)

    ymid = 50
    box(cx["fetch"], ymid - 22, W["fetch"], 44,
        "fetch_prism_daily\nfetch_earth2studio\nfetch_usgs_discharge\nfetch_insitu_sm\n"
        "fetch_snotel_swe\nfetch_gauge_basins\nfetch_solus_domain\ndownload_3dep_domain\n"
        "(ERA5-Land: #72)\n\nretry + offline\nfallbacks; fail loud",
        fc=SURF, ec=INK, fs=7.6)
    arrow(cx["fetch"] + W["fetch"], ymid, cx["homo"], ymid)

    box(cx["homo"], ymid - 22, W["homo"], 44,
        "reproject to the frozen\ngrid  EPSG:5070, 90 m\n(src/config/domain.py)\n\n"
        "each datum keeps its\nnative footprint $g_i$:\n"
        "point / coda volume /\nsatellite pixel / basin\n\n"
        "UPSCALE-then-compare\nnever regrid the obs",
        fc="white", ec=INK, fs=7.8)
    arrow(cx["homo"] + W["homo"], ymid, cx["stage"], ymid)

    box(cx["stage"], ymid - 22, W["stage"], 44,
        "obstore + zarr_format=3\nconsolidated=False\n(gaia-cli convention)\n\n"
        "layout = [time, variable]\n= earth2studio\nDataSource contract\n\n"
        "s3://gaia/soil-twin/\n  static/ forecast/\n  forcing/ obs/",
        fc=SURF, ec=ROLE["forecast"], lw=1.4, fs=7.8)
    arrow(cx["stage"] + W["stage"], ymid, cx["assim"], ymid)

    box(cx["assim"], ymid - 16, W["assim"], 32,
        "$m_a = m_b +$\n$BG^\\top(GBG^\\top{+}R)^{-1}$\n$(d - G m_b)$\n\n"
        "space -> $G$\ntime -> $R$\n(exp$(-\\Delta t/2\\tau)$)\n\nobservability.py",
        fc="white", ec=INK, lw=1.6, fs=8.2, weight="normal")

    # products + evaluation out the bottom of assimilate
    box(cx["assim"] - 1, 6, W["assim"] + 2, 12,
        "PRODUCTS\nGWL + SM + Vs30\n@ 90 m + per-cell sigma", fc=ROLE["state"], ec=INK,
        tc="white", fs=8.2, weight="bold")
    arrow(cx["assim"] + W["assim"] / 2, ymid - 16, cx["assim"] + W["assim"] / 2, 18)

    # evaluation feedback (eval streams score the product, never force it)
    ax.text(cx["homo"] + W["homo"] / 2, 2.5,
            "ERA5-Land / GRACE / SNOTEL / gauges enter the SAME way but are held out — they SCORE the "
            "product, never force it",
            ha="center", va="center", fontsize=12, style="italic", color=ROLE["eval"])

    # legend of roles
    from matplotlib.patches import Patch
    leg = [Patch(fc="white", ec=ROLE[k], lw=2, label=k) for k in ROLE]
    ax.legend(handles=leg, loc="lower left", bbox_to_anchor=(0.005, 0.005), ncol=3, fontsize=12,
              frameon=True, framealpha=.9, title="data role", title_fontsize=12)

    fig.suptitle("The data plane: heterogeneous streams reconciled by forward operators, not regridding",
                 fontsize=16, weight="bold", y=0.995)
    OUT.parent.mkdir(parents=True, exist_ok=True); ASSETS.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=125, bbox_inches="tight", facecolor="white")
    shutil.copy(OUT, ASSETS / OUT.name)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
