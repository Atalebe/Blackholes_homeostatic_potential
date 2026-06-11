from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)
RUNTIME = globals().get("RUNTIME_KWARGS", {})


def one_sided_p(null_values: np.ndarray, obs: float, direction: str) -> float:
    null_values = np.asarray(null_values, dtype=float)
    if direction == "negative":
        return float((np.sum(null_values <= obs) + 1) / (len(null_values) + 1))
    if direction == "positive":
        return float((np.sum(null_values >= obs) + 1) / (len(null_values) + 1))
    raise ValueError(f"Unknown direction: {direction}")


def compute_binned_variance(df: pd.DataFrame, x_col: str, y_col: str, bin_edges: list[float]) -> pd.DataFrame:
    work = df[[x_col, y_col]].dropna().copy()
    work["x_bin"] = pd.cut(work[x_col], bins=bin_edges, include_lowest=True, right=False)

    rows = []
    for interval, g in work.groupby("x_bin", observed=True):
        if len(g) < 2:
            continue
        x_mid = 0.5 * (interval.left + interval.right)
        var_y = float(np.var(g[y_col].to_numpy(dtype=float), ddof=1))
        rows.append({"x_mid": x_mid, "n": int(len(g)), "var_y": var_y})

    return pd.DataFrame(rows).sort_values("x_mid").reset_index(drop=True)


def slope_from_binned(binned: pd.DataFrame) -> tuple[float, float]:
    x = binned["x_mid"].to_numpy(dtype=float)
    y = binned["var_y"].to_numpy(dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept)


def permute_within_groups(df: pd.DataFrame, y_col: str, group_col: str, rng: np.random.Generator) -> pd.DataFrame:
    pieces = []
    for _, g in df.groupby(group_col, observed=True, sort=False):
        gg = g.copy()
        vals = gg[y_col].to_numpy(copy=True)
        rng.shuffle(vals)
        gg[y_col] = vals
        pieces.append(gg)
    return pd.concat(pieces, ignore_index=True)


input_csv = cfg["data"]["state_vector_csv"]
x_col = cfg["columns"]["x_col"]
y_col = cfg["columns"]["y_col"]
clean_flag_col = cfg["columns"].get("clean_flag_col", "is_clean_maps_row")
bin_edges = cfg["binning"]["bin_edges"]

out_binned_csv = cfg["outputs"]["binned_csv"]
out_summary_csv = cfg["outputs"]["summary_csv"]
out_null_csv = cfg["outputs"]["null_csv"]
out_png = cfg["outputs"]["figure_png"]

n_perm = int(RUNTIME.get("n_perm", cfg["run"].get("n_perm", 2000)))
seed = int(cfg["run"].get("seed", 123))
direction = cfg["run"].get("p_direction", "negative")
group_col = cfg["run"].get("permute_within", "host_mass_class")

df = pd.read_csv(input_csv)

if clean_flag_col not in df.columns:
    raise KeyError(f"Missing clean flag column: {clean_flag_col}")
if group_col not in df.columns:
    raise KeyError(f"Missing grouping column: {group_col}")

work = df[df[clean_flag_col].fillna(False)].copy()
work = work[[x_col, y_col, group_col]].dropna().copy()

binned = compute_binned_variance(work, x_col, y_col, bin_edges)
if len(binned) < 2:
    raise RuntimeError("Need at least 2 populated bins for slope fitting.")

obs_slope, intercept = slope_from_binned(binned)

rng = np.random.default_rng(seed)
null_slopes = []
for _ in range(n_perm):
    perm = permute_within_groups(work, y_col=y_col, group_col=group_col, rng=rng)
    pb = compute_binned_variance(perm, x_col, y_col, bin_edges)
    if len(pb) < 2:
        continue
    s, _ = slope_from_binned(pb)
    null_slopes.append(s)

null_slopes = np.asarray(null_slopes, dtype=float)
p_val = one_sided_p(null_slopes, obs_slope, direction=direction)

Path(out_binned_csv).parent.mkdir(parents=True, exist_ok=True)
Path(out_summary_csv).parent.mkdir(parents=True, exist_ok=True)
Path(out_null_csv).parent.mkdir(parents=True, exist_ok=True)
Path(out_png).parent.mkdir(parents=True, exist_ok=True)

binned.to_csv(out_binned_csv, index=False)
pd.DataFrame({"null_slope": null_slopes}).to_csv(out_null_csv, index=False)
pd.DataFrame([{
    "obs_slope": obs_slope,
    "intercept": intercept,
    "p_one_sided_negative": p_val if direction == "negative" else np.nan,
    "p_one_sided_positive": p_val if direction == "positive" else np.nan,
    "n_perm": int(len(null_slopes)),
    "n_bins_used": int(len(binned)),
    "x_col": x_col,
    "y_col": y_col,
    "clean_rows_used": int(len(work)),
    "group_col": group_col,
}]).to_csv(out_summary_csv, index=False)

plt.figure(figsize=(7, 5))
plt.plot(binned["x_mid"], binned["var_y"], marker="o")
plt.xlabel(x_col)
plt.ylabel(f"var({y_col})")
plt.title("Clean only variance scaling")
plt.tight_layout()
plt.savefig(out_png, dpi=300)
plt.close()

print("[ok] wrote", out_binned_csv)
print("[ok] wrote", out_summary_csv)
print("[ok] wrote", out_null_csv)
print("[ok] wrote", out_png)
print(pd.DataFrame([{
    "obs_slope": obs_slope,
    "intercept": intercept,
    "p_one_sided_negative": p_val if direction == "negative" else np.nan,
    "p_one_sided_positive": p_val if direction == "positive" else np.nan,
    "n_perm": int(len(null_slopes)),
    "n_bins_used": int(len(binned)),
    "x_col": x_col,
    "y_col": y_col,
    "clean_rows_used": int(len(work)),
}]).to_string(index=False))
print(binned.to_string(index=False))
