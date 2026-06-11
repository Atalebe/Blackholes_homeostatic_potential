from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from src.utils.config import load_yaml
from src.core.variance_scaling import binned_variance, fit_linear
from src.core.permutation_nulls import variance_slope_null

cfg = load_yaml(CONFIG_PATH)
infile = Path(cfg["data"]["bh_level_csv"])
if not infile.exists():
    raise FileNotFoundError(f"Missing BH-level CSV: {infile}")

df = pd.read_csv(infile)

xcol = cfg["variance_scaling"]["x"]
ycol = cfg["variance_scaling"]["y"]

df = df.replace([np.inf, -np.inf], np.nan)
df = df.dropna(subset=[xcol, ycol]).copy()

bins = np.arange(
    cfg["variance_scaling"]["bin_start"],
    cfg["variance_scaling"]["bin_stop"] + cfg["variance_scaling"]["bin_step"],
    cfg["variance_scaling"]["bin_step"],
)
min_bin_count = cfg["variance_scaling"]["min_bin_count"]

bv = binned_variance(df, x_col=xcol, y_col=ycol, bins=bins, min_count=min_bin_count)

variance_out = Path(cfg["outputs"]["variance_table_out"])
variance_out.parent.mkdir(parents=True, exist_ok=True)
bv.to_csv(variance_out, index=False)

if len(bv) < 2:
    summary = pd.DataFrame([{
        "obs_slope": np.nan,
        "intercept": np.nan,
        "p_one_sided_negative": np.nan,
        "n_perm": 0,
        "n_bins_used": len(bv),
        "note": "Not enough populated bins for variance scaling fit",
    }])

    summary_out = Path(cfg["outputs"]["variance_summary_out"])
    summary.to_csv(summary_out, index=False)

    null_out = Path(cfg["outputs"]["null_slopes_out"])
    pd.DataFrame({"null_slope": []}).to_csv(null_out, index=False)

    print(f"[warn] not enough populated bins for fit: {len(bv)}")
    print(f"[ok] wrote {variance_out}")
    print(f"[ok] wrote {summary_out}")
    print(f"[ok] wrote {null_out}")
    raise SystemExit(0)

fit = fit_linear(bv["x_mid"].values, bv["var_y"].values)

shuffle_group = cfg["nulls"].get("shuffle_within", "category")
n_perm = N_PERM_OVERRIDE if N_PERM_OVERRIDE is not None else cfg["nulls"]["n_perm"]

null = variance_slope_null(
    df,
    group_col=shuffle_group,
    x_col=xcol,
    y_col=ycol,
    bins=bins,
    n_perm=n_perm,
    min_count=min_bin_count,
    seed=cfg["run"]["seed"],
)

summary = pd.DataFrame([{
    "obs_slope": fit["slope"],
    "intercept": fit["intercept"],
    "p_one_sided_negative": null["p_one_sided_negative"],
    "n_perm": len(null["null_slopes"]),
    "n_bins_used": len(bv),
    "x_col": xcol,
    "y_col": ycol,
    "shuffle_group": shuffle_group,
}])

summary_out = Path(cfg["outputs"]["variance_summary_out"])
summary.to_csv(summary_out, index=False)

null_out = Path(cfg["outputs"]["null_slopes_out"])
pd.DataFrame({"null_slope": null["null_slopes"]}).to_csv(null_out, index=False)

fig_path = Path(f"{cfg['outputs']['figure_prefix']}_variance_scaling.png")
fig_path.parent.mkdir(parents=True, exist_ok=True)

x = bv["x_mid"].values
y = bv["var_y"].values
xx = np.linspace(x.min(), x.max(), 200)
yy = fit["slope"] * xx + fit["intercept"]

plt.figure(figsize=(7, 5))
plt.scatter(x, y)
plt.plot(xx, yy)
plt.xlabel("log10(M_BH, final / M_sun)")
plt.ylabel("Var(track_median_phi)")
plt.title("BH time-domain variance scaling, reduced Tier 1")
plt.tight_layout()
plt.savefig(fig_path, dpi=160)
plt.close()

print(f"[ok] wrote {variance_out}")
print(f"[ok] wrote {summary_out}")
print(f"[ok] wrote {null_out}")
print(f"[ok] wrote {fig_path}")
print(summary.to_string(index=False))
print(bv.to_string(index=False))
