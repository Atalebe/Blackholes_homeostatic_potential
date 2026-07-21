#!/usr/bin/env python3
"""Create exact lag-1/2/3 controls for the post-hoc AR-depth ladder."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml


def enrich(df: pd.DataFrame, id_col: str, order_col: str) -> pd.DataFrame:
    work = df.sort_values([id_col, order_col], kind="stable").copy()
    grouped = work.groupby(id_col, sort=False, observed=True)
    for lag in (1, 2, 3):
        suffix = "" if lag == 1 else str(lag)
        work[f"lambda_previous{suffix}"] = grouped["lambda_current"].shift(lag)
        work[f"delta_u_previous{suffix}"] = grouped["delta_u_next"].shift(lag)
    required = [
        "lambda_previous", "lambda_previous2", "lambda_previous3",
        "delta_u_previous", "delta_u_previous2", "delta_u_previous3",
    ]
    return work.dropna(subset=required).reset_index(drop=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--repo-root", default=".")
    a = p.parse_args()
    root = Path(a.repo_root).resolve()
    cfg = yaml.safe_load((root / a.config).read_text(encoding="utf-8"))
    source = root / cfg["data"]["candidate_parquet"]
    raw = pd.read_parquet(source)
    output = enrich(raw, cfg["columns"]["id"], cfg["columns"]["order"])
    out_root = root / cfg["outputs"]["root"]
    out_root.mkdir(parents=True, exist_ok=True)
    path = out_root / "bh_memory_generator3_deeplag_candidates.parquet"
    output.to_parquet(path, index=False)
    verdict = {
        "schema_version": 1,
        "run_id": cfg["run_id"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "posthoc_sensitivity_only",
        "source": cfg["data"]["candidate_parquet"],
        "n_input_rows": int(len(raw)),
        "n_output_rows": int(len(output)),
        "expected_row_loss": int(3 * raw[cfg["columns"]["id"]].nunique()),
        "observed_row_loss": int(len(raw) - len(output)),
        "n_tracks": int(output[cfg["columns"]["id"]].nunique()),
        "lags": [1, 2, 3],
        "primary_confirmation_unchanged": True,
        "claim_cap": "diagnostic_ar_lag_ladder",
    }
    if verdict["observed_row_loss"] != verdict["expected_row_loss"]:
        raise RuntimeError(f"Unexpected row loss: {verdict}")
    (out_root / "bh_memory_generator3_deeplag_enrichment_verdict.json").write_text(
        json.dumps(verdict, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
