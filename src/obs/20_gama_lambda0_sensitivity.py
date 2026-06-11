from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from src.utils.config import load_yaml
from src.core.normalize import apply_within_group
from src.core.state_vector import compute_phi_bh
from src.core.windows import define_quantile_window
from src.core.variance_scaling import binned_variance, fit_linear
from src.core.permutation_nulls import variance_slope_null

def mass_class_from_bins(values, bins):
    edges = [b[0] for b in bins] + [bins[-1][1]]
    labels = [f"{lo:.1f}_{hi:.1f}" for lo, hi in bins]
    return pd.cut(values, bins=edges, labels=labels, include_lowest=True, right=False)

cfg = load_yaml(CONFIG_PATH)

runtime = pd.read_csv(cfg["data"]["runtime_table"]).copy()
c = cfg["columns"]
s = cfg["selection"]

# Canonical table
df = pd.DataFrame({
    "gal_id": runtime[c["gal_id"]].astype(str),
    "logMstar": pd.to_numeric(runtime[c["logMstar"]], errors="coerce"),
    "SFR": pd.to_numeric(runtime[c["SFR"]], errors="coerce"),
    "logMbh": pd.to_numeric(runtime[c["logMbh"]], errors="coerce"),
    "mdot_bh": pd.to_numeric(runtime[c["mdot_bh"]], errors="coerce"),
    "z": pd.to_numeric(runtime[c["z"]], errors="coerce"),
    "sigma_star": pd.to_numeric(runtime[c["sigma_star"]], errors="coerce"),
    "SN": pd.to_numeric(runtime[c["sn_col"]], errors="coerce") if "sn_col" in c else np.nan,
    "NQ": pd.to_numeric(runtime[c["nq_col"]], errors="coerce") if "nq_col" in c else np.nan,
})

# QC except lambda upper cut
mask = pd.Series(True, index=df.index)
mask &= np.isfinite(df["logMstar"])
mask &= np.isfinite(df["SFR"])
mask &= np.isfinite(df["logMbh"])
mask &= np.isfinite(df["mdot_bh"])
mask &= np.isfinite(df["z"])
mask &= np.isfinite(df["sigma_star"])
mask &= df["z"] <= s["z_max"]
mask &= df["logMstar"].between(s["host_mass_log10_min"], s["host_mass_log10_max"])

if s.get("require_positive_sfr", False):
    mask &= df["SFR"] > 0
if s.get("require_positive_mdot_bh", False):
    mask &= df["mdot_bh"] > 0
if s.get("require_positive_sigma", False):
    mask &= df["sigma_star"] > 0
if s.get("require_positive_logMstar", False):
    mask &= df["logMstar"] > 0
if "sn_min" in s:
    mask &= df["SN"] >= s["sn_min"]
if "nq_min" in s:
    mask &= df["NQ"] >= s["nq_min"]

base = df.loc[mask].copy().reset_index(drop=True)

# Derived coordinates
base["log10_sbhg"] = np.log10(base["mdot_bh"]) - base["logMbh"]
base["log10_sfr_star"] = np.log10(base["SFR"]) - base["logMstar"]
base["lambda0"] = base["log10_sbhg"] - base["log10_sfr_star"]

# Lower cut only here, sweep upper later
base = base[np.isfinite(base["lambda0"])].copy()
base = base[base["lambda0"] >= s["lambda0_band_low"]].copy().reset_index(drop=True)

rel = cfg["bh_sigma_relation"]
base["logMbh_sigma"] = rel["a"] + rel["b"] * np.log10(base["sigma_star"] / rel["sigma_norm_kms"])
base["S_sigma_raw"] = -np.abs(base["logMbh"] - base["logMbh_sigma"])

upper_bounds = cfg["sweep"]["lambda0_upper_bounds"]
bins_massclass = cfg["class_conditioning"]["bh_mass_bins"]

var_cfg = cfg["variance_scaling"]
var_bins = np.arange(var_cfg["bin_start"], var_cfg["bin_stop"] + var_cfg["bin_step"], var_cfg["bin_step"])
min_bin_count = var_cfg["min_bin_count"]
n_perm = N_PERM_OVERRIDE if N_PERM_OVERRIDE is not None else cfg["nulls"]["n_perm"]

summary_rows = []
binned_rows = []

for upper in upper_bounds:
    work = base[base["lambda0"] <= upper].copy().reset_index(drop=True)

    work["H_raw"] = work["lambda0"]
    work["S_raw"] = work["S_sigma_raw"]
    work["bh_mass_class"] = mass_class_from_bins(work["logMbh"], bins_massclass)
    work = work.dropna(subset=["bh_mass_class"]).reset_index(drop=True)

    if len(work) == 0:
        summary_rows.append({
            "lambda0_upper": upper,
            "retained_rows": 0,
            "retained_fraction_from_input": 0.0,
            "retained_fraction_from_qc": 0.0,
            "obs_slope": np.nan,
            "intercept": np.nan,
            "p_one_sided_negative": np.nan,
            "n_perm": 0,
            "n_bins_used": 0,
            "note": "No rows retained",
        })
        continue

    work = apply_within_group(work, "bh_mass_class", "H_raw", "H_hat")
    work = apply_within_group(work, "bh_mass_class", "S_raw", "S_hat")
    work = compute_phi_bh(work, h_hat_col="H_hat", s_hat_col="S_hat")
    work = define_quantile_window(
        work,
        group_col="bh_mass_class",
        phi_col="phi_bh",
        q_low=cfg["window"]["q_low"],
        q_high=cfg["window"]["q_high"],
    )

    bv = binned_variance(work, x_col="logMbh", y_col="phi_bh", bins=var_bins, min_count=min_bin_count)
    if not bv.empty:
        tmp = bv.copy()
        tmp["lambda0_upper"] = upper
        binned_rows.append(tmp)

    if len(bv) < 2:
        summary_rows.append({
            "lambda0_upper": upper,
            "retained_rows": len(work),
            "retained_fraction_from_input": len(work) / len(df),
            "retained_fraction_from_qc": len(work) / len(base) if len(base) > 0 else np.nan,
            "obs_slope": np.nan,
            "intercept": np.nan,
            "p_one_sided_negative": np.nan,
            "n_perm": 0,
            "n_bins_used": len(bv),
            "note": "Not enough populated bins",
        })
        continue

    fit = fit_linear(bv["x_mid"].values, bv["var_y"].values)
    null = variance_slope_null(
        work,
        group_col=cfg["nulls"]["shuffle_within"],
        x_col="logMbh",
        y_col="phi_bh",
        bins=var_bins,
        n_perm=n_perm,
        min_count=min_bin_count,
        seed=cfg["run"]["seed"],
    )

    summary_rows.append({
        "lambda0_upper": upper,
        "retained_rows": len(work),
        "retained_fraction_from_input": len(work) / len(df),
        "retained_fraction_from_qc": len(work) / len(base) if len(base) > 0 else np.nan,
        "obs_slope": fit["slope"],
        "intercept": fit["intercept"],
        "p_one_sided_negative": null["p_one_sided_negative"],
        "n_perm": len(null["null_slopes"]),
        "n_bins_used": len(bv),
        "note": "",
    })

summary = pd.DataFrame(summary_rows)
binned = pd.concat(binned_rows, ignore_index=True) if binned_rows else pd.DataFrame()

outdir = Path("outputs/tables")
outdir.mkdir(parents=True, exist_ok=True)

summary_out = outdir / cfg["outputs"]["summary_csv"]
binned_out = outdir / cfg["outputs"]["binned_csv"]
summary.to_csv(summary_out, index=False)
binned.to_csv(binned_out, index=False)

# Quick summary figures
figdir = Path("outputs/figures")
figdir.mkdir(parents=True, exist_ok=True)

plt.figure(figsize=(7, 5))
plt.plot(summary["lambda0_upper"], summary["retained_rows"], marker="o")
plt.xlabel("lambda0 upper bound")
plt.ylabel("retained rows")
plt.title("GAMA retention vs lambda0 upper bound")
plt.tight_layout()
plt.savefig(figdir / cfg["outputs"]["figure_retention"], dpi=160)
plt.close()

plt.figure(figsize=(7, 5))
plt.plot(summary["lambda0_upper"], summary["obs_slope"], marker="o")
plt.xlabel("lambda0 upper bound")
plt.ylabel("variance slope")
plt.title("GAMA slope vs lambda0 upper bound")
plt.tight_layout()
plt.savefig(figdir / cfg["outputs"]["figure_slope"], dpi=160)
plt.close()

print(f"[ok] wrote {summary_out}")
print(f"[ok] wrote {binned_out}")
print(summary.to_string(index=False))
