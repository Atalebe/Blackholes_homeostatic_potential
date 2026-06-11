from pathlib import Path
import numpy as np
import pandas as pd
from astropy.io import fits

raw_csv = Path("data/raw/obs/obs_mw_homeostasis_input_manga_v1.csv")
drpall_fits = Path("data/external/manga/dr17/catalogs/drpall-v3_1_1.fits")
dapall_fits = Path("data/external/manga/dr17/catalogs/dapall-v3_1_1-3.1.0.fits")
cube_dir = Path("data/external/manga/dr17/cubes")

out_catalogs = Path("outputs/catalogs")
out_tables = Path("outputs/tables")
out_catalogs.mkdir(parents=True, exist_ok=True)
out_tables.mkdir(parents=True, exist_ok=True)

raw = pd.read_csv(raw_csv).copy()
raw["plateifu"] = raw["gal_id"].astype(str).str.strip()

def find_col_name(data, target: str):
    names = list(data.names)
    lower_map = {n.lower(): n for n in names}
    return lower_map.get(target.lower())

def to_native_array(arr):
    arr = np.asarray(arr)
    if arr.dtype.kind in ("S", "U", "O"):
        return arr
    dt = arr.dtype
    if dt.byteorder == ">" or (dt.byteorder == "=" and not dt.isnative):
        arr = arr.byteswap().view(dt.newbyteorder("="))
    else:
        arr = arr.astype(dt.newbyteorder("="), copy=False)
    return arr

def extract_scalar_columns(fits_path, requested_cols):
    with fits.open(fits_path, memmap=True) as hdul:
        data = hdul[1].data
        out = {}
        for req in requested_cols:
            actual = find_col_name(data, req)
            if actual is None:
                continue
            arr = data[actual]
            if hasattr(arr, "shape") and len(arr.shape) > 1 and arr.shape[1:] != ():
                continue
            arr = to_native_array(arr)
            if arr.dtype.kind in ("S", "U", "O"):
                out[req] = pd.Series(arr).astype(str).str.strip()
            else:
                out[req] = pd.Series(arr)
        return pd.DataFrame(out)

drp_cols = [
    "plateifu", "mangaid", "objra", "objdec", "nsa_z",
    "nsa_elpetro_mass", "nsa_sersic_mass", "nsa_elpetro_ba",
    "nsa_elpetro_phi", "versdrp3"
]
dap_cols = [
    "plateifu",
    "daptype",
    "drp3qual",
    "dapqual",
    "stellar_sigma_1re",
    "ha_gflux_1re",
    "ha_gsb_1re",
]

drp = extract_scalar_columns(drpall_fits, drp_cols)
dap = extract_scalar_columns(dapall_fits, dap_cols)

# Parent staging table for later expanded runs
parent = drp.merge(dap, on="plateifu", how="outer", suffixes=("_drp", "_dap"))
parent_out = out_catalogs / "manga_parent_staging_table.parquet"
parent.to_parquet(parent_out, index=False)

# Cube manifest
cube_files = sorted(cube_dir.glob("manga-*-LOGCUBE.fits.gz"))
cube_rows = []
for p in cube_files:
    plateifu = p.name.replace("manga-", "").replace("-LOGCUBE.fits.gz", "")
    cube_rows.append({
        "plateifu": plateifu,
        "cube_path": str(p),
        "size_bytes": p.stat().st_size,
    })
cube_manifest = pd.DataFrame(cube_rows)
cube_manifest_out = out_tables / "manga_cube_manifest.csv"
cube_manifest.to_csv(cube_manifest_out, index=False)

# Current-sample runtime table
runtime = raw.merge(drp, on="plateifu", how="left")
runtime = runtime.merge(dap, on="plateifu", how="left", suffixes=("_drp", "_dap"))
runtime = runtime.merge(cube_manifest, on="plateifu", how="left")

# Simple staged mass proxies
runtime["logMstar_drp_elpetro"] = np.log10(pd.to_numeric(runtime["nsa_elpetro_mass"], errors="coerce"))
runtime["logMstar_drp_sersic"] = np.log10(pd.to_numeric(runtime["nsa_sersic_mass"], errors="coerce"))

runtime_out = out_tables / "manga_sample_runtime_table.csv"
runtime.to_csv(runtime_out, index=False)

print(f"[ok] wrote {parent_out}")
print(f"[ok] wrote {cube_manifest_out}")
print(f"[ok] wrote {runtime_out}")
print(runtime.head().to_string(index=False))
