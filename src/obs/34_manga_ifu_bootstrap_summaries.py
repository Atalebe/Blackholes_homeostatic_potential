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

df = read_table(cfg["data"]["input_table"]).copy()

group_cols = cfg["bootstrap"].get("group_cols", ["role"])
metric_cols = cfg["bootstrap"].get("metric_cols", ["phi_ifu", "H_raw", "S_raw"])
window_col = cfg["bootstrap"].get("window_col", "in_window")
n_boot = N_BOOT_OVERRIDE if N_BOOT_OVERRIDE is not None else int(cfg["bootstrap"]["n_boot"])
seed = int(cfg["run"]["seed"])

for c in metric_cols:
    df[c] = pd.to_numeric(df[c], errors="coerce")
if window_col in df.columns:
    df[window_col] = df[window_col].astype(bool)

if group_cols:
    grouped = df.groupby(group_cols, dropna=False, observed=False)
else:
    grouped = [(("all",), df)]

rows = []
rng = np.random.default_rng(seed)

for key, g in grouped:
    if not isinstance(key, tuple):
        key = (key,)

    row = {"n_rows": len(g)}
    for col_name, value in zip(group_cols, key):
        row[col_name] = value

    for m in metric_cols:
        vals = pd.to_numeric(g[m], errors="coerce").to_numpy(dtype=float)
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            row[f"{m}_median"] = np.nan
            row[f"{m}_boot_p16"] = np.nan
            row[f"{m}_boot_p84"] = np.nan
            continue

        boot = []
        for _ in range(n_boot):
            samp = rng.choice(vals, size=len(vals), replace=True)
            boot.append(np.nanmedian(samp))
        boot = np.asarray(boot, dtype=float)

        row[f"{m}_median"] = float(np.nanmedian(vals))
        row[f"{m}_boot_p16"] = float(np.nanpercentile(boot, 16))
        row[f"{m}_boot_p84"] = float(np.nanpercentile(boot, 84))

    if window_col in g.columns:
        win = g[window_col].astype(bool).to_numpy()
        boot = []
        for _ in range(n_boot):
            samp = rng.choice(win, size=len(win), replace=True)
            boot.append(np.mean(samp))
        boot = np.asarray(boot, dtype=float)

        row["window_fraction"] = float(np.mean(win))
        row["window_boot_p16"] = float(np.nanpercentile(boot, 16))
        row["window_boot_p84"] = float(np.nanpercentile(boot, 84))

    rows.append(row)

out = pd.DataFrame(rows)
out_path = Path(cfg["outputs"]["summary_csv"])
out_path.parent.mkdir(parents=True, exist_ok=True)
out.to_csv(out_path, index=False)

print(f"[ok] wrote {out_path}")
print(out.to_string(index=False))
