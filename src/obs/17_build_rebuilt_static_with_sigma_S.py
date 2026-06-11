from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml
from src.core.normalize import apply_within_group
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

# Pull canonical columns from the staged runtime table
out = pd.DataFrame({
    "gal_id": df[c["gal_id"]].astype(str),
    "logMstar": pd.to_numeric(df[c["logMstar"]], errors="coerce"),
    "SFR": pd.to_numeric(df[c["SFR"]], errors="coerce"),
    "logMbh": pd.to_numeric(df[c["logMbh"]], errors="coerce"),
    "mdot_bh": pd.to_numeric(df[c["mdot_bh"]], errors="coerce"),
    "z": pd.to_numeric(df[c["z"]], errors="coerce"),
    "sigma_star": pd.to_numeric(df[c["sigma_star"]], errors="coerce"),
})

# Optional carry-through columns for diagnostics
for extra in c.get("extras", []):
    if extra in df.columns:
        out[extra] = df[extra]

# Basic QC
s = cfg["selection"]
sel = pd.Series(True, index=out.index)

sel &= np.isfinite(out["logMstar"])
sel &= np.isfinite(out["SFR"])
sel &= np.isfinite(out["logMbh"])
sel &= np.isfinite(out["mdot_bh"])
sel &= np.isfinite(out["z"])
sel &= np.isfinite(out["sigma_star"])

sel &= out["z"] <= s["z_max"]
sel &= out["logMstar"].between(s["host_mass_log10_min"], s["host_mass_log10_max"])

if s.get("require_positive_sfr", False):
    sel &= out["SFR"] > 0
if s.get("require_positive_mdot_bh", False):
    sel &= out["mdot_bh"] > 0
if s.get("require_positive_sigma", False):
    sel &= out["sigma_star"] > 0
if s.get("require_positive_logMstar", False):
    sel &= out["logMstar"] > 0
if s.get("require_finite_logMbh", False):
    sel &= np.isfinite(out["logMbh"])

# Optional survey-specific quality cuts
if "sn_col" in c and c["sn_col"] in df.columns and "sn_min" in s:
    sel &= pd.to_numeric(df[c["sn_col"]], errors="coerce") >= s["sn_min"]

if "nq_col" in c and c["nq_col"] in df.columns and "nq_min" in s:
    sel &= pd.to_numeric(df[c["nq_col"]], errors="coerce") >= s["nq_min"]

if "dapqual_col" in c and c["dapqual_col"] in df.columns and s.get("require_zero_dapqual", False):
    sel &= pd.to_numeric(df[c["dapqual_col"]], errors="coerce") == 0

if "drpqual_col" in c and c["drpqual_col"] in df.columns and s.get("allow_nonzero_drpqual", True) is False:
    sel &= pd.to_numeric(df[c["drpqual_col"]], errors="coerce") == 0

out = out.loc[sel].copy().reset_index(drop=True)

# H proxy
out["log10_sbhg"] = np.log10(out["mdot_bh"]) - out["logMbh"]
out["log10_sfr_star"] = np.log10(out["SFR"]) - out["logMstar"]
out["lambda0"] = out["log10_sbhg"] - out["log10_sfr_star"]

# Bound pathological tails before normalization
out = out[np.isfinite(out["lambda0"])].copy()
out = out[out["lambda0"].between(s["lambda0_band_low"], s["lambda0_band_high"])].copy()
out = out.reset_index(drop=True)

# Static S proxy from MBH-sigma offset
rel = cfg["bh_sigma_relation"]
out["logMbh_sigma"] = rel["a"] + rel["b"] * np.log10(out["sigma_star"] / rel["sigma_norm_kms"])
out["S_sigma_raw"] = -np.abs(out["logMbh"] - out["logMbh_sigma"])

# Reduced Tier 1 static realization
out["H_raw"] = out["lambda0"]
out["S_raw"] = out["S_sigma_raw"]

# Mass classes
bins = cfg["class_conditioning"]["bh_mass_bins"]
out["bh_mass_class"] = mass_class_from_bins(out["logMbh"], bins)
out = out.dropna(subset=["bh_mass_class"]).reset_index(drop=True)

# Normalize within class
out = apply_within_group(out, "bh_mass_class", "H_raw", "H_hat")
out = apply_within_group(out, "bh_mass_class", "S_raw", "S_hat")

# Scalar potential
out = compute_phi_bh(out, h_hat_col="H_hat", s_hat_col="S_hat")

# Bounded regulated window
out = define_quantile_window(
    out,
    group_col="bh_mass_class",
    phi_col="phi_bh",
    q_low=cfg["window"]["q_low"],
    q_high=cfg["window"]["q_high"],
)

# QC summary
qc = pd.DataFrame([{
    "input_rows": len(df),
    "retained_rows": len(out),
    "retained_fraction": len(out) / len(df) if len(df) > 0 else np.nan,
    "finite_sigma_rows": int(np.isfinite(pd.to_numeric(df[c["sigma_star"]], errors="coerce")).sum()),
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
    "gal_id", "logMstar", "logMbh", "sigma_star", "logMbh_sigma",
    "lambda0", "S_sigma_raw", "phi_bh", "bh_mass_class", "in_window"
]].head().to_string(index=False))
print(out["bh_mass_class"].value_counts(dropna=False).sort_index())
