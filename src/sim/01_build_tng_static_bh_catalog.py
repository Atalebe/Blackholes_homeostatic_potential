from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml

def safe_log10(x, floor=1e-30):
    x = np.asarray(x, dtype=float)
    return np.log10(np.clip(x, floor, None))

def mass_class_from_bins(values, bins):
    edges = [b[0] for b in bins] + [bins[-1][1]]
    labels = [f"{lo:.1f}_{hi:.1f}" for lo, hi in bins]
    return pd.cut(values, bins=edges, labels=labels, include_lowest=True, right=False)

cfg = load_yaml(CONFIG_PATH)

sub_path = Path(cfg["data"]["subhalo_catalog"])
bh_path = Path(cfg["data"]["bh_catalog"])
if not sub_path.exists():
    raise FileNotFoundError(f"Missing subhalo catalog: {sub_path}")
if not bh_path.exists():
    raise FileNotFoundError(f"Missing bh catalog: {bh_path}")

cols = cfg["columns"]
join_key = cols["join_key"]

sub = pd.read_parquet(sub_path)
bh = pd.read_parquet(bh_path)

needed_sub = [join_key, cols["mstar"], cols["mhalo"], cols["sfr"]]
needed_bh = [join_key, cols["bh_id"], cols["bh_mass"], cols["bhmar"]]

missing_sub = [c for c in needed_sub if c not in sub.columns]
missing_bh = [c for c in needed_bh if c not in bh.columns]
if missing_sub:
    raise KeyError(f"Missing subhalo columns: {missing_sub}")
if missing_bh:
    raise KeyError(f"Missing bh columns: {missing_bh}")

keep_sub = needed_sub.copy()
keep_bh = needed_bh.copy()

s_raw_col = cols.get("s_raw")
if s_raw_col is not None:
    if s_raw_col in sub.columns:
        keep_sub.append(s_raw_col)
    elif s_raw_col in bh.columns:
        keep_bh.append(s_raw_col)
    else:
        raise KeyError(f"s_raw column '{s_raw_col}' not found in subhalo or bh catalog")

sub = sub[keep_sub].copy()
bh = bh[keep_bh].copy()

df = bh.merge(sub, on=join_key, how="inner").reset_index(drop=True)

df["log10_mbh"] = safe_log10(df[cols["bh_mass"]])
df["log10_mstar"] = safe_log10(df[cols["mstar"]])
df["log10_mhalo"] = safe_log10(df[cols["mhalo"]])
df["log10_sbhg"] = safe_log10(df[cols["bhmar"]] / np.clip(df[cols["bh_mass"]], 1e-30, None))
df["log10_sfr_star"] = safe_log10(df[cols["sfr"]] / np.clip(df[cols["mstar"]], 1e-30, None))
df["lambda0"] = df["log10_sbhg"] - df["log10_sfr_star"]

sel = pd.Series(True, index=df.index)
s = cfg["selection"]
sel &= df["log10_mstar"].between(s["host_mass_log10_min"], s["host_mass_log10_max"])
sel &= df["log10_mhalo"].between(s["halo_mass_log10_min"], s["halo_mass_log10_max"])

if s.get("require_positive_sfr", False):
    sel &= df[cols["sfr"]] > 0
if s.get("require_positive_bhmar", False):
    sel &= df[cols["bhmar"]] > 0

df = df.loc[sel].reset_index(drop=True)

df["H_raw"] = df["lambda0"]

if s_raw_col is None:
    df["S_raw"] = 0.0
else:
    if s_raw_col in df.columns:
        df["S_raw"] = pd.to_numeric(df[s_raw_col], errors="coerce").fillna(0.0)
    else:
        df["S_raw"] = 0.0

bins = cfg["class_conditioning"]["bh_mass_bins"]
df["bh_mass_class"] = mass_class_from_bins(df["log10_mbh"], bins)
df = df.dropna(subset=["bh_mass_class"]).reset_index(drop=True)

out = Path(cfg["outputs"]["base_catalog_out"])
out.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(out, index=False)

print(f"[ok] wrote {out}")
print(f"[info] rows={len(df)}")
print(df["bh_mass_class"].value_counts(dropna=False).sort_index())
