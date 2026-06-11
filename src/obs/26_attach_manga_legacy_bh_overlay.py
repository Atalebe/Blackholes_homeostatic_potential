from pathlib import Path
import pandas as pd

full_csv = Path("outputs/tables/manga_full_download_runtime.csv")
legacy_csv = Path("data/raw/obs/obs_mw_homeostasis_input_manga_v1.csv")
out_csv = Path("outputs/tables/manga_full_download_runtime_with_legacy_overlay.csv")
summary_csv = Path("outputs/tables/manga_full_download_runtime_with_legacy_overlay_summary.csv")

full = pd.read_csv(full_csv).copy()
legacy = pd.read_csv(legacy_csv).copy()

full["plateifu"] = full["plateifu"].astype(str).str.strip()
legacy["plateifu"] = legacy["gal_id"].astype(str).str.strip()

legacy = legacy.rename(columns={
    "gal_id": "legacy_gal_id",
    "logMbh": "legacy_logMbh",
    "mdot_bh": "legacy_mdot_bh",
    "SFR": "legacy_SFR",
    "logMstar": "legacy_logMstar",
    "z": "legacy_z",
})

merged = full.merge(
    legacy[[
        "plateifu",
        "legacy_gal_id",
        "legacy_logMbh",
        "legacy_mdot_bh",
        "legacy_SFR",
        "legacy_logMstar",
        "legacy_z",
    ]],
    on="plateifu",
    how="left",
)

merged["has_legacy_bh_overlay"] = merged["legacy_logMbh"].notna()
merged.to_csv(out_csv, index=False)

summary = pd.DataFrame([{
    "rows_full_runtime": len(merged),
    "overlay_matches": int(merged["has_legacy_bh_overlay"].sum()),
    "overlay_fraction": float(merged["has_legacy_bh_overlay"].mean()),
}])
summary.to_csv(summary_csv, index=False)

print(f"[ok] wrote {out_csv}")
print(f"[ok] wrote {summary_csv}")
print(summary.to_string(index=False))
print(merged[[
    "plateifu",
    "has_legacy_bh_overlay",
    "legacy_logMbh",
    "legacy_mdot_bh",
    "dn4000_1re",
    "oiii5008_gflux_1re",
]].head(12).to_string(index=False))
