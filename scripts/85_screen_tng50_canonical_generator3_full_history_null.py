#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.core.causal_memory import causal_exponential_memory, normalize_track_time
from src.core.memory_nulls import plus_one_p


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_evaluate(root: Path):
    path = root / "scripts/46_screen_bh_memory_generator3_selection_null.py"
    spec = importlib.util.spec_from_file_location("frozen_phase_c", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.evaluate


class TrackPlan(NamedTuple):
    signal: np.ndarray
    u: np.ndarray
    candidate_positions: np.ndarray
    raw_indices: np.ndarray


def read_selected(path: Path, columns, identifiers: list[int]) -> pd.DataFrame:
    try:
        return pd.read_parquet(path, columns=columns, filters=[("bh_id", "in", identifiers)])
    except (TypeError, ValueError, OSError):
        frame = pd.read_parquet(path, columns=columns)
        return frame.loc[frame["bh_id"].isin(identifiers)].copy()


def build_plans(raw: pd.DataFrame, candidate: pd.DataFrame, cfg: dict) -> tuple[list[TrackPlan], dict]:
    c = cfg["columns"]
    positions = {
        int(identifier): group.index.to_numpy(dtype=np.int64)
        for identifier, group in candidate.groupby(c["id"], sort=False, observed=False)
    }
    candidate_groups = {
        int(identifier): group.sort_values(c["order"])
        for identifier, group in candidate.groupby(c["id"], sort=False, observed=False)
    }
    plans = []
    exact = []
    for identifier, raw_group in raw.groupby(c["id"], sort=False, observed=False):
        identifier = int(identifier)
        if identifier not in positions:
            continue
        rg = raw_group.sort_values(c["raw_time"], kind="stable").reset_index(drop=True)
        cg = candidate_groups[identifier]
        raw_indices = cg[c["order"]].to_numpy(dtype=np.int64)
        expected = np.arange(1, len(rg) - 1, dtype=np.int64)
        index_ok = np.array_equal(raw_indices, expected)
        time_ok = np.allclose(
            cg[c["candidate_time"]].to_numpy(float),
            rg[c["raw_time"]].to_numpy(float)[raw_indices],
            rtol=0.0,
            atol=1e-12,
        )
        exact.append(index_ok and time_ok)
        plans.append(TrackPlan(
            rg[c["raw_signal"]].to_numpy(float),
            normalize_track_time(rg[c["raw_time"]].to_numpy(float)),
            positions[identifier],
            raw_indices,
        ))
    return plans, {
        "all_candidate_raw_indices_exact": bool(all(exact)),
        "n_planned_tracks": len(plans),
        "all_selected_tracks_planned": len(plans) == candidate[c["id"]].nunique(),
        "all_selected_candidate_rows_mapped": sum(len(plan.raw_indices) for plan in plans) == len(candidate),
    }


def recompute(candidate: pd.DataFrame, plans: list[TrackPlan], taus: list[float],
              rng: np.random.Generator) -> pd.DataFrame:
    destroyed = candidate.copy()
    memories = {tau: np.full(len(candidate), np.nan, dtype=float) for tau in taus}
    for plan in plans:
        proxy = plan.signal.copy()
        permutable = np.arange(0, len(proxy) - 1, dtype=np.int64)
        proxy[permutable] = proxy[permutable][rng.permutation(len(permutable))]
        for tau in taus:
            full = causal_exponential_memory(plan.u, proxy, tau)
            memories[tau][plan.candidate_positions] = full[plan.raw_indices]
    for tau in taus:
        destroyed[f"memory_tau_{tau:g}"] = memories[tau]
    return destroyed


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
    phase_b_path = root / cfg["data"]["phase_b_verdict"]
    phase_b = json.loads(phase_b_path.read_text(encoding="utf-8"))
    if not phase_b.get("phase_c_full_history_screen_authorized"):
        raise RuntimeError("Canonical hash-split Phase B did not authorize Phase C")
    candidate_path = root / cfg["data"]["candidate_parquet"]
    if sha256(candidate_path) != phase_b.get("candidate_sha256"):
        raise RuntimeError("Canonical Phase B candidate hash mismatch")
    plan_path = root / manifest["track_plan"]
    if sha256(plan_path) != manifest["track_plan_sha256"]:
        raise RuntimeError("Canonical complete-track plan changed")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    identifiers = [
        int(identifier)
        for split in cfg["screen"]["split_order"]
        for identifier in plan["selected_track_ids"][split]
    ]
    c = cfg["columns"]
    candidate = read_selected(candidate_path, None, identifiers).reset_index(drop=True)
    raw = read_selected(
        root / cfg["data"]["raw_track_parquet"],
        [c["id"], c["raw_time"], c["raw_signal"]],
        identifiers,
    )
    expected_count = int(cfg["screen"]["complete_tracks_per_split"])
    counts = candidate.groupby(c["split"])[c["id"]].nunique().to_dict()
    if any(int(counts.get(split, 0)) != expected_count for split in cfg["screen"]["split_order"]):
        raise RuntimeError(f"Canonical selected track counts changed: {counts}")
    evaluate = load_evaluate(root)
    observed_selection, observed = evaluate(candidate, cfg)
    plans, mapping = build_plans(raw, candidate, cfg)
    if not all(mapping.values()):
        raise RuntimeError(f"Canonical raw-to-candidate mapping failed: {mapping}")
    taus = [float(value) for value in cfg["selection"]["tau_track_fractions"]]
    rng = np.random.default_rng(int(cfg["seed"]))
    effects = []
    selected_taus = []
    n_perm = int(cfg["screen"]["n_permutations"])
    for index in range(n_perm):
        destroyed = recompute(candidate, plans, taus, rng)
        selection, result = evaluate(destroyed, cfg)
        effects.append(float(result["fractional_test_improvement"]))
        selected_taus.append(float(result["selected_tau_track_fraction"]))
        if (index + 1) % int(cfg["screen"]["progress_every"]) == 0:
            print(f"[progress] {index + 1}/{n_perm}", flush=True)
    effects_array = np.asarray(effects)
    observed_effect = float(observed["fractional_test_improvement"])
    null_mean = float(np.mean(effects_array))
    excess = observed_effect - null_mean
    exceedances = int(np.sum(effects_array >= observed_effect))
    p_value = plus_one_p(exceedances, n_perm)
    floor = float(cfg["gates"]["minimum_fractional_test_improvement"])
    passed = bool(
        observed_effect >= floor
        and excess >= floor
        and p_value <= float(cfg["gates"]["screen_alpha"])
    )
    is_confirmation = n_perm >= 2000
    out_dir = root / cfg["outputs"]["root"]
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "replicate": np.arange(n_perm),
        "selected_tau_track_fraction": selected_taus,
        "fractional_test_improvement": effects,
    }).to_csv(out_dir / f"{cfg['outputs']['label']}_replicates.csv", index=False)
    verdict = {
        "schema_version": 1,
        "run_id": cfg["run_id"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "split_method": "sha256_id_modulo_10_canonical_repair",
        "null": "permute_complete_raw_track_and_recompute_complete_history",
        "complete_tracks_per_split": expected_count,
        "selected_track_counts": {key: int(value) for key, value in counts.items()},
        "n_selected_tracks": int(candidate[c["id"]].nunique()),
        "n_selected_candidate_rows": int(len(candidate)),
        "full_raw_seed_history_included": True,
        "terminal_target_only_row_permuted": False,
        "candidate_fragments_used_for_recompute": False,
        "selection_repeated_inside_each_null": True,
        "mapping_checks": mapping,
        "phase_b_verdict_sha256": sha256(phase_b_path),
        "n_permutations": n_perm,
        "observed": observed,
        "null_mean_fractional_improvement": null_mean,
        "null_q95_fractional_improvement": float(np.quantile(effects_array, 0.95)),
        "null_adjusted_order_excess": excess,
        "exceedances": exceedances,
        "p_one_sided_plus_one": p_value,
        "minimum_fractional_improvement": floor,
        "screen_pass": passed,
        "confirmation_2000_authorized": bool(passed and not is_confirmation),
        "confirmation_status": (
            "passed" if is_confirmation and passed
            else "failed" if is_confirmation
            else "not_confirmation"
        ),
        "generator4_execution_authorized": bool(is_confirmation and passed),
        "canonical_external_generator3_status": (
            "confirmed_full_history_2000"
            if is_confirmation and passed
            else "failed_canonical_hash_split_full_history_confirmation"
            if is_confirmation
            else "passed_screen_pending_2000_confirmation"
            if passed
            else "failed_canonical_hash_split_full_history_screen"
        ),
        "prior_seeded_split_confirmation_status": "retained_as_nonbinding_robustness_evidence",
        "hrsm_M_status": (
            "externally_replicated_self_history_candidate_not_admitted"
            if is_confirmation and passed
            else "candidate_not_admitted"
        ),
        "claim_cap": (
            "confirmed_canonical_hash_split_external_order_dependent_self_history_gain"
            if is_confirmation and passed
            else "canonical_hash_split_external_order_dependent_screen"
            if passed
            else "canonical_hash_split_raw_effect_only_null_test_failed"
        ),
    }
    out_path = out_dir / f"{cfg['outputs']['label']}_verdict.json"
    out_path.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
