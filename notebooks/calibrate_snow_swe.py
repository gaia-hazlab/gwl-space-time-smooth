"""Calibrate the degree-day snow module against SNOTEL SWE (D8, #100).

The snowpack is the water table's clock: melt release peaks in April and the observed water table
peaks in April. Our degree-day parameters (ddf, t_snow_hi/lo, t_melt) are NOMINAL and have never been
fitted, because the old lowland domain is rain-dominated and the module never fired.

Calibrated at the SNOTEL stations using each station's OWN precipitation and temperature, so the 4 km
PRISM rain/snow-line smearing is not inside the calibration loop. The rain/snow line is sharp; a 4 km
cell straddling it smears the partition and would be fitted as a model error.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("calib_snow")


def swe_series(precip, tmean, ddf, t_snow_lo, t_snow_hi, t_melt):
    """Degree-day SWE (mm) — the same partition as src.models.forecast.liquid_input, exposing SWE."""
    p = np.asarray(precip, float)
    t = np.asarray(tmean, float)
    rain_frac = np.clip((t - t_snow_lo) / max(t_snow_hi - t_snow_lo, 1e-6), 0.0, 1.0)
    snow = p * (1.0 - rain_frac)
    swe = np.zeros(len(p))
    s = 0.0
    for i in range(len(p)):
        s += snow[i]
        melt = min(max(ddf * (t[i] - t_melt), 0.0), s)
        s -= melt
        swe[i] = s
    return swe


def _meltout(swe, thresh=10.0):
    """Index of melt-out: the first day after the peak on which the pack is essentially gone.

    This -- not the SWE peak, and not RMSE -- is what sets the water table's phase.
    """
    pk = int(np.argmax(swe))
    after = np.where(np.asarray(swe)[pk:] < thresh)[0]
    return int(pk + after[0]) if after.size else len(swe)


def main():
    df = pd.read_parquet("data/processed/snotel_swe_daily.parquet")
    df = df.dropna(subset=["swe_mm", "tmean_c", "precip_mm"]).sort_values(["triplet", "date"])
    logger.info("stations: %d, rows: %d", df.triplet.nunique(), len(df))

    best = None
    for ddf in (1.5, 2.0, 3.0, 4.0, 5.0, 6.0):
        for tlo in (-2.0, -1.0, 0.0):
            for thi in (1.0, 2.0, 3.0, 4.0):
                for tm in (-1.0, 0.0, 1.0):
                    errs, peaks, outs = [], [], []
                    for _, g in df.groupby("triplet"):
                        obs = g.swe_mm.values
                        mod = swe_series(g.precip_mm.values, g.tmean_c.values, ddf, tlo, thi, tm)
                        errs.append(np.sqrt(np.mean((mod - obs) ** 2)))
                        peaks.append(abs(int(np.argmax(mod)) - int(np.argmax(obs))))
                        outs.append(abs(_meltout(mod) - _meltout(obs)))
                    rmse = float(np.mean(errs))
                    dpk = float(np.mean(peaks))
                    dout = float(np.mean(outs))
                    # MELT-OUT timing is the objective, not generic RMSE. RMSE is dominated by the
                    # ACCUMULATION season, and optimising it picked ddf=1.5, which melted so slowly the
                    # pack lingered into June (mod 70 mm vs obs 6 mm) and pushed melt release into MAY --
                    # when the wells say APRIL. What sets the water table's clock is when the snow
                    # actually leaves, so that is what we fit.
                    score = rmse / 200.0 + dpk / 20.0 + dout / 7.0
                    if best is None or score < best[0]:
                        best = (score, ddf, tlo, thi, tm, rmse, dpk, dout)

    score, ddf, tlo, thi, tm, rmse, dpk, dout = best
    print()
    print("NOMINAL (never fitted): ddf=3.0  t_snow=-1..3  t_melt=0.0")
    print("CALIBRATED            : ddf=%.1f  t_snow=%.1f..%.1f  t_melt=%.1f" % (ddf, tlo, thi, tm))
    print("   SWE RMSE %.0f mm | SWE-peak err %.1f d | MELT-OUT err %.1f d (the one that matters)"
          % (rmse, dpk, dout))
    print()

    # seasonality with the calibrated parameters: when does the melt actually release its water?
    df["month"] = pd.to_datetime(df.date).dt.month
    rows = []
    for _, g in df.groupby("triplet"):
        g = g.sort_values("date")
        mod = swe_series(g.precip_mm.values, g.tmean_c.values, ddf, tlo, thi, tm)
        melt = np.diff(np.concatenate([[0.0], mod]))
        rows.append(pd.DataFrame({"month": pd.to_datetime(g.date).dt.month.values,
                                  "obs_swe": g.swe_mm.values, "mod_swe": mod,
                                  "melt_mm": np.clip(-melt, 0, None)}))
    r = pd.concat(rows)
    # NB: do not name a column "melt" -- DataFrame.melt() shadows it on attribute access.
    c = r.groupby("month").agg(obs_swe=("obs_swe", "mean"), mod_swe=("mod_swe", "mean"),
                               melt_out=("melt_mm", "sum"))
    mo = c["melt_out"]
    print(" mo   obs SWE   mod SWE   MELT released")
    for m in c.index:
        bar = "#" * int(mo[m] / max(mo.max(), 1) * 28)
        print(" %2d  %8.0f %9.0f   %s" % (m, c["obs_swe"][m], c["mod_swe"][m], bar))
    print()
    print("  observed SWE peaks : month %d" % int(c["obs_swe"].idxmax()))
    print("  modelled SWE peaks : month %d" % int(c["mod_swe"].idxmax()))
    print("  MELT RELEASE peaks : month %d   <-- this is the water table's clock" % int(mo.idxmax()))
    print("  observed WELLS peak: month 4    (26,816 shallow-well obs)")


if __name__ == "__main__":
    main()
