# src/sim/56_bh_ripeness_decoupling_audit.py
from pathlib import Path

import pandas as pd
import numpy as np

from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

catalog_csv = Path(cfg["data"]["catalog_csv"])
summary_out = Path(cfg["outputs"]["summary_csv"])

df = pd.read_csv(catalog_csv).copy()

needed = [
    "category",
    "final_mass_class",
    "ripeness_score",
    "ripeness_bh",
    "contrib_ripeness_bh" if "contrib_ripeness_bh" in df.columns else None,
]
needed = [x for x in needed if x is not None]

group_cols = cfg["context"]["group_cols"]

agg_map = {
    "n_bh": ("bh_id", "size"),
    "ripeness_score_median": ("ripeness_score", "median"),
    "ripeness_bh_median": ("ripeness_bh", "median"),
    "log10_mbh_final_median": ("log10_mbh_final", "median"),
    "track_median_lambda_median": ("track_median_lambda", "median"),
    "track_median_phi_median": ("track_median_phi", "median"),
    "n_track_median": ("n_track", "median"),
    "ripeness_bh_hat_median": ("ripeness_bh_hat", "median"),
    "commitment_mass_hat_median": ("commitment_mass_hat", "median"),
    "quiet_hat_median": ("quiet_hat", "median"),
    "settlement_hat_median": ("settlement_hat", "median"),
    "persistence_hat_median": ("persistence_hat", "median"),
}

if "contrib_ripeness_bh" in df.columns:
    agg_map["contrib_ripeness_bh_median"] = ("contrib_ripeness_bh", "median")
if "contrib_commitment_mass" in df.columns:
    agg_map["contrib_commitment_mass_median"] = ("contrib_commitment_mass", "median")
if "contrib_quiet" in df.columns:
    agg_map["contrib_quiet_median"] = ("contrib_quiet", "median")
if "contrib_settlement" in df.columns:
    agg_map["contrib_settlement_median"] = ("contrib_settlement", "median")
if "contrib_persistence" in df.columns:
    agg_map["contrib_persistence_median"] = ("contrib_persistence", "median")

summary = (
    df.groupby(group_cols, observed=True)
      .agg(**agg_map)
      .reset_index()
)

summary_out.parent.mkdir(parents=True, exist_ok=True)
summary.to_csv(summary_out, index=False)

print(f"[ok] wrote {summary_out}")
print(summary.to_string(index=False))
