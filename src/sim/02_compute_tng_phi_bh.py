from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml
from src.core.normalize import apply_within_group
from src.core.state_vector import compute_phi_bh

cfg = load_yaml(CONFIG_PATH)
infile = Path(cfg["outputs"]["base_catalog_out"])
if not infile.exists():
    raise FileNotFoundError(f"Missing base catalog: {infile}")

df = pd.read_parquet(infile).reset_index(drop=True)

df = apply_within_group(df, "bh_mass_class", "H_raw", "H_hat")

if np.nanstd(df["S_raw"].values) > 0:
    df = apply_within_group(df, "bh_mass_class", "S_raw", "S_hat")
else:
    df["S_hat"] = 0.0

df = compute_phi_bh(df, h_hat_col="H_hat", s_hat_col="S_hat")

out = Path(cfg["outputs"]["phi_catalog_out"])
out.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(out, index=False)

print(f"[ok] wrote {out}")
print(df[["H_hat", "S_hat", "phi_bh"]].describe().to_string())
