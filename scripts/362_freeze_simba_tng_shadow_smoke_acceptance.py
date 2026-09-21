#!/usr/bin/env python3
"""Freeze the current v1.4 lifecycle smoke; authorize the matrix only on full acceptance."""

from __future__ import annotations

import argparse
import csv
import json
import re
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
)
from bh_simba_shadow_exact_binding_source_state_lifecycle_recovery_v1_4 import (
    construction_audit_exact,
    runtime_binding_receipt_exact,
    safe_relative,
    stage_output_evidence_exact,
    source_authority_resolution_exact,
)


HEX64 = re.compile(r"[0-9a-f]{64}")


def exact_artifacts(output: Path, item: dict[str, Any]) -> bool:
    records = item.get("artifacts", {})
    return bool(records) and all(
        (output / name).is_file()
        and not (output / name).is_symlink()
        and sha256(output / name) == record.get("sha256")
        for name, record in records.items()
    )


def artifact_exact(root: Path, relative: str, expected: str) -> bool:
    path = root / safe_relative(relative)
    return path.is_file() and not path.is_symlink() and sha256(path) == expected


def canonical_argument(path: str, expected: Path) -> bool:
    return Path(path).resolve() == expected.resolve()


def source_authority_receipt_exact(
    audit: Any,
    cfg: dict[str, Any],
    source_root: Path,
) -> bool:
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


def smoke_csv_provenance_exact(
    rows: Any,
    audit: Any,
    cfg: dict[str, Any],
    receipt: Any,
    source_root: Path,
) -> bool:
    if not isinstance(rows, list) or not isinstance(audit, dict) or not isinstance(receipt, dict):
        return False
    stages = cfg["stage_contracts"]
    if len(rows) != len(stages) or [row.get("stage") for row in rows] != [stage["stage"] for stage in stages]:
        return False
    rows_by_stage = {row["stage"]: row for row in rows}
    if len(rows_by_stage) != len(stages):
        return False
    config_by_path = {
        item.get("relative_path"): item
        for item in audit.get("construction_config_mutation_receipts", [])
        if isinstance(item, dict)
    }
    manifest_by_path = {
        item.get("relative_path"): item
        for item in audit.get("construction_manifest_mutation_receipts", [])
        if isinstance(item, dict)
    }
    closures_by_path = {
        item.get("manifest_relative_path"): item
        for item in audit.get("final_manifest_closures", [])
        if isinstance(item, dict)
    }
    binding = cfg["runtime_binding"]
    producer = rows_by_stage.get(binding["producer_stage"], {})
    consumers = binding["consumer_stages"]
    baseline = float(cfg["synthetic_contract"]["baseline_offset"])
    try:
        offsets_exact = all(float(row.get("offset", "nan")) == baseline for row in rows)
    except (TypeError, ValueError):
        return False
    evidence = audit.get("stage_output_evidence")
    evidence_by_stage = {
        item.get("stage"): item
        for item in evidence
        if isinstance(item, dict)
    } if isinstance(evidence, list) else {}
    lifecycle_and_output_evidence_exact = bool(
        stage_output_evidence_exact(audit, cfg, source_root)
        and len(evidence_by_stage) == len(stages)
        and all(
            row.get("return_code") == "0"
            and row.get("executor_invoked") == "True"
            and row.get("stage_executed") == "True"
            and row.get("expected_output_fresh_exact") == "True"
            and row.get("stage_verdict_fresh") == "True"
            and row.get("stage_verdict_run_id_exact") == "True"
            and row.get("required_verdict_keys_pass") == "True"
            and row.get("required_truthy_keys_pass") == "True"
            and row.get("stage_lifecycle_pass") == "True"
            and row.get("classified_interface_hold") == "False"
            and row.get("stage_verdict_sha256")
            == evidence_by_stage[row["stage"]].get("stage_verdict_sha256")
            and row.get("shadow_config_sha256")
            == evidence_by_stage[row["stage"]].get("shadow_config_sha256")
            and row.get("invocation_manifest_sha256")
            == evidence_by_stage[row["stage"]].get("invocation_manifest_sha256")
            for row in rows
        )
        and evidence_by_stage[binding["producer_stage"]].get(
            "stage_verdict_payload_b64"
        ) == receipt.get("product_payload_b64")
    )
    if audit.get("post_stage_generated_bindings_complete") is True:
        post = audit.get("post_stage_generated_binding_receipts", [])
        by = {item.get("producer_stage"): item for item in post if isinstance(item, dict)} if isinstance(post, list) else {}
        screen_binding = by.get("generator3_null_screen", {}); confirm_binding = by.get("generator3_null_confirmation_2000", {})
        chain_exact = bool(len(by)==2 and rows_by_stage.get(consumers[0],{}).get("invocation_manifest_sha256")==receipt.get("shared_manifest_after_sha256") and screen_binding.get("target_manifest_before_sha256")==receipt.get("confirmation_manifest_after_sha256") and rows_by_stage.get(consumers[1],{}).get("invocation_manifest_sha256")==screen_binding.get("target_manifest_after_sha256") and rows_by_stage.get("generator4_pooled_innovation_screen",{}).get("invocation_manifest_sha256")==confirm_binding.get("target_manifest_after_sha256"))
        nonruntime_exact = True
    else:
        chain_exact = (rows_by_stage.get(consumers[0], {}).get("invocation_manifest_sha256") == receipt.get("shared_manifest_after_sha256") and rows_by_stage.get(consumers[1], {}).get("invocation_manifest_sha256") == receipt.get("confirmation_manifest_after_sha256"))
        nonruntime_exact = all(rows_by_stage[stage["stage"]].get("invocation_manifest_sha256") == manifest_by_path.get(stage["manifest"], {}).get("after_sha256") == closures_by_path.get(stage["manifest"], {}).get("manifest_sha256") for stage in stages if stage["stage"] not in {binding["producer_stage"], *consumers})
    return bool(
        offsets_exact and lifecycle_and_output_evidence_exact
        and producer.get("runtime_binding_receipt_sha256") == receipt.get("receipt_sha256")
        and producer.get("stage_verdict_sha256") == receipt.get("target_sha256") == receipt.get("product_sha256")
        and producer.get("invocation_manifest_sha256") == receipt.get("producer_invocation_manifest_sha256") == receipt.get("shared_manifest_before_sha256")
        and chain_exact
        and all(rows_by_stage[stage["stage"]].get("shadow_config_sha256") == config_by_path.get(stage["config"], {}).get("after_sha256") for stage in stages)
        and nonruntime_exact
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--design-verdict", required=True)
    parser.add_argument("--preflight-verdict", required=True)
    parser.add_argument("--smoke-verdict", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    cfg = read_json(root / args.config)
    output = root / safe_relative(cfg["outputs"]["directory"])
    design_path = output / cfg["outputs"]["design_verdict"]
    preflight_path = output / cfg["outputs"]["preflight_verdict"]
    smoke_path = output / cfg["outputs"]["smoke_verdict"]
    design, _, design_digest = stable_json_snapshot(Path(args.design_verdict))
    preflight, _, preflight_digest = stable_json_snapshot(Path(args.preflight_verdict))
    smoke, _, smoke_digest = stable_json_snapshot(Path(args.smoke_verdict))
    audit = smoke.get("shadow_audit", {})
    receipts = audit.get("runtime_product_binding_receipts", []) if isinstance(audit, dict) else []
    receipt = receipts[0] if isinstance(receipts, list) and len(receipts) == 1 else {}
    try:
        smoke_rows, _, smoke_results_digest = stable_csv_snapshot(
            output / cfg["outputs"]["smoke_results"]
        )
    except (OSError, UnicodeError, csv.Error):
        smoke_rows = []
        smoke_results_digest = ""
    source_resolution_exact = source_authority_receipt_exact(audit, cfg, root)
    runtime_receipt_independently_exact = bool(
        isinstance(receipt, dict)
        and runtime_binding_receipt_exact(receipt, cfg, root)
    )
    construction_audit_independently_exact = bool(
        runtime_receipt_independently_exact
        and construction_audit_exact(audit, cfg, receipt, root)
    )
    translated_closure_exact = translated_shadow_closures_exact(audit, cfg, receipt)
    smoke_provenance_exact = bool(
        construction_audit_independently_exact
        and translated_closure_exact
        and smoke_csv_provenance_exact(smoke_rows, audit, cfg, receipt, root)
    )
    failed_spec = cfg["failed_run_217A"]
    prior_v1_3_attempt = prior_v1_3_attempt_custody_exact(root, cfg)
    current_release_authority = release_field_authority(root, cfg.get("release_field_authority"))
    frozen_release_authority = design.get("prior_release_field_authority")
    release_authority_chain_exact = (
        current_release_authority is not None
        and frozen_release_authority == current_release_authority
    )
    accepted_files = {
        str((output / cfg["outputs"]["design_inventory"]).relative_to(root)): design["artifacts"][cfg["outputs"]["design_inventory"]],
        str((output / cfg["outputs"]["preflight_evidence"]).relative_to(root)): preflight["artifacts"][cfg["outputs"]["preflight_evidence"]],
        str((output / cfg["outputs"]["smoke_results"]).relative_to(root)): smoke["artifacts"][cfg["outputs"]["smoke_results"]],
    }
    v1_3_custody_file_collision_free = True
    configured_v1_3_custody = cfg.get("prior_v1_3_attempt_custody", {}).get(
        "artifacts"
    )
    if not isinstance(configured_v1_3_custody, dict) or len(configured_v1_3_custody) != 2:
        v1_3_custody_file_collision_free = False
    else:
        for name, record in configured_v1_3_custody.items():
            if name in accepted_files:
                v1_3_custody_file_collision_free = False
            accepted_files[name] = record
    release_file_collision_free = True
    if current_release_authority is not None:
        authority_files = {
            current_release_authority["path"]: {"sha256": current_release_authority["sha256"]},
            **current_release_authority["files"],
        }
        for name, record in authority_files.items():
            if name in accepted_files:
                release_file_collision_free = False
            accepted_files[name] = record
    checks = {
        "current_predecessor_paths_exact": all((
            canonical_argument(args.design_verdict, design_path),
            canonical_argument(args.preflight_verdict, preflight_path),
            canonical_argument(args.smoke_verdict, smoke_path),
        )),
        "current_design_id_digest_and_pass_exact": (
            design.get("run_id") == cfg["cli_repair_design_run_id"]
            and design.get("lifecycle_repair_design_freeze_pass") is True
            and preflight.get("predecessor_verdicts", {}).get("design_verdict_sha256") == design_digest
            and smoke.get("predecessor_verdicts", {}).get("design_verdict_sha256") == design_digest
        ),
        "current_preflight_id_digest_and_pass_exact": (
            preflight.get("run_id") == cfg["manifest_preflight_run_id"]
            and preflight.get("runtime_manifest_preflight_pass") is True
            and smoke.get("predecessor_verdicts", {}).get("preflight_verdict_sha256") == preflight_digest
        ),
        "current_smoke_id_and_pass_exact": (
            smoke.get("run_id") == cfg["smoke_run_id"]
            and smoke.get("sequential_smoke_pass") is True
            and smoke.get("smoke_process_pass") is True
        ),
        "all_current_upstream_artifacts_exact": all(exact_artifacts(output, item) for item in (design, preflight, smoke)),
        "smoke_csv_semantics_and_digest_from_one_stable_snapshot": (
            smoke_results_digest
            == smoke.get("artifacts", {})
            .get(cfg["outputs"]["smoke_results"], {})
            .get("sha256")
        ),
        "all_predecessor_claim_caps_exact": design.get("claim_cap") == preflight.get("claim_cap") == smoke.get("claim_cap") == cfg["claim_cap"],
        "historical_failed_217A_verdict_still_exact": artifact_exact(root, failed_spec["verdict"], failed_spec["verdict_sha256"]),
        "historical_failed_217A_evidence_still_exact": artifact_exact(root, failed_spec["evidence"], failed_spec["evidence_sha256"]),
        "failed_v1_3_R3_custody_exact_at_acceptance": (
            prior_v1_3_attempt.get("pass") is True
        ),
        "failed_v1_3_R3_custody_receipts_match_predecessors": (
            preflight.get("failed_v1_3_attempt_custody", {}).get("artifacts")
            == smoke.get("prior_v1_3_attempt_custody", {}).get("artifacts")
            == cfg["prior_v1_3_attempt_custody"]["artifacts"]
            and preflight.get("failed_v1_3_attempt_custody", {}).get("verification")
            == smoke.get("prior_v1_3_attempt_custody", {}).get("verification")
            == prior_v1_3_attempt
        ),
        "failed_v1_3_R3_custody_files_collision_free": (
            v1_3_custody_file_collision_free
        ),
        "exactly_four_invocations_attempted_and_successful": smoke.get("attempted_stage_invocations") == 4 and smoke.get("successful_stage_invocations") == 4,
        "all_four_stages_executed_sequentially": smoke.get("all_four_stages_executed_sequentially") is True,
        "all_four_expected_outputs_fresh_exact": smoke.get("all_expected_outputs_fresh_exact") is True,
        "all_manifest_config_bindings_concordant": smoke.get("all_stage_manifest_config_bindings_concordant") is True,
        "full_executor_manifest_closure_pass": (
            smoke.get("full_manifest_closure_pass") is True
            and translated_closure_exact
        ),
        "exactly_one_runtime_binding_receipt_pass": smoke.get("runtime_binding_receipt_count") == 1 and smoke.get("runtime_binding_receipts_pass") is True,
        "runtime_binding_provenance_chain_pass": (
            smoke.get("runtime_binding_provenance_chain_pass") is True
            and smoke_provenance_exact
        ),
        "source_authority_resolution_receipt_independently_exact": source_resolution_exact,
        "historical_source_manifest_discordance_preserved_not_called_closed": source_resolution_exact,
        "runtime_binding_receipt_independently_exact": runtime_receipt_independently_exact,
        "construction_authority_audit_independently_exact": construction_audit_independently_exact,
        "construction_and_runtime_receipts_independently_exact": bool(
            runtime_receipt_independently_exact
            and construction_audit_independently_exact
        ),
        "translated_shadow_manifest_closure_independently_exact": translated_closure_exact,
        "all_four_stage_output_byte_receipts_independently_exact": (
            stage_output_evidence_exact(audit, cfg, root)
        ),
        "smoke_csv_runtime_manifest_and_config_provenance_exact": smoke_provenance_exact,
        "shadow_config_digests_bound_to_construction_receipts": smoke_provenance_exact,
        "prior_release_field_authority_matches_design_freeze": release_authority_chain_exact,
        "prior_release_field_authority_files_collision_free": release_file_collision_free,
        "no_interface_hold": smoke.get("interface_hold") is False and smoke.get("hold_reason") is None,
        "synthetic_rows_exact": audit.get("synthetic_row_count") == cfg["synthetic_contract"]["track_count"] * cfg["synthetic_contract"]["steps_per_track"],
        "unattested_local_imports_zero": audit.get("unattested_local_import_count") == 0,
        "matrix_authorization_depends_on_current_full_smoke": cfg["execution_authorizations"]["execute_full_exact_stage_matrix_only_after_smoke_acceptance"] is True,
        "scientific_execution_closed": smoke.get("scientific_execution_authorized") is False,
    }
    passed = all(checks.values())
    verdict = {
        "schema_version": 2,
        "run_id": cfg["acceptance_run_id"],
        "generated_utc": utc_now(),
        "checks": checks,
        "smoke_acceptance_freeze_pass": passed,
        "matrix_execution_authorized": passed,
        "smoke_interface_resolved": passed,
        "accepted_predecessor_verdicts": {
            "design_run_id": design.get("run_id"),
            "design_verdict_sha256": design_digest,
            "preflight_run_id": preflight.get("run_id"),
            "preflight_verdict_sha256": preflight_digest,
            "smoke_run_id": smoke.get("run_id"),
            "smoke_verdict_sha256": smoke_digest,
        },
        "accepted_lifecycle_evidence": {
            "stage_invocations": smoke.get("successful_stage_invocations"),
            "fresh_exact_stage_verdicts": 4 if smoke.get("all_expected_outputs_fresh_exact") is True else 0,
            "runtime_binding_receipts": smoke.get("runtime_binding_receipt_count"),
            "full_manifest_closure_pass": translated_closure_exact,
            "runtime_binding_provenance_chain_pass": smoke_provenance_exact,
        },
        "prior_release_field_authority": current_release_authority or {},
        "prior_v1_3_attempt_custody": {
            "bundle_version": cfg["prior_v1_3_attempt_custody"]["bundle_version"],
            "bundle_sha256": cfg["prior_v1_3_attempt_custody"]["bundle_sha256"],
            "disposition": cfg["prior_v1_3_attempt_custody"]["disposition"],
            "artifacts": cfg["prior_v1_3_attempt_custody"]["artifacts"],
            "verification": prior_v1_3_attempt,
        },
        "historical_source_manifest_concordance_claimed": False,
        "historical_source_manifest_discordance_preserved": source_resolution_exact,
        "translated_shadow_manifest_closure_pass": translated_closure_exact,
        "construction_and_runtime_receipts_independently_exact": bool(
            runtime_receipt_independently_exact
            and construction_audit_independently_exact
        ),
        "shadow_config_provenance_exact": smoke_provenance_exact,
        "scientific_design_changed": False,
        "scientific_execution_authorized": False,
        "files": accepted_files,
        "next_gate": "execute_full_twenty_invocation_synthetic_matrix_with_one_binding_receipt_per_shadow" if passed else "hold_smoke_acceptance_and_repair_first_exact_lifecycle_failure",
        "claim_cap": cfg["claim_cap"],
    }
    atomic_json(output / cfg["outputs"]["acceptance_verdict"], verdict)
    print(json.dumps(verdict, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
