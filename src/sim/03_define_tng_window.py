from pathlib import Path
import pandas as pd
from src.utils.config import load_yaml
from src.core.windows import define_quantile_window

cfg = load_yaml(CONFIG_PATH)
infile = Path(cfg["outputs"]["phi_catalog_out"])
if not infile.exists():
    raise FileNotFoundError(f"Missing phi catalog: {infile}")

df = pd.read_parquet(infile).reset_index(drop=True)
q_low = cfg["window"]["q_low"]
q_high = cfg["window"]["q_high"]

df = define_quantile_window(
    df,
    group_col="bh_mass_class",
    phi_col="phi_bh",
    q_low=q_low,
    q_high=q_high,
)

out = Path(cfg["outputs"]["window_catalog_out"])
out.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(out, index=False)

summary = (
    df.groupby("bh_mass_class", observed=False)
      .agg(
          n=("phi_bh", "size"),
          n_in_window=("in_window", "sum"),
          frac_in_window=("in_window", "mean"),
          phi_median=("phi_bh", "median"),
      )
      .reset_index()
)

summary_out = Path(cfg["outputs"]["class_summary_out"])
summary_out.parent.mkdir(parents=True, exist_ok=True)
summary.to_csv(summary_out, index=False)

print(f"[ok] wrote {out}")
print(f"[ok] wrote {summary_out}")
print(summary.to_string(index=False))
