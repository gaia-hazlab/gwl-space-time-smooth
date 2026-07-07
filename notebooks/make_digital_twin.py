"""Digital-twin MVP: a 2x3 animated GIF of the coupled 90 m subsurface state and its uncertainty.

Top row  : 90 m groundwater depth-to-water, soil moisture theta, and Vs30 (near-surface stiffness).
Bottom row: their per-cell 1-sigma.
Animated over one hydrologic year at ~5-day cadence. The static structure is real 90 m data; the
time evolution (and the high-frequency content) comes from assimilating the depth-separated dv/v
onto those static fields with `assimilate_points`, so the animation literally shows the
data-assimilation digital twin: fields update and sigma shrinks where/when sensors constrain them.

  GWL  : baseline_dtw_m.tif  +  dv/v deep-band -> ΔWTD (assimilated)
  theta: soil_hydraulic_envelope theta_fc  +  dv/v shallow-band -> Δtheta (assimilated)
  Vs30 : vs30_90m.tif (fetched; else synth from HAND)  x (1 + top-30 m dv/v) (assimilated)

Ground sensors are drawn with distinct markers (wells / SNOTEL / seismic UW,CC); remote-sensing
products are listed in a legend. The dv/v is a physically realistic synthetic (low freq -> slow
GWL, high freq -> fast ET/rain) for this compute-free MVP; the same calls run on real dv/v.

Run:  pixi run python notebooks/make_digital_twin.py   (or: pixi run digital-twin)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib as mpl
import numpy as np
import pandas as pd
import rioxarray as rxr
import xarray as xr
from pyproj import Transformer

from src.data.fetch_seismic import PUGET_CASCADES_BBOX
from src.models import dvv
from src.models.anchor import assimilate_points, assimilation_attribution
from src.models.downscale import representativeness_sigma
from src.viz.fonts import register_inter

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.lines import Line2D

PROC = Path("data/processed")
CACHE = Path("data/cache/seismic")
OUT = Path("figures/demo"); OUT.mkdir(parents=True, exist_ok=True)
ASSETS = Path("docs/assets"); ASSETS.mkdir(parents=True, exist_ok=True)
INK, MUTED, GRID = "#1a1a2e", "#5a5a6e", "#d9d9e0"
OI = {"gwl": "#0072B2", "theta": "#009E73", "vs30": "#CC79A7",
      "well": "#0072B2", "snotel": "#E69F00", "uw": "#0072B2", "cc": "#D55E00"}
N_FRAMES, DT_DAYS, DISP_PX, WATER_TABLE_KM = 73, 5.0, 180, 0.03
T0 = pd.Timestamp("2023-10-01")   # hydrologic-year start (fixed; no wall-clock dependency)
# GWL and soil moisture are shown as anomalies from the per-frame geospatial mean (the domain mean
# is written as a text insert), so the time-varying assimilated signal is visible rather than being
# swamped by the large static range. Vs30 stays absolute (turbo) for geotechnical recognition.
DELTA_PRODUCTS = {"gwl", "theta"}
DCMAP = {"gwl": "RdBu_r", "theta": "BrBG"}          # diverging, centered on the mean
DUNIT = {"gwl": "m", "theta": "m³/m³"}

# Remote-sensing products used by the pipeline (for the legend).
REMOTE = [("SMAP", "9 km", "validation"), ("MERRA-2", "0.5°", "validation"),
          ("TerraClimate", "4 km", "forcing"), ("PRISM", "4 km", "forcing"),
          ("SOLUS100", "100 m", "static"), ("3DEP", "10 m", "static")]


# --------------------------------------------------------------------------- static fields
def _load_static():
    """Real 90 m static base + per-cell static sigma for gwl (DTW m), theta, Vs30 (m/s), EPSG:5070."""
    out = {}
    base = rxr.open_rasterio(PROC / "baseline_dtw_m.tif", masked=True).squeeze("band", drop=True)
    rfs = rxr.open_rasterio(PROC / "baseline_rf_std_m.tif", masked=True).squeeze("band", drop=True)
    g_ds = representativeness_sigma(base, 2000.0, 90.0)
    # DTW: shallow water table -> blue (water near surface), deep -> pale (dry). Sequential and
    # colorblind-safe; pairs with theta so BLUE=water and PALE=dry read the same on both panels.
    out["gwl"] = dict(base=base, sigma=np.sqrt(np.nan_to_num(rfs.values) ** 2 + np.nan_to_num(g_ds) ** 2),
                      cmap="YlGnBu_r", label="depth-to-water (m)  ·  shallow=blue", units="m")

    env = xr.open_zarr(PROC / "soil_hydraulic_envelope_90m.zarr").rio.write_crs("EPSG:5070")
    theta_ref = env["theta_fc"]
    t_ds = representativeness_sigma(theta_ref, 4000.0, 90.0)
    out["theta"] = dict(base=theta_ref, sigma=np.sqrt(0.03 ** 2 + np.nan_to_num(t_ds) ** 2),
                        cmap="YlGnBu", label="soil moisture θ (m³/m³)  ·  wet=blue", units="")

    vs30 = _vs30_field(base)
    v_ds = representativeness_sigma(vs30, 2000.0, 90.0)
    # Vs30: turbo -- the colorblind-improved "jet"/rainbow geotechnical engineers recognize for Vs30.
    out["vs30"] = dict(base=vs30, sigma=np.sqrt((0.15 * np.nan_to_num(vs30.values)) ** 2 + np.nan_to_num(v_ds) ** 2),
                       cmap="turbo", label="Vs30 (m/s)  ·  soft=blue, stiff=red", units="m/s")
    return out


def _vs30_field(like):
    """Read vs30_90m.tif if present; else synthesize from HAND (vs30=180+520*(1-exp(-hand/30)))."""
    tif = PROC / "vs30_90m.tif"
    if tif.exists():
        v = rxr.open_rasterio(tif, masked=True).squeeze("band", drop=True)
        return v.rio.reproject_match(like)
    hand = rxr.open_rasterio(PROC / "terrain_hand_90m.tif", masked=True).squeeze("band", drop=True)
    hand = hand.rio.reproject_match(like)
    vs = 180.0 + 520.0 * (1.0 - np.exp(-np.nan_to_num(hand.values) / 30.0))
    return like.copy(data=vs.astype("float32")).rio.write_crs(like.rio.crs)


# --------------------------------------------------------------------------- display grid
def _display_grid(template, n_px=DISP_PX, bbox=None):
    """Coarse WGS84 display grid cropped to where we actually have 90 m data.

    The frame is the reprojected bounds of ``template`` (the GWL product, the limiting extent), so
    the panels are filled with data instead of the mostly-empty full pilot bbox. Assimilation still
    uses all stations (distance-decayed), even those outside this cropped view.
    """
    if bbox is None:
        w, s, e, n = template.rio.reproject("EPSG:4326").rio.bounds()
    else:
        w, s, e, n = bbox
    aspect = (n - s) / max(e - w, 1e-9)
    nx = n_px
    ny = max(int(round(n_px * aspect)), 8)
    lon = np.linspace(w, e, nx)
    lat = np.linspace(n, s, ny)                 # north-up
    like = xr.DataArray(np.zeros((ny, nx)), dims=("y", "x"),
                        coords={"y": lat, "x": lon}).rio.write_crs("EPSG:4326")
    LON, LAT = np.meshgrid(lon, lat)
    x5070, y5070 = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform(LON, LAT)
    return dict(like=like, extent=[w, e, s, n], LON=LON, LAT=LAT, x5070=x5070, y5070=y5070,
                shape=(ny, nx))


def _to_display(field5070, grid):
    field5070 = field5070.rio.write_crs("EPSG:5070") if field5070.rio.crs is None else field5070
    return field5070.rio.reproject_match(grid["like"]).values


# --------------------------------------------------------------------------- sensors
def _seismic():
    df = pd.read_parquet(CACHE / "inventory_UW-CC.parquet")
    return df


def _wells():
    df = pd.read_parquet(PROC / "nwis_sites_clean.parquet")
    return df[["lat", "lon"]].dropna()


def _snotel():
    df = pd.read_parquet(PROC / "snotel_soil_moisture_monthly.parquet")
    return df.drop_duplicates("triplet")[["lat", "lon"]].dropna()


# --------------------------------------------------------------------------- twin stacks
def _compute_stacks(static, grid):
    """Precompute (n_frame, ny, nx) field + sigma stacks for gwl, theta, vs30 via per-frame assimilation."""
    from codameter.uq_depth import band_sensitivity_matrix

    seis = _seismic()
    tf = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    sx, sy = tf.transform(seis.lon.values, seis.lat.values)

    prof = dvv.pnw_velocity_profile(400.0)
    fc = np.sqrt(np.asarray(dvv.DEFAULT_BANDS)[:, 0] * np.asarray(dvv.DEFAULT_BANDS)[:, 1])
    K = band_sensitivity_matrix(prof, fc)
    syn = dvv.synthetic_station_dvv(seis.lon.values, seis.lat.values, K,
                                    n_epoch=N_FRAMES, dt_days=DT_DAYS, water_table_km=WATER_TABLE_KM)
    dvv_bt = syn["dvv_bt"]                       # (n_sta, n_band, n_epoch)
    m_zt = syn["m_zt"]                           # (n_sta, n_depth, n_epoch)
    depths = syn["depths_km"]

    # per-station, per-frame state anomalies + representativeness-floored sigmas
    wtd, _ = dvv.dvv_to_wtd_change(dvv_bt[:, 0, :], np.zeros_like(dvv_bt[:, 0, :]))     # deep band
    dth, _ = dvv.dvv_to_theta_change(dvv_bt[:, -1, :], np.zeros_like(dvv_bt[:, -1, :]))  # shallow band
    frac = np.stack([dvv.dvv_to_vs30_change(dvv.top_layer_mean_dvv(m_zt[i], depths, 0.03))[0]
                     for i in range(m_zt.shape[0])], axis=0)                              # (n_sta, n_epoch)
    n_sta = dvv_bt.shape[0]
    sig = dict(gwl=np.full(n_sta, 0.4), theta=np.full(n_sta, 0.02), vs30=np.full(n_sta, 0.02))
    anom = dict(gwl=wtd, theta=dth, vs30=frac)
    prior = dict(gwl=0.5, theta=0.05, vs30=0.06)
    L = 25_000.0

    base_disp = {p: _to_display(static[p]["base"], grid) for p in static}
    sigma_static = {p: _to_display(static[p]["base"].copy(
        data=static[p]["sigma"].astype("float32")).rio.write_crs("EPSG:5070"), grid) for p in static}

    fields, sigmas = {p: [] for p in static}, {p: [] for p in static}
    for i in range(N_FRAMES):
        for p in static:
            fld, psig = assimilate_points(grid["x5070"], grid["y5070"], sx, sy,
                                          anom[p][:, i], sig[p], L, prior[p])
            if p == "vs30":
                field = base_disp[p] * (1.0 + fld)
                s = np.sqrt(sigma_static[p] ** 2 + (base_disp[p] * psig) ** 2)
            else:
                field = base_disp[p] + fld
                s = np.sqrt(sigma_static[p] ** 2 + psig ** 2)
            fields[p].append(field)
            sigmas[p].append(s)
    for p in static:
        fields[p] = np.stack(fields[p]); sigmas[p] = np.stack(sigmas[p])
    means = {p: np.array([float(np.nanmean(fields[p][i])) for i in range(N_FRAMES)]) for p in static}
    meta = dict(n_stations_seismic=int(n_sta), peak_depths_km=[float(x) for x in K.peak_depths_km],
                sigma_shrink=dict((p, float(1 - np.nanmin(sigmas[p]) / np.nanmax(sigmas[p]))) for p in static),
                domain_mean_range=dict((p, [float(means[p].min()), float(means[p].max())]) for p in static))
    return fields, sigmas, means, meta


# --------------------------------------------------------------------------- figure
def _panels(fig, static, order=("gwl", "theta", "vs30")):
    axes = fig.subplots(2, 3)
    return axes


def _draw_markers(ax, kind, seis, wells, snotel):
    """Primary sensor per panel: wells on GWL, SNOTEL on theta, seismic on Vs30 (dv/v drives all)."""
    if kind == "gwl":
        ax.scatter(wells.lon, wells.lat, s=7, c=INK, marker="o", edgecolor="white",
                   linewidths=0.2, alpha=0.75, zorder=4)
    elif kind == "theta":
        ax.scatter(snotel.lon, snotel.lat, s=40, c=OI["snotel"], marker="s", edgecolor=INK,
                   linewidths=0.5, zorder=4)
    elif kind == "vs30":
        for net, mk, col in (("UW", "^", OI["uw"]), ("CC", "s", OI["cc"])):
            sub = seis[seis.network == net]
            ax.scatter(sub.lon, sub.lat, s=30, c=col, marker=mk, edgecolor="white",
                       linewidths=0.4, zorder=5)


def _vlims(stack):
    v = stack[np.isfinite(stack)]
    return (float(np.percentile(v, 3)), float(np.percentile(v, 97))) if v.size else (0, 1)


def _field_display(p, stack, means, i):
    """The array drawn for product p at frame i: anomaly (field - domain mean) for delta products."""
    if p in DELTA_PRODUCTS:
        return stack[i] - means[p][i]
    return stack[i]


def _build_figure(static, fields, sigmas, means, grid):
    seis, wells, snotel = _seismic(), _wells(), _snotel()
    order = ("gwl", "theta", "vs30")
    fig, axes = plt.subplots(2, 3, figsize=(13.6, 8.2), constrained_layout=True)
    w, e, s, n = grid["extent"]
    ims, vl, mean_txt = {}, {}, {}
    for c, p in enumerate(order):
        if p in DELTA_PRODUCTS:                            # symmetric limits about zero anomaly
            anoms = np.stack([_field_display(p, fields[p], means, i) for i in range(fields[p].shape[0])])
            a = np.nanpercentile(np.abs(anoms[np.isfinite(anoms)]), 97) if np.isfinite(anoms).any() else 1.0
            vl[(0, p)] = (-a, a); top_cm = DCMAP[p]; top_tag = f"Δ {static[p]['label']}"
        else:
            vl[(0, p)] = _vlims(fields[p]); top_cm = static[p]["cmap"]; top_tag = static[p]["label"]
        vl[(1, p)] = _vlims(sigmas[p])
        for r, (stack, tag, cm) in enumerate([(fields[p], top_tag, top_cm),
                                              (sigmas[p], "1σ " + static[p]["units"], "magma")]):
            ax = axes[r, c]
            cmap = mpl.colormaps[cm].copy(); cmap.set_bad(alpha=0.0)
            data0 = _field_display(p, stack, means, 0) if r == 0 else stack[0]
            im = ax.imshow(data0, extent=[w, e, s, n], origin="upper", cmap=cmap,
                           vmin=vl[(r, p)][0], vmax=vl[(r, p)][1], interpolation="nearest", aspect="auto")
            ims[(r, c)] = im
            ax.set_title(tag, fontsize=12, color=INK)
            ax.set_xlim(w, e); ax.set_ylim(s, n)                # pin frame; don't autoscale to markers
            ax.set_xticks([]); ax.set_yticks([])
            for sp in ax.spines.values():
                sp.set_edgecolor(MUTED); sp.set_linewidth(0.6)
            if r == 0:                                          # markers + mean insert on the field row
                _draw_markers(ax, p, seis, wells, snotel)
                if p in DELTA_PRODUCTS:
                    mean_txt[p] = ax.text(0.035, 0.04, "", transform=ax.transAxes, fontsize=10.5,
                                          color=INK, va="bottom", ha="left",
                                          bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=MUTED, alpha=0.9))
            fig.colorbar(im, ax=ax, shrink=0.82, pad=0.01)
    date_txt = axes[0, 0].text(0.035, 0.965, "", transform=axes[0, 0].transAxes, fontsize=14,
                               fontweight="bold", color=INK, va="top", ha="left",
                               bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=MUTED, alpha=0.9))

    # remote-sensing + sensor legend across the bottom
    sens = [Line2D([0], [0], marker="o", color="none", markerfacecolor=OI["well"], markeredgecolor="white", markersize=7, label="GWL wells (NWIS)"),
            Line2D([0], [0], marker="s", color="none", markerfacecolor=OI["snotel"], markeredgecolor=INK, markersize=7, label="SNOTEL soil moisture"),
            Line2D([0], [0], marker="^", color="none", markerfacecolor=OI["uw"], markeredgecolor="white", markersize=8, label="Seismic UW"),
            Line2D([0], [0], marker="s", color="none", markerfacecolor=OI["cc"], markeredgecolor="white", markersize=7, label="Seismic CC")]
    rs = "Remote sensing: " + " | ".join(f"{n} ({r}, {role})" for n, r, role in REMOTE)
    fig.legend(handles=sens, loc="lower center", ncol=4, frameon=False, fontsize=10,
               bbox_to_anchor=(0.5, -0.02))
    fig.text(0.5, -0.045, rs + "   —   dv/v: synthetic MVP; SNOTEL = soil moisture only (SWE roadmap)",
             ha="center", fontsize=8.5, color=MUTED)
    return fig, ims, date_txt, mean_txt, order


_MEAN_NAME = {"gwl": "DTW", "theta": "θ"}
_MEAN_FMT = {"gwl": "{:.1f}", "theta": "{:.3f}"}


def _set_frame(ims, mean_txt, date_txt, fields, sigmas, means, order, times, i):
    for c, p in enumerate(order):
        ims[(0, c)].set_data(_field_display(p, fields[p], means, i))
        ims[(1, c)].set_data(sigmas[p][i])
        if p in mean_txt:
            val = _MEAN_FMT[p].format(means[p][i])
            mean_txt[p].set_text(f"domain mean {_MEAN_NAME[p]} = {val} {DUNIT[p]}")
    date_txt.set_text(pd.Timestamp(times[i]).strftime("%Y-%m-%d"))


def _animate(static, fields, sigmas, means, grid, times, path, fps=9):
    fig, ims, date_txt, mean_txt, order = _build_figure(static, fields, sigmas, means, grid)

    def update(i):
        _set_frame(ims, mean_txt, date_txt, fields, sigmas, means, order, times, i)
        return list(ims.values()) + [date_txt] + list(mean_txt.values())

    anim = FuncAnimation(fig, update, frames=len(times), blit=False)
    anim.save(str(path), writer=PillowWriter(fps=fps), dpi=74)   # dpi kept modest to bound GIF size
    plt.close(fig)


def _poster(static, fields, sigmas, means, grid, times, path, frame):
    fig, ims, date_txt, mean_txt, order = _build_figure(static, fields, sigmas, means, grid)
    _set_frame(ims, mean_txt, date_txt, fields, sigmas, means, order, times, frame)
    fig.savefig(path, bbox_inches="tight", facecolor="white", dpi=150)
    plt.close(fig)


def _sensor_xy():
    """Sensor coordinates in EPSG:5070 for the attribution sources."""
    tf = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    seis, wells, snotel = _seismic(), _wells(), _snotel()
    sx, sy = tf.transform(seis.lon.values, seis.lat.values)
    wx, wy = tf.transform(wells.lon.values, wells.lat.values)
    nx, ny = tf.transform(snotel.lon.values, snotel.lat.values)
    return dict(seismic=(np.asarray(sx), np.asarray(sy)),
                wells=(np.asarray(wx), np.asarray(wy)),
                snotel=(np.asarray(nx), np.asarray(ny)))


# Which data streams inform each state, with their per-station σ and the model prior σ (state units).
ATTR_SOURCES = {
    "gwl":   dict(streams={"wells": 0.3, "seismic": 0.4}, prior=0.5),
    "theta": dict(streams={"snotel": 0.02, "seismic": 0.02}, prior=0.05),
    "vs30":  dict(streams={"seismic": 0.02}, prior=0.06),
}
STREAM_COLOR = {"wells": OI["well"], "snotel": OI["snotel"], "seismic": "#009E73", "model": "#b8b8c2"}
STREAM_LABEL = {"wells": "GWL wells", "snotel": "SNOTEL", "seismic": "seismic dv/v", "model": "model prior"}


def make_attribution_figure(grid, static, path, L=25_000.0):
    """Per-state attribution of the assimilated estimate to each data stream + the model prior.

    Top row: the dominant data stream at each cell (categorical map). Bottom row: the domain-mean
    attribution share of each stream (stacked bar). Answers 'how much does each sensor/data stream
    contribute to GWL, soil moisture, and Vs30' - computed exactly from the assimilation weights.
    """
    from matplotlib.colors import to_rgba
    from matplotlib.patches import Patch

    xy = _sensor_xy()
    order = ("gwl", "theta", "vs30")
    titles = {"gwl": "Groundwater (DTW)", "theta": "Soil moisture θ", "vs30": "Vs30"}
    w, e, s, n = grid["extent"]
    fig, axes = plt.subplots(2, 3, figsize=(13.6, 8.6), height_ratios=[3, 1.5],
                             constrained_layout=True)
    shares_out = {}
    for c, p in enumerate(order):
        spec = ATTR_SOURCES[p]
        sources = {name: (xy[name][0], xy[name][1], sig) for name, sig in spec["streams"].items()}
        attr = assimilation_attribution(grid["x5070"], grid["y5070"], sources, spec["prior"], L)
        cats = list(spec["streams"]) + ["model"]
        valid = np.isfinite(_to_display(static[p]["base"], grid))

        # dominant-source categorical map
        stack = np.stack([attr[k] for k in cats])
        dom = np.argmax(stack, axis=0)
        rgba = np.zeros(dom.shape + (4,))
        for k, name in enumerate(cats):
            rgba[dom == k] = to_rgba(STREAM_COLOR[name])
        rgba[~valid] = (0, 0, 0, 0)
        ax = axes[0, c]
        ax.imshow(rgba, extent=[w, e, s, n], origin="upper", interpolation="nearest", aspect="auto")
        ax.set_xlim(w, e); ax.set_ylim(s, n); ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(titles[p], fontsize=12.5, color=INK)
        for name in spec["streams"]:
            ax.scatter(*_lonlat(xy[name], grid), s=8, c="k", alpha=0.35, linewidths=0, zorder=3)

        # domain-mean shares (over valid cells) -> stacked horizontal bar
        shares = {k: float(np.nanmean(attr[k][valid])) for k in cats}
        ssum = sum(shares.values()) or 1.0
        shares = {k: v / ssum for k, v in shares.items()}
        shares_out[p] = shares
        axb = axes[1, c]
        left = 0.0
        for name in cats:
            axb.barh(0, shares[name], left=left, color=STREAM_COLOR[name], edgecolor="white")
            if shares[name] > 0.06:
                axb.text(left + shares[name] / 2, 0, f"{shares[name]*100:.0f}%", ha="center",
                         va="center", fontsize=10, color="white", fontweight="bold")
            left += shares[name]
        axb.set_xlim(0, 1); axb.set_ylim(-0.5, 0.5); axb.set_yticks([])
        axb.set_xticks([0, 0.5, 1.0]); axb.set_xticklabels(["0", "50", "100%"], fontsize=9)
        axb.set_title("domain-mean attribution", fontsize=10, color=MUTED)

    handles = [Patch(facecolor=STREAM_COLOR[k], label=STREAM_LABEL[k])
               for k in ("wells", "snotel", "seismic", "model")]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, fontsize=10.5,
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Data-stream attribution: which sensors set each state, and where",
                 fontsize=13.5, fontweight="bold", color=INK)
    fig.savefig(path, bbox_inches="tight", facecolor="white", dpi=150)
    plt.close(fig)
    return shares_out


def _lonlat(xy5070, grid):
    """Project 5070 sensor coords back to lon/lat for overlay on the WGS84 display axes."""
    tf = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True)
    lon, lat = tf.transform(xy5070[0], xy5070[1])
    return lon, lat


def main():
    register_inter(size=13)
    static = _load_static()
    grid = _display_grid(static["gwl"]["base"])
    fields, sigmas, means, meta = _compute_stacks(static, grid)
    times = [T0 + pd.Timedelta(days=DT_DAYS * i) for i in range(N_FRAMES)]

    _animate(static, fields, sigmas, means, grid, times, OUT / "digital_twin.gif")
    # poster = frame of deepest table (late dry season) = max domain-mean DTW
    frame = int(np.nanargmax(means["gwl"]))
    for p in (OUT / "digital_twin_poster.png", ASSETS / "digital_twin_poster.png"):
        _poster(static, fields, sigmas, means, grid, times, p, frame)
    # copy GIF to assets for the report
    (ASSETS / "digital_twin.gif").write_bytes((OUT / "digital_twin.gif").read_bytes())

    # data-stream attribution figure (which sensors set each state, and where)
    shares = make_attribution_figure(grid, static, OUT / "digital_twin_attribution.png")
    (ASSETS / "digital_twin_attribution.png").write_bytes(
        (OUT / "digital_twin_attribution.png").read_bytes())

    meta.update(n_frames=N_FRAMES, dt_days=DT_DAYS, span_days=DT_DAYS * (N_FRAMES - 1),
                display_px=list(grid["shape"]), poster_frame=frame,
                vs30_source=("fetched" if (PROC / "vs30_90m.tif").exists() else "synthetic-from-HAND"),
                attribution=shares)
    (PROC / "digital_twin_summary.json").write_text(json.dumps(meta, indent=2))
    print("wrote twin + attribution; summary:", json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
