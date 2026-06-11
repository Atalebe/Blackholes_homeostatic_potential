# src/sim/57_bh_ripeness_stable_core_overlap.py
from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

catalog_csv = Path(cfg["data"]["catalog_csv"])
out_core_csv = Path(cfg["outputs"]["stable_core_csv"])
out_summary_csv = Path(cfg["outputs"]["summary_csv"])
out_membership_csv = Path(cfg["outputs"]["membership_csv"])

top_n = int(cfg["run"].get("top_n", 25))

weights = {
    "ripeness_bh_hat": float(cfg["weights"]["ripeness_bh"]),
    "commitment_mass_hat": float(cfg["weights"]["commitment_mass"]),
    "quiet_hat": float(cfg["weights"]["quiet_quietness"]),
    "settlement_hat": float(cfg["weights"]["settlement_phi"]),
    "persistence_hat": float(cfg["weights"]["persistence_tracks"]),
}

df = pd.read_csv(catalog_csv).copy()
df["bh_id"] = df["bh_id"].astype(str)

needed = list(weights.keys())
missing = [c for c in needed if c not in df.columns]
if missing:
    raise KeyError(f"Missing required columns: {missing}")

def build_score(frame: pd.DataFrame, wmap: dict) -> pd.Series:
    s = pd.Series(0.0, index=frame.index)
    for comp, w in wmap.items():
        s = s + w * pd.to_numeric(frame[comp], errors="coerce")
    return s

full_weights = weights.copy()

drop_quiet_weights = {k: v for k, v in weights.items() if k != "quiet_hat"}
s_quiet = sum(drop_quiet_weights.values())
drop_quiet_weights = {k: v / s_quiet for k, v in drop_quiet_weights.items()}

drop_persistence_weights = {k: v for k, v in weights.items() if k != "persistence_hat"}
s_persist = sum(drop_persistence_weights.values())
drop_persistence_weights = {k: v / s_persist for k, v in drop_persistence_weights.items()}

df["score_full"] = build_score(df, full_weights)
df["score_drop_quiet"] = build_score(df, drop_quiet_weights)
df["score_drop_persistence"] = build_score(df, drop_persistence_weights)

df["rank_full"] = df["score_full"].rank(method="dense", ascending=False).astype(int)
df["rank_drop_quiet"] = df["score_drop_quiet"].rank(method="dense", ascending=False).astype(int)
df["rank_drop_persistence"] = df["score_drop_persistence"].rank(method="dense", ascending=False).astype(int)

top_full = set(df.nsmallest(top_n, "rank_full")["bh_id"].tolist())
top_quiet = set(df.nsmallest(top_n, "rank_drop_quiet")["bh_id"].tolist())
top_persist = set(df.nsmallest(top_n, "rank_drop_persistence")["bh_id"].tolist())

stable_core = top_full & top_quiet & top_persist

membership = df[[
    "bh_id",
    "category",
    "final_mass_class",
    "score_full",
    "rank_full",
    "score_drop_quiet",
    "rank_drop_quiet",
    "score_drop_persistence",
    "rank_drop_persistence",
]].copy()

membership["in_top_full"] = membership["bh_id"].isin(top_full)
membership["in_top_drop_quiet"] = membership["bh_id"].isin(top_quiet)
membership["in_top_drop_persistence"] = membership["bh_id"].isin(top_persist)
membership["in_stable_core"] = membership["bh_id"].isin(stable_core)

stable_core_df = (
    membership[membership["in_stable_core"]]
    .sort_values(["rank_full", "rank_drop_quiet", "rank_drop_persistence"])
    .reset_index(drop=True)
)

summary = pd.DataFrame([{
    "top_n": top_n,
    "n_top_full": len(top_full),
    "n_top_drop_quiet": len(top_quiet),
    "n_top_drop_persistence": len(top_persist),
    "stable_core_n": len(stable_core),
    "stable_core_fraction_vs_top_n": len(stable_core) / top_n if top_n > 0 else np.nan,
    "overlap_full_vs_drop_quiet": len(top_full & top_quiet),
    "overlap_full_vs_drop_persistence": len(top_full & top_persist),
    "overlap_drop_quiet_vs_drop_persistence": len(top_quiet & top_persist),
}])

for p in [out_core_csv, out_summary_csv, out_membership_csv]:
    p.parent.mkdir(parents=True, exist_ok=True)

stable_core_df.to_csv(out_core_csv, index=False)
summary.to_csv(out_summary_csv, index=False)
membership.to_csv(out_membership_csv, index=False)

print(f"[ok] wrote {out_core_csv}")
print(f"[ok] wrote {out_summary_csv}")
print(f"[ok] wrote {out_membership_csv}")
print(summary.to_string(index=False))
print(stable_core_df.to_string(index=False))
