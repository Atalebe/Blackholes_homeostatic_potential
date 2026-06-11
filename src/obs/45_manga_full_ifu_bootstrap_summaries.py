# src/obs/45_manga_full_ifu_bootstrap_summaries.py
from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)
df = pd.read_csv(cfg["data"]["state_vector_csv"]).copy()

role_col = cfg["bootstrap"]["role_col"]
mass_col = cfg["bootstrap"]["mass_col"]
columns = cfg["bootstrap"]["summary_columns"]
window_col = cfg["bootstrap"]["window_col"]

n_boot = N_BOOT_OVERRIDE if N_BOOT_OVERRIDE is not None else cfg["bootstrap"]["n_boot"]
rng = np.random.default_rng(cfg["run"]["seed"])

rows = []

for (role, mass_bin), g in df.groupby([role_col, mass_col], observed=False):
    if len(g) == 0:
        continue

    row = {
        "n_rows": len(g),
        "role": role,
        "host_mass_class": mass_bin,
    }

    for col in columns:
        vals = pd.to_numeric(g[col], errors="coerce").values
        vals = vals[np.isfinite(vals)]
        row[f"{col}_median"] = np.median(vals) if len(vals) else np.nan

        boots = []
        for _ in range(n_boot):
            samp = rng.choice(vals, size=len(vals), replace=True) if len(vals) else np.array([])
            boots.append(np.median(samp) if len(samp) else np.nan)

        boots = np.asarray(boots, dtype=float)
        row[f"{col}_boot_p16"] = np.nanpercentile(boots, 16) if np.isfinite(boots).any() else np.nan
        row[f"{col}_boot_p84"] = np.nanpercentile(boots, 84) if np.isfinite(boots).any() else np.nan

    win = pd.to_numeric(g[window_col], errors="coerce").fillna(0).values.astype(float)
    row["window_fraction"] = np.mean(win) if len(win) else np.nan

    boots_w = []
    for _ in range(n_boot):
        samp = rng.choice(win, size=len(win), replace=True) if len(win) else np.array([])
        boots_w.append(np.mean(samp) if len(samp) else np.nan)

    boots_w = np.asarray(boots_w, dtype=float)
    row["window_boot_p16"] = np.nanpercentile(boots_w, 16) if np.isfinite(boots_w).any() else np.nan
    row["window_boot_p84"] = np.nanpercentile(boots_w, 84) if np.isfinite(boots_w).any() else np.nan

    rows.append(row)

out = pd.DataFrame(rows)
Path(cfg["outputs"]["csv"]).parent.mkdir(parents=True, exist_ok=True)
out.to_csv(cfg["outputs"]["csv"], index=False)

print(f"[ok] wrote {cfg['outputs']['csv']}")
print(out.to_string(index=False))
