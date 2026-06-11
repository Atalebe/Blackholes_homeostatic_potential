# src/sim/60_verify_intermediate_mass_class_gating.py
from pathlib import Path
import re
import numpy as np
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

catalog_csv = Path(cfg["data"]["catalog_csv"])
stable_core_csv = Path(cfg["data"]["stable_core_csv"])
out_summary_csv = Path(cfg["outputs"]["summary_csv"])
out_intermediate_csv = Path(cfg["outputs"]["intermediate_csv"])

df = pd.read_csv(catalog_csv).copy()
df["bh_id"] = df["bh_id"].astype(str)

stable = pd.read_csv(stable_core_csv).copy()
stable_ids = set(stable["bh_id"].astype(str).tolist())

if "final_mass_class" not in df.columns:
    raise KeyError("Missing final_mass_class")

def parse_mid(label: str):
    m = re.match(r"^\s*([0-9.]+)_([0-9.]+)\s*$", str(label))
    if not m:
        return np.nan
    a, b = float(m.group(1)), float(m.group(2))
    return 0.5 * (a + b)

mass_classes = (
    pd.DataFrame({"final_mass_class": sorted(df["final_mass_class"].dropna().unique())})
)
mass_classes["mass_mid"] = mass_classes["final_mass_class"].apply(parse_mid)
mass_classes = mass_classes.sort_values("mass_mid").reset_index(drop=True)

if len(mass_classes) <= 2:
    intermediate_classes = []
else:
    intermediate_classes = mass_classes["final_mass_class"].iloc[1:-1].tolist()

df["in_stable_core"] = df["bh_id"].isin(stable_ids)

summary = (
    df.groupby("final_mass_class", observed=True)
      .agg(
          n_bh=("bh_id", "size"),
          median_ripeness_score=("ripeness_score", "median"),
          median_ripeness_bh=("ripeness_bh", "median"),
          frac_high_ripeness=("ripeness_class", lambda x: np.mean(pd.Series(x) == "high_ripeness")),
          frac_low_ripeness=("ripeness_class", lambda x: np.mean(pd.Series(x) == "low_ripeness")),
          stable_core_n=("in_stable_core", "sum"),
          stable_core_fraction=("in_stable_core", "mean"),
      )
      .reset_index()
      .merge(mass_classes, on="final_mass_class", how="left")
      .sort_values("mass_mid")
      .reset_index(drop=True)
)

intermediate_df = summary[summary["final_mass_class"].isin(intermediate_classes)].copy()

for p in [out_summary_csv, out_intermediate_csv]:
    p.parent.mkdir(parents=True, exist_ok=True)

summary.to_csv(out_summary_csv, index=False)
intermediate_df.to_csv(out_intermediate_csv, index=False)

print(f"[ok] wrote {out_summary_csv}")
print(f"[ok] wrote {out_intermediate_csv}")
print(summary.to_string(index=False))
if len(intermediate_df) == 0:
    print("[info] no intermediate mass classes found in this catalogue")
else:
    print(intermediate_df.to_string(index=False))
