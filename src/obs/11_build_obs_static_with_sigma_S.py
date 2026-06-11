from pathlib import Path
import numpy as np
import pandas as pd
from astropy.io import fits
from src.utils.config import load_yaml
from src.core.normalize import apply_within_group
from src.core.state_vector import compute_phi_bh
from src.core.windows import define_quantile_window

def load_table(path, fmt="csv"):
    path = Path(path)
    fmt = fmt.lower()
    if fmt == "csv":
        return pd.read_csv(path)
    if fmt == "parquet":
        return pd.read_parquet(path)
    if fmt == "fits":
        with fits.open(path, memmap=True) as hdul:
            data = hdul[1].data
            cols = {}
            for name in data.names:
                arr = np.asarray(data[name])
                if hasattr(arr, "shape") and len(arr.shape) > 1 and arr.shape[1:] != ():
                    continue
                if arr.dtype.kind in ("S", "U", "O"):
                    cols[name] = pd.Series(arr).astype(str).str.strip()
                else:
                    if arr.dtype.byteorder == ">" or (arr.dtype.byteorder == "=" and not arr.dtype.isnative):
                        arr = arr.byteswap().view(arr.dtype.newbyteorder("="))
                    cols[name] = pd.Series(arr)
            return pd.DataFrame(cols)
    raise ValueError(f"Unsupported format: {fmt}")

def mass_class_from_bins(values, bins):
    edges = [b[0] for b in bins] + [bins[-1][1]]
    labels = [f"{lo:.1f}_{hi:.1f}" for lo, hi in bins]
    return pd.cut(values, bins=edges, labels=labels, include_lowest=True, right=False)

cfg = load_yaml(CONFIG_PATH)
df = load_table(cfg["data"]["input_table"], cfg["io"]["format"])
c = cfg["columns"]

# Rename to canonical names
rename_map = {v: k for k, v in c.items()}
df = df.rename(columns=rename_map).copy()

required = ["gal_id", "logMstar", "SFR", "logMbh", "mdot_bh", "z", "sigma_star"]
missing = [x for x in required if x not in df.columns]
if missing:
    raise KeyError(f"Missing required columns after rename: {missing}")

# Selection
s = cfg["selection"]
sel = pd.Series(True, index=df.index)
sel &= pd.to_numeric(df["z"], errors="coerce") <= s["z_max"]
sel &= pd.to_numeric(df["logMstar"], errors="coerce").between(
    s["host_mass_log10_min"], s["host_mass_log10_max"]
)

if s.get("require_positive_sfr", False):
    sel &= pd.to_numeric(df["SFR"], errors="coerce") > 0
if s.get("require_positive_mdot_bh", False):
    sel &= pd.to_numeric(df["mdot_bh"], errors="coerce") > 0
if s.get("require_positive_sigma", False):
    sel &= pd.to_numeric(df["sigma_star"], errors="coerce") > 0

df = df.loc[sel].copy().reset_index(drop=True)

# H proxy
df["log10_sbhg"] = np.log10(pd.to_numeric(df["mdot_bh"], errors="coerce")) - pd.to_numeric(df["logMbh"], errors="coerce")
df["log10_sfr_star"] = np.log10(pd.to_numeric(df["SFR"], errors="coerce")) - pd.to_numeric(df["logMstar"], errors="coerce")
df["lambda0"] = df["log10_sbhg"] - df["log10_sfr_star"]

# Band clip
df = df[np.isfinite(df["lambda0"])].copy()
df = df[df["lambda0"].between(s["lambda0_band_low"], s["lambda0_band_high"])].copy()
df = df.reset_index(drop=True)

# S proxy from MBH-sigma offset
rel = cfg["bh_sigma_relation"]
sigma = pd.to_numeric(df["sigma_star"], errors="coerce")
df["logMbh_sigma"] = rel["a"] + rel["b"] * np.log10(sigma / rel["sigma_norm_kms"])
df["S_sigma_raw"] = -np.abs(pd.to_numeric(df["logMbh"], errors="coerce") - df["logMbh_sigma"])

# Canonical Tier 1
df["H_raw"] = df["lambda0"]
df["S_raw"] = df["S_sigma_raw"]

bins = cfg["class_conditioning"]["bh_mass_bins"]
df["bh_mass_class"] = mass_class_from_bins(pd.to_numeric(df["logMbh"], errors="coerce"), bins)
df = df.dropna(subset=["bh_mass_class"]).reset_index(drop=True)

df = apply_within_group(df, "bh_mass_class", "H_raw", "H_hat")
df = apply_within_group(df, "bh_mass_class", "S_raw", "S_hat")
df = compute_phi_bh(df, h_hat_col="H_hat", s_hat_col="S_hat")

df = define_quantile_window(
    df,
    group_col="bh_mass_class",
    phi_col="phi_bh",
    q_low=cfg["window"]["q_low"],
    q_high=cfg["window"]["q_high"],
)

Path(cfg["outputs"]["catalog_out"]).parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(cfg["outputs"]["catalog_out"], index=False)
df.to_parquet(cfg["outputs"]["window_catalog_out"], index=False)

print(f"[ok] wrote {cfg['outputs']['catalog_out']}")
print(df[[
    "gal_id", "logMstar", "logMbh", "sigma_star", "logMbh_sigma",
    "lambda0", "S_sigma_raw", "phi_bh", "bh_mass_class", "in_window"
]].head().to_string(index=False))
print(df["bh_mass_class"].value_counts(dropna=False).sort_index())
