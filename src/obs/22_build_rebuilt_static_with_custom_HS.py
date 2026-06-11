from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml
from src.core.state_vector import compute_phi_bh
from src.core.windows import define_quantile_window

def mass_class_from_bins(values, bins):
    edges = [b[0] for b in bins] + [bins[-1][1]]
    labels = [f"{lo:.1f}_{hi:.1f}" for lo, hi in bins]
    return pd.cut(values, bins=edges, labels=labels, include_lowest=True, right=False)

cfg = load_yaml(CONFIG_PATH)

runtime_path = Path(cfg["data"]["runtime_table"])
if runtime_path.suffix.lower() == ".csv":
    df = pd.read_csv(runtime_path)
elif runtime_path.suffix.lower() == ".parquet":
    df = pd.read_parquet(runtime_path)
else:
    raise ValueError(f"Unsupported runtime table format: {runtime_path.suffix}")

c = cfg["columns"]
s = cfg["selection"]
h_mode = cfg["h_definition"]["mode"]
s_mode = cfg["s_definition"]["mode"]

out = pd.DataFrame({
    "gal_id": df[c["gal_id"]].astype(str),
    "logMstar": pd.to_numeric(df[c["logMstar"]], errors="coerce"),
    "logMbh": pd.to_numeric(df[c["logMbh"]], errors="coerce"),
    "z": pd.to_numeric(df[c["z"]], errors="coerce"),
})

# Optional columns
if "SFR" in c and c["SFR"] in df.columns:
    out["SFR"] = pd.to_numeric(df[c["SFR"]], errors="coerce")
if "mdot_bh" in c and c["mdot_bh"] in df.columns:
    out["mdot_bh"] = pd.to_numeric(df[c["mdot_bh"]], errors="coerce")
if "sigma_star" in c and c["sigma_star"] in df.columns:
    out["sigma_star"] = pd.to_numeric(df[c["sigma_star"]], errors="coerce")

for extra in c.get("extras", []):
    if extra in df.columns:
        out[extra] = df[extra]

if "h_col" in c and c["h_col"] in df.columns:
    out["_H_SOURCE"] = pd.to_numeric(df[c["h_col"]], errors="coerce")
if "s_col" in c and c["s_col"] in df.columns:
    out["_S_SOURCE"] = pd.to_numeric(df[c["s_col"]], errors="coerce")

mask = pd.Series(True, index=out.index)
mask &= np.isfinite(out["logMstar"])
mask &= np.isfinite(out["logMbh"])
mask &= np.isfinite(out["z"])
mask &= out["z"] <= s["z_max"]
mask &= out["logMstar"].between(s["host_mass_log10_min"], s["host_mass_log10_max"])

if s.get("require_positive_logMstar", False):
    mask &= out["logMstar"] > 0
if s.get("require_finite_logMbh", False):
    mask &= np.isfinite(out["logMbh"])

if h_mode == "lambda0":
    mask &= np.isfinite(out["SFR"])
    mask &= np.isfinite(out["mdot_bh"])
    if s.get("require_positive_sfr", False):
        mask &= out["SFR"] > 0
    if s.get("require_positive_mdot_bh", False):
        mask &= out["mdot_bh"] > 0

if "sigma_star" in out.columns and s.get("require_positive_sigma", False):
    mask &= np.isfinite(out["sigma_star"])
    mask &= out["sigma_star"] > 0

if "_H_SOURCE" in out.columns and s.get("require_positive_h_source", False):
    mask &= np.isfinite(out["_H_SOURCE"])
    mask &= out["_H_SOURCE"] > 0

if "_S_SOURCE" in out.columns and s.get("require_positive_s_source", False):
    mask &= np.isfinite(out["_S_SOURCE"])
    mask &= out["_S_SOURCE"] > 0

if "sn_col" in c and c["sn_col"] in df.columns and "sn_min" in s:
    mask &= pd.to_numeric(df[c["sn_col"]], errors="coerce") >= s["sn_min"]

if "nq_col" in c and c["nq_col"] in df.columns and "nq_min" in s:
    mask &= pd.to_numeric(df[c["nq_col"]], errors="coerce") >= s["nq_min"]

if "dapqual_col" in c and c["dapqual_col"] in df.columns and s.get("require_zero_dapqual", False):
    mask &= pd.to_numeric(df[c["dapqual_col"]], errors="coerce") == 0

out = out.loc[mask].copy().reset_index(drop=True)

# H definition
if h_mode == "lambda0":
    out["log10_sbhg"] = np.log10(out["mdot_bh"]) - out["logMbh"]
    out["log10_sfr_star"] = np.log10(out["SFR"]) - out["logMstar"]
    out["lambda0"] = out["log10_sbhg"] - out["log10_sfr_star"]
    out = out[np.isfinite(out["lambda0"])].copy()
    out = out[out["lambda0"].between(s["lambda0_band_low"], s["lambda0_band_high"])].copy()
    out["H_raw"] = out["lambda0"]

elif h_mode == "log10_col":
    out = out[np.isfinite(out["_H_SOURCE"])].copy()
    out = out[out["_H_SOURCE"] > 0].copy()
    out["H_raw"] = np.log10(out["_H_SOURCE"])

elif h_mode == "col":
    out = out[np.isfinite(out["_H_SOURCE"])].copy()
    out["H_raw"] = out["_H_SOURCE"]

else:
    raise ValueError(f"Unknown h_definition.mode: {h_mode}")

out = out.reset_index(drop=True)

bins = cfg["class_conditioning"]["bh_mass_bins"]
out["bh_mass_class"] = mass_class_from_bins(out["logMbh"], bins)
out = out.dropna(subset=["bh_mass_class"]).reset_index(drop=True)

# S definition
if s_mode == "sigma_offset":
    rel = cfg["bh_sigma_relation"]
    out["logMbh_sigma"] = rel["a"] + rel["b"] * np.log10(out["sigma_star"] / rel["sigma_norm_kms"])
    out["S_raw"] = -np.abs(out["logMbh"] - out["logMbh_sigma"])

elif s_mode == "offset_from_class_median_log10_col":
    out = out[np.isfinite(out["_S_SOURCE"])].copy()
    out = out[out["_S_SOURCE"] > 0].copy()
    out["_S_LOG"] = np.log10(out["_S_SOURCE"])
    med = out.groupby("bh_mass_class", observed=False)["_S_LOG"].median().rename("_S_MED_CLASS")
    out = out.merge(med, left_on="bh_mass_class", right_index=True, how="left")
    out["S_raw"] = -np.abs(out["_S_LOG"] - out["_S_MED_CLASS"])

elif s_mode == "direct_col":
    out = out[np.isfinite(out["_S_SOURCE"])].copy()
    out["S_raw"] = out["_S_SOURCE"]

else:
    raise ValueError(f"Unknown s_definition.mode: {s_mode}")

mad_floor = float(cfg.get("normalization", {}).get("mad_floor", 1e-3))

def robust_hat(frame, group_col, raw_col, hat_col, mad_floor=1e-3):
    parts = []
    for cls, g in frame.groupby(group_col, observed=False):
        vals = pd.to_numeric(g[raw_col], errors="coerce").to_numpy(dtype=float)
        med = np.nanmedian(vals)
        mad = np.nanmedian(np.abs(vals - med))
        if not np.isfinite(mad) or mad < mad_floor:
            mad = mad_floor
        gg = g.copy()
        gg[hat_col] = (vals - med) / mad
        parts.append(gg)
    return pd.concat(parts, ignore_index=True)

out = robust_hat(out, "bh_mass_class", "H_raw", "H_hat", mad_floor=mad_floor)
out = robust_hat(out, "bh_mass_class", "S_raw", "S_hat", mad_floor=mad_floor)

clip_abs = float(cfg.get("normalization", {}).get("clip_abs", 10.0))
out["H_hat"] = out["H_hat"].clip(-clip_abs, clip_abs)
out["S_hat"] = out["S_hat"].clip(-clip_abs, clip_abs)

out = compute_phi_bh(out, h_hat_col="H_hat", s_hat_col="S_hat")

out = define_quantile_window(
    out,
    group_col="bh_mass_class",
    phi_col="phi_bh",
    q_low=cfg["window"]["q_low"],
    q_high=cfg["window"]["q_high"],
)

qc = pd.DataFrame([{
    "input_rows": len(df),
    "retained_rows": len(out),
    "retained_fraction": len(out) / len(df) if len(df) > 0 else np.nan,
    "h_mode": h_mode,
    "s_mode": s_mode,
    "mad_floor": mad_floor,
    "clip_abs": clip_abs,
}])

catalog_out = Path(cfg["outputs"]["catalog_out"])
window_out = Path(cfg["outputs"]["window_catalog_out"])
qc_out = Path(cfg["outputs"]["qc_summary_out"])
catalog_out.parent.mkdir(parents=True, exist_ok=True)

out.to_parquet(catalog_out, index=False)
out.to_parquet(window_out, index=False)
qc.to_csv(qc_out, index=False)

print(f"[ok] wrote {catalog_out}")
print(f"[ok] wrote {window_out}")
print(f"[ok] wrote {qc_out}")
print(qc.to_string(index=False))
print(out[[
    "gal_id", "logMstar", "logMbh", "H_raw", "S_raw", "H_hat", "S_hat", "phi_bh", "bh_mass_class", "in_window"
]].head().to_string(index=False))
print(out["bh_mass_class"].value_counts(dropna=False).sort_index())
