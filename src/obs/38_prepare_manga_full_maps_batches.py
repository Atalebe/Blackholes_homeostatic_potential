from pathlib import Path
import math
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

parent_csv = Path(cfg["data"]["parent_manifest"])
df = pd.read_csv(parent_csv).copy()

df["plateifu"] = df["plateifu"].astype(str).str.strip()
df["plate"] = df["plate"].astype(str).str.strip()
df["ifudesign"] = df["ifudesign"].astype(str).str.strip()
df["daptype"] = df["daptype"].astype(str).str.strip()

maps_root = Path(cfg["paths"]["maps_root"])
sas_base = cfg["paths"]["sas_base"].rstrip("/")

df["maps_local_path"] = df.apply(
    lambda r: str(
        maps_root
        / r["daptype"]
        / r["plate"]
        / r["ifudesign"]
        / f"manga-{r['plate']}-{r['ifudesign']}-MAPS-{r['daptype']}.fits.gz"
    ),
    axis=1,
)

df["maps_url"] = df.apply(
    lambda r: (
        f"{sas_base}/{r['daptype']}/{r['plate']}/{r['ifudesign']}/"
        f"manga-{r['plate']}-{r['ifudesign']}-MAPS-{r['daptype']}.fits.gz"
    ),
    axis=1,
)

df["maps_present"] = df["maps_local_path"].apply(lambda p: Path(p).exists())

master_csv = Path(cfg["outputs"]["master_manifest_csv"])
master_csv.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(master_csv, index=False)

chunk_size = int(cfg["batching"]["chunk_size"])
n_chunks = math.ceil(len(df) / chunk_size)

chunk_dir = Path(cfg["outputs"]["chunk_manifest_dir"])
config_dir = Path(cfg["outputs"]["chunk_config_dir"])
feature_dir = Path(cfg["outputs"]["chunk_feature_dir"])
summary_dir = Path(cfg["outputs"]["chunk_summary_dir"])
download_sh = Path(cfg["outputs"]["download_script"])
extract_sh = Path(cfg["outputs"]["extract_script"])

for d in [chunk_dir, config_dir, feature_dir, summary_dir]:
    d.mkdir(parents=True, exist_ok=True)

with download_sh.open("w", encoding="utf-8") as fdl:
    fdl.write("#!/usr/bin/env bash\nset -euo pipefail\n\n")
    for _, row in df.loc[~df["maps_present"]].iterrows():
        local_path = Path(row["maps_local_path"])
        fdl.write(f'mkdir -p "{local_path.parent}"\n')
        fdl.write(f'if [ ! -f "{local_path}" ]; then\n')
        fdl.write(f'  wget -c --tries=20 --retry-connrefused --waitretry=15 --read-timeout=60 --timeout=60 -O "{local_path}" "{row["maps_url"]}" || true\n')
        fdl.write("fi\n\n")

with extract_sh.open("w", encoding="utf-8") as frun:
    frun.write("#!/usr/bin/env bash\nset -euo pipefail\n\n")
    for i in range(n_chunks):
        lo = i * chunk_size
        hi = min((i + 1) * chunk_size, len(df))
        chunk = df.iloc[lo:hi].copy()

        chunk_manifest = chunk_dir / f"manga_full_maps_chunk_{i:03d}.csv"
        chunk_config = config_dir / f"manga_full_maps_chunk_{i:03d}.yaml"
        chunk_features = feature_dir / f"manga_full_maps_chunk_{i:03d}_features.csv"
        chunk_summary = summary_dir / f"manga_full_maps_chunk_{i:03d}_summary.csv"

        chunk.to_csv(chunk_manifest, index=False)

        chunk_config.write_text(
f"""data:
  manifest_csv: {chunk_manifest}

outputs:
  features_csv: {chunk_features}
  summary_csv: {chunk_summary}
""",
            encoding="utf-8"
        )

        frun.write(
            f'python run_script.py src/obs/29_extract_manga_maps_features.py "{chunk_config}"\n'
        )

download_sh.chmod(0o755)
extract_sh.chmod(0o755)

summary = pd.DataFrame([{
    "rows_parent_manifest": len(df),
    "rows_with_maps_present": int(df["maps_present"].sum()),
    "rows_missing_maps": int((~df["maps_present"]).sum()),
    "chunk_size": chunk_size,
    "n_chunks": n_chunks,
}])

summary_csv = Path(cfg["outputs"]["batch_summary_csv"])
summary.to_csv(summary_csv, index=False)

print(f"[ok] wrote {master_csv}")
print(f"[ok] wrote {summary_csv}")
print(f"[ok] wrote {download_sh}")
print(f"[ok] wrote {extract_sh}")
print(summary.to_string(index=False))
