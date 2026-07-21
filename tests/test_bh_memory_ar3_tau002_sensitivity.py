from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "protocol"
EXPECTED = [
    "lambda_current", "lambda_previous", "lambda_previous2", "lambda_previous3",
    "delta_u_next", "delta_u_previous", "delta_u_previous2", "delta_u_previous3",
]


def read(name):
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))


def test_fixed_singleton_tau_in_both_phases():
    for name in ["bh_memory_generator3_ar3_tau002_phase_b.yaml", "bh_memory_generator3_ar3_tau002_phase_c.yaml"]:
        assert read(name)["selection"]["tau_track_fractions"] == [0.02]


def test_ar3_baseline_identical_in_both_phases():
    b = read("bh_memory_generator3_ar3_tau002_phase_b.yaml")
    c = read("bh_memory_generator3_ar3_tau002_phase_c.yaml")
    assert b["columns"]["baseline_continuous"] == EXPECTED
    assert c["columns"]["baseline_continuous"] == EXPECTED


def test_sensitivity_is_capped_and_separate():
    b = read("bh_memory_generator3_ar3_tau002_phase_b.yaml")
    c = read("bh_memory_generator3_ar3_tau002_phase_c.yaml")
    assert b["status"] == c["status"] == "posthoc_sensitivity_only"
    assert b["primary_confirmation_unchanged"] is True
    assert c["primary_confirmation_unchanged"] is True
    assert b["outputs"]["root"] == c["outputs"]["root"]
    assert "ladder_sensitivity" not in b["outputs"]["root"]
