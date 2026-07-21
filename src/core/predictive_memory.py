"""Leakage-controlled linear prediction utilities for memory candidates."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class RidgeModel:
    continuous: list[str]
    categorical: list[str]
    categories: dict[str, list[str]]
    means: np.ndarray
    scales: np.ndarray
    coefficients: np.ndarray


def _matrix(df: pd.DataFrame, model: RidgeModel) -> np.ndarray:
    continuous = df[model.continuous].to_numpy(float)
    continuous = (continuous - model.means) / model.scales
    columns = [np.ones((len(df), 1), dtype=float), continuous]
    for name in model.categorical:
        values = df[name].astype(str).to_numpy()
        # First level is the reference category.
        for level in model.categories[name][1:]:
            columns.append((values == level).astype(float)[:, None])
    return np.hstack(columns)


def fit_ridge(
    df: pd.DataFrame,
    target: str,
    continuous: list[str],
    categorical: list[str],
    alpha: float,
) -> RidgeModel:
    if alpha < 0:
        raise ValueError("alpha must be non-negative")
    values = df[continuous].to_numpy(float)
    if not np.isfinite(values).all() or not np.isfinite(df[target].to_numpy(float)).all():
        raise ValueError("Training data contain non-finite values")
    means = values.mean(axis=0)
    scales = values.std(axis=0, ddof=0)
    scales[scales == 0] = 1.0
    categories = {name: sorted(df[name].astype(str).unique().tolist()) for name in categorical}
    prototype = RidgeModel(continuous, categorical, categories, means, scales, np.array([]))
    matrix = _matrix(df, prototype)
    target_values = df[target].to_numpy(float)
    penalty = np.eye(matrix.shape[1]) * alpha
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(matrix.T @ matrix + penalty, matrix.T @ target_values)
    prototype.coefficients = coefficients
    return prototype


def predict_ridge(df: pd.DataFrame, model: RidgeModel) -> np.ndarray:
    return _matrix(df, model) @ model.coefficients


def rmse(observed: np.ndarray, predicted: np.ndarray) -> float:
    residual = np.asarray(observed, float) - np.asarray(predicted, float)
    return float(np.sqrt(np.mean(residual * residual)))


def bootstrap_fractional_improvement(
    per_track: pd.DataFrame,
    n_boot: int,
    seed: int,
) -> np.ndarray:
    """Bootstrap tracks and return baseline-to-augmented RMSE fractions."""
    if n_boot <= 0:
        raise ValueError("n_boot must be positive")
    base_sse = per_track["baseline_sse"].to_numpy(float)
    aug_sse = per_track["augmented_sse"].to_numpy(float)
    counts = per_track["n_test"].to_numpy(float)
    rng = np.random.default_rng(seed)
    out = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        draw = rng.integers(0, len(per_track), size=len(per_track))
        base = np.sqrt(base_sse[draw].sum() / counts[draw].sum())
        aug = np.sqrt(aug_sse[draw].sum() / counts[draw].sum())
        out[i] = (base - aug) / base
    return out
