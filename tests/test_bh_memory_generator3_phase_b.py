import numpy as np
import pandas as pd

from src.core.predictive_memory import (
    bootstrap_fractional_improvement,
    fit_ridge,
    predict_ridge,
    rmse,
)


def synthetic():
    x = np.linspace(-2, 2, 100)
    return pd.DataFrame({
        "x": x,
        "m": np.sin(x),
        "group": ["a"] * 50 + ["b"] * 50,
        "y": 1.5 + 2.0 * x + 0.5 * np.sin(x),
    })


def test_ridge_predicts_synthetic_linear_signal():
    df = synthetic()
    model = fit_ridge(df, "y", ["x", "m"], ["group"], 1e-8)
    assert rmse(df["y"].to_numpy(), predict_ridge(df, model)) < 1e-8


def test_training_standardization_is_reused():
    df = synthetic()
    model = fit_ridge(df.iloc[:80], "y", ["x", "m"], ["group"], 1e-6)
    predicted = predict_ridge(df.iloc[80:], model)
    assert np.isfinite(predicted).all()


def test_bootstrap_is_deterministic():
    table = pd.DataFrame({
        "baseline_sse": [10.0, 20.0, 30.0],
        "augmented_sse": [9.0, 18.0, 27.0],
        "n_test": [10, 20, 30],
    })
    first = bootstrap_fractional_improvement(table, 50, 123)
    second = bootstrap_fractional_improvement(table, 50, 123)
    assert np.array_equal(first, second)
    assert np.all(first > 0)


def test_intercept_is_not_penalized():
    df = pd.DataFrame({"x": np.zeros(20), "group": ["a"] * 20, "y": np.full(20, 7.0)})
    model = fit_ridge(df, "y", ["x"], ["group"], 1e6)
    assert np.allclose(predict_ridge(df, model), 7.0)
