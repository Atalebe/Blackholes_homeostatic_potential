#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml


EXPECTED_BASELINE = ["lambda_current", "delta_u_next"]
EXPECTED_GRID = [0.02, 0.05, 0.1, 0.2]
PINNED = [
    "configs/protocol/bh_memory_generator3_primary_confirmation_2000.yaml",
    "configs/protocol/bh_memory_generator3_phase_b_v1.yaml",
    "configs/protocol/bh_memory_generator3_phase_c_v1.yaml",
    "scripts/46_screen_bh_memory_generator3_selection_null.py",
    "src/core/memory_nulls.py",
    "src/core/predictive_memory.py",
    "outputs/protocol/memory_generator3/bh_memory_generator3_candidates.parquet",
    "outputs/protocol/memory_generator3/bh_memory_generator3_phase_b_verdict.json",
    "outputs/protocol/memory_generator3/bh_memory_generator3_phase_c_recompute_screen_verdict.json",
]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def baseline(cfg: dict) -> list[str]:
    c = cfg["columns"]
    return list(c.get("baseline_continuous", [c["current"], c["delta_time"]]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    confirmation = load_yaml(root / PINNED[0])
    primary_b = load_yaml(root / PINNED[1])
    primary_c = load_yaml(root / PINNED[2])
    phase_b_verdict = json.loads((root / PINNED[7]).read_text(encoding="utf-8"))
    screen_verdict = json.loads((root / PINNED[8]).read_text(encoding="utf-8"))

    checks = {
        "confirmation_baseline_exact": baseline(confirmation) == EXPECTED_BASELINE,
        "confirmation_grid_exact": confirmation["selection"]["tau_track_fractions"] == EXPECTED_GRID,
        "confirmation_permutations_2000": confirmation["screen"]["n_permutations"] == 2000,
        "confirmation_seed_12345": confirmation["seed"] == 12345,
        "confirmation_sample_cap_100000": confirmation["screen"]["max_rows_per_split"] == 100000,
        "primary_phase_b_baseline_unchanged": baseline(primary_b) == EXPECTED_BASELINE,
        "primary_phase_c_baseline_unchanged": baseline(primary_c) == EXPECTED_BASELINE,
        "primary_phase_b_grid_unchanged": primary_b["selection"]["tau_track_fractions"] == EXPECTED_GRID,
        "primary_phase_c_grid_unchanged": primary_c["selection"]["tau_track_fractions"] == EXPECTED_GRID,
        "same_candidate_as_primary": confirmation["data"]["candidate_parquet"] == primary_c["data"]["candidate_parquet"],
        "phase_b_authorized": bool(phase_b_verdict.get("phase_c_selection_within_null_authorized")),
        "screen_authorized_confirmation": bool(screen_verdict.get("phase_c_confirmation_2000_authorized")),
        "screen_recomputed_memory": bool(screen_verdict.get("causal_memory_recomputed_inside_each_null")),
        "screen_repeated_selection": bool(screen_verdict.get("selection_repeated_inside_each_null")),
    }
    missing = [name for name in PINNED if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing pinned inputs: {missing}")
    manifest = {
        "schema_version": 1,
        "run_id": "BH-MEMORY-GENERATOR3-PRIMARY-CONFIRMATION-FREEZE-006",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "freeze_authorized": all(checks.values()),
        "files": {name: {"sha256": digest(root / name)} for name in PINNED},
        "claim_cap": "small_order_dependent_self_history_gain_in_tng_lambda_tracks",
        "hrsm_M_status": "candidate_not_admitted",
        "physical_timescale_interpretation_authorized": False,
        "posthoc_ar3_diagnostics_excluded_from_primary": True,
    }
    out = root / "outputs/protocol/memory_generator3_primary_confirmation_2000/bh_memory_primary_confirmation_freeze_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["freeze_authorized"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
