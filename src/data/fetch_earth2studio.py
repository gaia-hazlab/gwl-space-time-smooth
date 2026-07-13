"""AI weather forecast -> rainfall forcing for the soil-state forecast (earth2studio / GraphCast).

Produces a daily precipitation + temperature forecast on the analysis grid, which
:class:`src.models.forecast.ForecastForcing` consumes. This module is the *only* place that knows
about earth2studio; the forecast physics never imports it.

## Which model actually predicts rain (this is a trap)

``GraphCastOperational`` (0.25 deg) is HRES-fine-tuned and **does not predict precipitation**: it
emits ``tp06`` as a **zero-filled placeholder** (see earth2studio's
``models/px/graphcast_operational.py``: "add in zeros tp06 (operational model does not need tp06)").
Choosing it -- the obvious pick, since it is the high-resolution one -- yields a rainfall forecast that
is identically zero, and the water budget will happily forecast a drought with no error raised.

``GraphCastSmall`` (ERA5-trained) **does** predict ``tp06``, but on a **1 degree** grid
(``lat=linspace(90,-90,181)``, ``lon=linspace(0,360,360)``) -- ~110 x 75 km at PNW latitudes. That is
far too coarse to resolve the Cascade crest, so **orographic enhancement, the dominant precipitation
signal in this domain, is absent rather than merely blurred**. This is a deliberate MVP compromise;
bias-correction against PRISM climatology and an orographic downscaler are the follow-ups.

:func:`assert_precipitation_is_real` enforces the above at runtime -- it is what stops a silent
all-zero forecast from ever reaching the water budget.

## Where this runs

earth2studio's ``graphcast`` extra requires ``jax[cuda13]`` (plus dm-haiku / flax), so **GraphCast
needs Linux + an NVIDIA GPU** -- it will not run on macOS/arm64. Run this module on a GPU host, write
the forcing netCDF, and drive the (pure-numpy) forecast anywhere:

    pip install "earth2studio[graphcast]"
    python -m src.data.fetch_earth2studio --start 2024-12-01 --lead-days 10 --out data/forecast/gc.nc

NOT YET VALIDATED against a live GPU run -- the guards below are written to fail loudly rather than
to paper over a mismatch (notably the ``tp06`` unit check, which differs between checkpoints).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger("fetch_earth2studio")

PUGET_CASCADES_BBOX = (-123.3, 46.8, -120.8, 48.5)
# earth2studio prognostic models that genuinely predict total precipitation (tp06). Anything not on
# this list must be paired with a precipitation *diagnostic* (e.g. dx.PrecipitationAFNO).
PRECIP_CAPABLE = {"FuXi", "GraphCastSmall"}
# FuXi is the preferred model here: it is the only other earth2studio prognostic that natively emits
# tp06, it runs at 0.25 deg (4x finer than GraphCastSmall's 1 deg), it is an onnxruntime model (so it
# is not CUDA-JAX-locked like GraphCast), and it is a 3-model cascade explicitly trained for
# short (5 d) / medium (10 d) / LONG (15 d) forecasts -- i.e. it covers a +1..+15 day horizon by design.
PREFERRED_MODEL = "FuXi"
MAX_LEAD_DAYS = {"FuXi": 15, "GraphCastSmall": 10}
# Every other prognostic (Pangu, FengWu, Aurora, SFNO, FCN3, ACE2) emits NO precipitation at all and
# would need the dx.PrecipitationAFNO diagnostic chained on.
PRECIP_ZERO_MODELS = {"GraphCastOperational"}          # emits tp06 as zeros -- never use for rain


def assert_precipitation_is_real(tp, model_name, min_total_mm=0.1):
    """Fail loudly if the 'rainfall forecast' is a zero-filled placeholder or otherwise degenerate.

    This exists because ``GraphCastOperational`` returns ``tp06`` as literal zeros: without this
    check the soil forecast would silently predict a drought. A forecast that is exactly zero
    everywhere is never a physical outcome over a 10-day PNW window -- it is a bug.
    """
    if model_name in PRECIP_ZERO_MODELS:
        raise ValueError(
            f"{model_name} does not predict precipitation -- it emits tp06 as zeros. "
            f"Use one of {sorted(PRECIP_CAPABLE)}, or pair it with a precipitation diagnostic."
        )
    tp = np.asarray(tp, dtype="float64")
    if not np.isfinite(tp).any():
        raise ValueError(f"{model_name}: precipitation field is entirely non-finite")
    total = float(np.nansum(tp))
    if total <= min_total_mm:
        raise ValueError(
            f"{model_name}: precipitation forecast totals {total:.4g} mm over the whole window/grid "
            "-- this is a zero/placeholder field, not a forecast. Refusing to drive the water budget."
        )
    return total


def _tp06_to_mm(tp06):
    """Convert a tp06 field to mm, guarding the m-vs-mm ambiguity between checkpoints.

    ERA5 total precipitation is accumulated **metres**; some exports are already mm. A 6-hour total
    of 0.02 m (=20 mm) is a heavy but ordinary PNW event, whereas 20 mm read as metres would be 20 m
    of rain. Decide on magnitude and say which branch was taken -- never guess silently.
    """
    tp = np.asarray(tp06, dtype="float64")
    p98 = float(np.nanpercentile(tp[np.isfinite(tp)], 98)) if np.isfinite(tp).any() else 0.0
    if p98 < 0.5:                       # metres of water (a 6h total above 0.5 m is unphysical)
        logger.info("tp06 interpreted as METRES (98th pct %.4g) -> x1000 to mm", p98)
        return tp * 1000.0
    logger.info("tp06 interpreted as MILLIMETRES (98th pct %.4g)", p98)
    return tp


def ai_precip_forecast(start_time, lead_days=15, bbox=PUGET_CASCADES_BBOX,
                       model_name=PREFERRED_MODEL, out=None):
    """Run an earth2studio prognostic model and return a DAILY precip + temperature forecast.

    Returns an ``xarray.Dataset`` with ``precip_mm`` (mm/day) and ``tmean_c`` on the model's native
    grid, clipped to ``bbox``. Raises rather than returning a degenerate field.
    """
    import torch
    import xarray as xr
    from earth2studio.data import GFS
    from earth2studio.models import px

    if model_name in PRECIP_ZERO_MODELS:
        raise ValueError(f"{model_name} emits tp06 as zeros; see PRECIP_ZERO_MODELS.")
    if model_name not in PRECIP_CAPABLE:
        raise ValueError(f"{model_name} is not known to predict tp06; known: {sorted(PRECIP_CAPABLE)}")
    cap = MAX_LEAD_DAYS[model_name]
    if lead_days > cap:
        raise ValueError(f"{model_name} is trained to {cap} days; {lead_days} d requested. "
                         f"FuXi is the 15-day model.")

    Model = getattr(px, model_name)
    model = Model.load_model(Model.load_default_package())
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        logger.warning("No CUDA device: GraphCast on CPU is very slow and may be unusable.")
    model = model.to(device)

    from earth2studio.run import deterministic

    nsteps = int(lead_days * 4)                                   # the model steps 6-hourly
    io = deterministic([str(start_time)], nsteps, model, GFS(), None)
    ds = io if isinstance(io, xr.Dataset) else io.to_xarray()

    tp = _tp06_to_mm(ds["tp06"])
    assert_precipitation_is_real(tp, model_name)

    # 6-hourly accumulations -> daily totals; temperature -> daily mean
    tp = tp.resample(lead_time="1D").sum()
    t2m = ds["t2m"].resample(lead_time="1D").mean() - 273.15

    w, s, e, n = bbox
    lon = xr.where(tp.lon > 180, tp.lon - 360, tp.lon)            # model grid is 0..360
    tp = tp.assign_coords(lon=lon).sortby("lon").sel(lon=slice(w, e), lat=slice(n, s))
    t2m = t2m.assign_coords(lon=lon).sortby("lon").sel(lon=slice(w, e), lat=slice(n, s))

    out_ds = xr.Dataset({"precip_mm": tp, "tmean_c": t2m})
    res = 0.25 if model_name == "FuXi" else 1.0
    out_ds.attrs.update(source=f"{model_name}/earth2studio", native_res_deg=res,
                        start_time=str(start_time), lead_days=lead_days, dt_days=1.0,
                        caveat=f"{res} deg grid: orographic enhancement over the Cascades is "
                               "under-resolved; bias-correct against PRISM before trusting totals")
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        out_ds.to_netcdf(out)
        logger.info("wrote %s", out)
    return out_ds


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="AI weather (GraphCast) -> daily rainfall forcing.")
    p.add_argument("--start", required=True, help="forecast initialisation time, e.g. 2024-12-01")
    p.add_argument("--lead-days", type=int, default=15)
    p.add_argument("--model", default=PREFERRED_MODEL, choices=sorted(PRECIP_CAPABLE))
    p.add_argument("--bbox", type=float, nargs=4, default=PUGET_CASCADES_BBOX)
    p.add_argument("--out", type=Path, default=Path("data/forecast/graphcast_precip.nc"))
    a = p.parse_args()
    ai_precip_forecast(a.start, a.lead_days, tuple(a.bbox), a.model, a.out)


if __name__ == "__main__":
    main()
