# src/obs/41_manga_full_ifu_variance_scaling.py
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from src.utils.config import load_yaml
from src.core.variance_scaling import binned_variance, fit_linear
from src.core.permutation_nulls import variance_slope_null

cfg = load_yaml(CONFIG_PATH)
df = pd.read_csv(cfg["data"]["state_vector_csv"]).copy()

x_col = cfg["variance_scaling"]["x"]
y_col = cfg["variance_scaling"]["y"]
min_bin_count = cfg["variance_scaling"]["min_bin_count"]

bins = np.arange(
    cfg["variance_scaling"]["bin_start"],
    cfg["variance_scaling"]["bin_stop"] + cfg["variance_scaling"]["bin_step"],
    cfg["variance_scaling"]["bin_step"],
)

work = df[[x_col, y_col]].copy()
if "shuffle_within" in cfg.get("nulls", {}) and cfg["nulls"]["shuffle_within"] not in (None, "", "global", False):
    shuffle_col = cfg["nulls"]["shuffle_within"]
    work[shuffle_col] = df[shuffle_col]

work = work.replace([np.inf, -np.inf], np.nan).dropna().copy()

bv = binned_variance(
    work,
    x_col=x_col,
    y_col=y_col,
    bins=bins,
    min_count=min_bin_count,
)

if len(bv) < 2:
    summary = pd.DataFrame([{
        "obs_slope": np.nan,
        "intercept": np.nan,
        "p_one_sided_negative": np.nan,
        "n_perm": 0,
        "n_bins_used": len(bv),
        "x_col": x_col,
        "y_col": y_col,
        "note": "Not enough populated bins for variance scaling fit",
    }])
    Path(cfg["outputs"]["variance_table_out"]).parent.mkdir(parents=True, exist_ok=True)
    bv.to_csv(cfg["outputs"]["variance_table_out"], index=False)
    summary.to_csv(cfg["outputs"]["variance_summary_out"], index=False)
    pd.DataFrame({"null_slope": []}).to_csv(cfg["outputs"]["null_slopes_out"], index=False)
    print(f"[warn] not enough populated bins for fit: {len(bv)}")
    raise SystemExit(0)

fit = fit_linear(bv["x_mid"].values, bv["var_y"].values)

n_perm = N_PERM_OVERRIDE if N_PERM_OVERRIDE is not None else cfg["nulls"]["n_perm"]
shuffle_within = cfg.get("nulls", {}).get("shuffle_within", "global")
if shuffle_within in (None, False, "", "global"):
    group_arg = None
else:
    group_arg = work[shuffle_within]
group_arg = None if shuffle_within in (None, "", "global", False) else work[shuffle_within]

null = variance_slope_null(
    work,
    group_col=group_arg,
    x_col=x_col,
    y_col=y_col,
    bins=bins,
    n_perm=n_perm,
    min_count=min_bin_count,
    seed=cfg["run"]["seed"],
)

Path(cfg["outputs"]["variance_table_out"]).parent.mkdir(parents=True, exist_ok=True)
bv.to_csv(cfg["outputs"]["variance_table_out"], index=False)

summary = pd.DataFrame([{
    "obs_slope": fit["slope"],
    "intercept": fit["intercept"],
    "p_one_sided_negative": null["p_one_sided_negative"],
    "n_perm": len(null["null_slopes"]),
    "n_bins_used": len(bv),
    "x_col": x_col,
    "y_col": y_col,
}])
summary.to_csv(cfg["outputs"]["variance_summary_out"], index=False)
pd.DataFrame({"null_slope": null["null_slopes"]}).to_csv(cfg["outputs"]["null_slopes_out"], index=False)

fig_path = Path(f"{cfg['outputs']['figure_prefix']}_variance_scaling.png")
fig_path.parent.mkdir(parents=True, exist_ok=True)

x = bv["x_mid"].values
y = bv["var_y"].values
xx = np.linspace(x.min(), x.max(), 200)
yy = fit["slope"] * xx + fit["intercept"]

plt.figure(figsize=(7, 5))
plt.scatter(x, y)
plt.plot(xx, yy)
plt.xlabel(x_col)
plt.ylabel(f"Var({y_col})")
plt.title(cfg["run"]["run_name"])
plt.tight_layout()
plt.savefig(fig_path, dpi=160)
plt.close()

print(f"[ok] wrote {cfg['outputs']['variance_table_out']}")
print(f"[ok] wrote {cfg['outputs']['variance_summary_out']}")
print(f"[ok] wrote {cfg['outputs']['null_slopes_out']}")
print(f"[ok] wrote {fig_path}")
print(summary.to_string(index=False))
print(bv.to_string(index=False))
