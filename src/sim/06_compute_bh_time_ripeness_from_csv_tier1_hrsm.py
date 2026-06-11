from pathlib import Path
import pandas as pd
from src.utils.config import load_yaml
from src.core.normalize import apply_within_group
from src.core.state_vector import compute_phi_bh
from src.core.windows import define_quantile_window
from src.core.ripeness import compute_residence_fraction

cfg = load_yaml(CONFIG_PATH)
infile = Path(cfg["outputs"]["track_catalog_out"])
df = pd.read_parquet(infile).reset_index(drop=True)

df = apply_within_group(df, "final_mass_class", "H_t_raw", "H_hat")
df = apply_within_group(df, "final_mass_class", "S_t_raw", "S_hat")
df = compute_phi_bh(df, h_hat_col="H_hat", s_hat_col="S_hat")

df = define_quantile_window(
    df,
    group_col="final_mass_class",
    phi_col="phi_bh",
    q_low=cfg["window"]["q_low"],
    q_high=cfg["window"]["q_high"],
)
df = df.rename(columns={"in_window": "in_window_t"})

track_phi_out = Path(cfg["outputs"]["track_phi_out"])
track_phi_out.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(track_phi_out, index=False)

ripeness = compute_residence_fraction(
    df,
    id_col="bh_id",
    time_col="t",
    in_window_col="in_window_t",
)

meta = (
    df.groupby("bh_id", as_index=False, observed=False)
      .agg(
          category=("category", "last"),
          final_mass_class=("final_mass_class", "last"),
          log10_mbh_final=("log10_mbh_final", "last"),
          has_major=("has_major", "last"),
          lambda_med_track=("lambda_bh_med_track", "last"),
          track_median_phi=("phi_bh", "median"),
          track_median_lambda=("lambda_bh_t", "median"),
          track_median_S=("S_t_raw", "median"),
          n_track=("t", "size"),
      )
)

ripeness = ripeness.merge(meta, on=["bh_id", "n_track"], how="left")

out = Path(cfg["outputs"]["ripeness_out"])
out.parent.mkdir(parents=True, exist_ok=True)
ripeness.to_csv(out, index=False)

summary = (
    ripeness.groupby(["category", "final_mass_class", "has_major"], dropna=False, observed=False)
            .agg(
                n_bh=("bh_id", "size"),
                ripeness_median=("ripeness_bh", "median"),
                ripeness_mean=("ripeness_bh", "mean"),
                lambda_median=("track_median_lambda", "median"),
                S_median=("track_median_S", "median"),
            )
            .reset_index()
)

summary_out = Path(cfg["outputs"]["time_summary_out"])
summary_out.parent.mkdir(parents=True, exist_ok=True)
summary.to_csv(summary_out, index=False)

print(f"[ok] wrote {track_phi_out}")
print(f"[ok] wrote {out}")
print(f"[ok] wrote {summary_out}")
print(summary.to_string(index=False))
