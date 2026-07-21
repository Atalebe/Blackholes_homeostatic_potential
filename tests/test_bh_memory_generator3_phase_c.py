import numpy as np
import pandas as pd

from src.core.memory_nulls import (
    balanced_sample,
    circular_shift_memory,
    plus_one_p,
    recompute_sampled_memory,
)


def table():
    return pd.DataFrame({
        "bh_id": [1] * 6 + [2] * 6,
        "row": list(range(6)) * 2,
        "split": ["train", "train", "validation", "validation", "test", "test"] * 2,
        "m1": np.arange(12, dtype=float),
        "m2": np.arange(12, dtype=float) * 10,
    })


def test_shift_is_nonzero_and_shared_across_tau():
    df = table()
    shifted = circular_shift_memory(df, "bh_id", "split", "row", ["m1", "m2"], np.random.default_rng(7))
    for bh_id, group in shifted.groupby("bh_id"):
        original = df[df["bh_id"] == bh_id]
        assert not np.array_equal(group["m1"].to_numpy(), original["m1"].to_numpy())
        assert np.array_equal(group["m2"].to_numpy(), group["m1"].to_numpy() * 10)


def test_shift_preserves_values_per_track():
    df = table()
    shifted = circular_shift_memory(df, "bh_id", "split", "row", ["m1", "m2"], np.random.default_rng(2))
    for bh_id in [1, 2]:
        for column in ["m1", "m2"]:
            assert sorted(shifted.loc[shifted.bh_id == bh_id, column]) == sorted(df.loc[df.bh_id == bh_id, column])


def test_plus_one_p():
    assert plus_one_p(0, 200) == 1 / 201
    assert plus_one_p(200, 200) == 1.0


def test_balanced_sample_is_deterministic_and_capped():
    df = pd.concat([table()] * 20, ignore_index=True)
    first = balanced_sample(df, "split", "bh_id", 20, 3)
    second = balanced_sample(df, "split", "bh_id", 20, 3)
    assert first.equals(second)
    assert first.groupby("split").size().max() <= 20


def test_recompute_null_regenerates_past_only_memory():
    df = pd.DataFrame({
        "bh_id": [1] * 6,
        "row": np.arange(6),
        "u": np.linspace(0, 1, 6),
        "split": ["train", "train", "validation", "validation", "test", "test"],
        "x": [1., 2., 3., 4., 5., 6.],
    })
    observed = recompute_sampled_memory(df, "bh_id", "split", "row", "u", "x", [0.2])
    destroyed = recompute_sampled_memory(
        df, "bh_id", "split", "row", "u", "x", [0.2], np.random.default_rng(4)
    )
    assert len(observed) == 5
    assert np.isfinite(observed["memory_tau_0.2"]).all()
    assert not np.array_equal(observed["memory_tau_0.2"], destroyed["memory_tau_0.2"])
