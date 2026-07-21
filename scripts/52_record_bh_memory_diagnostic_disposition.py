#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(verdict: dict) -> dict:
    observed = float(verdict["observed"]["fractional_test_improvement"])
    null_mean = float(verdict["null_mean_fractional_improvement"])
    return {
        "run_id": verdict["run_id"],
        "tau_track_fraction": float(verdict["observed"]["selected_tau_track_fraction"]),
        "observed_fractional_improvement": observed,
        "null_mean_fractional_improvement": null_mean,
        "null_adjusted_order_excess": observed - null_mean,
        "null_q95_fractional_improvement": float(verdict["null_q95_fractional_improvement"]),
        "exceedances": int(verdict["exceedances"]),
        "p_one_sided_plus_one": float(verdict["p_one_sided_plus_one"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()

    short = summarize(read_json(root / "outputs/protocol/memory_generator3_ladder_sensitivity/lag3/bh_memory_generator3_phase_c_recompute_screen_verdict.json"))
    tau002 = summarize(read_json(root / "outputs/protocol/memory_generator3_ar3_tau002_sensitivity/bh_memory_generator3_phase_c_recompute_screen_verdict.json"))
    floor = 0.01
    short["practical_floor_pass"] = short["null_adjusted_order_excess"] >= floor
    tau002["practical_floor_pass"] = tau002["null_adjusted_order_excess"] >= floor

    disposition = {
        "schema_version": 1,
        "run_id": "BH-MEMORY-DIAGNOSTIC-DISPOSITION-005",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "posthoc_diagnostic_disposition",
        "practical_null_excess_floor": floor,
        "ar3_tau005": short,
        "ar3_tau002": tau002,
        "verdict": "statistically_detectable_but_scale_fragile_short_scale_order_dependence",
        "advancing_scale": 0.005 if short["practical_floor_pass"] else None,
        "tau002_disposition": "detectable_but_below_practical_floor" if not tau002["practical_floor_pass"] else "practical_floor_pass",
        "depth_status": "unresolved_no_fixed_row_lag_claim",
        "primary_confirmation_unchanged": True,
        "hrsm_M_status": "candidate_not_admitted",
        "authorized_claim": "posthoc short-scale order-dependent predictive structure beyond an AR3 baseline",
        "prohibited_claims": [
            "confirmatory_beyond_AR3_memory",
            "physical_memory_timescale",
            "fixed_lag_4_to_10_support_without_kernel_support_audit",
            "independent_H_S_axes",
            "host_galaxy_regulation",
        ],
    }
    out = root / "outputs/protocol/memory_generator3_disposition/bh_memory_diagnostic_disposition_005.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(disposition, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(disposition, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
