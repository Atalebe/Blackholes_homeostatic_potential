from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml
from src.core.variance_scaling import binned_variance, fit_linear
from src.core.permutation_nulls import variance_slope_null
from src.core.state_vector import compute_phi_bh
from src.core.windows import define_quantile_window

def mass_class_from_bins(values, bins):
    edges = [b[0] for b in bins] + [bins[-1][1]]
    labels = [f"{lo:.1f}_{hi:.1f}" for lo, hi in bins]
    return pd.cut(values, bins=edges, labels=labels, include_lowest=True, right=False)

def robust_hat(frame, group_col, raw_col, hat_col, mad_floor=1e-3):
    parts = []
    for cls, g in frame.groupby(group_col, observed=False):
        vals = pd.to_numeric(g[raw_col], errors="coerce").to_numpy(dtype=float)
        med = np.nanmedian(vals)
        mad = np.nanmedian(np.abs(vals - med))
        if not np.isfinite(mad) or mad < mad_floor:
            mad = mad_floor
        gg = g.copy()
        gg[hat_col] = (vals - med) / mad
        parts.append(gg)
    return pd.concat(parts, ignore_index=True)

cfg = load_yaml(CONFIG_PATH)
runtime = pd.read_csv(cfg["data"]["runtime_table"]).copy()

# Canonical source columns
runtime["gal_id"] = runtime["gal_id"].astype(str)
runtime["logMstar"] = pd.to_numeric(runtime["logMstar_gama"], errors="coerce")
runtime["logMbh"] = pd.to_numeric(runtime["logMbh"], errors="coerce")
runtime["z"] = pd.to_numeric(runtime["z_gama"], errors="coerce")
runtime["OIIIB_FLUX"] = pd.to_numeric(runtime["OIIIB_FLUX"], errors="coerce")
runtime["HB_FLUX"] = pd.to_numeric(runtime["HB_FLUX"], errors="coerce")
runtime["D4000N"] = pd.to_numeric(runtime["D4000N"], errors="coerce")
runtime["SN"] = pd.to_numeric(runtime["SN"], errors="coerce")
runtime["NQ"] = pd.to_numeric(runtime["NQ"], errors="coerce")
runtime["sigma_star_gama"] = pd.to_numeric(runtime["sigma_star_gama"], errors="coerce")
base_sel = cfg["selection"]
bins = cfg["class_conditioning"]["bh_mass_bins"]
vs = cfg["variance_scaling"]
x_bins = np.arange(vs["bin_start"], vs["bin_stop"] + vs["bin_step"], vs["bin_step"])

summary_rows = []
binned_rows = []

for variant in cfg["variants"]:
    name = variant["name"]
    sn_min = variant.get("sn_min", base_sel["sn_min"])
    nq_min = variant.get("nq_min", base_sel["nq_min"])
    mad_floor = float(variant.get("mad_floor", cfg["normalization"]["mad_floor"]))
    clip_abs = float(variant.get("clip_abs", cfg["normalization"]["clip_abs"]))

    mask = pd.Series(True, index=runtime.index)
    mask &= np.isfinite(runtime["logMstar"])
    mask &= np.isfinite(runtime["logMbh"])
    mask &= np.isfinite(runtime["z"])
    mask &= runtime["z"] <= base_sel["z_max"]
    mask &= runtime["logMstar"].between(base_sel["host_mass_log10_min"], base_sel["host_mass_log10_max"])
    mask &= runtime["logMstar"] > 0
    mask &= np.isfinite(runtime["SN"]) & (runtime["SN"] >= sn_min)
    mask &= np.isfinite(runtime["NQ"]) & (runtime["NQ"] >= nq_min)

    work = runtime.loc[mask].copy().reset_index(drop=True)

    # H definition
    if variant["h_kind"] == "log10_col":
        col = variant["h_col"]
        work = work[np.isfinite(work[col]) & (work[col] > 0)].copy()
        work["H_raw"] = np.log10(work[col])

    elif variant["h_kind"] == "log10_ratio":
        num = variant["h_col_num"]
        den = variant["h_col_den"]
        work = work[
            np.isfinite(work[num]) & np.isfinite(work[den]) &
            (work[num] > 0) & (work[den] > 0)
        ].copy()
        work["H_raw"] = np.log10(work[num] / work[den])

    else:
        raise ValueError(f"Unknown h_kind for {name}: {variant['h_kind']}")

    # S definition
    if variant["s_kind"] == "offset_from_class_median_log10_col":
        col = variant["s_col"]
        work = work[np.isfinite(work[col]) & (work[col] > 0)].copy()
        work["_S_LOG"] = np.log10(work[col])

    elif variant["s_kind"] == "direct_log10_col":
        col = variant["s_col"]
        work = work[np.isfinite(work[col]) & (work[col] > 0)].copy()
        work["_S_LOG"] = np.log10(work[col])

    else:
        raise ValueError(f"Unknown s_kind for {name}: {variant['s_kind']}")

    work["bh_mass_class"] = mass_class_from_bins(work["logMbh"], bins)
    work = work.dropna(subset=["bh_mass_class"]).reset_index(drop=True)

    if variant["s_kind"] == "offset_from_class_median_log10_col":
        med = work.groupby("bh_mass_class", observed=False)["_S_LOG"].median().rename("_S_MED")
        work = work.merge(med, left_on="bh_mass_class", right_index=True, how="left")
        work["S_raw"] = -np.abs(work["_S_LOG"] - work["_S_MED"])
    else:
        work["S_raw"] = work["_S_LOG"]

    work = robust_hat(work, "bh_mass_class", "H_raw", "H_hat", mad_floor=mad_floor)
    work = robust_hat(work, "bh_mass_class", "S_raw", "S_hat", mad_floor=mad_floor)

    work["H_hat"] = work["H_hat"].clip(-clip_abs, clip_abs)
    work["S_hat"] = work["S_hat"].clip(-clip_abs, clip_abs)

    work = compute_phi_bh(work, h_hat_col="H_hat", s_hat_col="S_hat")
    work = define_quantile_window(
        work,
        group_col="bh_mass_class",
        phi_col="phi_bh",
        q_low=cfg["window"]["q_low"],
        q_high=cfg["window"]["q_high"],
    )

    bv = binned_variance(
        work,
        x_col=vs.get("x", "logMbh"),
        y_col=vs.get("y", "phi_bh"),
        bins=x_bins,
        min_count=vs["min_bin_count"],
    )

    if len(bv) < 2:
        summary_rows.append({
            "variant": name,
            "retained_rows": len(work),
            "obs_slope": np.nan,
            "intercept": np.nan,
            "p_one_sided_negative": np.nan,
            "n_perm": 0,
            "n_bins_used": len(bv),
            "note": "not enough populated bins",
        })
        continue

    fit = fit_linear(bv["x_mid"].values, bv["var_y"].values)

    null = variance_slope_null(
        work,
        group_col="global",
        x_col=vs.get("x", "logMbh"),
        y_col=vs.get("y", "phi_bh"),
        bins=x_bins,
        n_perm=cfg["nulls"]["n_perm"],
        min_count=vs["min_bin_count"],
        seed=cfg["run"]["seed"],
    )

    tmp = bv.copy()
    tmp["variant"] = name
    binned_rows.append(tmp)

    summary_rows.append({
        "variant": name,
        "retained_rows": len(work),
        "obs_slope": fit["slope"],
        "intercept": fit["intercept"],
        "p_one_sided_negative": null["p_one_sided_negative"],
        "n_perm": len(null["null_slopes"]),
        "n_bins_used": len(bv),
        "mad_floor": mad_floor,
        "clip_abs": clip_abs,
        "sn_min": sn_min,
        "nq_min": nq_min,
        "h_kind": variant["h_kind"],
        "s_kind": variant["s_kind"],
        "note": "",
    })

summary = pd.DataFrame(summary_rows)
binned = pd.concat(binned_rows, ignore_index=True) if binned_rows else pd.DataFrame()

summary_out = Path(cfg["outputs"]["summary_csv"])
binned_out = Path(cfg["outputs"]["binned_csv"])
summary_out.parent.mkdir(parents=True, exist_ok=True)

summary.to_csv(summary_out, index=False)
binned.to_csv(binned_out, index=False)

print(f"[ok] wrote {summary_out}")
print(f"[ok] wrote {binned_out}")
print(summary.to_string(index=False))
