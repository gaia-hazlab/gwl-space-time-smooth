"""Stage every dataset the MVP needs for **Fall–Winter 2025-2026** (2025-09-01 .. 2026-03-31).

One window, one command. This is the season the twin is actually about: the PNW wet season, when the
atmospheric rivers land, the soil wets up, the water table recharges, and the landslide/liquefaction
antecedent state is set.

Three streams, and they play different roles — this is the point of staging them together:

  FORCING     PRISM daily precip + tmean (+ Hamon PET)   what went in
  STATE       NWIS wells, depth to water                  where the water table sat
  FLUX        USGS river gauges, discharge -> mm/day      what came out (and, via baseflow
                                                          separation, how much came out as
                                                          groundwater vs quickflow)

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

from src.io.zarr_store import GAIA_BUCKET, write_zarr

logger = logging.getLogger("stage_mvp")

# The PNW wet season: fall build-up through the winter AR season and the spring water-table peak.
MVP_START = "2025-09-01"
MVP_END = "2026-03-31"
PUGET_CASCADES_BBOX = (-123.3, 46.8, -120.8, 48.5)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Stage the Fall-Winter 2025-2026 MVP datasets.")
    p.add_argument("--start", default=MVP_START)
    p.add_argument("--end", default=MVP_END)
    p.add_argument("--kopah", action="store_true", help="stage to s3://gaia/soil-twin instead of local")
    p.add_argument("--skip", nargs="*", default=[], choices=["prism", "gauges", "wells"])
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
