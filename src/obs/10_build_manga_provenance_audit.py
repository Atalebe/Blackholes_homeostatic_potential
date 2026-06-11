from pathlib import Path
import numpy as np
import pandas as pd
from astropy.io import fits

raw_csv = "data/raw/obs/obs_mw_homeostasis_input_manga_v1.csv"
drpall_fits = "data/external/manga/dr17/catalogs/drpall-v3_1_1.fits"
dapall_fits = "data/external/manga/dr17/catalogs/dapall-v3_1_1-3.1.0.fits"

outdir = Path("outputs/tables")
outdir.mkdir(parents=True, exist_ok=True)

raw = pd.read_csv(raw_csv).copy()
raw["plateifu"] = raw["gal_id"].astype(str).str.strip()

def find_col_name(data, target: str):
    names = list(data.names)
    lower_map = {n.lower(): n for n in names}
    return lower_map.get(target.lower())

def to_native_array(arr):
    arr = np.asarray(arr)

    # Handle byte/string columns
    if arr.dtype.kind in ("S", "U", "O"):
        return arr

    # FITS tables often come in big-endian; convert to native endian
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

            # Skip multi-dimensional columns
            if hasattr(arr, "shape") and len(arr.shape) > 1 and arr.shape[1:] != ():
                print(f"[warn] skipping non-1D column {actual} with shape {arr.shape}")
                continue

            arr = to_native_array(arr)

            if arr.dtype.kind in ("S", "U", "O"):
                vals = pd.Series(arr).astype(str).str.strip()
            else:
                vals = pd.Series(arr)

            out[req] = vals

        df = pd.DataFrame(out)
        return df

drp_requested = [
    "plateifu",
    "mangaid",
    "objra",
    "objdec",
    "nsa_z",
    "nsa_elpetro_mass",
    "nsa_elpetro_ba",
    "nsa_elpetro_phi",
    "nsa_sersic_mass",
    "versdrp3",
]

dap_requested = [
    "plateifu",
    "daptype",
    "drp3qual",
    "dapqual",
    "stellar_sigma_1re",
    "ha_gflux_1re",
    "ha_gsb_1re",
    "specindex_1re_dn4000",
    "emline_sflux_ha_1re",
]

drp = extract_scalar_columns(drpall_fits, drp_requested)
dap = extract_scalar_columns(dapall_fits, dap_requested)

if "plateifu" in drp.columns:
    drp["plateifu"] = drp["plateifu"].astype(str).str.strip()
if "plateifu" in dap.columns:
    dap["plateifu"] = dap["plateifu"].astype(str).str.strip()

drp_sub = drp[drp["plateifu"].isin(raw["plateifu"])].copy() if "plateifu" in drp.columns else pd.DataFrame()
dap_sub = dap[dap["plateifu"].isin(raw["plateifu"])].copy() if "plateifu" in dap.columns else pd.DataFrame()

audit = raw.merge(drp_sub, on="plateifu", how="left")
audit = audit.merge(dap_sub, on="plateifu", how="left", suffixes=("_drp", "_dap"))

audit["proxy_logMstar_current"] = "raw_obs_mw_homeostasis_input_manga_v1.csv"
audit["proxy_SFR_current"] = "raw_obs_mw_homeostasis_input_manga_v1.csv"
audit["proxy_logMbh_current"] = "raw_obs_mw_homeostasis_input_manga_v1.csv"
audit["proxy_mdot_bh_current"] = "raw_obs_mw_homeostasis_input_manga_v1.csv"

audit["next_logMstar_candidate"] = "drpall:nsa_elpetro_mass or nsa_sersic_mass"
audit["next_S_candidate"] = "dapall: stellar_sigma_1re, Dn4000, Halpha proxies"
audit["next_R_candidate"] = "cube or dapall: Halpha flux gradients, gas maps, replenishment proxies"
audit["next_M_candidate"] = "host structure + future BH/merger memory crosswalk"

audit_out = outdir / "manga_provenance_audit.csv"
audit.to_csv(audit_out, index=False)

print(f"[ok] wrote {audit_out}")
print(f"[info] raw rows={len(raw)} drp matches={len(drp_sub)} dap matches={len(dap_sub)}")
print(audit.head().to_string(index=False))
