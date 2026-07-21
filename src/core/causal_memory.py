"""Strictly causal memory kernels for irregularly sampled tracks."""
from __future__ import annotations

import numpy as np


def normalize_track_time(t: np.ndarray) -> np.ndarray:
    """Map a finite, strictly increasing track to [0, 1]."""
    values = np.asarray(t, dtype=float)
    if values.ndim != 1 or values.size < 2:
        raise ValueError("A track requires at least two timestamps")
    if not np.isfinite(values).all():
        raise ValueError("Timestamps must be finite")
    dt = np.diff(values)
    if np.any(dt <= 0):
        raise ValueError("Timestamps must be strictly increasing")
    span = values[-1] - values[0]
    if span <= 0:
        raise ValueError("Track span must be positive")
    return (values - values[0]) / span


def causal_exponential_memory(
    u: np.ndarray,
    x: np.ndarray,
    tau: float,
) -> np.ndarray:
    """Return a past-only exponentially weighted history on an irregular grid.

    At row i the value uses intervals and samples ending at i, with x[i-1]
    representing the left endpoint of the newest completed interval. x[i] and
    all future values are excluded. The first row is NaN by construction.
    """
    time = np.asarray(u, dtype=float)
    values = np.asarray(x, dtype=float)
    if time.shape != values.shape or time.ndim != 1:
        raise ValueError("u and x must be aligned one-dimensional arrays")
    if not np.isfinite(values).all():
        raise ValueError("Signal values must be finite")
    if not np.isfinite(tau) or tau <= 0:
        raise ValueError("tau must be finite and positive")
    if np.any(np.diff(time) <= 0):
        raise ValueError("u must be strictly increasing")

    out = np.full(values.size, np.nan, dtype=float)
    numerator = 0.0
    denominator = 0.0
    for i in range(1, values.size):
        dt = time[i] - time[i - 1]
        decay = np.exp(-dt / tau)
        numerator = decay * numerator + values[i - 1] * dt
        denominator = decay * denominator + dt
        out[i] = numerator / denominator
    return out


def chronological_split(n_predictions: int, train: float, validation: float) -> np.ndarray:
    """Assign chronological train/validation/test labels."""
    if n_predictions < 3:
        raise ValueError("At least three prediction rows are required")
    if not (0 < train < 1 and 0 < validation < 1 and train + validation < 1):
        raise ValueError("Invalid split fractions")
    train_end = max(1, int(np.floor(n_predictions * train)))
    validation_end = max(train_end + 1, int(np.floor(n_predictions * (train + validation))))
    validation_end = min(validation_end, n_predictions - 1)
    labels = np.full(n_predictions, "test", dtype=object)
    labels[:train_end] = "train"
    labels[train_end:validation_end] = "validation"
    return labels
