from pathlib import Path
import pandas as pd

root = Path("data/external/gama/dr4")
outdir = Path("outputs/tables")
outdir.mkdir(parents=True, exist_ok=True)

files = []
for p in sorted(root.rglob("*")):
    if p.is_file():
        files.append({
            "path": str(p),
            "suffix": p.suffix.lower(),
            "size_bytes": p.stat().st_size,
        })

df = pd.DataFrame(files)
out = outdir / "gama_download_inventory.csv"
df.to_csv(out, index=False)

print(f"[ok] wrote {out}")
if len(df) == 0:
    print("[warn] no GAMA files found under data/external/gama/dr4")
else:
    print(df.to_string(index=False))
