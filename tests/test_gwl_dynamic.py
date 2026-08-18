"""Tests for the operational dynamic-DTW product (`gwl_dynamic_90m`).

Runs standalone (`python -m tests.test_gwl_dynamic`); also pytest-discoverable.

This module krige-interpolates each well's OBSERVED anomaly (dtw_m minus that well's own
window mean) and adds it to the static baseline. It is NOT a climate-response / β-map
reconstruction (that lives in `src.models.climate_response` and is a documented future
swap-in, see the module docstring and issue #8/#23) and there is no transfer-function-noise
(TFN) model anywhere in this repo. `gwl_dynamic_90m` does not even accept a climate-index
argument, so the only thing worth pinning at the code level is the algebra it DOES implement:
DTW(t) = baseline + krige(per-well anomaly). A regression here should fail loudly if a future
edit quietly starts kriging raw well levels (not anomalies), or a shared/climate signal
instead of each well's own anomaly.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pykrige.ok as pykrige_ok
import xarray as xr

import src.models.gwl_dynamic as gd
from src.models.gwl_dynamic import gwl_dynamic_90m


class _force_kriging_failure:
    """Context manager: monkeypatch pykrige.ok.OrdinaryKriging so every call raises.

    `_krige_month` does `from pykrige.ok import OrdinaryKriging` locally on each call, so
    patching the class on the `pykrige.ok` module (not on `src.models.gwl_dynamic`, which
    holds no reference to it) is what actually reaches the code under test.
    """

    def __enter__(self):
        self._orig = pykrige_ok.OrdinaryKriging

        class _Boom:
            def __init__(self, *a, **k):
                raise RuntimeError("forced failure (test double; not a real degeneracy)")

        pykrige_ok.OrdinaryKriging = _Boom
        return self

    def __exit__(self, *exc_info):
        pykrige_ok.OrdinaryKriging = self._orig
        return False


def _grid(nx=6, ny=6, res=90.0, value=100.0):
    """A small EPSG:5070 DataArray with descending y (north-up), like our rasters."""
    x = res / 2 + res * np.arange(nx)
    y = (res / 2 + res * np.arange(ny))[::-1]
    da = xr.DataArray(np.full((ny, nx), value, "float64"), dims=("y", "x"), coords={"y": y, "x": x})
    return da.rio.write_crs("EPSG:5070")


def test_dynamic_dtw_is_baseline_plus_own_anomaly_not_raw_level_or_shared_signal():
    # Four wells, each with a wildly different absolute DTW level, but the SAME shape of
    # month-to-month change (-5 in Jan relative to its own mean, +5 in Feb). If the code
    # correctly uses each well's own anomaly, the per-month anomaly sample is a constant
    # -5 / +5 regardless of the wells' absolute levels, so the reconstructed DTW is a flat
    # baseline-5 / baseline+5. If it instead kriged raw levels (or some shared climate
    # signal), the wells' wildly different absolute levels (10 vs 1000 vs -50) would leak
    # through and this would fail.
    #
    # NOTE: because the anomaly sample is constant here (zero spatial variance), pykrige's
    # variogram fit is degenerate and `_krige_month` actually takes its `except Exception`
    # IDW fallback (verified: logs "kriging fell back to IDW ..."), where a constant input
    # trivially returns the constant. So this test pins the anomaly ALGEBRA (baseline + each
    # well's own anomaly) through whichever interpolation path runs -- it does not by itself
    # prove pykrige's ordinary-kriging path works on spatially-varying data; see
    # `test_dynamic_dtw_krige_path_produces_spatially_varying_field_not_idw_fallback` below for that.
    wells = {
        "W1": (10.0, 20.0),
        "W2": (110.0, 120.0),
        "W3": (1000.0, 1010.0),
        "W4": (-50.0, -40.0),
    }
    coords = {
        "W1": (100.0, 100.0), "W2": (400.0, 100.0),
        "W3": (100.0, 400.0), "W4": (400.0, 400.0),
    }
    rows = []
    for site, (jan, feb) in wells.items():
        x, y = coords[site]
        rows.append(dict(site_no=site, x_5070=x, y_5070=y, dtw_m=jan, date=pd.Timestamp("2024-01-01")))
        rows.append(dict(site_no=site, x_5070=x, y_5070=y, dtw_m=feb, date=pd.Timestamp("2024-02-01")))
    monthly_pilot = pd.DataFrame(rows)

    baseline = _grid(value=100.0)
    rf_std = _grid(value=1.0)

    times, dtw_90m, budget = gwl_dynamic_90m(
        monthly_pilot, baseline, rf_std, window=("2024-01-01", "2024-02-28"),
        coarse_res_m=180.0, min_wells=4,
    )

    assert len(times) == 2
    assert times[0] == pd.Timestamp("2024-01-01") and times[1] == pd.Timestamp("2024-02-01")
    jan, feb = dtw_90m[0], dtw_90m[1]

    # every well's own Jan/Feb anomaly is exactly -5 / +5 relative to ITS OWN mean, so the
    # entire reconstructed field is flat at baseline-5 / baseline+5 -- not the raw well levels
    # (10..1000) and not anything asymmetric between wells.
    assert np.allclose(jan, 95.0, atol=1e-6)
    assert np.allclose(feb, 105.0, atol=1e-6)

    # sanity: it really is baseline + a dynamic anomaly term, and the static/dynamic
    # uncertainty components are both present in the budget (no climate/forcing term).
    assert set(budget.components) == {"static_rf_baseline", "dynamic_kriging", "downscaling"}


def test_dynamic_dtw_krige_path_produces_spatially_varying_field_not_idw_fallback():
    # Same 4-well layout as above, but now the anomaly pattern is spatially structured:
    # the two SOUTH wells (y=100) get -5, the two NORTH wells (y=400) get +5 in Jan (and the
    # mirror image in Feb, since each well only has two months so its own anomaly is forced
    # antisymmetric). This gives the per-month anomaly sample genuine spatial variance, so
    # pykrige's variogram fit is non-degenerate and ordinary kriging (not the IDW fallback)
    # actually runs. This is confirmed directly by asserting the fallback's warning log never
    # fires (captured with a plain logging handler, so this works identically under pytest and
    # standalone `python -m`), not merely inferred from the output shape.
    wells = {
        "W1": (10.0, 20.0),      # south -> anom -5 (Jan) / +5 (Feb)
        "W2": (110.0, 120.0),    # south -> anom -5 (Jan) / +5 (Feb)
        "W3": (1010.0, 1000.0),  # north -> anom +5 (Jan) / -5 (Feb)
        "W4": (-40.0, -50.0),    # north -> anom +5 (Jan) / -5 (Feb)
    }
    coords = {
        "W1": (100.0, 100.0), "W2": (400.0, 100.0),
        "W3": (100.0, 400.0), "W4": (400.0, 400.0),
    }
    rows = []
    for site, (jan, feb) in wells.items():
        x, y = coords[site]
        rows.append(dict(site_no=site, x_5070=x, y_5070=y, dtw_m=jan, date=pd.Timestamp("2024-01-01")))
        rows.append(dict(site_no=site, x_5070=x, y_5070=y, dtw_m=feb, date=pd.Timestamp("2024-02-01")))
    monthly_pilot = pd.DataFrame(rows)

    baseline = _grid(value=100.0)
    rf_std = _grid(value=1.0)

    # capture WARNING logs from the gwl_dynamic module logger with a plain handler (works the
    # same under pytest or standalone `python -m`, no fixture needed). Look the logger up via
    # the module's own __name__ (not a literal "src.models.gwl_dynamic" string) so this survives
    # a package rename/restructure instead of silently stopping capturing anything.
    dyn_logger = logging.getLogger(gd.__name__)
    records: list[str] = []

    class _Collector(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Collector(level=logging.WARNING)
    dyn_logger.addHandler(handler)
    try:
        times, dtw_90m, budget = gwl_dynamic_90m(
            monthly_pilot, baseline, rf_std, window=("2024-01-01", "2024-02-28"),
            coarse_res_m=180.0, min_wells=4,
        )
    finally:
        dyn_logger.removeHandler(handler)

    # the fallback logs "kriging fell back to IDW (...)" on the module logger -- assert it
    # never fired, i.e. this test genuinely exercises pykrige's ordinary-kriging path.
    assert not any("fell back to IDW" in msg for msg in records), records

    assert len(times) == 2
    jan, feb = dtw_90m[0], dtw_90m[1]

    # the field must be non-constant (real spatial interpolation happened, not IDW-of-a-
    # -constant and not a degenerate/flat kriging result).
    assert np.nanstd(jan) > 1e-6
    assert np.nanstd(feb) > 1e-6

    # sign/ordering sanity: south (y=100, near W1/W2) should read LOWER than north (y=400,
    # near W3/W4) in Jan, and the mirror in Feb -- following the wells' anomaly pattern.
    y_coord = baseline["y"].values
    south_rows = y_coord < 250.0
    north_rows = y_coord >= 250.0
    assert np.nanmean(jan[south_rows, :]) < np.nanmean(jan[north_rows, :])
    assert np.nanmean(feb[south_rows, :]) > np.nanmean(feb[north_rows, :])

    # bracketing sanity: kriging is clipped to [min(anom) - prior, max(anom) + prior] with
    # prior = std(anom) = 5.0, i.e. the reconstructed DTW cannot stray past baseline +/- 10.
    assert np.nanmin(jan) >= 100.0 - 10.0 - 1e-6
    assert np.nanmax(jan) <= 100.0 + 10.0 + 1e-6

    assert set(budget.components) == {"static_rf_baseline", "dynamic_kriging", "downscaling"}

    # Structural discriminator that does NOT depend on the log message/logger name: the
    # kriging branch's sigma (gwl_dynamic.py:64, ok.execute's kriging variance, clipped to
    # [0, prior]) and the IDW branch's sigma (gwl_dynamic.py:74, a hand-rolled
    # prior*(1-exp(-nearest_well_dist/(5*dx))) decay) are built by unrelated formulas that,
    # for this exact 4-well/coarse-grid layout, land in non-overlapping ranges: real ordinary
    # kriging here saturates the sigma near its `prior` cap almost everywhere on the coarse
    # grid (mean sigma ~4.78, min ~3.03 out of prior=5), because the variogram's fitted range
    # is short relative to the well spacing, so nowhere on the coarse grid (which never
    # coincides exactly with a well) is "close" in variogram terms. The IDW fallback's decay
    # formula instead forces sigma -> 0 at well locations and stays low across this domain
    # (mean ~0.52, min ~0.08). (Verified by forcing pykrige to raise: this assertion flips
    # from passing to failing under the fallback -- see
    # test_dynamic_dtw_idw_fallback_produces_sane_field_when_kriging_forced_to_fail below for
    # the actual measured fallback values.) Thresholds are set with wide margin from both
    # measured values so this does not depend on exact floating-point/variogram-fit output.
    sig_dyn = budget.components["dynamic_kriging"]
    assert np.nanmean(sig_dyn) > 2.0, sig_dyn
    assert np.nanmin(sig_dyn) > 1.0, sig_dyn


def test_dynamic_dtw_idw_fallback_produces_sane_field_when_kriging_forced_to_fail():
    # Deliberately pins the IDW fallback branch itself (gwl_dynamic.py:66-75), rather than
    # exercising it by accident/degeneracy. Same spatially-structured 4-well layout as
    # `test_dynamic_dtw_krige_path_produces_spatially_varying_field_not_idw_fallback`, but here
    # pykrige.ok.OrdinaryKriging is monkeypatched to always raise, so every month is forced
    # down the IDW path. This is also the mutation used to prove the sibling test's assertions
    # actually discriminate the two branches (see PR discussion / Auditor review): with this
    # same monkeypatch, the sibling test's kriging-sigma assertions (nanmean/nanmin thresholds
    # above) fail, while this test's IDW-appropriate assertions below pass.
    wells = {
        "W1": (10.0, 20.0), "W2": (110.0, 120.0),
        "W3": (1010.0, 1000.0), "W4": (-40.0, -50.0),
    }
    coords = {
        "W1": (100.0, 100.0), "W2": (400.0, 100.0),
        "W3": (100.0, 400.0), "W4": (400.0, 400.0),
    }
    rows = []
    for site, (jan, feb) in wells.items():
        x, y = coords[site]
        rows.append(dict(site_no=site, x_5070=x, y_5070=y, dtw_m=jan, date=pd.Timestamp("2024-01-01")))
        rows.append(dict(site_no=site, x_5070=x, y_5070=y, dtw_m=feb, date=pd.Timestamp("2024-02-01")))
    monthly_pilot = pd.DataFrame(rows)

    baseline = _grid(value=100.0)
    rf_std = _grid(value=1.0)

    dyn_logger = logging.getLogger(gd.__name__)
    records: list[str] = []

    class _Collector(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Collector(level=logging.WARNING)
    dyn_logger.addHandler(handler)
    try:
        with _force_kriging_failure():
            times, dtw_90m, budget = gwl_dynamic_90m(
                monthly_pilot, baseline, rf_std, window=("2024-01-01", "2024-02-28"),
                coarse_res_m=180.0, min_wells=4,
            )
    finally:
        dyn_logger.removeHandler(handler)

    # confirm the fallback really is the code path that ran (both months).
    assert sum("fell back to IDW" in msg for msg in records) == 2, records

    assert len(times) == 2
    jan, feb = dtw_90m[0], dtw_90m[1]

    # the IDW fallback still produces a sane, finite, non-constant, correctly-ordered field.
    assert np.all(np.isfinite(jan)) and np.all(np.isfinite(feb))
    assert np.nanstd(jan) > 1e-6 and np.nanstd(feb) > 1e-6

    y_coord = baseline["y"].values
    south_rows = y_coord < 250.0
    north_rows = y_coord >= 250.0
    assert np.nanmean(jan[south_rows, :]) < np.nanmean(jan[north_rows, :])
    assert np.nanmean(feb[south_rows, :]) > np.nanmean(feb[north_rows, :])

    assert np.nanmin(jan) >= 100.0 - 10.0 - 1e-6
    assert np.nanmax(jan) <= 100.0 + 10.0 + 1e-6

    # this is the discriminator: under the FORCED fallback, sigma sits low, unlike the real
    # kriging branch's near-prior-saturated sigma in the sibling test.
    sig_dyn = budget.components["dynamic_kriging"]
    assert np.nanmean(sig_dyn) < 2.0, sig_dyn


if __name__ == "__main__":
    test_dynamic_dtw_is_baseline_plus_own_anomaly_not_raw_level_or_shared_signal()
    test_dynamic_dtw_krige_path_produces_spatially_varying_field_not_idw_fallback()
    test_dynamic_dtw_idw_fallback_produces_sane_field_when_kriging_forced_to_fail()
    print("all gwl_dynamic tests passed")
