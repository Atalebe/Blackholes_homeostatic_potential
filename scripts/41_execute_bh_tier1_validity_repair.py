#!/usr/bin/env python3
"""Protocol v6 validity repair for the reduced Tier 1 black-hole branch.

This runner does not fit R or M. It audits the layer on which those coordinates
would be built and refuses to invent dependence identifiers or independent axes.
"""
from __future__ import annotations

import argparse
import ast
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

VERSION = "1.2.0"


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet": return pd.read_parquet(path)
    if path.suffix.lower() == ".csv": return pd.read_csv(path)
    if path.suffix.lower() == ".tsv": return pd.read_csv(path, sep="\t")
    raise ValueError(f"Unsupported table format: {path}")


def norm_source(text: str) -> str:
    return re.sub(r"\s+", "", text)


def formula_concordance(root: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    data = cfg["data"]
    time_src = (root / data["time_source"]).read_text(encoding="utf-8")
    gama_src = (root / data["gama_source"]).read_text(encoding="utf-8")
    tex = (root / data["manuscript_tex"]).read_text(encoding="utf-8")
    nt, ng, nx = map(norm_source, (time_src, gama_src, tex))

    time_code = 'df["S_t_raw"]=-np.abs(df["lambda_bh_t"]-df["lambda_bh_med_track"])' in nt
    time_tex = bool(re.search(r"S_t&?\\equiv-\\left\\?\|.*lambda.*tilde", nx, re.I)) or ("S_t" in tex and "tilde\\lambda" in tex and "left|" in tex)
    d4000_code = 'out["S_raw"]=-np.abs(out["_S_LOG"]-out["_S_MED_CLASS"])' in ng
    d4000_tex = "S_{\\rmD4000,offset}" in nx and "D4000N" in tex
    sigma_code_mass_resid = 'out["S_raw"]=-np.abs(out["logMbh"]-out["logMbh_sigma"])' in ng
    sigma_tex_class_offset = "S_{\\sigma_\\star,offset}" in nx and "widetilde{\\log_{10}(\\sigma" in nx

    return [
        {"check_id":"tng_stability", "code_formula":"-abs(lambda_bh_t - lambda_bh_med_track)", "manuscript_formula":"-abs(lambda_bh(t) - track median lambda_bh)", "verdict":"pass" if time_code and time_tex else "unresolved", "binding_action":"none" if time_code and time_tex else "block equation claim"},
        {"check_id":"gama_d4000_stability", "code_formula":"-abs(log10(D4000N) - class median)", "manuscript_formula":"-abs(log10(D4000N) - class median)", "verdict":"pass" if d4000_code and d4000_tex else "unresolved", "binding_action":"retain bounded only"},
        {"check_id":"gama_sigma_stability", "code_formula":"-abs(logMbh - predicted logMbh(sigma_star))", "manuscript_formula":"-abs(log10(sigma_star) - class median log10(sigma_star))", "verdict":"fail_nonconcordant" if sigma_code_mass_resid and sigma_tex_class_offset else "unresolved", "binding_action":"quarantine branch and remove positive manuscript claim"},
    ]


def load_ripeness_function(path: Path):
    spec = importlib.util.spec_from_file_location("bh_core_ripeness_probe", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.compute_residence_fraction


def scalar_from_result(result: Any) -> float:
    if isinstance(result, pd.DataFrame):
        for col in ["ripeness_bh", "residence_fraction", "ripeness"]:
            if col in result.columns: return float(result.iloc[0][col])
    if isinstance(result, pd.Series): return float(result.iloc[0])
    return float(result)


def residence_semantics(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    fn = load_ripeness_function(root / cfg["data"]["ripeness_source"])
    probe = pd.DataFrame({"bh_id":[1,1,1], "t":[0.0,1.0,10.0], "in_window_t":[True,False,True]})
    value = scalar_from_result(fn(probe, id_col="bh_id", time_col="t", in_window_col="in_window_t"))
    row_fraction = 2.0 / 3.0
    left_interval_fraction = 1.0 / 10.0
    right_interval_fraction = 9.0 / 10.0
    if abs(value-row_fraction) < 1e-12: mode = "row_fraction"
    elif abs(value-left_interval_fraction) < 1e-12: mode = "left_interval_time_weighted"
    elif abs(value-right_interval_fraction) < 1e-12: mode = "right_interval_time_weighted"
    else: mode = "other_or_weighted"
    return {"probe_times":[0.0,1.0,10.0], "probe_membership":[1,0,1], "observed":value, "row_fraction":row_fraction, "left_interval_time_weighted":left_interval_fraction, "right_interval_time_weighted":right_interval_fraction, "implementation_mode":mode, "manuscript_integral_concordant": mode != "row_fraction"}


def time_weighted_fraction(g: pd.DataFrame, time_col: str, member_col: str, endpoint: str = "left") -> float:
    x = g[[time_col, member_col]].dropna().sort_values(time_col)
    if len(x) < 2: return np.nan
    t = x[time_col].to_numpy(float); y = x[member_col].to_numpy(bool)
    dtv = np.diff(t); good = np.isfinite(dtv) & (dtv > 0)
    if not good.any(): return np.nan
    if endpoint == "left": occupancy = y[:-1]
    elif endpoint == "right": occupancy = y[1:]
    else: raise ValueError(f"Unknown endpoint convention: {endpoint}")
    return float(np.sum(dtv[good] * occupancy[good]) / np.sum(dtv[good]))


def cadence_audit(tracks: pd.DataFrame, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rcfg=cfg["residence_audit"]; idc=cfg["axis_audit"]["id_col"]; tc=rcfg["time_col"]
    rows=[]
    for bh_id,g in tracks.groupby(idc, sort=False):
        ts=np.sort(pd.to_numeric(g[tc],errors="coerce").dropna().unique()); d=np.diff(ts)
        d=d[np.isfinite(d)&(d>0)]
        rows.append({"bh_id":bh_id,"n_time":len(ts),"dt_median":float(np.median(d)) if len(d) else np.nan,"dt_cv":float(np.std(d)/np.mean(d)) if len(d) and np.mean(d)>0 else np.nan,"irregular":bool(len(d)>1 and np.std(d)/np.mean(d)>0.05)})
    frame=pd.DataFrame(rows)
    return rows, {"n_tracks":len(frame),"irregular_tracks":int(frame["irregular"].sum()),"irregular_fraction":float(frame["irregular"].mean()) if len(frame) else np.nan,"median_dt_cv":float(frame["dt_cv"].median()) if len(frame) else np.nan}


def mutual_information_quantile(x: pd.Series, y: pd.Series, bins: int) -> float:
    z=pd.DataFrame({"x":x,"y":y}).dropna()
    if len(z)<20:return np.nan
    try:
        xb=pd.qcut(z.x, q=min(bins,z.x.nunique()), labels=False, duplicates="drop")
        yb=pd.qcut(z.y, q=min(bins,z.y.nunique()), labels=False, duplicates="drop")
    except ValueError:return np.nan
    tab=pd.crosstab(xb,yb,normalize=True); px=tab.sum(axis=1); py=tab.sum(axis=0); mi=0.0
    for i in tab.index:
        for j in tab.columns:
            p=tab.loc[i,j]
            if p>0:mi+=p*math.log(p/(px.loc[i]*py.loc[j]))
    return float(mi)


def axis_dependence(tracks: pd.DataFrame, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    ac=cfg["axis_audit"]; cols=[ac["h_raw_col"],ac["s_raw_col"],ac["h_hat_col"],ac["s_hat_col"],ac["track_median_col"],ac["group_col"]]
    d=tracks[cols].dropna().copy()
    if len(d)>ac["max_rows"]: d=d.sample(ac["max_rows"],random_state=cfg["seed"])
    rows=[]
    for group,g in [("ALL",d),*list(d.groupby(ac["group_col"],observed=False))]:
        corr=np.corrcoef(g[ac["h_hat_col"]],g[ac["s_hat_col"]]) if len(g)>2 else np.full((2,2),np.nan)
        eig=np.linalg.eigvalsh(corr) if np.isfinite(corr).all() else [np.nan,np.nan]
        deff=float(np.sum(eig)**2/np.sum(np.square(eig))) if np.isfinite(eig).all() and np.sum(np.square(eig))>0 else np.nan
        recon=-np.abs(g[ac["h_raw_col"]]-g[ac["track_median_col"]]); err=np.max(np.abs(recon-g[ac["s_raw_col"]])) if len(g) else np.nan
        rows.append({"group":str(group),"n_rows":len(g),"pearson":g[ac["h_hat_col"]].corr(g[ac["s_hat_col"]],method="pearson"),"spearman":g[ac["h_hat_col"]].corr(g[ac["s_hat_col"]],method="spearman"),"mutual_information_nats":mutual_information_quantile(g[ac["h_hat_col"]],g[ac["s_hat_col"]],ac["mi_bins"]),"effective_dim_correlation":deff,"max_s_reconstruction_error":float(err),"same_measurement_channel":bool(err<=ac["reconstruction_tolerance"]),"axis_independence_verdict":"blocked_same_channel" if err<=ac["reconstruction_tolerance"] else "unresolved"})
    return rows


def dispersion(values: pd.Series, metric: str) -> float:
    x=pd.to_numeric(values,errors="coerce").dropna().to_numpy(float)
    if len(x)<2:return np.nan
    if metric=="variance":return float(np.var(x,ddof=1))
    med=np.median(x); mad=np.median(np.abs(x-med))
    if metric=="mad2":return float(mad*mad)
    if metric=="iqr2":return float((np.quantile(x,.75)-np.quantile(x,.25))**2)
    raise ValueError(metric)


def slope_for(bh: pd.DataFrame, ycol: str, metric: str, rc: dict[str, Any]) -> tuple[float,int]:
    edges=np.arange(rc["bin_start"],rc["bin_stop"]+rc["bin_step"]*.5,rc["bin_step"])
    cats=pd.cut(bh[rc["mass_col"]],edges,right=False,include_lowest=True)
    pts=[]
    for interval,g in bh.groupby(cats,observed=False):
        if len(g)>=rc["min_bin_count"]:pts.append(((interval.left+interval.right)/2,dispersion(g[ycol],metric)))
    pts=[p for p in pts if np.isfinite(p[1])]
    return (float(np.polyfit([p[0] for p in pts],[p[1] for p in pts],1)[0]),len(pts)) if len(pts)>=2 else (np.nan,len(pts))


def residence_sensitivity(tracks: pd.DataFrame, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]],list[dict[str,Any]]]:
    ac=cfg["axis_audit"]; rc=cfg["residence_audit"]; rng=np.random.default_rng(cfg["seed"])
    summary=[]; bh_rows=[]
    meta=tracks.groupby(ac["id_col"],as_index=False,observed=False).agg(**{rc["category_col"]:(rc["category_col"],"last"),rc["mass_col"]:(rc["mass_col"],"last")})
    for coord in rc["coordinate_variants"]:
        for width in rc["window_widths"]:
            qlo=(1-width)/2; qhi=1-qlo; member=f"_member_{coord}_{width:.2f}"
            thresholds=tracks.groupby(ac["group_col"],observed=False)[coord].quantile([qlo,qhi]).unstack()
            # Mapping a categorical group can preserve categorical dtype even when the
            # mapped thresholds are numeric. Force all operands to float before comparison.
            low=pd.to_numeric(tracks[ac["group_col"]].map(thresholds[qlo]),errors="coerce").astype(float)
            high=pd.to_numeric(tracks[ac["group_col"]].map(thresholds[qhi]),errors="coerce").astype(float)
            coordinate=pd.to_numeric(tracks[coord],errors="coerce").astype(float)
            work=tracks[[ac["id_col"],rc["time_col"]]].copy(); work[member]=(coordinate>=low)&(coordinate<=high)
            row=work.groupby(ac["id_col"],observed=False)[member].mean().rename("row_fraction")
            left=work.groupby(ac["id_col"],observed=False).apply(lambda g:time_weighted_fraction(g,rc["time_col"],member,"left"),include_groups=False).rename("left_fraction")
            right=work.groupby(ac["id_col"],observed=False).apply(lambda g:time_weighted_fraction(g,rc["time_col"],member,"right"),include_groups=False).rename("right_fraction")
            bh=meta.merge(row,left_on=ac["id_col"],right_index=True).merge(left,left_on=ac["id_col"],right_index=True).merge(right,left_on=ac["id_col"],right_index=True)
            bh["coordinate"]=coord; bh["window_width"]=width
            bh["abs_left_row_difference"]=(bh.left_fraction-bh.row_fraction).abs()
            bh["abs_right_row_difference"]=(bh.right_fraction-bh.row_fraction).abs()
            bh["abs_left_right_difference"]=(bh.left_fraction-bh.right_fraction).abs()
            bh_rows.extend(bh.to_dict("records"))
            modes={"row":"row_fraction","left_endpoint":"left_fraction","right_endpoint":"right_fraction"}
            for mode in rc.get("residence_modes",["row","left_endpoint","right_endpoint"]):
                ycol=modes[mode]
                for metric in rc["metrics"]:
                    obs,nb=slope_for(bh,ycol,metric,rc); null=[]
                    for _ in range(rc["n_perm_screen"]):
                        p=bh.copy(); p[ycol]=p.groupby(rc["category_col"],observed=False)[ycol].transform(lambda s:rng.permutation(s.to_numpy()))
                        val,_=slope_for(p,ycol,metric,rc); null.append(val)
                    null=np.asarray(null,float); valid=null[np.isfinite(null)]
                    if len(valid) and np.isfinite(obs) and obs < 0:
                        exceed=int(np.sum(valid<=obs)); pv=(exceed+1)/(len(valid)+1)
                    elif len(valid) and np.isfinite(obs):
                        # The declared alternative is a negative slope. A non-negative
                        # observed slope cannot reject that one-sided null.
                        exceed=len(valid); pv=1.0
                    else:
                        exceed=0; pv=np.nan
                    summary.append({"coordinate":coord,"window_width":width,"residence_mode":mode,"metric":metric,"obs_slope":obs,"n_bins":nb,"n_perm":len(valid),"exceedances_negative":exceed,"p_one_sided_negative":pv,"confirmatory_status":"posthoc_sensitivity_only","time_order_information":"none_occupancy_is_order_invariant"})
    return summary,bh_rows


def sigma_quarantine(root: Path,cfg:dict[str,Any])->tuple[list[dict[str,Any]],dict[str,Any]]:
    sc=cfg["sigma_quarantine"]; ns=pd.read_csv(root/cfg["data"]["sigma_normalization_summary"]); vs=pd.read_csv(root/cfg["data"]["sigma_variance_summary"])
    rows=[]
    for _,r in ns.iterrows():rows.append({"mass_class":r["bh_mass_class"],"n":int(r["n"]),"S_mad":float(r["S_mad"]),"collapsed":bool(float(r["S_mad"])<sc["mad_floor"])})
    p=float(vs.iloc[0]["p_one_sided_negative"]); collapsed=sum(r["collapsed"] for r in rows)
    verdict={"collapsed_mass_classes":collapsed,"total_mass_classes":len(rows),"p_one_sided_negative":p,"null_rejected":p<sc["alpha"],"verdict":"quarantined_numeric_and_target_construction" if collapsed else "unresolved","positive_manuscript_claim_allowed":False}
    return rows,verdict


def schema_columns(path:Path,max_csv:int)->list[str]:
    try:
        if path.suffix.lower()==".parquet":
            import pyarrow.parquet as pq
            return list(pq.ParquetFile(path).schema.names)
        if path.suffix.lower() in {".csv",".tsv"} and path.stat().st_size<=max_csv:
            with path.open("r",encoding="utf-8",errors="replace") as f:return next(csv.reader(f,delimiter="\t" if path.suffix.lower()==".tsv" else ","))
    except Exception:return []
    return []


def dependence_bridge(root:Path,cfg:dict[str,Any],expected_bh_ids:set[Any]|None=None)->tuple[list[dict[str,Any]],pd.DataFrame,dict[str,Any]]:
    dc=cfg["dependence_bridge"]; inventory=[]; bridge_parts=[]
    aliases={}
    alias_config=dc.get("id_aliases") or {name:[name] for name in dc.get("id_candidates",[])}
    for canonical,names in alias_config.items():
        for name in names: aliases[re.sub(r"[^a-z0-9]","",name.lower())]=canonical
    for rel in dc["scan_roots"]:
        base=root/rel
        if not base.exists():continue
        paths=[base] if base.is_file() else list(base.rglob("*.csv"))+list(base.rglob("*.tsv"))+list(base.rglob("*.parquet"))
        for p in paths:
            cols=schema_columns(p,dc["max_csv_bytes"])
            canonical_to_raw={}
            for col in cols:
                key=re.sub(r"[^a-z0-9]","",col.lower())
                if key in aliases and aliases[key] not in canonical_to_raw: canonical_to_raw[aliases[key]]=col
            raw_id_like=[c for c in cols if re.search(r"(?i)(id|subhalo|group|fof|tree|host|grnr|simulation|run)",c)]
            if not canonical_to_raw and not raw_id_like:continue
            ids=sorted(canonical_to_raw)
            has_bh="bh_id" in canonical_to_raw; dep=[k for k in ids if k!="bh_id"]
            inventory.append({"artifact":p.relative_to(root).as_posix(),"id_columns":"|".join(ids),"raw_id_like_columns":"|".join(raw_id_like),"contains_bh_id":has_bh,"contains_dependency_id":bool(dep)})
            if has_bh and dep:
                use=[canonical_to_raw["bh_id"],*[canonical_to_raw[k] for k in dep]]
                try:
                    d=pd.read_parquet(p,columns=use) if p.suffix.lower()==".parquet" else pd.read_csv(p,usecols=use,sep="\t" if p.suffix.lower()==".tsv" else ",")
                    rename={canonical_to_raw["bh_id"]:"bh_id",**{canonical_to_raw[k]:k for k in dep}}
                    d=d.rename(columns=rename).drop_duplicates(); d["bridge_source"]=p.relative_to(root).as_posix(); bridge_parts.append(d)
                except Exception:pass
    bridge=pd.concat(bridge_parts,ignore_index=True,sort=False) if bridge_parts else pd.DataFrame(columns=["bh_id","bridge_source"])
    if not bridge.empty:bridge=bridge.sort_values(["bh_id","bridge_source"]).drop_duplicates()
    depcols=[c for c in bridge.columns if c not in {"bh_id","bridge_source"}]
    conflicts=0
    for col in depcols:
        conflicts+=int((bridge.dropna(subset=[col]).groupby("bh_id")[col].nunique()>1).sum())
    bridged_ids=set(bridge["bh_id"].dropna()) if len(bridge) else set()
    coverage=float(len(bridged_ids&expected_bh_ids)/len(expected_bh_ids)) if expected_bh_ids else None
    if not len(bridge): status="no_explicit_bh_dependency_bridge"
    elif conflicts: status="bridge_conflict_quarantine"
    else: status="bridge_candidate_requires_uniqueness_review"
    verdict={"candidate_artifacts":len(inventory),"bridge_rows":len(bridge),"dependency_columns":depcols,"conflicting_bh_dependency_assignments":conflicts,"expected_bh_ids":len(expected_bh_ids) if expected_bh_ids else None,"covered_bh_ids":len(bridged_ids&expected_bh_ids) if expected_bh_ids else None,"coverage_fraction":coverage,"verdict":status,"forbidden_assumption":"bh_id equals subhalo_id"}
    return inventory,bridge,verdict


def latex_escape(x:Any)->str:
    s=str(x)
    for a,b in [("\\",r"\textbackslash{}"),("&",r"\&"),("%",r"\%"),("_",r"\_"),("#",r"\#")]:s=s.replace(a,b)
    return s


def write_logbook(path:Path,run_id:str,formula:list[dict[str,Any]],res:dict[str,Any],axis:list[dict[str,Any]],cad:dict[str,Any],sig:dict[str,Any],bridge:dict[str,Any],manifest_hash:str)->None:
    rows=[r"\documentclass[11pt]{article}",r"\usepackage[margin=1in]{geometry}",r"\usepackage{booktabs,longtable}",r"\begin{document}",r"\section*{Logbook Entry 003: Tier 1 Validity Freeze Candidate}",f"\\textbf{{Run ID:}} {latex_escape(run_id)}\\\\",f"\\textbf{{Manifest SHA-256:}} \\texttt{{{manifest_hash}}}",r"\subsection*{Purpose}","This entry compares row, left-endpoint, and right-endpoint residence conventions before recoverability or memory generators are activated.",r"\subsection*{Formula concordance}",r"\begin{tabular}{lll}\toprule Check & Verdict & Action \\\midrule"]
    for r in formula:rows.append(f"{latex_escape(r['check_id'])} & {latex_escape(r['verdict'])} & {latex_escape(r['binding_action'])} " + r"\\")
    rows += [r"\bottomrule\end{tabular}",r"\subsection*{Binding findings}",f"Residence implementation mode: {latex_escape(res['implementation_mode'])}.\\\\",f"Irregular-cadence tracks: {cad['irregular_tracks']} of {cad['n_tracks']}.\\\\",f"Tier 1 axis verdict: {latex_escape(axis[0]['axis_independence_verdict'])}.\\\\",f"GAMA sigma verdict: {latex_escape(sig['verdict'])}.\\\\",f"Dependence bridge verdict: {latex_escape(bridge['verdict'])}.",r"\subsection*{Adjudication}","The TNG ripeness association remains bounded. The GAMA sigma branch is quarantined. Occupancy is order-invariant and cannot itself activate memory. R and M fitting remain blocked until the validity remediations and dependence bridge are frozen.",r"\end{document}",""]
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text("\n".join(rows),encoding="utf-8")


def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("--config",default="configs/protocol/bh_tier1_validity_repair_v1.yaml");ap.add_argument("--repo-root",default=".");a=ap.parse_args()
    root=Path(a.repo_root).resolve();cp=(root/a.config).resolve();cfg=yaml.safe_load(cp.read_text());out=root/cfg["outputs"]["root"];out.mkdir(parents=True,exist_ok=True)
    tracks=read_table(root/cfg["data"]["track_phi_parquet"]); formulas=formula_concordance(root,cfg); semantics=residence_semantics(root,cfg); cadence_rows,cadence_summary=cadence_audit(tracks,cfg); axes=axis_dependence(tracks,cfg); sensitivity,bh_sensitivity=residence_sensitivity(tracks,cfg); sigma_rows,sigma_verdict=sigma_quarantine(root,cfg); bridge_inv,bridge,bridge_verdict=dependence_bridge(root,cfg,set(tracks[cfg["axis_audit"]["id_col"]].dropna().unique()))
    write_csv(out/"bh_formula_code_concordance_v1_2.csv",formulas,["check_id","code_formula","manuscript_formula","verdict","binding_action"]);write_json(out/"bh_residence_semantics.json",semantics);write_csv(out/"bh_cadence_audit.csv",cadence_rows,["bh_id","n_time","dt_median","dt_cv","irregular"]);write_json(out/"bh_cadence_summary.json",cadence_summary);write_csv(out/"bh_axis_dependence.csv",axes,["group","n_rows","pearson","spearman","mutual_information_nats","effective_dim_correlation","max_s_reconstruction_error","same_measurement_channel","axis_independence_verdict"]);write_csv(out/"bh_residence_sensitivity_summary.csv",sensitivity,["coordinate","window_width","residence_mode","metric","obs_slope","n_bins","n_perm","exceedances_negative","p_one_sided_negative","confirmatory_status","time_order_information"]);write_csv(out/"bh_residence_sensitivity_by_bh.csv",bh_sensitivity,["bh_id",cfg["residence_audit"]["category_col"],cfg["residence_audit"]["mass_col"],"row_fraction","left_fraction","right_fraction","coordinate","window_width","abs_left_row_difference","abs_right_row_difference","abs_left_right_difference"]);write_csv(out/"bh_sigma_quarantine_by_class.csv",sigma_rows,["mass_class","n","S_mad","collapsed"]);write_json(out/"bh_sigma_quarantine_verdict.json",sigma_verdict);write_csv(out/"bh_dependence_bridge_inventory.csv",bridge_inv,["artifact","id_columns","raw_id_like_columns","contains_bh_id","contains_dependency_id"]);bridge.to_csv(out/"bh_tng_dependence_bridge_candidate.csv",index=False);write_json(out/"bh_dependence_bridge_verdict.json",bridge_verdict)
    memory_ready=all(r["verdict"]=="pass" for r in formulas[:2]) and formulas[2]["verdict"]=="fail_nonconcordant" and semantics["manuscript_integral_concordant"] and bridge_verdict["verdict"]!="no_explicit_bh_dependency_bridge"
    summary={"run_id":cfg["run_id"],"generated_utc":now_utc(),"formula_verdicts":{r["check_id"]:r["verdict"] for r in formulas},"residence_mode":semantics["implementation_mode"],"cadence":cadence_summary,"axis_verdict":axes[0]["axis_independence_verdict"],"sigma_verdict":sigma_verdict["verdict"],"dependence_bridge_verdict":bridge_verdict["verdict"],"memory_stage_authorized":False,"memory_preconditions_satisfied":memory_ready,"reason":"Memory remains a separate frozen generator stage; occupancy is order-invariant and cannot establish M."};write_json(out/"bh_tier1_validity_summary.json",summary)
    inputs=[cp,root/cfg["data"]["track_phi_parquet"],root/cfg["data"]["bh_level_csv"],root/cfg["data"]["sigma_normalization_summary"],root/cfg["data"]["sigma_variance_summary"],root/cfg["data"]["manuscript_tex"],root/cfg["data"]["time_source"],root/cfg["data"]["gama_source"],root/cfg["data"]["ripeness_source"]];manifest={"run_id":cfg["run_id"],"script_version":VERSION,"generated_utc":now_utc(),"git_commit":subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],capture_output=True,text=True).stdout.strip() or None,"inputs":[{"path":p.relative_to(root).as_posix(),"sha256":sha256(p),"bytes":p.stat().st_size} for p in inputs],"policy":{"scientific_inputs_modified":False,"sigma_positive_claim_allowed":False,"memory_activated":False,"recoverability_activated":False,"sequential_generator_search_allowed":False}};mp=out/"bh_tier1_validity_manifest.json";write_json(mp,manifest);mh=sha256(mp);write_logbook(root/cfg["outputs"]["paper_root"]/"bh_tier1_validity_freeze_entry_003.tex",cfg["run_id"],formulas,semantics,axes,cadence_summary,sigma_verdict,bridge_verdict,mh);summary["manifest_sha256"]=mh;write_json(out/"bh_tier1_validity_summary.json",summary);print(json.dumps(summary,indent=2,sort_keys=True));return 0


if __name__=="__main__":raise SystemExit(main())
