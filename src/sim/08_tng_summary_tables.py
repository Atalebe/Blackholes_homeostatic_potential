from pathlib import Path
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)
window_in = Path(cfg["outputs"]["window_catalog_out"])
if not window_in.exists():
    raise FileNotFoundError(f"Missing window catalog: {window_in}")

df = pd.read_parquet(window_in)

summary = (
    df.groupby("bh_mass_class", observed=False)
      .agg(
          n=("phi_bh", "size"),
          phi_median=("phi_bh", "median"),
          phi_p16=("phi_bh", lambda x: x.quantile(0.16)),
          phi_p84=("phi_bh", lambda x: x.quantile(0.84)),
          frac_in_window=("in_window", "mean"),
          log10_mbh_median=("log10_mbh", "median"),
      )
      .reset_index()
)

ripeness_path = Path("outputs/tables/tng300_ripeness.csv")
if ripeness_path.exists():
    rip = pd.read_csv(ripeness_path)
    rip_sum = (
        rip.groupby("final_mass_class", observed=False)
           .agg(
               ripeness_median=("ripeness_bh", "median"),
               ripeness_mean=("ripeness_bh", "mean"),
           )
           .reset_index()
           .rename(columns={"final_mass_class": "bh_mass_class"})
    )
    summary = summary.merge(rip_sum, on="bh_mass_class", how="left")

out = Path(cfg["outputs"]["class_summary_out"])
out.parent.mkdir(parents=True, exist_ok=True)
summary.to_csv(out, index=False)

print(f"[ok] wrote {out}")
print(summary.to_string(index=False))
