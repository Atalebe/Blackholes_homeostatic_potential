#!/usr/bin/env python3
"""Generic Phase B screen supporting a declared continuous baseline."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.core.predictive_memory import bootstrap_fractional_improvement, fit_ridge, predict_ridge, rmse


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--config", required=True); p.add_argument("--repo-root", default=".")
    a = p.parse_args(); root = Path(a.repo_root).resolve(); cfg = yaml.safe_load((root/a.config).read_text())
    source = root/cfg["data"]["candidate_parquet"]; phase_a = json.loads((root/cfg["data"]["phase_a_verdict"]).read_text())
    if not phase_a.get("phase_b_predictive_comparison_authorized", False): raise RuntimeError("Phase A did not authorize comparison")
    df = pd.read_parquet(source); c = cfg["columns"]; target = c["target"]
    base = list(c.get("baseline_continuous", [c["current"], c["delta_time"]])); cats = [c["category"], c["mass_class"]]
    taus = cfg["selection"]["tau_track_fractions"]; memories = [f"memory_tau_{x:g}" for x in taus]
    train=df[df[c["split"]]=="train"]; val=df[df[c["split"]]=="validation"]; test=df[df[c["split"]]=="test"].copy(); dev=df[df[c["split"]].isin(["train","validation"])]
    alpha=float(cfg["model"]["ridge_alpha"]); bm=fit_ridge(train,target,base,cats,alpha); br=rmse(val[target],predict_ridge(val,bm)); rows=[]
    for tau,memory in zip(taus,memories):
        model=fit_ridge(train,target,[*base,memory],cats,alpha); score=rmse(val[target],predict_ridge(val,model))
        rows.append({"tau_track_fraction":float(tau),"memory_column":memory,"baseline_validation_rmse":br,"augmented_validation_rmse":score,"fractional_validation_improvement":(br-score)/br})
    selection=pd.DataFrame(rows).sort_values(["augmented_validation_rmse","tau_track_fraction"],kind="stable").reset_index(drop=True); chosen=selection.iloc[0]; memory=str(chosen.memory_column)
    bm=fit_ridge(dev,target,base,cats,alpha); am=fit_ridge(dev,target,[*base,memory],cats,alpha); y=test[target].to_numpy(float); bp=predict_ridge(test,bm); ap=predict_ridge(test,am)
    b=rmse(y,bp); q=rmse(y,ap); test["bse"]=(y-bp)**2; test["ase"]=(y-ap)**2
    per=test.groupby(c["id"],observed=True).agg(n_test=(target,"size"),baseline_sse=("bse","sum"),augmented_sse=("ase","sum")).reset_index(); per["baseline_rmse"]=np.sqrt(per.baseline_sse/per.n_test); per["augmented_rmse"]=np.sqrt(per.augmented_sse/per.n_test); per["fractional_improvement"]=(per.baseline_rmse-per.augmented_rmse)/per.baseline_rmse
    boot=bootstrap_fractional_improvement(per,int(cfg["bootstrap"]["n_resamples"]),int(cfg["seed"])); lo,hi=np.quantile(boot,[.025,.975]); gain=(b-q)/b
    out=root/cfg["outputs"]["root"]; out.mkdir(parents=True,exist_ok=True); label=cfg["outputs"]["label"]; selection.to_csv(out/f"{label}_tau_selection.csv",index=False); per.to_csv(out/f"{label}_test_by_track.csv",index=False)
    effect_gate=bool(gain >= 0.01 and lo > 0)
    verdict={"schema_version":1,"run_id":cfg["run_id"],"generated_utc":datetime.now(timezone.utc).isoformat(),"status":"posthoc_sensitivity_only","candidate_sha256":sha256(source),"baseline_continuous":base,"selected_tau_track_fraction":float(chosen.tau_track_fraction),"baseline_test_rmse":b,"augmented_test_rmse":q,"fractional_test_improvement":gain,"bootstrap_ci_fractional_improvement":[float(lo),float(hi)],"median_track_fractional_improvement":float(per.fractional_improvement.median()),"effect_size_gate_pass":effect_gate,"phase_c_selection_within_null_authorized":effect_gate,"primary_confirmation_unchanged":True,"hrsm_M_status":"candidate_not_admitted"}
    (out/f"{label}_phase_b_verdict.json").write_text(json.dumps(verdict,indent=2)+"\n"); print(json.dumps(verdict,indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
