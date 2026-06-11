# src/sim/52_bh_ripeness_diagnostics.py
from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

catalog_csv = Path(cfg["data"]["catalog_csv"])
out_context_top_csv = Path(cfg["outputs"]["context_top_csv"])
out_context_bottom_csv = Path(cfg["outputs"]["context_bottom_csv"])
out_class_summary_csv = Path(cfg["outputs"]["class_summary_csv"])
out_rank_overlap_csv = Path(cfg["outputs"]["rank_overlap_csv"])

group_cols = cfg["context"]["group_cols"]
top_n = int(cfg["outputs"].get("top_n", 10))
bottom_n = int(cfg["outputs"].get("bottom_n", 10))

df = pd.read_csv(catalog_csv).copy()

context_top = (
    df.sort_values(group_cols + ["ripeness_score"], ascending=[True] * len(group_cols) + [False])
      .groupby(group_cols, observed=True)
      .head(top_n)
      .copy()
)

context_bottom = (
    df.sort_values(group_cols + ["ripeness_score"], ascending=[True] * len(group_cols) + [True])
      .groupby(group_cols, observed=True)
      .head(bottom_n)
      .copy()
)

class_summary = (
    df.groupby("ripeness_class", observed=True)
      .agg(
          n_bh=("bh_id", "size"),
          ripeness_score_median=("ripeness_score", "median"),
          ripeness_bh_median=("ripeness_bh", "median"),
          log10_mbh_final_median=("log10_mbh_final", "median"),
          track_median_lambda_median=("track_median_lambda", "median"),
          track_median_phi_median=("track_median_phi", "median"),
          n_track_median=("n_track", "median"),
      )
      .reset_index()
)

# overlap between top ripeness_score and top ripeness_bh
n_overlap = int(cfg["outputs"].get("overlap_n", 25))
top_score = set(df.nlargest(n_overlap, "ripeness_score")["bh_id"].tolist())
top_res = set(df.nlargest(n_overlap, "ripeness_bh")["bh_id"].tolist())
overlap = len(top_score & top_res)

rank_overlap = pd.DataFrame([{
    "top_n": n_overlap,
    "score_top_n": len(top_score),
    "residence_top_n": len(top_res),
    "overlap_n": overlap,
    "overlap_fraction_vs_score": overlap / len(top_score) if top_score else np.nan,
    "overlap_fraction_vs_residence": overlap / len(top_res) if top_res else np.nan,
}])

for p in [out_context_top_csv, out_context_bottom_csv, out_class_summary_csv, out_rank_overlap_csv]:
    p.parent.mkdir(parents=True, exist_ok=True)

context_top.to_csv(out_context_top_csv, index=False)
context_bottom.to_csv(out_context_bottom_csv, index=False)
class_summary.to_csv(out_class_summary_csv, index=False)
rank_overlap.to_csv(out_rank_overlap_csv, index=False)

print(f"[ok] wrote {out_context_top_csv}")
print(f"[ok] wrote {out_context_bottom_csv}")
print(f"[ok] wrote {out_class_summary_csv}")
print(f"[ok] wrote {out_rank_overlap_csv}")
print(class_summary.to_string(index=False))
print(rank_overlap.to_string(index=False))
