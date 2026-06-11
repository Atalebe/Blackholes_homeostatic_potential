from pathlib import Path
import numpy as np
import pandas as pd
from astropy.io import fits

raw_csv = Path("data/raw/obs/obs_mw_homeostasis_input_gama_dr4_v1.csv")

mass_fits = Path("data/external/gama/dr4/catalogs/StellarMassesPanChromv24.fits")
sigma_fits = Path("data/external/gama/dr4/catalogs/VelocityDispersionsv02.fits")
gauss_fits = Path("data/external/gama/dr4/catalogs/GaussFitSimplev05.fits")
env_fits = Path("data/external/gama/dr4/catalogs/EnvironmentMeasuresv06.fits")

out_catalogs = Path("outputs/catalogs")
out_tables = Path("outputs/tables")
out_catalogs.mkdir(parents=True, exist_ok=True)
out_tables.mkdir(parents=True, exist_ok=True)

raw = pd.read_csv(raw_csv).copy()
raw["CATAID"] = pd.to_numeric(raw["gal_id"], errors="coerce").astype("Int64")
target_ids = set(raw["CATAID"].dropna().astype(int).tolist())

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

def extract_matching_rows(fits_path, key_col, requested_cols, target_ids):
    with fits.open(fits_path, memmap=True) as hdul:
        data = hdul[1].data

        key_actual = find_col_name(data, key_col)
        if key_actual is None:
            raise KeyError(f"{key_col} not found in {fits_path}")

        key_arr = to_native_array(data[key_actual])
        key_num = pd.to_numeric(pd.Series(key_arr), errors="coerce")
        mask = key_num.isin(target_ids).to_numpy()

        if mask.sum() == 0:
            return pd.DataFrame({key_col: pd.Series(dtype="Int64")})

        idx = np.where(mask)[0]
        out = {}

        for req in requested_cols:
            actual = find_col_name(data, req)
            if actual is None:
                continue

            arr = data[actual][idx]

            if hasattr(arr, "shape") and len(arr.shape) > 1 and arr.shape[1:] != ():
                continue

            arr = to_native_array(arr)

            if arr.dtype.kind in ("S", "U", "O"):
                out[req] = pd.Series(arr).astype(str).str.strip()
            else:
                out[req] = pd.Series(arr)

        df = pd.DataFrame(out)

        if key_col in df.columns:
            df[key_col] = pd.to_numeric(df[key_col], errors="coerce").astype("Int64")

        return df

def collapse_gauss_best(df):
    if df.empty:
        return df
    for col in ["IS_BEST", "IS_SBEST", "NQ", "SN"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    sort_cols = []
    ascending = []
    for col, asc in [
        ("IS_BEST", False),
        ("IS_SBEST", False),
        ("NQ", False),
        ("SN", False),
    ]:
        if col in df.columns:
            sort_cols.append(col)
            ascending.append(asc)
    if sort_cols:
        df = df.sort_values(["CATAID"] + sort_cols, ascending=[True] + ascending)
    return df.drop_duplicates(subset=["CATAID"], keep="first").copy()

def collapse_sigma_best(df):
    if df.empty:
        return df
    for col in ["SNR_REST", "SIGERR_STARCORR", "SIG_STARCORR"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # Higher SNR better, lower sigma error better
    if "SIGERR_STARCORR" in df.columns:
        df["_neg_SIGERR_STARCORR"] = -df["SIGERR_STARCORR"]
        sort_cols = ["SNR_REST", "_neg_SIGERR_STARCORR"]
    else:
        sort_cols = ["SNR_REST"] if "SNR_REST" in df.columns else []
    if sort_cols:
        df = df.sort_values(["CATAID"] + sort_cols, ascending=[True] + [False] * len(sort_cols))
    out = df.drop_duplicates(subset=["CATAID"], keep="first").copy()
    if "_neg_SIGERR_STARCORR" in out.columns:
        out = out.drop(columns=["_neg_SIGERR_STARCORR"])
    return out

mass_cols = [
    "CATAID", "Z", "logmstar", "dellogmstar", "mstar",
    "logage", "logtau", "logmet", "dustEBV"
]

sigma_cols = [
    "CATAID", "SPECID", "Z", "SNR_REST", "SNR_OBSR",
    "V_STAR", "SIG_STAR", "SIGERR_STAR", "SIG_STARCORR", "SIGERR_STARCORR"
]

gauss_cols = [
    "CATAID", "SPECID", "RA", "DEC", "Z", "NQ", "SN",
    "IS_BEST", "IS_SBEST",
    "D4000N", "D4000N_ERR",
    "HB_FLUX", "HB_FLUX_ERR",
    "OIIR_FLUX", "OIIR_FLUX_ERR",
    "OIIIB_FLUX", "OIIIB_FLUX_ERR",
    "HA_FLUX", "HA_FLUX_ERR",
    "NIIR_FLUX", "NIIR_FLUX_ERR"
]

env_cols = [
    "CATAID", "Z_TONRY", "SurfaceDensity", "SurfaceDensityErr",
    "CountInCyl", "CountInCylErr", "AGEDenPar", "AGEScale"
]

print("[info] extracting matched rows only...")
mass = extract_matching_rows(mass_fits, "CATAID", mass_cols, target_ids)
sigma = extract_matching_rows(sigma_fits, "CATAID", sigma_cols, target_ids)
gauss = extract_matching_rows(gauss_fits, "CATAID", gauss_cols, target_ids)
env = extract_matching_rows(env_fits, "CATAID", env_cols, target_ids)

# Collapse spectrum-level tables to one row per CATAID
sigma_best = collapse_sigma_best(sigma)
gauss_best = collapse_gauss_best(gauss)

# Save matched subtables
mass.to_csv(out_tables / "gama_mass_matched.csv", index=False)
sigma_best.to_csv(out_tables / "gama_sigma_best.csv", index=False)
gauss_best.to_csv(out_tables / "gama_gauss_best.csv", index=False)
env.to_csv(out_tables / "gama_env_matched.csv", index=False)

# Parent staging table, one row per CATAID where possible
parent = mass.merge(sigma_best, on="CATAID", how="outer", suffixes=("_mass", "_sigma"))
parent = parent.merge(gauss_best, on="CATAID", how="outer", suffixes=("", "_gauss"))
parent = parent.merge(env, on="CATAID", how="outer", suffixes=("", "_env"))

parent_out = out_catalogs / "gama_parent_staging_table_matched.parquet"
parent.to_parquet(parent_out, index=False)

# Runtime table for current sample
runtime = raw.merge(mass, on="CATAID", how="left", suffixes=("", "_mass"))
runtime = runtime.merge(sigma_best, on="CATAID", how="left", suffixes=("", "_sigma"))
runtime = runtime.merge(gauss_best, on="CATAID", how="left", suffixes=("", "_gauss"))
runtime = runtime.merge(env, on="CATAID", how="left", suffixes=("", "_env"))

runtime["logMstar_gama"] = pd.to_numeric(runtime["logmstar"], errors="coerce")
runtime["sigma_star_gama"] = pd.to_numeric(runtime["SIG_STARCORR"], errors="coerce")
runtime["z_gama"] = pd.to_numeric(runtime["Z"], errors="coerce")

runtime_out = out_tables / "gama_sample_runtime_table.csv"
runtime.to_csv(runtime_out, index=False)

summary = pd.DataFrame([{
    "raw_rows": len(raw),
    "target_ids": len(target_ids),
    "mass_matches": int(runtime["logmstar"].notna().sum()),
    "sigma_matches": int(runtime["SIG_STARCORR"].notna().sum()),
    "gauss_matches": int(runtime["SPECID"].notna().sum()),
    "env_matches": int(runtime["SurfaceDensity"].notna().sum()),
    "runtime_rows": len(runtime),
}])

summary_out = out_tables / "gama_runtime_match_summary.csv"
summary.to_csv(summary_out, index=False)

print(f"[ok] wrote {parent_out}")
print(f"[ok] wrote {runtime_out}")
print(f"[ok] wrote {summary_out}")
print(summary.to_string(index=False))
print(runtime.head().to_string(index=False))
