#!/usr/bin/env python3
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

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.core.predictive_memory import (
    bootstrap_fractional_improvement,
    fit_ridge,
    predict_ridge,
    rmse,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(root: Path, manifest: dict) -> None:
    if not manifest.get("freeze_authorized"):
        raise RuntimeError("Canonical G3 rerun freeze is not authorized")
    changed = [
        relative for relative, record in manifest["files"].items()
        if not (root / relative).is_file() or sha256(root / relative) != record["sha256"]
    ]
    if changed:
        raise RuntimeError(f"Frozen canonical G3 inputs changed: {changed}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--freeze-manifest", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    cfg = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))
    manifest = json.loads((root / args.freeze_manifest).read_text(encoding="utf-8"))
    verify(root, manifest)
    source = root / cfg["data"]["candidate_parquet"]
    frame = pd.read_parquet(source)
    c = cfg["columns"]
    target = c["target"]
    baseline = [c["current"], c["delta_time"]]
    categorical = [c["category"], c["mass_class"]]
    taus = [float(value) for value in cfg["selection"]["tau_track_fractions"]]
    memory_columns = [f"memory_tau_{tau:g}" for tau in taus]
    required = [target, c["id"], c["split"], *baseline, *categorical, *memory_columns]
    missing = [column for column in required if column not in frame]
    if missing:
        raise KeyError(f"Missing canonical candidate columns: {missing}")
    train = frame[frame[c["split"]] == "train"]
    validation = frame[frame[c["split"]] == "validation"]
    test = frame[frame[c["split"]] == "test"].copy()
    if min(len(train), len(validation), len(test)) == 0:
        raise RuntimeError("Canonical split contains an empty partition")

    alpha = float(cfg["model"]["ridge_alpha"])
    baseline_validation_model = fit_ridge(train, target, baseline, categorical, alpha)
    baseline_validation_rmse = rmse(
        validation[target].to_numpy(float),
        predict_ridge(validation, baseline_validation_model),
    )
    rows = []
    for tau, memory in zip(taus, memory_columns):
        model = fit_ridge(train, target, [*baseline, memory], categorical, alpha)
        score = rmse(validation[target].to_numpy(float), predict_ridge(validation, model))
        rows.append({
            "tau_track_fraction": tau,
            "memory_column": memory,
            "baseline_validation_rmse": baseline_validation_rmse,
            "augmented_validation_rmse": score,
            "fractional_validation_improvement": (baseline_validation_rmse - score) / baseline_validation_rmse,
        })
    selection = pd.DataFrame(rows).sort_values(
        ["augmented_validation_rmse", "tau_track_fraction"], kind="stable"
    ).reset_index(drop=True)
    selected = selection.iloc[0]
    selected_memory = str(selected["memory_column"])
    development = frame[frame[c["split"]].isin(["train", "validation"])]
    baseline_model = fit_ridge(development, target, baseline, categorical, alpha)
    augmented_model = fit_ridge(
        development, target, [*baseline, selected_memory], categorical, alpha
    )
    observed = test[target].to_numpy(float)
    test["baseline_prediction"] = predict_ridge(test, baseline_model)
    test["augmented_prediction"] = predict_ridge(test, augmented_model)
    baseline_rmse = rmse(observed, test["baseline_prediction"].to_numpy(float))
    augmented_rmse = rmse(observed, test["augmented_prediction"].to_numpy(float))
    improvement = (baseline_rmse - augmented_rmse) / baseline_rmse
    test["baseline_squared_error"] = (observed - test["baseline_prediction"]) ** 2
    test["augmented_squared_error"] = (observed - test["augmented_prediction"]) ** 2
    per_track = test.groupby(c["id"], observed=True).agg(
        n_test=(target, "size"),
        baseline_sse=("baseline_squared_error", "sum"),
        augmented_sse=("augmented_squared_error", "sum"),
    ).reset_index()
    per_track["baseline_rmse"] = np.sqrt(per_track["baseline_sse"] / per_track["n_test"])
    per_track["augmented_rmse"] = np.sqrt(per_track["augmented_sse"] / per_track["n_test"])
    per_track["fractional_improvement"] = (
        per_track["baseline_rmse"] - per_track["augmented_rmse"]
    ) / per_track["baseline_rmse"]
    boot = bootstrap_fractional_improvement(
        per_track, int(cfg["bootstrap"]["n_resamples"]), int(cfg["seed"])
    )
    confidence = float(cfg["bootstrap"]["confidence"])
    tail = (1.0 - confidence) / 2.0
    ci_low, ci_high = np.quantile(boot, [tail, 1.0 - tail])
    floor = float(cfg["gates"]["minimum_fractional_test_improvement"])
    passed = bool(improvement >= floor and ci_low > 0)

    out_dir = root / cfg["outputs"]["root"]
    out_dir.mkdir(parents=True, exist_ok=True)
    selection.to_csv(out_dir / "bh_tng50_memory_generator3_sha256_tau_selection.csv", index=False)
    per_track.to_csv(out_dir / "bh_tng50_memory_generator3_sha256_test_by_track.csv", index=False)
    verdict = {
        "schema_version": 1,
        "run_id": cfg["run_id"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "split_method": "sha256_id_modulo_10_canonical_repair",
        "candidate_sha256": sha256(source),
        "baseline_continuous": baseline,
        "selected_tau_track_fraction": float(selected["tau_track_fraction"]),
        "selected_memory_column": selected_memory,
        "baseline_test_rmse": baseline_rmse,
        "augmented_test_rmse": augmented_rmse,
        "fractional_test_improvement": improvement,
        "bootstrap_ci_fractional_improvement": [float(ci_low), float(ci_high)],
        "median_track_fractional_improvement": float(per_track["fractional_improvement"].median()),
        "n_test_tracks": int(len(per_track)),
        "effect_size_gate_pass": passed,
        "phase_c_full_history_screen_authorized": passed,
        "generator4_execution_authorized": False,
        "hrsm_M_status": "candidate_not_admitted",
        "claim_cap": "canonical_hash_split_external_effect_size_only_pending_null",
    }
    out_path = out_dir / "bh_tng50_memory_generator3_sha256_phase_b_verdict.json"
    out_path.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

