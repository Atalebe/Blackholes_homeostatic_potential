# src/obs/43_manga_full_ifu_role_views.py
from pathlib import Path
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

for key in ["age", "kin"]:
    df = pd.read_csv(cfg["data"][f"{key}_csv"]).copy()
    role = df["role"].astype(str).str.strip().str.lower()
    df["role_seed_vs_nonseed"] = role.where(role == "seed", "nonseed")

    out_csv = cfg["outputs"][f"{key}_roleviews_csv"]
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)

    print(f"[ok] wrote {out_csv}")
    print(df[["plateifu", "role", "role_seed_vs_nonseed"]].head(12).to_string(index=False))
