# src/sim/55_bh_ripeness_leave_one_out_audit.py
from pathlib import Path
import pandas as pd
import numpy as np
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

catalog_csv = Path(cfg["data"]["catalog_csv"])
summary_out = Path(cfg["outputs"]["summary_csv"])
focus_out = Path(cfg["outputs"]["focus_csv"])

focus_ids = set(str(x) for x in cfg["focus"]["bh_ids"])
top_n = int(cfg["outputs"].get("top_n", 25))

df = pd.read_csv(catalog_csv).copy()
df["bh_id"] = df["bh_id"].astype(str)

components = {
    "ripeness_bh_hat": float(cfg["weights"]["ripeness_bh"]),
    "commitment_mass_hat": float(cfg["weights"]["commitment_mass"]),
    "quiet_hat": float(cfg["weights"]["quiet_quietness"]),
    "settlement_hat": float(cfg["weights"]["settlement_phi"]),
    "persistence_hat": float(cfg["weights"]["persistence_tracks"]),
}

for comp in components:
    if comp not in df.columns:
        raise KeyError(f"Missing required component column: {comp}")

variants = {"full": components.copy()}
for leave_out in components:
    vv = {k: v for k, v in components.items() if k != leave_out}
    s = sum(vv.values())
    vv = {k: v / s for k, v in vv.items()}
    variants[f"drop_{leave_out.replace('_hat','')}"] = vv

for name, weights in variants.items():
    score_col = f"score_{name}"
    rank_col = f"rank_{name}"
    df[score_col] = 0.0
    for comp, w in weights.items():
        df[score_col] += w * df[comp]
    df[rank_col] = df[score_col].rank(method="dense", ascending=False).astype(int)

base_top = set(df.nsmallest(top_n, "rank_full")["bh_id"].tolist())

summary_rows = []
for name in variants:
    rank_col = f"rank_{name}"
    score_col = f"score_{name}"
    top_set = set(df.nsmallest(top_n, rank_col)["bh_id"].tolist())
    overlap = len(base_top & top_set)
    summary_rows.append({
        "variant": name,
        "top_n": top_n,
        "overlap_with_full_top_n": overlap,
        "overlap_fraction": overlap / top_n if top_n > 0 else np.nan,
        "spearman_vs_full": df["score_full"].corr(df[score_col], method="spearman"),
        "pearson_vs_full": df["score_full"].corr(df[score_col], method="pearson"),
    })

focus_cols = ["bh_id", "category", "final_mass_class", "score_full", "rank_full"]
for name in variants:
    if name == "full":
        continue
    focus_cols += [f"score_{name}", f"rank_{name}"]

focus_df = (
    df[df["bh_id"].isin(focus_ids)][focus_cols]
    .sort_values("rank_full")
    .copy()
)
summary_df = pd.DataFrame(summary_rows)

summary_out.parent.mkdir(parents=True, exist_ok=True)
focus_out.parent.mkdir(parents=True, exist_ok=True)

summary_df.to_csv(summary_out, index=False)
focus_df.to_csv(focus_out, index=False)

print(f"[ok] wrote {summary_out}")
print(f"[ok] wrote {focus_out}")
print(summary_df.to_string(index=False))
print(focus_df.to_string(index=False))
