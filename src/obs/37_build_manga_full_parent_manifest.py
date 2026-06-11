from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

runtime_csv = Path(cfg["data"]["runtime_table"])
df = pd.read_csv(runtime_csv).copy()

# Basic hygiene
for c in [
    "nsa_z",
    "logMstar_drp_elpetro",
    "logMstar_drp_sersic",
    "stellar_sigma_1re",
    "dapqual",
    "drp3qual",
    "legacy_logMbh",
]:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

df["plateifu"] = df["plateifu"].astype(str).str.strip()
df["plate"] = df["plateifu"].str.split("-").str[0]
df["ifudesign"] = df["plateifu"].str.split("-").str[1]

sel = cfg["selection"]

mask = pd.Series(True, index=df.index)

if sel.get("require_dapqual_zero", False):
    mask &= (df["dapqual"] == 0)

if sel.get("z_max") is not None:
    mask &= np.isfinite(df["nsa_z"]) & (df["nsa_z"] <= float(sel["z_max"]))

if sel.get("host_mass_log10_min") is not None:
    mask &= np.isfinite(df["logMstar_drp_elpetro"]) & (
        df["logMstar_drp_elpetro"] >= float(sel["host_mass_log10_min"])
    )

if sel.get("host_mass_log10_max") is not None:
    mask &= np.isfinite(df["logMstar_drp_elpetro"]) & (
        df["logMstar_drp_elpetro"] < float(sel["host_mass_log10_max"])
    )

if sel.get("require_finite_sigma", False):
    mask &= np.isfinite(df["stellar_sigma_1re"]) & (df["stellar_sigma_1re"] > 0)

parent = df.loc[mask].copy()

parent["has_legacy_bh_overlay"] = parent["has_legacy_bh_overlay"].fillna(False).astype(bool)
parent["role"] = np.where(parent["has_legacy_bh_overlay"], "seed", "filler")

bins = cfg["class_conditioning"]["host_mass_bins"]
edges = [b[0] for b in bins] + [bins[-1][1]]
labels = [f"{lo:.1f}_{hi:.1f}" for lo, hi in bins]
parent["host_mass_class"] = pd.cut(
    parent["logMstar_drp_elpetro"],
    bins=edges,
    labels=labels,
    include_lowest=True,
    right=False,
)

keep_cols = [
    "plateifu",
    "plate",
    "ifudesign",
    "mangaid",
    "objra",
    "objdec",
    "nsa_z",
    "nsa_elpetro_mass",
    "nsa_sersic_mass",
    "nsa_elpetro_ba",
    "nsa_elpetro_phi",
    "versdrp3",
    "daptype",
    "drp3qual",
    "dapqual",
    "stellar_sigma_1re",
    "dn4000_1re",
    "oiii5008_gflux_1re",
    "ha_gflux_1re",
    "ha_gsb_1re",
    "logMstar_drp_elpetro",
    "logMstar_drp_sersic",
    "legacy_gal_id",
    "legacy_logMbh",
    "legacy_mdot_bh",
    "legacy_SFR",
    "legacy_logMstar",
    "legacy_z",
    "has_legacy_bh_overlay",
    "role",
    "host_mass_class",
]
keep_cols = [c for c in keep_cols if c in parent.columns]
parent = parent[keep_cols].copy()

summary = pd.DataFrame([{
    "rows_runtime": len(df),
    "rows_parent": len(parent),
    "seed_rows": int((parent["role"] == "seed").sum()),
    "parent_rows": int((parent["role"] == "parent").sum()),
    "host_mass_bins_used": int(parent["host_mass_class"].notna().sum() > 0 and parent["host_mass_class"].nunique()),
}])

counts = (
    parent.groupby(["host_mass_class", "role"], observed=False)
    .size()
    .rename("n")
    .reset_index()
)

out_manifest = Path(cfg["outputs"]["manifest_csv"])
out_summary = Path(cfg["outputs"]["summary_csv"])
out_counts = Path(cfg["outputs"]["counts_csv"])

out_manifest.parent.mkdir(parents=True, exist_ok=True)
parent.to_csv(out_manifest, index=False)
summary.to_csv(out_summary, index=False)
counts.to_csv(out_counts, index=False)

print(f"[ok] wrote {out_manifest}")
print(f"[ok] wrote {out_summary}")
print(f"[ok] wrote {out_counts}")
print(summary.to_string(index=False))
print(counts.to_string(index=False))
print(parent.head(12).to_string(index=False))
