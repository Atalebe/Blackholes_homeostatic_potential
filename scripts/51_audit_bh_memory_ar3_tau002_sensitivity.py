#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


EXPECTED_BASELINE = [
    "lambda_current",
    "lambda_previous",
    "lambda_previous2",
    "lambda_previous3",
    "delta_u_next",
    "delta_u_previous",
    "delta_u_previous2",
    "delta_u_previous3",
]
EXPECTED_PRIMARY_BASELINE = ["lambda_current", "delta_u_next"]
EXPECTED_PRIMARY_GRID = [0.02, 0.05, 0.1, 0.2]


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()

    b = load(root / "configs/protocol/bh_memory_generator3_ar3_tau002_phase_b.yaml")
    c = load(root / "configs/protocol/bh_memory_generator3_ar3_tau002_phase_c.yaml")
    primary_b = load(root / "configs/protocol/bh_memory_generator3_phase_b_v1.yaml")
    primary_c = load(root / "configs/protocol/bh_memory_generator3_phase_c_v1.yaml")

    checks = {
        "phase_b_ar3_baseline_exact": b["columns"]["baseline_continuous"] == EXPECTED_BASELINE,
        "phase_c_ar3_baseline_exact": c["columns"]["baseline_continuous"] == EXPECTED_BASELINE,
        "phase_b_singleton_tau002": b["selection"]["tau_track_fractions"] == [0.02],
        "phase_c_singleton_tau002": c["selection"]["tau_track_fractions"] == [0.02],
        "same_candidate": b["data"]["candidate_parquet"] == c["data"]["candidate_parquet"],
        "posthoc_only": b.get("status") == c.get("status") == "posthoc_sensitivity_only",
        "primary_confirmation_unchanged_flags": bool(b.get("primary_confirmation_unchanged")) and bool(c.get("primary_confirmation_unchanged")),
        "primary_phase_b_baseline_unchanged": primary_b["columns"].get("baseline_continuous", [primary_b["columns"]["current"], primary_b["columns"]["delta_time"]]) == EXPECTED_PRIMARY_BASELINE,
        "primary_phase_b_grid_unchanged": primary_b["selection"]["tau_track_fractions"] == EXPECTED_PRIMARY_GRID,
        "primary_phase_c_baseline_unchanged": primary_c["columns"].get("baseline_continuous", [primary_c["columns"]["current"], primary_c["columns"]["delta_time"]]) == EXPECTED_PRIMARY_BASELINE,
        "primary_phase_c_grid_unchanged": primary_c["selection"]["tau_track_fractions"] == EXPECTED_PRIMARY_GRID,
    }
    result = {
        "schema_version": 1,
        "audit": "BH-MEMORY-AR3-TAU002-SENSITIVITY-PREFLIGHT-001",
        "checks": checks,
        "authorized": all(checks.values()),
        "interpretation": "posthoc_fixed_scale_robustness_only",
        "primary_confirmation_unchanged": all(v for k, v in checks.items() if k.startswith("primary_")),
    }
    print(json.dumps(result, indent=2))
    return 0 if result["authorized"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
