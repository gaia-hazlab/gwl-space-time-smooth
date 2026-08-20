# Can the assimilation avoid forming dense `C`? — a ground-truth benchmark of A vs B

**Status:** evaluation only. **Nothing merged.** PRs #215 (B) and #216 (A) remain open and labelled
`needs-human-decision`.
**Harness:** [`scripts/bench_prior_operator.py`](../../scripts/bench_prior_operator.py) — extracts A
and B from their commits at runtime (`git show <sha>:path`), so neither branch is checked out or merged.

---

## 1. The current covariance / BLUE call path, and where dense `C` is materialised

There is exactly **one** place, and every caller routes through it:

| Step | Location |
|---|---|
| dense `C` is built | [`GaussianPrior.cov()`](../../src/models/observability.py#L112) — `d = sqrt(sum((c[:,None,:] - c[None,:,:])**2, -1))` then `matern_correlation(d, L, nu) * mask`, returning `(n, n)` |
| consumed by | [`resolution()`](../../src/models/observability.py#L381), [`blue_update()`](../../src/models/observability.py#L406), `marginal_resolution()` — each does `C = np.asarray(prior_cov)` |
| production caller | [`notebooks/make_twin_gif.py:107-108`](../../notebooks/make_twin_gif.py#L107-L108) — `B_gwl = GaussianPrior(SIG_GWL, L_GWL).cov(coords)` on the **coarse** grid, then `blue_update(B_gwl, …)` at :197 / :213 |
| figure callers | `make_observability_figure.py:161-162`, `make_observing_system_figure.py:91-92`, `make_checkerboard_test.py:146-147`, `make_static_resolution_figure.py` |

Two things worth recording about the production path:

- The coarse grid exists **solely** because `cov()` is dense: `STEP=8 × AFAC=5` → a 3.6 km analysis
  grid, solved, then `upsample()`d linearly to 90 m ([`make_twin_gif.py:167-171`](../../notebooks/make_twin_gif.py#L167-L171)).
- **`region_id` is not used in production.** `GaussianPrior(SIG_GWL, L_GWL)` passes no `region_id`, so
  the twin currently runs a stationary isotropic Matérn with no drainage-divide masking. The
  terrain-awareness delivered by PR #181 is available but unwired. This matters for judging A, whose
  cost is `O(K n log n)` in the number of regions `K`: at `K = 1` that factor is absent today.

### Dense `C` is not required

`resolution()` and `blue_update()` use `C` only through three quantities:

```
diag(C)              -> sigma**2 exactly, for a stationary prior (verified: max|diag - sigma^2| = 0)
Bx = C @ G.T         -> (n, n_obs)
S  = G @ Bx + R      -> (n_obs, n_obs)
```

with `m_post = m0 + Bx @ solve(S, d - G @ m0)` and
`diag(C_post) = diag(C) - einsum('ij,ji->i', Bx, solve(S, Bx.T))`. At n = 2.96 M and 100 observations,
`Bx` is 2.4 GB while `C` is 70 TB. **The dense matrix is an implementation artefact, not a requirement.**

## 2. Proposed minimal operator-form refactor

PR #216 (A) **already contains this refactor**, separably from its FFT backend. It is ~15 lines:

```python
def _as_prior(P):
    if isinstance(P, np.ndarray):
        return np.asarray(P, dtype="float64")     # legacy dense path, byte-identical
    if hasattr(P, "diagonal") and hasattr(P, "__matmul__") and hasattr(P, "shape"):
        return P                                   # matrix-free backend
    return np.asarray(P, dtype="float64")
```

`resolution()` / `blue_update()` then swap `np.asarray(prior_cov)` for `_as_prior(prior_cov)` and use
`C.diagonal()` instead of `np.diag(C)`. The protocol is **`.shape`, `.diagonal()`, `__matmul__`** —
which `np.ndarray` already satisfies, so no existing caller changes behaviour.

This is the right seam, and it is independent of which backend wins: it admits a dense array (tests),
an FFT operator (A), a sparse-precision operator (B), or a kernel-direct operator, without further
changes to the estimator.

## 3. The benchmark

[`scripts/bench_prior_operator.py`](../../scripts/bench_prior_operator.py). Native-90-m subdomain,
`y` descending (the north-up convention every caller uses). Four implementations of the same
quantities:

| name | what it is |
|---|---|
| `dense` | production `GaussianPrior.cov()`, ν=1.5. **Reference only** |
| `direct` | minimal operator form written for this study: `C @ G.T` by Matérn evaluation over each footprint's support. Never forms `C`. ν=1.5 exact |
| `A` | `GaussianPrior.operator()` → `StationaryGridPrior` from commit `658493d` (PR #216) |
| `B` | `SparseMaternPrior` from commit `2414434` (PR #215), ν=1 |

Region geometry is deliberately **not axis-aligned** — a sinusoidally-perturbed partition, since an
axis-aligned split would be an unrealistically easy case for a Toeplitz/FFT representation. The
observation set covers all five required cases: a point interior to a region, a point adjacent to a
region boundary, one point per region, a single-station dv/v coda kernel, and a station-pair kernel
straddling a region boundary.

### Verified: the `length_km` convention

Before comparing anything, the module's Matérn was checked against the analytic form. With
`x = sqrt(2ν)·d/L`, `matern_correlation` agrees with `2^(1-ν)/Γ(ν)·x^ν·K_ν(x)` to **6.66e-16**. So
`length_km` is the standard Matérn **range** parameter (not an e-folding length, not a practical
range): at ν=1.5, `corr(L) = (1+√3)e^(-√3) = 0.483`.

### Measured: footprint support — this decides direct-vs-FFT

Effective support = smallest set of cells carrying 99.9% of footprint mass (25,600-cell domain):

| footprint | nnz | eff. support | eff. % |
|---|---|---|---|
| point sensor, interior | 25,600 | 1,282 | **5.0%** |
| point sensor, at region boundary | 25,600 | 1,340 | **5.2%** |
| dv/v single-station coda | 25,600 | 25,196 | **98.4%** |
| dv/v station pair, crosses boundary | 25,600 | 25,485 | **99.6%** |

Two consequences:

1. **Point sensors are compact and stay compact.** ~1,300 cells is set by `point_footprint`'s
   `width_km=0.5` (≈3.7σ radius ≈ 20 cells ⇒ π·20² ≈ 1,257), *independent of n*. Direct kernel
   evaluation costs `n × 1,300` — linear in n, and the obvious method for wells and SNOTEL.
2. **dv/v footprints cover the domain.** Diffuse-coda kernels are broad by construction, so direct
   evaluation costs `n × n` per observation — i.e. the dense cost, per datum. For the volume sensors
   that are the twin's entire rationale, **a fast transform is not an optimisation, it is required.**

Note also that `nnz` is the full grid for every footprint: `point_footprint` is a Gaussian that never
underflows to exactly zero on a domain this small, so a `g != 0` support test is meaningless. Any
direct implementation must therefore **truncate** at a mass tolerance — a controlled approximation
that A, being exact, does not need.

> **Correction (2026-08-19).** The paragraph above was right, and the benchmark script did not do it.
> `cross_direct` took its support from `np.nonzero(g)`, which on the real 90 m km-grid is **100% of
> the domain** at every size this study used (86% at 400×400, where the tail finally underflows). So
> every `direct` timing in §4 below was measured on an untruncated implementation — precisely the one
> this paragraph says nobody should write. Found by Copilot review on PR #217.
>
> The script now truncates by mass. `effective_support(g, mass_tol)` keeps the smallest cell set
> carrying all but `mass_tol` of the footprint's absolute mass. The error is **bounded, not
> heuristic**: since `Bx[:,i] = σ² Σ_j corr(x,x_j) g_j` and `|corr| ≤ 1`, dropping a set `D` changes
> the result by at most `σ² Σ_{j∈D} |g_j| ≤ σ²·mass_tol`. At the default `mass_tol = 1e-12` and
> σ = 0.5 that is 2.5e-13 — measured max deviation 1.85e-13, i.e. the bound holds and is tight.
>
> Re-measured on the same 25,600-cell domain and the same 7 observations: mean effective support
> 76.7% → 42.1%, and `C @ G.T` **147.4 s → 81.6 s (1.81×)**. The residual 42% is the two dv/v
> footprints, which genuinely do cover the domain — which is the finding of §3, now measured on an
> implementation that matches its own description. The speedup grows with domain size, because the
> truncated point-sensor support is a constant ~5,363 cells while `nnz` was `n`:
>
> | domain | cells | `nnz` support | truncated support | ratio |
> |---|---|---|---|---|
> | 60×60 | 3,600 | 100.0% | 98.9% | 1.0× |
> | 100×100 | 10,000 | 100.0% | 53.6% | 1.9× |
> | 160×160 | 25,600 | 100.0% | 21.0% | 4.8× |
> | 260×260 | 67,600 | 100.0% | 7.9% | 12.6× |
> | 400×400 | 160,000 | 86.2% | 3.4% | 25.7× |
>
> **No conclusion in this report changes.** A is still exact and still orders of magnitude faster;
> `direct` still degenerates on volume footprints, which is the whole argument. What changes is that
> the `direct` column is now an honest measurement of the method §3 describes, rather than an upper
> bound from a method §3 rules out. The §4 tables below are left at their original values and are
> superseded by this note for the `direct` row only.

## 4. Numerical comparison

Primary metric is `C @ G.T`, as required. 25,600-cell native-90-m domain, 3 non-axis-aligned regions,
7 observations. `relFro = ||B_x - B_dense||_F / ||B_dense||_F`.

**Config 2 — L = 2 km (domain spans 7.2 correlation lengths; the regime where boundary effects are
properly exercised and B has a stationary interior):**

| impl | relFro(`C G^T`) | maxabs | relFro(m_post) | relFro(res) | t(`C G^T`) |
|---|---|---|---|---|---|
| dense | 0 | 0 | 0 | 0 | 0.199 s |
| `direct` | 2.872e-16 | 1.665e-16 | 2.862e-15 | 5.428e-16 | 195.3 s |
| **A** | **3.148e-16** | 2.220e-16 | 2.906e-15 | 5.678e-16 | **0.048 s** |
| **B** (default) | **5.688e-01** | 1.484e-01 | 5.134e-01 | 1.250e-01 | 0.091 s |
| **B** (`standardize=True`) | **1.009e-01** | 2.243e-02 | 7.698e-02 | 8.467e-02 | **2.127 s** |

> **Timing methodology.** All timings in this report are from a **single sequential run** on an idle
> machine. An earlier parallel run of the same configurations produced inflated and inconsistent
> timings under CPU/memory contention (B-with-`standardize` measured 106.8 s there against 2.127 s
> here — a 50× artefact). Accuracy figures were unaffected; only wall-clock was. Timings below n = 1e6
> are single-shot, not best-of-N, so treat sub-second values as indicative to ~±50%.

**Config 1 — L = 12 km (production prior), 25,600 cells, all four implementations:**

| impl | relFro(`C G^T`) | maxabs | relFro(m_post) | relFro(res) | t(`C G^T`) |
|---|---|---|---|---|---|
| dense | 0 | 0 | 0 | 0 | 0.110 s |
| `direct` | **2.679e-16** | 2.498e-16 | 6.626e-15 | 4.507e-16 | **195.4 s** |
| **A** | **2.800e-16** | 2.498e-16 | 6.813e-15 | 4.673e-16 | **0.252 s** |
| B | 1.411e+01 | 3.173e+00 | 6.172e-01 | 3.336e-01 | 0.186 s |

**`direct` and A agree with dense to the same 2.7e-16 — and A is 776× faster** (≈430× against the
truncated `direct`; see the correction in §3, and note the two runs are on different machine loads,
so treat the ratio rather than the absolute seconds as the comparable quantity). `direct`'s cost is
also **independent of L** (195.4 s at L=12 km, 195.3 s and 192.1 s at L=2 km), confirming that it is
set by footprint support and not by the correlation length. The direct form
degenerates to dense cost here because the two dv/v footprints have ~99% support (§3): its 195 s is
`O(n·|supp|) ≈ O(n²)` for those two observations alone. This is the measured version of the
support argument, not an inference from it.

(B's 1.411e+01 at this configuration is the sub-correlation-length regime — the domain is 1.2 L
across — where its reflecting-boundary inflation is at its worst; see §7.)

The dense reference cost **32.1 s and 30.8 GB peak at only 25,600 cells** (the `(n, n, 2)` broadcast
in `cov()`), against A's 0.080 s and no build step at all.

### A reproduces the dense ν=1.5 prior exactly

Per-observation, config 2:

| # | kind | relFro | maxabs | note |
|---|---|---|---|---|
| 0 | point | 3.001e-16 | 1.388e-16 | interior of a region |
| 1 | point | 3.144e-16 | 8.327e-17 | **adjacent to a region boundary** |
| 2–4 | point | 3.001–3.495e-16 | ≤2.220e-16 | one per region |
| 5 | dvv | 2.755e-16 | 5.551e-17 | single-station coda |
| 6 | dvv | 2.683e-16 | 8.327e-17 | **station pair crossing a region boundary** |

Every case is at double-precision round-off — six orders of magnitude tighter than the 1e-10 threshold
set for investigation. **A's "exact to double precision" claim is confirmed**, in both the
sub-correlation-length and the 7.2-correlation-length regime, including the boundary-crossing volume
footprint.

## 5. Runtime and memory, and A's `region_id` scaling (the flagged risk, measured)

`C @ G.T` for 20 point observations, A only, no dense reference:

| n | domain | dense `C` would be | K=1 | K=2 | K=4 | K=8 | K=16 | K=32 | s / region-pass |
|---|---|---|---|---|---|---|---|---|---|
| 102,400 | 28.8 km | 0.08 TB | 0.07 s | 0.14 s | 0.29 s | 0.63 s | 1.19 s | 2.39 s | **0.07** |
| 409,600 | 57.6 km | 1.34 TB | 0.21 s | 0.55 s | 1.08 s | 2.15 s | 4.35 s | 8.69 s | **0.27** |
| 1,000,000 | 90.0 km | 8.00 TB | 0.55 s | 1.34 s | 2.48 s | 5.17 s | 11.65 s | 21.18 s | **0.65** |

Cost is **exactly linear in K** at every n — a flat per-pass cost, no superlinear blow-up, no pathology.
Scaling in n is very close to linear in practice (4× n → 3.9× time; 2.44× n → 2.4× time), i.e. the
`log n` factor is barely visible against FFT sizing and threading.

Extrapolating one step from the measured n = 1,000,000 row (a 2.96× step to the full 2,960,063-cell
domain) gives ≈2.0 s per region-pass, so for a full-domain `C @ G.T` with 20 observations:

* K = 1 (production today): **~2 s**
* K = 32 basins: **~63 s**
* K = 100 basins: **~200 s**

All tractable for a monthly product. **The `O(K n log n)` concern is real but benign**, and does not
overturn the recommendation. The contrast is stark at the measured end: at n = 1,000,000 with 32
regions A completes in **21 s**, where the dense `C` it replaces would be **8 TB**.

Memory: A holds `(n, n_obs)` plus one padded FFT workspace. The 30.8 GB peaks in the comparison tables
are the **dense reference's** allocation, not A's — A alone never exceeded ~1 GB in the K-scaling runs
above, which build no dense matrix at all.

## 6. Why A does *not* fail — the mechanism, from the code

The specific failure modes to look for were checked in the source, not inferred from the result:

| failure mode | finding |
|---|---|
| cyclic wraparound / periodic covariance | **Absent by construction.** `py, px = next_fast_len(2*ny - 1), next_fast_len(2*nx - 1)` — full linear-convolution padding. Circular convolution on a ≥2N−1 grid *is* linear convolution |
| insufficient zero padding | `buf = np.zeros((m, py, px)); buf[:, :ny, :nx] = cols` — explicit zero pad, result cropped back to `[:ny, :nx]` |
| eigenvalue clipping / negative-eigenvalue modification | **None.** `_khat = rfft2(k)` is used only as a multiplier: `f *= self._khat`. No `abs`, no `clip`, no `maximum`, no square root |
| kernel truncation | None — the kernel is evaluated on the full padded lag grid `min(a, p−a)` |
| changed Matérn normalisation | Same `matern_correlation` function as `main`; verified against the analytic form at 6.66e-16 |
| `region_id` handling | Applied as a partition-identity weighting, K FFT passes; the boundary-adjacent and boundary-crossing observations show no elevated error |

This is exactly the benign case of circulant embedding. The embedding's eigenvalues **may** be negative,
and it does not matter: A never treats the embedding as a covariance, never samples from it, and never
takes its square root. It uses the FFT solely as an exact zero-padded Toeplitz matvec. A's own docstring
concedes the corresponding limitation — no sampling, no cross-cell posterior covariance.

## 7. B: quantifying the ν change separately from the boundary artifact

These must not be conflated, and they turn out to be very different in size.

**(a) The ν = 1.5 → 1 model change alone** (analytic, implementation-independent, same σ and L):

| | max\|ΔC\| (corr. units) | 50% range | 20% range | 5% range |
|---|---|---|---|---|
| ν=1.5 → ν=1.0 | **0.0538** | −8.2% | −1.7% | +3.1% |

Scale-invariant (identical at L = 12, 8 and 2 km). **This is a modest change** — the half-correlation
range shrinks 8%, tails move by a few percent. On its own it would be a defensible modelling choice
requiring a physical argument, not a disqualification.

**(b) The SPDE reflecting-boundary / small-region artifact** is the dominant term, and it is large:

| config | domain | B marginal variance vs σ²=0.25 |
|---|---|---|
| L=2 km, 3 regions | 7.2 L across | mean 0.446 (**1.78×**), min 0.277, max 1.877 (**7.5×**), spread **358%** |
| L=12 km, 3 regions | 0.45 L across | mean 24.2 (**97×**) |

**(c) With B's own remedy applied (`standardize=True`)** the marginal variance is exactly σ² everywhere
(mean = min = max = 0.25, spread **0.00%**) and the discrepancy against the ν=1.5 dense reference falls
from 57% to **10.1%** (m_post 7.7%, resolution 8.5%) — consistent with the ν change plus SPDE
discretisation, i.e. the irreducible *model* difference once the artifact is removed.

It costs **2.127 s versus A's 0.048 s — a factor of ~46** — because standardisation needs the marginal
variance everywhere, which is `n` solves or a Monte-Carlo estimate. So B's cheap path is the inaccurate
one and its accurate path is ~46× slower than A, at 25,600 cells. That is a real gap but a far smaller
one than a contended earlier measurement suggested (see the timing note in §4); it is a cost
consideration, not a disqualification on its own.

B warns about this itself at construction (predicting ×95.6 for regions below one practical range
squared, ×1.95 at a straight edge, ×3.83 at a corner) and offers `standardize=True` as the remedy.

**So B's 57% discrepancy is overwhelmingly boundary/region geometry, not ν.** σ in this model is a
calibrated physical quantity (0.5 m of water-table anomaly); a prior that silently inflates it by 1.8×
on average and 7.5× at corners is not usable without `standardize=True`, and the regions in the real
domain are drainage basins — many of which *are* smaller than one practical range at L = 12 km.

## 8. Reconciling the cell counts

All three figures are traceable; two are right for different domains and one is wrong.

| Figure | Where | Verdict |
|---|---|---|
| **2,960,063** cells (1567 × 1889), dense **70.1 TB** | issue #154; PR #216's benchmark table | **Correct** for the current **v0.4** domain: `src/config/domain.py` bounds `(-2005000, 2892000, -1864000, 3062000)`, 141 × 170 km at 90 m |
| **922,675** cells (835 × 1105), dense **6.8 TB** | the figure quoted in this task | The **legacy** grid (`terrain_hand_90m.tif` bounds). Superseded by v0.4 in issue #92; `domain.py` documents the extension as "3.2× the legacy 0.92 M" and `assert_on_grid()` exists specifically to stop the two being mixed |
| **~1e7** cells, dense **~800 TB** | PR #215 (B) | **Wrong.** Matches no grid in the repo — ~3.4× too many cells and ~11× too many bytes. It overstates the problem B is solving |

**Provenance of the ~1,900-cell coarse grid.** `STEP × AFAC = 40` cells = 3.60 km, and `sub` is the
whole template (`tmpl.isel(y=slice(None,None,STEP), x=…)`), so:

* v0.4 grid: `ceil(1567/40) × ceil(1889/40)` = 40 × 48 = **1,920** ✓ matches "~1,900"
* legacy grid: `ceil(835/40) × ceil(1105/40)` = 21 × 28 = **588** ✗

So the ~1,900 figure is derived from the **current 2.96 M grid**, and the 40× / 1600× arithmetic in the
task is right: it is 40× coarser per axis, ~1600× fewer cells by area.

**Not silently fixed.** PR #215's size claim is left as-is in its branch; this note is the record.

## 9. Recommendation

**Adopt the operator protocol, keep ν = 1.5, and take A's FFT backend. Do not adopt B as the
production prior on scalability grounds.**

The three questions, kept separate:

**Statistical model — what covariance do we intend?** Matérn ν = 1.5, σ and L as calibrated, with
`region_id` masking available. This is what `main` has had since PR #181, and nothing in this
benchmark argues for changing it. B changes it (ν = 1) not because the physics asked but because a
*local* sparse precision does not exist in 2-D at ν = 1.5. **Changing the statistical model to obtain
convenient algebra is the wrong trade when an exact representation of the intended model exists** —
and A demonstrably is one.

**Numerical representation — how do we apply C without forming it?** Settled: `diag(C)`, `C G^T`, and
`G C G^T + R` are all the estimator needs; dense `C` is an artefact. The protocol
(`.shape` / `.diagonal()` / `__matmul__`, with `np.ndarray` already conforming) is the right seam, and
it is backend-agnostic.

**Scientific resolution — what scales are actually constrained?** *Not settled here, and not settleable
by this benchmark.* Removing the dense-`C` limit lets the solve run at 90 m; it does **not** follow that
the result resolves 90 m structure. With L = 12 km and a few hundred sensors, the constrained scale is
set by L and by sensor geometry, not by the grid. That question needs a separate resolution/checkerboard
study, and until it is done the product should not be described as 90 m resolution merely because it is
posted on a 90 m raster.

### Ranked

1. **Operator protocol + A's `StationaryGridPrior`.** A is exact (3.1e-16), needs no dense build,
   and is the only candidate that preserves the intended prior. Its architectural half — `_as_prior`
   and the protocol — is worth taking on its own merits and is what makes any future backend cheap to
   add. Note the two questions were never really separate: **PR #216 already contains the operator
   refactor**, so "prefer the operator form over A" is a false choice.
2. **Add a kernel-direct fast path later, if profiling justifies it.** Measured support says point
   sensors touch ~5% of cells (≈1,300, independent of n) — for wells and SNOTEL, direct evaluation is
   `O(n·1300)` and plausibly beats an FFT. But dv/v coda kernels touch **98–99.6%** of cells, so for
   the volume sensors that are the twin's whole rationale, direct evaluation is `O(n²)` per datum and
   the transform is mandatory. A direct path is also only cheap if the footprint is **truncated** at a
   mass tolerance — an approximation A does not need. This is an optimisation, not an architecture.
3. **B — not as the production prior.** Its 57% discrepancy is mostly boundary/region artifact, not ν:
   with `standardize=True` the marginal variance becomes exactly σ² and the residual model difference
   is 10.1%. That correct configuration costs **2.127 s against A's 0.048 s (~46×)** at 25,600 cells,
   because standardisation requires the marginal variance everywhere. The decisive objection to B is
   therefore **not** speed but that it does not represent the intended prior (10.1% off, ν=1 not 1.5)
   and needs `standardize=True` plus ≥1 practical range of padding to avoid a large variance artifact —
   while real drainage basins are frequently smaller than one practical range at L = 12 km, which is
   exactly where that artifact is worst. Its stated problem
   size (~1e7 cells / ~800 TB) is wrong by ~3.4× / ~11×. **This is not a rejection of GMRF/SPDE as
   an idea** — it remains the right tool if the domain later needs genuine nonstationarity, unstructured
   meshes, or a joint space-time precision, none of which A can do. It should be reconsidered on those
   merits, with an independent physical argument for ν, not adopted now for sparsity.

### Caveats on this recommendation

- A **requires a complete uniform raster.** The production domain is one today, but a masked/irregular
  analysis domain would break it; it raises rather than silently approximating, which is the right
  failure mode.
- A's cost is `O(K n log n)` in the number of regions — **measured to n = 1,000,000 (§5), and
  benign**: exactly linear in K at every size, ~0.65 s per pass at n = 1e6, extrapolating to ~2 s
  (K=1) to ~200 s (K=100 basins) for a full-domain `C @ G.T`. `region_id` is unused in production today
  (`make_twin_gif.py` builds `GaussianPrior(SIG, L)` with no regions), so K = 1.
- A supplies no sampling and no cross-cell posterior covariance. Nothing in the current estimator needs
  either; an ensemble/UQ workflow later would.

### Next step

Wire A into `make_twin_gif.py` behind the operator protocol, drop `STEP`/`AFAC`, and run the full
2,960,063-cell domain once with the real `region_id` raster to confirm the §5 extrapolation end-to-end.
Then — separately, and before any resolution claim is made — run a checkerboard/resolution study to
establish what spatial scales the sensor network actually constrains at L = 12 km. Those are different
questions and the second is the one that governs how the product may be described.
