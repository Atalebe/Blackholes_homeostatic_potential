# src/obs/42_manga_full_ifu_robust_dispersion_scaling.py
from pathlib import Path
import numpy as np
import pandas as pd

from src.utils.config import load_yaml
from src.core.variance_scaling import fit_linear
from src.core.permutation_nulls import variance_slope_null


def mad2(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return np.nan
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    return mad ** 2


def iqr2(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return np.nan
    q75, q25 = np.percentile(x, [75, 25])
    iqr = q75 - q25
    return iqr ** 2


METRICS = {
    "variance": np.var,
    "mad2": mad2,
    "iqr2": iqr2,
}

cfg = load_yaml(CONFIG_PATH)
df = pd.read_csv(cfg["data"]["state_vector_csv"]).copy()

x_col = cfg["dispersion_scaling"]["x"]
y_cols = cfg["dispersion_scaling"]["y_cols"]
min_bin_count = cfg["dispersion_scaling"]["min_bin_count"]

bins = np.arange(
    cfg["dispersion_scaling"]["bin_start"],
    cfg["dispersion_scaling"]["bin_stop"] + cfg["dispersion_scaling"]["bin_step"],
    cfg["dispersion_scaling"]["bin_step"],
)

shuffle_within = cfg.get("nulls", {}).get("shuffle_within", "global")
n_perm = N_PERM_OVERRIDE if N_PERM_OVERRIDE is not None else cfg["nulls"]["n_perm"]

summary_rows = []
binned_rows = []

for y_col in y_cols:
    for metric_name, metric_fn in METRICS.items():
        work = df[[x_col, y_col]].copy()
        if shuffle_within not in (None, "", "global", False):
            work[shuffle_within] = df[shuffle_within]

        work = work.replace([np.inf, -np.inf], np.nan).dropna().copy()

        bin_ids = pd.cut(work[x_col], bins=bins, include_lowest=True, right=False)
        grouped = work.groupby(bin_ids, observed=False)

        rows = []
        for interval, g in grouped:
            if interval is None or len(g) < min_bin_count:
                continue
            disp = metric_fn(g[y_col].values)
            if not np.isfinite(disp):
                continue
            rows.append({
                "x_mid": interval.mid,
                "n": len(g),
                "dispersion_y": disp,
                "metric": metric_name,
                "y_col": y_col,
            })

        bv = pd.DataFrame(rows)
        binned_rows.append(bv)

        if len(bv) < 2:
            summary_rows.append({
                "y_col": y_col,
                "metric": metric_name,
                "obs_slope": np.nan,
                "intercept": np.nan,
                "p_one_sided_negative": np.nan,
                "n_perm": 0,
                "n_bins_used": len(bv),
                "note": "Not enough populated bins",
            })
            continue

        fit = fit_linear(bv["x_mid"].values, bv["dispersion_y"].values)

        null_slopes = []
        rng = np.random.default_rng(cfg["run"]["seed"])

        for _ in range(n_perm):
            tmp = work.copy()

            if shuffle_within in (None, "", "global", False):
                tmp[y_col] = rng.permutation(tmp[y_col].values)
            else:
                shuffled = tmp[y_col].copy()
                for _, idx in tmp.groupby(shuffle_within, observed=False).groups.items():
                    idx = list(idx)
                    shuffled.loc[idx] = rng.permutation(shuffled.loc[idx].values)
                tmp[y_col] = shuffled

            bin_ids_p = pd.cut(tmp[x_col], bins=bins, include_lowest=True, right=False)
            grouped_p = tmp.groupby(bin_ids_p, observed=False)

            rows_p = []
            for interval, g in grouped_p:
                if interval is None or len(g) < min_bin_count:
                    continue
                disp = metric_fn(g[y_col].values)
                if not np.isfinite(disp):
                    continue
                rows_p.append((interval.mid, disp))

            if len(rows_p) < 2:
                continue

            xp = np.array([r[0] for r in rows_p], dtype=float)
            yp = np.array([r[1] for r in rows_p], dtype=float)
            fit_p = fit_linear(xp, yp)
            null_slopes.append(fit_p["slope"])

        null_slopes = np.asarray(null_slopes, dtype=float)
        p_neg = (1 + np.sum(null_slopes <= fit["slope"])) / (1 + len(null_slopes)) if len(null_slopes) else np.nan

        summary_rows.append({
            "y_col": y_col,
            "metric": metric_name,
            "obs_slope": fit["slope"],
            "intercept": fit["intercept"],
            "p_one_sided_negative": p_neg,
            "n_perm": len(null_slopes),
            "n_bins_used": len(bv),
            "note": "",
        })

summary_df = pd.DataFrame(summary_rows)
binned_df = pd.concat(binned_rows, ignore_index=True) if len(binned_rows) else pd.DataFrame()

Path(cfg["outputs"]["summary_csv"]).parent.mkdir(parents=True, exist_ok=True)
summary_df.to_csv(cfg["outputs"]["summary_csv"], index=False)
binned_df.to_csv(cfg["outputs"]["binned_csv"], index=False)

print(f"[ok] wrote {cfg['outputs']['summary_csv']}")
print(f"[ok] wrote {cfg['outputs']['binned_csv']}")
print(summary_df.to_string(index=False))
