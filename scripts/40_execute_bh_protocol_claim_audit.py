#!/usr/bin/env python3
"""Deterministic, read-only scientific evidence audit for the black-hole HRSM branch."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required. Install repository requirements first.") from exc


SCRIPT_VERSION = "1.0.0"
TEXT_READ_LIMIT = 16 * 1024 * 1024
CSV_ROW_LIMIT = 2_000_000


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def csv_dump(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def safe_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def discover_files(root: Path, scan_roots: list[str], extensions: set[str]) -> list[Path]:
    found: set[Path] = set()
    for item in scan_roots:
        base = root / item
        if base.is_file() and base.suffix.lower() in extensions:
            found.add(base)
        elif base.is_dir():
            for path in base.rglob("*"):
                if path.is_file() and path.suffix.lower() in extensions:
                    found.add(path)
    return sorted(found)


def read_text(path: Path) -> str:
    if path.stat().st_size > TEXT_READ_LIMIT:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def glob_matches(root: Path, patterns: list[str]) -> list[Path]:
    matches: set[Path] = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file():
                matches.add(path)
    return sorted(matches)


def git_info(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    status = run("status", "--porcelain")
    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "tag_exact": run("describe", "--tags", "--exact-match"),
        "worktree_dirty": bool(status) if status is not None else None,
    }


def build_claim_inventory(root: Path, claims: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[Path]]]:
    rows: list[dict[str, Any]] = []
    evidence_map: dict[str, list[Path]] = {}
    for claim in claims:
        paths = glob_matches(root, claim.get("evidence_globs", []))
        evidence_map[claim["claim_id"]] = paths
        corpus = "\n".join(read_text(p).lower() for p in paths)
        tokens = [str(t).lower() for t in claim.get("required_any_tokens", [])]
        token_hits = sorted(t for t in tokens if t in corpus)
        evidence_present = bool(paths)
        base = claim["base_verdict"]
        if not evidence_present and base in {"allowed", "allowed_bounded"}:
            verdict = "blocked_missing_artifact"
        elif evidence_present and tokens and not token_hits and base in {"allowed", "allowed_bounded"}:
            verdict = "blocked_unverified_content"
        else:
            verdict = base
        rows.append({
            "claim_id": claim["claim_id"],
            "short_name": claim["short_name"],
            "attempted_headline": claim["attempted_headline"],
            "base_verdict": base,
            "audit_verdict": verdict,
            "allowed_headline": claim["allowed_headline"],
            "forbidden_headline": claim["forbidden_headline"],
            "artifact_count": len(paths),
            "token_hits": "|".join(token_hits),
            "artifacts": "|".join(safe_rel(p, root) for p in paths),
        })
    return rows, evidence_map


def axis_audit(root: Path, text_files: list[Path]) -> list[dict[str, Any]]:
    patterns = {
        "H": re.compile(r"(?i)(specific[_ ]?accretion|mdot|lambda[_ ]?bh|throughput|forcing|reserve)"),
        "R": re.compile(r"(?i)(recoverability|return[_ ]?time|recovery[_ ]?rate|restoring[_ ]?rate)"),
        "S": re.compile(r"(?i)(stability|settlement|equilibrium|offset|residual|d4000|sigma)"),
        "M": re.compile(r"(?i)(memory[_ ]?kernel|augmentation[_ ]?manifest|power[_ -]?law[_ ]?kernel|history[_ ]?kernel)"),
    }
    rows: list[dict[str, Any]] = []
    for axis, regex in patterns.items():
        matches: list[str] = []
        for path in text_files:
            text = read_text(path)
            if text and regex.search(text):
                matches.append(safe_rel(path, root))
        if axis == "H":
            verdict = "identity_unresolved" if matches else "not_found"
            cap = "Do not call throughput reserve without an axis-specificity justification."
        elif axis == "R":
            verdict = "candidate_only" if matches else "not_activated"
            cap = "Retrospective return time cannot validate the same future recovery event."
        elif axis == "S":
            verdict = "formula_concordance_required" if matches else "not_found"
            cap = "Equilibrium-distance prose must match code and equations."
        else:
            verdict = "candidate_only" if matches else "not_activated"
            cap = "No memory claim without a frozen admitted-augmentation manifest."
        rows.append({"axis": axis, "files_with_candidates": len(matches), "candidate_files": "|".join(matches[:100]), "verdict": verdict, "binding_cap": cap})
    return rows


def formula_concordance(root: Path, text_files: list[Path]) -> list[dict[str, Any]]:
    checks = [
        ("stability_absolute_residual", re.compile(r"(?i)(abs\s*\(|np\.abs|absolute|distance.{0,30}(median|equilibrium))"), "Expected for unsigned equilibrium distance."),
        ("stability_signed_residual", re.compile(r"(?i)(residual|offset).{0,80}(median|class|predict|equilibrium)"), "Admissible only with declared orientation."),
        ("tier1_composite", re.compile(r"(?i)(phi|potential).{0,100}(H|throughput).{0,30}(S|stability)"), "Requires common scale and dominance audit."),
        ("ripeness_window_035_065", re.compile(r"(?i)(0\.35.{0,40}0\.65|q35.{0,40}q65|quantile.{0,80}35)"), "Treat as selected unless frozen before outcome inspection."),
        ("sigma_mass_shared_channel", re.compile(r"(?i)(m[_ ]?sigma|mbh.{0,40}sigma|black.?hole.?mass.{0,60}velocity.?dispersion)"), "Potential target-side construction dependence."),
    ]
    rows: list[dict[str, Any]] = []
    for check_id, regex, consequence in checks:
        hits: list[str] = []
        snippets: list[str] = []
        for path in text_files:
            text = read_text(path)
            match = regex.search(text)
            if match:
                hits.append(safe_rel(path, root))
                snippets.append(re.sub(r"\s+", " ", text[max(0, match.start()-80):match.end()+120])[:300])
        rows.append({
            "check_id": check_id,
            "status": "candidate_found_review_required" if hits else "not_found_unresolved",
            "hit_count": len(hits),
            "files": "|".join(hits[:50]),
            "example": snippets[0] if snippets else "",
            "protocol_consequence": consequence,
        })
    return rows


def delimiter_for(path: Path) -> str:
    return "\t" if path.suffix.lower() == ".tsv" else ","


def effective_unit_inventory(root: Path, table_files: list[Path], candidates: list[str]) -> list[dict[str, Any]]:
    target = {c.lower() for c in candidates}
    rows: list[dict[str, Any]] = []
    for path in table_files:
        try:
            with path.open("r", newline="", encoding="utf-8", errors="replace") as handle:
                reader = csv.DictReader(handle, delimiter=delimiter_for(path))
                fields = reader.fieldnames or []
                selected = [f for f in fields if f.strip().lower() in target]
                if not selected:
                    continue
                values = {f: set() for f in selected}
                n = 0
                truncated = False
                for record in reader:
                    n += 1
                    for field in selected:
                        value = (record.get(field) or "").strip()
                        if value:
                            values[field].add(value)
                    if n >= CSV_ROW_LIMIT:
                        truncated = True
                        break
                for field in selected:
                    rows.append({
                        "artifact": safe_rel(path, root), "candidate_unit": field,
                        "rows_scanned": n, "unique_nonmissing": len(values[field]),
                        "scan_truncated": truncated,
                        "interpretation": "candidate_only_not_automatically_independent",
                    })
        except (OSError, csv.Error):
            continue
    return rows


def numeric_quarantine(root: Path, table_files: list[Path], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    extreme = float(cfg["extreme_absolute_value"])
    near_zero = float(cfg["near_zero_scale"])
    ignore = re.compile(cfg["ignore_column_regex"])
    rows: list[dict[str, Any]] = []
    for path in table_files:
        flags: defaultdict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"count": 0, "example": ""})
        try:
            with path.open("r", newline="", encoding="utf-8", errors="replace") as handle:
                reader = csv.DictReader(handle, delimiter=delimiter_for(path))
                for idx, record in enumerate(reader, start=2):
                    if idx > CSV_ROW_LIMIT + 1:
                        break
                    for column, raw in record.items():
                        if column is None or ignore.search(column) or raw is None or not raw.strip():
                            continue
                        try:
                            value = float(raw)
                        except ValueError:
                            continue
                        reason = None
                        if not math.isfinite(value): reason = "nonfinite"
                        elif abs(value) > extreme: reason = "extreme_absolute_value"
                        elif value != 0.0 and abs(value) < near_zero and re.search(r"(?i)(scale|mad|std|denom|sigma|iqr)", column): reason = "near_zero_scale"
                        if reason:
                            cell = flags[(column, reason)]
                            cell["count"] += 1
                            if not cell["example"]: cell["example"] = f"row={idx};value={raw}"
        except (OSError, csv.Error):
            continue
        for (column, reason), info in flags.items():
            rows.append({"artifact": safe_rel(path, root), "column": column, "reason": reason, "count": info["count"], "example": info["example"], "verdict": "quarantine_review_required"})
    return rows


def closing_contract(claim_rows: list[dict[str, Any]]) -> dict[str, Any]:
    contracts = []
    for row in claim_rows:
        verdict = row["audit_verdict"]
        action = "retain_bounded" if verdict in {"allowed", "allowed_bounded"} else "rewrite_or_remove"
        if verdict in {"rejected_negative_result", "numeric_quarantine"}: action = "retain_as_refusal_or_quarantine"
        contracts.append({
            "claim_id": row["claim_id"], "verdict": verdict, "manuscript_action": action,
            "allowed_headline": row["allowed_headline"], "forbidden_headline": row["forbidden_headline"],
            "artifact_count": row["artifact_count"], "artifacts": row["artifacts"].split("|") if row["artifacts"] else [],
        })
    return {"contract_version": 1, "generated_utc": utc_now(), "claims": contracts}


def tex_escape(value: Any) -> str:
    text = str(value)
    for old, new in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#"), ("$", r"\$")]:
        text = text.replace(old, new)
    return text


def write_latex(path: Path, cfg: dict[str, Any], claims: list[dict[str, Any]], axis_rows: list[dict[str, Any]], numeric_rows: list[dict[str, Any]], manifest_hash: str) -> None:
    counts = defaultdict(int)
    for row in claims: counts[row["audit_verdict"]] += 1
    lines = [
        r"\documentclass[11pt]{article}", r"\usepackage[margin=1in]{geometry}", r"\usepackage{booktabs,longtable,array}",
        r"\usepackage[hidelinks]{hyperref}", r"\begin{document}",
        r"\section*{Logbook Entry 001: Protocol-Aware Black-Hole Claim Audit}",
        rf"\textbf{{Audit ID:}} {tex_escape(cfg['audit_id'])}\\",
        rf"\textbf{{Protocol:}} {tex_escape(cfg['protocol_version'])}\\",
        rf"\textbf{{Manifest SHA-256:}} \texttt{{{manifest_hash}}}",
        r"\subsection*{Purpose}",
        r"This entry adjudicates manuscript-facing claims before recoverability or memory coordinates are activated. It inventories frozen evidence, records numerical and construction caps, and prevents unsupported claims from entering the next manuscript revision.",
        r"\subsection*{Claim adjudication}",
        r"\small\begin{longtable}{p{1.5cm}p{3.5cm}p{9.2cm}}\toprule Claim & Verdict & Allowed headline \\\midrule\endhead",
    ]
    for row in claims:
        lines.append(f"{tex_escape(row['claim_id'])} & {tex_escape(row['audit_verdict'])} & {tex_escape(row['allowed_headline'])} " + r"\\")
    lines += [r"\bottomrule\end{longtable}\normalsize", r"\subsection*{Axis status}", r"\begin{tabular}{lll}\toprule Axis & Candidate files & Verdict \\\midrule"]
    for row in axis_rows:
        lines.append(f"{tex_escape(row['axis'])} & {row['files_with_candidates']} & {tex_escape(row['verdict'])} " + r"\\")
    lines += [r"\bottomrule\end{tabular}", r"\subsection*{Outcome}"]
    summary = "; ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    lines.append(tex_escape(summary) + r".\\")
    lines.append(f"Numeric quarantine flags requiring review: {len(numeric_rows)}. ")
    lines += [
        r"The current branch remains a reduced Tier 1 projection. Recoverability and memory are not activated by this audit. The next stage may begin only after the configuration and manifest hashes are frozen and the blocked formula, provenance, effective-unit, and numerical items are resolved or explicitly carried as caps.",
        r"\end{document}", ""
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/protocol/bh_claim_audit_v1.yaml")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    config_path = (root / args.config).resolve()
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    out = root / cfg["output_root"]
    audit_dir, manifest_dir, adjudication_dir = out / "audits", out / "manifests", out / "adjudication"
    text_ext = {e.lower() for e in cfg["text_extensions"]}
    hash_ext = {e.lower() for e in cfg["hash_extensions"]}
    text_files = discover_files(root, cfg["scan_roots"], text_ext)
    table_files = [p for p in text_files if p.suffix.lower() in {".csv", ".tsv"}]

    claims, evidence_map = build_claim_inventory(root, cfg["claims"])
    axes = axis_audit(root, text_files)
    formulas = formula_concordance(root, text_files)
    units = effective_unit_inventory(root, table_files, cfg["effective_unit_candidates"])
    numeric = numeric_quarantine(root, table_files, cfg["numeric_quarantine"])

    csv_dump(audit_dir / "bh_claim_inventory.csv", claims, ["claim_id","short_name","attempted_headline","base_verdict","audit_verdict","allowed_headline","forbidden_headline","artifact_count","token_hits","artifacts"])
    csv_dump(audit_dir / "bh_axis_definition_audit.csv", axes, ["axis","files_with_candidates","candidate_files","verdict","binding_cap"])
    csv_dump(audit_dir / "bh_formula_code_concordance.csv", formulas, ["check_id","status","hit_count","files","example","protocol_consequence"])
    csv_dump(audit_dir / "bh_effective_unit_inventory.csv", units, ["artifact","candidate_unit","rows_scanned","unique_nonmissing","scan_truncated","interpretation"])
    csv_dump(audit_dir / "bh_numeric_quarantine.csv", numeric, ["artifact","column","reason","count","example","verdict"])
    csv_dump(audit_dir / "bh_claim_to_artifact_matrix.csv", claims, ["claim_id","audit_verdict","artifact_count","artifacts","allowed_headline","forbidden_headline"])

    contract = closing_contract(claims)
    json_dump(adjudication_dir / "bh_closing_contract.json", contract)
    forbidden = [{"claim_id": c["claim_id"], "forbidden_headline": c["forbidden_headline"], "replacement": c["allowed_headline"]} for c in claims]
    csv_dump(root / cfg["paper_output_root"] / "forbidden_headlines.csv", forbidden, ["claim_id","forbidden_headline","replacement"])
    csv_dump(root / cfg["paper_output_root"] / "claim_to_artifact_matrix.csv", claims, ["claim_id","audit_verdict","artifact_count","artifacts","allowed_headline"])

    generated_roots = [(root / cfg["output_root"]).resolve(), (root / cfg["paper_output_root"]).resolve()]
    hash_files = [
        p for p in discover_files(root, cfg["scan_roots"], hash_ext)
        if not any(p.resolve().is_relative_to(generated) for generated in generated_roots)
    ]
    manifest = {
        "schema_version": 1, "audit_id": cfg["audit_id"], "script_version": SCRIPT_VERSION,
        "generated_utc": utc_now(), "repo_root": str(root), "config": safe_rel(config_path, root),
        "config_sha256": sha256_file(config_path), "git": git_info(root),
        "counts": {"claims": len(claims), "text_files": len(text_files), "table_files": len(table_files), "numeric_flags": len(numeric), "effective_unit_rows": len(units)},
        "input_hashes": [{"path": safe_rel(p, root), "sha256": sha256_file(p), "bytes": p.stat().st_size} for p in hash_files],
        "policy": {"scientific_inputs_modified": False, "missing_evidence_can_pass": False, "memory_activated": False, "recoverability_activated": False},
    }
    manifest_path = manifest_dir / "bh_claim_audit_manifest.json"
    json_dump(manifest_path, manifest)
    manifest_hash = sha256_file(manifest_path)
    write_latex(root / cfg["paper_output_root"] / "bh_protocol_claim_audit.tex", cfg, claims, axes, numeric, manifest_hash)

    summary = {
        "audit_id": cfg["audit_id"], "manifest_sha256": manifest_hash,
        "claim_verdict_counts": dict(sorted((v, sum(1 for c in claims if c["audit_verdict"] == v)) for v in {c["audit_verdict"] for c in claims})),
        "numeric_quarantine_flags": len(numeric), "effective_unit_inventory_rows": len(units),
        "next_stage_authorized": False,
        "next_stage_condition": "Review closing contract and freeze unresolved remediations before adding R/M generators.",
    }
    json_dump(adjudication_dir / "bh_claim_audit_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
