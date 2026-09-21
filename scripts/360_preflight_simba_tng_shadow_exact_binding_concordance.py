#!/usr/bin/env python3
"""Preflight the v1.4 exact-binding lifecycle and full manifest closure."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from bh_simba_runtime_manifest_common_v1_4 import (
    atomic_json,
    prior_attempt_custody_exact,
    prior_v1_3_attempt_custody_exact,
    read_csv,
    read_json,
    sha256,
    stable_json_snapshot,
    utc_now,
    write_csv,
)
from bh_simba_shadow_exact_binding_source_state_lifecycle_recovery_v1_4 import (
    audit_executor_manifest_closure,
    authorities_unchanged,
    construction_audit_exact,
    deep_get,
    exact_manifest_file_records,
    original_authority_hashes,
    prepare_shadow,
    runtime_binding_preflight,
    safe_relative,
)


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


def expected_fields_exact(value: dict[str, Any], expected: dict[str, Any]) -> bool:
    if not isinstance(value, dict) or not isinstance(expected, dict) or not expected:
        return False
    for key, wanted in expected.items():
        try:
            observed = deep_get(value, key) if "." in key else value[key]
        except KeyError:
            return False
        if isinstance(wanted, dict):
            if not expected_fields_exact(observed, wanted):
                return False
        elif observed != wanted:
            return False
    return True


def binding_value(binding: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in binding:
            return binding[name]
    return None


def canonical_argument(path: str, expected: Path) -> bool:
    return Path(path).resolve() == expected.resolve()


def failed_evidence_exact(root: Path, cfg: dict[str, Any]) -> bool:
    spec = cfg["failed_run_217A"]
    rows = read_csv(root / safe_relative(spec["evidence"]))
    expected = spec["expected_evidence"]
    target = cfg["runtime_binding"]["target_relative_path"]
    target_rows = [row for row in rows if row.get("relative_path") == target]
    preexisting = [row for row in rows if row.get("status") == "preexisting_concordant"]
    missing = [row for row in target_rows if row.get("manifest_record_present", "").lower() == "false"]
    declared = [row for row in target_rows if row.get("manifest_record_present", "").lower() == "true"]
    return all((
        len(rows) == expected["row_count"],
        len(target_rows) == expected["runtime_target_binding_count"],
        len(preexisting) == expected["preexisting_concordant_row_count"],
        len(missing) == expected["runtime_target_missing_from_shared_manifest_count"],
        len(declared) == expected["runtime_target_declared_only_in_confirmation_template_count"],
    ))


def csv_fields(rows: list[dict[str, Any]]) -> list[str]:
    preferred = [
        "row_kind", "manifest", "stage", "relative_path", "status", "allowed_missing",
        "record_present", "file_exists", "contained", "regular_file", "non_symlink",
        "digest_exact", "recorded_sha256", "observed_sha256",
    ]
    extras = sorted({key for row in rows for key in row} - set(preferred))
    return [key for key in preferred if any(key in row for row in rows)] + extras


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--design-verdict", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    cfg = read_json(root / args.config)
    output = root / safe_relative(cfg["outputs"]["directory"])
    output.mkdir(parents=True, exist_ok=True)
    design_path = output / cfg["outputs"]["design_verdict"]
    design, _, design_digest = stable_json_snapshot(Path(args.design_verdict))
    failed_spec = cfg["failed_run_217A"]
    failed_verdict = read_json(root / safe_relative(failed_spec["verdict"]))
    prior_attempt = prior_attempt_custody_exact(root, cfg)
    prior_v1_3_attempt = prior_v1_3_attempt_custody_exact(root, cfg)
    frozen = original_authority_hashes(root, cfg)
    prerequisites = {
        "current_design_path_exact": canonical_argument(args.design_verdict, design_path),
        "current_lifecycle_design_exact": design.get("run_id") == cfg["cli_repair_design_run_id"] and design.get("lifecycle_repair_design_freeze_pass") is True,
        "current_design_artifact_exact": exact_artifacts(output, design),
        "design_claim_cap_exact": design.get("claim_cap") == cfg["claim_cap"],
        "failed_run_217A_verdict_hash_exact": artifact_exact(root, failed_spec["verdict"], failed_spec["verdict_sha256"]),
        "failed_run_217A_evidence_hash_exact": artifact_exact(root, failed_spec["evidence"], failed_spec["evidence_sha256"]),
        "failed_run_217A_fields_exact": expected_fields_exact(failed_verdict, failed_spec["expected_fields"]),
        "failed_run_217A_evidence_rows_exact": failed_evidence_exact(root, cfg),
        "failed_run_217A_custody_matches_design": design.get("failed_run_217A_custody") == {
            "verdict": failed_spec["verdict"],
            "verdict_sha256": failed_spec["verdict_sha256"],
            "evidence": failed_spec["evidence"],
            "evidence_sha256": failed_spec["evidence_sha256"],
            "disposition": failed_spec["disposition"],
        },
        "failed_v1_2_R1_R2_custody_exact": prior_attempt.get("pass") is True,
        "failed_v1_2_custody_matches_design": design.get("prior_attempt_custody", {}).get("artifacts")
        == cfg["prior_attempt_custody"]["artifacts"],
        "failed_v1_3_R3_custody_exact": prior_v1_3_attempt.get("pass") is True,
        "failed_v1_3_R3_custody_matches_design": design.get("checks", {}).get(
            "failed_v1_3_R3_custody_exact"
        ) is True and design.get("prior_v1_3_attempt_custody") == {
            "bundle_version": cfg["prior_v1_3_attempt_custody"]["bundle_version"],
            "bundle_sha256": cfg["prior_v1_3_attempt_custody"]["bundle_sha256"],
            "artifacts": cfg["prior_v1_3_attempt_custody"]["artifacts"],
            "verification": prior_v1_3_attempt,
            "disposition": cfg["prior_v1_3_attempt_custody"]["disposition"],
        },
        "zero_offset_exact": float(cfg["synthetic_contract"]["baseline_offset"]) == 0.0,
        "synthetic_only_authorized": cfg["execution_authorizations"]["construct_temporary_synthetic_shadow"] is True,
        "network_and_SIMBA_science_closed": cfg["execution_authorizations"]["network"] is False and cfg["execution_authorizations"]["SIMBA_scientific_payload"] is False,
    }
    rows: list[dict[str, Any]] = []
    shadow_audit: dict[str, Any] = {}
    lifecycle: dict[str, Any] = {}
    closure_audits: dict[str, dict[str, Any]] = {}
    construction_error = None
    prefix = "bh_simba_runtime_manifest_preflight_"
    if all(prerequisites.values()):
        try:
            with tempfile.TemporaryDirectory(prefix=prefix) as temporary:
                shadow = Path(temporary) / "repo"
                shadow.mkdir()
                configs, shadow_audit = prepare_shadow(root, shadow, cfg, 0.0)
                for item in shadow_audit.get("source_authority_resolution", {}).get("rows", []):
                    rows.append({"row_kind": "authority_claim", **item})
                lifecycle = runtime_binding_preflight(root, shadow, cfg, configs)
                for item in lifecycle.get("rows", []):
                    rows.append({"row_kind": "runtime_binding", **item})
                binding = cfg["runtime_binding"]
                target = str(binding_value(binding, "target", "target_relative_path", "runtime_product"))
                confirmation = str(binding_value(binding, "confirmation_manifest", "confirmation_template_manifest"))
                pending: dict[str, set[str]] = {confirmation: {target}}
                for item in binding.get("post_stage_generated_bindings", []):
                    pending.setdefault(item["target_manifest"], set()).add(item["target_relative_path"])
                for manifest in sorted({stage["manifest"] for stage in cfg["stage_contracts"]}):
                    allowed_missing = frozenset(pending.get(manifest, set()))
                    closure = audit_executor_manifest_closure(shadow, manifest, allowed_missing=allowed_missing)
                    closure_audits[manifest] = {
                        key: value for key, value in closure.items()
                        if key not in {"rows", "auxiliary_rows"}
                    }
                    for item in closure.get("rows", []):
                        rows.append({"row_kind": "manifest_closure", "manifest": manifest, **item})
                    for item in closure.get("auxiliary_rows", []):
                        rows.append({"row_kind": "auxiliary_integrity_binding", "manifest": manifest, **item})
        except Exception as error:
            construction_error = f"{type(error).__name__}:{str(error)[:1000]}"
    target = str(binding_value(cfg.get("runtime_binding", {}), "target", "target_relative_path", "runtime_product"))
    confirmation = str(binding_value(cfg.get("runtime_binding", {}), "confirmation_manifest", "confirmation_template_manifest"))
    lifecycle_checks = lifecycle.get("checks", {})
    source_template_records: dict[str, dict[str, Any]] = {}
    if confirmation not in ("", "None"):
        try:
            source_template_records = exact_manifest_file_records(read_json(root / safe_relative(confirmation)))
        except Exception:
            source_template_records = {}
    source_manifest_file_counts: dict[str, int] = {}
    try:
        source_manifest_file_counts = {
            manifest: len(exact_manifest_file_records(read_json(root / safe_relative(manifest))))
            for manifest in sorted({stage["manifest"] for stage in cfg["stage_contracts"]})
        }
    except Exception:
        source_manifest_file_counts = {}
    closure_pass = bool(closure_audits) and len(closure_audits) == len({stage["manifest"] for stage in cfg["stage_contracts"]}) and all(
        audit.get("closure_pass") is True for audit in closure_audits.values()
    )
    construction_anchor = {
        "shared_manifest_before_sha256": lifecycle.get("producer_manifest_sha256"),
        "producer_invocation_manifest_sha256": lifecycle.get("producer_manifest_sha256"),
        "confirmation_manifest_expected_before_sha256": lifecycle.get("confirmation_manifest_sha256"),
        "confirmation_manifest_before_sha256": lifecycle.get("confirmation_manifest_sha256"),
    }
    construction_exact = bool(
        shadow_audit and construction_audit_exact(shadow_audit, cfg, construction_anchor, root)
    )
    checks = {
        **prerequisites,
        "shadow_constructed_without_error": construction_error is None,
        "source_authority_resolution_receipt_exact": shadow_audit.get("source_authority_resolution_pass") is True,
        "construction_authority_audit_independently_exact": construction_exact,
        "design_and_shadow_authority_resolution_receipts_identical": (
            design.get("source_authority_resolution", {}).get("receipt_sha256")
            == shadow_audit.get("source_authority_resolution_receipt_sha256")
        ),
        "historical_source_manifest_discordance_preserved": shadow_audit.get(
            "source_authority_resolution", {}
        ).get("primary_manifest_disagreement_count", 0) >= 1,
        "primary_conflict_policy_adjudicated": shadow_audit.get(
            "source_authority_resolution", {}
        ).get("known_prior_first_conflict_resolved_by_primary") is True,
        "runtime_binding_preflight_complete": lifecycle.get("pass") is True and bool(lifecycle.get("rows")),
        "producer_target_deliberately_absent_before_execution": lifecycle_checks.get("runtime_target_absent_before_producer") is True,
        "producer_shared_manifest_target_record_absent": lifecycle_checks.get("source_shared_target_record_absent") is True and lifecycle_checks.get("shadow_shared_target_record_absent") is True,
        "confirmation_template_target_record_present": lifecycle_checks.get("source_confirmation_template_record_present") is True,
        "confirmation_template_target_record_exact_in_shadow": lifecycle_checks.get("shadow_confirmation_template_record_exact") is True,
        "confirmation_template_target_pending": lifecycle_checks.get("confirmation_has_exactly_one_allowed_pending_target") is True,
        "confirmation_template_content_digest_exact": source_template_records.get(target, {}).get("sha256") == cfg["runtime_binding"]["template_target_content_sha256"],
        "confirmation_template_record_digest_recorded": isinstance(lifecycle.get("template_record_sha256"), str) and len(lifecycle["template_record_sha256"]) == 64,
        "all_unique_executor_manifests_audited": len(closure_audits) == 3,
        "all_top_level_manifest_record_counts_derived_and_nonzero": all(
            audit.get("manifest_file_record_count", 0) > 0 for audit in closure_audits.values()
        ),
        "all_shadow_manifest_record_counts_equal_hash_pinned_sources": bool(source_manifest_file_counts) and all(
            closure_audits.get(manifest, {}).get("manifest_file_record_count") == count
            for manifest, count in source_manifest_file_counts.items()
        ),
        "all_nonpending_top_level_manifest_files_exact_contained_regular_non_symlink": closure_pass,
        "only_declared_generated_records_allowed_missing": all(
            audit.get("allowed_missing_count", 0) <= len(pending.get(manifest, set()))
            for manifest, audit in closure_audits.items()
        ),
        "runtime_target_is_safe_shadow_relative": target not in ("", "None") and safe_relative(target).as_posix() == target,
        "all_rewritten_manifest_digests_recorded": all(
            isinstance(lifecycle.get(key), str) and len(lifecycle[key]) == 64
            for key in ("producer_manifest_sha256", "confirmation_manifest_sha256", "template_record_sha256")
        ),
        "source_template_manifest_hash_exact": (
            lifecycle.get("template_manifest_expected_sha256")
            == lifecycle.get("template_manifest_observed_sha256")
            == cfg["runtime_binding"]["source_manifest_sha256"][confirmation]
        ),
        "historical_authorities_unchanged": authorities_unchanged(root, frozen),
        "historical_failed_evidence_unchanged": artifact_exact(root, failed_spec["verdict"], failed_spec["verdict_sha256"]) and artifact_exact(root, failed_spec["evidence"], failed_spec["evidence_sha256"]),
        "failed_v1_2_evidence_unchanged": prior_attempt_custody_exact(root, cfg).get("pass") is True,
        "failed_v1_3_R3_evidence_unchanged": prior_v1_3_attempt_custody_exact(
            root, cfg
        ).get("pass") is True,
        "temporary_shadow_removed": not any(output.glob(f"{prefix}*")),
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
    evidence = output / cfg["outputs"]["preflight_evidence"]
    fields = csv_fields(rows) if rows else ["row_kind", "manifest", "relative_path", "status"]
    write_csv(evidence, rows, fields)
    verdict = {
        "schema_version": 2,
        "run_id": cfg["manifest_preflight_run_id"],
        "generated_utc": utc_now(),
        "checks": checks,
        "runtime_manifest_preflight_pass": passed,
        "manifest_concordance_preflight_pass": passed,
        "construction_error": construction_error,
        "predecessor_verdicts": {
            "design_run_id": design.get("run_id"),
            "design_verdict_sha256": design_digest,
        },
        "historical_failed_217A_custody": {
            "verdict_sha256": failed_spec["verdict_sha256"],
            "evidence_sha256": failed_spec["evidence_sha256"],
        },
        "failed_v1_2_attempt_custody": {
            "bundle_version": cfg["prior_attempt_custody"]["bundle_version"],
            "bundle_sha256": cfg["prior_attempt_custody"]["bundle_sha256"],
            "disposition": cfg["prior_attempt_custody"]["disposition"],
            "artifacts": cfg["prior_attempt_custody"]["artifacts"],
            "verification": prior_attempt,
        },
        "failed_v1_3_attempt_custody": {
            "bundle_version": cfg["prior_v1_3_attempt_custody"]["bundle_version"],
            "bundle_sha256": cfg["prior_v1_3_attempt_custody"]["bundle_sha256"],
            "disposition": cfg["prior_v1_3_attempt_custody"]["disposition"],
            "artifacts": cfg["prior_v1_3_attempt_custody"]["artifacts"],
            "verification": prior_v1_3_attempt,
        },
        "runtime_binding_preflight": {key: value for key, value in lifecycle.items() if key != "rows"},
        "manifest_closure_audits": closure_audits,
        "source_manifest_file_record_counts": source_manifest_file_counts,
        "executor_manifest_count": len(closure_audits),
        "manifest_file_record_count": sum(int(audit.get("manifest_file_record_count", 0)) for audit in closure_audits.values()),
        "manifest_file_digest_match_count": sum(int(audit.get("manifest_file_digest_match_count", 0)) for audit in closure_audits.values()),
        "runtime_product_pending_count": sum(
            row.get("status") in {"pending", "allowed_pending", "runtime_product_pending", "confirmation_template_record_pending"}
            for row in lifecycle.get("rows", [])
        ),
        "shadow_audit": shadow_audit,
        "historical_source_manifest_cross_claim_concordance": False,
        "primary_conflict_policy_adjudicated": checks.get("primary_conflict_policy_adjudicated") is True,
        "translated_shadow_invocation_manifest_closure": closure_pass,
        "scientific_parameter_changed": False,
        "scientific_execution_authorized": False,
        "artifacts": {evidence.name: {"sha256": sha256(evidence)}},
        "next_gate": "execute_sequential_zero_offset_with_post_producer_runtime_binding" if passed else "hold_runtime_manifest_lifecycle_preflight",
        "claim_cap": cfg["claim_cap"],
    }
    atomic_json(output / cfg["outputs"]["preflight_verdict"], verdict)
    print(json.dumps(verdict, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
