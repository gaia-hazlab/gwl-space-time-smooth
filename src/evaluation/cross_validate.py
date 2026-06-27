"""Spatial block cross-validation utilities for GWL models.

Always use spatial block CV (verde.BlockShuffleSplit) for GWL/spatial data.
Random CV inflates R² by 0.1–0.3 due to spatial autocorrelation between
nearby wells that end up in both train and test sets.
"""

from __future__ import annotations

import logging
from typing import Iterator

import numpy as np
import pandas as pd
from verde import BlockShuffleSplit

logger = logging.getLogger(__name__)

# Defaults matching modeling-approaches.md
DEFAULT_SPACING_M = 200_000   # 200 km blocks
DEFAULT_N_SPLITS = 5


def spatial_block_cv(
    X: np.ndarray,
    y: np.ndarray,
    coords_5070: np.ndarray,
    spacing_m: float = DEFAULT_SPACING_M,
    n_splits: int = DEFAULT_N_SPLITS,
    random_state: int = 0,
) -> dict[int, dict]:
    """Evaluate a model with spatial block cross-validation.

    Parameters
    ----------
    X:
        Feature matrix (n_samples, n_features).
    y:
        Target vector (n_samples,).
    coords_5070:
        (n_samples, 2) array of (easting, northing) in EPSG:5070 metres.
    spacing_m:
        Block size in metres (default 200 km).
    n_splits:
        Number of CV folds.
    random_state:
        RNG seed.

    Returns
    -------
    dict
        {fold_index: {"train_idx", "test_idx", "n_train", "n_test"}}
        Indices are into the original arrays.
    """
    splitter = BlockShuffleSplit(
        spacing=spacing_m,
        n_splits=n_splits,
        random_state=random_state,
    )
    coordinates = (coords_5070[:, 0], coords_5070[:, 1])  # (easting, northing)

    folds = {}
    for fold_idx, (train_idx, test_idx) in enumerate(
        splitter.split(coordinates, y)
    ):
        folds[fold_idx] = {
            "train_idx": train_idx,
            "test_idx": test_idx,
            "n_train": len(train_idx),
            "n_test": len(test_idx),
        }
        logger.debug(
            "Fold %d: %d train / %d test", fold_idx, len(train_idx), len(test_idx)
        )

    return folds


def run_cv_metrics(
    estimator,
    X: np.ndarray,
    y: np.ndarray,
    coords_5070: np.ndarray,
    spacing_m: float = DEFAULT_SPACING_M,
    n_splits: int = DEFAULT_N_SPLITS,
) -> dict:
    """Fit and evaluate an estimator with spatial block CV; return metric summary.

    Parameters
    ----------
    estimator:
        sklearn-compatible estimator with fit() and predict().
    X, y, coords_5070:
        Features, target, coordinates (see spatial_block_cv).
    spacing_m, n_splits:
        Block CV parameters.

    Returns
    -------
    dict
        {"rmse_mean", "rmse_std", "mae_mean", "mae_std", "bias_mean",
         "r2_mean", "r2_std", "folds": {fold: per-fold metrics}}
    """
    from sklearn.metrics import mean_absolute_error, r2_score

    folds = spatial_block_cv(X, y, coords_5070, spacing_m, n_splits)
    fold_metrics = {}

    for fold_idx, fold in folds.items():
        X_tr, y_tr = X[fold["train_idx"]], y[fold["train_idx"]]
        X_te, y_te = X[fold["test_idx"]], y[fold["test_idx"]]

        from sklearn.base import clone
        est = clone(estimator) if hasattr(estimator, "get_params") else estimator
        est.fit(X_tr, y_tr)
        y_pred = est.predict(X_te)

        residuals = y_te - y_pred
        rmse = float(np.sqrt(np.mean(residuals ** 2)))
        mae = float(mean_absolute_error(y_te, y_pred))
        bias = float(np.mean(residuals))
        r2 = float(r2_score(y_te, y_pred))

        fold_metrics[fold_idx] = {
            "rmse": rmse,
            "mae": mae,
            "bias": bias,
            "r2": r2,
            "n_test": fold["n_test"],
        }
        logger.info(
            "Fold %d: RMSE=%.2f m  MAE=%.2f m  bias=%.2f m  R²=%.3f  (n=%d)",
            fold_idx, rmse, mae, bias, r2, fold["n_test"],
        )

    rmse_vals = [v["rmse"] for v in fold_metrics.values()]
    mae_vals = [v["mae"] for v in fold_metrics.values()]
    bias_vals = [v["bias"] for v in fold_metrics.values()]
    r2_vals = [v["r2"] for v in fold_metrics.values()]

    summary = {
        "rmse_mean": float(np.mean(rmse_vals)),
        "rmse_std": float(np.std(rmse_vals)),
        "mae_mean": float(np.mean(mae_vals)),
        "mae_std": float(np.std(mae_vals)),
        "bias_mean": float(np.mean(bias_vals)),
        "r2_mean": float(np.mean(r2_vals)),
        "r2_std": float(np.std(r2_vals)),
        "folds": fold_metrics,
    }
    logger.info(
        "Spatial CV summary: RMSE=%.2f±%.2f m  R²=%.3f±%.3f  bias=%.2f m",
        summary["rmse_mean"], summary["rmse_std"],
        summary["r2_mean"], summary["r2_std"],
        summary["bias_mean"],
    )
    return summary
