#!/usr/bin/env python3
"""Adjudicate only a current, complete Run 218-R3 synthetic matrix."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import re
import tempfile
from pathlib import Path
from typing import Any

from bh_simba_runtime_manifest_common_v1_4 import (
    atomic_json,
    prior_v1_3_attempt_custody_exact,
    read_json,
    release_field_authority,
    sha256,
    stable_csv_snapshot,
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
    safe_relative,
    select_observables_value,
    stage_output_evidence_exact,
    source_authority_resolution_exact,
    strict_json_bytes,
)


HEX64 = re.compile(r"[0-9a-f]{64}")
LIVE_REPLAY_RECEIPT_KEYS = {
    "schema_version", "receipt_kind", "attestation_limit", "run_offset_module",
    "run_offset_module_sha256", "matrix_verdict_sha256",
    "persisted_observable_evidence_sha256", "offsets", "stage_order",
    "fresh_temporary_shadow_count", "expected_stage_invocations",
    "attempted_stage_invocations", "successful_stage_invocations",
    "actual_executor_invoked_rc0_lifecycle_pass_count", "row_receipt_sha256s",
    "offset_audit_sha256s", "replay_audit_sha256", "stage_invariance",
    "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved",
    "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected",
    "construction_runtime_and_closure_predicates_exact",
    "selected_observables_semantically_match_persisted_run_218",
    "source_authorities_unchanged", "live_replay_pass", "hold_reason",
    "receipt_sha256",
}
LIVE_REPLAY_AUDIT_KEYS = {"rows", "metrics", "audits"}


def current_output_path(root: Path, output: Path, supplied: str, filename: str) -> tuple[Path, bool]:
    candidate = root / supplied
    symlink = candidate.is_symlink()
    path = candidate.resolve()
    return path, path == (output / filename).resolve() and path.is_file() and not symlink


def digest_still_exact(path: Path, expected: str) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and sha256(path) == expected
    except (OSError, RuntimeError, ValueError):
        return False


def exact_records(base: Path, records: Any, expected_names: set[str] | None = None) -> bool:
    if not isinstance(records, dict) or not records:
        return False
    if expected_names is not None and set(records) != expected_names:
        return False
    for name, record in records.items():
        expected = record.get("sha256") if isinstance(record, dict) else None
        if not isinstance(name, str) or not isinstance(expected, str) or HEX64.fullmatch(expected) is None:
            return False
        candidate = base / name
        if candidate.is_symlink():
            return False
        try:
            path = candidate.resolve(strict=True)
            path.relative_to(base.resolve())
        except (OSError, RuntimeError, ValueError):
            return False
        if not path.is_file() or sha256(path) != expected:
            return False
    return True


def true_cell(row: dict[str, str], name: str) -> bool:
    return row.get(name) == "True"


def recompute_observable_invariance(
    matrix: dict[str, Any],
    cfg: dict[str, Any],
    output: Path,
    csv_rows: list[dict[str, str]] | None = None,
) -> dict[str, bool] | None:
    """Rebuild every selected observable from the persisted exact verdict bytes."""
    evidence = matrix.get("observable_evidence")
    if not isinstance(evidence, list) or matrix.get("observable_evidence_sha256") != canonical_json_sha256(evidence):
        return None
    expected_pairs = [
        (float(offset), stage["stage"])
        for offset in cfg["synthetic_contract"]["offsets"]
        for stage in cfg["stage_contracts"]
    ]
    if csv_rows is None:
        try:
            csv_rows, _, _ = stable_csv_snapshot(
                output / cfg["outputs"]["matrix_results"]
            )
        except (KeyError, OSError, UnicodeError, csv.Error):
            return None
    rows = csv_rows
    if len(evidence) != len(expected_pairs) or len(rows) != len(expected_pairs):
        return None
    by_pair: dict[tuple[str, float], dict[str, Any]] = {}
    expected_keys = {
        "offset", "stage", "stage_verdict_sha256", "stage_verdict_bytes",
        "stage_verdict_payload_b64", "observables", "observables_sha256",
    }
    for item, row, (offset, stage) in zip(evidence, rows, expected_pairs):
        if not isinstance(item, dict) or set(item) != expected_keys:
            return None
        try:
            payload = base64.b64decode(item["stage_verdict_payload_b64"], validate=True)
        except (TypeError, ValueError):
            return None
        if not (
            item["offset"] == offset
            and item["stage"] == stage
            and row.get("stage") == stage
            and float(row.get("offset", "nan")) == offset
            and isinstance(item["stage_verdict_bytes"], int)
            and not isinstance(item["stage_verdict_bytes"], bool)
            and item["stage_verdict_bytes"] == len(payload) > 0
            and hashlib.sha256(payload).hexdigest()
            == item["stage_verdict_sha256"]
            == row.get("stage_verdict_sha256")
        ):
            return None
        try:
            verdict = strict_json_bytes(payload, f"observable_evidence:{stage}:{offset}")
            selected = select_observables_value(verdict)
            row_count = int(row.get("observable_count", "-1"))
        except (RuntimeError, TypeError, ValueError):
            return None
        if not (
            selected
            and selected == item["observables"]
            and item["observables_sha256"] == canonical_json_sha256(selected)
            and row_count == len(selected)
        ):
            return None
        by_pair[(stage, offset)] = selected
    if len(by_pair) != len(expected_pairs):
        return None
    baseline = float(cfg["synthetic_contract"]["baseline_offset"])
    result: dict[str, bool] = {}
    for stage in [item["stage"] for item in cfg["stage_contracts"]]:
        result[stage] = all(
            observables_equal(
                by_pair[(stage, baseline)],
                by_pair[(stage, float(offset))],
                float(cfg["synthetic_contract"]["absolute_tolerance"]),
                float(cfg["synthetic_contract"]["relative_tolerance"]),
            )
            for offset in cfg["synthetic_contract"]["offsets"]
        )
    return result


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


def matrix_csv_exact(
    output: Path,
    cfg: dict[str, Any],
    matrix: dict[str, Any],
    csv_rows: list[dict[str, str]] | None = None,
) -> bool:
    """Recompute the 20-row lifecycle acceptance from the current matrix CSV."""
    if csv_rows is None:
        try:
            csv_rows, _, _ = stable_csv_snapshot(
                output / cfg["outputs"]["matrix_results"]
            )
        except (KeyError, OSError, UnicodeError, csv.Error):
            return False
    rows = csv_rows
    expected_pairs = [
        (float(offset), stage["stage"])
        for offset in cfg["synthetic_contract"]["offsets"]
        for stage in cfg["stage_contracts"]
    ]
    if len(rows) != 20 or len(expected_pairs) != 20:
        return False
    stage_invariance = matrix.get("stage_invariance") if isinstance(matrix, dict) else None
    if not isinstance(stage_invariance, dict):
        return False
    recomputed_invariance = recompute_observable_invariance(
        matrix, cfg, output, rows
    )
    if recomputed_invariance is None or stage_invariance != recomputed_invariance:
        return False
    stage_contracts = {stage["stage"]: stage for stage in cfg["stage_contracts"]}
    for row, (offset, stage) in zip(rows, expected_pairs):
        try:
            observed_offset = float(row.get("offset", "nan"))
            observable_count = int(row.get("observable_count", "-1"))
            record_count = int(row.get("manifest_file_record_count", "-1"))
            existing_count = int(row.get("manifest_file_existing_count", "-1"))
            match_count = int(row.get("manifest_file_digest_match_count", "-1"))
            required_count = int(row.get("required_input_count", "-1"))
            required_existing = int(row.get("required_input_existing_count", "-1"))
            required_recorded = int(row.get("required_input_manifest_record_count", "-1"))
            required_matched = int(row.get("required_input_digest_match_count", "-1"))
        except (TypeError, ValueError):
            return False
        producer = stage == "generator3_phase_b"
        contract = stage_contracts[stage]
        if not (
            observed_offset == offset
            and row.get("stage") == stage
            and row.get("executor_sha256") == contract["executor_sha256"]
            and row.get("observed_executor_sha256") == contract["executor_sha256"]
            and row.get("authority_config_sha256") == contract["config_sha256"]
            and isinstance(row.get("shadow_config_sha256"), str)
            and HEX64.fullmatch(row["shadow_config_sha256"]) is not None
            and row.get("preinvoke_config_sha256") == row.get("shadow_config_sha256")
            and true_cell(row, "preinvoke_primary_snapshots_exact")
            and row.get("return_code") == "0"
            and true_cell(row, "executor_invoked")
            and true_cell(row, "stage_executed")
            and true_cell(row, "expected_output_fresh_exact")
            and true_cell(row, "stage_verdict_fresh")
            and true_cell(row, "stage_verdict_run_id_exact")
            and true_cell(row, "required_verdict_keys_pass")
            and true_cell(row, "required_truthy_keys_pass")
            and observable_count > 0
            and row.get("classified_interface_hold") == "False"
            and row.get("shadow_config_integrity_mutations_before_stage") == "0"
            and row.get("shadow_manifest_integrity_mutations_before_stage") == "0"
            and true_cell(row, "command_contract_exact")
            and true_cell(row, "repo_root_is_explicit_shadow")
            and true_cell(row, "config_path_shadow_relative")
            and true_cell(row, "manifest_path_shadow_relative")
            and true_cell(row, "manifest_config_concordant")
            and true_cell(row, "executor_manifest_closure_pass")
            and true_cell(row, "all_shadow_manifests_closure_pass")
            and true_cell(row, "manifest_byte_invariance_pass")
            and true_cell(row, "stage_lifecycle_pass")
            and true_cell(row, "numeric_and_categorical_invariant") is stage_invariance.get(stage)
            and record_count > 0
            and record_count == existing_count == match_count
            and required_count > 0
            and required_count == required_existing == required_recorded == required_matched
            and true_cell(row, "post_stage_binding_required") is producer
            and true_cell(row, "post_stage_binding_pass")
            and isinstance(row.get("stage_verdict_sha256"), str)
            and HEX64.fullmatch(row["stage_verdict_sha256"]) is not None
            and isinstance(row.get("invocation_manifest_sha256"), str)
            and HEX64.fullmatch(row["invocation_manifest_sha256"]) is not None
            and isinstance(row.get("command_sha256"), str)
            and HEX64.fullmatch(row["command_sha256"]) is not None
            and isinstance(row.get("stdout_sha256"), str)
            and HEX64.fullmatch(row["stdout_sha256"]) is not None
            and isinstance(row.get("stderr_sha256"), str)
            and HEX64.fullmatch(row["stderr_sha256"]) is not None
        ):
            return False
        receipt = row.get("runtime_binding_receipt_sha256", "")
        if producer and HEX64.fullmatch(receipt) is None:
            return False
        if not producer and receipt:
            return False
    return True



def runtime_manifest_mutations_exact(
    receipt: Any,
    cfg: dict[str, Any],
) -> bool:
    """Independently validate the v1 or declared-dependency v2 mutation journal."""
    if not isinstance(receipt, dict):
        return False
    mutations = receipt.get("manifest_mutations")
    if not isinstance(mutations, list):
        return False
    binding = cfg.get("runtime_binding", {})
    if not isinstance(binding, dict):
        return False
    dependency = binding.get("dependency_refresh")
    if dependency is None:
        return len(mutations) == 2
    expected_keys = {
        "schema_version", "child_manifest", "parent_manifest", "record_field",
        "exact_existing_record_only", "derive_after_from_serialized_child_after_bytes",
        "no_size_field_invention", "no_generic_refresh",
    }
    if not (
        binding.get("schema_version") == 2
        and isinstance(dependency, dict)
        and set(dependency) == expected_keys
        and dependency.get("schema_version") == 1
        and dependency.get("record_field") == "sha256"
        and all(dependency.get(name) is True for name in (
            "exact_existing_record_only",
            "derive_after_from_serialized_child_after_bytes",
            "no_size_field_invention",
            "no_generic_refresh",
        ))
        and len(mutations) == 3
    ):
        return False
    child = dependency.get("child_manifest")
    parent = dependency.get("parent_manifest")
    third = mutations[2]
    if not isinstance(child, str) or not isinstance(parent, str) or not isinstance(third, dict):
        return False
    return third == {
        "manifest": parent,
        "before_sha256": receipt.get("confirmation_manifest_before_sha256"),
        "after_sha256": receipt.get("confirmation_manifest_after_sha256"),
        "operation": "refresh_declared_dependency_digest",
        "relative_path": child,
        "field": "sha256",
        "before": receipt.get("shared_manifest_before_sha256"),
        "after": receipt.get("shared_manifest_after_sha256"),
    }

def matrix_audits_exact(
    matrix: dict[str, Any],
    cfg: dict[str, Any],
    output: Path,
    source_root: Path,
    csv_rows: list[dict[str, str]] | None = None,
) -> bool:
    audits = matrix.get("shadow_audits")
    if not isinstance(audits, list) or len(audits) != 5:
        return False
    expected_offsets = [float(value) for value in cfg["synthetic_contract"]["offsets"]]
    binding = cfg["runtime_binding"]
    producer_stage = binding["producer_stage"]
    consumers = binding["consumer_stages"]
    try:
        if csv_rows is None:
            csv_rows, _, _ = stable_csv_snapshot(
                output / cfg["outputs"]["matrix_results"]
            )
        csv_by_pair = {
            (float(row.get("offset", "nan")), row.get("stage")): row
            for row in csv_rows
        }
    except (OSError, UnicodeError, csv.Error, TypeError, ValueError):
        return False
    if len(csv_rows) != 20 or len(csv_by_pair) != 20:
        return False
    observable_evidence = matrix.get("observable_evidence")
    if (
        not isinstance(observable_evidence, list)
        or len(observable_evidence) != 20
        or matrix.get("observable_evidence_sha256")
        != canonical_json_sha256(observable_evidence)
    ):
        return False
    observable_by_pair = {
        (float(item.get("offset", "nan")), item.get("stage")): item
        for item in observable_evidence
        if isinstance(item, dict)
    }
    if len(observable_by_pair) != 20:
        return False
    receipt_digests: list[str] = []
    for audit, offset in zip(audits, expected_offsets):
        if not isinstance(audit, dict):
            return False
        try:
            observed_offset = float(audit.get("offset", "nan"))
        except (TypeError, ValueError):
            return False
        if observed_offset != offset:
            return False
        receipts = audit.get("runtime_product_binding_receipts")
        receipt = receipts[0] if isinstance(receipts, list) and len(receipts) == 1 and isinstance(receipts[0], dict) else {}
        payload = {
            key: value for key, value in receipt.items()
            if key not in {"receipt_sha256", "receipt_payload_sha256"}
        }
        observed_receipt_sha256 = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        closures = audit.get("final_manifest_closures")
        closures_exact = translated_shadow_closures_exact(audit, cfg, receipt)
        closure_by_path = {
            item["manifest_relative_path"]: item
            for item in closures
            if isinstance(item, dict) and isinstance(item.get("manifest_relative_path"), str)
        } if isinstance(closures, list) else {}
        construction_by_path = {
            item.get("relative_path"): item
            for item in audit.get("construction_manifest_mutation_receipts", [])
            if isinstance(item, dict)
        }
        config_by_path = {
            item.get("relative_path"): item
            for item in audit.get("construction_config_mutation_receipts", [])
            if isinstance(item, dict)
        }
        phase = csv_by_pair.get((offset, producer_stage), {})
        screen = csv_by_pair.get((offset, consumers[0]), {})
        confirmation = csv_by_pair.get((offset, consumers[1]), {})
        if audit.get("post_stage_generated_bindings_complete") is True:
            post = audit.get("post_stage_generated_binding_receipts", [])
            post_by = {item.get("producer_stage"): item for item in post if isinstance(item, dict)} if isinstance(post, list) else {}
            screen_binding = post_by.get("generator3_null_screen", {}); confirm_binding = post_by.get("generator3_null_confirmation_2000", {})
            g4 = csv_by_pair.get((offset, "generator4_pooled_innovation_screen"), {})
            csv_provenance_exact = bool(len(post_by)==2 and phase.get("runtime_binding_receipt_sha256")==receipt.get("receipt_sha256") and phase.get("stage_verdict_sha256")==receipt.get("target_sha256")==receipt.get("product_sha256") and phase.get("invocation_manifest_sha256")==receipt.get("producer_invocation_manifest_sha256")==receipt.get("shared_manifest_before_sha256") and screen.get("invocation_manifest_sha256")==receipt.get("shared_manifest_after_sha256") and screen_binding.get("target_manifest_before_sha256")==receipt.get("confirmation_manifest_after_sha256") and confirmation.get("invocation_manifest_sha256")==screen_binding.get("target_manifest_after_sha256") and g4.get("invocation_manifest_sha256")==confirm_binding.get("target_manifest_after_sha256"))
            final_expected = {receipt.get("shared_manifest"): receipt.get("shared_manifest_after_sha256"), receipt.get("confirmation_manifest"): receipt.get("confirmation_manifest_after_sha256")}
            for item in post:
                if isinstance(item,dict): final_expected[item.get("target_manifest_relative_path")]=item.get("target_manifest_after_sha256")
            closure_provenance_exact = all(path in closure_by_path and closure_by_path[path].get("manifest_sha256")==digest for path,digest in final_expected.items() if isinstance(path,str))
            nonruntime_manifest_provenance_exact = True
        else:
            csv_provenance_exact = (phase.get("runtime_binding_receipt_sha256") == receipt.get("receipt_sha256") and phase.get("stage_verdict_sha256") == receipt.get("target_sha256") == receipt.get("product_sha256") and phase.get("invocation_manifest_sha256") == receipt.get("producer_invocation_manifest_sha256") == receipt.get("shared_manifest_before_sha256") and screen.get("invocation_manifest_sha256") == receipt.get("shared_manifest_after_sha256") and confirmation.get("invocation_manifest_sha256") == receipt.get("confirmation_manifest_after_sha256"))
            closure_provenance_exact = (closure_by_path.get(binding["shared_manifest"], {}).get("manifest_sha256") == receipt.get("shared_manifest_after_sha256") and closure_by_path.get(binding["confirmation_manifest"], {}).get("manifest_sha256") == receipt.get("confirmation_manifest_after_sha256"))
            nonruntime_manifest_provenance_exact = all(csv_by_pair.get((offset, stage["stage"]), {}).get("invocation_manifest_sha256") == construction_by_path.get(stage["manifest"], {}).get("after_sha256") == closure_by_path.get(stage["manifest"], {}).get("manifest_sha256") for stage in cfg["stage_contracts"] if stage["stage"] not in {producer_stage, *consumers})
        config_provenance_exact = all(
            csv_by_pair.get((offset, stage["stage"]), {}).get("shadow_config_sha256")
            == config_by_path.get(stage["config"], {}).get("after_sha256")
            for stage in cfg["stage_contracts"]
        )
        stage_evidence = audit.get("stage_output_evidence")
        stage_by_name = {
            item.get("stage"): item
            for item in stage_evidence
            if isinstance(item, dict)
        } if isinstance(stage_evidence, list) else {}
        stage_output_cross_artifact_exact = bool(
            stage_output_evidence_exact(audit, cfg, source_root)
            and len(stage_by_name) == len(cfg["stage_contracts"]) == 4
            and all(
                (
                    csv_by_pair.get((offset, stage["stage"]), {}).get(
                        "stage_verdict_sha256"
                    )
                    == stage_by_name[stage["stage"]].get("stage_verdict_sha256")
                    == observable_by_pair.get((offset, stage["stage"]), {}).get(
                        "stage_verdict_sha256"
                    )
                )
                and csv_by_pair.get((offset, stage["stage"]), {}).get(
                    "invocation_manifest_sha256"
                ) == stage_by_name[stage["stage"]].get("invocation_manifest_sha256")
                and csv_by_pair.get((offset, stage["stage"]), {}).get(
                    "shadow_config_sha256"
                ) == stage_by_name[stage["stage"]].get("shadow_config_sha256")
                and int(
                    csv_by_pair.get((offset, stage["stage"]), {}).get(
                        "observable_count", "-1"
                    )
                ) == len(stage_by_name[stage["stage"]].get("observables", {}))
                and all(
                    stage_by_name[stage["stage"]].get(field)
                    == observable_by_pair.get((offset, stage["stage"]), {}).get(field)
                    for field in (
                        "stage_verdict_sha256", "stage_verdict_bytes",
                        "stage_verdict_payload_b64", "observables",
                        "observables_sha256",
                    )
                )
                for stage in cfg["stage_contracts"]
            )
            and stage_by_name[producer_stage].get("stage_verdict_payload_b64")
            == receipt.get("product_payload_b64")
        )
        if not (
            isinstance(receipts, list)
            and len(receipts) == 1
            and isinstance(receipts[0], dict)
            and audit.get("runtime_binding_receipt_count") == binding["receipt_count_per_shadow"] == 1
            and audit.get("runtime_binding_receipts_pass") is True
            and runtime_binding_receipt_exact(receipt, cfg, source_root)
            and construction_audit_exact(audit, cfg, receipt, source_root)
            and stage_output_cross_artifact_exact
            and source_authority_receipt_exact(audit, cfg, source_root)
            and receipt.get("binding_pass") is True
            and receipt.get("schema_version") == binding["receipt_schema"]["version"] == binding["schema_version"]
            and receipt.get("offset") == offset
            and receipt.get("producer_stage") == producer_stage
            and receipt.get("producer_return_code") == 0
            and receipt.get("product_absent_before_producer") is True
            and receipt.get("product_regular_contained_non_symlink_single_link") is True
            and receipt.get("mutation_scope_exact") is True
            and receipt.get("all_staged_replacements_completed_and_postverified") is True
            and receipt.get("shared_manifest_closure_pass") is True
            and receipt.get("confirmation_manifest_closure_pass") is True
            and receipt.get("downstream_full_manifest_closure_pass") is True
            and receipt.get("downstream_three_of_three_input_concordance_pass") is True
            and receipt.get("downstream_required_input_concordance_count") == len(consumers)
            and receipt.get("downstream_required_input_concordance_pass_count") == len(consumers)
            and all(
                isinstance(receipt.get(name), str) and HEX64.fullmatch(receipt[name]) is not None
                for name in (
                    "source_template_manifest_expected_sha256", "source_template_manifest_observed_sha256",
                    "producer_invocation_manifest_sha256", "shared_manifest_before_sha256",
                    "shared_manifest_after_sha256", "confirmation_manifest_after_sha256",
                    "product_sha256", "target_sha256",
                )
            )
            and receipt.get("source_template_manifest_expected_sha256") == receipt.get("source_template_manifest_observed_sha256")
            and receipt.get("producer_invocation_manifest_sha256") == receipt.get("shared_manifest_before_sha256")
            and receipt.get("product_sha256") == receipt.get("target_sha256")
            and isinstance(receipt.get("product_bytes"), int)
            and not isinstance(receipt.get("product_bytes"), bool)
            and receipt["product_bytes"] > 0
            and receipt.get("product_bytes") == receipt.get("target_bytes")
            and isinstance(receipt.get("manifest_mutations"), list)
            and runtime_manifest_mutations_exact(receipt, cfg)
            and "hold_reason" not in receipt
            and receipt.get("receipt_sha256") == observed_receipt_sha256
            and receipt.get("receipt_payload_sha256") == observed_receipt_sha256
            and closures_exact
            and closure_provenance_exact
            and nonruntime_manifest_provenance_exact
            and config_provenance_exact
            and audit.get("manifest_byte_invariance_pass") is True
            and audit.get("full_manifest_closure_pass") is True
            and audit.get("manifest_provenance_chain_pass") is True
            and audit.get("runtime_binding_provenance_chain_pass") is True
            and csv_provenance_exact
            and audit.get("source_authorities_unchanged") is True
            and audit.get("source_authorities_unchanged_after_offset") is True
            and audit.get("source_authority_resolution_pass") is True
            and audit.get("source_authority_resolution", {}).get(
                "known_prior_first_conflict_resolved_by_primary"
            ) is True
        ):
            return False
        receipt_digests.append(receipt["receipt_sha256"])
    csv_receipts = [
        row.get("runtime_binding_receipt_sha256", "")
        for row in csv_rows
        if row.get("stage") == producer_stage
    ]
    return csv_receipts == receipt_digests


def matrix_receipt_axes_exact(
    matrix: dict[str, Any],
    cfg: dict[str, Any],
    output: Path,
    source_root: Path,
    csv_rows: list[dict[str, str]] | None = None,
) -> dict[str, bool]:
    """Independently revalidate each persisted late-gate receipt axis."""
    axes = {
        "source_authority_resolution_receipts": False,
        "runtime_binding_receipts": False,
        "construction_audits": False,
        "translated_shadow_manifest_closures": False,
        "shadow_config_provenance": False,
    }
    audits = matrix.get("shadow_audits")
    expected_offsets = [float(value) for value in cfg["synthetic_contract"]["offsets"]]
    if not isinstance(audits, list) or len(audits) != len(expected_offsets):
        return axes
    try:
        if csv_rows is None:
            csv_rows, _, _ = stable_csv_snapshot(
                output / cfg["outputs"]["matrix_results"]
            )
        csv_by_pair = {
            (float(row.get("offset", "nan")), row.get("stage")): row
            for row in csv_rows
        }
    except (OSError, UnicodeError, csv.Error, TypeError, ValueError):
        return axes
    expected_row_count = len(expected_offsets) * len(cfg["stage_contracts"])
    if len(csv_rows) != expected_row_count or len(csv_by_pair) != expected_row_count:
        return axes

    source_results: list[bool] = []
    runtime_results: list[bool] = []
    construction_results: list[bool] = []
    closure_results: list[bool] = []
    config_results: list[bool] = []
    for audit, offset in zip(audits, expected_offsets):
        if not isinstance(audit, dict):
            return axes
        try:
            if float(audit.get("offset", "nan")) != offset:
                return axes
        except (TypeError, ValueError):
            return axes
        receipts = audit.get("runtime_product_binding_receipts")
        if not isinstance(receipts, list) or len(receipts) != 1 or not isinstance(receipts[0], dict):
            return axes
        receipt = receipts[0]
        source_results.append(source_authority_receipt_exact(audit, cfg, source_root))
        runtime_results.append(bool(
            audit.get("runtime_binding_receipt_count")
            == cfg["runtime_binding"]["receipt_count_per_shadow"]
            == 1
            and audit.get("runtime_binding_receipts_pass") is True
            and runtime_binding_receipt_exact(receipt, cfg, source_root)
        ))
        construction_results.append(
            construction_audit_exact(audit, cfg, receipt, source_root)
        )
        closure_results.append(
            translated_shadow_closures_exact(audit, cfg, receipt)
        )
        config_by_path = {
            item.get("relative_path"): item
            for item in audit.get("construction_config_mutation_receipts", [])
            if isinstance(item, dict)
        }
        config_results.append(all(
            csv_by_pair.get((offset, stage["stage"]), {}).get("shadow_config_sha256")
            == config_by_path.get(stage["config"], {}).get("after_sha256")
            for stage in cfg["stage_contracts"]
        ))

    axes["source_authority_resolution_receipts"] = all(source_results)
    axes["runtime_binding_receipts"] = all(runtime_results)
    axes["construction_audits"] = all(construction_results)
    axes["translated_shadow_manifest_closures"] = all(closure_results)
    axes["shadow_config_provenance"] = all(config_results)
    return axes


def live_replay_row_exact(
    row: Any,
    stage: dict[str, Any],
    offset: float,
) -> bool:
    """Require one native in-memory row to prove a successful executor lifecycle."""
    if not isinstance(row, dict):
        return False
    producer = stage["stage"] == "generator3_phase_b"
    try:
        observed_offset = float(row.get("offset", "nan"))
    except (TypeError, ValueError):
        return False
    record_count = row.get("manifest_file_record_count")
    required_count = row.get("required_input_count")
    return bool(
        math.isfinite(observed_offset)
        and observed_offset == float(offset)
        and row.get("stage") == stage["stage"]
        and row.get("executor_sha256") == stage["executor_sha256"]
        and row.get("observed_executor_sha256") == stage["executor_sha256"]
        and row.get("authority_config_sha256") == stage["config_sha256"]
        and isinstance(row.get("shadow_config_sha256"), str)
        and HEX64.fullmatch(row["shadow_config_sha256"]) is not None
        and row.get("preinvoke_config_sha256") == row["shadow_config_sha256"]
        and row.get("preinvoke_primary_snapshots_exact") is True
        and row.get("executor_invoked") is True
        and isinstance(row.get("return_code"), int)
        and not isinstance(row.get("return_code"), bool)
        and row.get("return_code") == 0
        and row.get("stage_executed") is True
        and row.get("expected_output_fresh_exact") is True
        and row.get("stage_verdict_fresh") is True
        and row.get("stage_verdict_run_id_exact") is True
        and row.get("required_verdict_keys_pass") is True
        and row.get("required_truthy_keys_pass") is True
        and isinstance(row.get("observable_count"), int)
        and not isinstance(row.get("observable_count"), bool)
        and row["observable_count"] > 0
        and row.get("classified_interface_hold") is False
        and row.get("shadow_config_integrity_mutations_before_stage") == 0
        and row.get("shadow_manifest_integrity_mutations_before_stage") == 0
        and row.get("command_contract_exact") is True
        and row.get("repo_root_is_explicit_shadow") is True
        and row.get("config_path_shadow_relative") is True
        and row.get("manifest_path_shadow_relative") is True
        and row.get("manifest_config_concordant") is True
        and row.get("executor_manifest_closure_pass") is True
        and row.get("all_shadow_manifests_closure_pass") is True
        and row.get("manifest_byte_invariance_pass") is True
        and isinstance(record_count, int)
        and not isinstance(record_count, bool)
        and record_count > 0
        and row.get("manifest_file_existing_count") == record_count
        and row.get("manifest_file_digest_match_count") == record_count
        and isinstance(required_count, int)
        and not isinstance(required_count, bool)
        and required_count == len(stage["required_data_keys"]) > 0
        and row.get("required_input_existing_count") == required_count
        and row.get("required_input_manifest_record_count") == required_count
        and row.get("required_input_digest_match_count") == required_count
        and row.get("post_stage_binding_required") is producer
        and row.get("post_stage_binding_pass") is True
        and row.get("stage_lifecycle_pass") is True
        and isinstance(row.get("stage_verdict_sha256"), str)
        and HEX64.fullmatch(row["stage_verdict_sha256"]) is not None
        and all(
            isinstance(row.get(name), str) and HEX64.fullmatch(row[name]) is not None
            for name in (
                "invocation_manifest_sha256", "command_sha256",
                "stdout_sha256", "stderr_sha256",
            )
        )
        and (
            isinstance(row.get("runtime_binding_receipt_sha256"), str)
            and HEX64.fullmatch(row["runtime_binding_receipt_sha256"]) is not None
            if producer
            else row.get("runtime_binding_receipt_sha256") == ""
        )
    )


def live_replay_audit_exact(
    audit: Any,
    cfg: dict[str, Any],
    source_root: Path,
    offset: float,
    rows: list[dict[str, Any]],
) -> bool:
    """Reconstruct every construction/runtime predicate for one replay shadow."""
    if not isinstance(audit, dict) or len(rows) != len(cfg["stage_contracts"]) == 4:
        return False
    receipts = audit.get("runtime_product_binding_receipts")
    if not (
        isinstance(receipts, list)
        and len(receipts) == cfg["runtime_binding"]["receipt_count_per_shadow"] == 1
        and isinstance(receipts[0], dict)
    ):
        return False
    receipt = receipts[0]
    by_stage = {row.get("stage"): row for row in rows}
    if len(by_stage) != len(rows):
        return False
    config_receipts = {
        item.get("relative_path"): item
        for item in audit.get("construction_config_mutation_receipts", [])
        if isinstance(item, dict)
    }
    producer = cfg["runtime_binding"]["producer_stage"]
    consumers = cfg["runtime_binding"]["consumer_stages"]
    if producer not in by_stage or any(stage not in by_stage for stage in consumers):
        return False
    try:
        observed_offset = float(audit.get("offset", "nan"))
    except (TypeError, ValueError):
        return False
    stage_evidence = {
        item.get("stage"): item
        for item in audit.get("stage_output_evidence", [])
        if isinstance(item, dict)
    }
    return bool(
        math.isfinite(observed_offset)
        and observed_offset == float(offset)
        and audit.get("runtime_binding_receipt_count") == 1
        and audit.get("runtime_binding_receipts_pass") is True
        and runtime_binding_receipt_exact(receipt, cfg, source_root)
        and construction_audit_exact(audit, cfg, receipt, source_root)
        and stage_output_evidence_exact(audit, cfg, source_root)
        and source_authority_receipt_exact(audit, cfg, source_root)
        and translated_shadow_closures_exact(audit, cfg, receipt)
        and audit.get("manifest_byte_invariance_pass") is True
        and audit.get("full_manifest_closure_pass") is True
        and audit.get("manifest_provenance_chain_pass") is True
        and audit.get("runtime_binding_provenance_chain_pass") is True
        and audit.get("source_authorities_unchanged") is True
        and audit.get("source_authorities_unchanged_after_offset") is True
        and receipt.get("binding_pass") is True
        and receipt.get("producer_return_code") == 0
        and by_stage[producer].get("runtime_binding_receipt_sha256")
        == receipt.get("receipt_sha256")
        and by_stage[producer].get("invocation_manifest_sha256")
        == receipt.get("producer_invocation_manifest_sha256")
        and by_stage[consumers[0]].get("invocation_manifest_sha256")
        == receipt.get("shared_manifest_after_sha256")
        and (
            (audit.get("post_stage_generated_bindings_complete") is not True and by_stage[consumers[1]].get("invocation_manifest_sha256") == receipt.get("confirmation_manifest_after_sha256"))
            or (audit.get("post_stage_generated_bindings_complete") is True and len(audit.get("post_stage_generated_binding_receipts", [])) == 2 and by_stage[consumers[1]].get("invocation_manifest_sha256") == next(item["target_manifest_after_sha256"] for item in audit["post_stage_generated_binding_receipts"] if item["producer_stage"] == "generator3_null_screen") and by_stage["generator4_pooled_innovation_screen"].get("invocation_manifest_sha256") == next(item["target_manifest_after_sha256"] for item in audit["post_stage_generated_binding_receipts"] if item["producer_stage"] == "generator3_null_confirmation_2000"))
        )
        and len(stage_evidence) == len(cfg["stage_contracts"])
        and all(
            by_stage[stage["stage"]].get("stage_verdict_sha256")
            == stage_evidence.get(stage["stage"], {}).get("stage_verdict_sha256")
            and by_stage[stage["stage"]].get("invocation_manifest_sha256")
            == stage_evidence.get(stage["stage"], {}).get("invocation_manifest_sha256")
            and by_stage[stage["stage"]].get("shadow_config_sha256")
            == config_receipts.get(stage["config"], {}).get("after_sha256")
            for stage in cfg["stage_contracts"]
        )
    )


def reconstruct_live_replay_audit(
    audit_payload: Any,
    cfg: dict[str, Any],
    matrix: dict[str, Any],
    source_root: Path,
) -> tuple[bool, dict[str, bool], bool]:
    """Rebuild rows, per-shadow audits, metrics, and invariance from full evidence."""
    if not isinstance(audit_payload, dict) or set(audit_payload) != LIVE_REPLAY_AUDIT_KEYS:
        return False, {}, False
    rows = audit_payload.get("rows")
    metrics_list = audit_payload.get("metrics")
    audits = audit_payload.get("audits")
    offsets = [float(value) for value in cfg["synthetic_contract"]["offsets"]]
    stages = cfg["stage_contracts"]
    expected = len(offsets) * len(stages)
    if not (
        isinstance(rows, list) and len(rows) == expected == 20
        and isinstance(metrics_list, list) and len(metrics_list) == expected
        and isinstance(audits, list) and len(audits) == len(offsets) == 5
    ):
        return False, {}, False
    metric_keys = {
        "offset", "stage", "stage_verdict_sha256", "stage_verdict_bytes",
        "stage_verdict_payload_b64", "observables", "observables_sha256",
    }
    metrics: dict[tuple[str, float], dict[str, Any]] = {}
    for index, offset in enumerate(offsets):
        offset_rows = rows[index * len(stages):(index + 1) * len(stages)]
        if not all(
            live_replay_row_exact(row, stage, offset)
            for row, stage in zip(offset_rows, stages)
        ):
            return False, {}, False
        if not live_replay_audit_exact(
            audits[index], cfg, source_root, offset, offset_rows
        ):
            return False, {}, False
        for stage_index, stage in enumerate(stages):
            item = metrics_list[index * len(stages) + stage_index]
            if not isinstance(item, dict) or set(item) != metric_keys:
                return False, {}, False
            try:
                observed_offset = float(item["offset"])
                encoded = item["stage_verdict_payload_b64"]
                payload = base64.b64decode(encoded, validate=True)
                value = strict_json_bytes(
                    payload, f"live_replay_metric:{stage['stage']}:{offset}"
                )
            except (KeyError, RuntimeError, TypeError, ValueError):
                return False, {}, False
            observables = select_observables_value(value)
            row = offset_rows[stage_index]
            if not (
                math.isfinite(observed_offset)
                and observed_offset == offset
                and item["stage"] == stage["stage"]
                and isinstance(encoded, str)
                and base64.b64encode(payload).decode("ascii") == encoded
                and isinstance(item["stage_verdict_bytes"], int)
                and not isinstance(item["stage_verdict_bytes"], bool)
                and item["stage_verdict_bytes"] == len(payload) > 0
                and item["stage_verdict_sha256"]
                == hashlib.sha256(payload).hexdigest()
                == row["stage_verdict_sha256"]
                and item["observables"] == observables
                and bool(observables)
                and item["observables_sha256"] == canonical_json_sha256(observables)
                and row["observable_count"] == len(observables)
            ):
                return False, {}, False
            metrics[(stage["stage"], offset)] = item
    if len(metrics) != expected:
        return False, {}, False

    baseline = float(cfg["synthetic_contract"]["baseline_offset"])
    invariance: dict[str, bool] = {}
    for stage in stages:
        name = stage["stage"]
        invariance[name] = all(
            observables_equal(
                metrics[(name, baseline)]["observables"],
                metrics[(name, offset)]["observables"],
                float(cfg["synthetic_contract"]["absolute_tolerance"]),
                float(cfg["synthetic_contract"]["relative_tolerance"]),
            )
            for offset in offsets
        )
    try:
        persisted = {
            (item["stage"], float(item["offset"])): item["observables"]
            for item in matrix["observable_evidence"]
            if isinstance(item, dict)
        }
    except (KeyError, TypeError, ValueError):
        return False, {}, False
    semantic_match = bool(
        len(persisted) == expected
        and invariance == matrix.get("stage_invariance")
        and all(
            isinstance(persisted.get((stage["stage"], offset)), dict)
            and observables_equal(
                metrics[(stage["stage"], offset)]["observables"],
                persisted[(stage["stage"], offset)],
                float(cfg["synthetic_contract"]["absolute_tolerance"]),
                float(cfg["synthetic_contract"]["relative_tolerance"]),
            )
            for offset in offsets
            for stage in stages
        )
    )
    return semantic_match, invariance, semantic_match


def live_replay_receipt_exact(
    adjudication: Any,
    cfg: dict[str, Any],
    matrix: dict[str, Any],
    source_root: Path,
) -> bool:
    """Validate the embedded replay receipt; this is not adversarial attestation."""
    if not isinstance(adjudication, dict):
        return False
    receipt = adjudication.get("live_replay_receipt")
    if not isinstance(receipt, dict) or set(receipt) != LIVE_REPLAY_RECEIPT_KEYS:
        return False
    audit_payload = adjudication.get("live_replay_audit")
    if not isinstance(audit_payload, dict) or set(audit_payload) != LIVE_REPLAY_AUDIT_KEYS:
        return False
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    expected = len(cfg["stage_contracts"]) * len(cfg["synthetic_contract"]["offsets"])
    replay_cfg = cfg.get("adjudication_live_replay", {})
    stage_names = [stage["stage"] for stage in cfg["stage_contracts"]]
    matrix_invariance = matrix.get("stage_invariance")
    current_module_exact = False
    try:
        module_relative = safe_relative(receipt.get("run_offset_module"))
        source_root_resolved = source_root.resolve(strict=True)
        module_candidate = source_root / module_relative
        if module_candidate.is_symlink():
            raise RuntimeError("live_replay_verifier_module_symlink")
        module_path = module_candidate.resolve(strict=True)
        module_path.relative_to(source_root_resolved)
        current_module_exact = bool(
            module_path.is_file()
            and sha256(module_path) == receipt.get("run_offset_module_sha256")
            == replay_cfg.get("run_offset_module_sha256")
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        current_module_exact = False
    replay_audit_exact, reconstructed_invariance, semantic_match = (
        reconstruct_live_replay_audit(
            audit_payload, cfg, matrix, source_root
        )
    )
    return bool(
        receipt.get("receipt_sha256") == canonical_json_sha256(payload)
        and adjudication.get("live_replay_receipt_sha256") == receipt["receipt_sha256"]
        and adjudication.get("live_replay_audit_sha256") == receipt.get("replay_audit_sha256")
        and receipt.get("replay_audit_sha256") == canonical_json_sha256(audit_payload)
        and replay_audit_exact
        and adjudication.get("live_replay_attestation_limit")
        == receipt.get("attestation_limit")
        and receipt.get("schema_version") == replay_cfg.get("schema_version") == 1
        and receipt.get("receipt_kind") == "honest_code_independent_full_live_replay"
        and receipt.get("attestation_limit")
        == replay_cfg.get("attestation_limit")
        == "integrity_and_honest_code_execution_evidence_not_adversarial_process_attestation"
        and receipt.get("run_offset_module") == replay_cfg.get("run_offset_module")
        and receipt.get("run_offset_module_sha256") == replay_cfg.get("run_offset_module_sha256")
        and current_module_exact
        and isinstance(receipt.get("run_offset_module_sha256"), str)
        and HEX64.fullmatch(receipt["run_offset_module_sha256"]) is not None
        and receipt.get("matrix_verdict_sha256") == adjudication.get("matrix_verdict_sha256")
        and receipt.get("persisted_observable_evidence_sha256")
        == matrix.get("observable_evidence_sha256")
        and receipt.get("offsets")
        == [float(value) for value in cfg["synthetic_contract"]["offsets"]]
        and receipt.get("stage_order") == stage_names
        and receipt.get("fresh_temporary_shadow_count")
        == replay_cfg.get("expected_fresh_temporary_shadows")
        == len(cfg["synthetic_contract"]["offsets"]) == 5
        and receipt.get("expected_stage_invocations") == expected == 20
        and replay_cfg.get("expected_actual_executor_invocations") == expected
        and receipt.get("attempted_stage_invocations") == expected
        and receipt.get("successful_stage_invocations") == expected
        and receipt.get("actual_executor_invoked_rc0_lifecycle_pass_count") == expected
        and isinstance(receipt.get("row_receipt_sha256s"), list)
        and len(receipt["row_receipt_sha256s"]) == expected
        and all(isinstance(value, str) and HEX64.fullmatch(value) for value in receipt["row_receipt_sha256s"])
        and receipt["row_receipt_sha256s"]
        == [canonical_json_sha256(row) for row in audit_payload["rows"]]
        and isinstance(receipt.get("offset_audit_sha256s"), list)
        and len(receipt["offset_audit_sha256s"]) == 5
        and all(isinstance(value, str) and HEX64.fullmatch(value) for value in receipt["offset_audit_sha256s"])
        and receipt["offset_audit_sha256s"]
        == [canonical_json_sha256(audit) for audit in audit_payload["audits"]]
        and isinstance(receipt.get("replay_audit_sha256"), str)
        and HEX64.fullmatch(receipt["replay_audit_sha256"]) is not None
        and isinstance(receipt.get("stage_invariance"), dict)
        and set(receipt["stage_invariance"]) == set(stage_names)
        and all(isinstance(value, bool) for value in receipt["stage_invariance"].values())
        and receipt.get("stage_invariance") == matrix_invariance
        and receipt.get("stage_invariance") == reconstructed_invariance
        and receipt.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved")
        is matrix.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved")
        and receipt.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected")
        is matrix.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected")
        and isinstance(
            receipt.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved"), bool
        )
        and isinstance(
            receipt.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected"), bool
        )
        and (
            receipt["selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved"]
            ^ receipt["selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected"]
        )
        and receipt.get("construction_runtime_and_closure_predicates_exact") is True
        and receipt.get("selected_observables_semantically_match_persisted_run_218") is True
        and semantic_match
        and receipt.get("source_authorities_unchanged") is True
        and receipt.get("live_replay_pass") is True
        and receipt.get("hold_reason") is None
        and adjudication.get("live_replay_pass") is True
    )


def execute_live_replay(
    root: Path,
    cfg: dict[str, Any],
    matrix: dict[str, Any],
    matrix_digest: str,
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    """Actually replay 4x5 executor processes in new shadows before adjudication.

    The hash pin and receipts are strong honest-code integrity evidence.  They do
    not provide adversarial process attestation: an attacker able to rewrite the
    running interpreter and every unsigned authority remains outside this claim.
    """
    replay_cfg = cfg.get("adjudication_live_replay", {})
    offsets = [float(value) for value in cfg["synthetic_contract"]["offsets"]]
    stages = cfg["stage_contracts"]
    stage_order = [stage["stage"] for stage in stages]
    expected = len(offsets) * len(stages)
    rows: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    metrics: dict[tuple[str, float], dict[str, Any]] = {}
    hold_reason: str | None = None
    module_relative = replay_cfg.get("run_offset_module")
    module_expected_sha = replay_cfg.get("run_offset_module_sha256")
    module_exact = False
    frozen: dict[str, str] = {}
    try:
        if not isinstance(module_relative, str) or not isinstance(module_expected_sha, str):
            raise RuntimeError("live_replay_run_offset_pin_missing")
        module_path = (root / module_relative)
        if module_path.is_symlink():
            raise RuntimeError("live_replay_run_offset_module_symlink")
        resolved_module = module_path.resolve(strict=True)
        resolved_module.relative_to(root.resolve(strict=True))
        module_exact = resolved_module.is_file() and sha256(resolved_module) == module_expected_sha
        if not module_exact:
            raise RuntimeError("live_replay_run_offset_module_digest_mismatch")
        frozen = original_authority_hashes(root, cfg)
        with tempfile.TemporaryDirectory(prefix="bh_simba_adjudication_live_replay_") as temporary:
            replay_output = Path(temporary) / "replay-output"
            for offset in offsets:
                offset_rows, offset_metrics, audit = run_offset(
                    root, replay_output, cfg, offset, stages
                )
                audit = dict(audit)
                audit["source_authorities_unchanged_after_offset"] = authorities_unchanged(root, frozen)
                rows.extend(offset_rows)
                metrics.update(offset_metrics)
                audits.append(audit)
                if len(offset_rows) != len(stages):
                    raise RuntimeError(f"live_replay_incomplete_offset:{offset}")
                if not all(
                    live_replay_row_exact(row, stage, offset)
                    for row, stage in zip(offset_rows, stages)
                ):
                    raise RuntimeError(f"live_replay_row_lifecycle_hold:{offset}")
                if not live_replay_audit_exact(audit, cfg, root, offset, offset_rows):
                    raise RuntimeError(f"live_replay_construction_runtime_audit_hold:{offset}")
        module_exact = sha256(resolved_module) == module_expected_sha
        if not module_exact:
            raise RuntimeError("live_replay_run_offset_module_changed_during_replay")
    except Exception as error:
        hold_reason = f"{type(error).__name__}:{str(error)[:1000]}"

    replay_invariance: dict[str, bool] = {}
    persisted_by_pair = {
        (item.get("stage"), float(item.get("offset", "nan"))): item.get("observables")
        for item in matrix.get("observable_evidence", [])
        if isinstance(item, dict)
    }
    semantic_match = len(persisted_by_pair) == expected
    if len(rows) == expected and len(metrics) == expected:
        baseline = float(cfg["synthetic_contract"]["baseline_offset"])
        for stage in stages:
            name = stage["stage"]
            replay_invariance[name] = all(
                observables_equal(
                    metrics[(name, baseline)]["observables"],
                    metrics[(name, offset)]["observables"],
                    float(cfg["synthetic_contract"]["absolute_tolerance"]),
                    float(cfg["synthetic_contract"]["relative_tolerance"]),
                )
                for offset in offsets
            )
            semantic_match = semantic_match and all(
                isinstance(persisted_by_pair.get((name, offset)), dict)
                and observables_equal(
                    metrics[(name, offset)]["observables"],
                    persisted_by_pair[(name, offset)],
                    float(cfg["synthetic_contract"]["absolute_tolerance"]),
                    float(cfg["synthetic_contract"]["relative_tolerance"]),
                )
                for offset in offsets
            )
    else:
        semantic_match = False

    successful = sum(
        live_replay_row_exact(row, stage, offset)
        for index, offset in enumerate(offsets)
        for stage, row in zip(
            stages,
            rows[index * len(stages):(index + 1) * len(stages)],
        )
    ) if len(rows) == expected else 0
    predicates_exact = bool(
        len(audits) == len(offsets)
        and len(rows) == expected
        and all(
            live_replay_audit_exact(
                audit, cfg, root, offset,
                rows[index * len(stages):(index + 1) * len(stages)],
            )
            for index, (audit, offset) in enumerate(zip(audits, offsets))
        )
    )
    replay_resolved = bool(replay_invariance) and all(replay_invariance.values())
    replay_rejected = bool(replay_invariance) and not all(replay_invariance.values())
    matrix_outcome_match = bool(
        replay_invariance == matrix.get("stage_invariance")
        and replay_resolved
        is (matrix.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved") is True)
        and replay_rejected
        is (matrix.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected") is True)
    )
    source_stable = bool(frozen and authorities_unchanged(root, frozen))
    passed = bool(
        hold_reason is None
        and module_exact
        and expected == 20
        and len(rows) == successful == expected
        and predicates_exact
        and semantic_match
        and matrix_outcome_match
        and source_stable
        and (replay_resolved ^ replay_rejected)
    )
    if not passed and hold_reason is None:
        hold_reason = "live_replay_incomplete_nonconcordant_or_semantically_divergent"
    audit_payload = {
        "rows": rows,
        "metrics": [
            {"offset": offset, "stage": stage["stage"], **metrics[(stage["stage"], offset)]}
            for offset in offsets
            for stage in stages
            if (stage["stage"], offset) in metrics
        ],
        "audits": audits,
    }
    audit_sha = canonical_json_sha256(audit_payload)
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_kind": "honest_code_independent_full_live_replay",
        "attestation_limit": "integrity_and_honest_code_execution_evidence_not_adversarial_process_attestation",
        "run_offset_module": module_relative,
        "run_offset_module_sha256": module_expected_sha,
        "matrix_verdict_sha256": matrix_digest,
        "persisted_observable_evidence_sha256": matrix.get("observable_evidence_sha256", ""),
        "offsets": offsets,
        "stage_order": stage_order,
        "fresh_temporary_shadow_count": len(audits),
        "expected_stage_invocations": expected,
        "attempted_stage_invocations": len(rows),
        "successful_stage_invocations": successful,
        "actual_executor_invoked_rc0_lifecycle_pass_count": successful,
        "row_receipt_sha256s": [canonical_json_sha256(row) for row in rows],
        "offset_audit_sha256s": [canonical_json_sha256(audit) for audit in audits],
        "replay_audit_sha256": audit_sha,
        "stage_invariance": replay_invariance,
        "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved": replay_resolved,
        "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected": replay_rejected,
        "construction_runtime_and_closure_predicates_exact": predicates_exact,
        "selected_observables_semantically_match_persisted_run_218": semantic_match and matrix_outcome_match,
        "source_authorities_unchanged": source_stable,
        "live_replay_pass": passed,
        "hold_reason": None if passed else hold_reason,
    }
    receipt["receipt_sha256"] = canonical_json_sha256(receipt)
    return passed, receipt, audit_payload


def held_live_replay_receipt(
    cfg: dict[str, Any],
    matrix: dict[str, Any],
    matrix_digest: str,
    hold_reason: str,
) -> dict[str, Any]:
    """Create the canonical zero-execution receipt for a prerequisite hold."""
    replay_cfg = cfg.get("adjudication_live_replay", {})
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_kind": "honest_code_independent_full_live_replay",
        "attestation_limit": "integrity_and_honest_code_execution_evidence_not_adversarial_process_attestation",
        "run_offset_module": replay_cfg.get("run_offset_module"),
        "run_offset_module_sha256": replay_cfg.get("run_offset_module_sha256"),
        "matrix_verdict_sha256": matrix_digest,
        "persisted_observable_evidence_sha256": matrix.get("observable_evidence_sha256", ""),
        "offsets": [float(value) for value in cfg["synthetic_contract"]["offsets"]],
        "stage_order": [stage["stage"] for stage in cfg["stage_contracts"]],
        "fresh_temporary_shadow_count": 0,
        "expected_stage_invocations": (
            len(cfg["synthetic_contract"]["offsets"]) * len(cfg["stage_contracts"])
        ),
        "attempted_stage_invocations": 0,
        "successful_stage_invocations": 0,
        "actual_executor_invoked_rc0_lifecycle_pass_count": 0,
        "row_receipt_sha256s": [],
        "offset_audit_sha256s": [],
        "replay_audit_sha256": canonical_json_sha256(
            {"rows": [], "metrics": [], "audits": []}
        ),
        "stage_invariance": {},
        "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved": False,
        "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected": False,
        "construction_runtime_and_closure_predicates_exact": False,
        "selected_observables_semantically_match_persisted_run_218": False,
        "source_authorities_unchanged": False,
        "live_replay_pass": False,
        "hold_reason": hold_reason,
    }
    receipt["receipt_sha256"] = canonical_json_sha256(receipt)
    return receipt


def execute_live_replay_only_after_prechecks(
    root: Path,
    cfg: dict[str, Any],
    matrix: dict[str, Any],
    matrix_digest: str,
    pre_replay_checks: dict[str, bool],
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    """Never construct a replay shadow or invoke Popen before every precheck passes."""
    failed = [name for name, value in pre_replay_checks.items() if value is not True]
    if failed:
        receipt = held_live_replay_receipt(
            cfg, matrix, matrix_digest,
            f"live_replay_not_authorized_failed_prerequisite:{failed[0]}",
        )
        return False, receipt, {"rows": [], "metrics": [], "audits": []}
    return execute_live_replay(root, cfg, matrix, matrix_digest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--acceptance-verdict", required=True)
    parser.add_argument("--matrix-verdict", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    cfg = read_json(root / args.config)
    output = root / cfg["outputs"]["directory"]
    output.mkdir(parents=True, exist_ok=True)
    acceptance_path, acceptance_path_exact = current_output_path(
        root, output, args.acceptance_verdict, cfg["outputs"]["acceptance_verdict"]
    )
    matrix_path, matrix_path_exact = current_output_path(
        root, output, args.matrix_verdict, cfg["outputs"]["matrix_verdict"]
    )
    acceptance, _, acceptance_digest = stable_json_snapshot(acceptance_path)
    matrix, _, matrix_digest = stable_json_snapshot(matrix_path)
    prior_v1_3_attempt = prior_v1_3_attempt_custody_exact(root, cfg)
    try:
        matrix_csv_rows, _, matrix_csv_digest = stable_csv_snapshot(
            output / cfg["outputs"]["matrix_results"]
        )
    except (KeyError, OSError, UnicodeError, csv.Error):
        matrix_csv_rows = []
        matrix_csv_digest = ""
    current_release_authority = release_field_authority(root, cfg.get("release_field_authority"))
    frozen_release_authority = acceptance.get("prior_release_field_authority")
    frozen_authority_files = {}
    if (
        isinstance(frozen_release_authority, dict)
        and isinstance(frozen_release_authority.get("path"), str)
        and isinstance(frozen_release_authority.get("sha256"), str)
        and isinstance(frozen_release_authority.get("files"), dict)
    ):
        frozen_authority_files = {
            frozen_release_authority["path"]: {"sha256": frozen_release_authority["sha256"]},
            **frozen_release_authority["files"],
        }
    acceptance_files = acceptance.get("files")
    release_authority_chain_exact = (
        current_release_authority is not None
        and frozen_release_authority == current_release_authority
        and isinstance(acceptance_files, dict)
        and bool(frozen_authority_files)
        and all(acceptance_files.get(name) == record for name, record in frozen_authority_files.items())
    )
    expected = len(cfg["stage_contracts"]) * len(cfg["synthetic_contract"]["offsets"])

    matrix_declares_resolved = matrix.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved") is True
    matrix_declares_rejected = matrix.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected") is True
    stage_names = [stage["stage"] for stage in cfg["stage_contracts"]]
    stage_invariance = matrix.get("stage_invariance")
    recomputed_stage_invariance = recompute_observable_invariance(
        matrix, cfg, output, matrix_csv_rows
    )
    sensitivity_internally_exact = (
        isinstance(stage_invariance, dict)
        and recomputed_stage_invariance is not None
        and stage_invariance == recomputed_stage_invariance
        and set(stage_invariance) == set(stage_names)
        and all(isinstance(value, bool) for value in stage_invariance.values())
        and matrix_declares_resolved is all(stage_invariance.values())
        and matrix_declares_rejected is (not all(stage_invariance.values()))
    )
    matrix_counts_exact = (
        expected == 20
        and matrix.get("expected_stage_invocations") == expected
        and matrix.get("attempted_stage_invocations") == expected
        and matrix.get("successful_stage_invocations") == expected
    )
    matrix_complete = (
        matrix.get("matrix_complete") is True
        and matrix.get("all_four_stages_executed_at_all_offsets") is True
        and matrix.get("matrix_process_pass") is True
        and matrix.get("interface_hold") is False
        and matrix.get("hold_reason") is None
        and matrix_counts_exact
    )
    exact_one_matrix_outcome = matrix_declares_resolved ^ matrix_declares_rejected
    receipt_axes = matrix_receipt_axes_exact(
        matrix, cfg, output, root, matrix_csv_rows
    )
    construction_runtime_receipts_exact = bool(
        receipt_axes["runtime_binding_receipts"]
        and receipt_axes["construction_audits"]
    )
    matrix_audit_verification_exact = matrix_audits_exact(
        matrix, cfg, output, root, matrix_csv_rows
    )
    pre_replay_checks = {
        "run_217C_R3_path_and_verdict_exact": (
            acceptance_path_exact
            and acceptance.get("run_id") == cfg["acceptance_run_id"]
            and acceptance.get("smoke_acceptance_freeze_pass") is True
            and acceptance.get("matrix_execution_authorized") is True
            and acceptance.get("scientific_execution_authorized") is False
        ),
        "run_217C_R3_frozen_files_exact": exact_records(root, acceptance.get("files")),
        "run_218_R3_path_and_verdict_exact": matrix_path_exact and matrix.get("run_id") == cfg["matrix_run_id"],
        "run_218_bound_to_current_217C_digest": matrix.get("acceptance_verdict_sha256") == acceptance_digest,
        "run_218_current_matrix_artifact_exact": exact_records(
            output,
            matrix.get("artifacts"),
            {cfg["outputs"]["matrix_results"]},
        ),
        "failed_v1_3_R3_custody_exact_before_live_replay": (
            prior_v1_3_attempt.get("pass") is True
        ),
        "failed_v1_3_R3_custody_matches_acceptance_and_matrix": (
            acceptance.get("prior_v1_3_attempt_custody", {}).get("artifacts")
            == matrix.get("prior_v1_3_attempt_custody", {}).get("artifacts")
            == cfg["prior_v1_3_attempt_custody"]["artifacts"]
            and acceptance.get("prior_v1_3_attempt_custody", {}).get("verification")
            == matrix.get("prior_v1_3_attempt_custody", {}).get("verification")
            == prior_v1_3_attempt
        ),
        "run_218_matrix_csv_semantics_and_digest_from_one_stable_snapshot": (
            matrix_csv_digest
            == matrix.get("artifacts", {})
            .get(cfg["outputs"]["matrix_results"], {})
            .get("sha256")
        ),
        "run_218_current_matrix_csv_recomputes_twenty_exact_lifecycles": matrix_csv_exact(
            output, cfg, matrix, matrix_csv_rows
        ),
        "run_218_observable_maps_and_invariance_independently_recomputed": (
            recomputed_stage_invariance == stage_invariance
            and recomputed_stage_invariance is not None
        ),
        "run_218_five_runtime_binding_audits_exact": matrix_audit_verification_exact,
        "run_218_source_authority_resolution_receipts_independently_exact": receipt_axes["source_authority_resolution_receipts"],
        "run_218_historical_source_manifest_discordance_preserved_not_called_closed": receipt_axes["source_authority_resolution_receipts"],
        "run_218_runtime_binding_receipts_independently_exact": receipt_axes["runtime_binding_receipts"],
        "run_218_construction_audits_independently_exact": receipt_axes["construction_audits"],
        "run_218_construction_and_runtime_receipts_independently_exact": construction_runtime_receipts_exact,
        "run_218_shadow_config_digests_bound_to_construction_receipts": (
            construction_runtime_receipts_exact
            and receipt_axes["shadow_config_provenance"]
        ),
        "run_218_translated_shadow_manifest_closures_independently_exact": receipt_axes["translated_shadow_manifest_closures"],
        "run_218_expected_attempted_successful_exactly_twenty": matrix_counts_exact,
        "run_218_matrix_complete_without_interface_hold": matrix_complete,
        "run_218_exactly_one_sensitivity_outcome": matrix_complete and exact_one_matrix_outcome and sensitivity_internally_exact,
        "run_218_runtime_binding_and_closure_checks_pass": (
            matrix.get("checks", {}).get("one_passing_runtime_binding_receipt_per_offset") is True
            and matrix.get("checks", {}).get("all_executor_manifests_full_closure") is True
            and matrix.get("checks", {}).get("manifest_provenance_chain_exact_each_offset") is True
            and matrix.get("checks", {}).get("all_expected_stage_verdicts_fresh_exact") is True
            and matrix.get("checks", {}).get("historical_authorities_unchanged") is True
            and matrix.get("checks", {}).get("source_authority_resolution_receipt_independently_exact_each_offset") is True
            and matrix.get("checks", {}).get("historical_source_manifest_discordance_preserved_not_called_closed") is True
            and matrix.get("checks", {}).get("construction_and_runtime_receipts_independently_exact_each_offset") is True
            and matrix.get("checks", {}).get("shadow_config_digests_bound_to_construction_receipts_each_offset") is True
            and matrix.get("checks", {}).get("translated_shadow_manifest_closure_independently_exact_each_offset") is True
            and matrix.get("historical_source_manifest_concordance_claimed") is False
            and matrix.get("historical_source_manifest_discordance_preserved") is True
            and matrix.get("translated_shadow_manifest_closure_pass") is True
            and matrix.get("construction_and_runtime_receipts_independently_exact") is True
            and matrix.get("shadow_config_provenance_exact") is True
        ),
        "prior_release_field_authority_chain_exact": release_authority_chain_exact,
        "release_storage_identity_preserved": (
            release_authority_chain_exact
            and current_release_authority["exact_expected_bondi_storage_field_resolved"] is True
        ),
        "storage_identity_separate_from_physical_semantics": (
            release_authority_chain_exact
            and current_release_authority["expected_bondi_physical_semantics_resolved"] is False
        ),
        "synthetic_result_separate_from_memory_result": matrix.get("negative_memory_result") is False,
        "scientific_execution_closed": matrix.get("scientific_execution_authorized") is False,
        "claim_cap_exact": matrix.get("claim_cap") == cfg["claim_cap"],
    }
    (
        live_replay_pass,
        live_replay_receipt,
        live_replay_audit,
    ) = execute_live_replay_only_after_prechecks(
        root, cfg, matrix, matrix_digest, pre_replay_checks
    )
    prior_v1_3_attempt_after = prior_v1_3_attempt_custody_exact(root, cfg)
    checks = {
        **pre_replay_checks,
        "run_219_all_non_replay_prerequisites_pass_before_live_replay": all(
            pre_replay_checks.values()
        ),
        "run_219_current_acceptance_and_matrix_bytes_stable_during_live_replay": (
            live_replay_pass
            and digest_still_exact(acceptance_path, acceptance_digest)
            and digest_still_exact(matrix_path, matrix_digest)
        ),
        "failed_v1_3_R3_custody_exact_after_live_replay": (
            prior_v1_3_attempt_after.get("pass") is True
            and prior_v1_3_attempt_after == prior_v1_3_attempt
        ),
        "run_219_hash_pinned_run_offset_module_exact": (
            live_replay_receipt.get("run_offset_module_sha256")
            == cfg.get("adjudication_live_replay", {}).get("run_offset_module_sha256")
            and isinstance(live_replay_receipt.get("run_offset_module_sha256"), str)
            and HEX64.fullmatch(live_replay_receipt["run_offset_module_sha256"])
            is not None
        ),
        "run_219_independent_full_live_replay_exactly_twenty_executor_lifecycles": (
            live_replay_pass
            and live_replay_receipt.get("expected_stage_invocations") == 20
            and live_replay_receipt.get("attempted_stage_invocations") == 20
            and live_replay_receipt.get("successful_stage_invocations") == 20
            and live_replay_receipt.get(
                "actual_executor_invoked_rc0_lifecycle_pass_count"
            ) == 20
        ),
        "run_219_live_replay_construction_runtime_and_closure_predicates_exact": (
            live_replay_pass
            and live_replay_receipt.get(
                "construction_runtime_and_closure_predicates_exact"
            ) is True
        ),
        "run_219_live_replay_observables_and_outcome_match_persisted_run_218": (
            live_replay_pass
            and live_replay_receipt.get(
                "selected_observables_semantically_match_persisted_run_218"
            ) is True
            and live_replay_receipt.get("stage_invariance") == stage_invariance
        ),
    }
    passed = all(checks.values())
    # A sensitivity outcome is admissible only after every current-matrix check passes.
    resolved = passed and matrix_declares_resolved and not matrix_declares_rejected
    rejected = passed and matrix_declares_rejected and not matrix_declares_resolved
    sensitivity_closed = passed and (resolved ^ rejected)
    evidence = [
        {"axis": "release_storage_identity", "resolved": checks["release_storage_identity_preserved"], "claim_allowed": "exact_Mdot_bondi_storage_identity" if checks["release_storage_identity_preserved"] else "none", "claim_prohibited": "physical_Bondi_semantics_or_writer_assignment"},
        {"axis": "historical_source_manifest_authority", "resolved": receipt_axes["source_authority_resolution_receipts"], "claim_allowed": "primary_authority_selection_with_preserved_historical_manifest_discordance" if receipt_axes["source_authority_resolution_receipts"] else "none", "claim_prohibited": "historical_source_manifest_concordance_or_closure"},
        {"axis": "translated_shadow_manifest_closure", "resolved": receipt_axes["translated_shadow_manifest_closures"], "claim_allowed": "translated_ephemeral_shadow_manifest_closure" if receipt_axes["translated_shadow_manifest_closures"] else "none", "claim_prohibited": "historical_source_manifest_concordance"},
        {"axis": "construction_runtime_and_config_provenance", "resolved": construction_runtime_receipts_exact and receipt_axes["shadow_config_provenance"], "claim_allowed": "receipt_reconstruction_and_shadow_config_digest_binding" if construction_runtime_receipts_exact and receipt_axes["shadow_config_provenance"] else "none", "claim_prohibited": "unreceipted_shadow_mutation"},
        {"axis": "zero_offset_four_stage_interface", "resolved": passed and acceptance.get("smoke_interface_resolved") is True, "claim_allowed": "synthetic_exact_stage_chain_interface" if passed else "none", "claim_prohibited": "SIMBA_adapter_or_memory_result"},
        {"axis": "twenty_invocation_matrix", "resolved": passed, "claim_allowed": "synthetic_exact_stage_chain_matrix" if passed else "none", "claim_prohibited": "SIMBA_scientific_execution"},
        {"axis": "honest_code_independent_live_replay", "resolved": live_replay_pass and passed, "claim_allowed": "second_4_by_5_hash_pinned_executor_lifecycle_replay" if live_replay_pass and passed else "none", "claim_prohibited": "adversarial_process_attestation"},
        {"axis": "tested_latent_signal_offset_invariance", "resolved": resolved, "claim_allowed": "selected_observables_and_admission_decisions_invariant_under_five_tested_latent_signal_offsets" if resolved else "none", "claim_prohibited": "uniform_coordinate_translation_physical_units_or_black_hole_memory_result"},
        {"axis": "tested_latent_signal_offset_sensitivity", "resolved": rejected, "claim_allowed": "selected_observables_or_admission_decisions_sensitive_to_at_least_one_tested_latent_signal_offset" if rejected else "none", "claim_prohibited": "physical_unit_response_or_negative_memory_result"},
        {"axis": "physical_units", "resolved": False, "claim_allowed": "none", "claim_prohibited": "physical_coordinate_construction_or_unit_scale"},
        {"axis": "physical_unit_sensitivity", "resolved": False, "claim_allowed": "none", "claim_prohibited": "physical_unit_response_or_conversion"},
        {"axis": "real_unit_transformation", "resolved": False, "claim_allowed": "none", "claim_prohibited": "real_transform_is_one_additive_shift_or_claimed_offset_magnitude"},
        {"axis": "writer_semantics", "resolved": False, "claim_allowed": "none", "claim_prohibited": "exact_writer_assignment_or_physical_Bondi_semantics"},
        {"axis": "population_equivalence", "resolved": False, "claim_allowed": "none", "claim_prohibited": "TNG_SIMBA_sample_equivalence"},
        {"axis": "SIMBA_coordinates", "resolved": False, "claim_allowed": "none", "claim_prohibited": "SIMBA_coordinate_execution"},
        {"axis": "SIMBA_tracks_and_zero_policy", "resolved": False, "claim_allowed": "none", "claim_prohibited": "SIMBA_track_or_zero_policy_execution"},
        {"axis": "SIMBA_adapter", "resolved": False, "claim_allowed": "none", "claim_prohibited": "SIMBA_adapter_execution"},
        {"axis": "scientific_memory", "resolved": False, "claim_allowed": "none", "claim_prohibited": "scientific_generator_execution_or_memory_result"},
    ]
    evidence_path = output / cfg["outputs"]["adjudication_evidence"]
    write_csv(evidence_path, evidence, list(evidence[0]))
    if not passed:
        next_gate = "hold_run_219_until_exact_current_complete_twenty_invocation_matrix"
    elif resolved:
        next_gate = "resolve_exact_writer_physical_semantics_units_and_population_equivalence_before_SIMBA_execution"
    else:
        next_gate = "resolve_physical_units_and_semantics_without_native_unit_fallback_before_SIMBA_execution"
    verdict = {
        "schema_version": 2,
        "run_id": cfg["adjudication_run_id"],
        "generated_utc": utc_now(),
        "acceptance_verdict_sha256": acceptance_digest,
        "matrix_verdict_sha256": matrix_digest,
        "predecessor_verdicts": {
            "acceptance_run_id": acceptance.get("run_id"),
            "acceptance_verdict_sha256": acceptance_digest,
            "matrix_run_id": matrix.get("run_id"),
            "matrix_verdict_sha256": matrix_digest,
        },
        "prior_release_field_authority": current_release_authority or {},
        "provenance": {
            "prior_release_field_authority": current_release_authority or {},
            "prior_v1_3_attempt_custody": {
                "bundle_version": cfg["prior_v1_3_attempt_custody"]["bundle_version"],
                "bundle_sha256": cfg["prior_v1_3_attempt_custody"]["bundle_sha256"],
                "disposition": cfg["prior_v1_3_attempt_custody"]["disposition"],
                "artifacts": cfg["prior_v1_3_attempt_custody"]["artifacts"],
                "verification": prior_v1_3_attempt_after,
            },
        },
        "prior_v1_3_attempt_custody": {
            "bundle_version": cfg["prior_v1_3_attempt_custody"]["bundle_version"],
            "bundle_sha256": cfg["prior_v1_3_attempt_custody"]["bundle_sha256"],
            "disposition": cfg["prior_v1_3_attempt_custody"]["disposition"],
            "artifacts": cfg["prior_v1_3_attempt_custody"]["artifacts"],
            "verification": prior_v1_3_attempt_after,
        },
        "checks": checks,
        "live_replay_pass": live_replay_pass and passed,
        "live_replay_receipt": live_replay_receipt,
        "live_replay_audit": live_replay_audit,
        "live_replay_receipt_sha256": live_replay_receipt["receipt_sha256"],
        "live_replay_audit_sha256": live_replay_receipt["replay_audit_sha256"],
        "live_replay_attestation_limit": live_replay_receipt["attestation_limit"],
        "historical_source_manifest_concordance_claimed": False,
        "historical_source_manifest_discordance_preserved": receipt_axes["source_authority_resolution_receipts"],
        "translated_shadow_manifest_closure_pass": receipt_axes["translated_shadow_manifest_closures"],
        "construction_and_runtime_receipts_independently_exact": construction_runtime_receipts_exact,
        "shadow_config_provenance_exact": bool(
            construction_runtime_receipts_exact
            and receipt_axes["shadow_config_provenance"]
        ),
        "adjudication_pass": passed,
        "disposition": "process_pass_scientific_hold" if passed else "run_219_hold_no_sensitivity_inference",
        "matrix_complete": passed,
        "exact_expected_bondi_storage_field_resolved": checks["release_storage_identity_preserved"],
        "expected_bondi_physical_semantics_resolved": False,
        "physical_units_resolved": False,
        "physical_unit_sensitivity_resolved": False,
        "real_unit_transformation_resolved": False,
        "physical_offset_magnitude_resolved": False,
        "exact_writer_assignment_resolved": False,
        "writer_semantics_resolved": False,
        "synthetic_input_rebinding_interface_resolved": passed,
        "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved": resolved,
        "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected": rejected,
        "selected_output_admission_tested_synthetic_shift_axis_closed": sensitivity_closed,
        "native_unit_coordinate_fallback_authorized": False,
        "population_equivalence_resolved": False,
        "scientific_execution_ready": False,
        "coordinate_execution_authorized": False,
        "track_construction_authorized": False,
        "zero_policy_execution_authorized": False,
        "SIMBA_adapter_execution_authorized": False,
        "scientific_generator_execution_authorized": False,
        "negative_memory_result": False,
        "artifacts": {evidence_path.name: {"sha256": sha256(evidence_path)}},
        "next_gate": next_gate,
        "claim_cap": cfg["claim_cap"],
    }
    atomic_json(output / cfg["outputs"]["adjudication_verdict"], verdict)
    print(json.dumps(verdict, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
