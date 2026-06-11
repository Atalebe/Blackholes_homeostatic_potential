from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from src.utils.config import load_yaml
from src.core.variance_scaling import binned_variance, fit_linear

cfg = load_yaml(CONFIG_PATH)

window_parquet = Path(cfg["data"]["window_catalog_csv_or_parquet"])
out_summary_csv = Path(cfg["outputs"]["summary_csv"])
out_binned_csv = Path(cfg["outputs"]["binned_csv"])
out_png = Path(cfg["outputs"]["figure_png"])

x_col = cfg["variance_scaling"].get("x", "logMbh")
y_col = cfg["variance_scaling"].get("y", "phi_bh")

vs = cfg["variance_scaling"]
bins = np.arange(vs["bin_start"], vs["bin_stop"] + vs["bin_step"], vs["bin_step"])
min_bin_count = int(vs["min_bin_count"])

if window_parquet.suffix == ".parquet":
    df = pd.read_parquet(window_parquet)
else:
    df = pd.read_csv(window_parquet)

work = df.dropna(subset=[x_col, y_col]).copy()

# assign explicit bin labels once
work["_x_bin"] = pd.cut(work[x_col], bins=bins, include_lowest=True, right=False)
work = work[work["_x_bin"].notna()].copy()
work["_x_mid"] = work["_x_bin"].apply(lambda iv: 0.5 * (iv.left + iv.right))

populated = (
    work.groupby("_x_mid", observed=True)
    .size()
    .reset_index(name="n_rows")
)
populated = populated[populated["n_rows"] >= min_bin_count].sort_values("_x_mid")
populated_xmids = populated["_x_mid"].tolist()

rows = []
binned_rows = []

def run_variant(label, subdf):
    bv = binned_variance(subdf, x_col=x_col, y_col=y_col, bins=bins, min_count=min_bin_count)
    if len(bv) < 2:
        rows.append({
            "variant": label,
            "rows_used": len(subdf),
            "n_bins_used": len(bv),
            "obs_slope": np.nan,
            "intercept": np.nan,
            "note": "insufficient bins",
        })
        return

    fit = fit_linear(bv["x_mid"].values, bv["var_y"].values)

    rows.append({
        "variant": label,
        "rows_used": len(subdf),
        "n_bins_used": len(bv),
        "obs_slope": fit["slope"],
        "intercept": fit["intercept"],
        "note": "",
    })

    bb = bv.copy()
    bb["variant"] = label
    binned_rows.append(bb)

# full run
run_variant("full", work)

# leave-one-bin-out
for xmid in populated_xmids:
    sub = work[work["_x_mid"] != xmid].copy()
    run_variant(f"drop_bin_{xmid:.4f}", sub)

summary_df = pd.DataFrame(rows)
binned_df = pd.concat(binned_rows, ignore_index=True) if binned_rows else pd.DataFrame()

for p in [out_summary_csv, out_binned_csv, out_png]:
    p.parent.mkdir(parents=True, exist_ok=True)

summary_df.to_csv(out_summary_csv, index=False)
binned_df.to_csv(out_binned_csv, index=False)

plt.figure(figsize=(8, 5))
for variant, g in binned_df.groupby("variant", observed=True):
    plt.plot(g["x_mid"], g["var_y"], marker="o", label=variant)
plt.xlabel(r"$\log_{10}(M_{\rm BH}/M_\odot)$")
plt.ylabel(r"$\mathrm{Var}(\Phi_{\rm BH})$")
plt.title("GAMA leave-one-mass-bin-out")
plt.legend()
plt.tight_layout()
plt.savefig(out_png, dpi=160)
plt.close()

print(f"[ok] wrote {out_summary_csv}")
print(f"[ok] wrote {out_binned_csv}")
print(f"[ok] wrote {out_png}")
print(summary_df.to_string(index=False))
