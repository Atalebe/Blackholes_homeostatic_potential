from pathlib import Path
import numpy as np
import pandas as pd

from src.utils.config import load_yaml
from src.core.variance_scaling import fit_linear

cfg = load_yaml(CONFIG_PATH)

def read_table(path):
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        return pd.read_parquet(p)
    return pd.read_csv(p)

def dispersion_value(vals, metric):
    vals = np.asarray(vals, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return np.nan
    if metric == "variance":
        return float(np.nanvar(vals, ddof=0))
    if metric == "mad2":
        med = np.nanmedian(vals)
        mad = np.nanmedian(np.abs(vals - med))
        return float(mad ** 2)
    if metric == "iqr2":
        q25, q75 = np.nanpercentile(vals, [25, 75])
        return float((q75 - q25) ** 2)
    raise ValueError(f"Unknown metric: {metric}")

def binned_dispersion(df, x_col, y_col, bins, min_count, metric):
    rows = []
    x = pd.to_numeric(df[x_col], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(df[y_col], errors="coerce").to_numpy(dtype=float)

    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        if i == len(bins) - 2:
            mask = np.isfinite(x) & np.isfinite(y) & (x >= lo) & (x <= hi)
        else:
            mask = np.isfinite(x) & np.isfinite(y) & (x >= lo) & (x < hi)

        vals = y[mask]
        n = vals.size
        if n < min_count:
            continue

        rows.append({
            "x_mid": 0.5 * (lo + hi),
            "n": int(n),
            "dispersion_y": dispersion_value(vals, metric),
            "metric": metric,
            "y_col": y_col,
        })

    return pd.DataFrame(rows)

def shuffle_values(series, rng, groups=None):
    y = series.copy()

    if groups is None or groups is False:
        y.iloc[:] = rng.permutation(y.to_numpy())
        return y

    if isinstance(groups, str):
        if groups in ("", "global"):
            y.iloc[:] = rng.permutation(y.to_numpy())
            return y
        raise ValueError("Pass a Series for grouped shuffles, or 'global'.")

    grouped = pd.Series(np.arange(len(series)), index=series.index).groupby(groups, observed=False)
    for _, idx in grouped.groups.items():
        idx = list(idx)
        vals = y.loc[idx].to_numpy()
        y.loc[idx] = rng.permutation(vals)
    return y

df = read_table(cfg["data"]["input_table"]).copy()

x_col = cfg["variance_scaling"]["x"]
y_cols = cfg["tests"]["y_cols"]
metrics = cfg["tests"]["metrics"]

df[x_col] = pd.to_numeric(df[x_col], errors="coerce")
bins = np.arange(
    cfg["variance_scaling"]["bin_start"],
    cfg["variance_scaling"]["bin_stop"] + cfg["variance_scaling"]["bin_step"],
    cfg["variance_scaling"]["bin_step"],
)
min_bin_count = int(cfg["variance_scaling"]["min_bin_count"])

shuffle_within = cfg.get("nulls", {}).get("shuffle_within", "global")
if shuffle_within in (None, False, "", "global"):
    group_arg = "global"
else:
    group_arg = df[shuffle_within]

rng_seed = int(cfg["run"]["seed"])
n_perm = N_PERM_OVERRIDE if N_PERM_OVERRIDE is not None else int(cfg["nulls"]["n_perm"])

summary_rows = []
binned_rows = []

for y_col in y_cols:
    df[y_col] = pd.to_numeric(df[y_col], errors="coerce")
    work = df[np.isfinite(df[x_col]) & np.isfinite(df[y_col])].copy()

    for metric in metrics:
        bd = binned_dispersion(work, x_col, y_col, bins, min_bin_count, metric)

        if len(bd) < 2:
            summary_rows.append({
                "y_col": y_col,
                "metric": metric,
                "obs_slope": np.nan,
                "intercept": np.nan,
                "p_one_sided_negative": np.nan,
                "n_perm": 0,
                "n_bins_used": len(bd),
                "note": "Not enough populated bins",
            })
            continue

        fit = fit_linear(bd["x_mid"].values, bd["dispersion_y"].values)
        obs_slope = fit["slope"]

        rng = np.random.default_rng(rng_seed)
        null_slopes = []

        for _ in range(n_perm):
            yp = shuffle_values(work[y_col], rng, groups=group_arg)
            tmp = work.copy()
            tmp["_yperm"] = yp.values
            bd_perm = binned_dispersion(tmp, x_col, "_yperm", bins, min_bin_count, metric)
            if len(bd_perm) < 2:
                continue
            fit_perm = fit_linear(bd_perm["x_mid"].values, bd_perm["dispersion_y"].values)
            null_slopes.append(fit_perm["slope"])

        null_slopes = np.asarray(null_slopes, dtype=float)
        if len(null_slopes) == 0:
            p_neg = np.nan
        else:
            p_neg = (1 + np.sum(null_slopes <= obs_slope)) / (1 + len(null_slopes))

        binned_rows.append(bd)

        summary_rows.append({
            "y_col": y_col,
            "metric": metric,
            "obs_slope": obs_slope,
            "intercept": fit["intercept"],
            "p_one_sided_negative": p_neg,
            "n_perm": len(null_slopes),
            "n_bins_used": len(bd),
            "note": "",
        })

summary = pd.DataFrame(summary_rows)
binned = pd.concat(binned_rows, ignore_index=True) if binned_rows else pd.DataFrame()

summary_out = Path(cfg["outputs"]["summary_csv"])
binned_out = Path(cfg["outputs"]["binned_csv"])
summary_out.parent.mkdir(parents=True, exist_ok=True)

summary.to_csv(summary_out, index=False)
binned.to_csv(binned_out, index=False)

print(f"[ok] wrote {summary_out}")
print(f"[ok] wrote {binned_out}")
print(summary.to_string(index=False))
