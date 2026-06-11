import pandas as pd

def compute_residence_fraction(track_df,
                               id_col="bh_id",
                               time_col="t",
                               in_window_col="in_window_t"):
    rows = []
    for bh_id, g in track_df.groupby(id_col):
        g = g.sort_values(time_col)
        if len(g) < 2:
            continue
        dt = g[time_col].diff().fillna(0).values
        total = dt.sum()
        inside = dt[g[in_window_col].values].sum()
        frac = inside / total if total > 0 else float("nan")
        rows.append({"bh_id": bh_id, "ripeness_bh": frac, "n_track": len(g)})
    return pd.DataFrame(rows)
