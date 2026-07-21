import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[1] / "scripts" / "49_enrich_bh_memory_candidates_deeplag.py"
spec = importlib.util.spec_from_file_location("deeplag", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    rows = []
    for bh_id, offset in [(1, 0), (2, 100)]:
        for i in range(6):
            rows.append({"bh_id": bh_id, "row_in_track": i, "lambda_current": offset+i, "delta_u_next": offset+10+i})
    return pd.DataFrame(rows)


def test_exact_lag_columns_and_no_cross_track_bleed():
    result = module.enrich(fixture(), "bh_id", "row_in_track")
    assert len(result) == 6
    for _, row in result.iterrows():
        assert row.lambda_previous == row.lambda_current - 1
        assert row.lambda_previous2 == row.lambda_current - 2
        assert row.lambda_previous3 == row.lambda_current - 3
        assert row.delta_u_previous == row.delta_u_next - 1
        assert row.delta_u_previous2 == row.delta_u_next - 2
        assert row.delta_u_previous3 == row.delta_u_next - 3


def test_row_loss_is_three_per_track():
    raw = fixture()
    result = module.enrich(raw, "bh_id", "row_in_track")
    assert len(raw) - len(result) == 3 * raw.bh_id.nunique()
