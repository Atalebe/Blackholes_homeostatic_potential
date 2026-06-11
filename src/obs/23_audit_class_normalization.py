from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml

def mad(arr):
    arr = np.asarray(arr, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return np.nan
    med = np.median(arr)
    return np.median(np.abs(arr - med))

def mass_class_from_bins(values, bins):
    edges = [b[0] for b in bins] + [bins[-1][1]]
    labels = [f"{lo:.1f}_{hi:.1f}" for lo, hi in bins]
    return pd.cut(values, bins=edges, labels=labels, include_lowest=True, right=False)

cfg = load_yaml(CONFIG_PATH)
df = pd.read_csv(cfg["data"]["runtime_table"])

c = cfg["columns"]
s = cfg["selection"]

out = pd.DataFrame({
    "gal_id": df[c["gal_id"]].astype(str),
    "logMstar": pd.to_numeric(df[c["logMstar"]], errors="coerce"),
    "SFR": pd.to_numeric(df[c["SFR"]], errors="coerce"),
    "logMbh": pd.to_numeric(df[c["logMbh"]], errors="coerce"),
    "mdot_bh": pd.to_numeric(df[c["mdot_bh"]], errors="coerce"),
    "z": pd.to_numeric(df[c["z"]], errors="coerce"),
    "sigma_star": pd.to_numeric(df[c["sigma_star"]], errors="coerce"),
    "H_source": pd.to_numeric(df[c["h_col"]], errors="coerce"),
})

if "sn_col" in c:
    out["SN"] = pd.to_numeric(df[c["sn_col"]], errors="coerce")
if "nq_col" in c:
    out["NQ"] = pd.to_numeric(df[c["nq_col"]], errors="coerce")

mask = pd.Series(True, index=out.index)
mask &= np.isfinite(out["logMstar"])
mask &= np.isfinite(out["SFR"])
mask &= np.isfinite(out["logMbh"])
mask &= np.isfinite(out["mdot_bh"])
mask &= np.isfinite(out["z"])
mask &= np.isfinite(out["sigma_star"])
mask &= np.isfinite(out["H_source"])
mask &= out["z"] <= s["z_max"]
mask &= out["logMstar"].between(s["host_mass_log10_min"], s["host_mass_log10_max"])
mask &= out["SFR"] > 0
mask &= out["mdot_bh"] > 0
mask &= out["sigma_star"] > 0
mask &= out["logMstar"] > 0
mask &= out["H_source"] > 0

if "SN" in out.columns and "sn_min" in s:
    mask &= out["SN"] >= s["sn_min"]
if "NQ" in out.columns and "nq_min" in s:
    mask &= out["NQ"] >= s["nq_min"]

out = out.loc[mask].copy().reset_index(drop=True)

# Current GAMA custom H and S
out["H_raw"] = np.log10(out["H_source"])

rel = cfg["bh_sigma_relation"]
out["logMbh_sigma"] = rel["a"] + rel["b"] * np.log10(out["sigma_star"] / rel["sigma_norm_kms"])
out["S_raw"] = -np.abs(out["logMbh"] - out["logMbh_sigma"])

bins = cfg["class_conditioning"]["bh_mass_bins"]
out["bh_mass_class"] = mass_class_from_bins(out["logMbh"], bins)
out = out.dropna(subset=["bh_mass_class"]).reset_index(drop=True)

rows = []
for cls, g in out.groupby("bh_mass_class", observed=False):
    rows.append({
        "bh_mass_class": str(cls),
        "n": len(g),
        "H_median": np.median(g["H_raw"]),
        "H_mad": mad(g["H_raw"]),
        "H_min": np.min(g["H_raw"]),
        "H_max": np.max(g["H_raw"]),
        "S_median": np.median(g["S_raw"]),
        "S_mad": mad(g["S_raw"]),
        "S_min": np.min(g["S_raw"]),
        "S_max": np.max(g["S_raw"]),
    })

summary = pd.DataFrame(rows)

# Most extreme raw S objects
out["S_abs_dev"] = np.abs(out["S_raw"] - np.median(out["S_raw"]))
extreme = out.sort_values("S_abs_dev", ascending=False).head(20)

outdir = Path("outputs/tables")
outdir.mkdir(parents=True, exist_ok=True)
summary_out = outdir / cfg["outputs"]["summary_csv"]
extreme_out = outdir / cfg["outputs"]["extreme_csv"]

summary.to_csv(summary_out, index=False)
extreme.to_csv(extreme_out, index=False)

print(f"[ok] wrote {summary_out}")
print(f"[ok] wrote {extreme_out}")
print(summary.to_string(index=False))
print(extreme[[
    "gal_id","logMbh","sigma_star","logMbh_sigma","H_raw","S_raw","bh_mass_class"
]].to_string(index=False))
