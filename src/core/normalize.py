import numpy as np
import pandas as pd

def mad(arr):
    med = np.nanmedian(arr)
    return np.nanmedian(np.abs(arr - med))

def robust_zscore(values, floor=1e-6):
    values = np.asarray(values, dtype=float)
    med = np.median(vals)
    scale = np.median(np.abs(vals - med))
    if not np.isfinite(scale) or scale < mad_floor:
        scale = mad_floor
    norm_vals = (vals - med) / scale
    return (values - med) / scale

def apply_within_group(df, group_col, value_col, out_col, floor=1e-6):
    out = np.full(len(df), np.nan)
    for _, idx in df.groupby(group_col, observed=False).groups.items():
        vals = df.loc[idx, value_col].values
        out[idx] = robust_zscore(vals, floor=floor)
    df[out_col] = out
    return df
