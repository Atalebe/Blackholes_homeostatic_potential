from pathlib import Path
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

for key in ["age", "kin"]:
    in_csv = Path(cfg["data"][f"{key}_input"])
    out_csv = Path(cfg["outputs"][f"{key}_output"])

    df = pd.read_csv(in_csv).copy()

    if "role" not in df.columns:
        raise KeyError(f"'role' column not found in {in_csv}")

    df["role_seed_vs_nonseed"] = df["role"].astype(str).apply(
        lambda x: "seed" if x == "seed" else "nonseed"
    )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)

    print(f"[ok] wrote {out_csv}")
    print(df[["plateifu", "role", "role_seed_vs_nonseed"]].head(12).to_string(index=False))
