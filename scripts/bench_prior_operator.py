#!/usr/bin/env python3
"""Ground-truth benchmark for the competing prior representations (issues #154 / #163).

Question this settles: can the assimilation compute what it needs WITHOUT forming the dense
(n, n) prior C, and do the two candidate implementations reproduce the production prior?

  dense   -- production GaussianPrior.cov() on main. Matern nu=1.5. REFERENCE ONLY, never production.
  direct  -- minimal operator form written here: C @ G.T by kernel evaluation over each footprint's
             SUPPORT only. Never forms C. Preserves nu=1.5 exactly.
  A       -- StationaryGridPrior (PR #216 / commit 658493d): FFT / circulant embedding.
  B       -- SparseMaternPrior  (PR #215 / commit 2414434): GMRF/SPDE sparse precision, nu=1.

Everything the BLUE needs is  diag(C),  Bx = C @ G.T,  S = G @ Bx + R.  The full C is never required.

Usage:
    pixi run python scripts/bench_prior_operator.py --ny 160 --nx 160 --state gwl
    pixi run python scripts/bench_prior_operator.py --ny 200 --nx 200 --no-dense   # scaling only
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SHA_A = "658493d"   # PR #216 StationaryGridPrior
SHA_B = "2414434"   # PR #215 SparseMaternPrior

# Production priors (src/models/observability.py docstrings, notebooks/make_twin_gif.py)
PRIORS = {
    "gwl": dict(sigma=0.5,  length_km=12.0, label="water-table anomaly (m)"),
    "sm":  dict(sigma=0.03, length_km=8.0,  label="soil moisture (m3/m3)"),
}
RES_KM = 0.090          # native 90 m
NU_PROD = 1.5           # production Matern smoothness on main (PR #181)


# ----------------------------------------------------------------- loading the candidates
def load_module_from_git(sha: str, path: str, name: str):
    """Import a module from a git blob without checking anything out or merging."""
    src = subprocess.run(["git", "-C", str(REPO), "show", f"{sha}:{path}"],
                         capture_output=True, text=True, check=True).stdout
    tmp = Path(tempfile.gettempdir()) / f"{name}.py"
    tmp.write_text(src)
    spec = importlib.util.spec_from_file_location(name, tmp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------- the test domain
def build_domain(ny: int, nx: int, n_regions: int):
    """Native-90-m raster, y DESCENDING (north-up, the convention every caller uses)."""
    x_km = np.arange(nx) * RES_KM
    y_km = np.arange(ny)[::-1] * RES_KM
    gx, gy = np.meshgrid(x_km, y_km)
    coords = np.column_stack([gx.ravel(), gy.ravel()])

    # Drainage-like regions: an irregular (non-axis-aligned, wiggly) partition, so region
    # boundaries are not aligned with the FFT grid axes -- an axis-aligned split would be an
    # unrealistically easy case for a Toeplitz/FFT representation.
    xx, yy = gx.ravel(), gy.ravel()
    span_x, span_y = nx * RES_KM, ny * RES_KM
    phase = np.sin(2.0 * np.pi * yy / max(span_y, 1e-9)) * 0.12 * span_x
    if n_regions <= 1:
        region = np.zeros(coords.shape[0], dtype=np.int64)
    else:
        edges = np.linspace(0, span_x, n_regions + 1)[1:-1]
        region = np.zeros(coords.shape[0], dtype=np.int64)
        for e in edges:
            region += (xx > e + phase).astype(np.int64)
    return coords, region.astype(np.int64), (ny, nx)


def build_observations(coords, region, shape, obs_mod, dvv_mod):
    """The five cases the task asks for, plus enough point sensors to be a realistic design."""
    ny, nx = shape
    x_km = coords[:, 0].reshape(shape)[0, :]
    y_km = coords[:, 1].reshape(shape)[:, 0]
    gx = coords[:, 0].reshape(shape)
    gy = coords[:, 1].reshape(shape)
    rows, meta = [], []

    def add(g, kind, note):
        g = obs_mod.normalise_footprint(g)
        if g.sum() <= 0:
            return
        rows.append(g)
        meta.append((kind, note))

    reg2d = region.reshape(shape)
    # a cell deep inside region 0, and a cell adjacent to a region boundary
    r0 = np.argwhere(reg2d == reg2d[ny // 2, nx // 8])
    interior = r0[len(r0) // 2]
    # find a boundary cell: region changes between horizontal neighbours
    chg = np.argwhere(reg2d[:, 1:] != reg2d[:, :-1])
    bnd = chg[len(chg) // 2] if len(chg) else interior

    # 1. point observation well inside one region
    add(obs_mod.point_footprint(coords, (gx[tuple(interior)], gy[tuple(interior)])),
        "point", "interior of a region")
    # 2. point observation one cell from a region boundary
    add(obs_mod.point_footprint(coords, (gx[bnd[0], bnd[1]], gy[bnd[0], bnd[1]])),
        "point", "adjacent to a region boundary")
    # 3. multiple regions: one point per region
    for rid in np.unique(region):
        cells = np.argwhere(reg2d == rid)
        c = cells[len(cells) // 2]
        add(obs_mod.point_footprint(coords, (gx[c[0], c[1]], gy[c[0], c[1]])),
            "point", f"centre of region {rid}")
    # 4. dv/v volume footprint inside one region (single-station coda)
    si = (gx[tuple(interior)], gy[tuple(interior)])
    add(dvv_mod.single_station_kernel(gx, gy, si).ravel(), "dvv", "single-station, interior")
    # 5. dv/v pair footprint straddling a region boundary
    lo = np.argwhere(reg2d == reg2d[ny // 2, nx // 6])
    hi = np.argwhere(reg2d == reg2d[ny // 2, (5 * nx) // 6])
    if len(lo) and len(hi):
        a = lo[len(lo) // 2]; b = hi[len(hi) // 2]
        add(dvv_mod.pair_kernel(gx, gy, (gx[a[0], a[1]], gy[a[0], a[1]]),
                                (gx[b[0], b[1]], gy[b[0], b[1]])).ravel(),
            "dvv", "station pair, crosses region boundary")
    return np.vstack(rows), meta


# ----------------------------------------------------------------- the minimal operator form
def effective_support(g, mass_tol=1e-12):
    """Smallest index set carrying all but ``mass_tol`` of a footprint's absolute mass.

    ``np.nonzero(g)`` is NOT the support of a Gaussian footprint in floating point. A
    ``point_footprint`` on a 40x40 grid has 1177 of 1600 cells nonzero -- 74% of the domain --
    because the tail only underflows around 1e-322, while 99.999995% of the mass sits in the
    top ~25 cells. Taking nonzero as the support therefore made ``cross_direct`` cost ~74% of
    dense for the commonest observation type while still being described as support-restricted.
    (Found by Copilot review on PR #217.)

    The truncation is bounded, not heuristic. Since ``Bx[:, i] = sigma^2 * sum_j corr(x, x_j) g_j``
    and ``|corr| <= 1``, dropping a set D changes the result by at most ``sigma^2 * sum_{j in D} |g_j|``.
    So the absolute error is ``<= sigma^2 * mass_tol`` by construction -- at the default, ~1e-12
    of the prior variance, orders of magnitude below any comparison threshold in this benchmark.
    """
    a = np.abs(g)
    total = a.sum()
    if total == 0:
        return np.empty(0, dtype=np.intp)
    order = np.argsort(a)[::-1]
    keep = np.searchsorted(np.cumsum(a[order]), (1.0 - mass_tol) * total) + 1
    return np.sort(order[:keep])


def cross_direct(obs_mod, sigma, length_km, nu, region, coords, G, block=4096, mass_tol=1e-12):
    """C @ G.T evaluated from the Matern kernel over each footprint's SUPPORT. Never forms C.

    "Support" means the *effective* support -- the smallest cell set carrying all but
    ``mass_tol`` of the footprint's mass (see :func:`effective_support`), NOT every cell where
    ``g`` is bitwise nonzero. The induced error is bounded by ``sigma^2 * mass_tol``.

    Cost is n * |supp(g_i)| per observation, so it is the right method for compact footprints
    (wells, SNOTEL) and degenerates towards dense for a footprint that genuinely covers the
    domain -- a dv/v volume kernel does; a point sensor does not, and previously was treated
    as though it did.
    """
    n = coords.shape[0]
    out = np.zeros((n, G.shape[0]), dtype="float64")
    supp_sizes = []
    for i, g in enumerate(G):
        supp = effective_support(g, mass_tol)
        supp_sizes.append(supp.size)
        if supp.size == 0:
            continue
        acc = np.zeros(n, dtype="float64")
        for s in range(0, supp.size, block):
            sl = supp[s:s + block]
            d = np.sqrt(((coords[:, None, :] - coords[sl][None, :, :]) ** 2).sum(-1))
            corr = obs_mod.matern_correlation(d, length_km, nu)
            if region is not None:
                corr *= (region[:, None] == region[sl][None, :])
            acc += corr @ g[sl]
        out[:, i] = (sigma ** 2) * acc
    # Reported, not silent: a method that claims to be support-restricted has to show what
    # fraction of the domain it actually touched, or the claim is unfalsifiable.
    cross_direct.last_support = dict(
        n=n, mean=float(np.mean(supp_sizes)), max=int(np.max(supp_sizes)),
        min=int(np.min(supp_sizes)), mean_frac=float(np.mean(supp_sizes) / n),
        mass_tol=mass_tol)
    return out


# ----------------------------------------------------------------- BLUE from B and S only
def blue_from_cross(Bx, G, diagC, d, noise_var, prior_mean=0.0):
    """Everything assimilation needs, from B = C G^T and S = G B + R. No (n, n) anywhere."""
    nv = np.broadcast_to(np.asarray(noise_var, float), (G.shape[0],))
    S = G @ Bx + np.diag(nv)
    innov = np.asarray(d, float) - G @ np.broadcast_to(np.asarray(prior_mean, float), (Bx.shape[0],))
    m_post = np.broadcast_to(np.asarray(prior_mean, float), (Bx.shape[0],)) + Bx @ np.linalg.solve(S, innov)
    X = np.linalg.solve(S, Bx.T)                       # (n_obs, n)
    reduction = np.einsum("ij,ji->i", Bx, X)
    reduction = np.clip(reduction, 0.0, diagC)
    var_post = diagC - reduction
    res = np.where(diagC > 0, reduction / diagC, 0.0)
    return m_post, var_post, res, S


def peak_gb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6


def rel_err(a, b):
    den = np.linalg.norm(b)
    return float(np.linalg.norm(a - b) / den) if den > 0 else float("nan")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ny", type=int, default=140)
    p.add_argument("--nx", type=int, default=140)
    p.add_argument("--state", choices=list(PRIORS), default="gwl")
    p.add_argument("--regions", type=int, default=3)
    p.add_argument("--no-dense", action="store_true", help="skip the dense reference (scaling runs)")
    p.add_argument("--length-km", type=float, default=None,
                   help="override the production correlation length (to span several L on a "
                        "dense-feasible domain); default is the production value")
    p.add_argument("--skip-direct", action="store_true",
                   help="skip the O(n*|supp|) direct form (it is exact but slow at full support)")
    p.add_argument("--standardize", action="store_true",
                   help="B only: renormalize the SPDE marginal variance (its own remedy for the "
                        "reflecting-boundary inflation)")
    p.add_argument("--json", type=str, default="")
    args = p.parse_args()

    pr = PRIORS[args.state]
    sigma = pr["sigma"]
    L = args.length_km if args.length_km else pr["length_km"]
    n = args.ny * args.nx
    print(f"# domain {args.ny} x {args.nx} = {n:,} cells at {RES_KM*1000:.0f} m "
          f"({args.ny*RES_KM:.1f} x {args.nx*RES_KM:.1f} km)")
    print(f"# state={args.state} sigma={sigma} L={L} km  -> domain is "
          f"{args.nx*RES_KM/L:.2f} correlation lengths across; nu={NU_PROD}; regions={args.regions}")
    print(f"# dense C would be {n*n*8/1e9:.2f} GB")

    obs = importlib.import_module("src.models.observability")
    dvv = importlib.import_module("src.models.dvv_sensitivity")
    modA = load_module_from_git(SHA_A, "src/models/observability.py", "obs_A")
    modB = load_module_from_git(SHA_B, "src/models/observability.py", "obs_B")

    coords, region, shape = build_domain(args.ny, args.nx, args.regions)
    G, meta = build_observations(coords, region, shape, obs, dvv)
    nv = np.full(G.shape[0], (0.15 ** 2))
    rng = np.random.default_rng(11)
    d_obs = rng.normal(0.0, sigma, size=G.shape[0])

    print(f"\n## observations ({G.shape[0]})")
    print(f"{'#':>3}  {'kind':5}  {'nnz':>9}  {'eff99.9%':>9}  {'eff%':>6}  {'regions':>7}  note")
    for i, (kind, note) in enumerate(meta):
        g = np.abs(G[i]); nnz = int((g != 0).sum())
        srt = np.sort(g)[::-1]; cum = np.cumsum(srt) / max(srt.sum(), 1e-300)
        eff = int(np.searchsorted(cum, 0.999) + 1)
        spanned = len(np.unique(region[G[i] != 0]))
        print(f"{i:>3}  {kind:5}  {nnz:>9,}  {eff:>9,}  {100*eff/n:>5.1f}%  {spanned:>7}  {note}")

    results = {}

    # ---- dense reference -------------------------------------------------------------------
    if not args.no_dense:
        t0 = time.perf_counter()
        prior = obs.GaussianPrior(sigma=sigma, length_km=L, nu=NU_PROD, region_id=region)
        C = prior.cov(coords)
        t_build = time.perf_counter() - t0
        t0 = time.perf_counter()
        Bx_dense = C @ G.T
        t_cross = time.perf_counter() - t0
        diagC = np.diag(C).copy()
        m_d, v_d, r_d, S_d = blue_from_cross(Bx_dense, G, diagC, d_obs, nv)
        results["dense"] = dict(Bx=Bx_dense, m=m_d, v=v_d, r=r_d, S=S_d,
                                t_build=t_build, t_cross=t_cross, mem=peak_gb())
        print(f"\n## dense reference built in {t_build:.2f}s (+{t_cross:.2f}s for C@G.T), "
              f"peak {peak_gb():.2f} GB")
        print(f"   diag(C) exact? max|diag-sigma^2| = {np.abs(diagC - sigma**2).max():.3e}")
        del C

    # ---- direct operator form --------------------------------------------------------------
    if not args.skip_direct:
     t0 = time.perf_counter()
     Bx_dir = cross_direct(obs, sigma, L, NU_PROD, region, coords, G)
     t_dir = time.perf_counter() - t0
     diagC_an = np.full(n, sigma ** 2)
     m_x, v_x, r_x, S_x = blue_from_cross(Bx_dir, G, diagC_an, d_obs, nv)
     supp = cross_direct.last_support
     results["direct"] = dict(Bx=Bx_dir, m=m_x, v=v_x, r=r_x, S=S_x, t_cross=t_dir,
                              mem=peak_gb(), support=supp)
     print(f"\n## direct: effective support {supp['mean']:.0f} of {supp['n']} cells on average "
           f"({100*supp['mean_frac']:.2f}% of the domain), min {supp['min']}, max {supp['max']}")
     print(f"   mass_tol={supp['mass_tol']:g} => absolute error bound sigma^2*mass_tol "
           f"= {sigma**2 * supp['mass_tol']:.2e}")

    # ---- A: StationaryGridPrior (FFT) ------------------------------------------------------
    try:
        pA = modA.GaussianPrior(sigma=sigma, length_km=L, nu=NU_PROD, region_id=region)
        t0 = time.perf_counter()
        opA = pA.operator(coords)
        Bx_A = opA @ G.T
        t_A = time.perf_counter() - t0
        diagA = np.asarray(opA.diagonal())
        m_a, v_a, r_a, S_a = blue_from_cross(Bx_A, G, diagA, d_obs, nv)
        results["A"] = dict(Bx=Bx_A, m=m_a, v=v_a, r=r_a, S=S_a, t_cross=t_A, mem=peak_gb())
    except Exception as e:
        results["A"] = dict(error=f"{type(e).__name__}: {e}")

    # ---- B: SparseMaternPrior (SPDE/GMRF, nu=1) --------------------------------------------
    try:
        t0 = time.perf_counter()
        pB = modB.SparseMaternPrior(sigma=sigma, length_km=L, shape=shape, dx_km=RES_KM,
                                    dy_km=RES_KM, region_id=region, nu=1.0,
                                    standardize=args.standardize)
        Bx_B = pB.solve(np.ascontiguousarray(G.T))       # Q^-1 G^T = C_spde G^T
        t_B = time.perf_counter() - t0
        try:
            diagB = np.asarray(pB.marginal_var())
        except Exception:
            diagB = np.full(n, sigma ** 2)
        m_b, v_b, r_b, S_b = blue_from_cross(Bx_B, G, diagB, d_obs, nv)
        results["B"] = dict(Bx=Bx_B, m=m_b, v=v_b, r=r_b, S=S_b, t_cross=t_B, mem=peak_gb(),
                            diag=diagB)
    except Exception as e:
        results["B"] = dict(error=f"{type(e).__name__}: {e}")

    # ---- report ----------------------------------------------------------------------------
    print("\n## numerical comparison, primary metric = C @ G.T")
    hdr = f"{'impl':7} {'relFro(B)':>11} {'maxabs(B)':>11} {'relFro(mpost)':>14} {'relFro(res)':>12} {'t(C@G.T) s':>11} {'peak GB':>8}"
    print(hdr); print("-" * len(hdr))
    ref = results.get("dense")
    for key in ("dense", "direct", "A", "B"):
        r = results.get(key)
        if r is None:
            continue
        if "error" in r:
            print(f"{key:7} FAILED: {r['error'][:70]}")
            continue
        if ref is None or key == "dense":
            e1 = e2 = e3 = e4 = 0.0 if key == "dense" else float("nan")
        else:
            e1 = rel_err(r["Bx"], ref["Bx"])
            e2 = float(np.abs(r["Bx"] - ref["Bx"]).max())
            e3 = rel_err(r["m"], ref["m"])
            e4 = rel_err(r["r"], ref["r"])
        print(f"{key:7} {e1:>11.3e} {e2:>11.3e} {e3:>14.3e} {e4:>12.3e} "
              f"{r.get('t_cross', float('nan')):>11.3f} {r.get('mem', float('nan')):>8.2f}")

    if ref is not None and "A" in results and "Bx" in results["A"]:
        print("\n## per-observation error of A vs dense (isolates which footprint type breaks)")
        print(f"{'#':>3}  {'kind':5}  {'relFro':>11}  {'maxabs':>11}  note")
        for i, (kind, note) in enumerate(meta):
            e = rel_err(results["A"]["Bx"][:, i], ref["Bx"][:, i])
            m = float(np.abs(results["A"]["Bx"][:, i] - ref["Bx"][:, i]).max())
            print(f"{i:>3}  {kind:5}  {e:>11.3e}  {m:>11.3e}  {note}")

    if "B" in results and "diag" in results["B"]:
        db = results["B"]["diag"]
        print(f"\n## B marginal variance vs stationary sigma^2={sigma**2:.4g}: "
              f"mean={db.mean():.4g} min={db.min():.4g} max={db.max():.4g} "
              f"(rel spread {np.ptp(db)/max(db.mean(),1e-300):.2%})")

    if args.json:
        out = {k: {kk: (float(vv) if np.isscalar(vv) else None)
                   for kk, vv in v.items() if kk not in ("Bx", "m", "v", "r", "S", "diag")}
               for k, v in results.items()}
        out["_meta"] = dict(n=n, ny=args.ny, nx=args.nx, state=args.state,
                            regions=args.regions, sigma=sigma, L=L)
        Path(args.json).write_text(json.dumps(out, indent=2))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
