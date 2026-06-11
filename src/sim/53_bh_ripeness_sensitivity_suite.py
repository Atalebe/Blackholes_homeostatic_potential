# src/sim/53_bh_ripeness_sensitivity_suite.py
from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

catalog_csv = Path(cfg["data"]["catalog_csv"])
out_summary_csv = Path(cfg["outputs"]["summary_csv"])
out_overlap_csv = Path(cfg["outputs"]["overlap_csv"])

top_n = int(cfg["outputs"].get("top_n", 25))

df = pd.read_csv(catalog_csv).copy()

required = [
    "bh_id",
    "ripeness_bh_hat",
    "commitment_mass_hat",
    "quiet_hat",
    "settlement_hat",
    "persistence_hat",
]
missing = [c for c in required if c not in df.columns]
if missing:
    raise KeyError(f"Missing required columns: {missing}")

variants = {
    "residence_only": {
        "ripeness_bh_hat": 1.0,
    },
    "residence_plus_quiet": {
        "ripeness_bh_hat": 0.7,
        "quiet_hat": 0.3,
    },
    "full_composite": {
        "ripeness_bh_hat": 0.40,
        "commitment_mass_hat": 0.20,
        "quiet_hat": 0.15,
        "settlement_hat": 0.15,
        "persistence_hat": 0.10,
    },
    "without_mass": {
        "ripeness_bh_hat": 0.50,
        "quiet_hat": 0.20,
        "settlement_hat": 0.20,
        "persistence_hat": 0.10,
    },
    "without_persistence": {
        "ripeness_bh_hat": 0.45,
        "commitment_mass_hat": 0.25,
        "quiet_hat": 0.15,
        "settlement_hat": 0.15,
    },
}

score_cols = []
for name, weights in variants.items():
    score_col = f"score_{name}"
    score_cols.append(score_col)
    df[score_col] = 0.0
    for comp, w in weights.items():
        df[score_col] += w * df[comp]

summary_rows = []
overlap_rows = []

base_col = "score_full_composite"
base_top = set(df.nlargest(top_n, base_col)["bh_id"].tolist())

for sc in score_cols:
    summary_rows.append({
        "variant": sc.replace("score_", ""),
        "spearman_vs_full": df[base_col].corr(df[sc], method="spearman"),
        "pearson_vs_full": df[base_col].corr(df[sc], method="pearson"),
        "score_median": df[sc].median(),
        "score_std": df[sc].std(),
    })

    other_top = set(df.nlargest(top_n, sc)["bh_id"].tolist())
    overlap = len(base_top & other_top)
    overlap_rows.append({
        "variant": sc.replace("score_", ""),
        "top_n": top_n,
        "overlap_n_with_full": overlap,
        "overlap_fraction": overlap / top_n if top_n > 0 else np.nan,
    })

summary_df = pd.DataFrame(summary_rows)
overlap_df = pd.DataFrame(overlap_rows)

out_summary_csv.parent.mkdir(parents=True, exist_ok=True)
out_overlap_csv.parent.mkdir(parents=True, exist_ok=True)

summary_df.to_csv(out_summary_csv, index=False)
overlap_df.to_csv(out_overlap_csv, index=False)

print(f"[ok] wrote {out_summary_csv}")
print(f"[ok] wrote {out_overlap_csv}")
print(summary_df.to_string(index=False))
print(overlap_df.to_string(index=False))
