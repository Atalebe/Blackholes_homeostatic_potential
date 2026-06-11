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

num_cols = [
    "nsa_z",
    "logMstar_drp_elpetro",
    "stellar_sigma_1re",
    "dn4000_1re",
    "oiii5008_gflux_1re",
    "ha_gflux_1re",
    "ha_gew_1re",
    "dapqual",
    "drp3qual",
    "legacy_logMbh",
]
for c in num_cols:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

# Quality pool
pool = df.copy()
pool = pool[
    np.isfinite(pool["logMstar_drp_elpetro"]) &
    np.isfinite(pool["nsa_z"]) &
    np.isfinite(pool["stellar_sigma_1re"]) &
    np.isfinite(pool["dn4000_1re"]) &
    np.isfinite(pool["oiii5008_gflux_1re"]) &
    (pool["oiii5008_gflux_1re"] > 0) &
    (pool["dapqual"] == 0)
].copy()

# Host-mass classes
bins = cfg["class_conditioning"]["host_mass_bins"]
edges = [b[0] for b in bins] + [bins[-1][1]]
labels = [f"{lo:.1f}_{hi:.1f}" for lo, hi in bins]
pool["host_mass_class"] = pd.cut(
    pool["logMstar_drp_elpetro"],
    bins=edges,
    labels=labels,
    include_lowest=True,
    right=False
)

pool = pool.dropna(subset=["host_mass_class"]).copy()

seed_mask = pool["has_legacy_bh_overlay"].fillna(False).astype(bool)
seeds = pool.loc[seed_mask].copy()
controls = pool.loc[~seed_mask].copy()

if len(seeds) == 0:
    raise RuntimeError("No seed galaxies found in runtime table.")

match_cols = cfg["matching"]["columns"]
controls_per_seed = int(cfg["matching"]["controls_per_seed"])
target_per_bin = int(cfg["filler"]["target_per_host_mass_bin"])

# Standardize matching space on controls
stats = {}
for c in match_cols:
    vals = pd.to_numeric(controls[c], errors="coerce")
    mu = np.nanmedian(vals)
    sig = np.nanstd(vals)
    if not np.isfinite(sig) or sig == 0:
        sig = 1.0
    stats[c] = (mu, sig)

selected = []
selected_plateifus = set()

def add_row(row, role, matched_to="", match_rank=0, match_distance=np.nan, filler_reason=""):
    pifu = row["plateifu"]
    if pifu in selected_plateifus:
        return
    selected_plateifus.add(pifu)
    selected.append({
        "plateifu": pifu,
        "role": role,
        "matched_to": matched_to,
        "match_rank": match_rank,
        "match_distance": match_distance,
        "filler_reason": filler_reason,
        "plate": row["plate"],
        "ifudesign": row["ifudesign"],
        "daptype": row["daptype"],
        "host_mass_class": row["host_mass_class"],
        "logMstar_drp_elpetro": row["logMstar_drp_elpetro"],
        "nsa_z": row["nsa_z"],
        "stellar_sigma_1re": row["stellar_sigma_1re"],
        "dn4000_1re": row["dn4000_1re"],
        "oiii5008_gflux_1re": row["oiii5008_gflux_1re"],
        "has_legacy_bh_overlay": bool(row.get("has_legacy_bh_overlay", False)),
        "legacy_logMbh": row.get("legacy_logMbh", np.nan),
    })

# Add seeds
for _, s in seeds.iterrows():
    add_row(
        s,
        role="seed",
        matched_to=s["plateifu"],
        match_rank=0,
        match_distance=0.0,
        filler_reason=""
    )

# Add matched controls
for _, s in seeds.iterrows():
    svec = np.array([
        (float(s[c]) - stats[c][0]) / stats[c][1]
        for c in match_cols
    ], dtype=float)

    cand = controls.loc[~controls["plateifu"].isin(selected_plateifus)].copy()

    # Prefer same host-mass bin first
    same_bin = cand[cand["host_mass_class"] == s["host_mass_class"]].copy()
    use = same_bin if len(same_bin) >= controls_per_seed else cand

    dists = []
    for idx, r in use.iterrows():
        rvec = np.array([
            (float(r[c]) - stats[c][0]) / stats[c][1]
            for c in match_cols
        ], dtype=float)
        d = np.sqrt(np.sum((svec - rvec) ** 2))
        dists.append((idx, d))

    dists = sorted(dists, key=lambda x: x[1])[:controls_per_seed]
    chosen_idx = [i for i, _ in dists]
    chosen = use.loc[chosen_idx].copy()

    for rank, (_, crow) in enumerate(chosen.iterrows(), start=1):
        dist = next(d for i, d in dists if i == crow.name)
        add_row(
            crow,
            role="control",
            matched_to=s["plateifu"],
            match_rank=rank,
            match_distance=float(dist),
            filler_reason=""
        )

manifest = pd.DataFrame(selected)

# Add host-bin fillers
counts = manifest["host_mass_class"].value_counts().to_dict()

for cls in labels:
    have = counts.get(cls, 0)
    need = max(0, target_per_bin - have)
    if need == 0:
        continue

    filler_pool = controls[
        (controls["host_mass_class"] == cls) &
        (~controls["plateifu"].isin(selected_plateifus))
    ].copy()

    # Prefer more central coverage in line emission and sigma
    filler_pool["score"] = (
        np.log10(pd.to_numeric(filler_pool["oiii5008_gflux_1re"], errors="coerce").clip(lower=1e-6))
        + 0.01 * pd.to_numeric(filler_pool["stellar_sigma_1re"], errors="coerce")
    )
    filler_pool = filler_pool.sort_values(["score", "nsa_z"], ascending=[False, True])

    chosen = filler_pool.head(need)
    for _, row in chosen.iterrows():
        add_row(
            row,
            role="filler",
            matched_to="",
            match_rank=0,
            match_distance=np.nan,
            filler_reason=f"fill_host_mass_bin_{cls}"
        )

manifest = pd.DataFrame(selected).drop_duplicates(subset=["plateifu"]).copy()

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

summary = pd.DataFrame([{
    "seed_n": int((manifest["role"] == "seed").sum()),
    "control_n": int((manifest["role"] == "control").sum()),
    "filler_n": int((manifest["role"] == "filler").sum()),
    "total_n": len(manifest),
    "target_per_host_mass_bin": target_per_bin,
}])

bin_summary = (
    manifest.groupby(["host_mass_class", "role"], observed=False)
    .size()
    .rename("n")
    .reset_index()
)

manifest_out = Path(cfg["outputs"]["manifest_csv"])
summary_out = Path(cfg["outputs"]["summary_csv"])
bin_summary_out = Path(cfg["outputs"]["bin_summary_csv"])
download_sh = Path(cfg["outputs"]["download_script"])

manifest_out.parent.mkdir(parents=True, exist_ok=True)
manifest.to_csv(manifest_out, index=False)
summary.to_csv(summary_out, index=False)
bin_summary.to_csv(bin_summary_out, index=False)

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
print(f"[ok] wrote {bin_summary_out}")
print(f"[ok] wrote {download_sh}")
print(summary.to_string(index=False))
print(bin_summary.to_string(index=False))
print(manifest.head(15).to_string(index=False))
