"""Classify NWIS wells by what their screened interval actually measures (issues #46, #189).

Two distinct questions are answered here, and conflating them is the error this module now guards
against.

1. **Which hydrostratigraphic unit does the well tap?** (``classify_well_hydro``, issue #46.)
   HAND predicts only the shallowest **unconfined, terrain-following** water table. In the Puget
   Sound glacial system that table lives in the top ~15-30 m (Vashon till + recessional outwash);
   below it, advance outwash (Qva) is **confined** and its well level is a potentiometric head set
   by the recharge-area elevation and confining geometry, decoupled from height-above-drainage (and
   sometimes artesian). Pooling both populations into one DTW target fits a physically meaningless
   average.

2. **What state variable does this observation constrain?** (``measurement_target``, issue #189.)
   A water level in a well is a **hydraulic head for the screened interval**,
   :math:`H = z + p/(\\rho_w g)`. Only when that interval straddles the phreatic surface of an
   unconfined aquifer is :math:`H` the water-table head :math:`h_{wt}` -- and only then may the
   observation enter the assimilation through the shallow water-table point operator. A deep or
   confined well is often an *excellent* observation; it simply constrains a different state, and
   silently pinning the shallow water table with it is a category error, not a noise problem.

   The three-valued semantic is deliberate:

   ``water_table``   defensibly samples the shallow unconfined water table -> may use the
                     ``h_wt``/DTW point operator;
   ``aquifer_head``  screened in a confined/semiconfined/deep interval, or flowing/artesian ->
                     needs a depth/aquifer operator or its own hydraulic-head diagnostic;
   ``unknown``       metadata insufficient to defend either -> **flagged, not assigned**. An
                     unknown well is never silently promoted to ``water_table``.

Confined vs unconfined is a **vertical** distinction (a depth layer), not a surface map unit. The
most complete NWIS attribute is well depth, so it remains the fallback discriminator; where the
richer attributes are present (screen top/bottom ``screen_top_m``/``screen_bottom_m``, aquifer type
code ``aqfr_type_cd``, national/local aquifer codes, and a flowing/artesian flag) they take
precedence, because they answer the question directly rather than by proxy.

NWIS ``aqfr_type_cd`` values follow the GWSI domain: ``U`` unconfined, ``C`` confined,
``M`` multiple aquifers, ``N`` unknown/not applicable, ``X`` mixed. Only ``U`` is evidence *for*
``water_table``; ``C``/``M``/``X`` are evidence for ``aquifer_head``; ``N`` and missing are not
evidence either way.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Approximate Puget-Lowland thresholds (m below surface). Configurable; calibrate per basin.
SHALLOW_MAX_M = 30.0     # <= this: within the Vashon-till + recessional-outwash water table
DEEP_MIN_M = 60.0        # >= this: clearly into confined advance outwash / deeper units

#: The three observation semantics. See the module docstring; ``unknown`` is a real, kept state.
MEASUREMENT_TARGETS = ("water_table", "aquifer_head", "unknown")

#: NWIS GWSI ``aqfr_type_cd`` -> evidence about confinement. ``None`` = no evidence either way.
AQUIFER_TYPE_EVIDENCE = {
    "U": "unconfined",
    "C": "confined",
    "M": "confined",     # multiple aquifers: the composite head is not a water table
    "X": "confined",     # mixed
    "N": None,           # unknown / not applicable
}


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


# --- observation semantics: what does this well's water level actually constrain? (#189) ----------

def _col(df, name, default=np.nan):
    """Numeric column ``name`` if present, else an all-``default`` Series aligned to ``df``."""
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce")
    return pd.Series(default, index=df.index, dtype="float64")


def _flag(df, name):
    """Boolean column ``name`` if present, else all-False aligned to ``df``."""
    if name in df.columns:
        return df[name].fillna(False).astype(bool)
    return pd.Series(False, index=df.index, dtype=bool)


def measurement_target(sites, shallow_max_m=SHALLOW_MAX_M, deep_min_m=DEEP_MIN_M):
    """Return a Series of ``measurement_target`` per well: ``water_table``/``aquifer_head``/``unknown``.

    Evidence is applied in decreasing order of directness, and the FIRST decisive piece wins:

    1. **Flowing / artesian** (``is_flowing``, from the NWIS ``F`` status code): the head stands at
       or above land surface, so the reading is not a usable depth to a phreatic water table. Two
       different physical situations produce it -- a confined/artesian interval, and an unconfined
       table that has risen to the surface in a valley bottom -- and the status code alone does not
       distinguish them. So flowing **disqualifies** ``water_table`` but only asserts
       ``aquifer_head`` when some confining/depth evidence agrees; otherwise it downgrades to
       ``unknown``, which is the honest label for "we know this is not a clean water-table
       observation and we do not know what it is".
    2. **Aquifer type code** (``aqfr_type_cd``, GWSI domain): ``C``/``M``/``X`` -> ``aquifer_head``;
       ``U`` is evidence of an unconfined system but is not on its own sufficient, because an
       unconfined aquifer can still be screened well below its own water table -- it is combined
       with the screen/depth test below.
    3. **Screened interval** (``screen_top_m``/``screen_bottom_m``, m below land surface): a screen
       whose top is shallower than ``shallow_max_m`` and which is not entirely below the observed
       water level brackets the phreatic surface -> ``water_table``. A screen whose *top* is deeper
       than ``deep_min_m`` is sampling a deeper interval -> ``aquifer_head``.
    4. **Well depth** (``well_depth_m``, plus the legacy ``is_deep_well`` >500 ft flag): the fallback
       proxy, and the only attribute that is widely populated. ``<= shallow_max_m`` ->
       ``water_table``; ``>= deep_min_m`` or ``is_deep_well`` -> ``aquifer_head``.

    Anything the chain cannot decide -- notably a well with no depth, no screen and no aquifer code,
    and a well whose depth falls in the ``(shallow_max_m, deep_min_m)`` grey band -- is ``unknown``.
    ``unknown`` is a **flag, not a default assignment**: :func:`water_table_observations` excludes it
    unless the caller opts in explicitly, and
    :func:`src.models.observability.water_table_point_footprint` refuses it outright.
    """
    df = sites
    n = len(df)
    out = pd.Series("unknown", index=df.index, dtype=object)
    if n == 0:
        return out

    depth = _col(df, "well_depth_m")
    s_top = _col(df, "screen_top_m")
    s_bot = _col(df, "screen_bottom_m")
    is_deep = _flag(df, "is_deep_well")
    flowing = _flag(df, "is_flowing") | _flag(df, "is_artesian")

    if "aqfr_type_cd" in df.columns:
        code = df["aqfr_type_cd"].astype("string").str.strip().str.upper()
        evid = code.map(AQUIFER_TYPE_EVIDENCE)
    else:
        evid = pd.Series(pd.NA, index=df.index, dtype=object)

    # 4. depth fallback (weakest evidence first, so stronger evidence below overwrites it)
    out[depth <= shallow_max_m] = "water_table"
    out[(depth >= deep_min_m) | is_deep] = "aquifer_head"

    # 3. screened interval (direct: it says where in the column the head is sampled)
    has_screen = s_top.notna()
    out[has_screen & (s_top <= shallow_max_m)] = "water_table"
    out[has_screen & (s_top >= deep_min_m)] = "aquifer_head"
    # a screen that lies wholly below the shallow zone samples a deeper interval regardless of its top
    out[has_screen & s_bot.notna() & (s_top > shallow_max_m)] = "aquifer_head"

    # 2. aquifer type code (direct evidence of confinement)
    out[evid == "confined"] = "aquifer_head"

    # 1. flowing/artesian: never a water-table observation; aquifer_head only where corroborated
    out[flowing & (out == "water_table")] = "unknown"
    out[flowing & (evid == "confined")] = "aquifer_head"
    out[flowing & ((depth >= deep_min_m) | is_deep)] = "aquifer_head"

    return out


def water_table_observations(sites, shallow_max_m=SHALLOW_MAX_M, deep_min_m=DEEP_MIN_M,
                             include_unknown=False):
    """Subset the wells defensibly sampling the shallow unconfined water table (``measurement_target``).

    Unlike :func:`watertable_wells` -- which keeps unknown-depth wells by default and is retained for
    the Stage-1 baseline it already feeds -- this screen is **conservative**: ``unknown`` wells are
    dropped unless ``include_unknown=True``, because an observation that cannot be defended as a
    water-table measurement must not silently pin :math:`h_{wt}`.

    The returned frame carries a ``measurement_target`` column so downstream code can assert on it
    rather than re-deriving the classification.
    """
    tgt = measurement_target(sites, shallow_max_m, deep_min_m)
    keep = tgt == "water_table"
    if include_unknown:
        keep = keep | (tgt == "unknown")
    out = sites[keep].copy()
    out["measurement_target"] = tgt[keep]
    return out


def measurement_target_summary(sites, shallow_max_m=SHALLOW_MAX_M, deep_min_m=DEEP_MIN_M):
    """Counts and median DTW per ``measurement_target`` -- the audit table for a NWIS ingest run."""
    tgt = measurement_target(sites, shallow_max_m, deep_min_m)
    dtw = pd.to_numeric(sites.get("median_dtw_m"), errors="coerce")
    depth = pd.to_numeric(sites.get("well_depth_m"), errors="coerce")
    out = {}
    for k in MEASUREMENT_TARGETS:
        m = tgt == k
        out[k] = dict(
            n=int(m.sum()),
            median_depth_m=float(np.nanmedian(depth[m])) if m.any() else float("nan"),
            median_dtw_m=float(np.nanmedian(dtw[m])) if m.any() else float("nan"),
        )
    out["n_total"] = int(len(sites))
    return out
