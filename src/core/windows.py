import numpy as np

def define_quantile_window(df, group_col, phi_col="phi_bh",
                           q_low=0.35, q_high=0.65):
    in_window = np.zeros(len(df), dtype=bool)
    low_arr = np.full(len(df), np.nan)
    high_arr = np.full(len(df), np.nan)

    for _, idx in df.groupby(group_col, observed=False).groups.items():
        vals = df.loc[idx, phi_col].values
        ql = np.nanquantile(vals, q_low)
        qh = np.nanquantile(vals, q_high)
        low_arr[idx] = ql
        high_arr[idx] = qh
        in_window[idx] = (vals >= ql) & (vals <= qh)

    df["phi_window_low"] = low_arr
    df["phi_window_high"] = high_arr
    df["in_window"] = in_window
    return df
