#!/usr/bin/env python3
"""Freeze v1.4 all-claims authority resolution and runtime binding lifecycle."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from bh_simba_runtime_manifest_common_v1_4 import (
    atomic_json,
    read_json,
    release_field_authority,
    prior_attempt_custody_exact,
    prior_v1_3_attempt_custody_exact,
    sha256,
    utc_now,
    write_csv,
)
from bh_simba_shadow_exact_binding_source_state_lifecycle_recovery_v1_4 import (
    _path_state,
    canonical_json_sha256,
    deep_get,
    package_scaffold_source_census,
    prove_schema_specific_config_integrity_bindings,
    resolve_source_manifest_claims,
    safe_relative,
    source_snapshot_bytes,
    source_authority_resolution_exact,
)


CLAIM_CAP = (
    "synthetic_only_exact_TNG_CLI_manifest_interface_and_selected_observable_admission_"
    "sensitivity_to_tested_latent_signal_offsets_"
    "with_writer_semantics_physical_units_population_equivalence_SIMBA_coordinate_tracks_"
    "zero_policy_adapter_and_scientific_memory_execution_closed"
)

EXPECTED_EXACT_SOURCE_PATHS = {
    "scripts/84_run_tng50_canonical_generator3_phase_b.py",
    "scripts/85_screen_tng50_canonical_generator3_full_history_null.py",
    "scripts/89_screen_tng50_memory_generator4_pooled_innovation.py",
    "src/core/causal_memory.py",
    "src/core/innovation_memory.py",
    "src/core/memory_nulls.py",
    "src/core/predictive_memory.py",
}
EXPECTED_PACKAGE_SCAFFOLD_PATHS = {
    "src/__init__.py", "src/core/__init__.py", "scripts/__init__.py",
}
EXPECTED_SOURCE_BYTES = {
    "scripts/84_run_tng50_canonical_generator3_phase_b.py": 7113,
    "scripts/85_screen_tng50_canonical_generator3_full_history_null.py": 11156,
    "scripts/89_screen_tng50_memory_generator4_pooled_innovation.py": 16541,
    "src/core/predictive_memory.py": 3027,
    "src/core/causal_memory.py": 2784,
    "src/core/memory_nulls.py": 3616,
    "src/core/innovation_memory.py": 4442,
}

EXPECTED_RUNTIME_BINDING_RECEIPT_FIELDS = {
    "schema_version", "offset", "producer_stage", "producer_return_code",
    "target_relative_path", "product_payload_b64", "product_json_run_id",
    "product_json_schema_version", "target_sha256", "target_bytes",
    "template_manifest_relative_path", "template_manifest_source_sha256",
    "template_record_sha256", "preproducer_target_absent",
    "confirmation_manifest_expected_before_sha256", "manifest_mutations",
    "exact_mutation_scope_pass", "atomic_replacement_pass",
    "downstream_full_manifest_closure_pass",
    "downstream_three_of_three_input_concordance_pass",
    "receipt_payload_sha256", "receipt_sha256",
}

INVENTORY_FIELDS = [
    "row_kind", "relative_path", "role", "expected_sha256",
    "expected_bytes", "observed_sha256", "observed_bytes", "source_state",
    "exact_or_admissible", "detail_json",
]


def canonical_receipt_exact(receipt: Any) -> bool:
    """Require the self-hash to cover every field except itself."""
    if not isinstance(receipt, dict) or not isinstance(
        receipt.get("receipt_sha256"), str
    ):
        return False
    payload = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    return receipt["receipt_sha256"] == canonical_json_sha256(payload)


def tri_state(*, resolved: bool, evaluable: bool) -> str:
    """Return an explicit repair state without turning non-evaluation into failure."""
    if not evaluable:
        return "not_evaluable"
    return "resolved" if resolved else "still_failed"


def exact_source_census(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    raw_configured = cfg.get("exact_sources", {})
    configured = raw_configured if isinstance(raw_configured, dict) else {}
    for relative in sorted(EXPECTED_EXACT_SOURCE_PATHS | set(configured)):
        expected = configured.get(relative, "")
        expected_bytes = EXPECTED_SOURCE_BYTES.get(relative, -1)
        state = _path_state(root, relative, require_single_link=True)
        observed_sha = ""
        observed_bytes = -1
        observation_error = ""
        if state["valid_regular_contained"]:
            try:
                payload = source_snapshot_bytes(root, relative)
                observed_sha = hashlib.sha256(payload).hexdigest()
                observed_bytes = len(payload)
            except (OSError, RuntimeError) as error:
                observation_error = f"{type(error).__name__}:{str(error)[:500]}"
        exact = bool(
            relative in EXPECTED_EXACT_SOURCE_PATHS
            and isinstance(expected, str)
            and observed_sha == expected
            and observed_bytes == expected_bytes
        )
        if exact:
            source_state = "exact_regular"
        elif relative not in EXPECTED_EXACT_SOURCE_PATHS:
            source_state = "unexpected_configured_source"
        elif observation_error:
            source_state = "unstable_or_unreadable"
        elif not state["exists"]:
            source_state = "missing"
        elif not state["valid_regular_contained"]:
            source_state = "unsafe_or_nonregular"
        elif observed_sha != expected:
            source_state = "digest_mismatch"
        else:
            source_state = "byte_count_mismatch"
        rows.append({
            **state,
            "role": "executor" if relative.startswith("scripts/") else "core_module",
            "expected_sha256": expected,
            "expected_bytes": expected_bytes,
            "observed_sha256": observed_sha,
            "observed_bytes": observed_bytes,
            "observation_error": observation_error,
            "source_state": source_state,
            "source_state_admissible": exact,
        })
    scaffold = package_scaffold_source_census(root, cfg)
    combined = [*rows, *scaffold.get("rows", [])]
    exact_source_mismatch_paths = sorted(
        row["relative_path"]
        for row in rows
        if row["source_state_admissible"] is not True
    )
    scaffold_rows = scaffold.get("rows", [])
    scaffold_state_paths = {
        row["relative_path"]: row["source_state"] for row in scaffold_rows
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "configured_exact_sources_is_mapping": isinstance(raw_configured, dict),
        "configured_exact_source_count": len(configured),
        "expected_exact_source_count": len(EXPECTED_EXACT_SOURCE_PATHS),
        "exact_source_row_count": len(rows),
        "exact_source_exact_count": sum(
            row["source_state_admissible"] is True for row in rows
        ),
        "exact_source_mismatch_paths": exact_source_mismatch_paths,
        "expected_package_scaffold_count": len(EXPECTED_PACKAGE_SCAFFOLD_PATHS),
        "package_scaffold_row_count": len(scaffold_rows),
        "package_scaffold_source_states": scaffold_state_paths,
        "effective_python_input_count": len(combined),
        "original_seven_exact": bool(
            isinstance(raw_configured, dict)
            and set(configured) == EXPECTED_EXACT_SOURCE_PATHS
            and len(rows) == 7 and all(row["source_state_admissible"] for row in rows)
        ),
        "scaffold_triplet_admissible": bool(
            scaffold.get("census_pass") is True
            and set(scaffold_state_paths) == EXPECTED_PACKAGE_SCAFFOLD_PATHS
            and len(scaffold_rows) == 3
        ),
        "package_scaffold_source_census": scaffold,
        "rows": combined,
    }
    payload["census_pass"] = bool(
        payload["original_seven_exact"]
        and payload["scaffold_triplet_admissible"]
        and payload["effective_python_input_count"] == 10
    )
    payload["receipt_sha256"] = canonical_json_sha256(payload)
    return payload


def artifact_exact(root: Path, relative: str, expected: str) -> bool:
    path = root / safe_relative(relative)
    return path.is_file() and not path.is_symlink() and sha256(path) == expected


def argparse_flags(path: Path) -> dict[str, bool]:
    """Return literal long flags and whether each is declared required."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        flags = [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
        required = next(
            (kw.value.value for kw in node.keywords if kw.arg == "required" and isinstance(kw.value, ast.Constant)),
            False,
        )
        for flag in flags:
            if flag.startswith("--"):
                found[flag] = bool(required)
    return found


def upstream_file_records_exact(root: Path, item: dict[str, Any]) -> bool:
    records = item.get("files", item.get("artifacts", {}))
    if not isinstance(records, dict) or not records:
        return False
    for name, record in records.items():
        if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
            return False
        try:
            path = root / safe_relative(str(name))
        except RuntimeError:
            return False
        if not path.is_file():
            matches = list(root.glob(f"outputs/protocol/**/{Path(str(name)).name}"))
            path = matches[0] if len(matches) == 1 else path
        if not path.is_file() or path.is_symlink() or sha256(path) != record["sha256"]:
            return False
    return True


def expected_fields_exact(value: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Check the recursively frozen subset (and allow dotted leaf names)."""
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


def runtime_binding_receipt_fields_exact(cfg: dict[str, Any]) -> bool:
    binding = cfg.get("runtime_binding", {})
    receipt = binding.get("receipt_schema", {}) if isinstance(binding, dict) else {}
    fields = receipt.get("required_fields", []) if isinstance(receipt, dict) else []
    return bool(
        isinstance(fields, list)
        and len(fields) == 22
        and all(isinstance(field, str) for field in fields)
        and len(set(fields)) == 22
        and set(fields) == EXPECTED_RUNTIME_BINDING_RECEIPT_FIELDS
    )


def lifecycle_contract_exact(cfg: dict[str, Any]) -> bool:
    """Validate the exact v1 or declared-dependency v2 runtime-binding lifecycle."""
    binding = cfg.get("runtime_binding")
    if not isinstance(binding, dict):
        return False
    target = binding_value(binding, "target", "target_relative_path", "runtime_product")
    producer = binding_value(binding, "producer", "producer_stage")
    consumers = binding_value(binding, "consumers", "consumer_stages")
    shared = binding_value(binding, "shared_manifest", "producer_manifest")
    confirmation = binding_value(binding, "confirmation_manifest", "confirmation_template_manifest")
    template = binding_value(binding, "template_manifest", "confirmation_template_manifest")
    if not all(isinstance(value, str) and value for value in (target, producer, shared, confirmation, template)):
        return False
    if not isinstance(consumers, list) or len(consumers) != 2 or len(set(consumers)) != 2:
        return False
    try:
        safe_relative(target)
        safe_relative(shared)
        safe_relative(confirmation)
        safe_relative(template)
    except RuntimeError:
        return False
    stage_names = [stage["stage"] for stage in cfg["stage_contracts"]]
    preproducer = binding.get("required_preproducer_state", {})
    postproducer = binding.get("required_postproducer_state", {})
    mutation = binding.get("mutation_scope", {})
    receipt = binding.get("receipt_schema", {})
    configured_receipt_fields = receipt.get("required_fields", [])
    receipt_fields_exact = bool(
        isinstance(configured_receipt_fields, list)
        and len(configured_receipt_fields) == 22
        and all(isinstance(field, str) for field in configured_receipt_fields)
        and len(set(configured_receipt_fields)) == 22
        and set(configured_receipt_fields) == EXPECTED_RUNTIME_BINDING_RECEIPT_FIELDS
    )
    source_manifest_sha = binding.get("source_manifest_sha256", {})
    post = binding.get("post_stage_generated_bindings", [])
    post_schema = binding.get("post_stage_generated_receipt_schema", {})
    expected_post_fields = ['schema_version', 'binding_id', 'offset', 'producer_stage', 'producer_return_code', 'consumer_stage', 'target_relative_path', 'product_payload_b64', 'product_json_run_id', 'product_json_schema_version', 'target_sha256', 'target_bytes', 'target_manifest_relative_path', 'source_template_manifest_expected_sha256', 'source_template_manifest_observed_sha256', 'template_record_sha256', 'template_record', 'refreshed_record', 'preproducer_target_absent', 'producer_invocation_manifest_sha256', 'target_manifest_expected_before_sha256', 'target_manifest_before', 'target_manifest_before_sha256', 'target_manifest_after', 'target_manifest_after_sha256', 'manifest_mutations', 'exact_mutation_scope_pass', 'atomic_replacement_pass', 'downstream_manifest_closure_pass', 'downstream_required_input_concordance_pass', 'binding_pass', 'hold_reason', 'receipt_payload_sha256', 'receipt_sha256']
    post_exact = bool(
        isinstance(post, list)
        and len(post) == binding.get("post_stage_generated_binding_count_per_shadow") == 2
        and [item.get("producer_stage") for item in post] == stage_names[1:3]
        and [item.get("consumer_stage") for item in post] == stage_names[2:4]
        and all(item.get("schema_version") == 1 and item.get("target_relative_path") == next(stage["fresh_output_contract"]["expected_relative_path"] for stage in cfg["stage_contracts"] if stage["stage"] == item["producer_stage"]) and item.get("target_manifest") == next(stage["manifest"] for stage in cfg["stage_contracts"] if stage["stage"] == item["consumer_stage"]) for item in post)
        and isinstance(post_schema, dict) and post_schema.get("version") == 1
        and set(post_schema.get("required_fields", [])) == set(expected_post_fields)
        and len(post_schema.get("required_fields", [])) == len(expected_post_fields)
    )
    version = binding.get("schema_version")
    dependency = binding.get("dependency_refresh")
    if version == 1:
        lifecycle_version_exact = bool(
            dependency is None
            and mutation.get("target_record_only") is True
            and "target_plus_one_declared_dependency_record_only" not in mutation
            and receipt.get("name") == "bh_simba_shadow_runtime_manifest_binding_receipt"
            and receipt.get("version") == 1
            and "dependency_refresh_semantics" not in receipt
            and len(binding.get("binding_sequence", [])) == 7
        )
    elif version == 2:
        expected_dependency_keys = {
            "schema_version", "child_manifest", "parent_manifest", "record_field",
            "exact_existing_record_only", "derive_after_from_serialized_child_after_bytes",
            "no_size_field_invention", "no_generic_refresh",
        }
        expected_sequence = [
            "invoke_producer_with_unmodified_shared_shadow_manifest",
            "require_zero_return_code_and_exact_fresh_target_json",
            "clone_target_record_from_hash_pinned_confirmation_template",
            "derive_postproducer_shared_manifest_digest_from_complete_serialized_after_bytes",
            "refresh_exact_existing_confirmation_dependency_digest_for_shared_manifest",
            "refresh_only_existing_content_derived_target_record_fields",
            "atomically_replace_shared_and_confirmation_shadow_manifests",
            "verify_exact_mutation_scope_and_postwrite_manifest_digests",
            "audit_full_executor_manifest_closure_and_three_of_three_consumer_input_concordance",
        ]
        lifecycle_version_exact = bool(
            isinstance(dependency, dict)
            and set(dependency) == expected_dependency_keys
            and dependency.get("schema_version") == 1
            and dependency.get("child_manifest") == shared
            and dependency.get("parent_manifest") == confirmation
            and dependency.get("record_field") == "sha256"
            and all(dependency.get(name) is True for name in (
                "exact_existing_record_only",
                "derive_after_from_serialized_child_after_bytes",
                "no_size_field_invention",
                "no_generic_refresh",
            ))
            and mutation.get("target_record_only") is False
            and mutation.get("target_plus_one_declared_dependency_record_only") is True
            and receipt.get("name") == "bh_simba_shadow_runtime_manifest_binding_receipt_v2_dependency_refresh"
            and receipt.get("version") == 2
            and receipt.get("dependency_refresh_semantics") == "manifest_mutations_may_add_exact_declared_parent_dependency_digest_refresh"
            and binding.get("binding_sequence") == expected_sequence
        )
    else:
        lifecycle_version_exact = False
    return all((
        lifecycle_version_exact,
        producer == stage_names[0] == "generator3_phase_b",
        consumers == stage_names[1:3],
        shared == cfg["stage_contracts"][0]["manifest"] == cfg["stage_contracts"][1]["manifest"],
        confirmation == cfg["stage_contracts"][2]["manifest"],
        preproducer.get("target_absent") is True,
        preproducer.get("target_record_absent_from_shared_shadow_manifest") is True,
        preproducer.get("template_target_record_present_in_confirmation_source_manifest") is True,
        postproducer.get("producer_return_code") == 0,
        postproducer.get("target_is_fresh_json") is True,
        postproducer.get("target_is_contained_regular_nonsymlink_file") is True,
        mutation.get("source_authorities_immutable") is True,
        mutation.get("shadow_only") is True,
        mutation.get("clone_exact_confirmation_template_record") is True,
        mutation.get("atomic_sibling_temp_write_fsync_replace") is True,
        mutation.get("partial_multi_manifest_binding_is_failure") is True,
        receipt.get("one_receipt_per_shadow_offset") is True,
        receipt.get("absolute_temporary_paths_forbidden") is True,
        receipt.get("wall_clock_fields_forbidden") is True,
        receipt_fields_exact,
        isinstance(binding.get("template_target_content_sha256"), str) and len(binding["template_target_content_sha256"]) == 64,
        int(binding.get("template_target_bytes", -1)) > 0,
        source_manifest_sha.get(shared) == cfg["stage_contracts"][0]["manifest_sha256"],
        source_manifest_sha.get(confirmation) == cfg["stage_contracts"][2]["manifest_sha256"],
        binding.get("source_manifest_top_level_file_count_policy") == "derive_nonzero_exact_len_of_files_from_each_hash_pinned_source_manifest_and_record_in_every_shadow_audit",
        set(mutation.get("authorized_existing_content_derived_fields", [])) == {"sha256", "bytes", "size", "size_bytes", "file_size_bytes"},
        binding.get("generic_interstage_refresh_forbidden") is True,
        post_exact,
        cfg["repair_contract"].get("generic_interstage_manifest_or_config_refresh") is False,
        cfg["repair_contract"].get("only_explicit_postproducer_runtime_binding_mutation") is True,
    ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    cfg = read_json(root / args.config)
    inp, expected = cfg["inputs"], cfg["expected_prior"]
    failed_spec = cfg["failed_run_217A"]
    run214 = read_json(root / inp["run_214_diagnostic"])
    run215 = read_json(root / inp["run_215_closure"])
    run216 = read_json(root / inp["run_216_contract"])
    run217 = read_json(root / inp["run_217_baseline"])
    failed_verdict = read_json(root / safe_relative(failed_spec["verdict"]))
    release_authority = release_field_authority(root, cfg.get("release_field_authority"))
    prior_attempt = prior_attempt_custody_exact(root, cfg)
    prior_v1_3_attempt = prior_v1_3_attempt_custody_exact(root, cfg)
    source_census = exact_source_census(root, cfg)
    binding_proof = prove_schema_specific_config_integrity_bindings(root, cfg)
    stage_rows: list[dict[str, Any]] = []
    all_authorities = True
    all_cli = True
    for stage in cfg["stage_contracts"]:
        executor = root / safe_relative(stage["executor"])
        config = root / safe_relative(stage["config"])
        manifest = root / safe_relative(stage["manifest"])
        flags = argparse_flags(executor)
        exact = all((
            executor.is_file() and not executor.is_symlink() and sha256(executor) == stage["executor_sha256"],
            config.is_file() and not config.is_symlink() and sha256(config) == stage["config_sha256"],
            manifest.is_file() and not manifest.is_symlink() and sha256(manifest) == stage["manifest_sha256"],
        ))
        cli = flags.get("--config") is True and flags.get("--freeze-manifest") is True and flags.get("--repo-root") is False
        all_authorities &= exact
        all_cli &= cli
        stage_rows.append({
            "stage": stage["stage"],
            "executor": stage["executor"],
            "executor_hash_exact": executor.is_file() and sha256(executor) == stage["executor_sha256"],
            "config_required": flags.get("--config") is True,
            "freeze_manifest_required": flags.get("--freeze-manifest") is True,
            "repo_root_optional": flags.get("--repo-root") is False,
            "config_path_safe_relative": safe_relative(stage["config"]).as_posix() == stage["config"],
            "manifest_path_safe_relative": safe_relative(stage["manifest"]).as_posix() == stage["manifest"],
            "config_hash_exact": config.is_file() and sha256(config) == stage["config_sha256"],
            "manifest_hash_exact": manifest.is_file() and sha256(manifest) == stage["manifest_sha256"],
            "frozen_command_contract": "python EXECUTOR --config CONFIG --freeze-manifest MANIFEST --repo-root ABSOLUTE_SHADOW",
            "post_producer_runtime_binding": stage["stage"] == "generator3_phase_b",
            "scientific_parameter_changed": False,
        })
    resolution_error = None
    try:
        resolution = resolve_source_manifest_claims(root, cfg)
    except Exception as error:
        resolution = {}
        resolution_error = f"{type(error).__name__}:{str(error)[:1000]}"
    resolution_exact = source_authority_resolution_exact(resolution, cfg, root) if resolution else False
    source_census_receipt_exact = canonical_receipt_exact(source_census)
    scaffold_census = source_census.get("package_scaffold_source_census", {})
    scaffold_census_receipt_exact = canonical_receipt_exact(scaffold_census)
    binding_proof_receipt_exact = canonical_receipt_exact(binding_proof)
    lifecycle_exact = lifecycle_contract_exact(cfg)
    lifecycle_receipt_fields_exact = runtime_binding_receipt_fields_exact(cfg)

    source_census_evaluable = bool(
        source_census_receipt_exact
        and source_census.get("exact_source_row_count", 0) >= 7
        and source_census.get("package_scaffold_row_count") == 3
    )
    binding_proof_evaluable = bool(
        binding_proof_receipt_exact
        and binding_proof.get("error") == ""
        and binding_proof.get("declared_binding_count") == 1
        and len(binding_proof.get("rows", [])) == 1
    )
    runtime_binding = cfg.get("runtime_binding")
    lifecycle_evaluable = bool(
        isinstance(runtime_binding, dict)
        and isinstance(runtime_binding.get("receipt_schema"), dict)
        and isinstance(
            runtime_binding.get("receipt_schema", {}).get("required_fields"),
            list,
        )
    )
    prior_v1_3_predicate_states = {
        "all_ten_exact_sources_current": {
            "prior_observation": False,
            "current_repair_check": "seven_exact_sources_plus_three_admissible_shadow_scaffold_source_states",
            "current_status": tri_state(
                resolved=source_census.get("census_pass") is True,
                evaluable=source_census_evaluable,
            ),
            "current_evaluable": source_census_evaluable,
            "evidence_receipt_sha256": source_census.get("receipt_sha256", ""),
        },
        "generator4_config_integrity_binding": {
            "prior_observation": (
                "RuntimeError:unsupported_or_orphan_sibling_integrity_fields:"
                "$.screen:exact_g3_track_plan_sha256"
            ),
            "current_repair_check": "one_schema_specific_cross_mapping_binding_plus_manifest_observed_and_executor_ast_proof",
            "current_status": tri_state(
                resolved=binding_proof.get("binding_proof_pass") is True,
                evaluable=binding_proof_evaluable,
            ),
            "current_evaluable": binding_proof_evaluable,
            "evidence_receipt_sha256": binding_proof.get("receipt_sha256", ""),
        },
        "runtime_binding_lifecycle_schema_exact": {
            "prior_observation": False,
            "current_repair_check": "exact_22_field_runtime_binding_receipt_schema_and_lifecycle_contract",
            "current_status": tri_state(
                resolved=lifecycle_exact and lifecycle_receipt_fields_exact,
                evaluable=lifecycle_evaluable,
            ),
            "current_evaluable": lifecycle_evaluable,
            "configured_required_field_count": len(
                runtime_binding.get("receipt_schema", {}).get(
                    "required_fields", []
                )
            ) if lifecycle_evaluable else -1,
        },
    }
    predicate_statuses = {
        item["current_status"] for item in prior_v1_3_predicate_states.values()
    }
    if predicate_statuses == {"resolved"}:
        prior_v1_3_repair_verdict = "resolved"
    elif "still_failed" in predicate_statuses:
        prior_v1_3_repair_verdict = "still_failed"
    else:
        prior_v1_3_repair_verdict = "not_evaluable"
    rows: list[dict[str, Any]] = []
    for row in source_census["rows"]:
        rows.append({
            "row_kind": "source_state",
            "relative_path": row["relative_path"],
            "role": row["role"],
            "expected_sha256": row["expected_sha256"],
            "expected_bytes": row["expected_bytes"],
            "observed_sha256": row["observed_sha256"],
            "observed_bytes": row["observed_bytes"],
            "source_state": row["source_state"],
            "exact_or_admissible": row["source_state_admissible"],
            "detail_json": json.dumps(row, sort_keys=True, separators=(",", ":")),
        })
    for row in binding_proof.get("rows", []):
        rows.append({
            "row_kind": "schema_specific_config_integrity_binding",
            "relative_path": row.get("relative_path", ""),
            "role": row.get("stage", ""),
            "expected_sha256": row.get("claimed_sha256", ""),
            "expected_bytes": row.get("observed_bytes", -1),
            "observed_sha256": row.get("observed_sha256", ""),
            "observed_bytes": row.get("observed_bytes", -1),
            "source_state": "binding_proven" if row.get("binding_pass") else "binding_hold",
            "exact_or_admissible": row.get("binding_pass") is True,
            "detail_json": json.dumps(row, sort_keys=True, separators=(",", ":")),
        })
    for row in resolution.get("rows", []):
        rows.append({
            "row_kind": "authority_claim",
            "relative_path": row["relative_path"],
            "role": row["authority_class"],
            "expected_sha256": row["selected_sha256"],
            "expected_bytes": row["observed_source_bytes"],
            "observed_sha256": row["observed_source_sha256"],
            "observed_bytes": row["observed_source_bytes"],
            "source_state": row["resolution"],
            "exact_or_admissible": not row["fatal_conflict"],
            "detail_json": json.dumps(row, sort_keys=True, separators=(",", ":")),
        })
    failed_evidence_exact = artifact_exact(root, failed_spec["evidence"], failed_spec["evidence_sha256"])
    failed_verdict_exact = artifact_exact(root, failed_spec["verdict"], failed_spec["verdict_sha256"])
    checks = {
        "run_214_exact_argument_or_cli_hold": run214.get("run_id") == expected["run_214_id"] and run214.get("diagnostic_freeze_pass") is True and run214.get("prior_failure_class") == expected["run_214_failure_class"],
        "run_214_inventory_hash_exact": artifact_exact(root, inp["run_214_inventory"], expected["run_214_inventory_sha256"]),
        "run_215_exact": run215.get("run_id") == expected["run_215_id"] and run215.get("closure_inventory_pass") is True,
        "run_215_inventory_hash_exact": artifact_exact(root, inp["run_215_inventory"], expected["run_215_inventory_sha256"]),
        "run_216_exact": run216.get("run_id") == expected["run_216_id"] and run216.get("repair_contract_pass") is True,
        "run_217_exact_interface_hold": (
            run217.get("run_id") == expected["run_217_id"]
            and run217.get("baseline_process_pass") is True
            and run217.get("baseline_interface_resolved") is False
            and run217.get("disposition") == expected["run_217_disposition"]
            and run217.get("hold_reason") == expected["run_217_hold_reason"]
            and run217.get("attempted_stage_invocations") == expected["run_217_attempted"]
            and run217.get("successful_stage_invocations") == expected["run_217_successful"]
        ),
        "run_217_results_hash_exact": artifact_exact(root, inp["run_217_results"], expected["run_217_results_sha256"]),
        "failed_run_217A_verdict_hash_exact": failed_verdict_exact,
        "failed_run_217A_evidence_hash_exact": failed_evidence_exact,
        "failed_run_217A_fields_exact": expected_fields_exact(failed_verdict, failed_spec["expected_fields"]),
        "failed_run_217A_disposition_frozen": failed_spec.get("disposition") == "immutable_failed_prerequisite_not_overwritten",
        "failed_run_217A_is_distinct_preserved_custody": safe_relative(failed_spec["verdict"]).as_posix() != str(Path(cfg["outputs"]["directory"]) / cfg["outputs"]["preflight_verdict"]),
        "failed_v1_2_R1_R2_custody_exact": prior_attempt.get("pass") is True,
        "failed_v1_3_R3_custody_exact": prior_v1_3_attempt.get("pass") is True,
        "upstream_recorded_artifacts_exact": all(upstream_file_records_exact(root, item) for item in (run214, run215, run216, run217)),
        "exact_source_census_receipt_exact": source_census_receipt_exact,
        "package_scaffold_census_receipt_exact": scaffold_census_receipt_exact,
        "original_seven_exact_sources_current": source_census.get("original_seven_exact") is True,
        "three_package_scaffold_source_states_admissible": source_census.get("scaffold_triplet_admissible") is True,
        "ten_effective_python_source_states_attested": source_census.get("census_pass") is True,
        "all_stage_authorities_current": all_authorities,
        "three_unique_executor_CLIs_require_config_and_manifest": len({stage["executor"] for stage in cfg["stage_contracts"]}) == 3 and all_cli,
        "four_stages_and_three_unique_manifests_frozen": len(stage_rows) == 4 and len({stage["manifest"] for stage in cfg["stage_contracts"]}) == 3,
        "all_manifest_claims_inventoried_before_resolution": bool(resolution.get("rows")) and resolution.get("claim_count") == len(resolution.get("rows", [])),
        "source_authority_resolution_receipt_exact": resolution_exact,
        "schema_specific_generator4_binding_proof_receipt_exact": binding_proof_receipt_exact,
        "schema_specific_generator4_config_integrity_binding_proven": (
            binding_proof.get("binding_proof_pass") is True
        ),
        "equal_rank_primary_conflicts_zero": resolution.get("primary_conflict_count") == 0,
        "unresolved_non_primary_conflicts_zero": resolution.get("unresolved_non_primary_conflict_count") == 0,
        "known_script85_conflict_resolved_only_by_validated_primary": resolution.get("known_prior_first_conflict_resolved_by_primary") is True,
        "historical_source_manifest_discordance_preserved": resolution.get("primary_manifest_disagreement_count", 0) >= 1,
        "runtime_binding_receipt_schema_exact_22_field_set": lifecycle_receipt_fields_exact,
        "runtime_binding_lifecycle_schema_exact": lifecycle_exact,
        "prior_release_field_authority_current_and_exact": release_authority is not None,
        "repair_changes_only_invocation_and_shadow_lifecycle_receipts": cfg["repair_contract"]["scientific_parameter_mutation"] is False and cfg["repair_contract"]["historical_file_mutation"] is False,
        "claim_cap_exact": cfg.get("claim_cap") == CLAIM_CAP,
        "SIMBA_science_closed": cfg["execution_authorizations"]["SIMBA_scientific_payload"] is False,
    }
    output = root / safe_relative(cfg["outputs"]["directory"])
    output.mkdir(parents=True, exist_ok=True)
    inventory = output / cfg["outputs"]["design_inventory"]
    write_csv(inventory, rows, INVENTORY_FIELDS)
    passed = all(checks.values())
    binding_schema_digest = hashlib.sha256(
        json.dumps(cfg["runtime_binding"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    verdict = {
        "schema_version": 2,
        "run_id": cfg["cli_repair_design_run_id"],
        "generated_utc": utc_now(),
        "checks": checks,
        "lifecycle_repair_design_freeze_pass": passed,
        "cli_repair_design_freeze_pass": passed,
        "prior_runs_214_through_217_preserved": all(
            checks[key]
            for key in (
                "run_214_exact_argument_or_cli_hold",
                "run_214_inventory_hash_exact",
                "run_215_exact",
                "run_215_inventory_hash_exact",
                "run_216_exact",
                "run_217_exact_interface_hold",
                "run_217_results_hash_exact",
                "upstream_recorded_artifacts_exact",
            )
        ),
        "failed_run_217A_preserved": failed_verdict_exact and failed_evidence_exact,
        "failed_v1_2_attempt_preserved": prior_attempt.get("pass") is True,
        "failed_v1_3_attempt_preserved": prior_v1_3_attempt.get("pass") is True,
        "failed_run_217A_custody": {
            "verdict": failed_spec["verdict"],
            "verdict_sha256": failed_spec["verdict_sha256"],
            "evidence": failed_spec["evidence"],
            "evidence_sha256": failed_spec["evidence_sha256"],
            "disposition": failed_spec["disposition"],
        },
        "prior_attempt_custody": {
            "bundle_version": cfg["prior_attempt_custody"]["bundle_version"],
            "bundle_sha256": cfg["prior_attempt_custody"]["bundle_sha256"],
            "artifacts": cfg["prior_attempt_custody"]["artifacts"],
            "verification": prior_attempt,
            "disposition": cfg["prior_attempt_custody"]["disposition"],
        },
        "prior_v1_3_attempt_custody": {
            "bundle_version": cfg["prior_v1_3_attempt_custody"]["bundle_version"],
            "bundle_sha256": cfg["prior_v1_3_attempt_custody"]["bundle_sha256"],
            "artifacts": cfg["prior_v1_3_attempt_custody"]["artifacts"],
            "verification": prior_v1_3_attempt,
            "disposition": cfg["prior_v1_3_attempt_custody"]["disposition"],
        },
        "proven_failure_cause": "required_freeze_manifest_argument_omitted_from_run_217_command",
        "prior_v1_2_failure_cause": "fail_fast_cross_manifest_digest_merge_preceded_authorized_shadow_translation",
        "prior_v1_3_failed_predicate_repair_verdict": prior_v1_3_repair_verdict,
        "prior_v1_3_failed_predicate_states": prior_v1_3_predicate_states,
        "newly_resolved_design_defect": (
            "exact_source_scaffold_classification_schema_specific_generator4_binding_"
            "and_22_field_runtime_receipt_schema"
            if prior_v1_3_repair_verdict == "resolved"
            else "not_claimed"
        ),
        "authority_resolution_error": resolution_error,
        "exact_source_and_scaffold_census": source_census,
        "schema_specific_config_integrity_binding_proof": binding_proof,
        "source_authority_resolution": resolution,
        "historical_source_manifest_cross_claim_concordance": (
            False
            if resolution_exact
            and resolution.get("primary_manifest_disagreement_count", 0) >= 1
            else "not_evaluated"
        ),
        "primary_conflict_policy_adjudicated": passed,
        "translated_shadow_invocation_manifest_closure": "not_evaluated",
        "downstream_zero_offset_smoke_status": "not_evaluated",
        "downstream_translation_matrix_status": "not_evaluated",
        "scientific_result_status": "not_evaluated",
        "frozen_command_contract": ["PYTHON", "EXECUTOR", "--config", "CONFIG", "--freeze-manifest", "MANIFEST", "--repo-root", "ABSOLUTE_SHADOW"],
        "runtime_binding_schema_sha256": binding_schema_digest,
        "prior_release_field_authority": release_authority or {},
        "stage_count": len(stage_rows),
        "unique_executor_count": len({stage["executor"] for stage in cfg["stage_contracts"]}),
        "unique_manifest_count": len({stage["manifest"] for stage in cfg["stage_contracts"]}),
        "scientific_design_changed": False,
        "scientific_execution_performed": False,
        "scientific_execution_authorized": False,
        "artifacts": {inventory.name: {"sha256": sha256(inventory)}},
        "next_gate": "preflight_runtime_manifest_lifecycle_and_full_executor_manifest_closure" if passed else "hold_lifecycle_repair_design_authority_failure",
        "claim_cap": cfg["claim_cap"],
    }
    atomic_json(output / cfg["outputs"]["design_verdict"], verdict)
    print(json.dumps(verdict, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
