# src/core/permutation_nulls.py
import numpy as np
import pandas as pd

from src.core.variance_scaling import binned_variance, fit_linear


def _shuffle_values(series: pd.Series, rng, groups=None) -> pd.Series:
    y = series.copy()

    # Global shuffle
    if groups is None:
        y.iloc[:] = rng.permutation(y.to_numpy())
        return y

    # Grouped shuffle
    idx_by_group = pd.Series(np.arange(len(series)), index=series.index).groupby(groups, observed=False)
    for _, idx in idx_by_group.groups.items():
        idx = list(idx)
        vals = y.loc[idx].to_numpy()
        y.loc[idx] = rng.permutation(vals)
    return y


def variance_slope_null(
    df,
    group_col=None,
    x_col="logMbh",
    y_col="phi_bh",
    bins=None,
    n_perm=2000,
    min_count=8,
    seed=12345,
):
    rng = np.random.default_rng(seed)

    obs_bv = binned_variance(
        df,
        x_col=x_col,
        y_col=y_col,
        bins=bins,
        min_count=min_count,
    )

    if len(obs_bv) < 2:
        return {
            "null_slopes": np.array([]),
            "p_one_sided_negative": np.nan,
            "obs_slope": np.nan,
        }

    obs_fit = fit_linear(obs_bv["x_mid"].values, obs_bv["var_y"].values)
    obs_slope = obs_fit["slope"]

    groups = None
    if isinstance(group_col, pd.Series):
        groups = group_col
    elif group_col in (None, False, "", "global"):
        groups = None
    else:
        # allow passing a column name string if desired
        groups = df[group_col]

    null_slopes = []

    for _ in range(n_perm):
        yp = _shuffle_values(df[y_col], rng, groups=groups)
        tmp = df.copy()
        tmp[y_col] = yp

        bv = binned_variance(
            tmp,
            x_col=x_col,
            y_col=y_col,
            bins=bins,
            min_count=min_count,
        )

        if len(bv) < 2:
            continue

        fit = fit_linear(bv["x_mid"].values, bv["var_y"].values)
        null_slopes.append(fit["slope"])

    null_slopes = np.asarray(null_slopes, dtype=float)

    if len(null_slopes) == 0:
        p_neg = np.nan
    else:
        p_neg = (1 + np.sum(null_slopes <= obs_slope)) / (1 + len(null_slopes))

    return {
        "null_slopes": null_slopes,
        "p_one_sided_negative": p_neg,
        "obs_slope": obs_slope,
    }
