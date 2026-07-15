"""dv/v at the stations -> kernels -> a soil-moisture & water-table PROXY between the stations.

Run: ``pixi run dvv-proxy-demo``

The point the report needs to make concrete: we do NOT forecast a gridded dv/v field. dv/v is measured
(here, a reasonable synthetic) only AT the seismic stations; its coda kernels then carry that
information into the volume between them, and a BLUE update turns it into an estimate of the two states
the twin actually predicts -- soil moisture (shallow band) and the water table (deep band). This
demonstrates, and tests, the whole inverse chain: forward (state -> station dv/v) then inverse (station
dv/v -> inter-station state).
"""
from __future__ import annotations

import shutil
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rioxarray as rxr
from pyproj import Transformer

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROC = Path("data/processed")
ASSETS = Path("docs/twin/assets")
OUT = Path("figures/demo/dvv_proxy.png")
STEP = 22
S_THETA, K_SAT = -1.0, 5.0e-4          # dv/v per unit theta (shallow band); dv/v per m head (deep band)
SEED = 7                               # a notebook may seed RNG; workflow scripts may not


def main():
    try:
        from src.viz.fonts import register_inter
        register_inter()
    except Exception:
        pass
    from src.config.domain import DOMAIN
    from src.models.dvv_sensitivity import network_sensitivity, pair_kernel, single_station_kernel
    from src.models.observability import GaussianPrior, blue_update, normalise_footprint, resolution

    hand = rxr.open_rasterio(PROC / "terrain_hand_domain_90m.tif", masked=True).squeeze("band", drop=True)
    sub = hand.isel(y=slice(None, None, STEP), x=slice(None, None, STEP))
    land = np.isfinite(sub.values).ravel()
    gx, gy = np.meshgrid(sub.x.values / 1000.0, sub.y.values / 1000.0)
    coords = np.column_stack([gx.ravel(), gy.ravel()])
    shp = gx.shape
    x0, y0, x1, y1 = DOMAIN.bounds()

    seis = pd.read_parquet("data/cache/seismic/inventory_UW-CC.parquet")
    tf = Transformer.from_crs("EPSG:4326", DOMAIN.crs, always_xy=True)
    sxm, sym = tf.transform(seis.lon.values, seis.lat.values)
    inside = (sxm >= x0) & (sxm <= x1) & (sym >= y0) & (sym <= y1)
    st_km = np.column_stack([sxm[inside] / 1000.0, sym[inside] / 1000.0])

    # --- a reasonable "true" state: a smooth sample from each state's own prior --------------------
    rng = np.random.default_rng(SEED)
    B_sm = GaussianPrior(1.0, 8.0).cov(coords)             # soil moisture: shorter correlation
    B_gwl = GaussianPrior(1.0, 12.0).cov(coords)           # water table: smoother
    def sample(B):
        L = np.linalg.cholesky(B + 1e-8 * np.eye(len(B)))
        return L @ rng.standard_normal(len(B))
    truth_sm = np.where(land, sample(B_sm), np.nan)
    truth_gwl = np.where(land, sample(B_gwl), np.nan)

    # --- dv/v OBSERVATION operators: single-station autocorrelations + inter-station pairs ---------
    foot = []
    for i in range(len(st_km)):
        foot.append(normalise_footprint(single_station_kernel(gx, gy, st_km[i])))
        for j in range(i + 1, len(st_km)):
            if np.hypot(*(st_km[i] - st_km[j])) <= 40.0:
                foot.append(normalise_footprint(pair_kernel(gx, gy, st_km[i], st_km[j])))
    G = np.vstack(foot)                                    # (n_obs, n_cell), each row a coda footprint

    tsm = np.nan_to_num(truth_sm); tgwl = np.nan_to_num(truth_gwl)
    noise = 0.12                                           # dv/v measurement+processing error (rel.)
    # forward: each footprint sees a coda-weighted average of the true state -> synthetic dv/v
    dvv_shallow = S_THETA * (G @ tsm) + noise * rng.standard_normal(G.shape[0])
    dvv_deep = K_SAT * (G @ tgwl) + noise * K_SAT * rng.standard_normal(G.shape[0])
    # inverse: divide out the band sensitivity -> a state-equivalent datum, then BLUE through the kernels
    sm_proxy, _ = blue_update(B_sm, G, dvv_shallow / S_THETA, noise_var=(noise) ** 2)
    gwl_proxy, _ = blue_update(B_gwl, G, dvv_deep / K_SAT, noise_var=(noise) ** 2)
    res_sm, _ = resolution(B_sm, G, noise ** 2)
    res_gwl, _ = resolution(B_gwl, G, noise ** 2)

    # per-station dv/v (the single-station rows are the first entries; take autocorr magnitude for display)
    auto = np.array([normalise_footprint(single_station_kernel(gx, gy, s)) for s in st_km])
    dvv_st_sm = S_THETA * (auto @ tsm)
    dvv_st_gwl = K_SAT * (auto @ tgwl)

    m = lambda v: np.where(land, v, np.nan).reshape(shp)   # noqa: E731
    stx = (st_km[:, 0] * 1000 - x0) / (DOMAIN.res_m * STEP)
    sty = (y1 - st_km[:, 1] * 1000) / (DOMAIN.res_m * STEP)

    fig, ax = plt.subplots(2, 4, figsize=(19.5, 9.7), constrained_layout=True)
    rows = [
        ("SOIL MOISTURE", "#3BB273", truth_sm, sm_proxy, res_sm, dvv_st_sm, "shallow band  $\\propto\\,S_\\theta$"),
        ("WATER TABLE", "#2E86AB", truth_gwl, gwl_proxy, res_gwl, dvv_st_gwl, "deep band  $\\propto\\,k_{sat}$"),
    ]
    for r, (state, col, truth, proxy, res, dvv_st, band) in enumerate(rows):
        vlim = np.nanpercentile(np.abs(truth), 96)
        kw = dict(cmap="RdBu_r", vmin=-vlim, vmax=vlim)
        cm = plt.get_cmap("RdBu_r").copy(); cm.set_bad("#eef0f3")

        ax[r, 0].imshow(m(truth), cmap=cm, **{k: v for k, v in kw.items() if k != "cmap"})
        ax[r, 0].set_title("True %s anomaly" % state.lower(), fontsize=10.5, fontweight="bold")

        ax[r, 1].imshow(m(truth), cmap=plt.get_cmap("Greys"), alpha=.25)
        sc = ax[r, 1].scatter(stx, sty, c=dvv_st, cmap="RdBu_r", s=60, edgecolors="k", linewidths=.4,
                              vmin=-np.percentile(np.abs(dvv_st), 96), vmax=np.percentile(np.abs(dvv_st), 96))
        ax[r, 1].set_title("Synthetic dv/v AT stations\n(%s)" % band, fontsize=10.5, fontweight="bold")
        fig.colorbar(sc, ax=ax[r, 1], shrink=.7, label="dv/v")

        im = ax[r, 2].imshow(m(proxy), cmap=cm, **{k: v for k, v in kw.items() if k != "cmap"})
        ax[r, 2].scatter(stx, sty, s=10, c="k", marker="*")
        ax[r, 2].set_title("Recovered proxy (BLUE)\nbetween stations", fontsize=10.5, fontweight="bold")
        fig.colorbar(im, ax=ax[r, 2], shrink=.7, label="anomaly")

        err = np.where(res > 0.1, proxy - truth, np.nan)    # show error only where dv/v constrains it
        ev = np.nanpercentile(np.abs(err), 96) if np.isfinite(err).any() else 1.0
        cm2 = plt.get_cmap("PuOr").copy(); cm2.set_bad("#eef0f3")
        im = ax[r, 3].imshow(m(err), cmap=cm2, vmin=-ev, vmax=ev)
        ax[r, 3].set_title("Error where constrained\n(proxy − truth)", fontsize=10.5, fontweight="bold")
        fig.colorbar(im, ax=ax[r, 3], shrink=.7)

        for a in ax[r]:
            a.set_xticks([]); a.set_yticks([])
        ax[r, 0].set_ylabel(state, fontsize=12, fontweight="bold", color=col, labelpad=8)

    fig.suptitle("dv/v is measured only AT the stations; its coda kernels carry it into the volume "
                 "between them\nForward: state → station dv/v.   Inverse (BLUE through the kernels): "
                 "station dv/v → a soil-moisture & water-table proxy",
                 fontsize=12.5, fontweight="bold")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=120, bbox_inches="tight", facecolor="white")
    shutil.copy(OUT, ASSETS / OUT.name)
    # a one-line skill number for the caption
    ok = res_sm > 0.3
    r_sm = np.corrcoef(sm_proxy[ok], np.nan_to_num(truth_sm)[ok])[0, 1] if ok.sum() else np.nan
    print("wrote %s  (%d stations, %d dv/v footprints; SM proxy r=%.2f where well-constrained)"
          % (OUT, len(st_km), G.shape[0], r_sm))


if __name__ == "__main__":
    main()
