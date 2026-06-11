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
s = cfg["selection"]

out = pd.DataFrame({
    "gal_id": df[c["gal_id"]].astype(str),
    "logMstar": pd.to_numeric(df[c["logMstar"]], errors="coerce"),
    "SFR": pd.to_numeric(df[c["SFR"]], errors="coerce"),
    "logMbh": pd.to_numeric(df[c["logMbh"]], errors="coerce"),
    "mdot_bh": pd.to_numeric(df[c["mdot_bh"]], errors="coerce"),
    "z": pd.to_numeric(df[c["z"]], errors="coerce"),
})

if "sigma_star" in c:
    out["sigma_star"] = pd.to_numeric(df[c["sigma_star"]], errors="coerce")
if "d4000" in c:
    out["d4000"] = pd.to_numeric(df[c["d4000"]], errors="coerce")

for extra in c.get("extras", []):
    if extra in df.columns:
        out[extra] = df[extra]

mask = pd.Series(True, index=out.index)
mask &= np.isfinite(out["logMstar"])
mask &= np.isfinite(out["SFR"])
mask &= np.isfinite(out["logMbh"])
mask &= np.isfinite(out["mdot_bh"])
mask &= np.isfinite(out["z"])
mask &= out["z"] <= s["z_max"]
mask &= out["logMstar"].between(s["host_mass_log10_min"], s["host_mass_log10_max"])

if s.get("require_positive_sfr", False):
    mask &= out["SFR"] > 0
if s.get("require_positive_mdot_bh", False):
    mask &= out["mdot_bh"] > 0
if s.get("require_positive_logMstar", False):
    mask &= out["logMstar"] > 0
if s.get("require_finite_logMbh", False):
    mask &= np.isfinite(out["logMbh"])
if "sigma_star" in out.columns and s.get("require_positive_sigma", False):
    mask &= out["sigma_star"] > 0
if "d4000" in out.columns and s.get("require_positive_d4000", False):
    mask &= out["d4000"] > 0

if "dapqual_col" in c and c["dapqual_col"] in df.columns and s.get("require_zero_dapqual", False):
    mask &= pd.to_numeric(df[c["dapqual_col"]], errors="coerce") == 0

out = out.loc[mask].copy().reset_index(drop=True)

out["log10_sbhg"] = np.log10(out["mdot_bh"]) - out["logMbh"]
out["log10_sfr_star"] = np.log10(out["SFR"]) - out["logMstar"]
out["lambda0"] = out["log10_sbhg"] - out["log10_sfr_star"]

out = out[np.isfinite(out["lambda0"])].copy()
out = out[out["lambda0"].between(s["lambda0_band_low"], s["lambda0_band_high"])].copy()
out = out.reset_index(drop=True)

bins = cfg["class_conditioning"]["bh_mass_bins"]
out["bh_mass_class"] = mass_class_from_bins(out["logMbh"], bins)
out = out.dropna(subset=["bh_mass_class"]).reset_index(drop=True)

mode = cfg["s_definition"]["mode"]

out["H_raw"] = out["lambda0"]

if mode == "sigma_offset":
    rel = cfg["bh_sigma_relation"]
    out["logMbh_sigma"] = rel["a"] + rel["b"] * np.log10(out["sigma_star"] / rel["sigma_norm_kms"])
    out["S_raw"] = -np.abs(out["logMbh"] - out["logMbh_sigma"])

elif mode == "d4000":
    if "d4000" not in out.columns:
        raise KeyError("d4000 column required for s_definition.mode=d4000")
    out["S_raw"] = out["d4000"]

elif mode == "d4000_offset":
    if "d4000" not in out.columns:
        raise KeyError("d4000 column required for s_definition.mode=d4000_offset")
    med = out.groupby("bh_mass_class", observed=False)["d4000"].median().rename("d4000_med_class")
    out = out.merge(med, left_on="bh_mass_class", right_index=True, how="left")
    out["S_raw"] = -np.abs(out["d4000"] - out["d4000_med_class"])

else:
    raise ValueError(f"Unknown s_definition.mode: {mode}")

out = apply_within_group(out, "bh_mass_class", "H_raw", "H_hat")
out = apply_within_group(out, "bh_mass_class", "S_raw", "S_hat")
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
    "s_mode": mode,
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
show_cols = ["gal_id", "logMstar", "logMbh", "lambda0", "phi_bh", "bh_mass_class", "in_window"]
if "d4000" in out.columns:
    show_cols.insert(4, "d4000")
print(out[show_cols].head().to_string(index=False))
print(out["bh_mass_class"].value_counts(dropna=False).sort_index())
