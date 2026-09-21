#!/usr/bin/env bash

# Deliberately retain the caller's terminal. Every gate is checked explicitly.
set +e
set +u
set +E
set +o pipefail 2>/dev/null || true
ulimit -c 0 2>/dev/null || true

CONFIG="configs/protocol/bh_simba_bondi_shadow_exact_binding_source_state_lifecycle_recovery_v1_4.json"
TEST_PATTERN="test_bh_simba_bondi_shadow_exact_binding_source_state_lifecycle_recovery.py"

# Resolve every current-run path and ID from the frozen v1.4 configuration. The
# loader rejects absolute/escaping paths, old unversioned run IDs, output/custody
# collisions, and any attempted substitution of the failed Run 217A authorities.
mapfile -t CFG_VALUES < <(python - "$CONFIG" <<'PY'
import json
import re
import sys
import unicodedata
from pathlib import PurePosixPath

KNOWN_FAILED_JSON = "outputs/protocol/simba_bondi_shadow_cli_manifest_repair/bh_simba_tng_shadow_manifest_concordance_preflight_217A.json"
KNOWN_FAILED_JSON_SHA256 = "69e61ee83341b66874c9986de5c02677756f5ecfd732aa5074c2d5274adb639b"
KNOWN_FAILED_CSV = "outputs/protocol/simba_bondi_shadow_cli_manifest_repair/bh_simba_tng_shadow_manifest_concordance_preflight_217A.csv"
KNOWN_FAILED_CSV_SHA256 = "f5cf87cbfc2d7ee26c7ac4b5962121ff577d376a6848b5e7dcbea90063aafcef"
KNOWN_RELEASE_FIELD_AUTHORITY = {
    "path": (
        "outputs/protocol/simba_bondi_adapter_field_identity/"
        "bh_simba_bondi_release_rooted_field_identity_verdict_209.json"
    ),
    "sha256": "52b0b76290cc7407745b09410ad180ba68c81d3f972b5bfc6955674f63d3d9c1",
    "run_id": "BH-SIMBA-BONDI-RELEASE-ROOTED-FIELD-IDENTITY-209",
    "exact_expected_bondi_storage_field_resolved": True,
    "expected_bondi_physical_semantics_resolved": False,
    "files": {
        (
            "outputs/protocol/simba_bondi_adapter_field_identity/"
            "bh_simba_bondi_release_rooted_field_identity_evidence_209.csv"
        ): {
            "sha256": "27e6552a0451b1996f1c89098e7d35c566942c77ef66e4d0094e01db9eebb4d9"
        }
    },
}
KNOWN_V12_ARTIFACTS = {
    "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_2/bh_simba_tng_shadow_runtime_manifest_lifecycle_inventory_217A_R1.csv": "04235363a559d838ae2b88be5abf34370794bfea7f50f37edcbc5cf16491ab20",
    "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_2/bh_simba_tng_shadow_runtime_manifest_lifecycle_freeze_217A_R1.json": "b1ecf67e4589c68cc64139e5cf4ab94c28d02a0bce2bb9fea5aa668d78db0b63",
    "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_2/bh_simba_tng_shadow_runtime_manifest_binding_preflight_217A_R2.csv": "8608f823736b1a0e5d53a5dbb4f0fb8a2991b2f9f8d82e12f96c685576e57236",
    "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_2/bh_simba_tng_shadow_runtime_manifest_binding_preflight_217A_R2.json": "989f542252a407e5535d639cf20b6a9609de30a42f513228f834045a99b79cc4",
}
KNOWN_V12_PATH_FIELDS = {
    "design_inventory": "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_2/bh_simba_tng_shadow_runtime_manifest_lifecycle_inventory_217A_R1.csv",
    "design_verdict": "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_2/bh_simba_tng_shadow_runtime_manifest_lifecycle_freeze_217A_R1.json",
    "preflight_evidence": "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_2/bh_simba_tng_shadow_runtime_manifest_binding_preflight_217A_R2.csv",
    "preflight_verdict": "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_2/bh_simba_tng_shadow_runtime_manifest_binding_preflight_217A_R2.json",
}
KNOWN_V13_ARTIFACTS = {
    "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_3/bh_simba_tng_shadow_cross_manifest_authority_inventory_217A_R3.csv": "f3cfc773798d9bf34110c2a3b17760475ec0373a2932249f9e130a1f0b773b38",
    "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_3/bh_simba_tng_shadow_cross_manifest_authority_freeze_217A_R3.json": "501ba3581957ba01c4580877e33bee972a4bd6b9e01e0dded01b2a14360ea90e",
}
KNOWN_V13_PATH_FIELDS = {
    "design_inventory": "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_3/bh_simba_tng_shadow_cross_manifest_authority_inventory_217A_R3.csv",
    "design_verdict": "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_3/bh_simba_tng_shadow_cross_manifest_authority_freeze_217A_R3.json",
}
KNOWN_OUTPUT_DIRECTORY = "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_4"
KNOWN_OUTPUT_NAMES = {
    "design_inventory": "bh_simba_tng_shadow_exact_binding_source_state_lifecycle_inventory_217A_R3A.csv",
    "design_verdict": "bh_simba_tng_shadow_exact_binding_source_state_lifecycle_freeze_217A_R3A.json",
    "preflight_evidence": "bh_simba_tng_shadow_exact_binding_source_state_lifecycle_preflight_217A_R4A.csv",
    "preflight_verdict": "bh_simba_tng_shadow_exact_binding_source_state_lifecycle_preflight_217A_R4A.json",
    "smoke_results": "bh_simba_tng_shadow_sequential_zero_offset_smoke_results_217B_R3.csv",
    "smoke_verdict": "bh_simba_tng_shadow_sequential_zero_offset_smoke_verdict_217B_R3.json",
    "acceptance_verdict": "bh_simba_tng_shadow_runtime_manifest_acceptance_freeze_217C_R3.json",
    "matrix_results": "bh_simba_tng_shadow_translation_matrix_results_218_R3.csv",
    "matrix_verdict": "bh_simba_tng_shadow_translation_matrix_verdict_218_R3.json",
    "adjudication_evidence": "bh_simba_bondi_shadow_translation_adjudication_evidence_219_R3.csv",
    "adjudication_verdict": "bh_simba_bondi_shadow_translation_adjudication_verdict_219_R3.json",
    "final_route": "bh_simba_bondi_shadow_rebinding_route_freeze_220_R3.json",
}
KNOWN_PROTOCOL_ENTRY = "paper/protocol_audit/bh_simba_bondi_shadow_rebinding_entry_128_v1_4.tex"
KNOWN_RUN_IDS = (
    "BH-SIMBA-TNG-SHADOW-EXACT-BINDING-SOURCE-STATE-LIFECYCLE-FREEZE-217A-R3A",
    "BH-SIMBA-TNG-SHADOW-EXACT-BINDING-SOURCE-STATE-LIFECYCLE-PREFLIGHT-217A-R4A",
    "BH-SIMBA-TNG-SHADOW-SEQUENTIAL-ZERO-OFFSET-SMOKE-217B-R3",
    "BH-SIMBA-TNG-SHADOW-RUNTIME-MANIFEST-ACCEPTANCE-FREEZE-217C-R3",
    "BH-SIMBA-TNG-SHADOW-TRANSLATION-MATRIX-218-R3",
    "BH-SIMBA-BONDI-SHADOW-TRANSLATION-ADJUDICATION-219-R3",
    "BH-SIMBA-BONDI-SHADOW-REBINDING-ROUTE-FREEZE-220-R3",
)
KNOWN_STAGE_ORDER = (
    "generator3_phase_b",
    "generator3_null_screen",
    "generator3_null_confirmation_2000",
    "generator4_pooled_innovation_screen",
)
KNOWN_STAGE_OUTPUTS = {
    "generator3_phase_b": (
        "bh_tng50_memory_generator3_sha256_phase_b",
        "outputs/protocol/tng50_memory_generator3_sha256_split/"
        "bh_tng50_memory_generator3_sha256_phase_b_verdict.json",
    ),
    "generator3_null_screen": (
        "bh_tng50_memory_generator3_sha256_full_history_null_screen",
        "outputs/protocol/tng50_memory_generator3_sha256_split/full_history_null/"
        "bh_tng50_memory_generator3_sha256_full_history_null_screen_verdict.json",
    ),
    "generator3_null_confirmation_2000": (
        "bh_tng50_memory_generator3_sha256_full_history_null_confirmation_2000",
        "outputs/protocol/tng50_memory_generator3_sha256_split/full_history_null_confirmation_2000/"
        "bh_tng50_memory_generator3_sha256_full_history_null_confirmation_2000_verdict.json",
    ),
    "generator4_pooled_innovation_screen": (
        "bh_tng50_memory_generator4_pooled_innovation_screen",
        "outputs/protocol/tng50_memory_generator4_pooled_innovation/"
        "bh_tng50_memory_generator4_pooled_innovation_screen_verdict.json",
    ),
}
KNOWN_GENERATOR4_OUTPUT_POLICY = (
    "declared_expected_path_must_equal_hash_pinned_config_root_label_and_filename_template"
)
KNOWN_SYNTHETIC_CONTRACT = {
    "seed": 200703,
    "track_count": 1200,
    "complete_tracks_per_split": 400,
    "required_splits": ["train", "validation", "test"],
    "steps_per_track": 48,
    "offsets": [-12.5, -3.0, 0.0, 7.25, 20.0],
    "baseline_offset": 0.0,
    "absolute_tolerance": 1e-12,
    "relative_tolerance": 1e-10,
    "stage_timeout_seconds": 900,
    "maximum_rows": 200000,
    "diagnostic_tail_characters": 20000,
    "track_plan_required_key": "selected_track_ids",
    "track_plan_each_required_split_exact_count": 400,
    "memory_tau_source_config_key": "selection.tau_track_fractions",
    "memory_tau_column_template": "memory_tau_{tau:g}",
    "require_every_configured_memory_tau_column": True,
    "classified_interface_failure_is_hold_not_negative_result": True,
}
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
KNOWN_EXACT_SOURCES = {
    "scripts/84_run_tng50_canonical_generator3_phase_b.py": "bd4d2abee49683804f86f3313c7867eb667aa15e51791b7e8257200e1fe8d684",
    "scripts/85_screen_tng50_canonical_generator3_full_history_null.py": "0fd976cc6a0955bb84182b1e99d1ca8d363ea489257f1880f335d8eef8418fe1",
    "scripts/89_screen_tng50_memory_generator4_pooled_innovation.py": "9eb669cd2684e544d228f8d8d71a3fe51154977d84a4ea232e522a719ff9d4b8",
    "src/core/predictive_memory.py": "041ae4802059af87d7b1a99bdc9bbaad564543424c4ea55f6e0f33ad23695625",
    "src/core/causal_memory.py": "871a77690c0d39dd88a888c53a868200ce754fa1f78eaa01cc08e94daf537d76",
    "src/core/memory_nulls.py": "e5fd52e4bee13a710d0b24b63249599495c5380c55048eeeacfe5512612d1afb",
    "src/core/innovation_memory.py": "6e82ca529896de10e5b18bdc166597577018d30aa1c2ec81173920a999087244",
}
KNOWN_SHADOW_PACKAGE_SCAFFOLDS = {
    "schema_version": 1,
    "source_precondition": "absent_or_exact_empty_regular_contained_single_link",
    "shadow_construction": "exact_empty_atomic_shadow_only",
    "source_mutation": False,
    "paths": {
        "src/__init__.py": {"sha256": EMPTY_SHA256, "bytes": 0},
        "src/core/__init__.py": {"sha256": EMPTY_SHA256, "bytes": 0},
        "scripts/__init__.py": {"sha256": EMPTY_SHA256, "bytes": 0},
    },
}
KNOWN_SCHEMA_SPECIFIC_BINDINGS = [{
    "schema_version": 1,
    "binding_id": "generator4_exact_g3_track_plan_sha256_v1",
    "stage": "generator4_pooled_innovation_screen",
    "path_dotted_key": "data.canonical_g3_track_plan",
    "digest_dotted_key": "screen.exact_g3_track_plan_sha256",
    "algorithm": "sha256",
    "consumer_proof": "pinned_executor_ast_same_path_sha256_guard",
}]
KNOWN_RUNTIME_RECEIPT_FIELDS = [
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
]
KNOWN_LIVE_REPLAY = {
    "schema_version": 1,
    "run_offset_module": "scripts/bh_simba_shadow_exact_binding_source_state_lifecycle_recovery_v1_4.py",
    "run_offset_module_sha256": "1869e5eeca1620ae30f46756d204de5630ff0b9d7fe3f3e79cb59838086529bb",
    "expected_fresh_temporary_shadows": 5,
    "expected_actual_executor_invocations": 20,
    "attestation_limit": "integrity_and_honest_code_execution_evidence_not_adversarial_process_attestation",
}


def safe_relative(value, label, *, basename=False):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty single-line string")
    if "\\" in value or any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError(f"{label} contains a forbidden separator or control character")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError(f"{label} must use canonical NFC text")
    if re.match(r"^[A-Za-z]:", value):
        raise ValueError(f"{label} must not use a drive-qualified path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"{label} is not a safe relative path: {value!r}")
    if path.as_posix() != value:
        raise ValueError(f"{label} is not one canonical POSIX relative path: {value!r}")
    if basename and len(path.parts) != 1:
        raise ValueError(f"{label} must be a filename beneath outputs.directory")
    return path.as_posix()


def text(value, label):
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise ValueError(f"{label} must be a nonempty single-line string")
    return value


def pick(mapping, names, label):
    for name in names:
        if name in mapping:
            return mapping[name]
    raise KeyError(f"missing {label}; accepted keys: {', '.join(names)}")


try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        cfg = json.load(handle)
    if cfg.get("bundle_version") != "1.4":
        raise ValueError("bundle_version must be 1.4")
    outputs = cfg["outputs"]
    failed = cfg["failed_run_217A"]
    if not isinstance(outputs, dict) or not isinstance(failed, dict):
        raise TypeError("outputs and failed_run_217A must be objects")
    release_field_authority = cfg.get("release_field_authority")
    if release_field_authority != KNOWN_RELEASE_FIELD_AUTHORITY:
        raise ValueError("Run 209 release-field authority must equal the exact frozen verdict/evidence pin")
    if cfg.get("inputs", {}).get("prior_release_field_verdict") != release_field_authority["path"]:
        raise ValueError("inputs.prior_release_field_verdict must equal the frozen Run 209 verdict path")
    safe_relative(release_field_authority["path"], "release_field_authority.path")
    for name, record in release_field_authority["files"].items():
        safe_relative(name, "release_field_authority.files path")
        if not isinstance(record, dict) or set(record) != {"sha256"}:
            raise ValueError("Run 209 evidence pin must contain only one exact SHA-256 record")
    if not isinstance(failed.get("expected_fields"), dict) or not isinstance(failed.get("expected_evidence"), dict):
        raise TypeError("failed_run_217A expected_fields and expected_evidence must be objects")
    if failed.get("disposition") != "immutable_failed_prerequisite_not_overwritten":
        raise ValueError("failed_run_217A disposition must freeze immutable failed-prerequisite custody")
    prior_attempt = cfg.get("prior_attempt_custody")
    if not isinstance(prior_attempt, dict) or prior_attempt.get("disposition") != "immutable_failed_prerequisite_not_overwritten":
        raise ValueError("prior_attempt_custody must freeze immutable v1.2 R1/R2 custody")
    observed_v12 = {
        safe_relative(path, "prior_attempt_custody artifact"): record.get("sha256")
        for path, record in prior_attempt.get("artifacts", {}).items()
        if isinstance(record, dict)
    }
    if observed_v12 != KNOWN_V12_ARTIFACTS:
        raise ValueError("prior_attempt_custody must name the four exact v1.2 R1/R2 artifacts")
    observed_v12_fields = {
        key: safe_relative(prior_attempt.get(key), f"prior_attempt_custody.{key}")
        for key in KNOWN_V12_PATH_FIELDS
    }
    if observed_v12_fields != KNOWN_V12_PATH_FIELDS:
        raise ValueError("prior_attempt_custody path roles must name the exact v1.2 R1/R2 artifacts")
    prior_v13 = cfg.get("prior_v1_3_attempt_custody")
    if not isinstance(prior_v13, dict) or prior_v13.get("disposition") != "immutable_failed_prerequisite_not_overwritten":
        raise ValueError("prior_v1_3_attempt_custody must freeze immutable v1.3 R3 custody")
    observed_v13 = {
        safe_relative(path, "prior_v1_3_attempt_custody artifact"): record.get("sha256")
        for path, record in prior_v13.get("artifacts", {}).items()
        if isinstance(record, dict)
    }
    if observed_v13 != KNOWN_V13_ARTIFACTS:
        raise ValueError("prior_v1_3_attempt_custody must name the two exact held v1.3 R3 artifacts")
    observed_v13_fields = {
        key: safe_relative(prior_v13.get(key), f"prior_v1_3_attempt_custody.{key}")
        for key in KNOWN_V13_PATH_FIELDS
    }
    if observed_v13_fields != KNOWN_V13_PATH_FIELDS:
        raise ValueError("prior_v1_3_attempt_custody path roles must name the exact held v1.3 R3 artifacts")
    if any((
        prior_v13.get("bundle_version") != "1.3",
        prior_v13.get("bundle_sha256") != "229f4fc33fa6cafc3ff9e7476bc02e8770d705aa6e43833d162366d75d71fa2c",
        prior_v13.get("accepted_downstream_stage_invocations") != 0,
        prior_v13.get("protocol_entry_written") is not False,
    )):
        raise ValueError("prior_v1_3_attempt_custody status or bundle identity changed")

    output_directory = safe_relative(outputs["directory"], "outputs.directory")
    output_keys = (
        "design_inventory", "design_verdict", "preflight_evidence",
        "preflight_verdict", "smoke_results", "smoke_verdict",
        "acceptance_verdict", "matrix_results", "matrix_verdict",
        "adjudication_evidence", "adjudication_verdict", "final_route",
    )
    output_mapping = {
        key: safe_relative(outputs[key], f"outputs.{key}", basename=True)
        for key in output_keys
    }
    output_names = list(output_mapping.values())
    if len(set(output_names)) != len(output_names):
        raise ValueError("all current-run output filenames must be distinct")
    protocol_entry = safe_relative(outputs["protocol_entry"], "outputs.protocol_entry")
    if output_directory != KNOWN_OUTPUT_DIRECTORY or output_mapping != KNOWN_OUTPUT_NAMES:
        raise ValueError("current v1.4 output directory and filenames must remain exact and isolated")
    if protocol_entry != KNOWN_PROTOCOL_ENTRY:
        raise ValueError("the current Protocol Entry 128 path must be the exact isolated v1.4 path")

    run_id_keys = (
        "cli_repair_design_run_id", "manifest_preflight_run_id", "smoke_run_id",
        "acceptance_run_id", "matrix_run_id", "adjudication_run_id",
        "final_route_run_id",
    )
    run_ids = [text(cfg[key], key) for key in run_id_keys]
    required_suffixes = (
        "217A-R3A", "217A-R4A", "217B-R3", "217C-R3", "218-R3", "219-R3", "220-R3",
    )
    if any(not run_id.endswith(suffix) for run_id, suffix in zip(run_ids, required_suffixes)):
        raise ValueError("the seven v1.4 run IDs must end in 217A-R3A through 220-R3")
    if tuple(run_ids) != KNOWN_RUN_IDS:
        raise ValueError("the seven v1.4 run IDs must equal the frozen authority-resolution route")
    stages = cfg.get("stage_contracts")
    synthetic = cfg.get("synthetic_contract")
    if not isinstance(stages, list) or tuple(stage.get("stage") for stage in stages if isinstance(stage, dict)) != KNOWN_STAGE_ORDER:
        raise ValueError("the production four-stage dependency order must remain exact")
    for stage in stages:
        name = stage["stage"]
        contract = stage.get("fresh_output_contract")
        if not isinstance(contract, dict):
            raise ValueError(f"{name} must declare a fresh-output contract")
        label, expected_path = KNOWN_STAGE_OUTPUTS[name]
        if (
            contract.get("config_dotted_path_mapping")
            != {"root": "outputs.root", "label": "outputs.label"}
            or contract.get("filename_template") != "{outputs.label}_verdict.json"
            or contract.get("expected_label") != label
            or contract.get("expected_relative_path") != expected_path
            or safe_relative(expected_path, f"{name} expected output") != expected_path
        ):
            raise ValueError(f"{name} output root/label/template/path contract must remain exact")
    if (
        stages[-1]["fresh_output_contract"].get("expected_relative_path_policy")
        != KNOWN_GENERATOR4_OUTPUT_POLICY
    ):
        raise ValueError("the generator4 declared-versus-derived output-path policy must remain exact")
    if synthetic != KNOWN_SYNTHETIC_CONTRACT:
        raise ValueError("the production synthetic fixture and matrix contract must remain exact")
    if cfg.get("exact_sources") != KNOWN_EXACT_SOURCES:
        raise ValueError("exact_sources must equal the seven regular-file source authorities")
    if cfg.get("shadow_package_scaffolds") != KNOWN_SHADOW_PACKAGE_SCAFFOLDS:
        raise ValueError("shadow_package_scaffolds must equal the three exact-empty shadow-only initializers")
    if cfg.get("authority_resolution", {}).get("schema_specific_config_integrity_bindings") != KNOWN_SCHEMA_SPECIFIC_BINDINGS:
        raise ValueError("the sole Generator-4 schema-specific cross-mapping binding must remain exact")
    receipt_fields = cfg.get("runtime_binding", {}).get("receipt_schema", {}).get("required_fields")
    if receipt_fields != KNOWN_RUNTIME_RECEIPT_FIELDS:
        raise ValueError("the runtime binding receipt schema must contain the exact ordered 22 fields")
    if cfg.get("adjudication_live_replay") != KNOWN_LIVE_REPLAY:
        raise ValueError("Run 219 must freeze the exact hash-pinned 4x5 honest-code live replay")
    if len(stages) * len(synthetic["offsets"]) != 20:
        raise ValueError("the production matrix must remain exactly four stages by five offsets")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("the seven current-run IDs must be distinct")

    failed_json = safe_relative(
        pick(failed, ("verdict", "verdict_path", "json", "json_path"), "failed Run 217A verdict path"),
        "failed_run_217A verdict path",
    )
    failed_json_sha = text(
        pick(failed, ("verdict_sha256", "json_sha256"), "failed Run 217A verdict digest"),
        "failed_run_217A verdict digest",
    ).lower()
    failed_csv = safe_relative(
        pick(failed, ("evidence", "evidence_path", "csv", "csv_path"), "failed Run 217A evidence path"),
        "failed_run_217A evidence path",
    )
    failed_csv_sha = text(
        pick(failed, ("evidence_sha256", "csv_sha256"), "failed Run 217A evidence digest"),
        "failed_run_217A evidence digest",
    ).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", failed_json_sha) or not re.fullmatch(r"[0-9a-f]{64}", failed_csv_sha):
        raise ValueError("failed Run 217A digests must be lowercase SHA-256 strings")
    if (failed_json, failed_json_sha, failed_csv, failed_csv_sha) != (
        KNOWN_FAILED_JSON, KNOWN_FAILED_JSON_SHA256, KNOWN_FAILED_CSV, KNOWN_FAILED_CSV_SHA256,
    ):
        raise ValueError("failed Run 217A custody must name the exact known JSON/CSV authorities")

    current_paths = {f"{output_directory}/{name}" for name in output_names}
    if failed_json in current_paths or failed_csv in current_paths:
        raise ValueError("current v1.4 outputs must not overlap failed Run 217A custody")
    if current_paths & set(KNOWN_V12_ARTIFACTS):
        raise ValueError("current v1.4 outputs must not overlap v1.2 R1/R2 custody")
    if current_paths & set(KNOWN_V13_ARTIFACTS):
        raise ValueError("current v1.4 outputs must not overlap held v1.3 R3 custody")
    protected_protocol_targets = {
        safe_relative(sys.argv[1], "runner config path"),
        failed_json,
        failed_csv,
        *KNOWN_V12_ARTIFACTS,
        *KNOWN_V13_ARTIFACTS,
    }
    for name, value in cfg.get("inputs", {}).items():
        protected_protocol_targets.add(safe_relative(value, f"inputs.{name}"))
    protected_protocol_targets.add(safe_relative(
        release_field_authority["path"], "release_field_authority.path"
    ))
    for name in release_field_authority["files"]:
        protected_protocol_targets.add(safe_relative(name, "release_field_authority.files path"))
    for name in cfg.get("exact_sources", {}):
        protected_protocol_targets.add(safe_relative(name, f"exact_sources.{name}"))
    for name in cfg.get("shadow_package_scaffolds", {}).get("paths", {}):
        protected_protocol_targets.add(safe_relative(name, f"shadow_package_scaffolds.paths.{name}"))
    protected_protocol_targets.add(safe_relative(
        cfg["adjudication_live_replay"]["run_offset_module"],
        "adjudication_live_replay.run_offset_module",
    ))
    for index, stage in enumerate(cfg.get("stage_contracts", [])):
        if not isinstance(stage, dict):
            raise TypeError(f"stage_contracts[{index}] must be an object")
        for field in ("executor", "config", "manifest"):
            protected_protocol_targets.add(
                safe_relative(stage[field], f"stage_contracts[{index}].{field}")
            )
    if protocol_entry in current_paths:
        raise ValueError("outputs.protocol_entry must not overlap a current verdict or evidence artifact")
    if protocol_entry in protected_protocol_targets:
        raise ValueError("outputs.protocol_entry must not overlap historical, config, source, or stage authority custody")

    values = [
        output_directory, *output_names, protocol_entry, *run_ids,
        failed_json, failed_json_sha, failed_csv, failed_csv_sha,
    ]
    for value in values:
        print(value)
except Exception as error:
    print(f"[hold] invalid v1.4 runner configuration: {type(error).__name__}:{error}", file=sys.stderr)
PY
)

CONFIG_LOAD_RC=0
if [ "${#CFG_VALUES[@]}" -ne 25 ]; then
  CONFIG_LOAD_RC=2
  echo "[hold] v1.4 configuration did not yield the exact 25-field runner contract"
fi

OUT=""
DESIGN_INVENTORY=""
DESIGN=""
PREFLIGHT_EVIDENCE=""
PREFLIGHT=""
SMOKE_RESULTS=""
SMOKE=""
ACCEPT=""
MATRIX_RESULTS=""
MATRIX=""
ADJ_EVIDENCE=""
ADJ=""
FINAL=""
ENTRY=""
DESIGN_RUN_ID=""
PREFLIGHT_RUN_ID=""
SMOKE_RUN_ID=""
ACCEPT_RUN_ID=""
MATRIX_RUN_ID=""
ADJ_RUN_ID=""
FINAL_RUN_ID=""
FAILED_217A_JSON=""
FAILED_217A_JSON_SHA256=""
FAILED_217A_CSV=""
FAILED_217A_CSV_SHA256=""

if [ "$CONFIG_LOAD_RC" -eq 0 ]; then
  OUT="${CFG_VALUES[0]}"
  DESIGN_INVENTORY="$OUT/${CFG_VALUES[1]}"
  DESIGN="$OUT/${CFG_VALUES[2]}"
  PREFLIGHT_EVIDENCE="$OUT/${CFG_VALUES[3]}"
  PREFLIGHT="$OUT/${CFG_VALUES[4]}"
  SMOKE_RESULTS="$OUT/${CFG_VALUES[5]}"
  SMOKE="$OUT/${CFG_VALUES[6]}"
  ACCEPT="$OUT/${CFG_VALUES[7]}"
  MATRIX_RESULTS="$OUT/${CFG_VALUES[8]}"
  MATRIX="$OUT/${CFG_VALUES[9]}"
  ADJ_EVIDENCE="$OUT/${CFG_VALUES[10]}"
  ADJ="$OUT/${CFG_VALUES[11]}"
  FINAL="$OUT/${CFG_VALUES[12]}"
  ENTRY="${CFG_VALUES[13]}"
  DESIGN_RUN_ID="${CFG_VALUES[14]}"
  PREFLIGHT_RUN_ID="${CFG_VALUES[15]}"
  SMOKE_RUN_ID="${CFG_VALUES[16]}"
  ACCEPT_RUN_ID="${CFG_VALUES[17]}"
  MATRIX_RUN_ID="${CFG_VALUES[18]}"
  ADJ_RUN_ID="${CFG_VALUES[19]}"
  FINAL_RUN_ID="${CFG_VALUES[20]}"
  FAILED_217A_JSON="${CFG_VALUES[21]}"
  FAILED_217A_JSON_SHA256="${CFG_VALUES[22]}"
  FAILED_217A_CSV="${CFG_VALUES[23]}"
  FAILED_217A_CSV_SHA256="${CFG_VALUES[24]}"
fi

custody_check() {
  python - "$CONFIG" "$FAILED_217A_JSON" "$FAILED_217A_JSON_SHA256" "$FAILED_217A_CSV" "$FAILED_217A_CSV_SHA256" <<'PY'
import csv
import hashlib
import io
import json
import os
import stat
import sys
from pathlib import Path


def stable_bytes(path):
    """Read one regular-file snapshot for both digest and semantic checks."""
    before_path = path.lstat()
    if stat.S_ISLNK(before_path.st_mode) or not stat.S_ISREG(before_path.st_mode):
        raise ValueError(f"custody authority is not a regular non-symlink file: {path}")
    with path.open("rb") as handle:
        before_fd = os.fstat(handle.fileno())
        payload = handle.read()
        after_fd = os.fstat(handle.fileno())
    after_path = path.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    before_fd_key = tuple(getattr(before_fd, field) for field in fields)
    after_fd_key = tuple(getattr(after_fd, field) for field in fields)
    before_path_key = tuple(getattr(before_path, field) for field in fields)
    after_path_key = tuple(getattr(after_path, field) for field in fields)
    if not (before_fd_key == after_fd_key == before_path_key == after_path_key):
        raise ValueError(f"custody authority changed during snapshot: {path}")
    if len(payload) != before_fd.st_size:
        raise ValueError(f"custody authority byte count changed during snapshot: {path}")
    return payload


def digest_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


try:
    root = Path.cwd().resolve(strict=True)
    cfg = json.loads((root / sys.argv[1]).read_text(encoding="utf-8"))
    custody = cfg["failed_run_217A"]
    if custody.get("disposition") != "immutable_failed_prerequisite_not_overwritten":
        raise ValueError("configuration does not preserve failed-prerequisite custody")
    checked = []
    for relative, expected in ((sys.argv[2], sys.argv[3]), (sys.argv[4], sys.argv[5])):
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"custody authority is missing, non-regular, or a symlink: {relative}")
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise ValueError(f"custody authority escapes repository root: {relative}") from error
        current = root
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"custody authority ancestry contains a symlink: {relative}")
        payload = stable_bytes(path)
        observed = digest_bytes(payload)
        if observed != expected:
            raise ValueError(f"custody digest mismatch for {relative}: {observed}")
        checked.append((path, payload))

    verdict = json.loads(checked[0][1].decode("utf-8"))
    if verdict.get("run_id") != "BH-SIMBA-TNG-SHADOW-MANIFEST-CONCORDANCE-PREFLIGHT-217A":
        raise ValueError("custody JSON does not carry the failed Run 217A run_id")
    if verdict.get("manifest_concordance_preflight_pass") is not False:
        raise ValueError("custody JSON is not the failed Run 217A verdict")

    def require_subset(actual, expected, prefix=""):
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                raise ValueError(f"custody expected object missing at {prefix or '<root>'}")
            for key, value in expected.items():
                if key not in actual:
                    raise ValueError(f"custody expected field missing: {prefix}{key}")
                require_subset(actual[key], value, f"{prefix}{key}.")
        elif actual != expected:
            raise ValueError(f"custody expected-field mismatch at {prefix[:-1]}")

    require_subset(verdict, custody["expected_fields"])
    rows = list(csv.DictReader(io.StringIO(checked[1][1].decode("utf-8"), newline="")))
    if not rows:
        raise ValueError("custody CSV is empty")
    runtime_target = cfg["runtime_binding"]["target_relative_path"]
    runtime_rows = [row for row in rows if row.get("relative_path") == runtime_target]
    observed_evidence = {
        "row_count": len(rows),
        "runtime_target_binding_count": len(runtime_rows),
        "preexisting_concordant_row_count": sum(row.get("status") == "preexisting_concordant" for row in rows),
        "runtime_target_missing_from_shared_manifest_count": sum(
            row.get("manifest_record_present", "").lower() == "false" for row in runtime_rows
        ),
        "runtime_target_declared_only_in_confirmation_template_count": sum(
            row.get("manifest_record_present", "").lower() == "true" for row in runtime_rows
        ),
    }
    if observed_evidence != custody["expected_evidence"]:
        raise ValueError(f"custody CSV semantic summary mismatch: {observed_evidence}")
    prior = cfg["prior_attempt_custody"]
    if prior.get("disposition") != "immutable_failed_prerequisite_not_overwritten":
        raise ValueError("v1.2 prior-attempt disposition changed")
    exact_prior_paths = {
        "design_inventory": "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_2/bh_simba_tng_shadow_runtime_manifest_lifecycle_inventory_217A_R1.csv",
        "design_verdict": "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_2/bh_simba_tng_shadow_runtime_manifest_lifecycle_freeze_217A_R1.json",
        "preflight_evidence": "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_2/bh_simba_tng_shadow_runtime_manifest_binding_preflight_217A_R2.csv",
        "preflight_verdict": "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_2/bh_simba_tng_shadow_runtime_manifest_binding_preflight_217A_R2.json",
    }
    if any(prior.get(key) != value for key, value in exact_prior_paths.items()):
        raise ValueError("v1.2 R1/R2 custody path roles changed")
    if any((
        prior.get("bundle_version") != "1.2",
        prior.get("bundle_sha256") != "f29663e340a0e87651fd2ad5245216db23ec31fd0d4555afbab7edcaf1302588",
        prior.get("accepted_downstream_stage_invocations") != 0,
        prior.get("protocol_entry_written") is not False,
    )):
        raise ValueError("v1.2 failed-attempt status or bundle identity changed")
    prior_paths = {}
    prior_payloads = {}
    for relative, record in prior["artifacts"].items():
        path = root / relative
        expected = record.get("sha256") if isinstance(record, dict) else None
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"v1.2 custody authority is missing or unsafe: {relative}")
        payload = stable_bytes(path)
        if digest_bytes(payload) != expected:
            raise ValueError(f"v1.2 custody digest mismatch: {relative}")
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        current = root
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"v1.2 custody ancestry contains a symlink: {relative}")
        prior_paths[relative] = path
        prior_payloads[relative] = payload

    def subset(actual, expected):
        if isinstance(expected, dict):
            return isinstance(actual, dict) and all(key in actual and subset(actual[key], value) for key, value in expected.items())
        return actual == expected

    design = json.loads(prior_payloads[prior["design_verdict"]].decode("utf-8"))
    preflight = json.loads(prior_payloads[prior["preflight_verdict"]].decode("utf-8"))
    if not subset(design, prior["expected_design_fields"]):
        raise ValueError("v1.2 R1 design semantics changed")
    if not subset(preflight, prior["expected_preflight_fields"]):
        raise ValueError("v1.2 R2 failed-preflight semantics changed")
    design_digest = digest_bytes(prior_payloads[prior["design_verdict"]])
    design_inventory_digest = digest_bytes(prior_payloads[prior["design_inventory"]])
    preflight_evidence_digest = digest_bytes(prior_payloads[prior["preflight_evidence"]])
    if preflight.get("predecessor_verdicts") != {
        "design_run_id": "BH-SIMBA-TNG-SHADOW-RUNTIME-MANIFEST-LIFECYCLE-FREEZE-217A-R1",
        "design_verdict_sha256": design_digest,
    }:
        raise ValueError("v1.2 R2 predecessor digest chain changed")
    if design.get("artifacts") != {
        Path(prior["design_inventory"]).name: {"sha256": design_inventory_digest}
    }:
        raise ValueError("v1.2 R1 inventory linkage changed")
    if preflight.get("artifacts") != {
        Path(prior["preflight_evidence"]).name: {"sha256": preflight_evidence_digest}
    }:
        raise ValueError("v1.2 R2 evidence linkage changed")
    preflight_rows = list(csv.DictReader(io.StringIO(
        prior_payloads[prior["preflight_evidence"]].decode("utf-8"), newline=""
    )))
    if len(preflight_rows) != prior["expected_preflight_evidence_rows"]:
        raise ValueError("v1.2 R2 evidence row count changed")
    if os.path.lexists(root / "paper/protocol_audit/bh_simba_bondi_shadow_rebinding_entry_128_v1_2.tex"):
        raise ValueError("v1.2 Entry 128 unexpectedly exists")
    prior_v13 = cfg["prior_v1_3_attempt_custody"]
    exact_v13_paths = {
        "design_inventory": "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_3/bh_simba_tng_shadow_cross_manifest_authority_inventory_217A_R3.csv",
        "design_verdict": "outputs/protocol/simba_bondi_shadow_cli_manifest_repair_v1_3/bh_simba_tng_shadow_cross_manifest_authority_freeze_217A_R3.json",
    }
    if prior_v13.get("disposition") != "immutable_failed_prerequisite_not_overwritten":
        raise ValueError("v1.3 prior-attempt disposition changed")
    if any(prior_v13.get(key) != value for key, value in exact_v13_paths.items()):
        raise ValueError("v1.3 held R3 custody path roles changed")
    if any((
        prior_v13.get("bundle_version") != "1.3",
        prior_v13.get("bundle_sha256") != "229f4fc33fa6cafc3ff9e7476bc02e8770d705aa6e43833d162366d75d71fa2c",
        prior_v13.get("accepted_downstream_stage_invocations") != 0,
        prior_v13.get("protocol_entry_written") is not False,
    )):
        raise ValueError("v1.3 held-attempt status or bundle identity changed")
    v13_payloads = {}
    for relative, record in prior_v13.get("artifacts", {}).items():
        path = root / relative
        expected = record.get("sha256") if isinstance(record, dict) else None
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"v1.3 custody authority is missing or unsafe: {relative}")
        payload = stable_bytes(path)
        if digest_bytes(payload) != expected:
            raise ValueError(f"v1.3 custody digest mismatch: {relative}")
        path.resolve(strict=True).relative_to(root)
        current = root
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"v1.3 custody ancestry contains a symlink: {relative}")
        v13_payloads[relative] = payload
    if set(v13_payloads) != set(prior_v13.get("artifacts", {})) or len(v13_payloads) != 2:
        raise ValueError("v1.3 custody must contain exactly the held R3 inventory and verdict")
    v13_design = json.loads(v13_payloads[prior_v13["design_verdict"]].decode("utf-8"))
    if not subset(v13_design, prior_v13["expected_design_fields"]):
        raise ValueError("v1.3 held R3 design semantics changed")
    v13_inventory_digest = digest_bytes(v13_payloads[prior_v13["design_inventory"]])
    if v13_design.get("artifacts") != {
        Path(prior_v13["design_inventory"]).name: {"sha256": v13_inventory_digest}
    }:
        raise ValueError("v1.3 held R3 inventory linkage changed")
    if os.path.lexists(root / "paper/protocol_audit/bh_simba_bondi_shadow_rebinding_entry_128_v1_3.tex"):
        raise ValueError("v1.3 Entry 128 unexpectedly exists")
    print("failed_Run217A_custody_exact=true")
    print("failed_v1_2_R1_R2_custody_exact=true")
    print("failed_v1_3_R3_custody_exact=true")
except Exception as error:
    print(f"[hold] failed-attempt custody check failed: {type(error).__name__}:{error}", file=sys.stderr)
    raise SystemExit(2)
PY
}

output_directory_check() {
  python - "$OUT" <<'PY'
import os
import sys
from pathlib import Path, PurePosixPath

try:
    root = Path.cwd().resolve(strict=True)
    supplied = sys.argv[1]
    relative = PurePosixPath(supplied)
    if relative.is_absolute() or relative.as_posix() != supplied or any(part in ("", ".", "..") for part in relative.parts):
        raise ValueError("current output directory is not one canonical relative path")
    current = root
    for part in relative.parts:
        current = current / part
        if not os.path.lexists(current):
            raise ValueError(f"current output directory component is missing: {current.relative_to(root)}")
        if current.is_symlink() or not current.is_dir():
            raise ValueError(f"current output directory component is unsafe: {current.relative_to(root)}")
    current.resolve(strict=True).relative_to(root)
except Exception as error:
    print(f"[hold] current v1.4 output-directory path check failed: {type(error).__name__}:{error}", file=sys.stderr)
    raise SystemExit(2)
PY
}

validate_verdict() {
  python - "$1" "$2" "$3" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_id = sys.argv[2]
kind = sys.argv[3]
try:
    if path.is_symlink() or not path.is_file():
        raise ValueError("verdict is missing, non-regular, or a symlink")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("run_id") != expected_id:
        raise ValueError("run_id is not the exact current configured run")

    if kind == "design":
        ok = data.get("lifecycle_repair_design_freeze_pass") is True
    elif kind == "preflight":
        ok = data.get("runtime_manifest_preflight_pass") is True
    elif kind == "smoke":
        ok = all((
            data.get("sequential_smoke_pass") is True,
            data.get("smoke_process_pass") is True,
            data.get("expected_stage_invocations") == 4,
            data.get("attempted_stage_invocations") == 4,
            data.get("successful_stage_invocations") == 4,
            data.get("all_four_stages_executed_sequentially") is True,
            data.get("runtime_binding_receipt_count") == 1,
            data.get("runtime_binding_receipts_pass") is True,
            data.get("runtime_binding_provenance_chain_pass") is True,
            data.get("full_manifest_closure_pass") is True,
            data.get("all_expected_outputs_fresh_exact") is True,
            data.get("interface_hold") is False,
        ))
    elif kind == "acceptance":
        ok = all((
            data.get("smoke_acceptance_freeze_pass") is True,
            data.get("matrix_execution_authorized") is True,
        ))
    elif kind == "matrix":
        resolved = data.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved") is True
        rejected = data.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected") is True
        ok = all((
            data.get("matrix_process_pass") is True,
            data.get("expected_stage_invocations") == 20,
            data.get("attempted_stage_invocations") == 20,
            data.get("successful_stage_invocations") == 20,
            data.get("matrix_complete") is True,
            data.get("all_four_stages_executed_at_all_offsets") is True,
            data.get("runtime_binding_receipt_count") == 5,
            data.get("runtime_binding_receipts_pass") is True,
            data.get("runtime_binding_provenance_chain_pass") is True,
            data.get("full_manifest_closure_pass") is True,
            data.get("all_expected_outputs_fresh_exact") is True,
            data.get("interface_hold") is False,
            resolved != rejected,
        ))
    elif kind == "adjudication":
        resolved = data.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved") is True
        rejected = data.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected") is True
        replay = data.get("live_replay_receipt")
        audit = data.get("live_replay_audit")
        ok = all((
            data.get("adjudication_pass") is True,
            resolved != rejected,
            data.get("selected_output_admission_tested_synthetic_shift_axis_closed") is True,
            data.get("live_replay_pass") is True,
            isinstance(replay, dict),
            replay.get("fresh_temporary_shadow_count") == 5 if isinstance(replay, dict) else False,
            replay.get("expected_stage_invocations") == 20 if isinstance(replay, dict) else False,
            replay.get("attempted_stage_invocations") == 20 if isinstance(replay, dict) else False,
            replay.get("successful_stage_invocations") == 20 if isinstance(replay, dict) else False,
            replay.get("actual_executor_invoked_rc0_lifecycle_pass_count") == 20 if isinstance(replay, dict) else False,
            replay.get("live_replay_pass") is True if isinstance(replay, dict) else False,
            isinstance(audit, dict) and set(audit) == {"rows", "metrics", "audits"},
            len(audit.get("rows", [])) == 20 if isinstance(audit, dict) else False,
            len(audit.get("metrics", [])) == 20 if isinstance(audit, dict) else False,
            len(audit.get("audits", [])) == 5 if isinstance(audit, dict) else False,
            data.get("physical_units_resolved") is False,
            data.get("native_unit_coordinate_fallback_authorized") is False,
            data.get("scientific_execution_ready") is False,
            data.get("negative_memory_result") is False,
        ))
    elif kind == "final":
        resolved = data.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved") is True
        rejected = data.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected") is True
        ok = all((
            data.get("final_route_pass") is True,
            data.get("matrix_complete") is True,
            data.get("logbook_entry_written") is True,
            data.get("entry_install_transaction_state") == "committed",
            isinstance(data.get("entry_install_transaction"), dict),
            resolved != rejected,
            data.get("selected_output_admission_tested_synthetic_shift_axis_closed") is True,
            data.get("physical_units_resolved") is False,
            data.get("native_unit_coordinate_fallback_authorized") is False,
            data.get("scientific_execution_ready") is False,
            data.get("negative_memory_result") is False,
        ))
    else:
        raise ValueError(f"unknown verdict kind: {kind}")
    if not ok:
        raise ValueError(f"{kind} verdict failed its exact current-run acceptance contract")
except Exception as error:
    print(f"[hold] current verdict validation failed for {path}: {type(error).__name__}:{error}", file=sys.stderr)
    raise SystemExit(2)
PY
}

print_current_verdict() {
  python - "$1" "$2" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception as error:
    print(f"[hold] current verdict is unreadable: {path}: {type(error).__name__}:{error}")
    raise SystemExit(0)
if data.get("run_id") != sys.argv[2]:
    print(f"[hold] refusing to present non-current artifact: {path}")
    raise SystemExit(0)
print()
print(f"=== {path.name} ===")
for key in (
    "run_id", "lifecycle_repair_design_freeze_pass", "runtime_manifest_preflight_pass",
    "sequential_smoke_pass", "smoke_process_pass", "all_four_stages_executed_sequentially",
    "runtime_binding_receipt_count", "runtime_binding_receipts_pass",
    "runtime_binding_provenance_chain_pass", "full_manifest_closure_pass",
    "all_expected_outputs_fresh_exact", "smoke_acceptance_freeze_pass",
    "matrix_execution_authorized", "matrix_process_pass", "interface_hold", "hold_reason",
    "expected_stage_invocations", "attempted_stage_invocations", "successful_stage_invocations",
    "matrix_complete", "all_four_stages_executed_at_all_offsets", "stage_invariance",
    "adjudication_pass", "final_route_pass", "disposition", "logbook_entry_written",
    "physical_units_resolved", "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved",
    "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected", "selected_output_admission_tested_synthetic_shift_axis_closed",
    "native_unit_coordinate_fallback_authorized", "scientific_execution_ready",
    "negative_memory_result", "next_gate",
):
    if key in data:
        print(f"{key}: {data[key]}")
PY
}

print_gate_state() {
  GATE_LABEL="$1"
  GATE_EXECUTED="$2"
  GATE_RC="$3"
  if [ "$GATE_EXECUTED" -eq 1 ]; then
    echo "$GATE_LABEL: executed; exit code=$GATE_RC"
  elif [ "$GATE_RC" -eq 0 ]; then
    echo "$GATE_LABEL: not required; status code=0"
  else
    echo "$GATE_LABEL: not started; initialized hold code=$GATE_RC"
  fi
}

TEST_RC=1
RUN_LOCK_RC=1
RUN_LOCK_FD_OPEN=0
CUSTODY_PRE_RC=1
QUARANTINE_RC=1
RUN217AR3_RC=1
RUN217AR4_RC=1
RUN217BR3_RC=1
RUN217CR3_RC=1
RUN218R3_RC=1
RUN219R3_RC=1
CUSTODY_PRE220_RC=1
RUN220R3_RC=1
CUSTODY_POST_RC=1
ENTRY_GUARD_RC=1
ENTRY_HOLD_CLEANUP_RC=125
MARKER_CLEANUP_RC=125
FINAL_POST_STATE_RC=125
CORE_COMPLETION_PASS=0
RUN_STATUS=1

QUARANTINE_EXECUTED=0
RUN217AR3_EXECUTED=0
RUN217AR4_EXECUTED=0
RUN217BR3_EXECUTED=0
RUN217CR3_EXECUTED=0
RUN218R3_EXECUTED=0
RUN219R3_EXECUTED=0
RUN220R3_EXECUTED=0
CUSTODY_PRE220_EXECUTED=0
ENTRY_GUARD_EXECUTED=0
ENTRY_HOLD_CLEANUP_EXECUTED=0
MARKER_CLEANUP_EXECUTED=0
FINAL_POST_STATE_EXECUTED=0
RUN_MARKER=""

if [ "$CONFIG_LOAD_RC" -eq 0 ]; then
  custody_check
  CUSTODY_PRE_RC=$?
else
  echo "[hold] failed-attempt custody was not checked because configuration loading failed"
fi

if [ "$CONFIG_LOAD_RC" -eq 0 ] && [ "$CUSTODY_PRE_RC" -eq 0 ]; then
  python -m unittest discover -s tests -p "$TEST_PATTERN" -v
  TEST_RC=$?
else
  echo "[hold] dedicated tests were not started because configuration or pre-run custody failed"
fi

# Cooperating v1.4 runners serialize all repository mutations by holding an
# advisory lock on the already-validated output-directory inode. The descriptor
# remains open through final guarding and held-run cleanup.
if [ "$TEST_RC" -eq 0 ]; then
  python - "$OUT" <<'PY'
import os
import sys
from pathlib import Path, PurePosixPath

root = Path.cwd().resolve(strict=True)
relative = PurePosixPath(sys.argv[1])
if relative.is_absolute() or relative.as_posix() != sys.argv[1] or any(
    part in ("", ".", "..") for part in relative.parts
):
    raise SystemExit("unsafe output path before whole-run lock")
current = root
for part in relative.parts:
    parent = current
    current = current / part
    if os.path.lexists(current):
        if current.is_symlink() or not current.is_dir():
            raise SystemExit("unsafe output component before whole-run lock")
    else:
        try:
            current.mkdir()
        except FileExistsError:
            if current.is_symlink() or not current.is_dir():
                raise
        descriptor = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    current.resolve(strict=True).relative_to(root)
PY
  RUN_LOCK_RC=$?
  if [ "$RUN_LOCK_RC" -eq 0 ] && command -v flock >/dev/null 2>&1; then
    exec 8<"$OUT"
    RUN_LOCK_RC=$?
    if [ "$RUN_LOCK_RC" -eq 0 ]; then
      RUN_LOCK_FD_OPEN=1
      flock -n 8
      RUN_LOCK_RC=$?
    fi
  else
    if [ "$RUN_LOCK_RC" -eq 0 ]; then RUN_LOCK_RC=127; fi
  fi
  if [ "$RUN_LOCK_RC" -ne 0 ]; then
    echo "[hold] another cooperating v1.4 runner owns the output-directory lock, or flock is unavailable"
  fi
fi

# Move only declared v1.4 gate artifacts aside, recoverably, before the first
# current gate. Historical evidence is never moved, and the isolated v1.4 Entry
# 128 path must be absent so this run cannot overwrite a completed logbook entry.
if [ "$TEST_RC" -eq 0 ] && [ "$RUN_LOCK_RC" -eq 0 ]; then
  QUARANTINE_EXECUTED=1
  RUN_TOKEN="$(date -u +%Y%m%dT%H%M%SZ)_$$"
  python - "$OUT" "$RUN_TOKEN" "$ENTRY" "$FINAL" "$FINAL_RUN_ID" \
    "$DESIGN_INVENTORY" "$DESIGN" "$PREFLIGHT_EVIDENCE" "$PREFLIGHT" \
    "$SMOKE_RESULTS" "$SMOKE" "$ACCEPT" "$MATRIX_RESULTS" "$MATRIX" \
    "$ADJ_EVIDENCE" "$ADJ" <<'PY'
import importlib.util
import os
import sys
from pathlib import Path, PurePosixPath

try:
    root = Path.cwd().resolve(strict=True)
    output_relative = PurePosixPath(sys.argv[1])
    if output_relative.is_absolute() or output_relative.as_posix() != sys.argv[1] or any(
        part in ("", ".", "..") for part in output_relative.parts
    ):
        raise ValueError("current output directory is not one canonical relative path")
    output = root
    for part in output_relative.parts:
        output = output / part
        if os.path.lexists(output):
            if output.is_symlink() or not output.is_dir():
                raise ValueError(f"unsafe current output directory component: {output.relative_to(root)}")
        else:
            output.mkdir()
    output.resolve(strict=True).relative_to(root)
    quarantine = output / ".prior_runtime_manifest_recovery" / sys.argv[2]
    entry = root / sys.argv[3]
    final_route = root / sys.argv[4]
    entry.resolve(strict=False).relative_to(root)
    final_route.resolve(strict=False).relative_to(root)
    if final_route.parent != output:
        raise ValueError("current final route is outside the exact output directory")
    gate_path = root / "scripts/365_freeze_simba_bondi_shadow_cli_manifest_route.py"
    if gate_path.is_symlink() or not gate_path.is_file():
        raise ValueError("transaction recovery authority is missing or unsafe")
    sys.path.insert(0, os.fspath(gate_path.parent))
    specification = importlib.util.spec_from_file_location("bh_simba_v14_entry_recovery", gate_path)
    if specification is None or specification.loader is None:
        raise ValueError("transaction recovery authority could not be loaded")
    recovery = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(recovery)
    recovered_transaction_paths = recovery.pending_transaction_recovery_paths(
        root,
        output,
        entry,
        final_route,
        sys.argv[5],
    )
    if os.path.lexists(entry) and entry not in recovered_transaction_paths:
        raise ValueError("isolated v1.4 Protocol Entry 128 already exists; refusing overwrite")
    def fsync_directory(path):
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    # Deterministic staging names are validated duplicate hardlinks. Remove
    # them first so every remaining canonical transaction artifact is
    # single-link and each later rename is independently restart-safe.
    for path in recovered_transaction_paths:
        if path.name.endswith(".pending"):
            path.unlink()
            fsync_directory(path.parent)
    if recovered_transaction_paths:
        recovered_transaction_paths = recovery.pending_transaction_recovery_paths(
            root,
            output,
            entry,
            final_route,
            sys.argv[5],
        )
    candidates = []
    for relative in sys.argv[6:]:
        path = root / relative
        if path.parent != output:
            raise ValueError(f"current artifact is outside the exact output directory: {relative}")
        if path.name in ("", ".", ".."):
            raise ValueError(f"invalid current artifact path: {relative}")
        candidates.append(path)
    # Move an owned Entry before its owner marker, and move the pending final
    # journal last. A crash at any rename boundary therefore cannot leave a
    # canonical Entry without a canonical recovery journal.
    if entry in recovered_transaction_paths:
        candidates.append(entry)
    for path in recovered_transaction_paths:
        if path != entry:
            path.resolve(strict=False).relative_to(root)
            candidates.append(path)
    if final_route.parent != output:
        raise ValueError("current final route is outside the exact output directory")
    candidates.append(final_route)
    for path in recovered_transaction_paths:
        path.resolve(strict=False).relative_to(root)
    candidates = list(dict.fromkeys(candidates))
    existing = [path for path in candidates if os.path.lexists(path)]
    if existing:
        quarantine_parent = quarantine.parent
        if os.path.lexists(quarantine_parent):
            if quarantine_parent.is_symlink() or not quarantine_parent.is_dir():
                raise ValueError("unsafe current-run quarantine parent")
        else:
            quarantine_parent.mkdir()
            fsync_directory(output)
            fsync_directory(quarantine_parent)
        quarantine.mkdir(exist_ok=False)
        fsync_directory(quarantine_parent)
        fsync_directory(quarantine)
    for path in existing:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"declared current artifact is not a regular non-symlink file: {path.relative_to(root)}")
        path.resolve(strict=True).relative_to(root)
        destination = quarantine / path.name
        if os.path.lexists(destination):
            raise ValueError(f"quarantine collision: {destination.relative_to(root)}")
        os.rename(path, destination)
        fsync_directory(path.parent)
        fsync_directory(quarantine)
        print(f"[custody] prior current-run artifact moved to {destination.relative_to(root)}")
except Exception as error:
    print(f"[hold] could not establish stale-artifact quarantine: {type(error).__name__}:{error}", file=sys.stderr)
    raise SystemExit(2)
PY
  QUARANTINE_RC=$?
  if [ "$QUARANTINE_RC" -eq 0 ]; then
    output_directory_check
    QUARANTINE_RC=$?
  fi
  if [ "$QUARANTINE_RC" -eq 0 ]; then
    RUN_MARKER="$OUT/.runtime_manifest_recovery_current_${RUN_TOKEN}.marker"
    python - "$RUN_MARKER" "$RUN_TOKEN" <<'PY'
import json
import os
import secrets
from pathlib import Path
import sys
path = Path(sys.argv[1])
if path.parent.is_symlink() or not path.parent.is_dir():
    raise SystemExit("unsafe current output directory before marker write")
if os.path.lexists(path):
    raise SystemExit("current-run marker already exists")
payload = json.dumps({
    "schema_version": 1,
    "run_token": sys.argv[2],
    "owner_nonce": secrets.token_hex(32),
}, sort_keys=True, separators=(",", ":")) + "\n"
descriptor = os.open(
    path,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    0o600,
)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
        descriptor = -1
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
finally:
    if descriptor >= 0:
        os.close(descriptor)
directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
    QUARANTINE_RC=$?
  fi
else
  echo "[hold] stale-artifact quarantine was not started because dedicated tests or the whole-run lock failed"
fi

if [ "$QUARANTINE_RC" -eq 0 ] && output_directory_check; then
  RUN217AR3_EXECUTED=1
  python scripts/359_freeze_simba_tng_shadow_exact_binding_repair_design.py \
    --config "$CONFIG" --repo-root .
  RUN217AR3_RC=$?
  if [ "$RUN217AR3_RC" -eq 0 ]; then
    validate_verdict "$DESIGN" "$DESIGN_RUN_ID" design
    RUN217AR3_RC=$?
  fi
else
  echo "[hold] Run 217A-R3A was not started because the prerequisite chain failed"
fi

if [ "$RUN217AR3_RC" -eq 0 ] && output_directory_check; then
  RUN217AR4_EXECUTED=1
  python scripts/360_preflight_simba_tng_shadow_exact_binding_concordance.py \
    --config "$CONFIG" --design-verdict "$DESIGN" --repo-root .
  RUN217AR4_RC=$?
  if [ "$RUN217AR4_RC" -eq 0 ]; then
    validate_verdict "$PREFLIGHT" "$PREFLIGHT_RUN_ID" preflight
    RUN217AR4_RC=$?
  fi
else
  echo "[hold] Run 217A-R4A was not started because exact current Run 217A-R3A did not pass"
fi

if [ "$RUN217AR4_RC" -eq 0 ] && output_directory_check; then
  RUN217BR3_EXECUTED=1
  python scripts/361_execute_simba_tng_shadow_sequential_smoke.py \
    --config "$CONFIG" --preflight-verdict "$PREFLIGHT" --repo-root .
  RUN217BR3_RC=$?
  if [ "$RUN217BR3_RC" -eq 0 ]; then
    validate_verdict "$SMOKE" "$SMOKE_RUN_ID" smoke
    RUN217BR3_RC=$?
  fi
else
  echo "[hold] Run 217B-R3 was not started because exact current Run 217A-R4A did not pass"
fi

if [ "$RUN217BR3_RC" -eq 0 ] && output_directory_check; then
  RUN217CR3_EXECUTED=1
  python scripts/362_freeze_simba_tng_shadow_smoke_acceptance.py \
    --config "$CONFIG" --design-verdict "$DESIGN" \
    --preflight-verdict "$PREFLIGHT" --smoke-verdict "$SMOKE" --repo-root .
  RUN217CR3_RC=$?
  if [ "$RUN217CR3_RC" -eq 0 ]; then
    validate_verdict "$ACCEPT" "$ACCEPT_RUN_ID" acceptance
    RUN217CR3_RC=$?
  fi
else
  echo "[hold] Run 217C-R3 was not started because exact current four-stage smoke did not pass"
fi

if [ "$RUN217CR3_RC" -eq 0 ] && output_directory_check; then
  RUN218R3_EXECUTED=1
  python scripts/363_execute_simba_tng_shadow_translation_matrix.py \
    --config "$CONFIG" --acceptance-verdict "$ACCEPT" --repo-root .
  RUN218R3_RC=$?
  if [ "$RUN218R3_RC" -eq 0 ]; then
    validate_verdict "$MATRIX" "$MATRIX_RUN_ID" matrix
    RUN218R3_RC=$?
  fi
else
  echo "[hold] Run 218-R3 was not started because exact current Run 217C-R3 did not authorize it"
fi

if [ "$RUN218R3_RC" -eq 0 ] && output_directory_check; then
  RUN219R3_EXECUTED=1
  python scripts/364_adjudicate_simba_bondi_shadow_translation.py \
    --config "$CONFIG" --acceptance-verdict "$ACCEPT" \
    --matrix-verdict "$MATRIX" --repo-root .
  RUN219R3_RC=$?
  if [ "$RUN219R3_RC" -eq 0 ]; then
    validate_verdict "$ADJ" "$ADJ_RUN_ID" adjudication
    RUN219R3_RC=$?
  fi
else
  echo "[hold] Run 219-R3 was not started: Run 218-R3 was not exact-current, process-pass, complete, and 20/20 successful"
fi

if [ "$RUN219R3_RC" -eq 0 ]; then
  CUSTODY_PRE220_EXECUTED=1
  custody_check
  CUSTODY_PRE220_RC=$?
else
  echo "[hold] pre-Run-220 custody was not rechecked because exact current Run 219-R3 did not pass"
fi

if [ "$RUN219R3_RC" -eq 0 ] && [ "$CUSTODY_PRE220_RC" -eq 0 ] && output_directory_check; then
  RUN220R3_EXECUTED=1
  python scripts/365_freeze_simba_bondi_shadow_cli_manifest_route.py \
    --config "$CONFIG" --design-verdict "$DESIGN" \
    --preflight-verdict "$PREFLIGHT" --smoke-verdict "$SMOKE" \
    --acceptance-verdict "$ACCEPT" --matrix-verdict "$MATRIX" \
    --adjudication-verdict "$ADJ" --transaction-owner-marker "$RUN_MARKER" \
    --repo-root .
  RUN220R3_RC=$?
  if [ "$RUN220R3_RC" -eq 0 ]; then
    validate_verdict "$FINAL" "$FINAL_RUN_ID" final
    RUN220R3_RC=$?
  fi
else
  echo "[hold] Run 220-R3 was not started because exact current adjudication or failed-Run-217A custody did not pass"
fi

# This check is unconditional whenever the configuration loaded: even a held or
# partially executed chain must leave the historical failed evidence byte-exact.
if [ "$CONFIG_LOAD_RC" -eq 0 ]; then
  custody_check
  CUSTODY_POST_RC=$?
fi

echo
echo "configuration load exit code: $CONFIG_LOAD_RC"
echo "failed Run 217A plus v1.2 R1/R2 plus v1.3 R3 pre-run custody exit code: $CUSTODY_PRE_RC"
echo "dedicated tests exit code: $TEST_RC"
echo "whole-run output-directory lock exit code: $RUN_LOCK_RC"
print_gate_state "stale-artifact quarantine" "$QUARANTINE_EXECUTED" "$QUARANTINE_RC"
print_gate_state "Run 217A-R3A exact-binding/source-state/lifecycle design" "$RUN217AR3_EXECUTED" "$RUN217AR3_RC"
print_gate_state "Run 217A-R4A recovered runtime-manifest preflight" "$RUN217AR4_EXECUTED" "$RUN217AR4_RC"
print_gate_state "Run 217B-R3 sequential zero-offset smoke" "$RUN217BR3_EXECUTED" "$RUN217BR3_RC"
print_gate_state "Run 217C-R3 smoke acceptance" "$RUN217CR3_EXECUTED" "$RUN217CR3_RC"
print_gate_state "Run 218-R3 complete translation matrix" "$RUN218R3_EXECUTED" "$RUN218R3_RC"
print_gate_state "Run 219-R3 independent adjudication" "$RUN219R3_EXECUTED" "$RUN219R3_RC"
print_gate_state "failed-attempt pre-Run-220 custody" "$CUSTODY_PRE220_EXECUTED" "$CUSTODY_PRE220_RC"
print_gate_state "Run 220-R3 final route" "$RUN220R3_EXECUTED" "$RUN220R3_RC"
echo "failed Run 217A plus v1.2 R1/R2 plus v1.3 R3 post-run custody exit code: $CUSTODY_POST_RC"

if [ "$RUN217AR3_EXECUTED" -eq 1 ] && [ -f "$DESIGN" ]; then print_current_verdict "$DESIGN" "$DESIGN_RUN_ID"; fi
if [ "$RUN217AR4_EXECUTED" -eq 1 ] && [ -f "$PREFLIGHT" ]; then print_current_verdict "$PREFLIGHT" "$PREFLIGHT_RUN_ID"; fi
if [ "$RUN217BR3_EXECUTED" -eq 1 ] && [ -f "$SMOKE" ]; then print_current_verdict "$SMOKE" "$SMOKE_RUN_ID"; fi
if [ "$RUN217CR3_EXECUTED" -eq 1 ] && [ -f "$ACCEPT" ]; then print_current_verdict "$ACCEPT" "$ACCEPT_RUN_ID"; fi
if [ "$RUN218R3_EXECUTED" -eq 1 ] && [ -f "$MATRIX" ]; then print_current_verdict "$MATRIX" "$MATRIX_RUN_ID"; fi
if [ "$RUN219R3_EXECUTED" -eq 1 ] && [ -f "$ADJ" ]; then print_current_verdict "$ADJ" "$ADJ_RUN_ID"; fi
if [ "$RUN220R3_EXECUTED" -eq 1 ] && [ -f "$FINAL" ]; then print_current_verdict "$FINAL" "$FINAL_RUN_ID"; fi

if [ "$RUN220R3_RC" -eq 0 ] && [ "$CUSTODY_POST_RC" -eq 0 ] && [ -n "$RUN_MARKER" ] && output_directory_check; then
  ENTRY_GUARD_EXECUTED=1
  python - "$FINAL" "$FINAL_RUN_ID" "$MATRIX" "$MATRIX_RUN_ID" "$ENTRY" "$RUN_MARKER" <<'PY'
import json
import hashlib
import importlib.util
import os
import sys
from pathlib import Path

final_path, final_id, matrix_path, matrix_id, supplied_entry_path, marker_path = (
    Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4], Path(sys.argv[5]), Path(sys.argv[6])
)
try:
    root = Path.cwd().resolve(strict=True)
    final_path = final_path if final_path.is_absolute() else root / final_path
    matrix_path = matrix_path if matrix_path.is_absolute() else root / matrix_path
    marker_path = marker_path if marker_path.is_absolute() else root / marker_path
    entry_path = supplied_entry_path if supplied_entry_path.is_absolute() else root / supplied_entry_path
    entry_relative = entry_path.relative_to(root).as_posix()
    final_path.relative_to(root)
    matrix_path.relative_to(root)
    marker_path.relative_to(root)
    gate_path = root / "scripts/365_freeze_simba_bondi_shadow_cli_manifest_route.py"
    if gate_path.is_symlink() or not gate_path.is_file():
        raise ValueError("transaction validation authority is missing or unsafe")
    sys.path.insert(0, os.fspath(gate_path.parent))
    specification = importlib.util.spec_from_file_location("bh_simba_v14_entry_guard", gate_path)
    if specification is None or specification.loader is None:
        raise ValueError("transaction validation authority could not be loaded")
    transaction_authority = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(transaction_authority)
    output = final_path.parent
    transaction = transaction_authority.validate_entry_transaction(
        root,
        output,
        entry_path,
        final_path,
        final_id,
        allowed_states={"committed"},
        require_entry=True,
        expected_owner_marker=marker_path,
    )
    final = transaction["route"]
    matrix_payload = transaction_authority.stable_regular_bytes(root, matrix_path)
    matrix = transaction_authority.strict_json_object(matrix_payload)
    entry_payload = transaction["entry_payload"]
    if entry_payload is None:
        raise ValueError("committed transaction omitted Entry bytes")
    text = entry_payload.decode("utf-8")
    entry_sha256 = hashlib.sha256(entry_payload).hexdigest()
    final_file_record = final.get("files", {}).get(entry_relative)
    final_files_record = final.get("final_files", {}).get(entry_relative)
    entry_provenance = final.get("provenance", {}).get("protocol_entry", {})
    upstream_provenance = final.get("provenance", {}).get("upstream_verdicts", {})
    transaction_record = transaction["transaction"]
    resolved = final.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved") is True
    rejected = final.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected") is True
    ok = all((
        final.get("run_id") == final_id,
        final.get("final_route_pass") is True,
        final.get("matrix_complete") is True,
        final.get("logbook_entry_written") is True,
        final.get("entry_install_transaction_state") == "committed",
        matrix.get("run_id") == matrix_id,
        matrix.get("matrix_process_pass") is True,
        matrix.get("expected_stage_invocations") == 20,
        matrix.get("attempted_stage_invocations") == 20,
        matrix.get("successful_stage_invocations") == 20,
        matrix.get("matrix_complete") is True,
        matrix.get("all_four_stages_executed_at_all_offsets") is True,
        resolved != rejected,
        final.get("physical_units_resolved") is False,
        final.get("native_unit_coordinate_fallback_authorized") is False,
        final_file_record == {"sha256": entry_sha256},
        final_files_record == {"sha256": entry_sha256},
        entry_provenance.get("path") == entry_relative,
        entry_provenance.get("sha256") == entry_sha256,
        entry_provenance.get("written_only_after_complete_route") is True,
        transaction_record.get("matrix_verdict_sha256") == hashlib.sha256(matrix_payload).hexdigest(),
        transaction_record.get("adjudication_verdict_sha256")
        == upstream_provenance.get("adjudication", {}).get("sha256"),
        "Protocol Entry 128" in text,
        f"% entry_install_transaction_id: {transaction_record.get('transaction_id')}\n" in text,
        f"% final_route_run_id: {final_id}\n" in text,
        all(section in text for section in ("What was tested", "Methods", "Results", "Failures and holds", "Trust boundary", "Next steps")),
    ))
    if not ok:
        raise ValueError("Entry 128 is not bound to the exact current full matrix and final route")
    if (
        transaction_authority.stable_regular_bytes(root, final_path) != transaction["route_payload"]
        or transaction_authority.stable_regular_bytes(root, matrix_path) != matrix_payload
        or transaction_authority.stable_regular_bytes(root, entry_path) != entry_payload
        or transaction_authority.stable_regular_bytes(root, marker_path)
        != transaction["owner_marker_payload"]
    ):
        raise ValueError("completion artifacts changed across stable-snapshot guard")
except Exception as error:
    print(f"[hold] Protocol Entry 128 completion guard failed: {type(error).__name__}:{error}", file=sys.stderr)
    raise SystemExit(2)
PY
  ENTRY_GUARD_RC=$?
else
  echo "[hold] Protocol Entry 128 was not accepted because the exact current final route, full 20-invocation matrix, or custody check did not pass"
fi

if [ "$CONFIG_LOAD_RC" -eq 0 ] \
  && [ "$CUSTODY_PRE_RC" -eq 0 ] \
  && [ "$TEST_RC" -eq 0 ] \
  && [ "$RUN_LOCK_RC" -eq 0 ] \
  && [ "$QUARANTINE_RC" -eq 0 ] \
  && [ "$RUN217AR3_RC" -eq 0 ] \
  && [ "$RUN217AR4_RC" -eq 0 ] \
  && [ "$RUN217BR3_RC" -eq 0 ] \
  && [ "$RUN217CR3_RC" -eq 0 ] \
  && [ "$RUN218R3_RC" -eq 0 ] \
  && [ "$RUN219R3_RC" -eq 0 ] \
  && [ "$CUSTODY_PRE220_RC" -eq 0 ] \
  && [ "$RUN220R3_RC" -eq 0 ] \
  && [ "$CUSTODY_POST_RC" -eq 0 ] \
  && [ "$ENTRY_GUARD_RC" -eq 0 ]; then
  CORE_COMPLETION_PASS=1
fi

# If a final-gate defect writes the current Entry but any completion guard still
# holds, remove the owned Entry and its pending/committed final journal from the
# canonical paths recoverably. A held bundle must not leave accepted-looking
# completion artifacts behind.
if [ "$CORE_COMPLETION_PASS" -eq 0 ] && [ -n "$RUN_MARKER" ] && [ -n "$ENTRY" ] && output_directory_check; then
  ENTRY_HOLD_CLEANUP_EXECUTED=1
  python - "$ENTRY" "$RUN_MARKER" "$OUT" "$RUN_TOKEN" "$FINAL" "$FINAL_RUN_ID" <<'PY'
import importlib.util
import os
import sys
from pathlib import Path, PurePosixPath

try:
    root = Path.cwd().resolve(strict=True)
    entry = root / sys.argv[1]
    output_relative = PurePosixPath(sys.argv[3])
    if output_relative.is_absolute() or output_relative.as_posix() != sys.argv[3] or any(
        part in ("", ".", "..") for part in output_relative.parts
    ):
        raise ValueError("held-run output directory is not one canonical relative path")
    output = root
    for part in output_relative.parts:
        output = output / part
        if not os.path.lexists(output) or output.is_symlink() or not output.is_dir():
            raise ValueError(f"unsafe held-run output directory component: {output.relative_to(root)}")
    marker = root / sys.argv[2]
    if marker.is_symlink() or not marker.is_file():
        raise ValueError("held-run marker is missing or unsafe")
    entry.parent.resolve(strict=True).relative_to(root)
    marker.resolve(strict=True).relative_to(root)
    output.resolve(strict=True).relative_to(root)
    final_route = root / sys.argv[5]
    final_route.resolve(strict=False).relative_to(root)
    if os.path.lexists(final_route):
        gate_path = root / "scripts/365_freeze_simba_bondi_shadow_cli_manifest_route.py"
        if gate_path.is_symlink() or not gate_path.is_file():
            raise ValueError("transaction cleanup authority is missing or unsafe")
        sys.path.insert(0, os.fspath(gate_path.parent))
        specification = importlib.util.spec_from_file_location("bh_simba_v14_entry_cleanup", gate_path)
        if specification is None or specification.loader is None:
            raise ValueError("transaction cleanup authority could not be loaded")
        transaction_authority = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(transaction_authority)
        route = transaction_authority.strict_json_object(
            transaction_authority.stable_regular_bytes(root, final_route)
        )
        state = route.get("entry_install_transaction_state")
        if state in {"entry_pending", "committed"}:
            entry_exists = os.path.lexists(entry)
            transaction = transaction_authority.validate_entry_transaction(
                root,
                output,
                entry,
                final_route,
                sys.argv[6],
                allowed_states={state},
                require_entry=entry_exists,
                expected_owner_marker=marker,
            )
            quarantine = output / ".prior_runtime_manifest_recovery" / sys.argv[4]
            quarantine_parent = quarantine.parent
            def fsync_directory(path):
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            if os.path.lexists(quarantine_parent):
                if quarantine_parent.is_symlink() or not quarantine_parent.is_dir():
                    raise ValueError("unsafe held-run quarantine parent")
            else:
                quarantine_parent.mkdir()
                fsync_directory(output)
                fsync_directory(quarantine_parent)
            if os.path.lexists(quarantine):
                if quarantine.is_symlink() or not quarantine.is_dir():
                    raise ValueError("unsafe held-run quarantine directory")
            else:
                quarantine.mkdir()
                fsync_directory(quarantine_parent)
                fsync_directory(quarantine)
            # Normalize validated hardlink staging names before moving the two
            # canonical transaction artifacts. Entry moves first; the journal
            # moves last so every interruption remains recoverable.
            for key in ("staging_path", "final_staging_path"):
                staging = transaction[key]
                if os.path.lexists(staging):
                    staging.unlink()
                    fsync_directory(staging.parent)
            transaction_id = transaction["transaction"]["transaction_id"]
            candidates = [entry] if entry_exists else []
            candidates.append(final_route)
            for path in candidates:
                destination = quarantine / f"held_{transaction_id}_{path.name}"
                if os.path.lexists(destination):
                    raise ValueError("held-run transaction quarantine collision")
                os.rename(path, destination)
                fsync_directory(path.parent)
                fsync_directory(quarantine)
                print(f"[custody] held-run transaction artifact moved to {destination.relative_to(root)}")
        elif os.path.lexists(entry):
            raise ValueError("refusing to move Entry without an owned current transaction")
    elif os.path.lexists(entry):
        raise ValueError("orphan held-run Entry has no final transaction journal")
    if os.path.lexists(entry):
        raise ValueError("held-run Protocol Entry remained at its canonical path")
    if os.path.lexists(final_route):
        remaining = transaction_authority.strict_json_object(
            transaction_authority.stable_regular_bytes(root, final_route)
        )
        if (
            remaining.get("entry_install_transaction_state") in {"entry_pending", "committed"}
            or remaining.get("final_route_pass") is True
            or remaining.get("logbook_entry_written") is True
        ):
            raise ValueError("accepted-looking held-run final journal remained canonical")
except Exception as error:
    print(f"[hold] could not clear held completion artifacts: {type(error).__name__}:{error}", file=sys.stderr)
    raise SystemExit(2)
PY
  ENTRY_HOLD_CLEANUP_RC=$?
fi

if [ -n "$RUN_MARKER" ] && output_directory_check; then
  MARKER_CLEANUP_EXECUTED=1
  python - "$RUN_MARKER" "$CORE_COMPLETION_PASS" "$ENTRY" "$FINAL" "$OUT" "$FINAL_RUN_ID" <<'PY'
import importlib.util
import os
import sys
from pathlib import Path

root = Path.cwd().resolve(strict=True)
path = root / sys.argv[1]
core_pass = int(sys.argv[2]) == 1
if not os.path.lexists(path):
    if core_pass:
        raise SystemExit("successful route owner marker vanished before durable cleanup")
    raise SystemExit(0)
if path.is_symlink() or not path.is_file() or path.parent.is_symlink() or not path.parent.is_dir():
    raise SystemExit("unsafe current-run marker during durable cleanup")
if not core_pass:
    entry = root / sys.argv[3]
    final_route = root / sys.argv[4]
    output = root / sys.argv[5]
    final_id = sys.argv[6]
    if os.path.lexists(entry):
        print("[custody] preserving current-run marker for recoverable Entry transaction")
        raise SystemExit(2)
    gate_path = root / "scripts/365_freeze_simba_bondi_shadow_cli_manifest_route.py"
    try:
        sys.path.insert(0, os.fspath(gate_path.parent))
        specification = importlib.util.spec_from_file_location(
            "bh_simba_v14_marker_cleanup", gate_path
        )
        if specification is None or specification.loader is None:
            raise RuntimeError("transaction recovery authority could not be loaded")
        transaction_authority = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(transaction_authority)
        recovery_paths = transaction_authority.pending_transaction_recovery_paths(
            root, output, entry, final_route, final_id
        )
    except Exception as error:
        print(
            f"[custody] preserving current-run marker because transaction state could not be cleared: "
            f"{type(error).__name__}:{error}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if path in recovery_paths:
        print("[custody] preserving current-run marker for pending transaction recovery")
        raise SystemExit(2)
path.unlink()
descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
  MARKER_CLEANUP_RC=$?
elif [ "$CORE_COMPLETION_PASS" -eq 1 ]; then
  MARKER_CLEANUP_EXECUTED=1
  MARKER_CLEANUP_RC=2
  echo "[hold] successful route has no current-run marker to clean"
else
  MARKER_CLEANUP_RC=0
fi

# A marker-cleanup failure demotes an otherwise complete route. Because the
# earlier held cleanup was intentionally skipped for a core-complete route,
# perform an ownership-validated fallback now: quarantine the committed Entry
# first and its final journal last, then durably remove any remaining marker.
if [ "$CORE_COMPLETION_PASS" -eq 1 ] && [ "$MARKER_CLEANUP_RC" -ne 0 ]; then
  CORE_COMPLETION_PASS=0
  ENTRY_HOLD_CLEANUP_EXECUTED=1
  python - "$ENTRY" "$FINAL" "$OUT" "$RUN_TOKEN" "$FINAL_RUN_ID" "$RUN_MARKER" <<'PY'
import importlib.util
import os
import sys
from pathlib import Path, PurePosixPath

try:
    root = Path.cwd().resolve(strict=True)
    entry = root / sys.argv[1]
    final_route = root / sys.argv[2]
    output_relative = PurePosixPath(sys.argv[3])
    if output_relative.is_absolute() or output_relative.as_posix() != sys.argv[3] or any(
        part in ("", ".", "..") for part in output_relative.parts
    ):
        raise ValueError("marker-failure output directory is not one canonical relative path")
    output = root
    for part in output_relative.parts:
        output = output / part
        if not os.path.lexists(output) or output.is_symlink() or not output.is_dir():
            raise ValueError(f"unsafe marker-failure output component: {output.relative_to(root)}")
    output.resolve(strict=True).relative_to(root)
    entry.resolve(strict=False).relative_to(root)
    final_route.resolve(strict=False).relative_to(root)
    marker = root / sys.argv[6] if sys.argv[6] else None
    if marker is not None:
        marker.resolve(strict=False).relative_to(root)
    gate_path = root / "scripts/365_freeze_simba_bondi_shadow_cli_manifest_route.py"
    if gate_path.is_symlink() or not gate_path.is_file():
        raise ValueError("marker-failure transaction authority is missing or unsafe")
    sys.path.insert(0, os.fspath(gate_path.parent))
    specification = importlib.util.spec_from_file_location(
        "bh_simba_v14_marker_failure_fallback", gate_path
    )
    if specification is None or specification.loader is None:
        raise ValueError("marker-failure transaction authority could not be loaded")
    authority = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(authority)
    # A committed transaction is self-contained if its ephemeral marker was
    # already unlinked. If a marker still exists, the validator also verifies
    # its exact path, payload digest, and byte count before any rename.
    transaction = authority.validate_entry_transaction(
        root,
        output,
        entry,
        final_route,
        sys.argv[5],
        allowed_states={"committed"},
        require_entry=True,
    )
    if marker is None or transaction.get("owner_marker_path") != marker:
        raise ValueError("marker-failure transaction owner path changed")
    def fsync_directory(path):
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    quarantine = output / ".prior_runtime_manifest_recovery" / sys.argv[4]
    quarantine_parent = quarantine.parent
    if os.path.lexists(quarantine_parent):
        if quarantine_parent.is_symlink() or not quarantine_parent.is_dir():
            raise ValueError("unsafe marker-failure quarantine parent")
    else:
        quarantine_parent.mkdir()
        fsync_directory(output)
        fsync_directory(quarantine_parent)
    if os.path.lexists(quarantine):
        if quarantine.is_symlink() or not quarantine.is_dir():
            raise ValueError("unsafe marker-failure quarantine directory")
    else:
        quarantine.mkdir()
        fsync_directory(quarantine_parent)
        fsync_directory(quarantine)
    for key in ("staging_path", "final_staging_path"):
        staging = transaction[key]
        if os.path.lexists(staging):
            staging.unlink()
            fsync_directory(staging.parent)
    transaction_id = transaction["transaction"]["transaction_id"]
    for path in (entry, final_route):
        destination = quarantine / f"marker_hold_{transaction_id}_{path.name}"
        if os.path.lexists(destination):
            raise ValueError("marker-failure transaction quarantine collision")
        os.rename(path, destination)
        fsync_directory(path.parent)
        fsync_directory(quarantine)
        print(f"[custody] marker-failure transaction artifact moved to {destination.relative_to(root)}")
    if marker is not None and os.path.lexists(marker):
        if marker.is_symlink() or not marker.is_file() or marker.parent != output:
            raise ValueError("remaining marker is unsafe after transaction quarantine")
        marker.unlink()
        fsync_directory(marker.parent)
    if os.path.lexists(entry) or os.path.lexists(final_route):
        raise ValueError("marker-failure completion artifacts remained canonical")
    if marker is not None and os.path.lexists(marker):
        raise ValueError("marker remained after marker-failure fallback cleanup")
except Exception as error:
    print(f"[hold] marker-failure fallback cleanup failed: {type(error).__name__}:{error}", file=sys.stderr)
    raise SystemExit(2)
PY
  ENTRY_HOLD_CLEANUP_RC=$?
fi

# The final state is checked after marker cleanup. A passing route must be one
# self-verifying committed transaction without its ephemeral marker. A held
# route must have no canonical Entry and no accepted-looking final journal.
if [ "$CONFIG_LOAD_RC" -eq 0 ] && [ -n "$ENTRY" ] && [ -n "$FINAL" ] && output_directory_check; then
  FINAL_POST_STATE_EXECUTED=1
  python - "$CORE_COMPLETION_PASS" "$ENTRY" "$FINAL" "$OUT" "$FINAL_RUN_ID" "$RUN_MARKER" <<'PY'
import importlib.util
import os
import sys
from pathlib import Path

try:
    core_pass = int(sys.argv[1]) == 1
    root = Path.cwd().resolve(strict=True)
    entry = root / sys.argv[2]
    final_route = root / sys.argv[3]
    output = root / sys.argv[4]
    final_id = sys.argv[5]
    marker = root / sys.argv[6] if sys.argv[6] else None
    entry.resolve(strict=False).relative_to(root)
    final_route.resolve(strict=False).relative_to(root)
    output.resolve(strict=True).relative_to(root)
    if marker is not None and os.path.lexists(marker):
        raise ValueError("current-run owner marker remained after cleanup")
    gate_path = root / "scripts/365_freeze_simba_bondi_shadow_cli_manifest_route.py"
    if gate_path.is_symlink() or not gate_path.is_file():
        raise ValueError("transaction post-state authority is missing or unsafe")
    sys.path.insert(0, os.fspath(gate_path.parent))
    specification = importlib.util.spec_from_file_location("bh_simba_v14_post_state", gate_path)
    if specification is None or specification.loader is None:
        raise ValueError("transaction post-state authority could not be loaded")
    authority = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(authority)
    if core_pass:
        transaction = authority.validate_entry_transaction(
            root,
            output,
            entry,
            final_route,
            final_id,
            allowed_states={"committed"},
            require_entry=True,
        )
        if transaction.get("owner_marker_payload") is not None:
            raise ValueError("committed post-state retained an owner-marker payload")
    else:
        if os.path.lexists(entry):
            raise ValueError("held route retained a canonical Protocol Entry 128")
        if os.path.lexists(final_route):
            route = authority.strict_json_object(authority.stable_regular_bytes(root, final_route))
            if (
                route.get("entry_install_transaction_state") in {"entry_pending", "committed"}
                or route.get("final_route_pass") is True
                or route.get("logbook_entry_written") is True
            ):
                raise ValueError("held route retained an accepted-looking final journal")
except Exception as error:
    print(f"[hold] final completion post-state failed: {type(error).__name__}:{error}", file=sys.stderr)
    raise SystemExit(2)
PY
  FINAL_POST_STATE_RC=$?
fi

if [ "$CORE_COMPLETION_PASS" -eq 1 ] \
  && [ "$MARKER_CLEANUP_RC" -eq 0 ] \
  && [ "$FINAL_POST_STATE_RC" -eq 0 ]; then
  RUN_STATUS=0
fi

if [ "$RUN_LOCK_FD_OPEN" -eq 1 ]; then
  flock -u 8
  exec 8<&-
  RUN_LOCK_FD_OPEN=0
fi

echo
print_gate_state "Protocol Entry 128 completion guard" "$ENTRY_GUARD_EXECUTED" "$ENTRY_GUARD_RC"
print_gate_state "held completion-artifact cleanup" "$ENTRY_HOLD_CLEANUP_EXECUTED" "$ENTRY_HOLD_CLEANUP_RC"
print_gate_state "current-run marker cleanup" "$MARKER_CLEANUP_EXECUTED" "$MARKER_CLEANUP_RC"
print_gate_state "final completion post-state" "$FINAL_POST_STATE_EXECUTED" "$FINAL_POST_STATE_RC"
echo "Protocol Entry 128 PDF production was not attempted by this bundle."
echo
echo "The configured historical scope for Runs 214--217 is selected semantic/path continuity plus pinned supporting inventory/result digests."
if [ "$CUSTODY_PRE_RC" -eq 0 ] && [ "$CUSTODY_POST_RC" -eq 0 ]; then
  echo "Failed Run 217A, all four v1.2 R1/R2 artifacts, and both held v1.3 R3 artifacts remained under byte-exact custody."
else
  echo "HOLD: complete byte-exact failed-attempt custody was not established; no downstream result is accepted."
fi
if [ "$QUARANTINE_EXECUTED" -eq 1 ]; then
  echo "Declared prior-current v1.4 artifact paths were inspected; actual recoverable moves, if any, are only those reported by [custody] lines above."
else
  echo "Prior-current v1.4 artifact quarantine was not started; no artifact move is implied."
fi
if [ "$RUN217BR3_EXECUTED" -eq 0 ]; then
  echo "No production executor gate was reached in this run; dedicated tests may have used temporary stub CLIs."
else
  echo "A production executor gate was reached; only the exact-current verdicts printed above report whether and how many executor processes were invoked and accepted."
fi
if [ "$RUN217AR3_RC" -eq 0 ]; then
  echo "Current Run 217A-R3A froze the Phase-B post-producer binding lifecycle with its deterministic receipt and full-manifest-closure requirements."
else
  echo "Current Run 217A-R3A did not freeze or accept the proposed post-producer binding lifecycle."
fi
if [ "$RUN219R3_EXECUTED" -eq 1 ]; then
  echo "Run 219-R3 was executed; its exact-current verdict above reports whether the independent 20/20 live replay passed."
else
  echo "If opened, Run 219-R3 can pass only with an independent current 20/20 live replay."
fi
if [ "$RUN220R3_EXECUTED" -eq 1 ]; then
  echo "Run 220-R3 was executed; its exact-current verdict above reports whether exactly one latent-signal-offset axis was resolved or rejected."
else
  echo "If opened, Run 220-R3 can pass only after exactly one latent-signal-offset axis is resolved or rejected."
fi
if [ "$RUN_STATUS" -eq 0 ] && [ "$ENTRY_GUARD_RC" -eq 0 ] && [ "$FINAL_POST_STATE_RC" -eq 0 ]; then
  echo "The transactionally written Entry 128 TeX was accepted and provenance-bound."
else
  echo "No Protocol Entry 128 was accepted by this held or incomplete run."
fi
echo "Synthetic latent-signal-offset behavior was not promoted to physical units, unit conversion, writer semantics, population equivalence, or real-SIMBA/scientific-data memory inference."
echo "No real-SIMBA payload, coordinate, track, zero policy, adapter, or scientific-data memory inference was authorized."
echo "The configured maximum later scope is temporary declared synthetic-shadow work after the exact current prerequisites pass; this run may have stopped before that scope opened."
echo "The protocol is not an operating-system filesystem or network sandbox."
echo "No bundle script invoked a Git write command; no bundle-managed commit, tag, or push was attempted."
echo "RUN_STATUS=$RUN_STATUS"
echo "Terminal retained."

# The no-exit contract is intentional: RUN_STATUS carries the fail-closed result.
true
