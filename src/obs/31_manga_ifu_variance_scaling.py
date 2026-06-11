from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from src.utils.config import load_yaml
from src.core.variance_scaling import binned_variance, fit_linear
from src.core.permutation_nulls import variance_slope_null

cfg = load_yaml(CONFIG_PATH)

def read_table(path):
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        return pd.read_parquet(p)
    return pd.read_csv(p)

df = read_table(cfg["data"]["input_table"]).copy()

x_col = cfg["variance_scaling"]["x"]
y_col = cfg["variance_scaling"]["y"]

df[x_col] = pd.to_numeric(df[x_col], errors="coerce")
df[y_col] = pd.to_numeric(df[y_col], errors="coerce")
df = df[np.isfinite(df[x_col]) & np.isfinite(df[y_col])].copy()

vs = cfg["variance_scaling"]
bins = np.arange(vs["bin_start"], vs["bin_stop"] + vs["bin_step"], vs["bin_step"])
min_bin_count = int(vs["min_bin_count"])

bv = binned_variance(df, x_col=x_col, y_col=y_col, bins=bins, min_count=min_bin_count)

variance_out = Path(cfg["outputs"]["variance_table_out"])
summary_out = Path(cfg["outputs"]["variance_summary_out"])
null_out = Path(cfg["outputs"]["null_slopes_out"])
fig_path = Path(f"{cfg['outputs']['figure_prefix']}_variance_scaling.png")

variance_out.parent.mkdir(parents=True, exist_ok=True)
fig_path.parent.mkdir(parents=True, exist_ok=True)

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
    bv.to_csv(variance_out, index=False)
    summary.to_csv(summary_out, index=False)
    pd.DataFrame({"null_slope": []}).to_csv(null_out, index=False)
    print(f"[warn] not enough populated bins for fit: {len(bv)}")
    print(f"[ok] wrote {variance_out}")
    print(f"[ok] wrote {summary_out}")
    print(f"[ok] wrote {null_out}")
    raise SystemExit(0)

fit = fit_linear(bv["x_mid"].values, bv["var_y"].values)

n_perm = N_PERM_OVERRIDE if N_PERM_OVERRIDE is not None else int(cfg["nulls"]["n_perm"])
shuffle_within = cfg.get("nulls", {}).get("shuffle_within", "global")

if shuffle_within in (None, False, "", "global"):
    group_arg = "global"
else:
    group_arg = df[shuffle_within]

null = variance_slope_null(
    df,
    group_col=group_arg,
    x_col=x_col,
    y_col=y_col,
    bins=bins,
    n_perm=n_perm,
    min_count=min_bin_count,
    seed=int(cfg["run"]["seed"]),
)

bv.to_csv(variance_out, index=False)

summary = pd.DataFrame([{
    "obs_slope": fit["slope"],
    "intercept": fit["intercept"],
    "p_one_sided_negative": null["p_one_sided_negative"],
    "n_perm": len(null["null_slopes"]),
    "n_bins_used": len(bv),
    "x_col": x_col,
    "y_col": y_col,
}])
summary.to_csv(summary_out, index=False)

pd.DataFrame({"null_slope": null["null_slopes"]}).to_csv(null_out, index=False)

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

print(f"[ok] wrote {variance_out}")
print(f"[ok] wrote {summary_out}")
print(f"[ok] wrote {null_out}")
print(f"[ok] wrote {fig_path}")
print(summary.to_string(index=False))
print(bv.to_string(index=False))
