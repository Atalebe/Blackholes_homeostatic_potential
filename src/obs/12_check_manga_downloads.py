from pathlib import Path
import pandas as pd
from astropy.io import fits

raw_csv = Path("data/raw/obs/obs_mw_homeostasis_input_manga_v1.csv")
drpall_fits = Path("data/external/manga/dr17/catalogs/drpall-v3_1_1.fits")
dapall_fits = Path("data/external/manga/dr17/catalogs/dapall-v3_1_1-3.1.0.fits")
cube_dir = Path("data/external/manga/dr17/cubes")
outdir = Path("outputs/tables")
outdir.mkdir(parents=True, exist_ok=True)

raw = pd.read_csv(raw_csv).copy()
raw["plateifu"] = raw["gal_id"].astype(str).str.strip()

def extract_plateifu_set(fits_path):
    with fits.open(fits_path, memmap=True) as hdul:
        data = hdul[1].data
        names = list(data.names)
        lower = {n.lower(): n for n in names}
        key = lower.get("plateifu")
        if key is None:
            raise KeyError(f"plateifu column not found in {fits_path}")
        vals = pd.Series(data[key]).astype(str).str.strip()
        return set(vals.tolist()), len(vals)

drp_plateifu, drp_n = extract_plateifu_set(drpall_fits)
dap_plateifu, dap_n = extract_plateifu_set(dapall_fits)

raw_set = set(raw["plateifu"].tolist())
cube_files = sorted(cube_dir.glob("manga-*-LOGCUBE.fits.gz"))
cube_plateifu = set(
    p.name.replace("manga-", "").replace("-LOGCUBE.fits.gz", "") for p in cube_files
)

rows = []
for plateifu in sorted(raw_set):
    rows.append({
        "plateifu": plateifu,
        "in_raw_sample": True,
        "in_drpall": plateifu in drp_plateifu,
        "in_dapall": plateifu in dap_plateifu,
        "cube_downloaded": plateifu in cube_plateifu,
        "cube_path": str(cube_dir / f"manga-{plateifu}-LOGCUBE.fits.gz") if plateifu in cube_plateifu else "",
    })

check = pd.DataFrame(rows)
check_out = outdir / "manga_download_check.csv"
check.to_csv(check_out, index=False)

summary = pd.DataFrame([{
    "raw_sample_n": len(raw_set),
    "drpall_rows": drp_n,
    "dapall_rows": dap_n,
    "cubes_downloaded_n": len(cube_files),
    "raw_in_drpall_n": int(check["in_drpall"].sum()),
    "raw_in_dapall_n": int(check["in_dapall"].sum()),
    "raw_with_cube_n": int(check["cube_downloaded"].sum()),
}])

summary_out = outdir / "manga_download_check_summary.csv"
summary.to_csv(summary_out, index=False)

print(f"[ok] wrote {check_out}")
print(f"[ok] wrote {summary_out}")
print(summary.to_string(index=False))
print(check.to_string(index=False))
