import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).parents[1] / "scripts" / "42_freeze_bh_time_track_integrity.py"
SPEC = importlib.util.spec_from_file_location("freeze", SCRIPT)
freeze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(freeze)


def config():
    return {
        "columns": {"id": "bh_id", "time": "t", "phi": "phi", "low": "low", "high": "high", "membership": "member"},
        "exposure": {"short_span_fraction_of_median": 0.1, "min_rows_warning": 3},
        "tolerances": {"residence_difference": 1e-12},
        "cadence": {"dt_cv_warning": 1.0},
    }


def frame(times=(0.0, 1.0, 10.0), member=(True, False, True)):
    return pd.DataFrame({"bh_id": [1] * 3, "t": times, "phi": [0.5, 2.0, 0.5], "low": [0.0] * 3, "high": [1.0] * 3, "member": member})


def test_right_endpoint_probe_is_nine_tenths():
    assert np.isclose(freeze.right_residence(np.array([0., 1., 10.]), np.array([True, False, True])), 0.9)


def test_file_order_negative_step_is_not_erased():
    audit, summary = freeze.audit_tracks(frame(times=(0.0, 10.0, 1.0)), config())
    assert audit.loc[0, "file_order_negative_dt"] == 1
    assert summary["tracks_with_file_order_violations"] == 1
    assert audit.loc[0, "residence_order_difference"] > 0


def test_membership_mismatch_blocks_clean_summary():
    _, summary = freeze.audit_tracks(frame(member=(False, False, True)), config())
    assert summary["membership_mismatches"] == 1


def test_invalid_bounds_and_nonfinite_phi_are_separate():
    df = frame()
    df.loc[0, "high"] = 0.0
    df.loc[1, "phi"] = np.nan
    _, summary = freeze.audit_tracks(df, config())
    assert summary["invalid_window_bounds"] == 1
    assert summary["nonfinite_phi_or_bounds"] == 1


def test_internal_sort_detection(tmp_path):
    source = tmp_path / "ripeness.py"
    source.write_text("def compute_residence_fraction(df):\n    return df.sort_values('t')\n", encoding="utf-8")
    result = freeze.function_sorts_time(source, "compute_residence_fraction")
    assert result["function_found"] and result["sort_detected"]
