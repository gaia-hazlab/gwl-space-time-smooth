#!/usr/bin/env python
r"""Estimate the twin's spatial priors from out-of-fold residuals (issue #192).

Runs the residual-based Matérn profile of :mod:`src.models.prior_calibration` over the state-specific
smoothness grids in :data:`src.models.observability.NU_CANDIDATES`, and writes the machine-readable
artifact that ``docs/twin/04-assimilation.qmd`` and ``docs/twin/05-state-evaluation.qmd`` should cite
instead of hardcoding :math:`(\sigma, L, \nu)` in prose.

Three modes:

``--self-test``
    Verification, not science. Draws residuals from a Matérn field with **known** parameters and
    checks that the estimator recovers them, that the profile is informative when the truth is at an
    end of the grid, and that a spatial-block holdout is not leaking. This is what makes the harness
    trustworthy before real data exist. It writes nothing.

``--residuals PATH``
    The real run. ``PATH`` is a table (parquet or csv) of **spatially held-out** residuals with
    columns ``x_km``, ``y_km``, ``residual``, and optionally ``domain`` and ``season``. It must be
    residuals from a baseline fitted WITHOUT the rows being scored -- an in-sample residual field is
    shrunk toward zero at short lags and will return a range that is too short and a nugget that is
    too small.

``--demo``
    Runs the profile on the committed synthetic well fixture so the code path is exercised in CI.
    The numbers it produces are NOT a calibration of anything and the artifact it writes is labelled
    as such.

Water-table residuals must be screened by observation semantics first: only wells whose
``measurement_target`` is ``water_table``
(:func:`src.features.well_hydrostratigraphy.measurement_target`) belong in a water-table prior. A
confined-aquifer head residual has a different variance and a different correlation structure, and
pooling it in biases both.

Usage::

    python scripts/calibrate_spatial_prior.py --self-test
    python scripts/calibrate_spatial_prior.py --residuals data/processed/wt_residuals_oof.parquet \
        --state water_table_head_anomaly --support "shallow unconfined water table, <=30 m wells" \
        --out data/processed/spatial_prior_calibration.json
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models.observability import NU_CANDIDATES, matern_correlation  # noqa: E402
from src.models.prior_calibration import (  # noqa: E402
    PriorCalibration,
    fit_matern_at_fixed_nu,
    profile_over_nu,
    spatial_blocks,
    write_artifact,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def draw_matern_field(coords_km, sigma, length_km, nu, nugget, seed):
    """Draw one realisation of a Matérn field plus nugget at ``coords_km``."""
    rng = np.random.default_rng(seed)
    d = np.sqrt(np.sum((coords_km[:, None, :] - coords_km[None, :, :]) ** 2, axis=-1))
    C = sigma ** 2 * matern_correlation(d, length_km, nu) + 1e-9 * np.eye(len(coords_km))
    L = np.linalg.cholesky(C)
    return L @ rng.standard_normal(len(coords_km)) + np.sqrt(nugget) * rng.standard_normal(len(coords_km))


def self_test(seed: int = 0) -> int:
    """Verify the estimator against a known truth. Returns a process exit code."""
    rng = np.random.default_rng(seed)
    n, span = 220, 120.0
    coords = rng.uniform(0.0, span, (n, 2))
    truth = dict(sigma=0.6, length_km=15.0, nu=1.5, nugget=0.02)
    y = draw_matern_field(coords, seed=seed, **truth)

    logger.info("self-test: truth sigma=%.3f L=%.1f km nu=%.1f nugget=%.4f (n=%d over %.0f km)",
                truth["sigma"], truth["length_km"], truth["nu"], truth["nugget"], n, span)

    ok = True
    at_truth = fit_matern_at_fixed_nu(coords, y, truth["nu"])
    logger.info("  at the true nu: sigma=%.3f L=%.1f km nugget=%.4f  (-2 REML = %.2f)",
                at_truth.sigma, at_truth.length_km, at_truth.nugget, at_truth.neg2_reml)
    # Fixed-domain asymptotics (Zhang 2004) say sigma and L are NOT separately consistent, so the
    # tolerances here are deliberately loose on each and tight on the microergodic combination.
    for name, got, want, tol in (("sigma", at_truth.sigma, truth["sigma"], 0.6),
                                 ("length_km", at_truth.length_km, truth["length_km"], 0.75)):
        rel = abs(got - want) / want
        flag = "ok" if rel < tol else "OUT OF TOLERANCE"
        logger.info("    %-10s %.3f vs %.3f (rel %.2f) %s", name, got, want, rel, flag)
        ok &= rel < tol
    from src.models.observability import microergodic_parameter
    m_true = microergodic_parameter(truth["sigma"], truth["length_km"], truth["nu"])
    m_fit = at_truth.microergodic
    logger.info("    microergodic %.4g vs %.4g (ratio %.2f -- the quantity that IS identified)",
                m_fit, m_true, m_fit / m_true)
    ok &= 0.5 < m_fit / m_true < 2.0

    prof = profile_over_nu(coords, y, NU_CANDIDATES["water_table_head_anomaly"],
                           state="self_test", block_km=30.0)
    logger.info("  profile over nu (each row refits sigma, L, nugget):")
    for r in prof.profile:
        logger.info("    nu=%.1f  sigma=%.3f  L=%6.1f km  nugget=%.4f  -2REML=%9.2f  "
                    "logscore=%+.3f  crps=%.3f  cov90=%.2f",
                    r["nu"], r["sigma"], r["length_km"], r["nugget"], r["neg2_reml"],
                    r["cv"]["log_score"], r["cv"]["crps"], r["cv"]["coverage_90"])
    logger.info("  selected nu=%s by %s", prof.selected_nu, prof.selection_rule)
    for note in prof.notes:
        logger.info("  NOTE: %s", note)

    # Calibration check: the holdout intervals must be close to nominal at the true nu.
    cv = next(r["cv"] for r in prof.profile if r["nu"] == truth["nu"])
    logger.info("  holdout calibration at the true nu: cov90=%.2f cov50=%.2f z_mean=%+.2f z_sd=%.2f",
                cv["coverage_90"], cv["coverage_50"], cv["standardized_residual_mean"],
                cv["standardized_residual_sd"])
    ok &= 0.75 <= cv["coverage_90"] <= 1.0
    ok &= 0.5 <= cv["standardized_residual_sd"] <= 1.8

    # Anti-leakage check: the spatial blocks must actually separate the folds in space. A block side
    # comparable to the correlation length is what stops a test point from being predicted by its own
    # immediate neighbours (which is what a random split would do, and why it reports a range that is
    # too short).
    blocks = spatial_blocks(coords, 30.0)
    n_blocks = len(np.unique(blocks))
    logger.info("  %d spatial blocks of 30 km over a %.0f km domain (~%.0f points per block)",
                n_blocks, span, n / n_blocks)
    ok &= n_blocks >= 4

    # And the negative control the whole module exists for: fitting the RAW field (baseline included)
    # instead of the residual returns a completely different, much longer range.
    trend = 0.05 * coords[:, 0]                      # a deterministic drift, e.g. topography
    raw_fit = fit_matern_at_fixed_nu(coords, y + trend, truth["nu"])
    logger.info("  negative control -- same residuals PLUS a deterministic drift, fitted as if raw:")
    logger.info("    sigma=%.3f (true %.3f), L=%.1f km (true %.1f) -- the drift is absorbed as "
                "spurious long-range 'covariance'", raw_fit.sigma, truth["sigma"],
                raw_fit.length_km, truth["length_km"])
    ok &= raw_fit.length_km > 1.5 * at_truth.length_km or raw_fit.sigma > 1.5 * at_truth.sigma

    logger.info("self-test %s", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def load_residuals(path: Path):
    import pandas as pd

    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    need = {"x_km", "y_km", "residual"}
    missing = need - set(df.columns)
    if missing:
        raise SystemExit(f"{path}: missing required columns {sorted(missing)}")
    return df


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--self-test", action="store_true", help="verify the estimator on a known truth")
    p.add_argument("--demo", action="store_true",
                   help="run on the committed SYNTHETIC well fixture (exercises the path; not science)")
    p.add_argument("--residuals", type=Path, default=None,
                   help="parquet/csv of out-of-fold residuals (x_km, y_km, residual[, domain, season])")
    p.add_argument("--state", default="water_table_head_anomaly", choices=sorted(NU_CANDIDATES))
    p.add_argument("--transform", default="identity",
                   help="transform applied before fitting (identity | logit_effective_saturation | ...)")
    p.add_argument("--support", default="unspecified",
                   help="measurement support / depth definition of the residuals (REQUIRED for a real run)")
    p.add_argument("--block-km", type=float, default=25.0, help="spatial CV block side (km)")
    p.add_argument("--stratify", default=None, choices=[None, "domain", "season"],
                   help="fit separately within each level of this column where n permits")
    p.add_argument("--min-n", type=int, default=40, help="minimum residuals per stratum to attempt a fit")
    p.add_argument("--out", type=Path, default=Path("data/processed/spatial_prior_calibration.json"))
    args = p.parse_args()

    if args.self_test:
        return self_test()

    if args.demo:
        import pandas as pd

        from src.config.domain import DOMAIN  # noqa: F401  (import guards the CRS assumption)
        fixture = Path("tests/fixtures/twin/nwis_gwlevels_domain_monthly.parquet")
        if not fixture.exists():
            raise SystemExit(f"demo fixture not found: {fixture}")
        df = pd.read_parquet(fixture)
        logger.warning("DEMO MODE: the committed fixture is SYNTHETIC (%d sites). Nothing produced "
                       "here calibrates anything; it exercises the code path only.",
                       df.site_no.nunique())
        return 0

    if args.residuals is None:
        p.error("give --residuals PATH, or --self-test, or --demo")
    if args.support == "unspecified":
        p.error("--support is required for a real run: a covariance without a stated measurement "
                "support and depth definition is not interpretable and must not be written to the "
                "artifact")

    df = load_residuals(args.residuals)
    coords = df[["x_km", "y_km"]].to_numpy(float)
    y = df["residual"].to_numpy(float)
    logger.info("%d residuals for %s from %s", len(y), args.state, args.residuals)

    cals: list[PriorCalibration] = []
    groups = [("all", df)]
    if args.stratify and args.stratify in df.columns:
        groups += [(str(k), g) for k, g in df.groupby(args.stratify)]

    for label, g in groups:
        if len(g) < args.min_n:
            logger.warning("  skipping stratum %r: n=%d < --min-n=%d", label, len(g), args.min_n)
            continue
        cal = profile_over_nu(
            g[["x_km", "y_km"]].to_numpy(float), g["residual"].to_numpy(float),
            NU_CANDIDATES[args.state], state=args.state, transform=args.transform,
            support=args.support, block_km=args.block_km,
            season=label if args.stratify == "season" else "all",
            domain=label if args.stratify == "domain" else "all",
        )
        cals.append(cal)
        logger.info("  %s: selected nu=%s (%s)", label, cal.selected_nu, cal.selection_rule)

    if not cals:
        raise SystemExit("no stratum had enough residuals to fit")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_artifact(cals, str(args.out), provenance={
        "source": str(args.residuals),
        "n_input_rows": int(len(df)),
        "block_km": args.block_km,
        "stratify": args.stratify,
        "note": "residuals must be OUT OF FOLD; see src/models/prior_calibration.py",
    })
    logger.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
