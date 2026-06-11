from pathlib import Path
import numpy as np
import pandas as pd

from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

def read_table(path):
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        return pd.read_parquet(p)
    return pd.read_csv(p)

def permute_roles(role_series, rng, strata=None):
    out = role_series.copy()

    if strata is None or strata is False:
        out.iloc[:] = rng.permutation(out.to_numpy())
        return out

    if isinstance(strata, str):
        if strata in ("", "global"):
            out.iloc[:] = rng.permutation(out.to_numpy())
            return out
        raise ValueError("Pass a Series for stratified shuffles, not a column name string.")

    grouped = pd.Series(np.arange(len(out)), index=out.index).groupby(strata, observed=False)
    for _, idx in grouped.groups.items():
        idx = list(idx)
        vals = out.loc[idx].to_numpy()
        out.loc[idx] = rng.permutation(vals)
    return out

df = read_table(cfg["data"]["input_table"]).copy()

role_col = cfg["tests"].get("role_col", "role")
seed_label = cfg["tests"].get("seed_label", "seed")
control_label = cfg["tests"].get("control_label", "control")
stratify_by = cfg["tests"].get("stratify_by", "host_mass_class")
columns = cfg["tests"]["columns"]
n_perm = N_PERM_OVERRIDE if N_PERM_OVERRIDE is not None else int(cfg["tests"]["n_perm"])
seed = int(cfg["run"]["seed"])

if stratify_by in (None, False, "", "global"):
    strata = None
else:
    strata = df[stratify_by]

rows = []

for col in columns:
    use_cols = [role_col, col]
    if strata is not None:
        use_cols.append(stratify_by)

    work = df[use_cols].copy()
    work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work[np.isfinite(work[col])].copy()
    work = work[work[role_col].isin([seed_label, control_label])].copy()

    seed_vals = work.loc[work[role_col] == seed_label, col].to_numpy(dtype=float)
    ctrl_vals = work.loc[work[role_col] == control_label, col].to_numpy(dtype=float)

    if len(seed_vals) == 0 or len(ctrl_vals) == 0:
        rows.append({
            "column": col,
            "n_seed": len(seed_vals),
            "n_control": len(ctrl_vals),
            "seed_median": np.nan,
            "control_median": np.nan,
            "obs_seed_minus_control_median": np.nan,
            "p_two_sided": np.nan,
            "p_seed_gt_control": np.nan,
            "p_seed_lt_control": np.nan,
            "note": "Empty role group",
        })
        continue

    obs_stat = float(np.nanmedian(seed_vals) - np.nanmedian(ctrl_vals))

    rng = np.random.default_rng(seed)
    null_stats = []

    for _ in range(n_perm):
        perm_roles = permute_roles(
            work[role_col],
            rng,
            strata=None if strata is None else work[stratify_by]
        )
        perm_seed = work.loc[perm_roles == seed_label, col].to_numpy(dtype=float)
        perm_ctrl = work.loc[perm_roles == control_label, col].to_numpy(dtype=float)

        if len(perm_seed) == 0 or len(perm_ctrl) == 0:
            continue

        null_stats.append(float(np.nanmedian(perm_seed) - np.nanmedian(perm_ctrl)))

    null_stats = np.asarray(null_stats, dtype=float)

    if len(null_stats) == 0:
        p_two = np.nan
        p_gt = np.nan
        p_lt = np.nan
    else:
        p_two = (1 + np.sum(np.abs(null_stats) >= abs(obs_stat))) / (1 + len(null_stats))
        p_gt = (1 + np.sum(null_stats >= obs_stat)) / (1 + len(null_stats))
        p_lt = (1 + np.sum(null_stats <= obs_stat)) / (1 + len(null_stats))

    rows.append({
        "column": col,
        "n_seed": len(seed_vals),
        "n_control": len(ctrl_vals),
        "seed_median": float(np.nanmedian(seed_vals)),
        "control_median": float(np.nanmedian(ctrl_vals)),
        "obs_seed_minus_control_median": obs_stat,
        "p_two_sided": p_two,
        "p_seed_gt_control": p_gt,
        "p_seed_lt_control": p_lt,
        "note": "",
    })

out = pd.DataFrame(rows)
out_path = Path(cfg["outputs"]["summary_csv"])
out_path.parent.mkdir(parents=True, exist_ok=True)
out.to_csv(out_path, index=False)

print(f"[ok] wrote {out_path}")
print(out.to_string(index=False))
