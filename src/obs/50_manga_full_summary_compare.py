from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)


def read_single(csv_path: str, label: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path).copy()
    df["label"] = label
    return df


def read_sensitivity(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path).copy()
    if "label" not in df.columns:
        raise KeyError(f"Sensitivity file missing 'label' column: {csv_path}")
    return df


pieces = []

for item in cfg.get("summary_inputs", []):
    pieces.append(read_single(item["csv"], item["label"]))

for item in cfg.get("sensitivity_inputs", []):
    pieces.append(read_sensitivity(item["csv"]))

if not pieces:
    raise RuntimeError("No inputs provided for comparison.")

out = pd.concat(pieces, ignore_index=True, sort=False)

preferred_cols = [
    "label",
    "obs_slope",
    "intercept",
    "p_one_sided_negative",
    "p_one_sided_positive",
    "n_perm",
    "n_bins_used",
    "rows_used",
    "clean_rows_used",
    "x_col",
    "y_col",
    "group_col",
    "note",
]
existing_cols = [c for c in preferred_cols if c in out.columns]
remaining_cols = [c for c in out.columns if c not in existing_cols]
out = out[existing_cols + remaining_cols]

out_csv = cfg["outputs"]["compare_csv"]
Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
out.to_csv(out_csv, index=False)

print("[ok] wrote", out_csv)
print(out.to_string(index=False))
