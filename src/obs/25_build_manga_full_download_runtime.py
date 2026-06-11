from pathlib import Path
import numpy as np
import pandas as pd

parent_parquet = Path("outputs/catalogs/manga_parent_staging_table.parquet")
channel_csv = Path("outputs/tables/manga_dap_channels_full.csv")
out_csv = Path("outputs/tables/manga_full_download_runtime.csv")
summary_csv = Path("outputs/tables/manga_full_download_runtime_summary.csv")

parent = pd.read_parquet(parent_parquet).copy()
channels = pd.read_csv(channel_csv).copy()

parent["plateifu"] = parent["plateifu"].astype(str).str.strip()
channels["plateifu"] = channels["plateifu"].astype(str).str.strip()

full = parent.merge(channels, on="plateifu", how="left")

if "nsa_elpetro_mass" in full.columns:
    m = pd.to_numeric(full["nsa_elpetro_mass"], errors="coerce")
    full["logMstar_drp_elpetro"] = np.where(m > 0, np.log10(m), np.nan)

if "nsa_sersic_mass" in full.columns:
    m = pd.to_numeric(full["nsa_sersic_mass"], errors="coerce")
    full["logMstar_drp_sersic"] = np.where(m > 0, np.log10(m), np.nan)

full.to_csv(out_csv, index=False)

summary = pd.DataFrame([{
    "rows_full_download_runtime": len(full),
    "unique_plateifu": full["plateifu"].nunique(),
    "rows_with_dn4000": int(full["dn4000_1re"].notna().sum()),
    "rows_with_oiii5008": int(full["oiii5008_gflux_1re"].notna().sum()),
    "rows_with_ha_gflux": int(full["ha_gflux_1re"].notna().sum()),
    "rows_with_ha_gsb": int(full["ha_gsb_1re"].notna().sum()),
}])
summary.to_csv(summary_csv, index=False)

print(f"[ok] wrote {out_csv}")
print(f"[ok] wrote {summary_csv}")
print(summary.to_string(index=False))
print(full.head().to_string(index=False))
