#!/usr/bin/env python3
"""Run the frozen 200-draw pooled-track Generator-4 screen."""
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fractional_improvement(observed: np.ndarray, baseline, augmented) -> tuple[float, float, float]:
    base_residual = observed - baseline
    aug_residual = observed - augmented
    base_rmse = float(np.sqrt(np.mean(base_residual * base_residual)))
    aug_rmse = float(np.sqrt(np.mean(aug_residual * aug_residual)))
    return base_rmse, aug_rmse, (base_rmse - aug_rmse) / base_rmse


def build_rows(raw: pd.DataFrame, cfg: dict, selected: dict[str, set[int]]) -> pd.DataFrame:
    columns = cfg["columns"]
    required_raw_columns = {
        columns["id"],
        columns["split"],
        columns["time"],
        columns["signal"],
        columns["category"],
        columns["mass_class"],
    }
    missing = sorted(required_raw_columns.difference(raw.columns))
    if missing:
        raise RuntimeError(f"frozen canonical raw catalog is missing columns: {missing}")
    frames: list[pd.DataFrame] = []
    selected_all = set().union(*selected.values())
    raw = raw[raw[columns["id"]].astype(int).isin(selected_all)].copy()
    for bh_id, track in raw.groupby(columns["id"], sort=True, observed=True):
        if columns["order"] != columns["time"]:
            raise RuntimeError("frozen raw ordering must use the physical time column")
        track = track.sort_values(
            columns["time"], kind="stable"
        ).reset_index(drop=True)
        split = str(track[columns["split"]].iloc[0])
        if int(bh_id) not in selected[split]:
            raise RuntimeError("track plan and canonical split disagree")
        t = track[columns["time"]].to_numpy(float)
        x = track[columns["signal"]].to_numpy(float)
        if len(t) < 6 or not np.all(np.diff(t) > 0):
            raise RuntimeError("selected raw track is too short or not strictly ordered")
        u = (t - t[0]) / (t[-1] - t[0])
        i = np.arange(3, len(track) - 1)
        frame = pd.DataFrame(
            {
                "bh_id": int(bh_id),
                "split": split,
                "target_time": u[i + 1],
                "lambda_next": x[i + 1],
                "lambda_current": x[i],
                "lambda_previous": x[i - 1],
                "lambda_previous2": x[i - 2],
                "lambda_previous3": x[i - 3],
                "delta_u_next": u[i + 1] - u[i],
                "delta_u_previous": u[i] - u[i - 1],
                "delta_u_previous2": u[i - 1] - u[i - 2],
                "delta_u_previous3": u[i - 2] - u[i - 3],
                "category": str(track[columns["category"]].iloc[0]),
                "final_mass_class": str(track[columns["mass_class"]].iloc[0]),
            }
        )
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    required = [
        "target_time",
        "lambda_next",
        *cfg["model"]["baseline_continuous"],
    ]
    if not np.isfinite(out[required].to_numpy(float)).all():
        raise RuntimeError("non-finite G4 modeling values")
    return out


def grouped_vectors(frame: pd.DataFrame, value: str, split: str | None = None):
    source = frame if split is None else frame[frame["split"] == split]
    groups = source.groupby("bh_id", sort=True, observed=True)
    return (
        [group["target_time"].to_numpy(float) for _, group in groups],
        [group[value].to_numpy(float) for _, group in groups],
    )


def add_history(frame: pd.DataFrame, innovation: np.ndarray, tau: float, history_fn) -> pd.DataFrame:
    out = frame.copy()
    out["_permuted_innovation"] = innovation
    histories = np.full(len(out), np.nan, dtype=float)
    for _, positions in out.groupby("bh_id", sort=True, observed=True).indices.items():
        positions = np.asarray(positions, dtype=int)
        order = np.argsort(out.loc[positions, "target_time"].to_numpy(float))
        ordered_positions = positions[order]
        histories[ordered_positions] = history_fn(
            out.loc[ordered_positions, "target_time"].to_numpy(float),
            out.loc[ordered_positions, "_permuted_innovation"].to_numpy(float),
            tau,
        )
    out["innovation_history"] = histories
    return out[np.isfinite(out["innovation_history"])].copy()


def track_sse(frame: pd.DataFrame, observed: np.ndarray, predicted: np.ndarray, name: str) -> pd.DataFrame:
    values = frame[["bh_id"]].copy()
    values[name] = (observed - predicted) ** 2
    return values.groupby("bh_id", sort=True, observed=True).agg(
        **{name: (name, "sum")}, n_test=(name, "size")
    ).reset_index()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--freeze-manifest", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    sys.path.insert(0, str(root))
    from src.core.innovation_memory import (  # pylint: disable=import-outside-toplevel
        causal_innovation_history,
        estimate_pooled_ou_tau,
    )
    from src.core.predictive_memory import (  # pylint: disable=import-outside-toplevel
        fit_ridge,
        predict_ridge,
    )

    config_path = root / args.config
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    manifest_path = root / args.freeze_manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("freeze_authorized") is not True:
        raise RuntimeError("G4 freeze is not authorized")
    frozen_hash = manifest["files"][str(config_path.relative_to(root))]["sha256"]
    if sha256(config_path) != frozen_hash:
        raise RuntimeError("G4 config changed after freeze")
    runner_path = root / "scripts/89_screen_tng50_memory_generator4_pooled_innovation.py"
    if sha256(runner_path) != manifest["files"][str(runner_path.relative_to(root))]["sha256"]:
        raise RuntimeError("G4 runner changed after freeze")
    plan_path = root / cfg["data"]["canonical_g3_track_plan"]
    if sha256(plan_path) != cfg["screen"]["exact_g3_track_plan_sha256"]:
        raise RuntimeError("canonical G3 track plan changed")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    selected = {
        split: {int(value) for value in plan["selected_track_ids"][split]}
        for split in cfg["screen"]["split_order"]
    }
    raw_path = root / cfg["data"]["raw_track_parquet"]
    raw = pd.read_parquet(raw_path)
    frame = build_rows(raw, cfg, selected)
    continuous = cfg["model"]["baseline_continuous"]
    categorical = cfg["model"]["categorical"]
    alpha = float(cfg["model"]["ridge_alpha"])
    train = frame["split"] == "train"
    residualizer = fit_ridge(
        frame[train], "lambda_next", continuous, categorical, alpha
    )
    frame["innovation_target"] = (
        frame["lambda_next"].to_numpy(float) - predict_ridge(frame, residualizer)
    )
    lower, upper = cfg["innovation"]["tau_profile_bounds"]
    train_times, train_innovations = grouped_vectors(
        frame, "innovation_target", "train"
    )
    tau_fit = estimate_pooled_ou_tau(
        train_times,
        train_innovations,
        float(lower),
        float(upper),
        int(cfg["innovation"]["tau_profile_grid_size"]),
    )
    out_dir = root / cfg["outputs"]["root"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (cfg["outputs"]["label"] + "_verdict.json")
    if not tau_fit["interior"]:
        verdict = {
            "schema_version": 1,
            "run_id": cfg["run_id"],
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "status": "failed_observed_tau_boundary",
            "observed_tau_profile": tau_fit,
            "grid_changed": False,
            "scientific_null_outcome_computed": False,
            "screen_pass": False,
            "confirmation_2000_authorized": False,
            "hrsm_M_status": "externally_replicated_self_history_candidate_not_admitted",
            "claim_cap": "G4_boundary_failure_scale_unidentified",
        }
        out_path.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(verdict, indent=2))
        return 2

    observed_frame = add_history(
        frame,
        frame["innovation_target"].to_numpy(float),
        tau_fit["tau"],
        causal_innovation_history,
    )
    observed_train = observed_frame["split"] == "train"
    observed_test = observed_frame["split"] == "test"
    baseline_model = fit_ridge(
        observed_frame[observed_train],
        "innovation_target",
        continuous,
        categorical,
        alpha,
    )
    augmented_model = fit_ridge(
        observed_frame[observed_train],
        "innovation_target",
        [*continuous, "innovation_history"],
        categorical,
        alpha,
    )
    test = observed_frame[observed_test].copy()
    y_test = test["innovation_target"].to_numpy(float)
    base_prediction = predict_ridge(test, baseline_model)
    augmented_prediction = predict_ridge(test, augmented_model)
    base_rmse, augmented_rmse, observed_gain = fractional_improvement(
        y_test, base_prediction, augmented_prediction
    )
    observed_scores = track_sse(
        test, y_test, base_prediction, "baseline_sse"
    ).merge(
        track_sse(test, y_test, augmented_prediction, "observed_augmented_sse"),
        on=["bh_id", "n_test"],
        validate="one_to_one",
    )
    rng = np.random.default_rng(int(cfg["seed"]))
    n_permutations = int(cfg["screen"]["n_permutations"])
    null_gain = np.empty(n_permutations, dtype=float)
    null_tau = np.empty(n_permutations, dtype=float)
    null_interior = np.empty(n_permutations, dtype=bool)
    null_track_sse = np.empty((n_permutations, len(observed_scores)), dtype=float)
    track_positions = [
        np.asarray(positions, dtype=int)
        for _, positions in frame.groupby("bh_id", sort=True, observed=True).indices.items()
    ]
    original_innovation = frame["innovation_target"].to_numpy(float)
    test_track_ids = observed_scores["bh_id"].to_numpy()
    for permutation in range(n_permutations):
        permuted = original_innovation.copy()
        for positions in track_positions:
            permuted[positions] = rng.permutation(permuted[positions])
        permuted_frame = frame.copy()
        permuted_frame["_null_innovation"] = permuted
        null_times, null_innovations = grouped_vectors(
            permuted_frame, "_null_innovation", "train"
        )
        profile = estimate_pooled_ou_tau(
            null_times,
            null_innovations,
            float(lower),
            float(upper),
            int(cfg["innovation"]["tau_profile_grid_size"]),
        )
        null_tau[permutation] = profile["tau"]
        null_interior[permutation] = profile["interior"]
        destroyed = add_history(
            frame, permuted, profile["tau"], causal_innovation_history
        )
        destroyed_train = destroyed["split"] == "train"
        destroyed_test = destroyed["split"] == "test"
        null_model = fit_ridge(
            destroyed[destroyed_train],
            "innovation_target",
            [*continuous, "innovation_history"],
            categorical,
            alpha,
        )
        null_test = destroyed[destroyed_test]
        if not np.array_equal(
            null_test["bh_id"].to_numpy(), test["bh_id"].to_numpy()
        ) or not np.allclose(
            null_test["target_time"].to_numpy(), test["target_time"].to_numpy()
        ):
            raise RuntimeError("null and observed test rows do not align")
        null_prediction = predict_ridge(null_test, null_model)
        _, _, null_gain[permutation] = fractional_improvement(
            y_test, base_prediction, null_prediction
        )
        per_track = track_sse(
            null_test, y_test, null_prediction, "null_augmented_sse"
        ).set_index("bh_id").loc[test_track_ids]
        null_track_sse[permutation] = per_track["null_augmented_sse"].to_numpy(float)
        if (permutation + 1) % int(cfg["screen"]["progress_every"]) == 0:
            print(f"[progress] {permutation + 1}/{n_permutations}", flush=True)

    excess = float(observed_gain - null_gain.mean())
    exceedances = int(np.sum(null_gain >= observed_gain))
    p_value = (exceedances + 1) / (n_permutations + 1)
    bootstrap_rng = np.random.default_rng(int(cfg["seed"]) + 1)
    n_boot = int(cfg["screen"]["bootstrap_resamples"])
    bootstrap_excess = np.empty(n_boot, dtype=float)
    base_sse = observed_scores["baseline_sse"].to_numpy(float)
    observed_aug_sse = observed_scores["observed_augmented_sse"].to_numpy(float)
    counts = observed_scores["n_test"].to_numpy(float)
    for index in range(n_boot):
        draw = bootstrap_rng.integers(0, len(observed_scores), len(observed_scores))
        base = np.sqrt(base_sse[draw].sum() / counts[draw].sum())
        observed_aug = np.sqrt(observed_aug_sse[draw].sum() / counts[draw].sum())
        observed_draw = (base - observed_aug) / base
        null_aug = np.sqrt(
            null_track_sse[:, draw].sum(axis=1) / counts[draw].sum()
        )
        null_draw = np.mean((base - null_aug) / base)
        bootstrap_excess[index] = observed_draw - null_draw
    confidence = float(cfg["screen"]["confidence"])
    tail = (1.0 - confidence) / 2.0
    bootstrap_ci = np.quantile(bootstrap_excess, [tail, 1.0 - tail]).tolist()
    gates = {
        "observed_tau_interior": tau_fit["interior"],
        "raw_effect_floor": observed_gain
        >= float(cfg["gates"]["minimum_raw_fractional_improvement"]),
        "null_adjusted_effect_floor": excess
        >= float(cfg["gates"]["minimum_null_adjusted_fractional_improvement"]),
        "permutation_p_gate": p_value <= float(cfg["gates"]["p_max"]),
        "bootstrap_excess_lower_above_zero": bootstrap_ci[0] > 0,
        "all_null_draws_retained": len(null_gain) == n_permutations,
    }
    screen_pass = all(gates.values())
    verdict = {
        "schema_version": 1,
        "run_id": cfg["run_id"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "generator": "pooled_strictly_prior_AR3_innovation_history",
        "split_method": "sha256_id_modulo_10_canonical_repair",
        "residualizer_fit_partition": "train_only",
        "selected_track_counts": {
            split: len(selected[split]) for split in cfg["screen"]["split_order"]
        },
        "n_model_rows": int(len(frame)),
        "observed_tau_profile": tau_fit,
        "observed": {
            "baseline_test_rmse": base_rmse,
            "augmented_test_rmse": augmented_rmse,
            "fractional_test_improvement": observed_gain,
        },
        "n_permutations": n_permutations,
        "null_mean_fractional_improvement": float(null_gain.mean()),
        "null_q95_fractional_improvement": float(np.quantile(null_gain, 0.95)),
        "null_adjusted_order_excess": excess,
        "bootstrap_ci_null_adjusted_order_excess": bootstrap_ci,
        "exceedances": exceedances,
        "p_one_sided_plus_one": p_value,
        "null_tau_summary": {
            "minimum": float(null_tau.min()),
            "median": float(np.median(null_tau)),
            "maximum": float(null_tau.max()),
            "interior_count": int(null_interior.sum()),
            "boundary_count": int((~null_interior).sum()),
            "boundary_draws_discarded": 0,
        },
        "gates": gates,
        "screen_pass": screen_pass,
        "confirmation_2000_authorized": screen_pass,
        "hrsm_M_status": (
            "G4_screen_passed_pending_2000_confirmation"
            if screen_pass
            else "externally_replicated_self_history_candidate_not_admitted"
        ),
        "claim_cap": (
            "predictive_innovation_history_screen_beyond_frozen_AR3_"
            "not_irreducible_nonlocality"
        ),
    }
    out_path.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(verdict, indent=2))
    return 0 if screen_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
