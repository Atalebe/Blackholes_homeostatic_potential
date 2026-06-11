from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from src.utils.config import load_yaml
from src.core.robust_dispersion import (
    binned_dispersion,
    fit_linear,
    dispersion_slope_null,
)

cfg = load_yaml(CONFIG_PATH)
df = pd.read_csv(cfg["data"]["bh_level_csv"]).replace([np.inf, -np.inf], np.nan)

x_col = cfg["analysis"]["x_col"]
y_cols = cfg["analysis"]["y_cols"]
metrics = cfg["analysis"]["metrics"]
bins = np.arange(
    cfg["analysis"]["bin_start"],
    cfg["analysis"]["bin_stop"] + cfg["analysis"]["bin_step"],
    cfg["analysis"]["bin_step"],
)
min_bin_count = cfg["analysis"]["min_bin_count"]
shuffle_group = cfg["nulls"]["shuffle_within"]
n_perm = N_PERM_OVERRIDE if N_PERM_OVERRIDE is not None else cfg["nulls"]["n_perm"]

all_binned = []
summary_rows = []

for y_col in y_cols:
    work = df.dropna(subset=[x_col, y_col]).copy()

    for metric in metrics:
        bd = binned_dispersion(
            work, x_col=x_col, y_col=y_col, bins=bins,
            min_count=min_bin_count, metric=metric
        )
        if not bd.empty:
            all_binned.append(bd)

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
        null = dispersion_slope_null(
            work,
            group_col=shuffle_group,
            x_col=x_col,
            y_col=y_col,
            bins=bins,
            n_perm=n_perm,
            min_count=min_bin_count,
            seed=cfg["run"]["seed"],
            metric=metric,
        )

        summary_rows.append({
            "y_col": y_col,
            "metric": metric,
            "obs_slope": fit["slope"],
            "intercept": fit["intercept"],
            "p_one_sided_negative": null["p_one_sided_negative"],
            "n_perm": len(null["null_slopes"]),
            "n_bins_used": len(bd),
            "note": "",
        })

        fig_path = Path(f"{cfg['outputs']['figure_prefix']}_{y_col}_{metric}.png")
        fig_path.parent.mkdir(parents=True, exist_ok=True)
        x = bd["x_mid"].values
        y = bd["dispersion_y"].values
        xx = np.linspace(x.min(), x.max(), 200)
        yy = fit["slope"] * xx + fit["intercept"]

        plt.figure(figsize=(7, 5))
        plt.scatter(x, y)
        plt.plot(xx, yy)
        plt.xlabel(x_col)
        plt.ylabel(f"{metric}({y_col})")
        plt.title(f"{y_col}, {metric}")
        plt.tight_layout()
        plt.savefig(fig_path, dpi=160)
        plt.close()

summary = pd.DataFrame(summary_rows)
binned = pd.concat(all_binned, ignore_index=True) if all_binned else pd.DataFrame()

Path(cfg["outputs"]["summary_csv"]).parent.mkdir(parents=True, exist_ok=True)
summary.to_csv(cfg["outputs"]["summary_csv"], index=False)
binned.to_csv(cfg["outputs"]["binned_csv"], index=False)

print(f"[ok] wrote {cfg['outputs']['summary_csv']}")
print(f"[ok] wrote {cfg['outputs']['binned_csv']}")
print(summary.to_string(index=False))
