# src/sim/51_build_bh_ripeness_rankings.py
from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)


def robust_hat(series: pd.Series, mad_floor: float = 0.1) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med))
    if not np.isfinite(mad) or mad < mad_floor:
        mad = mad_floor
    return (x - med) / mad


def within_group_hat(
    df: pd.DataFrame,
    value_col: str,
    group_cols: list[str],
    out_col: str,
    mad_floor: float,
) -> pd.DataFrame:
    out = df.copy()
    out[out_col] = np.nan
    for _, idx in out.groupby(group_cols, observed=True).groups.items():
        idx = list(idx)
        out.loc[idx, out_col] = robust_hat(out.loc[idx, value_col], mad_floor=mad_floor).values
    return out


input_csv = Path(cfg["data"]["input_csv"])
out_catalog_csv = Path(cfg["outputs"]["catalog_csv"])
out_summary_csv = Path(cfg["outputs"]["summary_csv"])
out_top_csv = Path(cfg["outputs"]["top_csv"])
out_bottom_csv = Path(cfg["outputs"]["bottom_csv"])
out_corr_csv = Path(cfg["outputs"]["correlations_csv"])

group_cols = cfg["context"]["group_cols"]
mad_floor = float(cfg["normalization"].get("mad_floor", 0.1))
top_n = int(cfg["outputs"].get("top_n", 20))
bottom_n = int(cfg["outputs"].get("bottom_n", 20))

weights = cfg["weights"]
w_res = float(weights["ripeness_bh"])
w_mass = float(weights["commitment_mass"])
w_quiet = float(weights["quiet_quietness"])
w_settle = float(weights["settlement_phi"])
w_persist = float(weights["persistence_tracks"])

df = pd.read_csv(input_csv).copy()

required = [
    "bh_id",
    "category",
    "final_mass_class",
    "log10_mbh_final",
    "ripeness_bh",
    "track_median_lambda",
    "track_median_phi",
    "n_track",
]
missing = [c for c in required if c not in df.columns]
if missing:
    raise KeyError(f"Missing required columns: {missing}")

work = df.copy()

work["log10_n_track"] = np.log10(pd.to_numeric(work["n_track"], errors="coerce"))
work["quiet_raw"] = -pd.to_numeric(work["track_median_lambda"], errors="coerce")

# settlement is better when closer to class median phi
work["phi_group_median"] = (
    work.groupby(group_cols, observed=True)["track_median_phi"]
    .transform("median")
)
work["settle_raw"] = -np.abs(
    pd.to_numeric(work["track_median_phi"], errors="coerce")
    - pd.to_numeric(work["phi_group_median"], errors="coerce")
)

for col in ["ripeness_bh", "log10_mbh_final", "quiet_raw", "settle_raw", "log10_n_track"]:
    work[col] = pd.to_numeric(work[col], errors="coerce")

work = work.dropna(
    subset=["ripeness_bh", "log10_mbh_final", "quiet_raw", "settle_raw", "log10_n_track"]
).copy()

work = within_group_hat(work, "ripeness_bh", group_cols, "ripeness_bh_hat", mad_floor)
work = within_group_hat(work, "log10_mbh_final", group_cols, "commitment_mass_hat", mad_floor)
work = within_group_hat(work, "quiet_raw", group_cols, "quiet_hat", mad_floor)
work = within_group_hat(work, "settle_raw", group_cols, "settlement_hat", mad_floor)
work = within_group_hat(work, "log10_n_track", group_cols, "persistence_hat", mad_floor)

work["ripeness_score"] = (
    w_res * work["ripeness_bh_hat"]
    + w_mass * work["commitment_mass_hat"]
    + w_quiet * work["quiet_hat"]
    + w_settle * work["settlement_hat"]
    + w_persist * work["persistence_hat"]
)

work = work.sort_values("ripeness_score", ascending=False).reset_index(drop=True)
work["ripeness_rank_global"] = np.arange(1, len(work) + 1)

work["ripeness_rank_within_context"] = (
    work.groupby(group_cols, observed=True)["ripeness_score"]
    .rank(method="dense", ascending=False)
    .astype(int)
)

q25 = work["ripeness_score"].quantile(0.25)
q75 = work["ripeness_score"].quantile(0.75)

def classify(x: float) -> str:
    if x <= q25:
        return "low_ripeness"
    if x >= q75:
        return "high_ripeness"
    return "mid_ripeness"

work["ripeness_class"] = work["ripeness_score"].apply(classify)

summary = (
    work.groupby(group_cols, observed=True)
    .agg(
        n_bh=("bh_id", "size"),
        ripeness_score_median=("ripeness_score", "median"),
        ripeness_bh_median=("ripeness_bh", "median"),
        log10_mbh_final_median=("log10_mbh_final", "median"),
        track_median_lambda_median=("track_median_lambda", "median"),
        track_median_phi_median=("track_median_phi", "median"),
        n_track_median=("n_track", "median"),
        frac_has_major=("has_major", "mean") if "has_major" in work.columns else ("bh_id", lambda x: np.nan),
    )
    .reset_index()
)

corr_rows = []
for c in ["ripeness_bh", "log10_mbh_final", "track_median_lambda", "track_median_phi", "n_track"]:
    if c in work.columns:
        corr_rows.append(
            {
                "x": "ripeness_score",
                "y": c,
                "spearman": work["ripeness_score"].corr(work[c], method="spearman"),
                "pearson": work["ripeness_score"].corr(work[c], method="pearson"),
            }
        )
corr_df = pd.DataFrame(corr_rows)

top_df = work.head(top_n).copy()
bottom_df = work.tail(bottom_n).copy()

for p in [out_catalog_csv, out_summary_csv, out_top_csv, out_bottom_csv, out_corr_csv]:
    p.parent.mkdir(parents=True, exist_ok=True)

work.to_csv(out_catalog_csv, index=False)
summary.to_csv(out_summary_csv, index=False)
top_df.to_csv(out_top_csv, index=False)
bottom_df.to_csv(out_bottom_csv, index=False)
corr_df.to_csv(out_corr_csv, index=False)

print(f"[ok] wrote {out_catalog_csv}")
print(f"[ok] wrote {out_summary_csv}")
print(f"[ok] wrote {out_top_csv}")
print(f"[ok] wrote {out_bottom_csv}")
print(f"[ok] wrote {out_corr_csv}")
print(summary.to_string(index=False))
print(top_df[[
    "bh_id", "category", "final_mass_class", "ripeness_score",
    "ripeness_rank_global", "ripeness_rank_within_context",
    "ripeness_bh", "log10_mbh_final", "track_median_lambda",
    "track_median_phi", "n_track", "ripeness_class"
]].head(10).to_string(index=False))
