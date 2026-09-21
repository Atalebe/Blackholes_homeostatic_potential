#!/usr/bin/env python3
"""Run the strict four-stage zero-offset smoke with one runtime binding receipt."""

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
    construction_audit_exact,
    original_authority_hashes,
    run_offset,
    runtime_binding_receipt_exact,
    safe_relative,
    stage_output_evidence_exact,
    source_authority_resolution_exact,
)


PREFERRED_FIELDS = [
    "offset", "stage", "executor_sha256", "authority_config_sha256", "shadow_config_sha256",
    "return_code", "executor_invoked", "stage_executed", "expected_output_fresh_exact",
    "stage_verdict_fresh", "stage_verdict_sha256", "observable_count", "stdout_sha256", "stderr_sha256",
    "classified_interface_hold", "numeric_and_categorical_invariant", "command_contract_exact",
    "repo_root_is_explicit_shadow", "config_path_shadow_relative", "manifest_path_shadow_relative",
    "required_input_count", "required_input_existing_count", "required_input_manifest_record_count",
    "required_input_digest_match_count", "manifest_config_concordant", "executor_manifest_closure_pass",
    "manifest_file_record_count", "manifest_file_existing_count", "manifest_file_digest_match_count",
    "post_stage_binding_required", "post_stage_binding_pass", "runtime_binding_receipt_sha256",
    "stage_lifecycle_pass", "invocation_manifest_sha256", "command_sha256", "detail",
]


HEX64 = re.compile(r"[0-9a-f]{64}")


def exact_artifacts(output: Path, item: dict[str, Any]) -> bool:
    records = item.get("artifacts", {})
    return bool(records) and all(
        (output / name).is_file()
        and not (output / name).is_symlink()
        and sha256(output / name) == record.get("sha256")
        for name, record in records.items()
    )


def canonical_argument(path: str, expected: Path) -> bool:
    return Path(path).resolve() == expected.resolve()


def csv_fields(rows: list[dict[str, Any]]) -> list[str]:
    extras = sorted({key for row in rows for key in row} - set(PREFERRED_FIELDS))
    return [key for key in PREFERRED_FIELDS if any(key in row for row in rows)] + extras


def receipt_pass(receipt: dict[str, Any], cfg: dict[str, Any], source_root: Path) -> bool:
    return runtime_binding_receipt_exact(receipt, cfg, source_root)


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
    """Reconcile final translated-shadow closure summaries with their rows."""
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
        if relative not in expected or relative in by_path:
            return False
        rows = item.get("rows")
        auxiliary = item.get("auxiliary_rows")
        if not isinstance(rows, list) or not isinstance(auxiliary, list):
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


def row_provenance_exact(
    rows: Any,
    audit: Any,
    cfg: dict[str, Any],
    receipt: Any,
) -> bool:
    """Bind each invocation to translated manifests and construction-time configs."""
    if audit.get("post_stage_generated_bindings_complete") is True:
        post = audit.get("post_stage_generated_binding_receipts", [])
        if not isinstance(post,list) or len(post)!=2: return False
        by={item.get("producer_stage"):item for item in post if isinstance(item,dict)}
        screen=by.get("generator3_null_screen",{}); confirm=by.get("generator3_null_confirmation_2000",{})
        rows_by_stage={row.get("stage"):row for row in rows if isinstance(row,dict)}
        stages=cfg["stage_contracts"]
        config_by_path={item.get("relative_path"):item for item in audit.get("construction_config_mutation_receipts",[]) if isinstance(item,dict)}
        return bool(len(rows_by_stage)==len(stages) and rows_by_stage["generator3_phase_b"].get("runtime_binding_receipt_sha256")==receipt.get("receipt_sha256") and rows_by_stage["generator3_phase_b"].get("invocation_manifest_sha256")==receipt.get("shared_manifest_before_sha256") and rows_by_stage["generator3_null_screen"].get("invocation_manifest_sha256")==receipt.get("shared_manifest_after_sha256") and screen.get("target_manifest_before_sha256")==receipt.get("confirmation_manifest_after_sha256") and screen.get("target_sha256")==rows_by_stage["generator3_null_screen"].get("stage_verdict_sha256") and rows_by_stage["generator3_null_confirmation_2000"].get("invocation_manifest_sha256")==screen.get("target_manifest_after_sha256") and confirm.get("target_sha256")==rows_by_stage["generator3_null_confirmation_2000"].get("stage_verdict_sha256") and rows_by_stage["generator4_pooled_innovation_screen"].get("invocation_manifest_sha256")==confirm.get("target_manifest_after_sha256") and all(rows_by_stage[stage["stage"]].get("shadow_config_sha256")==config_by_path.get(stage["config"],{}).get("after_sha256") for stage in stages))
    if not isinstance(rows, list) or not isinstance(audit, dict) or not isinstance(receipt, dict):
        return False
    stages = cfg["stage_contracts"]
    if [row.get("stage") for row in rows if isinstance(row, dict)] != [stage["stage"] for stage in stages]:
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
    if not (
        producer.get("runtime_binding_receipt_sha256") == receipt.get("receipt_sha256")
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
        and all(row.get("offset") == receipt.get("offset") for row in rows)
        and all(
            rows_by_stage[stage["stage"]].get("shadow_config_sha256")
            == config_by_path.get(stage["config"], {}).get("after_sha256")
            for stage in stages
        )
        and all(
            rows_by_stage[stage["stage"]].get("invocation_manifest_sha256")
            == manifest_by_path.get(stage["manifest"], {}).get("after_sha256")
            == closures_by_path.get(stage["manifest"], {}).get("manifest_sha256")
            for stage in stages
            if stage["stage"] not in {binding["producer_stage"], *consumers}
        )
    ):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--preflight-verdict", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    cfg = read_json(root / args.config)
    output = root / safe_relative(cfg["outputs"]["directory"])
    design_path = output / cfg["outputs"]["design_verdict"]
    preflight_path = output / cfg["outputs"]["preflight_verdict"]
    design, _, design_digest = stable_json_snapshot(design_path)
    preflight, _, preflight_digest = stable_json_snapshot(Path(args.preflight_verdict))
    prior_v1_3_attempt = prior_v1_3_attempt_custody_exact(root, cfg)
    frozen = original_authority_hashes(root, cfg)
    prerequisites = {
        "current_preflight_path_exact": canonical_argument(args.preflight_verdict, preflight_path),
        "current_design_id_and_digest_exact": (
            design.get("run_id") == cfg["cli_repair_design_run_id"]
            and design.get("lifecycle_repair_design_freeze_pass") is True
            and preflight.get("predecessor_verdicts", {}).get("design_verdict_sha256") == design_digest
        ),
        "current_runtime_preflight_exact": preflight.get("run_id") == cfg["manifest_preflight_run_id"] and preflight.get("runtime_manifest_preflight_pass") is True,
        "current_preflight_artifact_exact": exact_artifacts(output, preflight),
        "failed_v1_3_R3_custody_exact_before_smoke": (
            prior_v1_3_attempt.get("pass") is True
        ),
        "failed_v1_3_R3_custody_matches_preflight": (
            preflight.get("failed_v1_3_attempt_custody", {}).get("bundle_version")
            == cfg["prior_v1_3_attempt_custody"]["bundle_version"]
            and preflight.get("failed_v1_3_attempt_custody", {}).get("bundle_sha256")
            == cfg["prior_v1_3_attempt_custody"]["bundle_sha256"]
            and preflight.get("failed_v1_3_attempt_custody", {}).get("disposition")
            == cfg["prior_v1_3_attempt_custody"]["disposition"]
            and preflight.get("failed_v1_3_attempt_custody", {}).get("artifacts")
            == cfg["prior_v1_3_attempt_custody"]["artifacts"]
            and preflight.get("failed_v1_3_attempt_custody", {}).get("verification")
            == prior_v1_3_attempt
        ),
        "predecessor_claim_caps_exact": design.get("claim_cap") == preflight.get("claim_cap") == cfg["claim_cap"],
        "four_stage_zero_offset_smoke_authorized": cfg["execution_authorizations"]["execute_zero_offset_four_stage_smoke_on_synthetic_only"] is True,
        "four_stage_order_exact": [stage["stage"] for stage in cfg["stage_contracts"]] == [
            "generator3_phase_b", "generator3_null_screen", "generator3_null_confirmation_2000", "generator4_pooled_innovation_screen"
        ],
        "runtime_binding_design_requires_exactly_one_post_producer_receipt": cfg["runtime_binding"].get("receipt_count_per_shadow", 1) == 1,
        "SIMBA_science_closed": cfg["execution_authorizations"]["SIMBA_scientific_payload"] is False,
    }
    rows: list[dict[str, Any]] = []
    audit: dict[str, Any] = {}
    construction_error = None
    if all(prerequisites.values()):
        try:
            rows, _, audit = run_offset(
                root,
                output,
                cfg,
                float(cfg["synthetic_contract"]["baseline_offset"]),
                cfg["stage_contracts"],
            )
        except Exception as error:
            construction_error = f"{type(error).__name__}:{str(error)[:1000]}"
    expected_stages = [stage["stage"] for stage in cfg["stage_contracts"]]
    stage_order_exact = [row.get("stage") for row in rows] == expected_stages
    config_receipts = {
        item.get("relative_path"): item
        for item in audit.get("construction_config_mutation_receipts", [])
        if isinstance(item, dict)
    }
    stage_by_name = {stage["stage"]: stage for stage in cfg["stage_contracts"]}
    stage_success = len(rows) == 4 and stage_order_exact and all(
        row.get("return_code") == 0
        and row.get("executor_invoked") is True
        and row.get("stage_executed") is True
        and row.get("expected_output_fresh_exact") is True
        and row.get("observed_executor_sha256") == row.get("executor_sha256")
        and row.get("preinvoke_config_sha256") == row.get("shadow_config_sha256")
        and row.get("preinvoke_primary_snapshots_exact") is True
        and isinstance(row.get("stage_verdict_sha256"), str)
        and len(row["stage_verdict_sha256"]) == 64
        and row.get("manifest_config_concordant") is True
        and row.get("executor_manifest_closure_pass") is True
        and row.get("manifest_file_record_count", 0) > 0
        and row.get("manifest_file_record_count") == row.get("manifest_file_existing_count") == row.get("manifest_file_digest_match_count")
        and row.get("command_contract_exact") is True
        and row.get("repo_root_is_explicit_shadow") is True
        and row.get("stage_lifecycle_pass") is True
        and row.get("shadow_config_sha256")
        == config_receipts.get(stage_by_name[row["stage"]]["config"], {}).get("after_sha256")
        for row in rows
    )
    receipts = audit.get("runtime_product_binding_receipts", [])
    receipt = receipts[0] if isinstance(receipts, list) and len(receipts) == 1 else {}
    source_resolution_exact = source_authority_receipt_exact(audit, cfg, root)
    construction_receipts_exact = bool(
        isinstance(receipt, dict)
        and receipt_pass(receipt, cfg, root)
        and construction_audit_exact(audit, cfg, receipt, root)
    )
    translated_closure_exact = translated_shadow_closures_exact(audit, cfg, receipt)
    stage_outputs_independently_exact = stage_output_evidence_exact(audit, cfg, root)
    invocation_provenance_exact = bool(
        construction_receipts_exact
        and translated_closure_exact
        and stage_outputs_independently_exact
        and row_provenance_exact(rows, audit, cfg, receipt)
    )
    exactly_one_receipt = (
        isinstance(receipts, list)
        and len(receipts) == 1
        and audit.get("runtime_binding_receipt_count", len(receipts)) == 1
        and construction_receipts_exact
        and receipts[0].get("offset") == float(cfg["synthetic_contract"]["baseline_offset"])
        and audit.get("runtime_binding_receipts_pass") is True
    )
    producer_rows = [row for row in rows if row.get("stage") == "generator3_phase_b"]
    producer_binding_exact = (
        len(producer_rows) == 1
        and producer_rows[0].get("post_stage_binding_required") is True
        and producer_rows[0].get("post_stage_binding_pass") is True
        and isinstance(producer_rows[0].get("runtime_binding_receipt_sha256"), str)
        and producer_rows[0].get("runtime_binding_receipt_sha256")
        == receipts[0].get("receipt_sha256", receipts[0].get("runtime_binding_receipt_sha256"))
        and producer_rows[0].get("stage_verdict_sha256")
        == receipts[0].get("target_sha256")
        == receipts[0].get("product_sha256")
    ) if receipts else False
    no_consumer_rebinding = len(rows) == 4 and all(
        row.get("post_stage_binding_required") is False
        for row in rows[1:]
    )
    full_closure = bool(
        translated_closure_exact
        and audit.get("full_manifest_closure_pass") is True
        and audit.get("manifest_byte_invariance_pass") is True
        and len(rows) == 4
        and all(
            row.get("executor_manifest_closure_pass") is True
            and row.get("all_shadow_manifests_closure_pass") is True
            and row.get("manifest_byte_invariance_pass") is True
            for row in rows
        )
    )
    provenance = (
        audit.get("runtime_binding_provenance_chain_pass") is True
        and audit.get("manifest_provenance_chain_pass") is True
        and invocation_provenance_exact
    )
    fresh_outputs = len(rows) == 4 and all(row.get("expected_output_fresh_exact") is True for row in rows)
    prior_v1_3_attempt_after = prior_v1_3_attempt_custody_exact(root, cfg)
    checks = {
        **prerequisites,
        "shadow_constructed_without_error": construction_error is None,
        "exactly_four_invocations_in_dependency_order": len(rows) == 4 and stage_order_exact,
        "all_four_executors_invoked_and_returned_zero": len(rows) == 4 and all(row.get("executor_invoked") is True and row.get("return_code") == 0 for row in rows),
        "all_four_expected_stage_verdicts_fresh_exact": fresh_outputs,
        "all_four_executor_manifest_closures_exact": full_closure,
        "exactly_one_successful_atomic_runtime_binding_receipt": exactly_one_receipt,
        "producer_stage_owns_only_runtime_binding": producer_binding_exact and no_consumer_rebinding,
        "runtime_manifest_provenance_chain_exact": provenance,
        "source_authority_resolution_receipt_independently_exact": source_resolution_exact,
        "historical_source_manifest_discordance_preserved_not_called_closed": source_resolution_exact,
        "construction_and_runtime_receipts_independently_exact": construction_receipts_exact,
        "shadow_config_digests_bound_to_construction_receipts": invocation_provenance_exact,
        "translated_shadow_invocation_manifest_closure_independently_exact": full_closure,
        "all_four_stage_output_byte_receipts_independently_exact": stage_outputs_independently_exact,
        "all_four_stage_lifecycles_pass": len(rows) == 4 and all(row.get("stage_lifecycle_pass") is True for row in rows),
        "all_four_stage_acceptance_requirements_pass": stage_success,
        "historical_authorities_unchanged": authorities_unchanged(root, frozen),
        "failed_v1_3_R3_custody_exact_after_smoke": (
            prior_v1_3_attempt_after.get("pass") is True
            and prior_v1_3_attempt_after == prior_v1_3_attempt
        ),
        "temporary_shadow_removed": not any(output.glob("bh_simba_shadow_recovery_*")) and not any(output.glob("bh_simba_shadow_repair_*")),
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
    passed = all(checks.values())
    first_hold = next(
        (
            row for row in rows
            if row.get("return_code") != 0
            or row.get("expected_output_fresh_exact") is not True
            or row.get("stage_lifecycle_pass") is not True
        ),
        None,
    )
    if construction_error:
        hold_reason = f"shadow_construction_hold:{construction_error}"
    elif first_hold:
        hold_reason = f"sequential_zero_offset_lifecycle_hold:{first_hold.get('stage')}:{first_hold.get('detail', 'stage_acceptance_failed')[:300]}"
    elif not passed:
        hold_reason = "sequential_zero_offset_lifecycle_acceptance_incomplete"
    else:
        hold_reason = None
    results = output / cfg["outputs"]["smoke_results"]
    write_csv(results, rows, csv_fields(rows) if rows else PREFERRED_FIELDS)
    verdict = {
        "schema_version": 2,
        "run_id": cfg["smoke_run_id"],
        "generated_utc": utc_now(),
        "checks": checks,
        "sequential_smoke_pass": passed,
        "smoke_process_pass": passed,
        "disposition": "synthetic_sequential_zero_offset_runtime_manifest_smoke_resolved" if passed else "synthetic_interface_hold",
        "interface_hold": not passed,
        "hold_reason": hold_reason,
        "predecessor_verdicts": {
            "design_run_id": design.get("run_id"),
            "design_verdict_sha256": design_digest,
            "preflight_run_id": preflight.get("run_id"),
            "preflight_verdict_sha256": preflight_digest,
        },
        "prior_v1_3_attempt_custody": {
            "bundle_version": cfg["prior_v1_3_attempt_custody"]["bundle_version"],
            "bundle_sha256": cfg["prior_v1_3_attempt_custody"]["bundle_sha256"],
            "disposition": cfg["prior_v1_3_attempt_custody"]["disposition"],
            "artifacts": cfg["prior_v1_3_attempt_custody"]["artifacts"],
            "verification": prior_v1_3_attempt_after,
        },
        "expected_stage_invocations": 4,
        "attempted_stage_invocations": len(rows),
        "successful_stage_invocations": sum(
            row.get("return_code") == 0 and row.get("expected_output_fresh_exact") is True for row in rows
        ),
        "all_four_stages_executed_sequentially": stage_success,
        "all_expected_outputs_fresh_exact": fresh_outputs,
        "all_stage_manifest_config_bindings_concordant": len(rows) == 4 and all(row.get("manifest_config_concordant") is True for row in rows),
        "full_manifest_closure_pass": full_closure,
        "runtime_binding_receipt_count": len(receipts) if isinstance(receipts, list) else 0,
        "runtime_binding_receipts_pass": exactly_one_receipt,
        "runtime_binding_provenance_chain_pass": provenance,
        "historical_source_manifest_concordance_claimed": False,
        "historical_source_manifest_discordance_preserved": source_resolution_exact,
        "translated_shadow_manifest_closure_pass": full_closure,
        "construction_and_runtime_receipts_independently_exact": construction_receipts_exact,
        "shadow_config_provenance_exact": invocation_provenance_exact,
        "shadow_audit": audit,
        "negative_memory_result": False,
        "scientific_execution_authorized": False,
        "artifacts": {results.name: {"sha256": sha256(results)}},
        "next_gate": "freeze_current_lifecycle_smoke_acceptance_before_twenty_invocation_matrix" if passed else "hold_sequential_smoke_and_repair_first_exact_failure",
        "claim_cap": cfg["claim_cap"],
    }
    atomic_json(output / cfg["outputs"]["smoke_verdict"], verdict)
    print(json.dumps(verdict, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
