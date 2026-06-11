import numpy as np
import pandas as pd

def binned_variance(df, x_col, y_col, bins, min_count=20):
    rows = []
    cats = pd.cut(df[x_col], bins=bins, include_lowest=True)
    for interval, g in df.groupby(cats, observed=False):
        if len(g) < min_count:
            continue
        rows.append({
            "x_mid": 0.5 * (interval.left + interval.right),
            "n": len(g),
            "var_y": np.nanvar(g[y_col].values, ddof=1)
        })
    return pd.DataFrame(rows)

def fit_linear(x, y):
    coeffs = np.polyfit(x, y, 1)
    return {"slope": coeffs[0], "intercept": coeffs[1]}
