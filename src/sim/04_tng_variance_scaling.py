from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from src.utils.config import load_yaml
from src.core.variance_scaling import binned_variance, fit_linear
from src.core.permutation_nulls import variance_slope_null

cfg = load_yaml(CONFIG_PATH)
infile = Path(cfg["outputs"]["window_catalog_out"])
if not infile.exists():
    raise FileNotFoundError(f"Missing window catalog: {infile}")

df = pd.read_parquet(infile)
df = df[np.isfinite(df["log10_mbh"]) & np.isfinite(df["phi_bh"])].copy()

vs = cfg["variance_scaling"]
bins = np.arange(vs["bin_start"], vs["bin_stop"] + vs["bin_step"], vs["bin_step"])
min_bin_count = N_BOOT_OVERRIDE if False else vs["min_bin_count"]

bv = binned_variance(df, x_col="log10_mbh", y_col="phi_bh", bins=bins, min_count=min_bin_count)
if len(bv) < 2:
    raise RuntimeError("Not enough populated bins for variance scaling fit")

fit = fit_linear(bv["x_mid"].values, bv["var_y"].values)

n_perm = N_PERM_OVERRIDE if N_PERM_OVERRIDE is not None else cfg["nulls"]["n_perm"]
null = variance_slope_null(
    df,
    group_col="bh_mass_class",
    x_col="log10_mbh",
    y_col="phi_bh",
    bins=bins,
    n_perm=n_perm,
    min_count=min_bin_count,
    seed=cfg["run"]["seed"],
)

variance_out = Path(cfg["outputs"]["variance_table_out"])
variance_out.parent.mkdir(parents=True, exist_ok=True)
bv.to_csv(variance_out, index=False)

summary = pd.DataFrame([{
    "obs_slope": fit["slope"],
    "intercept": fit["intercept"],
    "p_one_sided_negative": null["p_one_sided_negative"],
    "n_perm": len(null["null_slopes"]),
    "n_bins_used": len(bv),
}])

summary_out = Path(cfg["outputs"]["variance_summary_out"])
summary_out.parent.mkdir(parents=True, exist_ok=True)
summary.to_csv(summary_out, index=False)

null_slopes_out = Path(cfg["outputs"]["null_slopes_out"])
pd.DataFrame({"null_slope": null["null_slopes"]}).to_csv(null_slopes_out, index=False)

fig_prefix = cfg["outputs"]["figure_prefix"]
fig_path = Path(f"{fig_prefix}_variance_scaling.png")
fig_path.parent.mkdir(parents=True, exist_ok=True)

x = bv["x_mid"].values
y = bv["var_y"].values
xx = np.linspace(x.min(), x.max(), 200)
yy = fit["slope"] * xx + fit["intercept"]

plt.figure(figsize=(7, 5))
plt.scatter(x, y)
plt.plot(xx, yy)
plt.xlabel("log10(M_BH / M_sun)")
plt.ylabel("Var(phi_bh)")
plt.title("TNG variance scaling")
plt.tight_layout()
plt.savefig(fig_path, dpi=160)
plt.close()

print(f"[ok] wrote {variance_out}")
print(f"[ok] wrote {summary_out}")
print(f"[ok] wrote {null_slopes_out}")
print(f"[ok] wrote {fig_path}")
print(summary.to_string(index=False))
