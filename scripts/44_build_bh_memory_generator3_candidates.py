#!/usr/bin/env python3
"""Build past-only Generator 3 memory candidates and freeze their admission metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# Support direct execution as ``python scripts/44_...py`` from any directory.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.core.causal_memory import (
    causal_exponential_memory,
    chronological_split,
    normalize_track_time,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_track(group: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    c = cfg["columns"]
    group = group.sort_values(c["time"], kind="stable").reset_index(drop=True)
    t = pd.to_numeric(group[c["time"]], errors="coerce").to_numpy(float)
    x = pd.to_numeric(group[c["signal"]], errors="coerce").to_numpy(float)
    if not np.isfinite(x).all():
        raise ValueError(f"Non-finite signal in track {group[c['id']].iloc[0]}")
    u = normalize_track_time(t)
    n_predictions = len(group) - 1
    if n_predictions < cfg["selection"]["min_prediction_rows"]:
        return pd.DataFrame()

    result = pd.DataFrame({
        c["id"]: group[c["id"]].iloc[:-1].to_numpy(),
        c["category"]: group[c["category"]].iloc[:-1].astype(str).to_numpy(),
        c["mass_class"]: group[c["mass_class"]].iloc[:-1].astype(str).to_numpy(),
        "row_in_track": np.arange(n_predictions),
        "t_current": t[:-1],
        "u_current": u[:-1],
        "delta_u_next": np.diff(u),
        "lambda_current": x[:-1],
        "lambda_next": x[1:],
        "split": chronological_split(
            n_predictions,
            cfg["splitting"]["train_fraction"],
            cfg["splitting"]["validation_fraction"],
        ),
    })
    for tau in cfg["kernel"]["tau_track_fractions"]:
        memory = causal_exponential_memory(u, x, float(tau))
        result[f"memory_tau_{tau:g}"] = memory[:-1]
    # First prediction row has no completed prior interval and no candidate M.
    return result.iloc[1:].reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    cfg = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))
    source = root / cfg["data"]["track_parquet"]
    out_root = root / cfg["outputs"]["root"]
    out_root.mkdir(parents=True, exist_ok=True)

    c = cfg["columns"]
    required = [c["id"], c["time"], c["signal"], c["category"], c["mass_class"]]
    tracks = pd.read_parquet(source, columns=required)
    duplicate = int(tracks.duplicated([c["id"], c["time"]]).sum())
    if duplicate:
        raise ValueError(f"Duplicate id/time rows: {duplicate}")

    parts = []
    excluded = []
    for bh_id, group in tracks.groupby(c["id"], sort=False, observed=True):
        part = build_track(group, cfg)
        if part.empty:
            excluded.append(bh_id)
        else:
            parts.append(part)
    if not parts:
        raise RuntimeError("No tracks passed Generator 3 Phase A")
    candidates = pd.concat(parts, ignore_index=True)

    memory_cols = [name for name in candidates if name.startswith("memory_tau_")]
    finite_memory = bool(np.isfinite(candidates[memory_cols].to_numpy(float)).all())
    split_counts = candidates["split"].value_counts().to_dict()
    output_parquet = out_root / "bh_memory_generator3_candidates.parquet"
    candidates.to_parquet(output_parquet, index=False)

    verdict = {
        "schema_version": 1,
        "run_id": cfg["run_id"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "input": cfg["data"]["track_parquet"],
        "input_sha256": sha256(source),
        "generator": "causal_exponential_self_history",
        "time_coordinate": "within_track_normalized_ordering_coordinate",
        "physical_timescale_interpretation_authorized": False,
        "tau_track_fractions": cfg["kernel"]["tau_track_fractions"],
        "current_row_excluded_from_memory": True,
        "future_rows_excluded_from_memory": True,
        "target": "next_step_lambda_bh_t",
        "n_input_tracks": int(tracks[c["id"]].nunique()),
        "n_candidate_tracks": int(candidates[c["id"]].nunique()),
        "n_excluded_tracks": len(excluded),
        "excluded_track_ids": [str(value) for value in excluded],
        "n_candidate_rows": int(len(candidates)),
        "split_counts": {str(k): int(v) for k, v in split_counts.items()},
        "finite_memory_coordinates": finite_memory,
        "phase_a_authorized": finite_memory and not excluded,
        "phase_b_predictive_comparison_authorized": finite_memory and not excluded,
        "hrsm_M_status": "candidate_not_admitted",
        "claim_cap": "exploratory_track_level_self_history",
        "prohibited_claims": [
            "confirmatory_HRSM_M",
            "physical_memory_timescale",
            "independent_H_S_axes",
            "host_galaxy_regulation",
        ],
    }
    verdict_path = out_root / "bh_memory_generator3_phase_a_verdict.json"
    verdict_path.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["phase_a_authorized"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
