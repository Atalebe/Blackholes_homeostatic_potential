"""Selection-aware null helpers for causal memory candidates."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.causal_memory import causal_exponential_memory


def balanced_sample(
    df: pd.DataFrame,
    split_col: str,
    id_col: str,
    max_rows_per_split: int,
    seed: int,
) -> pd.DataFrame:
    """Deterministically cap each split while retaining every track when possible."""
    rng = np.random.default_rng(seed)
    parts = []
    for split, group in df.groupby(split_col, sort=False, observed=True):
        if len(group) <= max_rows_per_split:
            parts.append(group)
            continue
        # Reserve two rows per track when available so within-split circular
        # shifts remain defined, then fill the remaining quota uniformly.
        reserved = group.groupby(id_col, sort=False, observed=True).sample(n=2, random_state=seed)
        remaining = group.drop(index=reserved.index)
        need = max_rows_per_split - len(reserved)
        chosen = rng.choice(remaining.index.to_numpy(), size=need, replace=False)
        parts.append(pd.concat([reserved, remaining.loc[chosen]]))
    return pd.concat(parts).sort_index().reset_index(drop=True)


def circular_shift_memory(
    df: pd.DataFrame,
    id_col: str,
    split_col: str,
    order_col: str,
    memory_cols: list[str],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Apply a shared nonzero circular shift within each track-and-split block."""
    out = df.copy()
    for _, indices in df.sort_values([id_col, split_col, order_col], kind="stable").groupby(
        [id_col, split_col], sort=False, observed=True
    ).groups.items():
        positions = np.asarray(list(indices), dtype=int)
        n = len(positions)
        if n < 2:
            raise ValueError("Every sampled track must contain at least two rows")
        shift = int(rng.integers(1, n))
        values = df.loc[positions, memory_cols].to_numpy(float)
        out.loc[positions, memory_cols] = np.roll(values, shift, axis=0)
    return out


def plus_one_p(exceedances: int, n_perm: int) -> float:
    if not (0 <= exceedances <= n_perm and n_perm > 0):
        raise ValueError("Invalid permutation counts")
    return float((exceedances + 1) / (n_perm + 1))


def recompute_sampled_memory(
    df: pd.DataFrame,
    id_col: str,
    split_col: str,
    order_col: str,
    time_col: str,
    signal_col: str,
    taus: list[float],
    rng: np.random.Generator | None = None,
) -> pd.DataFrame:
    """Recompute causal kernels after optional within-track/split signal permutation.

    The sampled ordering grid is held fixed. When rng is supplied, signal values
    are permuted separately inside each chronological split of each track before
    all kernels are regenerated. Finished memory columns are never permuted.
    """
    out_parts = []
    for _, group in df.groupby(id_col, sort=False, observed=True):
        group = group.sort_values(order_col, kind="stable").copy()
        u = group[time_col].to_numpy(float)
        x = group[signal_col].to_numpy(float).copy()
        if rng is not None:
            split_values = group[split_col].astype(str).to_numpy()
            for level in np.unique(split_values):
                positions = np.flatnonzero(split_values == level)
                x[positions] = rng.permutation(x[positions])
        for tau in taus:
            group[f"memory_tau_{tau:g}"] = causal_exponential_memory(u, x, float(tau))
        out_parts.append(group.iloc[1:])  # first sampled row has no causal past
    return pd.concat(out_parts, ignore_index=True)
