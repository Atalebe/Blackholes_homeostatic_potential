from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

bh = pd.read_csv(cfg["data"]["bh_level_csv"])
tracks = pd.read_parquet(cfg["data"]["track_phi_parquet"])

bh = bh.replace([np.inf, -np.inf], np.nan)
tracks = tracks.replace([np.inf, -np.inf], np.nan)

bins = cfg["plots"]["mass_bins"]
top_n = cfg["plots"]["top_n_extreme"]
fig_prefix = Path(cfg["outputs"]["figure_prefix"])
fig_prefix.parent.mkdir(parents=True, exist_ok=True)

# Mass-bin label
def assign_bins(series, bins):
    edges = [b[0] for b in bins] + [bins[-1][1]]
    labels = [f"{lo:.1f}_{hi:.1f}" for lo, hi in bins]
    return pd.cut(series, bins=edges, labels=labels, include_lowest=True, right=False)

bh["mass_bin_diag"] = assign_bins(bh["log10_mbh_final"], bins)

# Bin summary
rows = []
for lab, g in bh.groupby("mass_bin_diag", observed=False):
    if len(g) == 0:
        continue
    rows.append({
        "mass_bin": str(lab),
        "n_bh": len(g),
        "phi_median": g["track_median_phi"].median(),
        "phi_p16": g["track_median_phi"].quantile(0.16),
        "phi_p84": g["track_median_phi"].quantile(0.84),
        "ripeness_median": g["ripeness_bh"].median(),
        "ripeness_p16": g["ripeness_bh"].quantile(0.16),
        "ripeness_p84": g["ripeness_bh"].quantile(0.84),
    })
bin_summary = pd.DataFrame(rows)
bin_summary.to_csv(cfg["outputs"]["bin_summary_csv"], index=False)

# Histograms by mass bin
for ycol, xlabel in [
    ("track_median_phi", "track_median_phi"),
    ("ripeness_bh", "ripeness_bh"),
]:
    n_bins = len(bins)
    ncols = 3
    nrows = int(np.ceil(n_bins / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(12, 3.5 * nrows))
    axes = np.atleast_1d(axes).ravel()

    for ax, (lo, hi) in zip(axes, bins):
        lab = f"{lo:.1f}_{hi:.1f}"
        g = bh[bh["mass_bin_diag"].astype(str) == lab]
        vals = g[ycol].dropna().values
        if len(vals) > 0:
            ax.hist(vals, bins=20)
        ax.set_title(f"{lab}, N={len(vals)}")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("count")

    for ax in axes[len(bins):]:
        ax.axis("off")

    fig.tight_layout()
    fig.savefig(f"{fig_prefix}_{ycol}_hist_by_massbin.png", dpi=160)
    plt.close(fig)

# Extreme BHs by phi
phi_med = bh["track_median_phi"].median()
bh["phi_abs_dev"] = np.abs(bh["track_median_phi"] - phi_med)

extreme_phi = pd.concat([
    bh.nlargest(top_n, "track_median_phi"),
    bh.nsmallest(top_n, "track_median_phi"),
    bh.nlargest(top_n, "phi_abs_dev"),
]).drop_duplicates(subset=["bh_id"])

extreme_phi = extreme_phi.sort_values(
    ["phi_abs_dev", "track_median_phi"], ascending=[False, False]
)
extreme_phi.to_csv(cfg["outputs"]["extreme_phi_csv"], index=False)

# Extreme BHs by ripeness
extreme_ripeness = pd.concat([
    bh.nlargest(top_n, "ripeness_bh"),
    bh.nsmallest(top_n, "ripeness_bh"),
]).drop_duplicates(subset=["bh_id"]).sort_values("ripeness_bh")
extreme_ripeness.to_csv(cfg["outputs"]["extreme_ripeness_csv"], index=False)

# Track plots for extreme phi BHs
def plot_tracks(selected_df, suffix):
    ids = selected_df["bh_id"].tolist()
    use = tracks[tracks["bh_id"].isin(ids)].copy()
    if use.empty:
        return

    n = len(ids)
    ncols = 2
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(12, 2.8 * nrows), sharex=False)
    axes = np.atleast_1d(axes).ravel()

    for ax, bh_id in zip(axes, ids):
        g = use[use["bh_id"] == bh_id].sort_values("t")
        meta = selected_df[selected_df["bh_id"] == bh_id].iloc[0]
        ax.plot(g["t"], g["lambda_bh_t"], label="lambda_bh_t")
        if "phi_bh" in g.columns:
            ax.plot(g["t"], g["phi_bh"], label="phi_bh")
        ax.set_title(
            f"BH {bh_id}\nlogM={meta['log10_mbh_final']:.2f}, "
            f"cat={meta['category']}, major={meta['has_major']}"
        )
        ax.set_xlabel("t")
        ax.set_ylabel("value")
        ax.legend(fontsize=8)

    for ax in axes[len(ids):]:
        ax.axis("off")

    fig.tight_layout()
    fig.savefig(f"{fig_prefix}_{suffix}_tracks.png", dpi=160)
    plt.close(fig)

plot_tracks(extreme_phi.nlargest(top_n, "track_median_phi"), "extreme_phi_high")
plot_tracks(extreme_phi.nsmallest(top_n, "track_median_phi"), "extreme_phi_low")
plot_tracks(extreme_ripeness.nlargest(top_n, "ripeness_bh"), "extreme_ripeness_high")
plot_tracks(extreme_ripeness.nsmallest(top_n, "ripeness_bh"), "extreme_ripeness_low")

print(f"[ok] wrote {cfg['outputs']['bin_summary_csv']}")
print(f"[ok] wrote {cfg['outputs']['extreme_phi_csv']}")
print(f"[ok] wrote {cfg['outputs']['extreme_ripeness_csv']}")
print(bin_summary.to_string(index=False))
