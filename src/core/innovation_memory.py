"""Strictly causal innovation-history utilities for Generator 4."""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np


def causal_innovation_history(time, innovation, tau: float) -> np.ndarray:
    """Return normalized exponential history using only innovations at earlier times."""
    t = np.asarray(time, dtype=float)
    e = np.asarray(innovation, dtype=float)
    if t.ndim != 1 or e.ndim != 1 or len(t) != len(e):
        raise ValueError("time and innovation must be equal-length vectors")
    if not np.isfinite(t).all() or not np.isfinite(e).all():
        raise ValueError("time and innovation must be finite")
    if not np.isfinite(tau) or tau <= 0:
        raise ValueError("tau must be finite and positive")
    if len(t) > 1 and not np.all(np.diff(t) > 0):
        raise ValueError("time must be strictly increasing")
    out = np.full(len(t), np.nan, dtype=float)
    numerator = 0.0
    denominator = 0.0
    for index in range(1, len(t)):
        decay = float(np.exp(-(t[index] - t[index - 1]) / tau))
        numerator = decay * (numerator + e[index - 1])
        denominator = decay * (denominator + 1.0)
        out[index] = numerator / denominator if denominator > 0 else np.nan
    return out


def _validated_pairs(
    track_time: Iterable[np.ndarray],
    track_innovation: Iterable[np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    times = list(track_time)
    innovations = list(track_innovation)
    if len(times) != len(innovations) or not times:
        raise ValueError("paired non-empty track collections are required")
    all_dt: list[np.ndarray] = []
    all_previous: list[np.ndarray] = []
    all_current: list[np.ndarray] = []
    used_tracks = 0
    for time, innovation in zip(times, innovations, strict=True):
        t = np.asarray(time, dtype=float)
        e = np.asarray(innovation, dtype=float)
        if t.ndim != 1 or e.ndim != 1 or len(t) != len(e):
            raise ValueError("each track must contain equal-length vectors")
        if not np.isfinite(t).all() or not np.isfinite(e).all():
            raise ValueError("all pooled values must be finite")
        if len(t) < 2:
            continue
        dt = np.diff(t)
        if not np.all(dt > 0):
            raise ValueError("time must increase strictly inside every track")
        all_dt.append(dt)
        all_previous.append(e[:-1])
        all_current.append(e[1:])
        used_tracks += 1
    if not all_dt:
        raise ValueError("at least one within-track adjacent pair is required")
    return (
        np.concatenate(all_dt),
        np.concatenate(all_previous),
        np.concatenate(all_current),
        used_tracks,
    )


def estimate_pooled_ou_tau(
    track_time: Iterable[np.ndarray],
    track_innovation: Iterable[np.ndarray],
    lower: float,
    upper: float,
    grid_size: int = 512,
) -> dict:
    """Fit one OU decay scale by pooled within-track adjacent-pair SSE.

    Tracks contribute pairs, never transitions between tracks. The result marks
    a boundary optimum as non-interior. Callers must retain boundary estimates
    in null draws, while an observed boundary estimate fails Generator 4.
    """
    if not (0 < lower < upper) or grid_size < 3:
        raise ValueError("invalid tau profile bounds or grid size")
    dt, previous, current, n_tracks = _validated_pairs(
        track_time, track_innovation
    )
    grid = np.geomspace(float(lower), float(upper), int(grid_size))
    sse = np.empty(len(grid), dtype=float)
    for index, tau in enumerate(grid):
        prediction = np.exp(-dt / tau) * previous
        residual = current - prediction
        sse[index] = float(residual @ residual)
    selected = int(np.argmin(sse))
    return {
        "tau": float(grid[selected]),
        "profile_index": selected,
        "grid_size": int(grid_size),
        "lower": float(lower),
        "upper": float(upper),
        "interior": bool(0 < selected < len(grid) - 1),
        "sse": float(sse[selected]),
        "n_within_track_pairs": int(len(dt)),
        "n_contributing_tracks": int(n_tracks),
        "cross_track_pairs": 0,
    }


def estimate_ou_tau(
    time, innovation, lower: float, upper: float, grid_size: int = 512
) -> dict:
    """Backward-compatible single-track wrapper."""
    return estimate_pooled_ou_tau(
        [np.asarray(time)], [np.asarray(innovation)], lower, upper, grid_size
    )
