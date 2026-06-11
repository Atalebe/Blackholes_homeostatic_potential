# src/obs/44_manga_full_ifu_role_permutation_tests.py
from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml


def permute_roles(role_series, rng, strata=None):
    out = role_series.copy()

    if strata is None:
        out.iloc[:] = rng.permutation(out.values)
        return out

    for _, idx in pd.Series(np.arange(len(role_series)), index=role_series.index).groupby(strata, observed=False).groups.items():
        idx = list(idx)
        out.loc[idx] = rng.permutation(out.loc[idx].values)
    return out


cfg = load_yaml(CONFIG_PATH)
df = pd.read_csv(cfg["data"]["state_vector_csv"]).copy()

role_col = cfg["role_tests"]["role_col"]
seed_label = cfg["role_tests"]["seed_label"]
control_label = cfg["role_tests"]["control_label"]
columns = cfg["role_tests"]["test_columns"]
stratify_by = cfg["role_tests"].get("stratify_by", None)

n_perm = N_PERM_OVERRIDE if N_PERM_OVERRIDE is not None else cfg["role_tests"]["n_perm"]
rng = np.random.default_rng(cfg["run"]["seed"])

rows = []

for col in columns:
    work = df[[role_col, col] + ([stratify_by] if stratify_by else [])].copy()
    work = work.replace([np.inf, -np.inf], np.nan).dropna().copy()

    seed_vals = work.loc[work[role_col] == seed_label, col].values
    ctrl_vals = work.loc[work[role_col] == control_label, col].values

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

    obs = np.median(seed_vals) - np.median(ctrl_vals)
    perm_diffs = []

    strata = None if stratify_by is None else work[stratify_by]

    for _ in range(n_perm):
        perm_roles = permute_roles(work[role_col], rng, strata=strata)
        seed_p = work.loc[perm_roles == seed_label, col].values
        ctrl_p = work.loc[perm_roles == control_label, col].values
        if len(seed_p) == 0 or len(ctrl_p) == 0:
            continue
        perm_diffs.append(np.median(seed_p) - np.median(ctrl_p))

    perm_diffs = np.asarray(perm_diffs, dtype=float)

    p_two = (1 + np.sum(np.abs(perm_diffs) >= abs(obs))) / (1 + len(perm_diffs))
    p_gt = (1 + np.sum(perm_diffs >= obs)) / (1 + len(perm_diffs))
    p_lt = (1 + np.sum(perm_diffs <= obs)) / (1 + len(perm_diffs))

    rows.append({
        "column": col,
        "n_seed": len(seed_vals),
        "n_control": len(ctrl_vals),
        "seed_median": np.median(seed_vals),
        "control_median": np.median(ctrl_vals),
        "obs_seed_minus_control_median": obs,
        "p_two_sided": p_two,
        "p_seed_gt_control": p_gt,
        "p_seed_lt_control": p_lt,
        "note": "",
    })

out = pd.DataFrame(rows)
Path(cfg["outputs"]["csv"]).parent.mkdir(parents=True, exist_ok=True)
out.to_csv(cfg["outputs"]["csv"], index=False)

print(f"[ok] wrote {cfg['outputs']['csv']}")
print(out.to_string(index=False))
