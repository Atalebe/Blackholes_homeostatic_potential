#!/usr/bin/env python3
"""Add explicit previous-state controls for the post-hoc short-lag sensitivity."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    cfg = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))
    source = root / cfg["data"]["candidate_parquet"]
    df = pd.read_parquet(source).sort_values(
        [cfg["columns"]["id"], cfg["columns"]["order"]], kind="stable"
    )
    grouped = df.groupby(cfg["columns"]["id"], sort=False, observed=True)
    df["lambda_previous"] = grouped[cfg["columns"]["current"]].shift(1)
    df["delta_u_previous"] = grouped[cfg["columns"]["delta_time"]].shift(1)
    before = len(df)
    df = df.dropna(subset=["lambda_previous", "delta_u_previous"]).reset_index(drop=True)
    out_root = root / cfg["outputs"]["root"]
    out_root.mkdir(parents=True, exist_ok=True)
    output = out_root / "bh_memory_generator3_shortlag_candidates.parquet"
    df.to_parquet(output, index=False)
    verdict = {
        "schema_version": 1,
        "run_id": cfg["run_id"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "posthoc_sensitivity_only",
        "n_input_rows": before,
        "n_output_rows": int(len(df)),
        "n_tracks": int(df[cfg["columns"]["id"]].nunique()),
        "added_columns": ["lambda_previous", "delta_u_previous"],
        "primary_confirmation_unchanged": True,
        "claim_cap": "diagnostic_short_lag_sensitivity",
    }
    (out_root / "bh_memory_generator3_shortlag_enrichment_verdict.json").write_text(
        json.dumps(verdict, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
