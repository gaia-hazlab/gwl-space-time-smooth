"""USGS river-gauge discharge — the integrated observation of the catchment water budget.

Wells constrain the **state** (where the water table sits). Gauges constrain the **fluxes**, and it is
the fluxes that are unconstrained and wrong: the budget currently turns ~94% of rain into recharge
(issue #88), and nothing in the well data can see that directly.

Streamflow *is* the catchment water budget, integrated over the basin:

    Q  =  surface runoff  +  interflow  +  baseflow (groundwater discharge)

so it observes exactly the partition we have been guessing at with ``k_aniso`` and
``recharge_ref_mm_day``. Better still, a **baseflow separation** splits the hydrograph into

  - **quickflow** -> surface runoff + interflow  (the fast limb),
  - **baseflow**  -> groundwater discharge to the stream  (the slow limb, "the rivers take the
    water"), which directly constrains the stream-discharge sink and the long-term mean recharge.

Together with the wells this **closes the budget**: precipitation in, and every outgoing flux
observed. This is the natural observation operator for assimilating the water budget.

Gauges follow ``gaia-hazlab/seis-hydro-2-sed`` (NWIS parameter 00060 discharge); this module uses the
**daily-values** service since the budget runs daily.

    python -m src.data.fetch_usgs_discharge --start 2025-12-01 --end 2025-12-31
"""

from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger("fetch_usgs_discharge")

CFS_TO_M3S = 0.0283168466

# Gauges used for per-basin closure. The criterion is a single one: the gauge's DRAINAGE BASIN must lie
# inside the analysis domain, so that the budget can actually be modelled over the area the gauge
# integrates. Basin coverage is measured from NLDI polygons against the terrain grid -- running the
# budget on one area and comparing it to discharge generated in another is not a closure, however
# carefully the millimetres are computed.
#
# All eight lie inside the western-Cascades domain. (Under the earlier Puget-lowland footprint only
# Newaukum Ck did, which is what forced the domain extension: interflow is most active on steep ground,
# and a lowland creek cannot constrain it.)
PUGET_GAGES = {
    "12082500": "Nisqually R nr National",         # 361 km2, Mt Rainier headwaters
    "12092000": "Puyallup R nr Electron",          # 238 km2
    "12097500": "Green R nr Lester",               # 190 km2
    "12115000": "Cedar R nr Cedar Falls",          # 110 km2
    "12134500": "Skykomish R nr Gold Bar",         # 1386 km2
    "12144500": "Snoqualmie R nr Carnation",       # 977 km2
    "12108500": "Newaukum Cr nr Black Diamond",    # 79 km2, lowland
    "12102078": "Clarks Cr at Stewart Ave",        # 70 km2, lowland
}


def fetch_discharge_mm_day(gages=None, start="2025-12-01", end="2025-12-31"):
    """Daily discharge for each gauge, converted to **mm/day over its own drainage basin**.

    Converting to mm/day is what makes the gauge directly comparable to the water budget's fluxes:
    both are then a depth of water per unit catchment area.
    """
    import dataretrieval.nwis as nwis

    gages = list(gages or PUGET_GAGES)
    info, _ = nwis.get_info(sites=gages)
    area = {str(r.site_no): float(r.drain_area_va) for _, r in info.iterrows()
            if pd.notna(getattr(r, "drain_area_va", None))}          # square miles

    rows = []
    for g in gages:
        if g not in area:
            logger.warning("%s: no drainage area reported; skipping", g)
            continue
        df, _ = nwis.get_dv(sites=g, start=start, end=end, parameterCd="00060")
        if df.empty:
            logger.warning("%s: no daily discharge in %s..%s", g, start, end)
            continue
        col = next((c for c in df.columns if c.startswith("00060")), None)
        q_cfs = pd.to_numeric(df[col], errors="coerce")
        a_m2 = area[g] * 2.589988e6                                   # sq mi -> m^2
        # cfs -> m3/s -> m3/day -> m over the basin -> mm
        q_mm_day = q_cfs * CFS_TO_M3S * 86400.0 / a_m2 * 1000.0
        rows.append(pd.DataFrame({"site_no": g, "name": PUGET_GAGES.get(g, g),
                                  "date": pd.to_datetime(df.index).tz_localize(None).normalize(),
                                  "q_mm_day": q_mm_day.values,
                                  "area_km2": area[g] * 2.58999}))
        logger.info("%s %-28s area %6.0f km2, mean %.2f mm/day",
                    g, PUGET_GAGES.get(g, g), area[g] * 2.58999, np.nanmean(q_mm_day.values))
    if not rows:
        raise ValueError("no gauge data retrieved")
    return pd.concat(rows, ignore_index=True)


def baseflow_separation(q, alpha=0.925, passes=3):
    """Lyne-Hollick recursive digital filter: split a hydrograph into quickflow and baseflow.

    Returns ``(baseflow, quickflow)``. ``alpha`` is the standard filter parameter (0.9-0.95); three
    passes (forward/backward/forward) is the Nathan-McMahon convention.

    Why this matters here: **baseflow is the groundwater discharge to the stream** -- the "rivers take
    the water" sink -- so it directly constrains that flux and, over a long record, the mean recharge.
    **Quickflow is surface runoff + interflow**, which constrains the ``k_aniso`` partition. These are
    precisely the two numbers the water budget currently has no observational handle on.
    """
    q = np.asarray(q, dtype="float64")
    b = q.copy()
    for p in range(passes):
        seq = range(1, len(q)) if p % 2 == 0 else range(len(q) - 2, -1, -1)
        prev = 0 if p % 2 == 0 else len(q) - 1
        f = np.zeros_like(q)
        f[prev] = 0.0
        cur = b.copy()
        for i in seq:
            j = i - 1 if p % 2 == 0 else i + 1
            f[i] = alpha * f[j] + (1 + alpha) / 2.0 * (cur[i] - cur[j])
            b[i] = cur[i] - max(f[i], 0.0)
        b = np.clip(b, 0.0, q)
    return b, q - b


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="USGS gauge discharge as mm/day over the basin.")
    p.add_argument("--start", default="2025-12-01")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--out", default="data/processed/usgs_discharge_daily.parquet")
    a = p.parse_args()

    df = fetch_discharge_mm_day(start=a.start, end=a.end)
    parts = []
    for g, sub in df.groupby("site_no"):
        sub = sub.sort_values("date").copy()
        bf, qf = baseflow_separation(sub.q_mm_day.fillna(0.0).values)
        sub["baseflow_mm_day"], sub["quickflow_mm_day"] = bf, qf
        parts.append(sub)
    out = pd.concat(parts, ignore_index=True)
    out.to_parquet(a.out, index=False)
    logger.info("wrote %s (%d rows, %d gauges)", a.out, len(out), out.site_no.nunique())


if __name__ == "__main__":
    main()
