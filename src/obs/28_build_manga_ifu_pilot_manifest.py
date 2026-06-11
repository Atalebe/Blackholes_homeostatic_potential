from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

runtime_csv = Path(cfg["data"]["runtime_table"])
df = pd.read_csv(runtime_csv).copy()

df["plateifu"] = df["plateifu"].astype(str).str.strip()
df["plate"] = df["plateifu"].str.split("-").str[0]
df["ifudesign"] = df["plateifu"].str.split("-").str[1]

# Numeric coercions
for col in [
    "nsa_z",
    "logMstar_drp_elpetro",
    "stellar_sigma_1re",
    "dn4000_1re",
    "oiii5008_gflux_1re",
    "ha_gsb_1re",
    "dapqual",
    "drp3qual",
    "legacy_logMbh",
]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

# Seeds: the sparse BH overlay
seed_mask = df["has_legacy_bh_overlay"].fillna(False).astype(bool)

# Basic IFU-quality filter for controls
control_mask = (
    df["dn4000_1re"].notna()
    & df["oiii5008_gflux_1re"].notna()
    & df["ha_gsb_1re"].notna()
    & df["logMstar_drp_elpetro"].notna()
    & df["nsa_z"].notna()
    & df["stellar_sigma_1re"].notna()
    & (df["dapqual"] == 0)
)

seeds = df.loc[seed_mask].copy()
controls = df.loc[control_mask & (~seed_mask)].copy()

if len(seeds) == 0:
    raise RuntimeError("No MaNGA BH-overlay seed galaxies found.")

match_cols = cfg["matching"]["columns"]
k_controls = int(cfg["matching"]["controls_per_seed"])

# Standardize the matching space on the control pool
ctrl_stats = {}
for c in match_cols:
    vals = pd.to_numeric(controls[c], errors="coerce")
    mu = np.nanmedian(vals)
    sig = np.nanstd(vals)
    if not np.isfinite(sig) or sig == 0:
        sig = 1.0
    ctrl_stats[c] = (mu, sig)

used_controls = set()
manifest_rows = []

for _, s in seeds.iterrows():
    svec = []
    for c in match_cols:
        mu, sig = ctrl_stats[c]
        svec.append((float(s[c]) - mu) / sig)
    svec = np.array(svec, dtype=float)

    cand = controls.loc[~controls["plateifu"].isin(list(used_controls))].copy()
    dists = []
    for idx, row in cand.iterrows():
        rvec = []
        for c in match_cols:
            mu, sig = ctrl_stats[c]
            rvec.append((float(row[c]) - mu) / sig)
        rvec = np.array(rvec, dtype=float)
        d = np.sqrt(np.sum((svec - rvec) ** 2))
        dists.append((idx, d))

    dists = sorted(dists, key=lambda x: x[1])[:k_controls]
    chosen_idx = [i for i, _ in dists]
    chosen = cand.loc[chosen_idx].copy()

    manifest_rows.append({
        "plateifu": s["plateifu"],
        "role": "seed",
        "matched_to": s["plateifu"],
        "match_rank": 0,
        "match_distance": 0.0,
        "plate": s["plate"],
        "ifudesign": s["ifudesign"],
        "daptype": s["daptype"],
        "logMstar_drp_elpetro": s.get("logMstar_drp_elpetro", np.nan),
        "nsa_z": s.get("nsa_z", np.nan),
        "stellar_sigma_1re": s.get("stellar_sigma_1re", np.nan),
        "legacy_logMbh": s.get("legacy_logMbh", np.nan),
        "has_legacy_bh_overlay": True,
    })

    for rank, (_, crow) in enumerate(chosen.iterrows(), start=1):
        used_controls.add(crow["plateifu"])
        manifest_rows.append({
            "plateifu": crow["plateifu"],
            "role": "control",
            "matched_to": s["plateifu"],
            "match_rank": rank,
            "match_distance": float(
                next(d for i, d in dists if i == crow.name)
            ),
            "plate": crow["plate"],
            "ifudesign": crow["ifudesign"],
            "daptype": crow["daptype"],
            "logMstar_drp_elpetro": crow.get("logMstar_drp_elpetro", np.nan),
            "nsa_z": crow.get("nsa_z", np.nan),
            "stellar_sigma_1re": crow.get("stellar_sigma_1re", np.nan),
            "legacy_logMbh": crow.get("legacy_logMbh", np.nan),
            "has_legacy_bh_overlay": False,
        })

manifest = pd.DataFrame(manifest_rows).drop_duplicates(subset=["plateifu"]).copy()

maps_root = Path(cfg["paths"]["maps_root"])
manifest["maps_local_path"] = manifest.apply(
    lambda r: str(
        maps_root
        / str(r["daptype"])
        / str(r["plate"])
        / str(r["ifudesign"])
        / f"manga-{r['plate']}-{r['ifudesign']}-MAPS-{r['daptype']}.fits.gz"
    ),
    axis=1,
)

sas_base = cfg["paths"]["sas_base"].rstrip("/")
manifest["maps_url"] = manifest.apply(
    lambda r: (
        f"{sas_base}/{r['daptype']}/{r['plate']}/{r['ifudesign']}/"
        f"manga-{r['plate']}-{r['ifudesign']}-MAPS-{r['daptype']}.fits.gz"
    ),
    axis=1,
)

manifest_out = Path(cfg["outputs"]["manifest_csv"])
summary_out = Path(cfg["outputs"]["summary_csv"])
download_sh = Path(cfg["outputs"]["download_script"])

manifest_out.parent.mkdir(parents=True, exist_ok=True)
manifest.to_csv(manifest_out, index=False)

summary = pd.DataFrame([{
    "seed_n": int((manifest["role"] == "seed").sum()),
    "control_n": int((manifest["role"] == "control").sum()),
    "total_n": len(manifest),
    "controls_per_seed_requested": k_controls,
}])
summary.to_csv(summary_out, index=False)

with download_sh.open("w", encoding="utf-8") as f:
    f.write("#!/usr/bin/env bash\nset -euo pipefail\n\n")
    f.write(f'mkdir -p "{maps_root}"\n\n')
    for _, r in manifest.iterrows():
        local_path = Path(r["maps_local_path"])
        f.write(f'mkdir -p "{local_path.parent}"\n')
        f.write(f'if [ ! -f "{local_path}" ]; then\n')
        f.write(f'  wget -O "{local_path}" "{r["maps_url"]}"\n')
        f.write("fi\n\n")

download_sh.chmod(0o755)

print(f"[ok] wrote {manifest_out}")
print(f"[ok] wrote {summary_out}")
print(f"[ok] wrote {download_sh}")
print(summary.to_string(index=False))
print(manifest.head(12).to_string(index=False))
