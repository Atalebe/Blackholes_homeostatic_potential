#!/usr/bin/env python3
"""Run the selection-within-null screen for Generator 3."""
from __future__ import annotations

import argparse
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

from src.core.memory_nulls import balanced_sample, plus_one_p, recompute_sampled_memory
from src.core.predictive_memory import fit_ridge, predict_ridge, rmse


def evaluate(df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    c = cfg["columns"]
    target = c["target"]
    base = list(c.get("baseline_continuous", [c["current"], c["delta_time"]]))
    cats = [c["category"], c["mass_class"]]
    taus = cfg["selection"]["tau_track_fractions"]
    memory_cols = [f"memory_tau_{tau:g}" for tau in taus]
    alpha = float(cfg["model"]["ridge_alpha"])
    train = df[df[c["split"]] == "train"]
    validation = df[df[c["split"]] == "validation"]
    test = df[df[c["split"]] == "test"]
    development = df[df[c["split"]].isin(["train", "validation"])]

    base_validation_model = fit_ridge(train, target, base, cats, alpha)
    base_validation_rmse = rmse(
        validation[target].to_numpy(float), predict_ridge(validation, base_validation_model)
    )
    rows = []
    for tau, memory in zip(taus, memory_cols):
        model = fit_ridge(train, target, [*base, memory], cats, alpha)
        score = rmse(validation[target].to_numpy(float), predict_ridge(validation, model))
        rows.append({
            "tau_track_fraction": float(tau),
            "memory_column": memory,
            "baseline_validation_rmse": base_validation_rmse,
            "augmented_validation_rmse": score,
        })
    selection = pd.DataFrame(rows).sort_values(
        ["augmented_validation_rmse", "tau_track_fraction"], kind="stable"
    ).reset_index(drop=True)
    selected = selection.iloc[0]
    memory = str(selected["memory_column"])
    baseline = fit_ridge(development, target, base, cats, alpha)
    augmented = fit_ridge(development, target, [*base, memory], cats, alpha)
    observed = test[target].to_numpy(float)
    base_rmse = rmse(observed, predict_ridge(test, baseline))
    aug_rmse = rmse(observed, predict_ridge(test, augmented))
    result = {
        "selected_tau_track_fraction": float(selected["tau_track_fraction"]),
        "selected_memory_column": memory,
        "baseline_test_rmse": base_rmse,
        "augmented_test_rmse": aug_rmse,
        "fractional_test_improvement": (base_rmse - aug_rmse) / base_rmse,
    }
    return selection, result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    cfg = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))
    phase_b = json.loads((root / cfg["data"]["phase_b_verdict"]).read_text(encoding="utf-8"))
    if not phase_b.get("phase_c_selection_within_null_authorized", False):
        raise RuntimeError("Phase B did not authorize Phase C")
    full = pd.read_parquet(root / cfg["data"]["candidate_parquet"])
    c = cfg["columns"]
    sampled = balanced_sample(
        full, c["split"], c["id"], int(cfg["screen"]["max_rows_per_split"]), int(cfg["seed"])
    )
    # The null needs at least two sampled rows per track. The balanced cap normally
    # guarantees more; enforce it rather than silently changing the null unit.
    counts = sampled.groupby([c["id"], c["split"]], observed=True).size()
    if (counts < 2).any():
        raise RuntimeError("At least one sampled track has fewer than two rows")

    # Guard the latent categorical failure mode: unseen evaluation levels must
    # never be silently encoded as the reference category.
    train_frame = sampled[sampled[c["split"]] == "train"]
    for name in [c["category"], c["mass_class"]]:
        known = set(train_frame[name].astype(str))
        unknown = set(sampled[name].astype(str)) - known
        if unknown:
            raise RuntimeError(f"Unseen categorical levels for {name}: {sorted(unknown)}")

    taus = [float(value) for value in cfg["selection"]["tau_track_fractions"]]
    observed_frame = recompute_sampled_memory(
        sampled, c["id"], c["split"], c["order"], c["time"], c["signal"], taus
    )
    observed_selection, observed = evaluate(observed_frame, cfg)
    n_perm = int(cfg["screen"]["n_permutations"])
    rng = np.random.default_rng(int(cfg["seed"]))
    null_rows = []
    for permutation in range(n_perm):
        destroyed = recompute_sampled_memory(
            sampled, c["id"], c["split"], c["order"], c["time"], c["signal"], taus, rng
        )
        _, result = evaluate(destroyed, cfg)
        result["permutation"] = permutation
        null_rows.append(result)
        if (permutation + 1) % int(cfg["screen"]["progress_every"]) == 0:
            print(f"[progress] {permutation + 1}/{n_perm}", flush=True)
    null = pd.DataFrame(null_rows)
    effect = float(observed["fractional_test_improvement"])
    exceedances = int((null["fractional_test_improvement"] >= effect).sum())
    p_value = plus_one_p(exceedances, n_perm)
    alpha = float(cfg["gates"]["screen_alpha"])
    screen_pass = bool(effect >= cfg["gates"]["minimum_fractional_test_improvement"] and p_value <= alpha)

    out_root = root / cfg["outputs"]["root"]
    out_root.mkdir(parents=True, exist_ok=True)
    observed_selection.to_csv(out_root / "bh_memory_generator3_phase_c_recompute_observed_selection.csv", index=False)
    null.to_csv(out_root / "bh_memory_generator3_phase_c_recompute_screen_null.csv", index=False)
    verdict = {
        "schema_version": 1,
        "run_id": cfg["run_id"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "null": "permute_lambda_within_track_and_split_then_recompute_all_causal_kernels",
        "finished_memory_columns_permuted": False,
        "causal_memory_recomputed_inside_each_null": True,
        "selection_repeated_inside_each_null": True,
        "sample_seed": int(cfg["seed"]),
        "n_sample_rows": int(len(sampled)),
        "n_sample_tracks": int(sampled[c["id"]].nunique()),
        "max_rows_per_split": int(cfg["screen"]["max_rows_per_split"]),
        "n_permutations": n_perm,
        "observed": observed,
        "null_mean_fractional_improvement": float(null["fractional_test_improvement"].mean()),
        "null_q95_fractional_improvement": float(null["fractional_test_improvement"].quantile(0.95)),
        "exceedances": exceedances,
        "p_one_sided_plus_one": p_value,
        "screen_alpha": alpha,
        "screen_pass": screen_pass,
        "phase_c_confirmation_2000_authorized": screen_pass,
        "hrsm_M_status": "candidate_not_admitted",
        "claim_cap": "exploratory_track_level_self_history",
        "reason": (
            "Screen passed; freeze this design and run 2000-replicate confirmation."
            if screen_pass else
            "Selection-aware null screen failed; do not claim memory or escalate permutations."
        ),
    }
    (out_root / "bh_memory_generator3_phase_c_recompute_screen_verdict.json").write_text(
        json.dumps(verdict, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
