from pathlib import Path
import pandas as pd
from astropy.io import fits

root = Path("data/external/gama/dr4")
outdir = Path("outputs/tables")
outdir.mkdir(parents=True, exist_ok=True)

rows = []

for p in sorted(root.rglob("*")):
    if not p.is_file():
        continue

    try:
        if p.suffix.lower() == ".csv":
            df = pd.read_csv(p, nrows=5)
            rows.append({
                "path": str(p),
                "format": "csv",
                "ncols_preview": len(df.columns),
                "columns_preview": " | ".join(map(str, df.columns[:20])),
            })
        elif p.suffix.lower() in [".fits", ".fit", ".fz"]:
            with fits.open(p, memmap=True) as hdul:
                if len(hdul) > 1 and hasattr(hdul[1], "data") and hdul[1].data is not None:
                    names = list(getattr(hdul[1].data, "names", []) or [])
                    rows.append({
                        "path": str(p),
                        "format": "fits",
                        "ncols_preview": len(names),
                        "columns_preview": " | ".join(map(str, names[:20])),
                    })
    except Exception as e:
        rows.append({
            "path": str(p),
            "format": "error",
            "ncols_preview": -1,
            "columns_preview": str(e),
        })

df = pd.DataFrame(rows)
out = outdir / "gama_table_audit.csv"
df.to_csv(out, index=False)

print(f"[ok] wrote {out}")
print(df.to_string(index=False))
