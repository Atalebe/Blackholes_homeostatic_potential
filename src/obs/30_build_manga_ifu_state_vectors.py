from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

df = pd.read_csv(cfg["data"]["features_csv"]).copy()

# numeric coercion
for col in [
    "logMstar_drp_elpetro",
    "legacy_logMbh",
    "oiii5008_gflux_cen",
    "dn4000_delta_out_minus_cen",
    "stellar_sigma_delta_out_minus_cen",
]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

# keep extracted rows only
df = df[df["maps_found"] == True].copy()
if "extract_error" in df.columns:
    df = df[df["extract_error"].isna()].copy()

# attach host mass from manifest merge if already present, otherwise merge from runtime
if "logMstar_drp_elpetro" not in df.columns:
    runtime = pd.read_csv(cfg["data"]["runtime_csv"])
    runtime["plateifu"] = runtime["plateifu"].astype(str).str.strip()
    runtime["logMstar_drp_elpetro"] = pd.to_numeric(runtime["logMstar_drp_elpetro"], errors="coerce")
    df["plateifu"] = df["plateifu"].astype(str).str.strip()
    df = df.merge(runtime[["plateifu", "logMstar_drp_elpetro"]], on="plateifu", how="left")

# host-mass classes
bins = cfg["class_conditioning"]["host_mass_bins"]
edges = [b[0] for b in bins] + [bins[-1][1]]
labels = [f"{lo:.1f}_{hi:.1f}" for lo, hi in bins]
df["host_mass_class"] = pd.cut(
    df["logMstar_drp_elpetro"],
    bins=edges,
    labels=labels,
    include_lowest=True,
    right=False
)

df = df.dropna(subset=["host_mass_class"]).copy()

# H coordinate: central OIII throughput
df = df[np.isfinite(df["oiii5008_gflux_cen"]) & (df["oiii5008_gflux_cen"] > 0)].copy()
df["H_raw"] = np.log10(df["oiii5008_gflux_cen"])

def build_state(frame, s_delta_col, out_csv, summary_csv, state_name):
    work = frame.copy()
    work = work[np.isfinite(work[s_delta_col])].copy()

    med = (
        work.groupby("host_mass_class", observed=False)[s_delta_col]
        .median()
        .rename("class_median_delta")
    )
    work = work.merge(med, left_on="host_mass_class", right_index=True, how="left")
    work["S_raw"] = -np.abs(work[s_delta_col] - work["class_median_delta"])

    parts = []
    for cls, g in work.groupby("host_mass_class", observed=False):
        gg = g.copy()
        for raw, hat in [("H_raw", "H_hat"), ("S_raw", "S_hat")]:
            vals = pd.to_numeric(gg[raw], errors="coerce").to_numpy(dtype=float)
            medv = np.nanmedian(vals)
            mad = np.nanmedian(np.abs(vals - medv))
            mad_floor = float(cfg["normalization"]["mad_floor"])
            if not np.isfinite(mad) or mad < mad_floor:
                mad = mad_floor
            gg[hat] = (vals - medv) / mad
        parts.append(gg)

    out = pd.concat(parts, ignore_index=True)
    clip_abs = float(cfg["normalization"]["clip_abs"])
    out["H_hat"] = out["H_hat"].clip(-clip_abs, clip_abs)
    out["S_hat"] = out["S_hat"].clip(-clip_abs, clip_abs)
    out["phi_ifu"] = out["H_hat"] + out["S_hat"]

    q_low = float(cfg["window"]["q_low"])
    q_high = float(cfg["window"]["q_high"])

    windows = (
        out.groupby("host_mass_class", observed=False)["phi_ifu"]
        .quantile([q_low, q_high])
        .unstack()
        .rename(columns={q_low: "phi_q_low", q_high: "phi_q_high"})
    )
    out = out.merge(windows, left_on="host_mass_class", right_index=True, how="left")
    out["in_window"] = (
        (out["phi_ifu"] >= out["phi_q_low"]) &
        (out["phi_ifu"] <= out["phi_q_high"])
    )

    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)
    role_series = out["role"].astype(str).str.strip().str.lower()

    seed_rows = int((role_series == "seed").sum())
    nonseed_rows = int((role_series != "seed").sum())
    control_rows = int((role_series == "control").sum())
    parent_rows = int((role_series == "parent").sum())
    filler_rows = int((role_series == "filler").sum())

    summary = pd.DataFrame([{
        "state_name": state_name,
        "rows_retained": len(out),
        "host_mass_bins_used": out["host_mass_class"].nunique(),
        "window_fraction": float(out["in_window"].mean()),
        "seed_rows": seed_rows,
        "nonseed_rows": nonseed_rows,
        "control_rows": control_rows,
        "parent_rows": parent_rows,
        "filler_rows": filler_rows,
    }])
    summary.to_csv(summary_csv, index=False)
    print(f"[ok] wrote {out_csv}")
    print(f"[ok] wrote {summary_csv}")
    print(summary.to_string(index=False))
    print(out[[
        "plateifu","role","host_mass_class","H_raw",s_delta_col,"S_raw","phi_ifu","in_window"
    ]].head(10).to_string(index=False))

build_state(
    df,
    "dn4000_delta_out_minus_cen",
    cfg["outputs"]["age_catalog_csv"],
    cfg["outputs"]["age_summary_csv"],
    "manga_ifu_age"
)

build_state(
    df,
    "stellar_sigma_delta_out_minus_cen",
    cfg["outputs"]["kin_catalog_csv"],
    cfg["outputs"]["kin_summary_csv"],
    "manga_ifu_kin"
)
