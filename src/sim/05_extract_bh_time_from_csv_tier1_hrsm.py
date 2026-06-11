from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml

def mass_class_from_bins(values, bins):
    edges = [b[0] for b in bins] + [bins[-1][1]]
    labels = [f"{lo:.1f}_{hi:.1f}" for lo, hi in bins]
    return pd.cut(values, bins=edges, labels=labels, include_lowest=True, right=False)

cfg = load_yaml(CONFIG_PATH)

timelines = pd.read_csv(cfg["data"]["timelines_csv"])
summary = pd.read_csv(cfg["data"]["summary_csv"])
mergers = pd.read_csv(cfg["data"]["merger_flags_csv"])

timelines = timelines.rename(columns={
    "time": "t",
    "mass": "mass_t",
    "mdot": "mdot_t",
    "lambda_bh": "lambda_bh_t",
})
summary = summary.rename(columns={"logMbh": "log10_mbh_final"})

if cfg["selection"].get("drop_infinite_lambda", True):
    timelines = timelines.replace([np.inf, -np.inf], np.nan)
    timelines = timelines.dropna(subset=["lambda_bh_t"])

track_n = timelines.groupby("bh_id").size().rename("n_track")
timelines = timelines.merge(track_n, left_on="bh_id", right_index=True, how="left")
timelines = timelines[timelines["n_track"] >= cfg["selection"]["min_track_length"]].copy()

summary_keep = summary[["bh_id", "log10_mbh_final", "n_entries", "t_span"]].copy()
merger_keep = mergers[["bh_id", "n_merger", "n_major", "n_minor", "has_major"]].copy()

df = timelines.merge(summary_keep, on="bh_id", how="left")
df = df.merge(merger_keep, on="bh_id", how="left")

bins = cfg["class_conditioning"]["final_mass_bins"]
df["final_mass_class"] = mass_class_from_bins(df["log10_mbh_final"], bins)
df = df.dropna(subset=["final_mass_class"]).reset_index(drop=True)

# Tier 1 reduced BH vector
df["H_t_raw"] = df["lambda_bh_t"]

track_med = (
    df.groupby("bh_id", observed=False)["lambda_bh_t"]
      .median()
      .rename("lambda_bh_med_track")
)
df = df.merge(track_med, left_on="bh_id", right_index=True, how="left")

# Stability = closeness to own regulated track
df["S_t_raw"] = -np.abs(df["lambda_bh_t"] - df["lambda_bh_med_track"])

out = Path(cfg["outputs"]["track_catalog_out"])
out.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(out, index=False)

print(f"[ok] wrote {out}")
print(df[[
    "bh_id", "category", "t", "lambda_bh_t", "lambda_bh_med_track",
    "H_t_raw", "S_t_raw", "log10_mbh_final", "final_mass_class", "has_major"
]].head().to_string(index=False))
print(df["final_mass_class"].value_counts(dropna=False).sort_index())
