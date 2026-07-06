"""dv/v module: ambient-noise cross-correlation -> banded dv/v -> depth-separated GWL & SM.

This is the third state variable's measurement path. It is deliberately split so the pieces are
independently testable and swappable:

  1. **Correlation layer (this file, new code).** Preprocess continuous noise, cross-correlate
     (single-station cross-component or a station pair), stack to a reference, and measure a
     relative velocity change per frequency band by coda-wave *stretching*. Output: dv/v(t) and
     the coda coherence cc(t) for each band. Grounded in the controlled-synthetic test of the
     companion methods paper (Denolle, in prep): a known dv/v is imposed by stretching the lapse
     axis and must be recovered.

  2. **Measurement uncertainty (codameter).** ``weaver_stretching_error`` turns cc into the
     Weaver/Clarke coherence bound on each dv/v; ``single_reference_dvv`` propagates the common
     reference error into a dense covariance. codameter is imported lazily.

  3. **Depth separation (codameter).** ``band_sensitivity_matrix`` builds the multi-band Rayleigh
     kernel G(f, z) (peak depth ~ Vs/3f); ``invert_depth_profile`` inverts the banded dv/v for a
     depth profile of dVs/Vs with propagated error. Splitting that profile at the **water-table
     depth** gives the two contributions the problem needs:
         shallow (above the water table) -> soil moisture (vadose capillary stiffness)
         deep   (below the water table)  -> **relative** water-table depth (poroelastic head)
     dv/v yields a *relative* GWL change, not an absolute level, consistent with the literature.

  4. **Forcing attribution (codameter).** ``run_workflow`` decomposes dv/v into temperature,
     precipitation/GWL, and trend terms with propagated uncertainty.

Steps 1 is self-contained; steps 2-4 require ``codameter`` (Denolle-Lab). The frequency->depth
physics follows the JGR framework (Denolle, submitted): delta v/v is a depth-averaged,
frequency-dependent measurement, L_peak = Vs/(3f).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

# Default monitoring bands (Hz): low->deep (GWL/WTD), high->shallow (soil moisture).
# Matches the multi-band grids of Okubo et al. (2024) / Ermert et al. (2023).
DEFAULT_BANDS = ((0.1, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 4.0))


def peak_depth_km(f_hz, vs_ms=1500.0):
    """Rayleigh peak-sensitivity depth L = Vs/(3f) (Obermann 2014; framework Eq. 13), in km."""
    return vs_ms / (3.0 * np.asarray(f_hz, dtype="float64")) / 1000.0


# --- Convert depth-separated dv/v to model state units (for assimilation) --------------------
# Nominal, calibration-pending sensitivities (documented; anchor to boreholes/lab).
from src.models.dvv_coupling import K_SAT           # dv/v per metre of head (5e-4)

# dv/v per unit volumetric θ; NEGATIVE because wetting softens the frame (v drops). Nominal.
S_THETA = -2.0


def dvv_to_wtd_change(dvv_wtd, dvv_wtd_std, k_sat=K_SAT):
    """Deep (saturated-band) dv/v -> RELATIVE water-table depth change in metres, with sigma.

    Poroelastic head sensitivity (dvv_coupling): dv/v = k_sat * ΔWTD, deeper table positive.
    Returns (delta_wtd_m, sigma_m). This is a *relative* change, not an absolute level.
    """
    return np.asarray(dvv_wtd) / k_sat, np.abs(np.asarray(dvv_wtd_std) / k_sat)


def dvv_to_theta_change(dvv_sm, dvv_sm_std, sensitivity=S_THETA):
    """Shallow (vadose-band) dv/v -> volumetric soil-moisture change Δθ, with sigma.

    dv/v = sensitivity * Δθ (sensitivity < 0: wetter -> softer -> lower velocity). Nominal
    sensitivity; calibrate against the SOLUS/Saxton-Rawls vadose operator per site.
    """
    return np.asarray(dvv_sm) / sensitivity, np.abs(np.asarray(dvv_sm_std) / sensitivity)


# ---------------------------------------------------------------------------
# 1. Correlation layer (new code)
# ---------------------------------------------------------------------------
def preprocess(data, sr, freqmin=0.05, freqmax=8.0, whiten=True, onebit=False):
    """Ambient-noise preprocessing: detrend, taper, bandpass, temporal + spectral normalization.

    ``data`` is a 1-D float array at sample rate ``sr`` (Hz). Returns the conditioned trace.
    Temporal normalization (running-abs-mean by default, one-bit optional) suppresses
    earthquakes/transients; spectral whitening flattens the noise spectrum so the correlation
    is dominated by phase, not source spectrum.
    """
    x = np.asarray(data, dtype="float64")
    x = signal.detrend(x, type="linear")
    x *= signal.windows.tukey(x.size, alpha=0.05)
    sos = signal.butter(4, [freqmin, freqmax], btype="band", fs=sr, output="sos")
    x = signal.sosfiltfilt(sos, x)
    if onebit:
        x = np.sign(x)
    else:                                             # running-absolute-mean normalization
        w = max(1, int(sr / (2.0 * freqmin)))
        env = np.convolve(np.abs(x), np.ones(w) / w, mode="same")
        x = np.divide(x, env, out=np.zeros_like(x), where=env > 0)
    if whiten:
        X = np.fft.rfft(x)
        mag = np.abs(X)
        X = np.divide(X, mag, out=np.zeros_like(X), where=mag > 0)
        # re-band after whitening (whitening is broadband) to keep the working band
        x = np.fft.irfft(X, n=x.size)
        x = signal.sosfiltfilt(sos, x)
    return x


def cross_correlate(a, b, sr, maxlag_s=60.0):
    """Normalized cross-correlation of two preprocessed traces; returns (lags_s, ccf).

    Symmetric lag axis in [-maxlag, +maxlag]. Normalized by the geometric mean energy so the
    zero-lag of the auto-correlation is 1; this is the daily noise correlation function (NCF).
    """
    a = np.asarray(a, float); b = np.asarray(b, float)
    n = int(maxlag_s * sr)
    full = signal.fftconvolve(a, b[::-1], mode="full")
    mid = full.size // 2
    ccf = full[mid - n: mid + n + 1]
    norm = np.sqrt(np.sum(a * a) * np.sum(b * b))
    ccf = ccf / norm if norm > 0 else ccf
    lags = np.arange(-n, n + 1) / sr
    return lags, ccf


def stretching_dvv(cur, ref, lags, band, cc_min=0.0, eps_max=0.03, n_eps=201):
    """Coda-wave *stretching* dv/v of ``cur`` vs ``ref`` over a symmetric coda window.

    Searches a uniform velocity perturbation eps = -dv/v by resampling the lapse axis
    t -> t(1+eps) and maximizing the correlation coefficient with the reference over the coda
    window ``band=(t1,t2)`` (both causal and acausal lobes). Returns (dvv, cc):

        dvv = -eps*  (the stretch that best matches the reference)
        cc  = max correlation coefficient at eps*  (feeds the Weaver error bound)
    """
    t1, t2 = band
    ref = np.asarray(ref, float); cur = np.asarray(cur, float)
    mask = (np.abs(lags) >= t1) & (np.abs(lags) <= t2)
    idx = np.where(mask)[0]
    r = ref[idx]
    eps = np.linspace(-eps_max, eps_max, n_eps)
    ccs = np.empty(n_eps)
    for i, e in enumerate(eps):
        stretched = np.interp(lags[idx], lags[idx] * (1.0 + e), cur[idx])
        s = stretched - stretched.mean()
        rr = r - r.mean()
        denom = np.sqrt(np.sum(s * s) * np.sum(rr * rr))
        ccs[i] = np.sum(s * rr) / denom if denom > 0 else 0.0
    j = int(np.argmax(ccs))
    cc = float(ccs[j])
    # Sub-grid refinement: parabolic vertex of cc(eps) around the peak (standard practice; avoids
    # quantizing dv/v to the eps grid, which would collapse the processing-ensemble spread).
    e_star = eps[j]
    if 0 < j < n_eps - 1:
        c0, c1, c2 = ccs[j - 1], ccs[j], ccs[j + 1]
        denom = c0 - 2.0 * c1 + c2
        if denom != 0.0:
            delta = 0.5 * (c0 - c2) / denom            # in [-1, 1] grid steps
            e_star = eps[j] + np.clip(delta, -1.0, 1.0) * (eps[1] - eps[0])
    if cc < cc_min:
        return np.nan, cc
    return float(-e_star), cc


@dataclass
class BandedDvv:
    """Per-band dv/v(t) and coherence, plus the band centers/edges and coda window used."""

    times: np.ndarray               # (n_epoch,) epoch index or datetime
    bands_hz: np.ndarray            # (n_band, 2) band edges
    f_center_hz: np.ndarray         # (n_band,) geometric-mean center
    dvv: np.ndarray                 # (n_epoch, n_band)
    cc: np.ndarray                  # (n_epoch, n_band)
    coda_s: tuple                   # (t1, t2) coda window


def measure_banded_dvv(ccf_series, ref, lags, sr, bands=DEFAULT_BANDS,
                       coda_s=(5.0, 30.0), times=None):
    """Measure dv/v(t) per frequency band from a series of daily NCFs against a reference.

    ``ccf_series`` is (n_epoch, n_lag); ``ref`` is (n_lag,). Each NCF and the reference are
    band-passed to each band, then stretched over the coda window. Returns a ``BandedDvv``.
    """
    ccf_series = np.atleast_2d(ccf_series)
    n_epoch = ccf_series.shape[0]
    bands = np.asarray(bands, float)
    fc = np.sqrt(bands[:, 0] * bands[:, 1])
    dvv = np.full((n_epoch, len(bands)), np.nan)
    cc = np.zeros((n_epoch, len(bands)))
    for bi, (f1, f2) in enumerate(bands):
        sos = signal.butter(4, [f1, f2], btype="band", fs=sr, output="sos")
        rb = signal.sosfiltfilt(sos, ref)
        for ei in range(n_epoch):
            cb = signal.sosfiltfilt(sos, ccf_series[ei])
            dvv[ei, bi], cc[ei, bi] = stretching_dvv(cb, rb, lags, coda_s)
    if times is None:
        times = np.arange(n_epoch)
    return BandedDvv(times=np.asarray(times), bands_hz=bands, f_center_hz=fc,
                     dvv=dvv, cc=cc, coda_s=coda_s)


# ---------------------------------------------------------------------------
# 2. Processing ensemble -> honest data covariance Cd (codameter)
# ---------------------------------------------------------------------------
# The uncertainty on dv/v is NOT just the Weaver coherence bound and the shared-reference term.
# The dominant, usually-hidden component is *methodological*: the spread across defensible
# processing choices (estimator, coda window, reference, band edges). codameter marginalises a
# processing ensemble into a single time-dependent data covariance Cd -- the honest object the
# depth inversion needs (Denolle, in prep). Here the correlation layer *generates* that ensemble
# by sweeping coda windows and reference epochs; codameter aggregates it.

# Coda windows and reference epochs swept to build the processing ensemble per band.
DEFAULT_CODA_WINDOWS = ((5.0, 25.0), (8.0, 30.0), (10.0, 40.0), (15.0, 50.0))


def processing_ensemble_dvv(ccf_series, lags, sr, bands=DEFAULT_BANDS,
                            coda_windows=DEFAULT_CODA_WINDOWS, ref_indices=(0,),
                            times_days=None):
    """Sweep processing choices per band and marginalise into codameter EnsembleResults.

    For every (coda window, reference epoch) configuration the coda-stretching dv/v(t) is
    measured; the Weaver coherence bound gives its within-configuration error. codameter's
    ``processing_ensemble`` combines the members by the law of total variance, exposing the
    *methodological* spread (the reproducibility uncertainty a single choice hides).

    Returns dict keyed by band center frequency -> dict(ensemble=EnsembleResult, Cd=ndarray),
    where ``Cd`` is the structured time-domain data covariance for that band.
    """
    from codameter.uq_measurement import (
        processing_ensemble,
        temporal_error_covariance,
        weaver_stretching_error,
    )

    ccf_series = np.atleast_2d(ccf_series)
    n_epoch = ccf_series.shape[0]
    bands = np.asarray(bands, float)
    fc = np.sqrt(bands[:, 0] * bands[:, 1])
    if times_days is None:
        times_days = np.arange(n_epoch, dtype="float64")

    out = {}
    for bi, (f1, f2) in enumerate(bands):
        sos = signal.butter(4, [f1, f2], btype="band", fs=sr, output="sos")
        cbands = np.array([signal.sosfiltfilt(sos, ccf_series[ei]) for ei in range(n_epoch)])
        members, within = {}, {}
        for (t1, t2) in coda_windows:
            raw = np.array([stretching_dvv(cbands[ei], cbands[0], lags, (t1, t2))
                            for ei in range(n_epoch)])          # per-epoch (dvv, cc)
            dvv_series, cc_series = raw[:, 0], raw[:, 1]
            sig = np.asarray(weaver_stretching_error(cc_series, float(fc[bi]), t1, t2), float)
            for ref in ref_indices:                             # re-reference to epoch `ref`
                lbl = f"coda{t1:g}-{t2:g}_ref{ref}"
                members[lbl] = dvv_series - dvv_series[ref]
                within[lbl] = sig
        ens = processing_ensemble(members, within_sigma=within)
        # Cd = structured within-method covariance (overlap + common mode) + methodological cov.
        cd = temporal_error_covariance(ens.within_std, times_days, corr_length_days=3.0,
                                       common_mode_sigma=float(np.median(ens.within_std)))
        cd = cd + ens.methodological_covariance()
        out[float(fc[bi])] = dict(ensemble=ens, Cd=cd)
    return out


def pnw_velocity_profile(vs30_ms=400.0, target_dz_km=0.01, max_depth_km=6.0):
    """A nominal Pacific-Northwest shallow layered model as a codameter ``VelocityProfile``.

    A soft sedimentary cover over increasing crystalline velocity -- adequate for building the
    band sensitivity kernels; replace per-site with an ambient-noise tomography profile. The
    top layer's Vs is tied to Vs30 (km/s).
    """
    from codameter.kernels.velocity_models import make_fine_model

    vs0 = vs30_ms / 1000.0
    thick = [0.05, 0.5, 2.0, 0.0]                    # km; last = half-space
    vs = [vs0, max(vs0 * 2.0, 0.8), 2.2, 3.4]
    vp = [v * 1.9 for v in vs]
    rho = [1.9, 2.1, 2.5, 2.8]
    return make_fine_model(thick, vp, vs, [r for r in rho],
                           target_dz_km=target_dz_km, max_depth_km=max_depth_km)


# ---------------------------------------------------------------------------
# 3. Depth separation: banded dv/v + Cd -> depth profile split at the water table (codameter)
# ---------------------------------------------------------------------------
def separate_depth(ens_by_band, velocity_profile, water_table_depth_km,
                   epoch=-1, prior_std=5e-3, corr_length_km=0.1):
    """Invert the banded dv/v for a depth profile and split it at the water table (codameter).

    ``ens_by_band`` is the output of :func:`processing_ensemble_dvv`. The per-band data variance
    fed to the inversion is the ensemble ``total_std`` (within + methodological) -- so processing
    uncertainty propagates into the depth profile, not just the coherence bound. The profile is
    partitioned at ``water_table_depth_km``:

        shallow (<= water table) -> soil moisture (vadose)
        deep    (>  water table) -> **relative** water-table depth (saturated / poroelastic)

    Returns (DepthProfilePosterior, partition dict with propagated std at ``epoch``).
    """
    from codameter.uq_depth import band_sensitivity_matrix, invert_depth_profile

    fcs = sorted(ens_by_band)
    kernels = band_sensitivity_matrix(velocity_profile, np.array(fcs))
    dvv_bands = np.array([ens_by_band[fc]["ensemble"].mean[epoch] for fc in fcs])
    total = np.array([ens_by_band[fc]["ensemble"].total_std[epoch] for fc in fcs])
    cov_bands = np.diag(total ** 2)                  # per-epoch band covariance (incl. method.)
    post = invert_depth_profile(dvv_bands, cov_bands, kernels,
                                prior_std=prior_std, corr_length_km=corr_length_km)
    z = kernels.depths_km
    m, sd = np.asarray(post.mean), post.std
    shallow = z <= water_table_depth_km

    def _agg(vals, err):
        if not len(vals):
            return np.nan, np.nan
        return float(np.mean(vals)), float(np.sqrt(np.mean(err ** 2)) / np.sqrt(len(vals)))

    sm, sm_sd = _agg(m[shallow], sd[shallow])
    wtd, wtd_sd = _agg(m[~shallow], sd[~shallow])
    part = dict(depths_km=z, profile=m, profile_std=sd, water_table_km=float(water_table_depth_km),
                soil_moisture_dvv=sm, soil_moisture_dvv_std=sm_sd,
                wtd_relative_dvv=wtd, wtd_relative_dvv_std=wtd_sd,
                peak_depths_km=kernels.peak_depths_km)
    return post, part
