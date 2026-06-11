from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml

def safe_log10(x, floor=1e-30):
    x = np.asarray(x, dtype=float)
    return np.log10(np.clip(x, floor, None))

def mass_class_from_bins(values, bins):
    edges = [b[0] for b in bins] + [bins[-1][1]]
    labels = [f"{lo:.1f}_{hi:.1f}" for lo, hi in bins]
    return pd.cut(values, bins=edges, labels=labels, include_lowest=True, right=False)

cfg = load_yaml(CONFIG_PATH)
infile = Path(cfg["data"]["bh_details"])
if not infile.exists():
    raise FileNotFoundError(f"Missing bh details: {infile}")

cols = cfg["columns"]
df = pd.read_parquet(infile)

needed = [cols["bh_id"], cols["time"], cols["bh_mass"], cols["bhmar"]]
missing = [c for c in needed if c not in df.columns]
if missing:
    raise KeyError(f"Missing bh_details columns: {missing}")

df = df[needed].copy()
df = df.sort_values([cols["bh_id"], cols["time"]]).reset_index(drop=True)

df["log10_mbh_t"] = safe_log10(df[cols["bh_mass"]])
df["H_t_raw"] = safe_log10(df[cols["bhmar"]] / np.clip(df[cols["bh_mass"]], 1e-30, None))
df["S_t_raw"] = 0.0

track_len = df.groupby(cols["bh_id"]).size().rename("n_track")
df = df.merge(track_len, left_on=cols["bh_id"], right_index=True, how="left")
df = df[df["n_track"] >= cfg["selection"]["min_track_length"]].copy()

final_mass = (
    df.groupby(cols["bh_id"], as_index=False)
      .tail(1)[[cols["bh_id"], "log10_mbh_t"]]
      .rename(columns={"log10_mbh_t": "log10_mbh_final"})
)

bins = cfg["class_conditioning"]["final_mass_bins"]
final_mass["final_mass_class"] = mass_class_from_bins(final_mass["log10_mbh_final"], bins)

df = df.merge(final_mass, on=cols["bh_id"], how="left")
df = df.dropna(subset=["final_mass_class"]).reset_index(drop=True)

df = df.rename(columns={
    cols["bh_id"]: "bh_id",
    cols["time"]: "t",
})

out = Path(cfg["outputs"]["track_catalog_out"])
out.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(out, index=False)

print(f"[ok] wrote {out}")
print(df[["bh_id", "t", "log10_mbh_t", "H_t_raw", "final_mass_class"]].head().to_string(index=False))
