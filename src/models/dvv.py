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

# dv/v per unit volumetric θ, for the depth-separated SHALLOW-BAND measurement. NEGATIVE (wetting
# softens the frame -> velocity drops). It is the product of two factors:
#   * material sensitivity S_MATERIAL ≈ -1.0 per unit θ, from the Hertz-Mindlin + van Genuchten
#     capillary-suction vadose model (dvv_coupling._vs_vadose): a 0.1 θ swing changes the *local*
#     shallow-soil velocity by ~10%; and
#   * a DEPTH-DILUTION factor ≈ 0.08: the θ-varying layer is only the top ~1 m, but the shallow
#     band's Rayleigh sensitivity kernel peaks near ~45 m (L = Vs/3f), so only a small fraction of
#     the band's kernel weight lies in the θ-active zone.
# The product S_THETA ≈ -0.08 gives ~0.8% dv/v for a 0.1 m³/m³ seasonal swing, matching the observed
# ~0.1-1% ambient-noise seasonal dv/v (the earlier -2.0 implied ~20%, ~1-2 orders too large). Refine
# per site from the actual band kernel and the local vadose envelope.
S_MATERIAL_THETA = -1.0
KERNEL_FRACTION_TOP1M = 0.08
S_THETA = S_MATERIAL_THETA * KERNEL_FRACTION_TOP1M   # ≈ -0.08 dv/v per unit volumetric θ


def dvv_to_wtd_change(dvv_wtd, dvv_wtd_std, k_sat=K_SAT):
    """Deep (saturated-band) dv/v -> RELATIVE water-table depth change in metres, with sigma.

    Poroelastic head sensitivity (dvv_coupling): dv/v = k_sat * ΔWTD, deeper table positive.
    Returns (delta_wtd_m, sigma_m). This is a *relative* change, not an absolute level.
    """
    return np.asarray(dvv_wtd) / k_sat, np.abs(np.asarray(dvv_wtd_std) / k_sat)


def dvv_to_theta_change(dvv_sm, dvv_sm_std, sensitivity=S_THETA):
    """Shallow (vadose-band) dv/v -> volumetric soil-moisture change Δθ, with sigma.

    dv/v = sensitivity * Δθ (sensitivity < 0: wetter -> softer -> lower velocity). The default
    ``S_THETA ≈ -0.08`` is the material vadose sensitivity (~-1 per unit θ, Hertz-Mindlin + suction)
    diluted by the fraction (~0.08) of the shallow band's kernel that lies in the θ-active top ~1 m,
    which reproduces the observed ~0.1-1% seasonal dv/v. Calibrate per site from the band kernel and
    the local Saxton-Rawls / van Genuchten vadose envelope.
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
            for ref in ref_indices:                             # stretch against epoch `ref` itself
                raw = np.array([stretching_dvv(cbands[ei], cbands[ref], lags, (t1, t2))
                                for ei in range(n_epoch)])      # per-epoch (dvv, cc) rel. to `ref`
                dvv_series, cc_series = raw[:, 0], raw[:, 1]     # dvv_series[ref] == 0 by construction
                sig = np.asarray(weaver_stretching_error(cc_series, float(fc[bi]), t1, t2), float)
                lbl = f"coda{t1:g}-{t2:g}_ref{ref}"
                members[lbl] = dvv_series                        # genuinely reference-specific member
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
        # The depth nodes are prior-correlated (corr_length_km), so we do NOT divide the RMS node
        # error by sqrt(N) -- that would treat correlated samples as independent and understate the
        # aggregated uncertainty that then sets the assimilation precision. Report the RMS (the
        # fully-correlated, conservative bound) instead.
        if not len(vals):
            return np.nan, np.nan
        return float(np.mean(vals)), float(np.sqrt(np.mean(err ** 2)))

    sm, sm_sd = _agg(m[shallow], sd[shallow])
    wtd, wtd_sd = _agg(m[~shallow], sd[~shallow])
    part = dict(depths_km=z, profile=m, profile_std=sd, water_table_km=float(water_table_depth_km),
                soil_moisture_dvv=sm, soil_moisture_dvv_std=sm_sd,
                wtd_relative_dvv=wtd, wtd_relative_dvv_std=wtd_sd,
                peak_depths_km=kernels.peak_depths_km)
    return post, part


def invert_states_from_bands(dvv_bands, cov_bands, kernels, water_table_km, top_km=0.03,
                             prior_std=5e-3, corr_length_km=0.1):
    """Invert one epoch's banded dv/v (with covariance) for the three state dv/v means + propagated σ.

    The efficient, honest per-station entry point: pass PRE-BUILT ``kernels`` (so the ~12 s disba
    kernel build happens once, not per call) and the measurement covariance ``cov_bands``. Returns
    dict with the shallow (soil-moisture), deep (relative WTD), and top-``top_km`` (Vs30) mean dv/v
    and their aggregated posterior σ -- all from the depth INVERSION, carrying measurement + inversion
    error. σ is the RMS over the depth nodes (prior-correlated, so not reduced by sqrt(N)).
    """
    from codameter.uq_depth import invert_depth_profile

    post = invert_depth_profile(np.asarray(dvv_bands), np.asarray(cov_bands), kernels,
                                prior_std=prior_std, corr_length_km=corr_length_km)
    z = np.asarray(kernels.depths_km); m, sd = np.asarray(post.mean), post.std
    shallow, deep, top = z <= water_table_km, z > water_table_km, z <= top_km

    def _agg(mask):
        if not mask.any():
            return np.nan, np.nan
        return float(np.mean(m[mask])), float(np.sqrt(np.mean(sd[mask] ** 2)))

    sm, sm_sd = _agg(shallow); wtd, wtd_sd = _agg(deep); v, v_sd = _agg(top)
    return dict(soil_moisture_dvv=sm, soil_moisture_dvv_std=sm_sd,
                wtd_relative_dvv=wtd, wtd_relative_dvv_std=wtd_sd,
                vs30_frac=v, vs30_frac_std=v_sd)


# ---------------------------------------------------------------------------
# 5. Physically realistic band-dependent synthetic (for the digital-twin demo)
# ---------------------------------------------------------------------------
# The old bulk synthetic stretched every band identically. Real dv/v is depth-structured: low
# frequencies (deep) track slow groundwater variation; high frequencies (shallow) track fast daily
# ET / rainfall perturbations. We build a depth-time truth m(z,t) = dVs/Vs(z,t) with that
# structure, forward it through the band kernels, and (optionally) synthesize per-band NCFs so the
# measurement chain recovers band-specific dv/v. Signs match the state conversions above: a
# deeper table (dry season) stiffens the saturated zone -> POSITIVE deep-band dv/v; a wetting pulse
# softens the vadose zone -> NEGATIVE shallow-band dv/v.


# Fraction of a hydrologic year (Oct 1 start) at the late-summer dry/stiff peak (~mid-Aug).
DRY_PEAK = 0.85


def synthetic_depth_time_truth(depths_km, n_epoch=73, dt_days=5.0, water_table_km=0.03,
                               shallow_max_km=0.05, gwl_seasonal=1.5e-3, gwl_trend=1.0e-3,
                               et_seasonal=2.0e-3, storm_amp=3.0e-3, storm_rate=0.18,
                               ar1_rho=0.6, seed=0):
    """Depth-time truth m(z,t)=dVs/Vs on the kernel depth grid; deep=slow GWL, shallow=fast ET/rain.

    Returns (m_zt (n_depth, n_epoch), t_days (n_epoch,)). Deep layers (z > water table) carry a
    smooth seasonal + interannual-drift groundwater signal (positive in the dry season); shallow
    layers (z <= shallow_max_km) carry a higher-frequency storm/ET train (negative wetting pulses
    on top of a seasonal ET cycle).
    """
    z = np.asarray(depths_km, dtype="float64")
    rng = np.random.RandomState(seed)
    t = np.arange(n_epoch, dtype="float64") * dt_days
    T = n_epoch * dt_days

    # depth blend: deep sigmoid switches on below the water table, shallow rolls off past ~50 m.
    w_deep = 0.5 * (1.0 + np.tanh((z - water_table_km) / 0.02))
    w_shal = 0.5 * (1.0 - np.tanh((z - shallow_max_km) / 0.02))

    # One shared seasonal cycle so the deep (GWL) and shallow (ET) zones stiffen together in the dry
    # season: season = +1 at the late-summer dry peak (fraction DRY_PEAK of a hydrologic year),
    # -1 in the wet winter half. Deep = drying trend + seasonal; shallow = seasonal ET + AR(1) storms.
    season = np.cos(2.0 * np.pi * (t / T - DRY_PEAK))          # +1 dry/stiff, -1 wet/soft
    s_deep = gwl_trend * (t / T) + gwl_seasonal * season
    et = et_seasonal * season
    e = np.zeros(n_epoch)
    for k in range(1, n_epoch):
        shock = -storm_amp if rng.rand() < storm_rate else 0.0  # storms wet -> soften (negative)
        e[k] = ar1_rho * e[k - 1] + shock
    s_shallow = et + e

    m_zt = w_shal[:, None] * s_shallow[None, :] + w_deep[:, None] * s_deep[None, :]
    return m_zt, t


def forward_banded_dvv(m_zt, kernels):
    """Forward the depth-time truth through the band kernels: dv/v_b(t) = G[b,:] @ m(:,t).

    ``kernels`` is a codameter ``DepthKernels`` (G is area-normalized, so each band's dv/v is the
    depth-weighted mean of m over that band's sensitivity). Returns (n_band, n_epoch).
    """
    return np.asarray(kernels.G) @ np.asarray(m_zt)


def synthesize_banded_ncfs(dvv_bt, bands=DEFAULT_BANDS, sr=25.0, maxlag=60.0, noise=0.05, seed=1):
    """Per-epoch NCF series whose band-filtered coda is stretched by dv/v_b(t) (recovery loop).

    Returns (lags, ref, series[n_epoch, n_lag]) consumable by measure_banded_dvv /
    processing_ensemble_dvv, which then recover BAND-SPECIFIC dv/v. ``ref`` is the unstretched
    broadband template (epoch reference).
    """
    dvv_bt = np.atleast_2d(dvv_bt)
    n_band, n_epoch = dvv_bt.shape
    rng = np.random.RandomState(seed)
    lags = np.arange(-int(maxlag * sr), int(maxlag * sr) + 1) / sr
    env = np.exp(-np.abs(lags) / 20.0)
    b_lo, b_hi = 0.1, 8.0
    sos_bb = signal.butter(4, [b_lo, b_hi], btype="band", fs=sr, output="sos")
    ref = signal.sosfiltfilt(sos_bb, rng.randn(lags.size)) * env
    band_sos = [signal.butter(4, [f1, f2], btype="band", fs=sr, output="sos") for f1, f2 in bands]
    ref_bands = [signal.sosfiltfilt(s, ref) for s in band_sos]

    series = np.empty((n_epoch, lags.size))
    for ei in range(n_epoch):
        acc = np.zeros(lags.size)
        for bi in range(n_band):
            eps = float(dvv_bt[bi, ei])
            acc += np.interp(lags, lags * (1.0 + eps), ref_bands[bi])
        acc += noise * signal.sosfiltfilt(sos_bb, rng.randn(lags.size)) * env
        series[ei] = acc
    return lags, ref, series


def synthetic_station_dvv(station_lon, station_lat, kernels, n_epoch=73, dt_days=5.0,
                          water_table_km=0.03, seed=0, **truth_kwargs):
    """Per-station banded dv/v with coherent-but-distinct spatial modulation (feeds the twin).

    Deep GWL amplitude scales with a normalized longitude gradient (regional recharge), shallow
    storm amplitude with a latitude gradient, plus a per-station seed offset. Returns dict with
    ``dvv_bt`` (n_sta, n_band, n_epoch), ``m_zt`` (n_sta, n_depth, n_epoch), ``t_days``,
    ``f_center_hz`` (from kernels), and ``depths_km``.
    """
    lon = np.asarray(station_lon, dtype="float64")
    lat = np.asarray(station_lat, dtype="float64")
    n_sta = lon.size
    glon = (lon - lon.mean()) / (np.ptp(lon) or 1.0)
    glat = (lat - lat.mean()) / (np.ptp(lat) or 1.0)
    z = np.asarray(kernels.depths_km, dtype="float64")
    fc = np.asarray(kernels.frequencies_hz, dtype="float64")

    dvv_bt = np.empty((n_sta, len(fc), n_epoch))
    m_all = np.empty((n_sta, z.size, n_epoch))
    t_days = None
    for i in range(n_sta):
        m, t_days = synthetic_depth_time_truth(
            z, n_epoch=n_epoch, dt_days=dt_days, water_table_km=water_table_km,
            gwl_seasonal=1.5e-3 * (1.0 + 0.6 * glon[i]),
            storm_amp=3.0e-3 * (1.0 + 0.6 * glat[i]),
            seed=seed + i, **truth_kwargs)
        m_all[i] = m
        dvv_bt[i] = forward_banded_dvv(m, kernels)
    return dict(dvv_bt=dvv_bt, m_zt=m_all, t_days=t_days, f_center_hz=fc, depths_km=z)


def top_layer_mean_dvv(profile_zt, depths_km, top_km=0.03):
    """Depth-average dVs/Vs over 0..top_km. Accepts (n_depth,) or (n_depth, n_epoch)."""
    z = np.asarray(depths_km, dtype="float64")
    p = np.asarray(profile_zt, dtype="float64")
    mask = z <= top_km
    if not mask.any():
        mask = z <= np.min(z) + 1e-9                          # at least the shallowest node
    return p[mask].mean(axis=0)


def dvv_to_vs30_change(dvv_top30, dvv_top30_std=None):
    """Top-0-30 m mean dVs/Vs -> fractional Vs30 change. Vs30(t) = baseline * (1 + frac).

    Unit sensitivity (a fractional velocity change is a fractional Vs30 change). Returns
    (frac, frac_std). A shallow stiffening (positive dVs/Vs) raises Vs30.
    """
    frac = np.asarray(dvv_top30, dtype="float64")
    std = None if dvv_top30_std is None else np.abs(np.asarray(dvv_top30_std, dtype="float64"))
    return frac, std
