from pathlib import Path
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

prebuilt = pd.read_csv(cfg["data"]["prebuilt_csv"]).copy()
rebuilt = pd.read_parquet(cfg["data"]["rebuilt_parquet"]).copy()

prebuilt["gal_id"] = prebuilt["gal_id"].astype(str)
rebuilt["gal_id"] = rebuilt["gal_id"].astype(str)

cmp = prebuilt.merge(
    rebuilt[["gal_id", "logMstar", "logMbh", "mdot_bh", "z", "sigma_star", "phi_bh", "S_sigma_raw"]],
    on="gal_id",
    how="inner",
    suffixes=("_prebuilt", "_rebuilt"),
)

out = Path(cfg["outputs"]["comparison_csv"])
out.parent.mkdir(parents=True, exist_ok=True)
cmp.to_csv(out, index=False)

print(f"[ok] wrote {out}")
print(f"[info] matched rows={len(cmp)}")
print(cmp.head().to_string(index=False))
