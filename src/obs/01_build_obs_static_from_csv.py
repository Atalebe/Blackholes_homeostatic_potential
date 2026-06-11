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
df = pd.read_csv(cfg["data"]["input_csv"])

# Selection
sel = pd.Series(True, index=df.index)
s = cfg["selection"]

sel &= df["z"] <= s["z_max"]
sel &= df["logMstar"].between(s["host_mass_log10_min"], s["host_mass_log10_max"])

if s.get("require_positive_sfr", False):
    sel &= df["SFR"] > 0
if s.get("require_positive_mdot_bh", False):
    sel &= df["mdot_bh"] > 0

df = df.loc[sel].copy().reset_index(drop=True)

# Static homeostasis proxy
df["log10_sbhg"] = np.log10(df["mdot_bh"]) - df["logMbh"]
df["log10_sfr_star"] = np.log10(df["SFR"]) - df["logMstar"]
df["lambda0"] = df["log10_sbhg"] - df["log10_sfr_star"]
lambda0_low = s.get("lambda0_band_low", -5.0)
lambda0_high = s.get("lambda0_band_high", 3.0)

df = df[np.isfinite(df["lambda0"])].copy()
df = df[df["lambda0"].between(lambda0_low, lambda0_high)].copy()
df = df.reset_index(drop=True)
df["H_raw"] = df["lambda0"]
df["S_raw"] = 0.0

bins = cfg["class_conditioning"]["bh_mass_bins"]
df["bh_mass_class"] = mass_class_from_bins(df["logMbh"], bins)
df = df.dropna(subset=["bh_mass_class"]).reset_index(drop=True)

df = apply_within_group(df, "bh_mass_class", "H_raw", "H_hat")
df["S_hat"] = 0.0
df = compute_phi_bh(df, h_hat_col="H_hat", s_hat_col="S_hat")

df = define_quantile_window(
    df,
    group_col="bh_mass_class",
    phi_col="phi_bh",
    q_low=cfg["window"]["q_low"],
    q_high=cfg["window"]["q_high"],
)

catalog_out = Path(cfg["outputs"]["catalog_out"])
catalog_out.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(catalog_out, index=False)

window_out = Path(cfg["outputs"]["window_catalog_out"])
df.to_parquet(window_out, index=False)

print(f"[ok] wrote {catalog_out}")
print(df[["gal_id","logMstar","logMbh","lambda0","phi_bh","bh_mass_class","in_window"]].head().to_string(index=False))
print(df["bh_mass_class"].value_counts(dropna=False).sort_index())
