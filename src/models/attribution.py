"""Statistical-learning attribution: which features explain each state (not just which sensor).

The precision-weighted assimilation attributes only the near-station *update* to its sensors, so a
state whose sole assimilated observation is dv/v reads as ~100% dv/v even though its field is really
set by covariates (e.g. Vs30 is terrain-driven; dv/v only anchors variation near seismic stations).

This module answers the field-level question with a random forest across ALL features -- the static
covariates (HAND, TWI, slope, clay, sand, the state's own baseline) plus the dv/v observation -- and
reports permutation importance. It shows covariates dominating where they should (Vs30) while giving
dv/v credit only where it adds information beyond the covariates. As real covariate/dv/v relations
are learned, the same call generalizes the dv/v signal beyond station neighborhoods.
"""

from __future__ import annotations

import numpy as np


def feature_attribution(target, features, sample=20000, n_estimators=200, max_depth=12,
                        n_repeats=5, seed=0):
    """Permutation feature importance of a random forest predicting ``target`` from ``features``.

    ``target``: 2-D field. ``features``: dict name -> 2-D field on the same grid. Cells finite in
    the target and all features are used (subsampled to ``sample`` for speed). Returns dict
    name -> importance share (non-negative, sums to 1), most-informative feature largest. If no
    feature is informative (all permutation importances <= 0) the shares are equal (undetermined).
    """
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.inspection import permutation_importance

    names = list(features)
    y = np.asarray(target, dtype="float64").ravel()
    X = np.stack([np.asarray(features[n], dtype="float64").ravel() for n in names], axis=1)
    ok = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    y, X = y[ok], X[ok]
    if y.size < 50:
        return {n: float("nan") for n in names}
    rng = np.random.RandomState(seed)
    if y.size > sample:
        idx = rng.choice(y.size, sample, replace=False)
        y, X = y[idx], X[idx]
    rf = RandomForestRegressor(n_estimators=n_estimators, max_depth=max_depth,
                               min_samples_leaf=5, n_jobs=-1, random_state=seed)
    rf.fit(X, y)
    imp = permutation_importance(rf, X, y, n_repeats=n_repeats, random_state=seed, n_jobs=-1)
    vals = np.clip(imp.importances_mean, 0.0, None)
    total = vals.sum()
    if total <= 0:                                           # nothing informative -> undetermined
        return {n: 1.0 / len(names) for n in names}
    return {n: float(v / total) for n, v in zip(names, vals)}
