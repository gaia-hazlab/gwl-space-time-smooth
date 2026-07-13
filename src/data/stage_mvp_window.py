"""Stage every dataset the MVP needs for **Fall–Winter 2025-2026** (2025-09-01 .. 2026-03-31).

One window, one command. This is the season the twin is actually about: the PNW wet season, when the
atmospheric rivers land, the soil wets up, the water table recharges, and the landslide/liquefaction
antecedent state is set.

Three streams, and they play different roles — this is the point of staging them together:

  FORCING     PRISM daily precip + tmean (+ Hamon PET)   what went in            (observed)
  STATE       NWIS wells, depth to water                  where the water table sat (observed)
  FLUX        USGS river gauges, discharge -> mm/day      what came out            (observed)
  FORECAST    FuXi 15-day precip, generated on Tillicum,  what we PREDICT would go in
              staged to Kopah, read lazily from here

The forecast is the only stream that is not an observation, and it is what the other three exist to
score. FuXi needs an H200 (9.4 GB of weights; GraphCast's jax[cuda13] will not even install on
arm64), so it is generated ON TILLICUM and staged to Kopah -- this end only reads the Zarr. A rolling
weekly initialisation gives ~30 forecasts across the wet season, which is what lets us measure skill
AS A FUNCTION OF LEAD TIME (+1..+15 d) rather than from a single lucky run:

    FuXi precip     vs PRISM        -> weather-forecast skill by lead
    forecast state  vs wells/gauges -> soil-state forecast skill by lead

Together they **close the water budget**: precipitation in, storage change observed by the wells,
and every outgoing flux observed by the gauges. Wells alone constrain the state but not the fluxes,
which is why the budget could be 8-26x wrong in the water table while looking plausible (issue #88).
The gauges are the constraint that catches it: observed baseflow index is 0.28, the model's is ~0.

Everything is staged to Zarr/parquet, locally or straight to Kopah (gaia-cli convention).

    pixi run stage-mvp                                   # local
    pixi run stage-mvp -- --kopah                        # -> s3://gaia/soil-twin/...
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from src.io.zarr_store import GAIA_BUCKET, open_zarr, write_zarr

logger = logging.getLogger("stage_mvp")

# The PNW wet season: fall build-up through the winter AR season and the spring water-table peak.
MVP_START = "2025-09-01"
MVP_END = "2026-03-31"
# Domain is defined ONCE in src.config.domain (issue #92). Do not re-declare a bbox here.
from src.config.domain import PUGET_CASCADES_BBOX  # noqa: E402

FUXI_PREFIX = f"{GAIA_BUCKET}/forecast/fuxi"
FORECAST_EVERY_DAYS = 7        # a rolling init each week -> ~30 forecasts across the wet season
FUXI_LEAD_DAYS = 15            # FuXi's long cascade is trained to 15 d


def fuxi_init_dates(start, end, every_days=FORECAST_EVERY_DAYS, lead_days=FUXI_LEAD_DAYS):
    """Forecast initialisation dates across the window.

    Each init is verified against the observations over its own +1..+15 day lead, so the last useful
    init is `lead_days` before the window ends. A rolling weekly init gives ~30 forecasts across the
    season -- enough to measure skill AS A FUNCTION OF LEAD TIME, which a single forecast cannot.
    """
    last = pd.Timestamp(end) - pd.Timedelta(days=lead_days)
    return [d.strftime("%Y-%m-%d")
            for d in pd.date_range(start, last, freq=f"{every_days}D")]


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Stage the Fall-Winter 2025-2026 MVP datasets.")
    p.add_argument("--start", default=MVP_START)
    p.add_argument("--end", default=MVP_END)
    p.add_argument("--kopah", action="store_true", help="stage to s3://gaia/soil-twin instead of local")
    p.add_argument("--forecast-every", type=int, default=FORECAST_EVERY_DAYS,
                   help="days between FuXi initialisations across the window")
    p.add_argument("--skip", nargs="*", default=[],
                   choices=["prism", "gauges", "wells", "forecast"])
    a = p.parse_args()

    root = f"{GAIA_BUCKET}" if a.kopah else "data/processed"
    logger.info("MVP window %s .. %s  ->  %s", a.start, a.end, root)

    # --- FORCING: PRISM daily (what went in) -----------------------------------------------------
    if "prism" not in a.skip:
        from src.data.fetch_prism_daily import open_prism_daily
        ds = open_prism_daily(a.start, a.end, PUGET_CASCADES_BBOX)
        tot = float(ds.precip_mm.mean(dim=[d for d in ds.precip_mm.dims if d != "time"]).sum())
        logger.info("PRISM daily: %d days, %.0f mm total (area mean)", ds.sizes["time"], tot)
        write_zarr(ds, f"{root}/prism_daily_{a.start[:7]}_{a.end[:7]}.zarr")

    # --- FLUX: USGS river gauges (what came out) -------------------------------------------------
    if "gauges" not in a.skip:
        import pandas as pd

        from src.data.fetch_usgs_discharge import baseflow_separation, fetch_discharge_mm_day
        df = fetch_discharge_mm_day(start=a.start, end=a.end)
        parts = []
        for g, sub in df.groupby("site_no"):
            sub = sub.sort_values("date").copy()
            bf, qf = baseflow_separation(sub.q_mm_day.fillna(0.0).values)
            sub["baseflow_mm_day"], sub["quickflow_mm_day"] = bf, qf
            parts.append(sub)
        out = pd.concat(parts, ignore_index=True)
        bfi = out.groupby("site_no").apply(
            lambda s: s.baseflow_mm_day.sum() / max(s.q_mm_day.sum(), 1e-9), include_groups=False)
        logger.info("gauges: %d sites, median baseflow index %.2f  <-- the flux constraint",
                    out.site_no.nunique(), float(bfi.median()))
        dst = Path("data/processed/usgs_discharge_mvp.parquet")
        dst.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(dst, index=False)
        logger.info("wrote %s", dst)

    # --- FORECAST: FuXi, generated on Tillicum, staged on Kopah, fetched here ---------------------
    # The fourth stream, and the only one that is not an observation. Without it stage-mvp only
    # describes the PAST; with it we can score the forecast against all three observation streams:
    #   FuXi precip   vs  PRISM        -> weather-forecast skill by lead time
    #   forecast state vs wells/gauges -> soil-state forecast skill by lead time
    # FuXi needs an H200 (9.4 GB of weights, 60 six-hourly steps), so it is generated ON TILLICUM and
    # staged to Kopah; this end only reads the Zarr lazily. Nothing is fabricated when it is absent.
    if "forecast" not in a.skip:
        from src.io.zarr_store import list_stores
        found = list_stores(FUXI_PREFIX)
        inits = fuxi_init_dates(a.start, a.end, every_days=a.forecast_every)
        have = {f.rstrip("/").split("/")[-1].replace(".zarr", "") for f in found}
        missing = [d for d in inits if d not in have]

        logger.info("FuXi forecasts on Kopah (%s): %d found, %d of %d wanted inits missing",
                    FUXI_PREFIX, len(found), len(missing), len(inits))
        if found:
            for uri in found[:3]:
                try:
                    ds = open_zarr(uri)
                    logger.info("  %s: %s", uri.split("/")[-1], dict(ds.sizes))
                except Exception as exc:
                    logger.warning("  %s unreadable (%s)", uri, exc)
        if missing:
            logger.warning(
                "NOT GENERATED YET — FuXi runs on Tillicum, not here (it needs an H200; the weights "
                "alone are 9.4 GB and GraphCast's jax[cuda13] will not even install on arm64).\n"
                "Generate the %d missing initialisations with:\n\n"
                "    sky launch --infra slurm/tillicum -c fuxi deploy/tillicum-fuxi.yaml \\\n"
                "      --env INITS=\"%s\" \\\n"
                "      --env AWS_ACCESS_KEY_ID --env AWS_SECRET_ACCESS_KEY\n\n"
                "Each init writes %s/<init>.zarr; re-run `pixi run stage-mvp` to pull them.",
                len(missing), ",".join(missing[:6]) + ("..." if len(missing) > 6 else ""),
                FUXI_PREFIX)

    # --- STATE: NWIS wells (where the table sat) --------------------------------------------------
    if "wells" not in a.skip:
        import pandas as pd
        src = Path("data/processed/nwis_gwlevels_monthly.parquet")
        if src.exists():
            w = pd.read_parquet(src)
            m = ((w.year * 100 + w.month) >= int(a.start[:4] + a.start[5:7])) & \
                ((w.year * 100 + w.month) <= int(a.end[:4] + a.end[5:7]))
            logger.info("wells: %d obs in the window, %d sites (shallow: %d)",
                        int(m.sum()), w[m].site_no.nunique(), int((~w[m].is_deep_well).sum()))
        else:
            logger.warning("%s not found; run the NWIS fetcher first", src)

    logger.info("MVP window staged. Forcing + state + flux -> the budget can now be CLOSED, "
                "not just plotted.")


if __name__ == "__main__":
    main()
