# src/sim/54_bh_ripeness_component_audit.py
from pathlib import Path

import pandas as pd
import numpy as np

from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

catalog_csv = Path(cfg["data"]["catalog_csv"])
summary_out = Path(cfg["outputs"]["summary_csv"])
top_out = Path(cfg["outputs"]["top_component_csv"])
bottom_out = Path(cfg["outputs"]["bottom_component_csv"])
focus_out = Path(cfg["outputs"]["focus_component_csv"])

top_n = int(cfg["outputs"].get("top_n", 20))
bottom_n = int(cfg["outputs"].get("bottom_n", 20))
focus_ids = set(str(x) for x in cfg["focus"]["bh_ids"])

weights = cfg["weights"]
w_res = float(weights["ripeness_bh"])
w_mass = float(weights["commitment_mass"])
w_quiet = float(weights["quiet_quietness"])
w_settle = float(weights["settlement_phi"])
w_persist = float(weights["persistence_tracks"])

df = pd.read_csv(catalog_csv).copy()

required = [
    "bh_id",
    "category",
    "final_mass_class",
    "ripeness_score",
    "ripeness_bh_hat",
    "commitment_mass_hat",
    "quiet_hat",
    "settlement_hat",
    "persistence_hat",
]
missing = [c for c in required if c not in df.columns]
if missing:
    raise KeyError(f"Missing required columns: {missing}")

df["bh_id"] = df["bh_id"].astype(str)

df["contrib_ripeness_bh"] = w_res * df["ripeness_bh_hat"]
df["contrib_commitment_mass"] = w_mass * df["commitment_mass_hat"]
df["contrib_quiet"] = w_quiet * df["quiet_hat"]
df["contrib_settlement"] = w_settle * df["settlement_hat"]
df["contrib_persistence"] = w_persist * df["persistence_hat"]

df["contrib_sum_check"] = (
    df["contrib_ripeness_bh"]
    + df["contrib_commitment_mass"]
    + df["contrib_quiet"]
    + df["contrib_settlement"]
    + df["contrib_persistence"]
)

summary = (
    df.groupby(["category", "final_mass_class"], observed=True)
      .agg(
          n_bh=("bh_id", "size"),
          ripeness_score_median=("ripeness_score", "median"),
          ripeness_bh_median=("ripeness_bh", "median") if "ripeness_bh" in df.columns else ("bh_id", lambda x: np.nan),
          contrib_ripeness_bh_median=("contrib_ripeness_bh", "median"),
          contrib_commitment_mass_median=("contrib_commitment_mass", "median"),
          contrib_quiet_median=("contrib_quiet", "median"),
          contrib_settlement_median=("contrib_settlement", "median"),
          contrib_persistence_median=("contrib_persistence", "median"),
          track_median_lambda_median=("track_median_lambda", "median") if "track_median_lambda" in df.columns else ("bh_id", lambda x: np.nan),
          track_median_phi_median=("track_median_phi", "median") if "track_median_phi" in df.columns else ("bh_id", lambda x: np.nan),
      )
      .reset_index()
)

show_cols = [
    "bh_id",
    "category",
    "final_mass_class",
    "ripeness_score",
    "ripeness_rank_global",
    "ripeness_rank_within_context",
    "ripeness_bh",
    "log10_mbh_final",
    "track_median_lambda",
    "track_median_phi",
    "n_track",
    "contrib_ripeness_bh",
    "contrib_commitment_mass",
    "contrib_quiet",
    "contrib_settlement",
    "contrib_persistence",
    "contrib_sum_check",
]

top_df = df.sort_values("ripeness_score", ascending=False).head(top_n)[show_cols].copy()
bottom_df = df.sort_values("ripeness_score", ascending=True).head(bottom_n)[show_cols].copy()
focus_df = df[df["bh_id"].isin(focus_ids)][show_cols].sort_values("ripeness_score", ascending=False).copy()

for p in [summary_out, top_out, bottom_out, focus_out]:
    p.parent.mkdir(parents=True, exist_ok=True)

summary.to_csv(summary_out, index=False)
top_df.to_csv(top_out, index=False)
bottom_df.to_csv(bottom_out, index=False)
focus_df.to_csv(focus_out, index=False)

print(f"[ok] wrote {summary_out}")
print(f"[ok] wrote {top_out}")
print(f"[ok] wrote {bottom_out}")
print(f"[ok] wrote {focus_out}")
print(summary.to_string(index=False))
print(focus_df.to_string(index=False))
