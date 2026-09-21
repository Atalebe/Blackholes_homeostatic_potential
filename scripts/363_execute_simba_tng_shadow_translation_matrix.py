#!/usr/bin/env python3
"""Run the exact four-stage/five-offset matrix after current Run 217C-R3 acceptance."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from bh_simba_runtime_manifest_common_v1_4 import (
    atomic_json,
    prior_v1_3_attempt_custody_exact,
    read_json,
    sha256,
    stable_json_snapshot,
    utc_now,
    write_csv,
)
from bh_simba_shadow_exact_binding_source_state_lifecycle_recovery_v1_4 import (
    authorities_unchanged,
    canonical_json_sha256,
    construction_audit_exact,
    observables_equal,
    original_authority_hashes,
    run_offset,
    runtime_binding_receipt_exact,
    stage_output_evidence_exact,
    source_authority_resolution_exact,
)


FIELDS = [
    "offset", "stage", "executor_sha256", "authority_config_sha256", "shadow_config_sha256",
    "observed_executor_sha256", "preinvoke_config_sha256",
    "preinvoke_primary_snapshots_exact",
    "return_code", "executor_invoked", "stage_executed", "expected_output_fresh_exact",
    "stage_verdict_fresh", "stage_verdict_sha256", "observable_count", "stdout_sha256", "stderr_sha256",
    "classified_interface_hold", "numeric_and_categorical_invariant",
    "shadow_config_integrity_mutations_before_stage", "shadow_manifest_integrity_mutations_before_stage",
    "command_contract_exact", "repo_root_is_explicit_shadow", "config_path_shadow_relative",
    "manifest_path_shadow_relative", "required_input_count", "required_input_existing_count",
    "required_input_manifest_record_count", "required_input_digest_match_count",
    "manifest_config_concordant", "executor_manifest_closure_pass", "manifest_file_record_count",
    "manifest_file_existing_count",
    "manifest_file_digest_match_count", "post_stage_binding_required", "post_stage_binding_pass",
    "all_shadow_manifests_closure_pass", "manifest_byte_invariance_pass",
    "runtime_binding_receipt_sha256", "stage_lifecycle_pass",
    "invocation_manifest_sha256", "command_sha256", "detail",
]


HEX64 = re.compile(r"[0-9a-f]{64}")


def csv_fields(rows: list[dict[str, Any]]) -> list[str]:
    extras = sorted({key for row in rows for key in row} - set(FIELDS))
    return FIELDS + extras


def expected_path(root: Path, output: Path, supplied: str, filename: str) -> tuple[Path, bool]:
    """Resolve an input and prove it is the one current output named by the config."""
    candidate = root / supplied
    symlink = candidate.is_symlink()
    path = candidate.resolve()
    return path, path == (output / filename).resolve() and path.is_file() and not symlink


def files_exact(root: Path, records: dict[str, Any]) -> bool:
    """Verify the complete root-relative file set frozen by an acceptance verdict."""
    if not isinstance(records, dict) or not records:
        return False
    for name, record in records.items():
        if not isinstance(name, str) or not isinstance(record, dict):
            return False
        expected = record.get("sha256")
        if not isinstance(expected, str) or HEX64.fullmatch(expected) is None:
            return False
        try:
            candidate = root / name
            if candidate.is_symlink():
                return False
            path = candidate.resolve(strict=True)
            path.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return False
        if not path.is_file() or sha256(path) != expected:
            return False
    return True


def row_success(row: dict[str, Any]) -> bool:
    """Define success as an invoked executor plus fresh output and full lifecycle closure."""
    record_count = row.get("manifest_file_record_count")
    match_count = row.get("manifest_file_digest_match_count")
    required_count = row.get("required_input_count")
    binding_flag_exact = isinstance(row.get("post_stage_binding_required"), bool)
    binding_required = row.get("post_stage_binding_required") is True
    binding_stage_exact = (
        binding_required
        if row.get("stage") == "generator3_phase_b"
        else row.get("post_stage_binding_required") is False
    )
    return (
        row.get("executor_invoked") is True
        and row.get("return_code") == 0
        and row.get("stage_executed") is True
        and row.get("observable_count", 0) > 0
        and row.get("expected_output_fresh_exact") is True
        and row.get("stage_verdict_fresh") is True
        and row.get("stage_verdict_run_id_exact") is True
        and row.get("required_verdict_keys_pass") is True
        and row.get("required_truthy_keys_pass") is True
        and isinstance(row.get("stage_verdict_sha256"), str)
        and HEX64.fullmatch(row["stage_verdict_sha256"]) is not None
        and all(
            isinstance(row.get(name), str) and HEX64.fullmatch(row[name]) is not None
            for name in (
                "shadow_config_sha256", "invocation_manifest_sha256", "command_sha256",
                "stdout_sha256", "stderr_sha256",
            )
        )
        and row.get("observed_executor_sha256") == row.get("executor_sha256")
        and row.get("preinvoke_config_sha256") == row.get("shadow_config_sha256")
        and row.get("preinvoke_primary_snapshots_exact") is True
        and row.get("manifest_config_concordant") is True
        and row.get("executor_manifest_closure_pass") is True
        and row.get("all_shadow_manifests_closure_pass") is True
        and row.get("manifest_byte_invariance_pass") is True
        and isinstance(record_count, int)
        and not isinstance(record_count, bool)
        and record_count > 0
        and row.get("manifest_file_existing_count") == record_count
        and match_count == record_count
        and isinstance(required_count, int)
        and not isinstance(required_count, bool)
        and required_count > 0
        and row.get("required_input_existing_count") == required_count
        and row.get("required_input_manifest_record_count") == required_count
        and row.get("required_input_digest_match_count") == required_count
        and row.get("command_contract_exact") is True
        and row.get("repo_root_is_explicit_shadow") is True
        and row.get("config_path_shadow_relative") is True
        and row.get("manifest_path_shadow_relative") is True
        and row.get("classified_interface_hold") is False
        and row.get("shadow_config_integrity_mutations_before_stage") == 0
        and row.get("shadow_manifest_integrity_mutations_before_stage") == 0
        and row.get("stage_lifecycle_pass") is True
        and binding_flag_exact
        and binding_stage_exact
        and row.get("post_stage_binding_pass") is True
    )


def receipt_exact(
    receipt: Any,
    cfg: dict[str, Any],
    source_root: Path,
) -> bool:
    """Require the immutable source context for every runtime receipt check."""
    return runtime_binding_receipt_exact(receipt, cfg, source_root)


def row_authority_exact(row: dict[str, Any], stage: dict[str, Any]) -> bool:
    return (
        row.get("stage") == stage.get("stage")
        and row.get("executor_sha256") == stage.get("executor_sha256")
        and row.get("authority_config_sha256") == stage.get("config_sha256")
        and isinstance(row.get("shadow_config_sha256"), str)
        and HEX64.fullmatch(row["shadow_config_sha256"]) is not None
    )


def source_authority_receipt_exact(
    audit: Any,
    cfg: dict[str, Any],
    source_root: Path,
) -> bool:
    """Validate historical source claims without calling them shadow-closed."""
    if not isinstance(audit, dict):
        return False
    resolution = audit.get("source_authority_resolution")
    return bool(
        audit.get("source_authority_resolution_pass") is True
        and isinstance(resolution, dict)
        and source_authority_resolution_exact(resolution, cfg, source_root)
        and audit.get("source_authority_resolution_receipt_sha256")
        == resolution.get("receipt_sha256")
        and resolution.get("resolution_pass") is True
        and resolution.get("fatal_path_count") == 0
        and resolution.get("primary_manifest_disagreement_count", 0) >= 1
        and resolution.get("known_prior_first_conflict_resolved_by_primary") is True
    )


def translated_shadow_closures_exact(
    audit: Any,
    cfg: dict[str, Any],
    receipt: Any,
) -> bool:
    """Reconcile translated-shadow closure summaries with every embedded row."""
    if audit.get("post_stage_generated_bindings_complete") is True:
        post = audit.get("post_stage_generated_binding_receipts", [])
        if not isinstance(post, list) or len(post) != 2 or any(not isinstance(item, dict) or item.get("binding_pass") is not True for item in post):
            return False
        closures = audit.get("final_manifest_closures", [])
        if not isinstance(closures, list): return False
        by_path = {item.get("manifest_relative_path"): item for item in closures if isinstance(item, dict)}
        expected = {receipt.get("shared_manifest"): receipt.get("shared_manifest_after_sha256"), receipt.get("confirmation_manifest"): receipt.get("confirmation_manifest_after_sha256")}
        for item in post: expected[item.get("target_manifest_relative_path")] = item.get("target_manifest_after_sha256")
        return bool(len(by_path) == len({stage["manifest"] for stage in cfg["stage_contracts"]}) and all(path in by_path and by_path[path].get("manifest_sha256") == digest and by_path[path].get("closure_pass") is True and by_path[path].get("allowed_missing_count") == 0 for path,digest in expected.items() if isinstance(path,str)))
    if not isinstance(audit, dict) or not isinstance(receipt, dict):
        return False
    closures = audit.get("final_manifest_closures")
    expected = {stage["manifest"] for stage in cfg["stage_contracts"]}
    if not isinstance(closures, list) or len(closures) != len(expected):
        return False
    by_path: dict[str, dict[str, Any]] = {}
    for item in closures:
        if not isinstance(item, dict):
            return False
        relative = item.get("manifest_relative_path")
        rows = item.get("rows")
        auxiliary = item.get("auxiliary_rows")
        if relative not in expected or relative in by_path or not isinstance(rows, list) or not isinstance(auxiliary, list):
            return False
        if any(not isinstance(row, dict) for row in rows + auxiliary):
            return False
        record_count = item.get("manifest_file_record_count")
        auxiliary_count = item.get("auxiliary_integrity_binding_count")
        if not (
            isinstance(record_count, int)
            and not isinstance(record_count, bool)
            and record_count == len(rows) > 0
            and item.get("manifest_file_existing_count")
            == sum(row.get("valid_regular_contained") is True for row in rows)
            == record_count
            and item.get("manifest_file_digest_match_count")
            == sum(row.get("digest_exact") is True for row in rows)
            == record_count
            and item.get("allowed_missing_count")
            == sum(row.get("allowed_pending") is True for row in rows)
            == 0
            and all(
                isinstance(row, dict)
                and row.get("digest_exact") is True
                and row.get("size_fields_exact") is True
                and row.get("allowed_pending") is False
                and row.get("status") == "exact"
                for row in rows
            )
            and isinstance(auxiliary_count, int)
            and not isinstance(auxiliary_count, bool)
            and auxiliary_count == len(auxiliary)
            and item.get("auxiliary_integrity_binding_match_count")
            == sum(row.get("exact") is True for row in auxiliary)
            == auxiliary_count
            and item.get("auxiliary_integrity_bindings_pass") is True
            and all(
                isinstance(row, dict)
                and row.get("exact") is True
                and row.get("allowed_pending") is False
                for row in auxiliary
            )
            and item.get("closure_pass") is True
            and item.get("hold_reason") is None
            and isinstance(item.get("manifest_sha256"), str)
            and HEX64.fullmatch(item["manifest_sha256"]) is not None
        ):
            return False
        by_path[relative] = item
    return bool(
        set(by_path) == expected
        and by_path.get(receipt.get("shared_manifest"), {}).get("manifest_sha256")
        == receipt.get("shared_manifest_after_sha256")
        and by_path.get(receipt.get("confirmation_manifest"), {}).get("manifest_sha256")
        == receipt.get("confirmation_manifest_after_sha256")
    )


def shadow_config_provenance_exact(
    audit: Any,
    cfg: dict[str, Any],
    offset_rows: list[dict[str, Any]],
) -> bool:
    """Tie every invoked shadow config digest to its construction receipt."""
    if not isinstance(audit, dict) or not isinstance(offset_rows, list):
        return False
    stages = cfg["stage_contracts"]
    if len(offset_rows) != len(stages) or [row.get("stage") for row in offset_rows] != [stage["stage"] for stage in stages]:
        return False
    rows_by_stage = {row["stage"]: row for row in offset_rows}
    config_by_path = {
        item.get("relative_path"): item
        for item in audit.get("construction_config_mutation_receipts", [])
        if isinstance(item, dict)
    }
    return bool(
        len(rows_by_stage) == len(stages)
        and all(
            rows_by_stage[stage["stage"]].get("shadow_config_sha256")
            == config_by_path.get(stage["config"], {}).get("after_sha256")
            for stage in stages
        )
    )


def offset_provenance_exact(
    audit: Any,
    cfg: dict[str, Any],
    offset_rows: list[dict[str, Any]],
) -> bool:
    """Bind every row to construction-time configs and its exact manifest state."""
    if audit.get("post_stage_generated_bindings_complete") is True:
        stages=cfg["stage_contracts"]; rows_by_stage={row.get("stage"):row for row in offset_rows if isinstance(row,dict)}; receipts=audit.get("runtime_product_binding_receipts",[]); post=audit.get("post_stage_generated_binding_receipts",[])
        if not isinstance(receipts,list) or len(receipts)!=1 or not isinstance(post,list) or len(post)!=2: return False
        receipt=receipts[0]; by={item.get("producer_stage"):item for item in post if isinstance(item,dict)}; screen=by.get("generator3_null_screen",{}); confirm=by.get("generator3_null_confirmation_2000",{})
        producer=rows_by_stage.get("generator3_phase_b",{})
        return bool(len(rows_by_stage)==len(stages) and producer.get("runtime_binding_receipt_sha256")==receipt.get("receipt_sha256") and producer.get("invocation_manifest_sha256")==receipt.get("shared_manifest_before_sha256") and rows_by_stage["generator3_null_screen"].get("invocation_manifest_sha256")==receipt.get("shared_manifest_after_sha256") and screen.get("target_manifest_before_sha256")==receipt.get("confirmation_manifest_after_sha256") and rows_by_stage["generator3_null_confirmation_2000"].get("invocation_manifest_sha256")==screen.get("target_manifest_after_sha256") and rows_by_stage["generator4_pooled_innovation_screen"].get("invocation_manifest_sha256")==confirm.get("target_manifest_after_sha256") and receipt.get("offset")==audit.get("offset") and all(row.get("offset")==receipt.get("offset") for row in offset_rows) and shadow_config_provenance_exact(audit,cfg,offset_rows))
    if not isinstance(audit, dict) or not isinstance(offset_rows, list):
        return False
    stages = cfg["stage_contracts"]
    if len(offset_rows) != len(stages) or [row.get("stage") for row in offset_rows] != [stage["stage"] for stage in stages]:
        return False
    rows_by_stage = {row["stage"]: row for row in offset_rows}
    if len(rows_by_stage) != len(stages):
        return False
    receipts = audit.get("runtime_product_binding_receipts")
    if not isinstance(receipts, list) or len(receipts) != 1 or not isinstance(receipts[0], dict):
        return False
    receipt = receipts[0]
    construction_by_path = {
        item.get("relative_path"): item
        for item in audit.get("construction_manifest_mutation_receipts", [])
        if isinstance(item, dict)
    }
    closure_by_path = {
        item.get("manifest_relative_path"): item
        for item in audit.get("final_manifest_closures", [])
        if isinstance(item, dict)
    }
    binding = cfg["runtime_binding"]
    producer = rows_by_stage.get(binding["producer_stage"], {})
    consumers = binding["consumer_stages"]
    return bool(
        producer.get("post_stage_binding_required") is True
        and producer.get("post_stage_binding_pass") is True
        and producer.get("runtime_binding_receipt_sha256") == receipt.get("receipt_sha256")
        and producer.get("stage_verdict_sha256")
        == receipt.get("target_sha256")
        == receipt.get("product_sha256")
        and producer.get("invocation_manifest_sha256")
        == receipt.get("producer_invocation_manifest_sha256")
        == receipt.get("shared_manifest_before_sha256")
        and rows_by_stage.get(consumers[0], {}).get("invocation_manifest_sha256")
        == receipt.get("shared_manifest_after_sha256")
        and rows_by_stage.get(consumers[1], {}).get("invocation_manifest_sha256")
        == receipt.get("confirmation_manifest_after_sha256")
        and receipt.get("offset") == audit.get("offset")
        and all(row.get("offset") == receipt.get("offset") for row in offset_rows)
        and shadow_config_provenance_exact(audit, cfg, offset_rows)
        and all(
            rows_by_stage[stage["stage"]].get("invocation_manifest_sha256")
            == construction_by_path.get(stage["manifest"], {}).get("after_sha256")
            == closure_by_path.get(stage["manifest"], {}).get("manifest_sha256")
            for stage in stages
            if stage["stage"] not in {binding["producer_stage"], *consumers}
        )
    )


def construction_and_runtime_receipts_exact(
    audit: Any,
    cfg: dict[str, Any],
    source_root: Path,
) -> bool:
    if not isinstance(audit, dict):
        return False
    receipts = audit.get("runtime_product_binding_receipts")
    return bool(
        isinstance(receipts, list)
        and len(receipts) == 1
        and isinstance(receipts[0], dict)
        and audit.get("runtime_binding_receipt_count")
        == cfg["runtime_binding"]["receipt_count_per_shadow"]
        == 1
        and receipt_exact(receipts[0], cfg, source_root)
        and construction_audit_exact(audit, cfg, receipts[0], source_root)
    )


def audit_exact(
    audit: Any,
    cfg: dict[str, Any],
    source_root: Path,
    offset_rows: list[dict[str, Any]],
) -> bool:
    if not isinstance(audit, dict) or not isinstance(offset_rows, list):
        return False
    receipts = audit.get("runtime_product_binding_receipts")
    receipt = receipts[0] if isinstance(receipts, list) and len(receipts) == 1 else None
    construction_exact = bool(
        isinstance(receipt, dict)
        and receipt_exact(receipt, cfg, source_root)
        and construction_audit_exact(audit, cfg, receipt, source_root)
    )
    return bool(
        isinstance(receipts, list)
        and len(receipts) == 1
        and audit.get("runtime_binding_receipt_count") == cfg["runtime_binding"]["receipt_count_per_shadow"] == 1
        and audit.get("runtime_binding_receipts_pass") is True
        and receipt_exact(receipts[0], cfg, source_root)
        and construction_exact
        and source_authority_receipt_exact(audit, cfg, source_root)
        and translated_shadow_closures_exact(audit, cfg, receipt)
        and stage_output_evidence_exact(audit, cfg, source_root)
        and offset_provenance_exact(audit, cfg, offset_rows)
        and audit.get("manifest_byte_invariance_pass") is True
        and audit.get("full_manifest_closure_pass") is True
        and audit.get("manifest_provenance_chain_pass") is True
        and audit.get("runtime_binding_provenance_chain_pass") is True
        and audit.get("source_authorities_unchanged") is True
        and audit.get("source_authorities_unchanged_after_offset") is True
    )


def audit_manifest_paths_exact(audit: dict[str, Any], expected: set[str]) -> bool:
    closures = audit.get("final_manifest_closures")
    return (
        isinstance(closures, list)
        and {item.get("manifest_relative_path") for item in closures if isinstance(item, dict)} == expected
    )


def rows_at_offset(rows: list[dict[str, Any]], offset: float) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    try:
        for row in rows:
            if float(row.get("offset", "nan")) == float(offset):
                selected.append(row)
    except (TypeError, ValueError):
        return []
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--acceptance-verdict", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    cfg = read_json(root / args.config)
    output = root / cfg["outputs"]["directory"]
    output.mkdir(parents=True, exist_ok=True)
    acceptance_path, acceptance_path_exact = expected_path(
        root, output, args.acceptance_verdict, cfg["outputs"]["acceptance_verdict"]
    )
    acceptance, _, acceptance_digest_before = stable_json_snapshot(acceptance_path)
    prior_v1_3_attempt = prior_v1_3_attempt_custody_exact(root, cfg)
    frozen = original_authority_hashes(root, cfg)
    stages = cfg["stage_contracts"]
    offsets = cfg["synthetic_contract"]["offsets"]
    expected = len(stages) * len(offsets)
    prerequisites = {
        "run_217C_R3_path_exact": acceptance_path_exact,
        "run_217C_R3_acceptance_exact": (
            acceptance.get("run_id") == cfg["acceptance_run_id"]
            and acceptance.get("smoke_acceptance_freeze_pass") is True
            and acceptance.get("matrix_execution_authorized") is True
            and acceptance.get("scientific_execution_authorized") is False
        ),
        "run_217C_R3_files_exact": files_exact(root, acceptance.get("files", {})),
        "failed_v1_3_R3_custody_exact_before_matrix": (
            prior_v1_3_attempt.get("pass") is True
        ),
        "failed_v1_3_R3_custody_matches_acceptance": (
            acceptance.get("prior_v1_3_attempt_custody", {}).get("bundle_version")
            == cfg["prior_v1_3_attempt_custody"]["bundle_version"]
            and acceptance.get("prior_v1_3_attempt_custody", {}).get("bundle_sha256")
            == cfg["prior_v1_3_attempt_custody"]["bundle_sha256"]
            and acceptance.get("prior_v1_3_attempt_custody", {}).get("disposition")
            == cfg["prior_v1_3_attempt_custody"]["disposition"]
            and acceptance.get("prior_v1_3_attempt_custody", {}).get("artifacts")
            == cfg["prior_v1_3_attempt_custody"]["artifacts"]
            and acceptance.get("prior_v1_3_attempt_custody", {}).get("verification")
            == prior_v1_3_attempt
        ),
        "twenty_invocations_predeclared": len(stages) == 4 and len(offsets) == 5 and expected == 20,
        "offsets_unique_and_baseline_present": len({float(value) for value in offsets}) == 5 and float(cfg["synthetic_contract"]["baseline_offset"]) in {float(value) for value in offsets},
        "full_matrix_authorized_only_after_acceptance": cfg["execution_authorizations"]["execute_full_exact_stage_matrix_only_after_smoke_acceptance"] is True,
        "SIMBA_science_closed": cfg["execution_authorizations"]["SIMBA_scientific_payload"] is False,
    }

    rows: list[dict[str, Any]] = []
    metrics: dict[tuple[str, float], dict[str, Any]] = {}
    audits: list[dict[str, Any]] = []
    hold_reason: str | None = None
    if not all(prerequisites.values()):
        failed = next(name for name, passed in prerequisites.items() if not passed)
        hold_reason = f"run_218_prerequisite_hold:{failed}"
    else:
        for offset_value in offsets:
            offset = float(offset_value)
            try:
                offset_rows, offset_metrics, audit = run_offset(root, output, cfg, offset, stages)
            except Exception as error:  # fail closed and retain only sanitized exception class/message
                hold_reason = f"shadow_construction_hold:offset_{offset}:{type(error).__name__}:{str(error)[:1000]}"
                break
            audit = dict(audit)
            audit["source_authorities_unchanged_after_offset"] = authorities_unchanged(root, frozen)
            rows.extend(offset_rows)
            metrics.update(offset_metrics)
            audits.append({"offset": offset, **audit})
            failed_row = next((row for row in offset_rows if not row_success(row)), None)
            if failed_row is not None:
                hold_reason = f"exact_stage_matrix_lifecycle_hold:{failed_row.get('stage', 'unknown')}:offset_{offset}"
                break
            if len(offset_rows) != len(stages):
                hold_reason = f"exact_stage_matrix_incomplete:offset_{offset}"
                break
            expected_manifest_paths = {stage["manifest"] for stage in stages}
            if not audit_exact(audits[-1], cfg, root, offset_rows) or not audit_manifest_paths_exact(audits[-1], expected_manifest_paths):
                hold_reason = f"runtime_manifest_binding_or_provenance_hold:offset_{offset}"
                break

    stage_order = [stage["stage"] for stage in stages]
    rows_by_offset = {
        float(offset): [row.get("stage") for row in rows_at_offset(rows, float(offset))]
        for offset in offsets
    }
    all_rows_exact = len(rows) == expected and all(row_success(row) for row in rows)
    offsets_and_order_exact = all(rows_by_offset[float(offset)] == stage_order for offset in offsets)
    stage_contracts_by_name = {stage["stage"]: stage for stage in stages}
    row_authorities_exact = len(rows) == expected and all(
        row.get("stage") in stage_contracts_by_name
        and row_authority_exact(row, stage_contracts_by_name[row["stage"]])
        for row in rows
    )
    expected_manifest_paths = {stage["manifest"] for stage in stages}
    audit_row_pairs = [
        (audit, rows_at_offset(rows, float(offset)))
        for audit, offset in zip(audits, offsets)
    ]
    source_resolution_pass = len(audits) == len(offsets) and all(
        source_authority_receipt_exact(audit, cfg, root)
        for audit, _ in audit_row_pairs
    )
    construction_runtime_receipts_pass = len(audits) == len(offsets) and all(
        construction_and_runtime_receipts_exact(audit, cfg, root)
        for audit, _ in audit_row_pairs
    )
    translated_closure_pass = len(audits) == len(offsets) and all(
        isinstance(audit.get("runtime_product_binding_receipts"), list)
        and len(audit["runtime_product_binding_receipts"]) == 1
        and translated_shadow_closures_exact(
            audit,
            cfg,
            audit["runtime_product_binding_receipts"][0],
        )
        for audit, _ in audit_row_pairs
    )
    config_provenance_pass = construction_runtime_receipts_pass and all(
        shadow_config_provenance_exact(audit, cfg, offset_rows)
        for audit, offset_rows in audit_row_pairs
    )
    invocation_provenance_pass = len(audits) == len(offsets) and all(
        offset_provenance_exact(audit, cfg, offset_rows)
        for audit, offset_rows in audit_row_pairs
    )
    audits_exact = len(audits) == len(offsets) and all(
        audit_exact(audit, cfg, root, offset_rows)
        and audit_manifest_paths_exact(audit, expected_manifest_paths)
        for audit, offset_rows in audit_row_pairs
    )
    acceptance_digest_stable = acceptance_path.is_file() and sha256(acceptance_path) == acceptance_digest_before
    authorities_stable = authorities_unchanged(root, frozen)
    matrix_complete = all_rows_exact and offsets_and_order_exact and row_authorities_exact and audits_exact and acceptance_digest_stable and authorities_stable
    if not matrix_complete and hold_reason is None:
        hold_reason = "run_218_incomplete_or_nonconcordant_lifecycle_hold"

    invariance: dict[str, bool] = {}
    baseline_offset = float(cfg["synthetic_contract"]["baseline_offset"])
    if matrix_complete:
        for stage in stages:
            name = stage["stage"]
            baseline = metrics[(name, baseline_offset)]["observables"]
            invariance[name] = all(
                observables_equal(
                    baseline,
                    metrics[(name, float(offset))]["observables"],
                    float(cfg["synthetic_contract"]["absolute_tolerance"]),
                    float(cfg["synthetic_contract"]["relative_tolerance"]),
                )
                for offset in offsets
            )
    for row in rows:
        if row.get("stage") in invariance:
            row["numeric_and_categorical_invariant"] = invariance[row["stage"]]
    candidate_resolved = matrix_complete and bool(invariance) and all(invariance.values())
    candidate_rejected = matrix_complete and bool(invariance) and not all(invariance.values())
    successful = sum(row_success(row) for row in rows)
    receipt_count = sum(
        len(audit.get("runtime_product_binding_receipts", []))
        for audit in audits
        if isinstance(audit.get("runtime_product_binding_receipts"), list)
    )
    outputs_fresh_exact = len(rows) == expected and all(row.get("expected_output_fresh_exact") is True for row in rows)
    full_closure_pass = bool(
        translated_closure_pass
        and len(rows) == expected
        and all(
            row.get("executor_manifest_closure_pass") is True
            and row.get("all_shadow_manifests_closure_pass") is True
            and row.get("manifest_byte_invariance_pass") is True
            for row in rows
        )
    )
    provenance_pass = len(audits) == len(offsets) and all(
        audit.get("manifest_provenance_chain_pass") is True
        and audit.get("runtime_binding_provenance_chain_pass") is True
        for audit in audits
    ) and invocation_provenance_pass
    prior_v1_3_attempt_after = prior_v1_3_attempt_custody_exact(root, cfg)
    checks = {
        **prerequisites,
        "acceptance_verdict_digest_stable_during_run": acceptance_digest_stable,
        "exactly_twenty_invocations_attempted_and_successful": len(rows) == successful == expected == 20,
        "all_expected_stage_verdicts_fresh_exact": outputs_fresh_exact,
        "all_executor_manifests_full_closure": full_closure_pass,
        "one_passing_runtime_binding_receipt_per_offset": audits_exact,
        "manifest_provenance_chain_exact_each_offset": provenance_pass,
        "source_authority_resolution_receipt_independently_exact_each_offset": source_resolution_pass,
        "historical_source_manifest_discordance_preserved_not_called_closed": source_resolution_pass,
        "construction_and_runtime_receipts_independently_exact_each_offset": construction_runtime_receipts_pass,
        "shadow_config_digests_bound_to_construction_receipts_each_offset": config_provenance_pass,
        "translated_shadow_manifest_closure_independently_exact_each_offset": translated_closure_pass,
        "stage_order_exact_each_offset": offsets_and_order_exact,
        "executor_and_config_authorities_exact_each_invocation": row_authorities_exact,
        "historical_authorities_unchanged": authorities_stable,
        "failed_v1_3_R3_custody_exact_after_matrix": (
            prior_v1_3_attempt_after.get("pass") is True
            and prior_v1_3_attempt_after == prior_v1_3_attempt
        ),
        "temporary_shadows_removed": not any(output.glob("bh_simba_shadow_repair_*")) and not any(output.glob("bh_simba_shadow_recovery_*")),
        "complete_matrix_has_exactly_one_sensitivity_outcome": (
            matrix_complete and (candidate_resolved ^ candidate_rejected)
        ),
        "raw_SIMBA_values_not_supplied_or_authorized": (
            cfg["execution_authorizations"].get("raw_SIMBA_values") is False
        ),
        "real_SIMBA_scientific_data_and_memory_inference_not_authorized": all(
            cfg["execution_authorizations"].get(key) is False
            for key in (
                "SIMBA_scientific_payload", "SIMBA_coordinate", "SIMBA_tracks",
                "zero_policy", "SIMBA_adapter", "scientific_memory_generator_execution",
            )
        ),
    }
    process_pass = matrix_complete and all(checks.values())
    resolved = process_pass and candidate_resolved
    rejected = process_pass and candidate_rejected
    interface_hold = not process_pass
    if not process_pass and hold_reason is None:
        failed = next(name for name, value in checks.items() if value is not True)
        hold_reason = f"run_218_acceptance_hold:{failed}"
    results = output / cfg["outputs"]["matrix_results"]
    write_csv(results, rows, csv_fields(rows))
    disposition = (
        "synthetic_tested_latent_signal_offset_invariance_resolved" if process_pass and resolved
        else "synthetic_tested_latent_signal_offset_invariance_rejected" if process_pass and rejected
        else "synthetic_interface_hold_no_scientific_inference"
    )
    observable_evidence = [
        {
            "offset": float(offset),
            "stage": stage["stage"],
            **metrics[(stage["stage"], float(offset))],
        }
        for offset in offsets
        for stage in stages
        if (stage["stage"], float(offset)) in metrics
    ]
    verdict = {
        "schema_version": 2,
        "run_id": cfg["matrix_run_id"],
        "generated_utc": utc_now(),
        "acceptance_verdict_sha256": acceptance_digest_before,
        "predecessor_verdicts": {
            "acceptance_run_id": acceptance.get("run_id"),
            "acceptance_verdict_sha256": acceptance_digest_before,
        },
        "prior_v1_3_attempt_custody": {
            "bundle_version": cfg["prior_v1_3_attempt_custody"]["bundle_version"],
            "bundle_sha256": cfg["prior_v1_3_attempt_custody"]["bundle_sha256"],
            "disposition": cfg["prior_v1_3_attempt_custody"]["disposition"],
            "artifacts": cfg["prior_v1_3_attempt_custody"]["artifacts"],
            "verification": prior_v1_3_attempt_after,
        },
        "checks": checks,
        "matrix_process_pass": process_pass,
        "matrix_complete": matrix_complete,
        "disposition": disposition,
        "interface_hold": interface_hold,
        "hold_reason": None if process_pass else hold_reason,
        "expected_stage_invocations": expected,
        "attempted_stage_invocations": len(rows),
        "successful_stage_invocations": successful,
        "all_four_stages_executed_at_all_offsets": matrix_complete,
        "all_expected_outputs_fresh_exact": outputs_fresh_exact,
        "full_manifest_closure_pass": full_closure_pass,
        "runtime_binding_receipt_count": receipt_count,
        "runtime_binding_receipts_pass": construction_runtime_receipts_pass,
        "runtime_binding_provenance_chain_pass": provenance_pass,
        "historical_source_manifest_concordance_claimed": False,
        "historical_source_manifest_discordance_preserved": source_resolution_pass,
        "translated_shadow_manifest_closure_pass": translated_closure_pass,
        "construction_and_runtime_receipts_independently_exact": construction_runtime_receipts_pass,
        "shadow_config_provenance_exact": config_provenance_pass,
        "stage_invariance": invariance if process_pass else {},
        "observable_evidence": observable_evidence if process_pass else [],
        "observable_evidence_sha256": (
            canonical_json_sha256(observable_evidence) if process_pass else ""
        ),
        "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved": resolved,
        "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected": rejected,
        "selected_output_admission_tested_synthetic_shift_axis_closed": process_pass and (resolved ^ rejected),
        "synthetic_only_result": process_pass,
        "negative_memory_result": False,
        "scientific_execution_authorized": False,
        "shadow_audits": audits,
        "artifacts": {results.name: {"sha256": sha256(results)}},
        "next_gate": "adjudicate_synthetic_translation_result_independently" if process_pass else "hold_run_218_and_repair_first_exact_lifecycle_failure",
        "claim_cap": cfg["claim_cap"],
    }
    atomic_json(output / cfg["outputs"]["matrix_verdict"], verdict)
    print(json.dumps(verdict, indent=2))
    return 0 if process_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
