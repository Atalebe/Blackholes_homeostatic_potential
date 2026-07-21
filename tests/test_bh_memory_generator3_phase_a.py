import numpy as np
import pytest

from src.core.causal_memory import (
    causal_exponential_memory,
    chronological_split,
    normalize_track_time,
)


def test_time_normalization():
    u = normalize_track_time(np.array([2.0, 3.0, 6.0]))
    assert np.allclose(u, [0.0, 0.25, 1.0])


def test_nonmonotonic_time_rejected():
    with pytest.raises(ValueError):
        normalize_track_time(np.array([0.0, 2.0, 1.0]))


def test_memory_is_strictly_past_only():
    u = np.array([0.0, 0.1, 0.4, 1.0])
    x1 = np.array([1.0, 2.0, 3.0, 4.0])
    x2 = np.array([1.0, 2.0, 3000.0, 4000.0])
    m1 = causal_exponential_memory(u, x1, 0.2)
    m2 = causal_exponential_memory(u, x2, 0.2)
    assert np.isnan(m1[0])
    assert m1[1] == m2[1]
    assert m1[2] == m2[2]
    assert m1[3] != m2[3]


def test_first_memory_equals_first_completed_interval_value():
    m = causal_exponential_memory(
        np.array([0.0, 0.2, 1.0]),
        np.array([7.0, 9.0, 11.0]),
        0.1,
    )
    assert m[1] == 7.0


def test_chronological_split_has_all_partitions():
    labels = chronological_split(10, 0.6, 0.2)
    assert list(labels[:6]) == ["train"] * 6
    assert list(labels[6:8]) == ["validation"] * 2
    assert list(labels[8:]) == ["test"] * 2
