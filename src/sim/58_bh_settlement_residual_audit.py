# src/sim/58_bh_settlement_residual_audit.py
from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

catalog_csv = Path(cfg["data"]["catalog_csv"])
out_focus_csv = Path(cfg["outputs"]["focus_csv"])
out_context_csv = Path(cfg["outputs"]["context_csv"])
out_summary_csv = Path(cfg["outputs"]["summary_csv"])

focus_ids = [str(x) for x in cfg["focus"].get("bh_ids", [])]
focus_ranks = cfg["focus"].get("ranks", [])

df = pd.read_csv(catalog_csv).copy()
df["bh_id"] = df["bh_id"].astype(str)

required = [
    "bh_id",
    "category",
    "final_mass_class",
    "track_median_phi",
    "phi_group_median",
    "settle_raw",
    "settlement_hat",
    "ripeness_score",
    "ripeness_rank_global",
]
missing = [c for c in required if c not in df.columns]
if missing:
    raise KeyError(f"Missing required columns: {missing}")

focus_mask = df["bh_id"].isin(focus_ids)
if focus_ranks:
    focus_mask = focus_mask | df["ripeness_rank_global"].isin(focus_ranks)

focus_df = df[focus_mask].copy()

context_rows = []
for _, row in focus_df.iterrows():
    mask = (
        (df["category"] == row["category"]) &
        (df["final_mass_class"] == row["final_mass_class"])
    )
    g = df.loc[mask].copy()

    phi = pd.to_numeric(g["track_median_phi"], errors="coerce")
    settle_raw = pd.to_numeric(g["settle_raw"], errors="coerce")
    settle_hat = pd.to_numeric(g["settlement_hat"], errors="coerce")

    phi_rank_low = int((phi < row["track_median_phi"]).sum() + 1)
    settle_raw_rank_low = int((settle_raw < row["settle_raw"]).sum() + 1)
    settle_hat_rank_low = int((settle_hat < row["settlement_hat"]).sum() + 1)

    context_rows.append({
        "bh_id": row["bh_id"],
        "category": row["category"],
        "final_mass_class": row["final_mass_class"],
        "context_n": len(g),
        "track_median_phi": row["track_median_phi"],
        "phi_group_median": row["phi_group_median"],
        "phi_minus_group_median": row["track_median_phi"] - row["phi_group_median"],
        "settle_raw": row["settle_raw"],
        "settlement_hat": row["settlement_hat"],
        "ripeness_score": row["ripeness_score"],
        "ripeness_rank_global": row["ripeness_rank_global"],
        "phi_rank_low": phi_rank_low,
        "settle_raw_rank_low": settle_raw_rank_low,
        "settlement_hat_rank_low": settle_hat_rank_low,
        "phi_context_min": phi.min(),
        "phi_context_p16": phi.quantile(0.16),
        "phi_context_median": phi.median(),
        "phi_context_p84": phi.quantile(0.84),
        "phi_context_max": phi.max(),
        "settle_raw_context_min": settle_raw.min(),
        "settle_raw_context_p16": settle_raw.quantile(0.16),
        "settle_raw_context_median": settle_raw.median(),
        "settle_raw_context_p84": settle_raw.quantile(0.84),
        "settle_raw_context_max": settle_raw.max(),
        "settlement_hat_context_min": settle_hat.min(),
        "settlement_hat_context_p16": settle_hat.quantile(0.16),
        "settlement_hat_context_median": settle_hat.median(),
        "settlement_hat_context_p84": settle_hat.quantile(0.84),
        "settlement_hat_context_max": settle_hat.max(),
    })

context_df = pd.DataFrame(context_rows)

summary = (
    context_df[[
        "bh_id",
        "category",
        "final_mass_class",
        "ripeness_rank_global",
        "phi_minus_group_median",
        "settle_raw",
        "settlement_hat",
        "settlement_hat_rank_low",
        "context_n",
    ]]
    .sort_values("ripeness_rank_global")
    .reset_index(drop=True)
)

for p in [out_focus_csv, out_context_csv, out_summary_csv]:
    p.parent.mkdir(parents=True, exist_ok=True)

focus_df.to_csv(out_focus_csv, index=False)
context_df.to_csv(out_context_csv, index=False)
summary.to_csv(out_summary_csv, index=False)

print(f"[ok] wrote {out_focus_csv}")
print(f"[ok] wrote {out_context_csv}")
print(f"[ok] wrote {out_summary_csv}")
print(summary.to_string(index=False))
