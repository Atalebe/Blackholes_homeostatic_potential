#!/usr/bin/env python3
"""Freeze the time-order and window-membership preconditions for BH Tier 1."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


def read_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def function_sorts_time(source_path: Path, function_name: str) -> dict:
    text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            body = ast.get_source_segment(text, node) or ""
            tokens = ("sort_values", "argsort", "np.sort", "sorted(")
            hits = [token for token in tokens if token in body]
            return {"function_found": True, "sort_detected": bool(hits), "sort_tokens": hits}
    return {"function_found": False, "sort_detected": False, "sort_tokens": []}


def as_membership(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.astype("boolean")
    mapped = series.astype(str).str.strip().str.casefold().map(
        {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}
    )
    return mapped.astype("boolean")


def right_residence(t: np.ndarray, member: np.ndarray) -> float:
    if len(t) < 2:
        return np.nan
    dt = np.diff(t)
    denominator = float(dt.sum())
    if not np.isfinite(denominator) or denominator <= 0:
        return np.nan
    return float(np.sum(dt * member[1:]) / denominator)


def audit_tracks(df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    c = cfg["columns"]
    required = list(c.values())
    missing = [name for name in required if name not in df.columns]
    if missing:
        raise KeyError(f"Missing required columns: {missing}")

    id_col, time_col = c["id"], c["time"]
    phi_col, low_col, high_col, member_col = c["phi"], c["low"], c["high"], c["membership"]
    work = df[required].copy()
    for name in (time_col, phi_col, low_col, high_col):
        work[name] = pd.to_numeric(work[name], errors="coerce")
    work["_member"] = as_membership(work[member_col])

    rows = []
    for bh_id, group in work.groupby(id_col, sort=False, observed=True):
        t = group[time_col].to_numpy(float)
        phi = group[phi_col].to_numpy(float)
        low = group[low_col].to_numpy(float)
        high = group[high_col].to_numpy(float)
        member = group["_member"].fillna(False).to_numpy(bool)
        finite_t = np.isfinite(t)
        dt_file = np.diff(t) if finite_t.all() else np.array([np.nan])
        order = np.argsort(t, kind="stable") if finite_t.all() else np.arange(len(t))
        t_sorted, member_sorted = t[order], member[order]
        dt_sorted = np.diff(t_sorted) if finite_t.all() else np.array([np.nan])
        numeric_finite = np.isfinite(phi) & np.isfinite(low) & np.isfinite(high)
        valid_bounds = numeric_finite & (low < high)
        expected = valid_bounds & (phi >= low) & (phi <= high)
        comparable = numeric_finite & group["_member"].notna().to_numpy()
        mismatch = comparable & (member != expected)
        positive_dt = dt_sorted[np.isfinite(dt_sorted) & (dt_sorted > 0)]
        mean_dt = float(positive_dt.mean()) if len(positive_dt) else np.nan
        cv = float(positive_dt.std(ddof=0) / mean_dt) if mean_dt > 0 else np.nan
        rows.append({
            "bh_id": bh_id,
            "n_rows": len(group),
            "nonfinite_time": int((~finite_t).sum()),
            "file_order_negative_dt": int(np.sum(dt_file < 0)),
            "file_order_zero_dt": int(np.sum(dt_file == 0)),
            "sorted_duplicate_dt": int(np.sum(dt_sorted == 0)),
            "nonfinite_phi_or_bounds": int((~numeric_finite).sum()),
            "invalid_window_bounds": int((numeric_finite & (low >= high)).sum()),
            "unparseable_membership": int(group["_member"].isna().sum()),
            "membership_mismatches": int(mismatch.sum()),
            "t_min": float(np.nanmin(t)) if finite_t.any() else np.nan,
            "t_max": float(np.nanmax(t)) if finite_t.any() else np.nan,
            "t_span": float(np.nanmax(t) - np.nanmin(t)) if finite_t.any() else np.nan,
            "median_dt": float(np.median(positive_dt)) if len(positive_dt) else np.nan,
            "within_track_dt_cv": cv,
            "right_residence_file_order": right_residence(t, member) if finite_t.all() else np.nan,
            "right_residence_sorted": right_residence(t_sorted, member_sorted) if finite_t.all() else np.nan,
        })

    audit = pd.DataFrame(rows)
    median_span = float(audit["t_span"].median())
    threshold = median_span * float(cfg["exposure"]["short_span_fraction_of_median"])
    audit["short_span_exposure"] = audit["t_span"] < threshold
    audit["sparse_track_exposure"] = audit["n_rows"] < int(cfg["exposure"]["min_rows_warning"])
    audit["residence_order_difference"] = (
        audit["right_residence_file_order"] - audit["right_residence_sorted"]
    ).abs()

    sums = {name: int(audit[name].sum()) for name in [
        "nonfinite_time", "file_order_negative_dt", "file_order_zero_dt",
        "sorted_duplicate_dt", "nonfinite_phi_or_bounds", "invalid_window_bounds",
        "unparseable_membership", "membership_mismatches",
    ]}
    summary = {
        "n_tracks": int(len(audit)),
        "n_rows": int(len(df)),
        **sums,
        "tracks_with_file_order_violations": int(
            ((audit["file_order_negative_dt"] > 0) | (audit["file_order_zero_dt"] > 0)).sum()
        ),
        "tracks_with_residence_order_difference": int(
            (audit["residence_order_difference"] > cfg["tolerances"]["residence_difference"]).sum()
        ),
        "irregular_tracks": int((audit["within_track_dt_cv"] > cfg["cadence"]["dt_cv_warning"]).sum()),
        "median_within_track_dt_cv": float(audit["within_track_dt_cv"].median()),
        "span_min": float(audit["t_span"].min()),
        "span_median": median_span,
        "span_max": float(audit["t_span"].max()),
        "short_span_threshold": threshold,
        "short_span_tracks": int(audit["short_span_exposure"].sum()),
        "sparse_tracks": int(audit["sparse_track_exposure"].sum()),
    }
    return audit, summary


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    cfg_path = (root / args.config).resolve()
    cfg = read_config(cfg_path)
    input_path = root / cfg["data"]["track_parquet"]
    source_path = root / cfg["data"]["ripeness_source"]
    out_root = root / cfg["outputs"]["root"]
    paper_root = root / cfg["outputs"]["paper_root"]
    out_root.mkdir(parents=True, exist_ok=True)
    paper_root.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(input_path)
    audit, summary = audit_tracks(df, cfg)
    source = function_sorts_time(source_path, cfg["source_audit"]["function_name"])
    file_order_safe = summary["tracks_with_file_order_violations"] == 0
    ordering_precondition = bool(file_order_safe or source["sort_detected"])
    blocking_fields = [
        "nonfinite_time", "sorted_duplicate_dt", "nonfinite_phi_or_bounds",
        "invalid_window_bounds", "unparseable_membership", "membership_mismatches",
    ]
    blocking_total = sum(summary[name] for name in blocking_fields)
    authorized = ordering_precondition and blocking_total == 0
    verdict = {
        "schema_version": 1,
        "run_id": cfg["run_id"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path.relative_to(root)),
        "input_sha256": sha256(input_path),
        "ripeness_source": str(source_path.relative_to(root)),
        "source_sort_audit": source,
        "file_order_monotonic": file_order_safe,
        "ordering_precondition_satisfied": ordering_precondition,
        "track_integrity": summary,
        "cadence_interpretation": "irregularity_is_orthogonal_to_time_integrity",
        "span_interpretation": "short_spans_are_equal_weight_interpretation_exposure_not_data_corruption",
        "right_interval_time_weighted_freeze_authorized": authorized,
        "memory_generator_3_ordering_authorized": authorized,
        "claim_cap": "time_integrity_only_no_memory_or_host_regulation_claim",
    }
    audit.to_csv(out_root / "bh_time_track_integrity_by_track.csv", index=False)
    verdict_path = out_root / "bh_time_track_integrity_verdict.json"
    verdict_path.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    tex = rf"""\documentclass[11pt]{{article}}
\usepackage[margin=1in]{{geometry}}
\begin{{document}}
\section*{{BH Tier 1 Logbook Entry 004: Time-Track Integrity Freeze}}
Run: \texttt{{{cfg['run_id'].replace('_', r'\_')}}}.\\
File-order monotonic: \texttt{{{str(file_order_safe).lower()}}}.\\
Internal sorting detected: \texttt{{{str(source['sort_detected']).lower()}}}.\\
Membership mismatches: {summary['membership_mismatches']}. Invalid bounds: {summary['invalid_window_bounds']}.\\
Irregular tracks: {summary['irregular_tracks']} of {summary['n_tracks']}; this is orthogonal to integrity.\\
Span range: {summary['span_min']:.6g} to {summary['span_max']:.6g}; {summary['short_span_tracks']} tracks fall below the declared short-span warning threshold.\\
Right-interval freeze authorized: \texttt{{{str(authorized).lower()}}}.
\end{{document}}
"""
    (paper_root / "bh_time_track_integrity_freeze_entry_004.tex").write_text(tex, encoding="utf-8")
    print(json.dumps(verdict, indent=2))
    return 0 if authorized else 2


if __name__ == "__main__":
    raise SystemExit(main())
