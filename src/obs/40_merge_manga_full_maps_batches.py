from pathlib import Path
import glob
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

feature_glob = cfg["data"]["feature_glob"]
summary_glob = cfg["data"]["summary_glob"]

feature_paths = sorted(glob.glob(feature_glob))
summary_paths = sorted(glob.glob(summary_glob))

if len(feature_paths) == 0:
    raise RuntimeError(f"No feature files matched: {feature_glob}")

frames = []
for p in feature_paths:
    df = pd.read_csv(p)
    df["source_file"] = Path(p).name
    frames.append(df)

merged = pd.concat(frames, ignore_index=True)
merged["plateifu"] = merged["plateifu"].astype(str).str.strip()
merged = merged.drop_duplicates(subset=["plateifu"], keep="first").copy()

summary_frames = []
for p in summary_paths:
    try:
        s = pd.read_csv(p)
        s["source_file"] = Path(p).name
        summary_frames.append(s)
    except Exception:
        pass

summary = pd.DataFrame([{
    "n_feature_files": len(feature_paths),
    "n_summary_files": len(summary_paths),
    "rows_merged": len(merged),
    "rows_with_maps_found": int(merged["maps_found"].fillna(False).sum()) if "maps_found" in merged.columns else None,
    "rows_with_errors": int(merged["extract_error"].notna().sum()) if "extract_error" in merged.columns else None,
}])

out_features = Path(cfg["outputs"]["merged_features_csv"])
out_summary = Path(cfg["outputs"]["merged_summary_csv"])
out_chunk_summaries = Path(cfg["outputs"]["merged_chunk_summaries_csv"])

out_features.parent.mkdir(parents=True, exist_ok=True)
merged.to_csv(out_features, index=False)
summary.to_csv(out_summary, index=False)

if len(summary_frames) > 0:
    pd.concat(summary_frames, ignore_index=True).to_csv(out_chunk_summaries, index=False)
else:
    pd.DataFrame().to_csv(out_chunk_summaries, index=False)

print(f"[ok] wrote {out_features}")
print(f"[ok] wrote {out_summary}")
print(f"[ok] wrote {out_chunk_summaries}")
print(summary.to_string(index=False))
print(merged.head(12).to_string(index=False))
