from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

df = pd.read_csv(cfg["data"]["state_vector_csv"]).copy()

x_col = cfg["columns"]["x_col"]
y_col = cfg["columns"]["y_col"]
bin_edges = cfg["binning"]["bin_edges"]

out_summary = cfg["outputs"]["summary_csv"]
out_binned = cfg["outputs"]["binned_csv"]


def compute_binned_variance(frame: pd.DataFrame, x_col: str, y_col: str, bin_edges: list[float]) -> pd.DataFrame:
    work = frame[[x_col, y_col]].dropna().copy()
    work["x_bin"] = pd.cut(work[x_col], bins=bin_edges, include_lowest=True, right=False)

    rows = []
    for interval, g in work.groupby("x_bin", observed=True):
        if len(g) < 2:
            continue
        x_mid = 0.5 * (interval.left + interval.right)
        var_y = float(np.var(g[y_col].to_numpy(dtype=float), ddof=1))
        rows.append(
            {
                "x_mid": x_mid,
                "n": int(len(g)),
                "var_y": var_y,
            }
        )

    if not rows:
        return pd.DataFrame(columns=["x_mid", "n", "var_y"])

    return pd.DataFrame(rows).sort_values("x_mid").reset_index(drop=True)


def fit_slope(binned: pd.DataFrame) -> tuple[float, float]:
    x = binned["x_mid"].to_numpy(dtype=float)
    y = binned["var_y"].to_numpy(dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept)


def apply_cut(frame: pd.DataFrame, cut: dict, x_col: str) -> pd.DataFrame:
    out = frame.copy()

    if cut.get("require_clean", False):
        if "is_clean" not in out.columns:
            raise KeyError("Cut requested require_clean=True but 'is_clean' is missing.")
        out = out[out["is_clean"].fillna(False)]

    if "mass_min" in cut:
        out = out[out[x_col] >= float(cut["mass_min"])]

    if "mass_max" in cut:
        out = out[out[x_col] < float(cut["mass_max"])]

    if "roles_in" in cut:
        roles = set(cut["roles_in"])
        out = out[out["role"].isin(roles)]

    return out.copy()


summary_rows = []
binned_pieces = []

for cut in cfg["cuts"]:
    label = str(cut["label"])
    sub = apply_cut(df, cut, x_col=x_col)
    sub = sub[[x_col, y_col]].dropna().copy()

    binned = compute_binned_variance(sub, x_col=x_col, y_col=y_col, bin_edges=bin_edges)

    if len(binned) < 2:
        summary_rows.append(
            {
                "label": label,
                "rows_used": int(len(sub)),
                "n_bins_used": int(len(binned)),
                "obs_slope": np.nan,
                "intercept": np.nan,
                "note": "insufficient bins",
            }
        )
        continue

    slope, intercept = fit_slope(binned)

    summary_rows.append(
        {
            "label": label,
            "rows_used": int(len(sub)),
            "n_bins_used": int(len(binned)),
            "obs_slope": slope,
            "intercept": intercept,
            "note": "",
        }
    )

    bb = binned.copy()
    bb["label"] = label
    binned_pieces.append(bb)

summary_df = pd.DataFrame(summary_rows)
binned_df = pd.concat(binned_pieces, ignore_index=True) if binned_pieces else pd.DataFrame()

Path(out_summary).parent.mkdir(parents=True, exist_ok=True)
summary_df.to_csv(out_summary, index=False)
binned_df.to_csv(out_binned, index=False)

print("[ok] wrote", out_summary)
print("[ok] wrote", out_binned)
print(summary_df.to_string(index=False))
