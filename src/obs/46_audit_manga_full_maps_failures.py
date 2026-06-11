# src/obs/46_audit_manga_full_maps_failures.py
from pathlib import Path
import pandas as pd
import numpy as np
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

feat = pd.read_csv(cfg["data"]["features_csv"]).copy()
runtime = pd.read_csv(cfg["data"]["runtime_csv"]).copy()

feat["plateifu"] = feat["plateifu"].astype(str).str.strip()
runtime["plateifu"] = runtime["plateifu"].astype(str).str.strip()

merged = feat.merge(runtime, on="plateifu", how="left", suffixes=("", "_runtime"))

merged["failed"] = merged["extract_error"].notna()
merged["clean"] = merged["maps_found"].fillna(False) & (~merged["failed"])

summary = pd.DataFrame([{
    "rows_total": len(merged),
    "rows_failed": int(merged["failed"].sum()),
    "rows_clean": int(merged["clean"].sum()),
    "failure_fraction": float(merged["failed"].mean()),
    "clean_fraction": float(merged["clean"].mean()),
}])

err_counts = (
    merged.loc[merged["failed"], "extract_error"]
    .fillna("missing")
    .value_counts(dropna=False)
    .rename_axis("extract_error")
    .reset_index(name="n")
)

compare_rows = []
for col in ["logMstar_drp_elpetro", "logMstar_drp_sersic", "nsa_z", "stellar_sigma_1re", "drp3qual", "dapqual"]:
    if col not in merged.columns:
        continue
    fail_vals = pd.to_numeric(merged.loc[merged["failed"], col], errors="coerce")
    clean_vals = pd.to_numeric(merged.loc[merged["clean"], col], errors="coerce")
    compare_rows.append({
        "column": col,
        "failed_median": np.nanmedian(fail_vals) if fail_vals.notna().any() else np.nan,
        "clean_median": np.nanmedian(clean_vals) if clean_vals.notna().any() else np.nan,
        "failed_n": int(fail_vals.notna().sum()),
        "clean_n": int(clean_vals.notna().sum()),
    })

compare = pd.DataFrame(compare_rows)

Path(cfg["outputs"]["summary_csv"]).parent.mkdir(parents=True, exist_ok=True)
summary.to_csv(cfg["outputs"]["summary_csv"], index=False)
err_counts.to_csv(cfg["outputs"]["error_counts_csv"], index=False)
compare.to_csv(cfg["outputs"]["compare_csv"], index=False)

print(f"[ok] wrote {cfg['outputs']['summary_csv']}")
print(f"[ok] wrote {cfg['outputs']['error_counts_csv']}")
print(f"[ok] wrote {cfg['outputs']['compare_csv']}")
print(summary.to_string(index=False))
print(err_counts.head(20).to_string(index=False))
print(compare.to_string(index=False))
