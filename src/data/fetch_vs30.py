"""Vs30 (time-averaged shear-wave velocity, top 30 m) for the near-surface stiffness product.

Replaces the earlier synthetic HAND ramp (issue #54) with defensible Vs30 from four sources, best first:

  1. **Soil Velocity Model, SVM (preferred).** Grant, Wirth & Stone (2025, Seismica; doi
     10.26443/seismica.v4i2.1672) build measurement-based Vs(z) profiles for four Holocene PNW soil
     provinces (Puget Lowlands, Willamette Valley, fill-and-alluvium, other) from 649 measured
     profiles, embedded in the USGS Cascadia velocity-model data release (doi 10.5066/P14HJ3IC). Vs30
     is the top-30 m travel-time average of the SVM shallow Vs. This is the best regional near-surface
     Vs constraint for the Pacific Northwest; used when staged, else it falls back to the slope proxy.
  2. **Wald-Allen slope proxy (always available).** Wald & Allen (2007) / Allen & Wald (2009) map
     topographic slope to Vs30 -- steeper terrain is stiffer, flat valley fill is soft. The standard
     terrain proxy behind the USGS global Vs30 model, applied to the native 90 m 3DEP slope
     (active-tectonic bins for Cascadia).
  3. **USGS global Vs30 grid** (the official product; a large ~30 arc-second GMT grid). Fetched and
     clipped where reachable; falls back to the slope proxy.
  4. **Sanger-Maurer parametric Vs30** (GAIA vs-STAC) -- a geology + geomorphon model. Placeholder
     that delegates to :func:`src.data.fetch_gaia.fetch_vs30`; the STAC is not always reachable.

Output: ``data/processed/vs30_90m.tif`` (EPSG:5070, 90 m). Unlike the HAND ramp, this is a real
site-condition estimate suitable (with its uncertainty) for NEHRP site class -- see the geotechnical
review in ``docs/peer_review.md``.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger("fetch_vs30")

PUGET_CASCADES_BBOX = (-123.3, 46.8, -120.8, 48.5)
USGS_GLOBAL_VS30_GRD = "https://apps.usgs.gov/shakemap_geodata/vs30/global_vs30.grd"

# Wald & Allen (2007) topographic-slope -> Vs30. Slope as gradient (m/m); Vs30 in m/s. Bins map to
# NEHRP classes E(180) / D(240-360) / C(490-620) / B(760). ACTIVE-TECTONIC table (Cascadia). Lower
# bin edges (exclusive-upper) and the Vs30 assigned at/above each edge. Verify against OFR 2007-1357.
_WA_ACTIVE_EDGES = np.array([2.2e-3, 6.3e-3, 0.018, 0.050, 0.10, 0.138])
_WA_ACTIVE_VS30 = np.array([180.0, 240.0, 300.0, 360.0, 490.0, 620.0, 760.0])
# Stable-continental bins are steeper for a given Vs30; not used for the PNW (kept for completeness).
_WA_STABLE_EDGES = np.array([2.0e-5, 2.0e-3, 4.0e-3, 7.2e-3, 0.013, 0.018])
_WA_STABLE_VS30 = np.array([180.0, 240.0, 300.0, 360.0, 490.0, 620.0, 760.0])


def wald_allen_vs30(slope_deg, region="active"):
    """Vs30 (m/s) from topographic slope (degrees) via the Wald-Allen binned proxy.

    ``region`` is ``"active"`` (default; Cascadia) or ``"stable"``. Slope is converted to gradient
    (tan of the angle) and binned. NaN slope -> NaN Vs30.
    """
    edges, vs30 = ((_WA_ACTIVE_EDGES, _WA_ACTIVE_VS30) if region == "active"
                   else (_WA_STABLE_EDGES, _WA_STABLE_VS30))
    s = np.asarray(slope_deg, dtype="float64")
    grad = np.tan(np.deg2rad(s))
    idx = np.digitize(grad, edges)                      # 0..len(edges) -> vs30 bin
    out = vs30[np.clip(idx, 0, len(vs30) - 1)]
    return np.where(np.isfinite(s), out, np.nan).astype("float32")


# NEHRP / ASCE 7 site-class Vs30 boundaries (m/s), soft -> stiff, and the classes they separate:
# E < 180 < D < 360 < C < 760 < B < 1500 < A. A design engineer reads P(class) and P(crossing a
# boundary), not a raw percent sigma -- issue #53.
NEHRP_BOUNDS = np.array([180.0, 360.0, 760.0, 1500.0])
NEHRP_CLASSES = ("E", "D", "C", "B", "A")


def nehrp_class_probabilities(vs30_mean, vs30_std, lognormal=False):
    """P(NEHRP site class) from a Vs30 estimate and its 1-sigma.

    Returns probabilities ``P(E, D, C, B, A)`` that the *true* Vs30 falls in each ASCE 7 / NEHRP
    class, with a trailing axis of length 5. Scalars return a length-5 vector; arrays broadcast over
    the input shape (so a whole Vs30 field maps to a per-cell class-probability stack). This turns the
    Vs30 uncertainty into the quantity a geotechnical design consumer needs -- P(class) and, by
    differencing the CDF, P(Vs30 crossing 180 / 360 / 760 m/s) -- rather than a raw percent sigma.

    ``lognormal=True`` treats ``vs30_std`` as the sigma of ln(Vs30) (the field-standard multiplicative
    error model, and requires ``vs30_mean > 0``); otherwise ``vs30_std`` is a linear m/s sigma
    (matching the dv/v-propagated 1-sigma). A zero sigma collapses to a one-hot class assignment
    (the deterministic bin of the mean). ``vs30_std`` must be non-negative.
    """
    from scipy.stats import norm

    mu = np.asarray(vs30_mean, dtype="float64")
    sd = np.asarray(vs30_std, dtype="float64")
    if np.any(sd < 0):
        raise ValueError("vs30_std must be non-negative")
    if lognormal and np.any(mu <= 0):
        raise ValueError("lognormal=True requires vs30_mean > 0")
    mu, sd = np.broadcast_arrays(mu, sd)                   # common shape so the zero-sd mask lines up
    with np.errstate(divide="ignore", invalid="ignore"):
        loc = np.log(mu)[..., None] if lognormal else mu[..., None]
        bnd = np.log(NEHRP_BOUNDS) if lognormal else NEHRP_BOUNDS
        cdf = norm.cdf((bnd - loc) / sd[..., None])        # P(Vs30 <= each boundary), shape (..., 4)
    lower = np.concatenate([np.zeros(cdf.shape[:-1] + (1,)), cdf], axis=-1)
    upper = np.concatenate([cdf, np.ones(cdf.shape[:-1] + (1,))], axis=-1)
    probs = upper - lower                                  # P in (E, D, C, B, A), shape (..., 5)
    zero = sd == 0                                         # sd==0 -> 0/0 NaN on an exact boundary
    if np.any(zero):
        onehot = np.eye(len(NEHRP_CLASSES))[np.digitize(mu, NEHRP_BOUNDS)]
        probs = np.where(zero[..., None], onehot, probs)
    return probs


def most_likely_nehrp_class(vs30_mean, vs30_std, lognormal=False):
    """(class_label, probability) of the most probable NEHRP class for a *scalar* Vs30 estimate."""
    p = nehrp_class_probabilities(vs30_mean, vs30_std, lognormal=lognormal)
    i = int(np.argmax(p))
    return NEHRP_CLASSES[i], float(p[i])


def vs30_from_slope(slope_tif, region="active"):
    """Apply the Wald-Allen proxy to a slope raster (degrees); returns a Vs30 DataArray (m/s)."""
    import rioxarray as rxr

    slope = rxr.open_rasterio(slope_tif, masked=True).squeeze("band", drop=True)
    vs = wald_allen_vs30(slope.values, region=region)
    return slope.copy(data=vs).rio.write_crs(slope.rio.crs)


def fetch_usgs_vs30(bbox=PUGET_CASCADES_BBOX, like=None, cache=Path("data/cache/vs30")):
    """Download + clip the USGS global Vs30 grid; returns a DataArray or None if unreachable.

    The global grid is a large (~600 MB) 30 arc-second GMT file; this attempts the documented URL,
    clips to ``bbox``, and (if ``like`` given) reprojects to that grid. On any failure it logs and
    returns None so the caller falls back to the slope proxy. Cached once downloaded.
    """
    import rioxarray as rxr

    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    local = cache / "global_vs30.grd"
    try:
        if not local.exists():
            import urllib.request
            logger.info("Downloading USGS global Vs30 grid (large) from %s ...", USGS_GLOBAL_VS30_GRD)
            urllib.request.urlretrieve(USGS_GLOBAL_VS30_GRD, local)
        w, s, e, n = bbox
        vs = rxr.open_rasterio(local, masked=True).squeeze("band", drop=True)
        vs = vs.rio.clip_box(w, s, e, n)
        return vs.rio.reproject_match(like) if like is not None else vs
    except Exception as exc:
        logger.warning("USGS Vs30 fetch unavailable (%s); use the slope proxy.", exc)
        return None


def fetch_sanger_maurer_vs30(bbox=PUGET_CASCADES_BBOX, output_dir=Path("data/processed")):
    """Placeholder: pull the Sanger-Maurer parametric Vs30 from the GAIA vs-STAC.

    Delegates to :func:`src.data.fetch_gaia.fetch_vs30` (the GAIA vs-STAC catalog). The STAC is not
    always reachable; returns the written path or None. Wired here so the pipeline can prefer the
    parametric product once the catalog is live.
    """
    try:
        from src.data.fetch_gaia import fetch_vs30 as _gaia_vs30

        return _gaia_vs30(tuple(bbox), Path(output_dir))
    except Exception as exc:
        logger.warning("Sanger-Maurer (GAIA vs-STAC) Vs30 not available yet (%s).", exc)
        return None


# Grant, Wirth & Stone (2025) Soil Velocity Model (SVM) — the preferred, measurement-based PNW
# near-surface Vs product. It gives Vs(z) profiles for four Holocene soil provinces (Puget Lowlands,
# Willamette Valley, fill-and-alluvium, other), from 649 measured profiles, embedded in the USGS
# Cascadia velocity-model data release (netCDF4 Vs grids, UTM Zone 10T).
SVM_ARTICLE_DOI = "10.26443/seismica.v4i2.1672"       # Grant, Wirth & Stone (2025), Seismica 4
SVM_DATA_RELEASE_DOI = "10.5066/P14HJ3IC"             # USGS: 3-D Cascadia velocity model w/ shallow soils v1.7


def vs30_from_vs_profile(vs, depth_m, top_m=30.0, axis=0):
    """Time-averaged shear-wave velocity over the top ``top_m`` metres: the definition of Vs30.

    ``Vs30 = top_m / T`` with the vertical travel time ``T = \\int_0^{top_m} dz / Vs(z)`` integrated to
    *exactly* ``top_m`` — when the depth grid does not land on ``top_m`` a partial top layer is added by
    linear interpolation, so the result is never silently the average over a shallower sample. ``vs`` is
    ``Vs(z, …)`` with the increasing depth coordinate ``depth_m`` (m) along ``axis``. Velocity is taken
    piecewise-linear between samples, for which a layer's travel time has the closed form
    ``Δz · ln(V2/V1) / (V2 − V1)`` (→ ``Δz / V`` as ``V2 → V1``). Returns Vs30 over the trailing dims.
    """
    vs = np.asarray(vs, dtype="float64")
    z = np.asarray(depth_m, dtype="float64")
    vs = np.moveaxis(vs, axis, 0)
    if z.ndim != 1 or z.shape[0] != vs.shape[0]:
        raise ValueError("depth_m must be 1-D and match vs along the depth axis")
    order = np.argsort(z)
    z = z[order]; vs = vs[order]
    if z[0] > 0.0:                                    # assume a surface layer at the shallowest velocity
        z = np.concatenate([[0.0], z]); vs = np.concatenate([vs[:1], vs], axis=0)
    if z[-1] < top_m:                                 # profile shallower than top_m: flat-extrapolate
        z = np.concatenate([z, [top_m]]); vs = np.concatenate([vs, vs[-1:]], axis=0)
    if z.shape[0] < 2:
        raise ValueError("need >=2 depth samples to integrate a travel time to top_m")
    eps = 1e-6                                        # one tolerance for both the node test and the cut
    if not np.any(np.abs(z - top_m) <= eps):          # insert an exact top_m node (interpolated velocity)
        k = int(np.searchsorted(z, top_m))
        frac = (top_m - z[k - 1]) / (z[k] - z[k - 1])
        v_top = vs[k - 1] + frac * (vs[k] - vs[k - 1])
        z = np.insert(z, k, top_m)
        vs = np.insert(vs, k, v_top, axis=0)
    keep = z <= top_m + eps                           # layers spanning 0..top_m only (matching tolerance)
    z = z[keep]
    vs = vs[keep]
    # snap EVERY within-eps node exactly onto top_m: gives an exact integration endpoint and keeps z
    # non-decreasing even when several nodes fall in (top_m, top_m+eps] (their zero-Δz layers add no
    # travel time) — snapping only the last node could leave a smaller predecessor and a negative dz.
    z = np.where(np.abs(z - top_m) <= eps, top_m, z)
    dz = np.diff(z)[(...,) + (None,) * (vs.ndim - 1)]  # (nlayer, 1, …) broadcast over trailing dims
    v1, v2 = vs[:-1], vs[1:]
    close = np.abs(v2 - v1) < 1e-9                    # exact piecewise-linear slowness (log-mean velocity)
    ratio = np.where(close, 2.0, v2 / np.clip(v1, 1e-9, None))   # dummy 2.0 avoids log(1)=0 where close
    v_lm = np.where(close, 0.5 * (v1 + v2), (v2 - v1) / np.log(ratio))
    travel = np.sum(dz / np.clip(v_lm, 1e-9, None), axis=0)      # Σ Δz / V_logmean = ∫ dz/Vs
    return top_m / np.clip(travel, 1e-9, None)


def vs30_surface_referenced(vs, depth_m, top_m=30.0, axis=0, min_vs=1.0):
    """Vs30 measured from each column's **ground surface**, not from the depth datum.

    The SVM/CVM grid carries topography on a depth axis referenced to sea level, so "the top 30 m" is
    *not* ``z in [0, top_m]``: every column's ground surface sits at its own ``z``, with void cells
    (air, water, nodata) above it. Averaging a fixed ``z`` window would therefore sample air on a ridge
    and deep rock in a valley. For each column this finds the shallowest valid sample (finite and
    ``Vs >= min_vs``, which also skips the ``Vs≈0`` water column) and integrates the travel time
    ``top_m`` *below that surface*, with the same exact piecewise-linear slowness as
    :func:`vs30_from_vs_profile`.

    Correct under either convention: when ``z`` is already surface-referenced (the first valid sample
    lands at ``z[0]`` in every column) this reduces exactly to the plain top-``top_m`` average.
    Columns with no ground, with a data gap inside the top ``top_m``, or with less than ``top_m`` of
    grid below their surface return **NaN** rather than a fabricated value.
    """
    vs = np.asarray(vs, dtype="float64")
    z = np.asarray(depth_m, dtype="float64")
    vs = np.moveaxis(vs, axis, 0)
    if z.ndim != 1 or z.shape[0] != vs.shape[0]:
        raise ValueError("depth_m must be 1-D and match vs along the depth axis")
    order = np.argsort(z)
    z = z[order]
    vs = vs[order]
    nz = z.shape[0]
    if nz < 2:
        raise ValueError("need >=2 depth samples to integrate a travel time")
    shape = vs.shape[1:]

    valid = np.isfinite(vs) & (vs >= min_vs)          # air / water / nodata are not ground
    has_ground = valid.any(axis=0)
    k0 = np.argmax(valid, axis=0)                     # shallowest valid sample = the ground surface

    # exact piecewise-linear per-layer travel time; a layer touching a void cell contributes nothing,
    # so the cumulative integral effectively starts at the ground surface
    v1, v2 = vs[:-1], vs[1:]
    good = valid[:-1] & valid[1:]
    a = np.where(good, v1, 1.0)                       # dummies keep the log finite; masked out below
    b = np.where(good, v2, 1.0)
    close = np.abs(b - a) < 1e-9
    ratio = np.where(close, 2.0, b / np.clip(a, 1e-9, None))
    v_lm = np.where(close, 0.5 * (a + b), (b - a) / np.log(ratio))
    dz = np.diff(z)[(...,) + (None,) * len(shape)]
    dt = np.where(good, dz / np.clip(v_lm, 1e-9, None), 0.0)
    cum = np.concatenate([np.zeros((1,) + shape), np.cumsum(dt, axis=0)], axis=0)      # (nz, …)

    z_surf = z[k0]
    z_targ = z_surf + top_m                           # 30 m BELOW this column's own surface
    j = np.clip(np.searchsorted(z, z_targ), 1, nz - 1)
    z_lo, z_hi = z[j - 1], z[j]
    frac = (z_targ - z_lo) / np.where(z_hi - z_lo == 0.0, 1.0, z_hi - z_lo)
    t_lo = np.take_along_axis(cum, (j - 1)[None, ...], axis=0)[0]
    t_hi = np.take_along_axis(cum, j[None, ...], axis=0)[0]
    travel = (t_lo + frac * (t_hi - t_lo)) - np.take_along_axis(cum, k0[None, ...], axis=0)[0]

    # the samples spanning [surface, surface+top_m] must be an unbroken run of valid ground
    cv = np.cumsum(valid.astype(np.int64), axis=0)
    n_valid = np.take_along_axis(cv, j[None, ...], axis=0)[0] - \
        np.take_along_axis(cv, k0[None, ...], axis=0)[0] + 1
    unbroken = n_valid == (j - k0 + 1)
    covered = (z[-1] - z_surf) >= top_m - 1e-9        # enough grid below the surface to reach top_m

    out = top_m / np.clip(travel, 1e-12, None)
    return np.where(has_ground & covered & unbroken & (travel > 0.0), out, np.nan)


def fetch_svm_vs30(bbox=PUGET_CASCADES_BBOX,
                   svm_vs30_tif=Path("data/processed/svm_vs30.tif"), svm_nc=None,
                   vs_var="vs", depth_name="depth", like=None, min_vs=1.0):
    """Vs30 from the **Soil Velocity Model** (Grant, Wirth & Stone 2025; USGS data release) — the
    preferred PNW Vs source. Returns a Vs30 DataArray (m/s) or None if the model is not staged.

    Two staging paths, tried in order:
      1. a **pre-extracted Vs30 raster** (``svm_vs30_tif``) — the recommended workflow: derive Vs30
         once from the SVM shallow-Vs grid and stage it as a GeoTIFF;
      2. an **SVM/CVM Vs netCDF** (``svm_nc``) from the data release (doi:%s) — the top-30 m Vs is
         travel-time-averaged (:func:`vs30_from_vs_profile`) and reprojected to ``like``.
    If neither is present the function logs the data-release DOI and returns None so the caller can
    fall back to the Wald-Allen slope proxy. No values are synthesised.
    """ % SVM_DATA_RELEASE_DOI
    import rioxarray as rxr

    if svm_vs30_tif and Path(svm_vs30_tif).exists():
        vs = rxr.open_rasterio(svm_vs30_tif, masked=True).squeeze("band", drop=True)
        return vs.rio.reproject_match(like) if like is not None else vs

    if svm_nc and Path(svm_nc).exists():
        try:
            import xarray as xr
            with xr.open_dataset(svm_nc) as ds:                           # close the file handle promptly
                # SURFACE-referenced: the CVM depth axis is referenced to sea level and the model
                # carries topography, so Vs30 must be integrated 30 m below each column's own ground
                # surface. (Reduces to the plain top-30 m average if z is already surface-referenced.)
                vs30 = vs30_surface_referenced(ds[vs_var], ds[depth_name].values,
                                               axis=ds[vs_var].dims.index(depth_name), min_vs=min_vs)
                da = ds[vs_var].isel({depth_name: 0}).copy(data=vs30)     # borrow + materialise (y, x) coords
                da.load()                                                 # detach from ds before it closes
            if da.rio.crs is None:
                da = da.rio.write_crs("EPSG:32610")                       # UTM Zone 10T
            da = da.rio.clip_box(*bbox, crs="EPSG:4326")
            return da.rio.reproject_match(like) if like is not None else da
        except Exception as exc:                                          # pragma: no cover
            logger.warning("SVM netCDF extraction failed (%s); falling back.", exc)
            return None

    logger.warning("SVM Vs grid not staged (article doi:%s / data doi:%s); stage it as %s or pass "
                   "--svm-nc, else the Wald-Allen proxy is used.",
                   SVM_ARTICLE_DOI, SVM_DATA_RELEASE_DOI, svm_vs30_tif)
    return None


def get_vs30(bbox=PUGET_CASCADES_BBOX, source="svm",
             slope_tif=Path("data/processed/terrain_slope_90m.tif"), like=None, region="active",
             svm_vs30_tif=Path("data/processed/svm_vs30.tif"), svm_nc=None,
             vs_var="vs", depth_name="depth", min_vs=1.0):
    """Unified Vs30 accessor. ``source`` in {svm, wald_allen, usgs, sanger_maurer}; the default
    **svm** (Grant, Wirth & Stone 2025) is the preferred measurement-based PNW model. Every non-proxy
    source falls back to the always-available Wald-Allen slope proxy. ``like`` reprojects the result
    onto the analysis grid (pass the 90 m terrain grid so the output co-registers with the other static
    layers). Returns a Vs30 DataArray (m/s)."""
    if source == "svm":
        vs = fetch_svm_vs30(bbox, svm_vs30_tif=svm_vs30_tif, svm_nc=svm_nc,
                            vs_var=vs_var, depth_name=depth_name, like=like, min_vs=min_vs)
        if vs is not None:
            return vs
        logger.info("Falling back to the Wald-Allen slope proxy for Vs30.")
        return vs30_from_slope(slope_tif, region=region)
    if source == "wald_allen":
        return vs30_from_slope(slope_tif, region=region)
    if source == "usgs":
        vs = fetch_usgs_vs30(bbox, like=like)
        return vs if vs is not None else vs30_from_slope(slope_tif, region=region)
    if source == "sanger_maurer":
        p = fetch_sanger_maurer_vs30(bbox)
        if p is not None and Path(p).exists():
            import rioxarray as rxr
            return rxr.open_rasterio(p, masked=True).squeeze("band", drop=True)
        logger.info("Falling back to the Wald-Allen slope proxy for Vs30.")
        return vs30_from_slope(slope_tif, region=region)
    raise ValueError(f"unknown Vs30 source {source!r}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Produce a 90 m Vs30 raster (Soil Velocity Model preferred; "
                                            "Wald-Allen slope proxy fallback).")
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"),
                   default=PUGET_CASCADES_BBOX)
    p.add_argument("--source", choices=["svm", "wald_allen", "usgs", "sanger_maurer"], default="svm")
    p.add_argument("--slope", type=Path, default=Path("data/processed/terrain_slope_90m.tif"))
    p.add_argument("--region", choices=["active", "stable"], default="active")
    p.add_argument("--svm-vs30", type=Path, default=Path("data/processed/svm_vs30.tif"),
                   help="Pre-extracted SVM Vs30 raster (Grant, Wirth & Stone 2025).")
    p.add_argument("--svm-nc", type=Path, default=None,
                   help="SVM/CVM Vs netCDF from the USGS data release (doi:10.5066/P14HJ3IC).")
    p.add_argument("--vs-var", default="vs", help="Vs variable name inside --svm-nc.")
    p.add_argument("--depth-name", default="depth", help="Depth coordinate name inside --svm-nc.")
    p.add_argument("--min-vs", type=float, default=1.0,
                   help="Vs below this (m/s) is void — air/water/nodata — when locating each column's "
                        "ground surface. The water column is Vs~0, so it is skipped.")
    p.add_argument("--like", type=Path, default=Path("data/processed/terrain_slope_90m.tif"),
                   help="Reproject the Vs30 output onto this grid (the 90 m analysis grid), so it "
                        "co-registers with the other static layers. Ignored if it does not exist.")
    p.add_argument("--output", type=Path, default=Path("data/processed/vs30_90m.tif"))
    args = p.parse_args()

    like = None
    if args.like and args.like.exists():
        import rioxarray as rxr
        like = rxr.open_rasterio(args.like, masked=True).squeeze("band", drop=True)

    vs = get_vs30(tuple(args.bbox), source=args.source, slope_tif=args.slope, region=args.region,
                  svm_vs30_tif=args.svm_vs30, svm_nc=args.svm_nc, vs_var=args.vs_var,
                  depth_name=args.depth_name, like=like, min_vs=args.min_vs)
    if vs.rio.crs is None:
        vs = vs.rio.write_crs("EPSG:5070")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    vs.rio.to_raster(args.output)
    finite = np.isfinite(vs.values)
    logger.info("Wrote Vs30 (%s) to %s | range %.0f-%.0f m/s, median %.0f",
                args.source, args.output, float(np.nanmin(vs.values)), float(np.nanmax(vs.values)),
                float(np.nanmedian(vs.values[finite])))


if __name__ == "__main__":
    main()
