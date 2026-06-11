import numpy as np
import pandas as pd

def mad(arr):
    arr = np.asarray(arr, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return np.nan
    med = np.median(arr)
    return np.median(np.abs(arr - med))

def iqr(arr):
    arr = np.asarray(arr, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return np.nan
    q25, q75 = np.percentile(arr, [25, 75])
    return q75 - q25

def dispersion_value(arr, metric="variance"):
    arr = np.asarray(arr, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return np.nan

    metric = metric.lower()
    if metric == "variance":
        return np.var(arr, ddof=1)
    if metric == "mad":
        return mad(arr)
    if metric == "mad2":
        m = mad(arr)
        return m * m
    if metric == "iqr":
        return iqr(arr)
    if metric == "iqr2":
        q = iqr(arr)
        return q * q

    raise ValueError(f"Unknown metric: {metric}")

def binned_dispersion(df, x_col, y_col, bins, min_count=20, metric="variance"):
    rows = []
    cats = pd.cut(df[x_col], bins=bins, include_lowest=True)
    for interval, g in df.groupby(cats, observed=False):
        if interval is pd.NA or len(g) < min_count:
            continue
        disp = dispersion_value(g[y_col].values, metric=metric)
        if not np.isfinite(disp):
            continue
        rows.append({
            "x_mid": 0.5 * (interval.left + interval.right),
            "n": len(g),
            "dispersion_y": disp,
            "metric": metric,
            "y_col": y_col,
        })
    return pd.DataFrame(rows)

def fit_linear(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    coeffs = np.polyfit(x, y, 1)
    return {"slope": coeffs[0], "intercept": coeffs[1]}

def permute_within_group(df, group_col, value_col, rng):
    df = df.copy()
    for _, idx in df.groupby(group_col, observed=False).groups.items():
        vals = df.loc[idx, value_col].to_numpy(copy=True)
        rng.shuffle(vals)
        df.loc[idx, value_col] = vals
    return df

def dispersion_slope_null(df, group_col, x_col, y_col, bins, n_perm=1000,
                          min_count=20, seed=12345, metric="variance"):
    rng = np.random.default_rng(seed)

    obs_bd = binned_dispersion(
        df, x_col=x_col, y_col=y_col, bins=bins,
        min_count=min_count, metric=metric
    )
    if len(obs_bd) < 2:
        return {
            "obs_slope": np.nan,
            "null_slopes": np.array([]),
            "p_one_sided_negative": np.nan,
        }

    obs_fit = fit_linear(obs_bd["x_mid"].values, obs_bd["dispersion_y"].values)
    obs_slope = obs_fit["slope"]

    null_slopes = []
    for _ in range(n_perm):
        tmp = permute_within_group(df, group_col, y_col, rng)
        bd = binned_dispersion(
            tmp, x_col=x_col, y_col=y_col, bins=bins,
            min_count=min_count, metric=metric
        )
        if len(bd) < 2:
            continue
        fit = fit_linear(bd["x_mid"].values, bd["dispersion_y"].values)
        null_slopes.append(fit["slope"])

    null_slopes = np.asarray(null_slopes, dtype=float)
    if null_slopes.size == 0:
        p = np.nan
    else:
        p = (1 + np.sum(null_slopes <= obs_slope)) / (null_slopes.size + 1)

    return {
        "obs_slope": obs_slope,
        "null_slopes": null_slopes,
        "p_one_sided_negative": p,
    }
