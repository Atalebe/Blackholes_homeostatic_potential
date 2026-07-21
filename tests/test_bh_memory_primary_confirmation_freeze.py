from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "configs/protocol/bh_memory_generator3_primary_confirmation_2000.yaml").read_text(encoding="utf-8"))


def test_primary_design_is_exact():
    assert CFG["columns"]["baseline_continuous"] == ["lambda_current", "delta_u_next"]
    assert CFG["selection"]["tau_track_fractions"] == [0.02, 0.05, 0.1, 0.2]


def test_confirmation_parameters_are_exact():
    assert CFG["seed"] == 12345
    assert CFG["screen"]["n_permutations"] == 2000
    assert CFG["screen"]["max_rows_per_split"] == 100000


def test_confirmation_output_is_separate():
    assert CFG["outputs"]["root"] == "outputs/protocol/memory_generator3_primary_confirmation_2000"
    assert CFG["status"] == "frozen_primary_confirmation"


def test_claim_remains_capped():
    assert CFG["claim"]["hrsm_M_status"] == "candidate_not_admitted"
    assert CFG["claim"]["physical_timescale_interpretation_authorized"] is False
