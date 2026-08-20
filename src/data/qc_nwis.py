"""
QC and process raw NWIS groundwater data into analysis-ready monthly parquet.

Applies the full QC chain from the water-table-model skill:
  1. Filter bad status codes (pumping, dry, obstructed, etc.)
  2. Remove sites with < N measurements
  3. Flag deep wells likely penetrating confined aquifers
  4. Convert feet → meters
  5. Compute WTE from DTW + land surface altitude
  6. Check datum consistency (drop NGVD29 or flag for VERTCON)
  7. Classify each SITE's observation semantics -- water_table / aquifer_head / unknown -- from its
     screened interval, aquifer type code, flowing status and depth (issue #189). Only
     ``water_table`` sites may enter the assimilation through the shallow water-table point operator;
     ``unknown`` is flagged, never silently promoted.
  8. Aggregate to monthly medians per site — NO gap filling; sparse months stay NaN
  9. Compute per-site temporal coverage statistics; flag sparse / gappy time series

Usage:
    python -m src.data.qc_nwis --input-dir data/raw/nwis --output data/processed/nwis_gwlevels_monthly.parquet

Output:
    data/processed/nwis_gwlevels_monthly.parquet
    data/processed/nwis_sites_clean.parquet
    data/processed/qc_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Feet to meters
FT_TO_M = 0.3048

# Status codes to DROP — keep only blank/NaN and "S" (static level)
BAD_STATUS_CODES = {
    "D",  # Dry
    "E",  # Recently flowing nearby
    "F",  # Flowing
    "G",  # Nearby recently flowing
    "I",  # Injecting
    "N",  # Measurement discontinued
    "O",  # Obstructed
    "P",  # Pumping
    "R",  # Recently pumped
    "T",  # Nearby recently pumped
    "V",  # Foreign substance
    "Z",  # Other
}

# Status codes that mark THIS well as flowing. Their readings are dropped with the rest of
# BAD_STATUS_CODES, but the site-level fact is retained (see qc_filter step 1 / 7b): a head at or
# above land surface means the reading is not a usable depth to a phreatic water table.
# Deliberately ONLY "F": the NWIS codes "E" (recently flowing nearby) and "G" (nearby recently
# flowing) describe a NEIGHBOURING well and are not evidence about this one -- including them would
# disqualify perfectly good water-table wells for their neighbours' behaviour.
FLOWING_STATUS_CODES = {"F"}

# Wells deeper than this (feet) are flagged as likely confined
DEEP_WELL_THRESHOLD_FT = 500

# Minimum number of measurements per site to keep
MIN_OBS_PER_SITE = 10

# Temporal coverage thresholds for sparsity flagging
# Sites with fewer than this fraction of possible months observed → is_sparse_timeseries
MIN_COVERAGE_FRACTION = 0.10
# Sites with a gap longer than this (months) → has_long_gap
MAX_GAP_MONTHS_FLAG = 36


def load_raw_data(
    input_dir: Path,
    states: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load and concatenate all state-level raw parquet files.

    Parameters
    ----------
    input_dir:
        Directory that holds ``<STATE>_gwlevels.parquet`` / ``<STATE>_sites.parquet``.
    states:
        Optional list of 2-letter state abbreviations (e.g. ``['WA', 'OR']``).
        If provided, only files for those states are loaded.
    """
    gw_files = sorted(input_dir.glob("*_gwlevels.parquet"))
    site_files = sorted(input_dir.glob("*_sites.parquet"))

    if states is not None:
        states_upper = {s.upper() for s in states}
        gw_files = [f for f in gw_files if f.stem.replace("_gwlevels", "").upper() in states_upper]
        site_files = [f for f in site_files if f.stem.replace("_sites", "").upper() in states_upper]

    if not gw_files:
        raise FileNotFoundError(
            f"No *_gwlevels.parquet files found in {input_dir}"
            + (f" for states {states}" if states else "")
        )

    logger.info(f"Loading GW levels from {len(gw_files)} state file(s)...")
    dfs_gw = []
    for f in gw_files:
        state_abbr = f.stem.replace("_gwlevels", "").upper()
        df = pd.read_parquet(f)
        df["state"] = state_abbr
        dfs_gw.append(df)
    df_gw = pd.concat(dfs_gw, ignore_index=True)
    logger.info(f"  → {len(df_gw):,} total raw GW level records")

    logger.info(f"Loading site metadata from {len(site_files)} state file(s)...")
    dfs_sites = []
    for f in site_files:
        state_abbr = f.stem.replace("_sites", "").upper()
        df = pd.read_parquet(f)
        df["state"] = state_abbr
        dfs_sites.append(df)
    df_sites = pd.concat(dfs_sites, ignore_index=True)
    # Deduplicate sites (same well can appear in multiple queries)
    df_sites = df_sites.drop_duplicates(subset=["site_no"], keep="first")
    logger.info(f"  → {len(df_sites):,} unique GW sites")

    return df_gw, df_sites


def qc_filter(
    df_gw: pd.DataFrame,
    df_sites: pd.DataFrame,
    min_obs: int = MIN_OBS_PER_SITE,
) -> tuple[pd.DataFrame, dict]:
    """
    Apply the full QC chain. Returns cleaned DataFrame and a QC report dict.
    """
    report: dict = {"raw_records": len(df_gw), "raw_sites": df_sites["site_no"].nunique()}

    # ---- Step 1: Filter bad status codes ----
    # Record the flowing/artesian SITES before the filter removes their readings: the reading is
    # unusable but the fact that this site's head stands above land surface is exactly the evidence
    # that it is not a phreatic water-table well (issue #189).
    if "lev_status_cd" in df_gw.columns:
        flowing_sites = set(df_gw.loc[df_gw["lev_status_cd"].isin(FLOWING_STATUS_CODES), "site_no"]
                            .astype(str).str.strip())
    else:
        flowing_sites = set()
    if "lev_status_cd" in df_gw.columns:
        bad_mask = df_gw["lev_status_cd"].isin(BAD_STATUS_CODES)
        n_bad_status = bad_mask.sum()
        df_gw = df_gw[~bad_mask].copy()
        logger.info(f"  Dropped {n_bad_status:,} records with bad status codes")
    else:
        n_bad_status = 0
        logger.warning("  Column 'lev_status_cd' not found — skipping status filter")
    report["dropped_bad_status"] = int(n_bad_status)

    # ---- Step 2: Parse dates, drop unparseable ----
    if "lev_dt" in df_gw.columns:
        df_gw["date"] = pd.to_datetime(df_gw["lev_dt"], errors="coerce")
    elif "datetime" in df_gw.columns:
        df_gw["date"] = pd.to_datetime(df_gw["datetime"], errors="coerce")
    else:
        raise KeyError("Cannot find date column ('lev_dt' or 'datetime') in GW data")

    n_no_date = df_gw["date"].isna().sum()
    df_gw = df_gw.dropna(subset=["date"]).copy()
    report["dropped_no_date"] = int(n_no_date)

    # ---- Step 3: Parse water level, drop missing ----
    # dataretrieval may return 'lev_va' as string; coerce to float
    lev_col = "lev_va" if "lev_va" in df_gw.columns else None
    if lev_col is None:
        # Try alternative column names
        for candidate in ["value", "result_va", "lev_va_00"]:
            if candidate in df_gw.columns:
                lev_col = candidate
                break
    if lev_col is None:
        raise KeyError("Cannot find water level column in GW data")

    df_gw["dtw_ft"] = pd.to_numeric(df_gw[lev_col], errors="coerce")
    n_no_level = df_gw["dtw_ft"].isna().sum()
    df_gw = df_gw.dropna(subset=["dtw_ft"]).copy()
    report["dropped_no_level"] = int(n_no_level)

    # Drop negative DTW (instrument errors; DTW < 0 would mean water above surface,
    # which is rare and usually an artesian/error condition)
    n_negative = (df_gw["dtw_ft"] < 0).sum()
    # Keep slightly negative values (< -2 ft) as they may be valid artesian conditions;
    # drop extreme negatives
    extreme_neg = df_gw["dtw_ft"] < -50
    df_gw = df_gw[~extreme_neg].copy()
    report["dropped_extreme_negative"] = int(extreme_neg.sum())
    logger.info(f"  Dropped {extreme_neg.sum():,} records with DTW < -50 ft")

    # ---- Step 4: Merge site metadata ----
    # Ensure site_no is string in both
    df_gw["site_no"] = df_gw["site_no"].astype(str).str.strip()
    df_sites["site_no"] = df_sites["site_no"].astype(str).str.strip()

    # Select key columns from site metadata
    site_cols = ["site_no"]
    # Everything needed to decide WHAT a well's water level measures (issue #189). Depth alone is a
    # proxy; the screened interval and the aquifer TYPE code answer the question directly, so they are
    # carried through even though NWIS populates them sparsely -- a sparse direct attribute still
    # beats a dense proxy, and where all of them are missing the well is flagged `unknown` rather
    # than assumed to be a water-table well.
    col_map = {
        "dec_lat_va": "lat",
        "dec_long_va": "lon",
        "alt_va": "alt_ft",
        "alt_datum_cd": "alt_datum",
        "well_depth_va": "well_depth_ft",
        "hole_depth_va": "hole_depth_ft",
        "aqfr_cd": "aquifer_cd",
        "nat_aqfr_cd": "nat_aquifer_cd",
        "aqfr_type_cd": "aqfr_type_cd",       # U unconfined / C confined / M multiple / X mixed / N unknown
        "openings_top_va": "screen_top_ft",   # GWSI open/screened interval, ft below land surface
        "openings_bot_va": "screen_bottom_ft",
    }
    for raw_col, clean_col in col_map.items():
        if raw_col in df_sites.columns:
            site_cols.append(raw_col)

    df_sites_slim = df_sites[site_cols].copy()
    df_sites_slim = df_sites_slim.rename(columns=col_map)

    # Convert numeric columns
    for col in ["lat", "lon", "alt_ft", "well_depth_ft", "hole_depth_ft",
                "screen_top_ft", "screen_bottom_ft"]:
        if col in df_sites_slim.columns:
            df_sites_slim[col] = pd.to_numeric(df_sites_slim[col], errors="coerce")

    # Drop any lat/lon columns already in df_gw (from OGC API download) to avoid
    # column-suffix collisions after the merge; the authoritative coordinates come
    # from the site-metadata table (dec_lat_va / dec_long_va).
    df_gw = df_gw.drop(columns=[c for c in ("lat", "lon") if c in df_gw.columns])

    df = df_gw.merge(df_sites_slim, on="site_no", how="left")
    n_no_site = df["lat"].isna().sum()
    df = df.dropna(subset=["lat", "lon"]).copy()
    report["dropped_no_coordinates"] = int(n_no_site)

    # ---- Step 5: Datum check ----
    if "alt_datum" in df.columns:
        ngvd29_mask = df["alt_datum"].str.upper().str.contains("NGVD", na=False)
        n_ngvd29 = ngvd29_mask.sum()
        # Drop NGVD29 sites (conservative; VERTCON correction is an option)
        df = df[~ngvd29_mask].copy()
        logger.info(f"  Dropped {n_ngvd29:,} records with NGVD29 datum")
    else:
        n_ngvd29 = 0
    report["dropped_ngvd29"] = int(n_ngvd29)

    # ---- Step 6: Flag deep wells ----
    if "well_depth_ft" in df.columns:
        df["is_deep_well"] = df["well_depth_ft"] > DEEP_WELL_THRESHOLD_FT
        n_deep = df["is_deep_well"].sum()
        logger.info(
            f"  Flagged {n_deep:,} records from wells deeper than "
            f"{DEEP_WELL_THRESHOLD_FT} ft (likely confined — kept but flagged)"
        )
    else:
        df["is_deep_well"] = False
        n_deep = 0
    report["flagged_deep_wells"] = int(n_deep)

    # ---- Step 7: Convert units (feet → meters) ----
    df["dtw_m"] = df["dtw_ft"] * FT_TO_M
    if "alt_ft" in df.columns:
        df["alt_m"] = df["alt_ft"] * FT_TO_M
        # Compute water table elevation: WTE = land surface altitude - DTW
        df["wte_m"] = df["alt_m"] - df["dtw_m"]
        n_no_alt = df["alt_m"].isna().sum()
        report["sites_missing_altitude"] = int(
            df.loc[df["alt_m"].isna(), "site_no"].nunique()
        )
    else:
        df["alt_m"] = np.nan
        df["wte_m"] = np.nan
        report["sites_missing_altitude"] = int(df["site_no"].nunique())

    if "well_depth_ft" in df.columns:
        df["well_depth_m"] = df["well_depth_ft"] * FT_TO_M
    else:
        df["well_depth_m"] = np.nan
    for ft_col, m_col in (("screen_top_ft", "screen_top_m"),
                          ("screen_bottom_ft", "screen_bottom_m"),
                          ("hole_depth_ft", "hole_depth_m")):
        df[m_col] = df[ft_col] * FT_TO_M if ft_col in df.columns else np.nan

    # ---- Step 7b: observation semantics (issue #189) ----
    # Attach what each well's water level actually constrains: water_table / aquifer_head / unknown.
    # This is a SITE attribute, derived from screen, aquifer type, flowing status and depth.
    df["is_flowing"] = df["site_no"].isin(flowing_sites)
    report["sites_flowing_or_artesian"] = int(df.loc[df["is_flowing"], "site_no"].nunique())

    from src.features.well_hydrostratigraphy import measurement_target

    df["measurement_target"] = measurement_target(df).values
    tgt_counts = df.drop_duplicates("site_no")["measurement_target"].value_counts().to_dict()
    report["measurement_target_sites"] = {k: int(v) for k, v in tgt_counts.items()}
    logger.info("  Observation semantics (sites): %s", report["measurement_target_sites"])

    # ---- Step 8: Remove sites with < min_obs measurements ----
    obs_counts = df.groupby("site_no").size()
    sparse_sites = obs_counts[obs_counts < min_obs].index
    n_sparse = len(sparse_sites)
    n_records_sparse = df["site_no"].isin(sparse_sites).sum()
    df = df[~df["site_no"].isin(sparse_sites)].copy()
    logger.info(
        f"  Dropped {n_sparse:,} sites with < {min_obs} observations "
        f"({n_records_sparse:,} records)"
    )
    report["dropped_sparse_sites"] = int(n_sparse)
    report["dropped_sparse_records"] = int(n_records_sparse)

    # ---- Summary ----
    report["clean_records"] = len(df)
    report["clean_sites"] = int(df["site_no"].nunique())
    logger.info(
        f"  QC complete: {report['clean_records']:,} records, "
        f"{report['clean_sites']:,} sites"
    )

    return df, report


def aggregate_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate raw observations to monthly medians per site.

    No gap filling — months without observations are absent from the output.
    Downstream code must handle NaN / missing months explicitly; do not impute.
    n_obs records how many raw measurements contributed to each site-month median.
    """
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month

    agg_kwargs: dict = {
        "lat": ("lat", "first"),
        "lon": ("lon", "first"),
        "wte_m": ("wte_m", "median"),
        "dtw_m": ("dtw_m", "median"),
        "n_obs": ("dtw_m", "size"),
        "well_depth_m": ("well_depth_m", "first"),
        "is_deep_well": ("is_deep_well", "first"),
    }
    if "aquifer_cd" in df.columns:
        agg_kwargs["aquifer_cd"] = ("aquifer_cd", "first")
    if "state" in df.columns:
        agg_kwargs["state"] = ("state", "first")
    # Carry the observation-semantics attributes through both aggregations, so a downstream consumer
    # never has to re-derive (or guess) what a well measures (issue #189).
    for col in ("measurement_target", "is_flowing", "aqfr_type_cd", "nat_aquifer_cd",
                "screen_top_m", "screen_bottom_m", "hole_depth_m"):
        if col in df.columns:
            agg_kwargs[col] = (col, "first")

    monthly = (
        df.groupby(["site_no", "year", "month"])
        .agg(**agg_kwargs)
        .reset_index()
    )

    logger.info(
        f"  Monthly aggregation: {len(monthly):,} site-months, "
        f"{monthly['site_no'].nunique():,} sites — no gap filling applied"
    )
    return monthly


def build_clean_sites(df_monthly: pd.DataFrame) -> pd.DataFrame:
    """
    Build a clean site-level summary table with temporal coverage statistics.

    Coverage statistics (computed from non-interpolated monthly records):
        n_observed_months   : months with at least one real measurement
        n_possible_months   : calendar span from first to last observed month
        coverage_fraction   : n_observed / n_possible  (0–1)
        max_gap_months      : longest consecutive gap between observations (months)
        record_span_years   : calendar span in years
        is_sparse_timeseries: True if coverage_fraction < MIN_COVERAGE_FRACTION
        has_long_gap        : True if max_gap_months > MAX_GAP_MONTHS_FLAG

    Only sites without either flag should be used in spatial interpolation.
    """
    agg_kwargs: dict = {
        "lat": ("lat", "first"),
        "lon": ("lon", "first"),
        "mean_wte_m": ("wte_m", "mean"),
        "mean_dtw_m": ("dtw_m", "mean"),
        "median_wte_m": ("wte_m", "median"),
        "median_dtw_m": ("dtw_m", "median"),
        "std_wte_m": ("wte_m", "std"),
        "n_observed_months": ("wte_m", "count"),
        "first_year": ("year", "min"),
        "last_year": ("year", "max"),
        "well_depth_m": ("well_depth_m", "first"),
        "is_deep_well": ("is_deep_well", "first"),
    }
    if "state" in df_monthly.columns:
        agg_kwargs["state"] = ("state", "first")
    if "aquifer_cd" in df_monthly.columns:
        agg_kwargs["aquifer_cd"] = ("aquifer_cd", "first")
    # Carry the observation-semantics attributes through both aggregations, so a downstream consumer
    # never has to re-derive (or guess) what a well measures (issue #189).
    for col in ("measurement_target", "is_flowing", "aqfr_type_cd", "nat_aquifer_cd",
                "screen_top_m", "screen_bottom_m", "hole_depth_m"):
        if col in df_monthly.columns:
            agg_kwargs[col] = (col, "first")

    sites = df_monthly.groupby("site_no").agg(**agg_kwargs).reset_index()

    # Temporal coverage statistics — computed per site over the raw monthly records
    def _coverage(grp: pd.DataFrame) -> pd.Series:
        ym = grp["year"] * 12 + grp["month"]
        ym_sorted = ym.sort_values().values
        n_possible = int(ym_sorted[-1] - ym_sorted[0] + 1)
        n_obs = int((grp["n_obs"] > 0).sum())
        coverage = n_obs / n_possible if n_possible > 0 else 0.0
        gaps = np.diff(ym_sorted) - 1  # consecutive gaps in months
        max_gap = int(gaps.max()) if len(gaps) > 0 else 0
        return pd.Series({
            "n_possible_months": n_possible,
            "coverage_fraction": round(coverage, 4),
            "max_gap_months": max_gap,
            "record_span_years": round(n_possible / 12, 2),
        })

    cov = df_monthly.groupby("site_no").apply(_coverage, include_groups=False).reset_index()
    sites = sites.merge(cov, on="site_no", how="left")

    # Quality flags
    sites["is_sparse_timeseries"] = sites["coverage_fraction"] < MIN_COVERAGE_FRACTION
    sites["has_long_gap"] = sites["max_gap_months"] > MAX_GAP_MONTHS_FLAG

    n_sparse = sites["is_sparse_timeseries"].sum()
    n_gap = sites["has_long_gap"].sum()
    logger.info(
        f"  Site-level flags: {n_sparse:,} sparse (coverage < {MIN_COVERAGE_FRACTION:.0%}), "
        f"{n_gap:,} with gap > {MAX_GAP_MONTHS_FLAG} months"
    )
    return sites


def main():
    parser = argparse.ArgumentParser(description="QC and process NWIS groundwater data")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/raw/nwis"),
        help="Directory with raw state-level parquet files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/nwis_gwlevels_monthly.parquet"),
        help="Output path for monthly parquet",
    )
    parser.add_argument(
        "--states",
        nargs="+",
        metavar="STATE",
        default=None,
        help="Two-letter state abbreviations to include (e.g. WA OR ID). Default: all states.",
    )
    parser.add_argument(
        "--min-obs",
        type=int,
        default=MIN_OBS_PER_SITE,
        help=f"Minimum observations per site (default: {MIN_OBS_PER_SITE})",
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Load
    df_gw, df_sites = load_raw_data(args.input_dir, states=args.states)

    # QC
    df_clean, qc_report = qc_filter(df_gw, df_sites, min_obs=args.min_obs)

    # Aggregate to monthly
    df_monthly = aggregate_monthly(df_clean)

    # Save monthly data
    df_monthly.to_parquet(args.output, index=False)
    logger.info(f"Saved monthly data to {args.output}")

    # Save clean site summary
    sites_path = args.output.parent / "nwis_sites_clean.parquet"
    df_sites_clean = build_clean_sites(df_monthly)
    df_sites_clean.to_parquet(sites_path, index=False)
    logger.info(f"Saved {len(df_sites_clean):,} clean site summaries to {sites_path}")

    # Save QC report
    report_path = args.output.parent / "qc_report.json"
    with open(report_path, "w") as f:
        json.dump(qc_report, f, indent=2)
    logger.info(f"Saved QC report to {report_path}")


if __name__ == "__main__":
    main()
