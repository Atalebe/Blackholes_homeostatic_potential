from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml
from src.core.permutation_nulls import variance_slope_null

cfg = load_yaml(CONFIG_PATH)
infile = Path(cfg["outputs"]["window_catalog_out"])
if not infile.exists():
    raise FileNotFoundError(f"Missing window catalog: {infile}")

df = pd.read_parquet(infile)
vs = cfg["variance_scaling"]
bins = np.arange(vs["bin_start"], vs["bin_stop"] + vs["bin_step"], vs["bin_step"])
n_perm = N_PERM_OVERRIDE if N_PERM_OVERRIDE is not None else cfg["nulls"]["n_perm"]

null = variance_slope_null(
    df,
    group_col="bh_mass_class",
    x_col="log10_mbh",
    y_col="phi_bh",
    bins=bins,
    n_perm=n_perm,
    min_count=vs["min_bin_count"],
    seed=cfg["run"]["seed"],
)

null_slopes_out = Path(cfg["outputs"]["null_slopes_out"])
null_slopes_out.parent.mkdir(parents=True, exist_ok=True)
pd.DataFrame({"null_slope": null["null_slopes"]}).to_csv(null_slopes_out, index=False)

summary_out = Path(cfg["outputs"]["null_summary_out"])
pd.DataFrame([{
    "obs_slope": null["obs_slope"],
    "p_one_sided_negative": null["p_one_sided_negative"],
    "n_perm": len(null["null_slopes"]),
}]).to_csv(summary_out, index=False)

print(f"[ok] wrote {null_slopes_out}")
print(f"[ok] wrote {summary_out}")
