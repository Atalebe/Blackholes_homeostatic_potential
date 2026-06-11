from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

runtime_path = Path(cfg["data"]["runtime_table"])
if runtime_path.suffix.lower() == ".csv":
    df = pd.read_csv(runtime_path)
elif runtime_path.suffix.lower() == ".parquet":
    df = pd.read_parquet(runtime_path)
else:
    raise ValueError(f"Unsupported runtime table format: {runtime_path.suffix}")

c = cfg["columns"]
s = cfg["selection"]

work = pd.DataFrame({
    "gal_id": df[c["gal_id"]].astype(str),
    "logMstar": pd.to_numeric(df[c["logMstar"]], errors="coerce"),
    "SFR": pd.to_numeric(df[c["SFR"]], errors="coerce"),
    "logMbh": pd.to_numeric(df[c["logMbh"]], errors="coerce"),
    "mdot_bh": pd.to_numeric(df[c["mdot_bh"]], errors="coerce"),
    "z": pd.to_numeric(df[c["z"]], errors="coerce"),
    "sigma_star": pd.to_numeric(df[c["sigma_star"]], errors="coerce"),
})

# Optional quality columns
if "sn_col" in c and c["sn_col"] in df.columns:
    work["SN"] = pd.to_numeric(df[c["sn_col"]], errors="coerce")
if "nq_col" in c and c["nq_col"] in df.columns:
    work["NQ"] = pd.to_numeric(df[c["nq_col"]], errors="coerce")
if "dapqual_col" in c and c["dapqual_col"] in df.columns:
    work["DAPQUAL"] = pd.to_numeric(df[c["dapqual_col"]], errors="coerce")
if "drpqual_col" in c and c["drpqual_col"] in df.columns:
    work["DRPQUAL"] = pd.to_numeric(df[c["drpqual_col"]], errors="coerce")

rows = []

mask = pd.Series(True, index=work.index)

def record(stage_name, current_mask):
    rows.append({
        "stage": stage_name,
        "rows_remaining": int(current_mask.sum()),
        "rows_removed_total": int((~current_mask).sum()),
        "fraction_remaining": float(current_mask.mean()),
    })

record("start", mask)

# Sequential cuts
cuts = []

cuts.append(("finite_logMstar", np.isfinite(work["logMstar"])))
cuts.append(("finite_SFR", np.isfinite(work["SFR"])))
cuts.append(("finite_logMbh", np.isfinite(work["logMbh"])))
cuts.append(("finite_mdot_bh", np.isfinite(work["mdot_bh"])))
cuts.append(("finite_z", np.isfinite(work["z"])))
cuts.append(("finite_sigma_star", np.isfinite(work["sigma_star"])))

cuts.append((f"z_le_{s['z_max']}", work["z"] <= s["z_max"]))
cuts.append((f"logMstar_ge_{s['host_mass_log10_min']}", work["logMstar"] >= s["host_mass_log10_min"]))
cuts.append((f"logMstar_le_{s['host_mass_log10_max']}", work["logMstar"] <= s["host_mass_log10_max"]))

if s.get("require_positive_sfr", False):
    cuts.append(("SFR_gt_0", work["SFR"] > 0))
if s.get("require_positive_mdot_bh", False):
    cuts.append(("mdot_bh_gt_0", work["mdot_bh"] > 0))
if s.get("require_positive_sigma", False):
    cuts.append(("sigma_star_gt_0", work["sigma_star"] > 0))
if s.get("require_positive_logMstar", False):
    cuts.append(("logMstar_gt_0", work["logMstar"] > 0))
if s.get("require_finite_logMbh", False):
    cuts.append(("logMbh_finite_repeat", np.isfinite(work["logMbh"])) )

if "SN" in work.columns and "sn_min" in s:
    cuts.append((f"SN_ge_{s['sn_min']}", work["SN"] >= s["sn_min"]))
if "NQ" in work.columns and "nq_min" in s:
    cuts.append((f"NQ_ge_{s['nq_min']}", work["NQ"] >= s["nq_min"]))
if "DAPQUAL" in work.columns and s.get("require_zero_dapqual", False):
    cuts.append(("DAPQUAL_eq_0", work["DAPQUAL"] == 0))
if "DRPQUAL" in work.columns and s.get("allow_nonzero_drpqual", True) is False:
    cuts.append(("DRPQUAL_eq_0", work["DRPQUAL"] == 0))

# Derived lambda0 band
log10_sbhg = np.log10(work["mdot_bh"]) - work["logMbh"]
log10_sfr_star = np.log10(work["SFR"]) - work["logMstar"]
lambda0 = log10_sbhg - log10_sfr_star

cuts.append(("lambda0_finite", np.isfinite(lambda0)))
cuts.append((f"lambda0_ge_{s['lambda0_band_low']}", lambda0 >= s["lambda0_band_low"]))
cuts.append((f"lambda0_le_{s['lambda0_band_high']}", lambda0 <= s["lambda0_band_high"]))

for name, cut in cuts:
    mask = mask & cut.fillna(False)
    record(name, mask)

audit = pd.DataFrame(rows)

# Per-cut marginal effect from start
marginal_rows = []
base = pd.Series(True, index=work.index)
for name, cut in cuts:
    keep = cut.fillna(False)
    marginal_rows.append({
        "cut": name,
        "rows_kept_if_only_this_cut": int((base & keep).sum()),
        "rows_removed_if_only_this_cut": int((base & ~keep).sum()),
        "fraction_kept_if_only_this_cut": float((base & keep).mean()),
    })
marginal = pd.DataFrame(marginal_rows)

outdir = Path("outputs/tables")
outdir.mkdir(parents=True, exist_ok=True)

audit_out = outdir / cfg["outputs"]["audit_csv"]
marginal_out = outdir / cfg["outputs"]["marginal_csv"]

audit.to_csv(audit_out, index=False)
marginal.to_csv(marginal_out, index=False)

print(f"[ok] wrote {audit_out}")
print(f"[ok] wrote {marginal_out}")
print(audit.to_string(index=False))
print(marginal.to_string(index=False))
