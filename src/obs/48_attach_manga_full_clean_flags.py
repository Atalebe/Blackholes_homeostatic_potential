from pathlib import Path

import pandas as pd

from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

features_csv = Path(cfg["data"]["features_csv"])
age_state_csv = Path(cfg["data"]["age_state_csv"])
kin_state_csv = Path(cfg["data"]["kin_state_csv"])

age_out_csv = Path(cfg["outputs"]["age_state_clean_csv"])
kin_out_csv = Path(cfg["outputs"]["kin_state_clean_csv"])
summary_csv = Path(cfg["outputs"]["summary_csv"])

features = pd.read_csv(features_csv).copy()
age = pd.read_csv(age_state_csv).copy()
kin = pd.read_csv(kin_state_csv).copy()

features["is_clean_maps_row"] = (
    features["maps_found"].fillna(False).astype(bool)
    & features["extract_error"].isna()
)

clean_lookup = (
    features[["plateifu", "maps_found", "extract_error", "is_clean_maps_row"]]
    .drop_duplicates(subset=["plateifu"])
    .copy()
)

for df in (age, kin):
    for col in ["maps_found", "extract_error", "is_clean_maps_row"]:
        if col in df.columns:
            df.drop(columns=[col], inplace=True)

age = age.merge(clean_lookup, on="plateifu", how="left")
kin = kin.merge(clean_lookup, on="plateifu", how="left")

age["is_clean_maps_row"] = age["is_clean_maps_row"].fillna(False).astype(bool)
kin["is_clean_maps_row"] = kin["is_clean_maps_row"].fillna(False).astype(bool)

age_out_csv.parent.mkdir(parents=True, exist_ok=True)
kin_out_csv.parent.mkdir(parents=True, exist_ok=True)
summary_csv.parent.mkdir(parents=True, exist_ok=True)

age.to_csv(age_out_csv, index=False)
kin.to_csv(kin_out_csv, index=False)

summary = pd.DataFrame(
    [
        {
            "table_name": "age",
            "rows_total": len(age),
            "rows_clean": int(age["is_clean_maps_row"].sum()),
            "clean_fraction": float(age["is_clean_maps_row"].mean()),
        },
        {
            "table_name": "kin",
            "rows_total": len(kin),
            "rows_clean": int(kin["is_clean_maps_row"].sum()),
            "clean_fraction": float(kin["is_clean_maps_row"].mean()),
        },
    ]
)

summary.to_csv(summary_csv, index=False)

print(f"[ok] wrote {age_out_csv}")
print(f"[ok] wrote {kin_out_csv}")
print(f"[ok] wrote {summary_csv}")
print(summary.to_string(index=False))
