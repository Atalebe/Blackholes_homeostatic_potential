#!/usr/bin/env python3
"""Prove that the primary confirmation still resolves to its original design."""
from __future__ import annotations

import json
from pathlib import Path

import yaml


primary = Path("configs/protocol/bh_memory_generator3_phase_c_v1.yaml")
script = Path("scripts/46_screen_bh_memory_generator3_selection_null.py")
cfg = yaml.safe_load(primary.read_text(encoding="utf-8"))
c = cfg["columns"]
resolved_baseline = list(c.get("baseline_continuous", [c["current"], c["delta_time"]]))
expected_baseline = ["lambda_current", "delta_u_next"]
expected_grid = [0.02, 0.05, 0.10, 0.20]
text = script.read_text(encoding="utf-8")
checks = {
    "primary_baseline": resolved_baseline,
    "primary_tau_grid": [float(x) for x in cfg["selection"]["tau_track_fractions"]],
    "baseline_is_config_gated": 'c.get("baseline_continuous"' in text,
    "primary_baseline_unchanged": resolved_baseline == expected_baseline,
    "primary_tau_grid_unchanged": [float(x) for x in cfg["selection"]["tau_track_fractions"]] == expected_grid,
    "primary_confirmation_unchanged": False,
}
checks["primary_confirmation_unchanged"] = bool(
    checks["baseline_is_config_gated"]
    and checks["primary_baseline_unchanged"]
    and checks["primary_tau_grid_unchanged"]
)
print(json.dumps(checks, indent=2))
if not checks["primary_confirmation_unchanged"]:
    raise SystemExit(2)
