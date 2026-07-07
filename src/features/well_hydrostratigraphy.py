"""Classify NWIS wells by the hydrostratigraphic unit they tap (issue #46).

HAND predicts only the shallowest **unconfined, terrain-following** water table. In the Puget Sound
glacial system that table lives in the top ~15-30 m (Vashon till + recessional outwash); below it,
advance outwash (Qva) is **confined** and its well level is a potentiometric head set by the
recharge-area elevation and confining geometry, decoupled from height-above-drainage (and sometimes
artesian). Pooling both populations into one DTW target fits a physically meaningless average, so
the water-table product must be screened to the shallow, unconfined/perched population.

Confined vs unconfined here is a **vertical** distinction (a depth layer), not a surface map unit, so
it is screened at the *well* level by depth (the most complete attribute; screened-interval is rarely
reported and NWIS aquifer codes are sparse). This module provides that classification and the screen.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Approximate Puget-Lowland thresholds (m below surface). Configurable; calibrate per basin.
SHALLOW_MAX_M = 30.0     # <= this: within the Vashon-till + recessional-outwash water table
DEEP_MIN_M = 60.0        # >= this: clearly into confined advance outwash / deeper units


def classify_well_hydro(sites, shallow_max_m=SHALLOW_MAX_M, deep_min_m=DEEP_MIN_M):
    """Return a Series of ``hydro_class`` per well: shallow_watertable | deep_confined | ambiguous.

    Uses well depth as the primary discriminator, plus the existing ``is_deep_well`` flag (NWIS
    depth > 500 ft) which always maps to ``deep_confined``. Wells with unknown depth are
    ``ambiguous`` (kept, but not asserted to be water-table).
    """
    df = sites
    depth = pd.to_numeric(df.get("well_depth_m"), errors="coerce")
    is_deep = df.get("is_deep_well", pd.Series(False, index=df.index)).fillna(False).astype(bool)

    cls = pd.Series("ambiguous", index=df.index, dtype=object)
    cls[depth <= shallow_max_m] = "shallow_watertable"
    cls[(depth >= deep_min_m) | is_deep] = "deep_confined"
    cls[depth.isna() & ~is_deep] = "ambiguous"
    return cls


def watertable_wells(sites, max_depth_m=SHALLOW_MAX_M, keep_unknown_depth=True):
    """Subset the wells likely tapping the unconfined/perched water table (HAND-predictable).

    Drops wells deeper than ``max_depth_m`` and any flagged ``is_deep_well``. Unknown-depth wells are
    kept when ``keep_unknown_depth`` (they cannot be excluded, only flagged). Use this to build the
    Stage-1 DTW target so the HAND regression fits a coherent shallow-water-table population.
    """
    df = sites
    depth = pd.to_numeric(df.get("well_depth_m"), errors="coerce")
    is_deep = df.get("is_deep_well", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    shallow = depth <= max_depth_m
    if keep_unknown_depth:
        shallow = shallow | depth.isna()
    return df[shallow & ~is_deep].copy()


def screening_summary(sites, shallow_max_m=SHALLOW_MAX_M, deep_min_m=DEEP_MIN_M):
    """Counts + median DTW per hydro_class -- a quick check that the screen is doing something."""
    cls = classify_well_hydro(sites, shallow_max_m, deep_min_m)
    out = {}
    dtw = pd.to_numeric(sites.get("median_dtw_m"), errors="coerce")
    for k in ("shallow_watertable", "ambiguous", "deep_confined"):
        m = cls == k
        out[k] = dict(n=int(m.sum()),
                      median_depth_m=float(np.nanmedian(pd.to_numeric(sites.get("well_depth_m"),
                                                                      errors="coerce")[m])) if m.any() else float("nan"),
                      median_dtw_m=float(np.nanmedian(dtw[m])) if m.any() else float("nan"))
    return out
