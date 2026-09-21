from __future__ import annotations

import ast
import base64
import copy
import csv
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CONFIG = ROOT / "configs/protocol/bh_simba_bondi_shadow_exact_binding_source_state_lifecycle_recovery_v1_4.json"
RUNNER = ROOT / "run_bh_simba_bondi_shadow_exact_binding_source_state_lifecycle_recovery_no_exit.sh"
GATE_NAMES = (
    "359_freeze_simba_tng_shadow_exact_binding_repair_design.py",
    "360_preflight_simba_tng_shadow_exact_binding_concordance.py",
    "361_execute_simba_tng_shadow_sequential_smoke.py",
    "362_freeze_simba_tng_shadow_smoke_acceptance.py",
    "363_execute_simba_tng_shadow_translation_matrix.py",
    "364_adjudicate_simba_bondi_shadow_translation.py",
    "365_freeze_simba_bondi_shadow_cli_manifest_route.py",
)
SCRIPT_NAMES = (*GATE_NAMES, "bh_simba_runtime_manifest_common_v1_4.py", "bh_simba_shadow_exact_binding_source_state_lifecycle_recovery_v1_4.py")
SCRIPT_PATHS = tuple(SCRIPTS / name for name in SCRIPT_NAMES)
sys.path.insert(0, str(SCRIPTS))

import bh_simba_shadow_exact_binding_source_state_lifecycle_recovery_v1_4 as repair  # noqa: E402
import bh_simba_runtime_manifest_common_v1_4 as common  # noqa: E402


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def deterministic_parquet_stub(frame, path, index=False) -> None:
    """Provide stable fixture bytes without depending on an optional parquet engine."""
    frame.to_csv(path, index=index)


G4_BINDING_EXECUTOR_PAYLOAD = b'''#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()


def load_guarded_plan(config, repo_root):
    plan_path = Path(repo_root) / config["data"]["canonical_g3_track_plan"]
    expected_plan_sha256 = config["screen"]["exact_g3_track_plan_sha256"]
    observed_plan_sha256 = sha256_file(plan_path)
    if observed_plan_sha256 != expected_plan_sha256:
        raise RuntimeError("canonical_g3_track_plan_digest_mismatch")
    return json.loads(plan_path.read_text(encoding="utf-8"))
'''


def load_gate(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_manifest(records: dict[str, tuple[bytes, dict[str, object] | None]]) -> dict[str, object]:
    files: dict[str, dict[str, object]] = {}
    for relative, (content, extra) in records.items():
        record: dict[str, object] = {"sha256": sha_bytes(content), "bytes": len(content)}
        if extra:
            record.update(extra)
        files[relative] = record
    return {"schema_version": 1, "files": files}


def build_binding_fixture(base: Path) -> dict[str, object]:
    base.mkdir(parents=True, exist_ok=True)
    source = base / "source"
    shadow = base / "shadow"
    source.mkdir()
    shadow.mkdir()
    shared_relative = "manifests/shared.json"
    confirmation_relative = "manifests/confirmation.json"
    g4_relative = "manifests/g4.json"
    target = "outputs/phase_b.json"
    input_a = "data/candidate.bin"
    input_b = "data/raw.bin"
    a_bytes = b"candidate\n"
    b_bytes = b"raw\n"
    historical_product = b'{"schema_version":1,"run_id":"HISTORICAL-PRODUCER"}\n'
    for root in (shadow,):
        write_bytes(root / input_a, a_bytes)
        write_bytes(root / input_b, b_bytes)
        (root / "outputs").mkdir(parents=True, exist_ok=True)
    binding_executor_payloads = {
        "scripts/producer.py": b"# pinned producer\n",
        "scripts/consumer.py": b"# pinned consumer\n",
        "scripts/g4.py": b"# pinned g4\n",
    }
    for root in (source, shadow):
        for relative, payload in binding_executor_payloads.items():
            write_bytes(root / relative, payload)

    shared_manifest = make_manifest({input_a: (a_bytes, None), input_b: (b_bytes, None)})
    g4_manifest = make_manifest({input_b: (b_bytes, None)})
    confirmation_manifest = copy.deepcopy(shared_manifest)
    confirmation_manifest["files"][target] = {
        "sha256": sha_bytes(historical_product),
        "bytes": len(historical_product),
        "role": "phase_b_runtime_product",
    }
    for root in (source, shadow):
        write_json(root / shared_relative, shared_manifest)
        write_json(root / confirmation_relative, confirmation_manifest)
        write_json(root / g4_relative, g4_manifest)
    write_bytes(source / target, historical_product)

    producer_config = "configs/producer.yaml"
    screen_config = "configs/screen.yaml"
    confirmation_config = "configs/confirmation.yaml"
    g4_config = "configs/g4.yaml"
    configs = {
        producer_config: {
            "run_id": "SYNTHETIC-PRODUCER",
            "data": {"candidate": input_a},
        },
        screen_config: {
            "run_id": "SYNTHETIC-SCREEN",
            "data": {"phase": target, "candidate": input_a, "raw": input_b},
        },
        confirmation_config: {
            "run_id": "SYNTHETIC-CONFIRMATION",
            "data": {"phase": target, "candidate": input_a, "raw": input_b},
        },
        g4_config: {
            "run_id": "SYNTHETIC-G4",
            "data": {"raw": input_b},
        },
    }
    for relative, value in configs.items():
        write_yaml(source / relative, value)
        write_yaml(shadow / relative, value)

    shared_sha = repair.sha256(source / shared_relative)
    confirmation_sha = repair.sha256(source / confirmation_relative)
    g4_sha = repair.sha256(source / g4_relative)
    stages = [
        {
            "stage": "generator3_phase_b",
            "executor": "scripts/producer.py",
            "executor_sha256": sha_bytes(binding_executor_payloads["scripts/producer.py"]),
            "config": producer_config,
            "config_sha256": repair.sha256(source / producer_config),
            "manifest": shared_relative,
            "manifest_sha256": shared_sha,
            "required_data_keys": ["data.candidate"],
        },
        {
            "stage": "generator3_null_screen",
            "executor": "scripts/consumer.py",
            "executor_sha256": sha_bytes(binding_executor_payloads["scripts/consumer.py"]),
            "config": screen_config,
            "config_sha256": repair.sha256(source / screen_config),
            "manifest": shared_relative,
            "manifest_sha256": shared_sha,
            "required_data_keys": ["data.phase", "data.candidate", "data.raw"],
        },
        {
            "stage": "generator3_null_confirmation_2000",
            "executor": "scripts/consumer.py",
            "executor_sha256": sha_bytes(binding_executor_payloads["scripts/consumer.py"]),
            "config": confirmation_config,
            "config_sha256": repair.sha256(source / confirmation_config),
            "manifest": confirmation_relative,
            "manifest_sha256": confirmation_sha,
            "required_data_keys": ["data.phase", "data.candidate", "data.raw"],
        },
        {
            "stage": "generator4_pooled_innovation_screen",
            "executor": "scripts/g4.py",
            "executor_sha256": sha_bytes(binding_executor_payloads["scripts/g4.py"]),
            "config": g4_config,
            "config_sha256": repair.sha256(source / g4_config),
            "manifest": g4_relative,
            "manifest_sha256": g4_sha,
            "required_data_keys": ["data.raw"],
        },
    ]
    production_binding = json.loads(CONFIG.read_text(encoding="utf-8"))["runtime_binding"]
    cfg = {
        "stage_contracts": stages,
        "runtime_binding": {
            "schema_version": production_binding["schema_version"],
            "target_relative_path": target,
            "producer_stage": "generator3_phase_b",
            "consumer_stages": ["generator3_null_screen", "generator3_null_confirmation_2000"],
            "producer_manifest": shared_relative,
            "shared_manifest": shared_relative,
            "confirmation_manifest": confirmation_relative,
            "confirmation_template_manifest": confirmation_relative,
            "template_target_content_sha256": sha_bytes(historical_product),
            "template_target_bytes": len(historical_product),
            "source_manifest_sha256": {
                shared_relative: shared_sha,
                confirmation_relative: confirmation_sha,
            },
            "required_postproducer_state": {"producer_return_code": 0},
            "mutation_scope": copy.deepcopy(production_binding["mutation_scope"]),
            "receipt_schema": copy.deepcopy(production_binding["receipt_schema"]),
            "receipt_count_per_shadow": 1,
        },
    }
    return {
        "source": source,
        "shadow": shadow,
        "cfg": cfg,
        "configs": configs,
        "producer": stages[0],
        "shared": shared_relative,
        "confirmation": confirmation_relative,
        "confirmation_expected_before_sha256": repair.sha256(shadow / confirmation_relative),
        "g4": g4_relative,
        "target": target,
    }


def write_product(fixture: dict[str, object], *, run_id: str = "SYNTHETIC-PRODUCER") -> Path:
    path = fixture["shadow"] / fixture["target"]
    write_json(path, {"schema_version": 1, "run_id": run_id, "effect_size_gate_pass": True})
    return path


def bind_fixture(fixture: dict[str, object], **overrides: object) -> dict[str, object]:
    shared_sha = repair.sha256(fixture["shadow"] / fixture["shared"])
    arguments = {
        "producer_stage": fixture["producer"],
        "producer_return_code": 0,
        "product_absent_before": True,
        "offset": 0.0,
        "producer_invocation_manifest_sha256": shared_sha,
        "expected_confirmation_manifest_sha256": fixture["confirmation_expected_before_sha256"],
    }
    arguments.update(overrides)
    return repair.bind_post_producer_runtime_product(
        fixture["source"], fixture["shadow"], fixture["cfg"], fixture["configs"], **arguments
    )


def build_live_authority_fixture(base: Path) -> dict[str, object]:
    """Build a complete three-manifest source authority without the user repository."""
    base.mkdir(parents=True, exist_ok=True)
    source = base / "source"
    shadow = base / "shadow"
    source.mkdir()
    shadow.mkdir()
    production = json.loads(CONFIG.read_text(encoding="utf-8"))

    executor_payloads = {
        "scripts/__init__.py": b"",
        "scripts/producer.py": b"# synthetic producer authority\n",
        "scripts/consumer.py": b"# synthetic consumer primary authority\n",
        "scripts/generator4.py": G4_BINDING_EXECUTOR_PAYLOAD,
        "src/core/causal_memory.py": (
            b"def normalize_track_time(values):\n    return values\n\n"
            b"def causal_exponential_memory(times, values, tau):\n    return values\n"
        ),
        "src/__init__.py": b"",
        "src/core/__init__.py": b"",
    }
    for relative, payload in executor_payloads.items():
        write_bytes(source / relative, payload)

    target = "outputs/generated/producer_verdict.json"
    candidate = "data/candidate.parquet"
    raw = "data/raw.parquet"
    plan = "data/track_plan.json"
    historical_plan = (
        b'{"schema_version":1,"selected_track_ids":'
        b'{"train":[0],"validation":[1],"test":[2]}}\n'
    )
    historical_plan_sha256 = sha_bytes(historical_plan)
    write_bytes(source / plan, historical_plan)
    shared = "manifests/shared.json"
    confirmation = "manifests/confirmation.json"
    g4_manifest_path = "manifests/generator4.json"
    config_paths = {
        "generator3_phase_b": "configs/producer.yaml",
        "generator3_null_screen": "configs/screen.yaml",
        "generator3_null_confirmation_2000": "configs/confirmation.yaml",
        "generator4_pooled_innovation_screen": "configs/generator4.yaml",
    }
    config_values = {
        config_paths["generator3_phase_b"]: {
            "run_id": "LIVE-PRODUCER",
            "screen": {"split_order": ["train", "validation", "test"], "complete_tracks_per_split": 1},
            "data": {"candidate_parquet": candidate},
        },
        config_paths["generator3_null_screen"]: {
            "run_id": "LIVE-SCREEN",
            "screen": {"split_order": ["train", "validation", "test"], "complete_tracks_per_split": 1},
            "data": {"phase_b_verdict": target, "candidate_parquet": candidate, "raw_track_parquet": raw},
        },
        config_paths["generator3_null_confirmation_2000"]: {
            "run_id": "LIVE-CONFIRMATION",
            "screen": {"split_order": ["train", "validation", "test"], "complete_tracks_per_split": 1},
            "data": {"phase_b_verdict": target, "candidate_parquet": candidate, "raw_track_parquet": raw},
        },
        config_paths["generator4_pooled_innovation_screen"]: {
            "run_id": "LIVE-GENERATOR4",
            "screen": {
                "split_order": ["train", "validation", "test"],
                "complete_tracks_per_split": 1,
                "exact_g3_track_plan_sha256": historical_plan_sha256,
            },
            "data": {"canonical_g3_track_plan": plan, "raw_track_parquet": raw},
        },
    }
    # BH_SIMBA_ROLE_AWARE_TEST_FIXTURE_COLUMNS_V1_5ZE
    # Copy role labels only; fixture paths, splits, controls, and assertions stay local.
    for fixture_stage, fixture_config in config_paths.items():
        production_stage = next(
            item for item in production["stage_contracts"]
            if item["stage"] == fixture_stage
        )
        production_stage_config = yaml.safe_load(
            (ROOT / production_stage["config"]).read_text(encoding="utf-8")
        )
        config_values[fixture_config]["columns"] = copy.deepcopy(
            production_stage_config["columns"]
        )

    for relative, value in config_values.items():
        write_yaml(source / relative, value)

    consumer = "scripts/consumer.py"
    historical = b'{"schema_version":1,"run_id":"HISTORICAL-PRODUCER"}\n'
    write_bytes(source / target, historical)
    shared_manifest = make_manifest({
        consumer: (b"superseded embedded consumer\n", {"bytes": len(executor_payloads[consumer])}),
        candidate: (b"historical synthetic candidate\n", None),
        raw: (b"historical synthetic raw\n", None),
    })
    confirmation_manifest = copy.deepcopy(shared_manifest)
    confirmation_manifest["files"][target] = {
        "sha256": sha_bytes(historical),
        "bytes": len(historical),
        "role": "phase_b_runtime_product",
    }
    generator4_manifest = make_manifest({
        consumer: (b"superseded embedded consumer\n", {"bytes": len(executor_payloads[consumer])}),
        plan: (historical_plan, None),
        raw: (b"historical synthetic raw\n", None),
    })
    # BH_SIMBA_PHASE_B_DEPENDENCY_TEST_FIXTURE_V1_5ZT
    write_json(source / shared, shared_manifest)
    confirmation_manifest["files"][shared] = {
        "sha256": repair.sha256(source / shared),
    }
    write_json(source / confirmation, confirmation_manifest)
    write_json(source / g4_manifest_path, generator4_manifest)

    stage_specs = [
        ("generator3_phase_b", "scripts/producer.py", shared, ["data.candidate_parquet"], target),
        (
            "generator3_null_screen", consumer, shared,
            ["data.phase_b_verdict", "data.candidate_parquet", "data.raw_track_parquet"],
            "outputs/generated/screen_verdict.json",
        ),
        (
            "generator3_null_confirmation_2000", consumer, confirmation,
            ["data.phase_b_verdict", "data.candidate_parquet", "data.raw_track_parquet"],
            "outputs/generated/confirmation_verdict.json",
        ),
        (
            "generator4_pooled_innovation_screen", "scripts/generator4.py", g4_manifest_path,
            ["data.canonical_g3_track_plan", "data.raw_track_parquet"],
            "outputs/generated/generator4_verdict.json",
        ),
    ]
    stages = []
    for name, executor, manifest, required, output in stage_specs:
        config = config_paths[name]
        stages.append({
            "stage": name,
            "executor": executor,
            "executor_sha256": repair.sha256(source / executor),
            "config": config,
            "config_sha256": repair.sha256(source / config),
            "manifest": manifest,
            "manifest_sha256": repair.sha256(source / manifest),
            "required_data_keys": required,
            "fresh_output_contract": {"fixed_relative_path": output},
        })

    runtime_binding = copy.deepcopy(production["runtime_binding"])
    runtime_binding.update({
        "target_relative_path": target,
        "producer_stage": "generator3_phase_b",
        "consumer_stages": ["generator3_null_screen", "generator3_null_confirmation_2000"],
        "producer_manifest": shared,
        "shared_manifest": shared,
        "confirmation_manifest": confirmation,
        "confirmation_template_manifest": confirmation,
        "template_target_content_sha256": sha_bytes(historical),
        "template_target_bytes": len(historical),
        "source_manifest_sha256": {
            shared: repair.sha256(source / shared),
            confirmation: repair.sha256(source / confirmation),
        },
    })
    if "dependency_refresh" in runtime_binding:
        runtime_binding["dependency_refresh"] = copy.deepcopy(
            runtime_binding["dependency_refresh"]
        )
        runtime_binding["dependency_refresh"]["child_manifest"] = shared
        runtime_binding["dependency_refresh"]["parent_manifest"] = confirmation
    synthetic = copy.deepcopy(production["synthetic_contract"])
    synthetic.update({
        "track_count": 3,
        "complete_tracks_per_split": 1,
        "track_plan_each_required_split_exact_count": 1,
        "steps_per_track": 4,
    })
    authority_resolution = copy.deepcopy(production["authority_resolution"])
    authority_resolution["known_prior_first_conflict_path"] = consumer
    cfg = {
        "schema_version": 2,
        "bundle_version": "test-live-authority",
        "authority_resolution": authority_resolution,
        "exact_sources": {
            "src/core/causal_memory.py": repair.sha256(source / "src/core/causal_memory.py"),
        },
        "shadow_package_scaffolds": copy.deepcopy(production["shadow_package_scaffolds"]),
        "stage_contracts": stages,
        "runtime_binding": runtime_binding,
        "synthetic_contract": synthetic,
        "outputs": copy.deepcopy(production["outputs"]),
    }
    # BH_SIMBA_V15X_FIXTURE_LEGACY_SINGLE_PHASE_BINDING
    cfg["authority_resolution"]["allowed_non_primary_static_paths"] = []
    cfg["runtime_binding"].pop("post_stage_generated_bindings", None)
    cfg["runtime_binding"].pop("post_stage_generated_binding_count_per_shadow", None)
    cfg["runtime_binding"].pop("post_stage_generated_receipt_schema", None)
    return {
        "source": source,
        "shadow": shadow,
        "cfg": cfg,
        "target": target,
        "shared": shared,
        "confirmation": confirmation,
        "g4": g4_manifest_path,
        "g4_config": config_paths["generator4_pooled_innovation_screen"],
        "g4_executor": "scripts/generator4.py",
        "plan": plan,
        "historical_plan_sha256": historical_plan_sha256,
        "consumer": consumer,
    }


def install_live_executor_stub(fixture: dict[str, object]) -> None:
    """Install a real CLI stub that emits one deterministic fresh verdict per stage."""
    payload = b'''#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import yaml


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
parser.add_argument("--freeze-manifest", required=True)
parser.add_argument("--repo-root", required=True)
args = parser.parse_args()
repo_root = Path(args.repo_root)
config = yaml.safe_load((repo_root / args.config).read_text(encoding="utf-8"))
run_id = config["run_id"]
if run_id == "LIVE-GENERATOR4":
    plan_path = repo_root / config["data"]["canonical_g3_track_plan"]
    expected_plan_sha256 = config["screen"]["exact_g3_track_plan_sha256"]
    observed_plan_sha256 = sha256_file(plan_path)
    if observed_plan_sha256 != expected_plan_sha256:
        raise RuntimeError("canonical_g3_track_plan_digest_mismatch")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
outputs = {
    "LIVE-PRODUCER": "outputs/generated/producer_verdict.json",
    "LIVE-SCREEN": "outputs/generated/screen_verdict.json",
    "LIVE-CONFIRMATION": "outputs/generated/confirmation_verdict.json",
    "LIVE-GENERATOR4": "outputs/generated/generator4_verdict.json",
}
target = repo_root / outputs[run_id]
target.parent.mkdir(parents=True, exist_ok=True)
value = {
    "schema_version": 1,
    "run_id": run_id,
    "effect_size": 0.25,
    "effect_size_gate_pass": True,
    "status": "pass",
}
target.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\\n", encoding="utf-8")
'''
    source = fixture["source"]
    for stage in fixture["cfg"]["stage_contracts"]:
        write_bytes(source / stage["executor"], payload)
        stage["executor_sha256"] = sha_bytes(payload)
    helper_name = "scripts/bh_simba_shadow_exact_binding_source_state_lifecycle_recovery_v1_4.py"
    helper_payload = (SCRIPTS / Path(helper_name).name).read_bytes()
    write_bytes(source / helper_name, helper_payload)
    fixture["cfg"]["adjudication_live_replay"] = {
        "schema_version": 1,
        "run_offset_module": helper_name,
        "run_offset_module_sha256": sha_bytes(helper_payload),
        "expected_fresh_temporary_shadows": 5,
        "expected_actual_executor_invocations": 20,
        "attestation_limit": "integrity_and_honest_code_execution_evidence_not_adversarial_process_attestation",
    }


def enable_live_replay_multibinder_fixture(fixture: dict[str, object]) -> None:
    production = json.loads(CONFIG.read_text(encoding="utf-8"))
    production_binding = production["runtime_binding"]
    production_post = production_binding["post_stage_generated_bindings"]
    if (
        production_binding.get("post_stage_generated_binding_count_per_shadow") != 2
        or not isinstance(production_post, list)
        or len(production_post) != 2
    ):
        raise AssertionError("production post-stage binding contract is not exact-two")
    cfg = fixture["cfg"]
    stages = {stage["stage"]: stage for stage in cfg["stage_contracts"]}

    def output_of(stage_name: str) -> str:
        contract = stages[stage_name]["fresh_output_contract"]
        value = contract.get("expected_relative_path") or contract.get("fixed_relative_path")
        if not isinstance(value, str) or not value:
            raise AssertionError(f"fixture output missing for {stage_name}")
        return value

    bindings = []
    for production_spec in production_post:
        producer = production_spec["producer_stage"]
        consumer = production_spec["consumer_stage"]
        bindings.append({
            "schema_version": 1,
            "binding_id": production_spec["binding_id"],
            "producer_stage": producer,
            "consumer_stage": consumer,
            "target_relative_path": output_of(producer),
            "target_manifest": stages[consumer]["manifest"],
            "mutation_scope": copy.deepcopy(production_spec["mutation_scope"]),
        })
    cfg["runtime_binding"]["post_stage_generated_bindings"] = bindings
    cfg["runtime_binding"]["post_stage_generated_binding_count_per_shadow"] = 2
    cfg["runtime_binding"]["post_stage_generated_receipt_schema"] = copy.deepcopy(
        production_binding["post_stage_generated_receipt_schema"]
    )

    templates = (
        (
            stages["generator3_null_confirmation_2000"]["manifest"],
            output_of("generator3_null_screen"),
            "HISTORICAL-SCREEN",
        ),
        (
            stages["generator4_pooled_innovation_screen"]["manifest"],
            output_of("generator3_null_confirmation_2000"),
            "HISTORICAL-CONFIRMATION",
        ),
    )
    for manifest_relative, target_relative, historical_run_id in templates:
        manifest_path = fixture["source"] / manifest_relative
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = (
            json.dumps(
                {"schema_version": 1, "run_id": historical_run_id},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        manifest["files"][target_relative] = {
            "sha256": sha_bytes(payload),
            "role": "declared_generated_runtime_template",
        }
        write_json(manifest_path, manifest)

    refresh_live_manifest_pins(fixture)


def prepare_live_fixture_only(
    fixture: dict[str, object], offset: float
) -> tuple[dict[str, dict], dict[str, object]]:
    with mock.patch("pandas.DataFrame.to_parquet", new=deterministic_parquet_stub):
        return repair.prepare_shadow(fixture["source"], fixture["shadow"], fixture["cfg"], offset)


def refresh_live_manifest_pins(fixture: dict[str, object]) -> None:
    """Refresh only the test fixture's immutable source-manifest authorities."""
    binding = fixture["cfg"]["runtime_binding"]
    dependency = binding.get("dependency_refresh")
    if dependency is not None:
        child = dependency["child_manifest"]
        parent = dependency["parent_manifest"]
        parent_path = fixture["source"] / parent
        parent_value = json.loads(parent_path.read_text(encoding="utf-8"))
        parent_value["files"][child][dependency["record_field"]] = repair.sha256(
            fixture["source"] / child
        )
        write_json(parent_path, parent_value)
    for stage in fixture["cfg"]["stage_contracts"]:
        stage["manifest_sha256"] = repair.sha256(
            fixture["source"] / stage["manifest"]
        )
    fixture["cfg"]["runtime_binding"]["source_manifest_sha256"] = {
        fixture["shared"]: repair.sha256(fixture["source"] / fixture["shared"]),
        fixture["confirmation"]: repair.sha256(
            fixture["source"] / fixture["confirmation"]
        ),
    }


def prepare_and_bind_live_fixture(
    fixture: dict[str, object], offset: float
) -> tuple[dict[str, dict], dict[str, object], dict[str, object]]:
    source = fixture["source"]
    shadow = fixture["shadow"]
    cfg = fixture["cfg"]
    frozen = repair.original_authority_hashes(source, cfg)
    configs, audit = prepare_live_fixture_only(fixture, offset)
    preflight = repair.runtime_binding_preflight(source, shadow, cfg, configs)
    if not preflight["pass"]:
        raise AssertionError(preflight)
    construction_by_path = {
        item["relative_path"]: item
        for item in audit["construction_manifest_mutation_receipts"]
    }
    product = fixture["shadow"] / fixture["target"]
    write_json(product, {"schema_version": 1, "run_id": "LIVE-PRODUCER", "effect_size_gate_pass": True})
    receipt = repair.bind_post_producer_runtime_product(
        source,
        shadow,
        cfg,
        configs,
        producer_stage=cfg["stage_contracts"][0],
        producer_return_code=0,
        product_absent_before=True,
        offset=float(offset),
        producer_invocation_manifest_sha256=construction_by_path[fixture["shared"]]["after_sha256"],
        expected_confirmation_manifest_sha256=construction_by_path[fixture["confirmation"]]["after_sha256"],
    )
    manifests = sorted({stage["manifest"] for stage in cfg["stage_contracts"]})
    audit.update({
        "offset": float(offset),
        "runtime_binding_preflight": preflight,
        "runtime_product_binding_receipts": [receipt],
        "runtime_binding_receipt_count": 1,
        "runtime_binding_receipts_pass": bool(
            receipt.get("binding_pass") is True
            and repair.runtime_binding_receipt_exact(receipt, cfg, source)
            and repair.construction_audit_exact(audit, cfg, receipt, source)
        ),
        "runtime_binding_provenance_chain_pass": True,
        "manifest_provenance_chain_pass": True,
        "final_manifest_closures": [
            repair.audit_executor_manifest_closure(shadow, manifest) for manifest in manifests
        ],
        "manifest_byte_invariance_pass": True,
        "source_authorities_unchanged": repair.authorities_unchanged(source, frozen),
        "source_authorities_unchanged_after_offset": repair.authorities_unchanged(source, frozen),
    })
    audit["full_manifest_closure_pass"] = all(
        item["closure_pass"] for item in audit["final_manifest_closures"]
    )
    return configs, audit, receipt


class BundleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_01_v14_config_and_seven_gate_files_exist(self):
        self.assertEqual(self.cfg["bundle_version"], "1.4")
        self.assertTrue(CONFIG.is_file())
        self.assertTrue(RUNNER.is_file())
        self.assertTrue(all((SCRIPTS / name).is_file() for name in GATE_NAMES))

    def test_02_run_ids_are_unique_and_versioned(self):
        keys = (
            "cli_repair_design_run_id", "manifest_preflight_run_id", "smoke_run_id",
            "acceptance_run_id", "matrix_run_id", "adjudication_run_id", "final_route_run_id",
        )
        suffixes = ("217A-R3A", "217A-R4A", "217B-R3", "217C-R3", "218-R3", "219-R3", "220-R3")
        values = [self.cfg[key] for key in keys]
        self.assertEqual(len(set(values)), 7)
        self.assertTrue(all(value.endswith(suffix) for value, suffix in zip(values, suffixes)))

    def test_03_current_outputs_are_disjoint_from_failed_217a_custody(self):
        output = Path(self.cfg["outputs"]["directory"])
        current = {
            (output / value).as_posix()
            for key, value in self.cfg["outputs"].items()
            if key not in {"directory", "protocol_entry"}
        }
        failed = self.cfg["failed_run_217A"]
        self.assertNotIn(failed["verdict"], current)
        self.assertNotIn(failed["evidence"], current)
        self.assertNotEqual(output.as_posix(), str(Path(failed["verdict"]).parent))

    def test_04_failed_217a_custody_is_exact_and_immutable(self):
        failed = self.cfg["failed_run_217A"]
        self.assertEqual(failed["disposition"], "immutable_failed_prerequisite_not_overwritten")
        self.assertEqual(failed["verdict_sha256"], "69e61ee83341b66874c9986de5c02677756f5ecfd732aa5074c2d5274adb639b")
        self.assertEqual(failed["evidence_sha256"], "f5cf87cbfc2d7ee26c7ac4b5962121ff577d376a6848b5e7dcbea90063aafcef")
        self.assertFalse(failed["expected_fields"]["manifest_concordance_preflight_pass"])

    def test_04a_run_209_release_field_authority_is_exactly_pinned(self):
        self.assertEqual(self.cfg["release_field_authority"], {
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
        })
        self.assertEqual(
            self.cfg["inputs"]["prior_release_field_verdict"],
            self.cfg["release_field_authority"]["path"],
        )
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("KNOWN_RELEASE_FIELD_AUTHORITY", runner)
        self.assertIn(
            "52b0b76290cc7407745b09410ad180ba68c81d3f972b5bfc6955674f63d3d9c1",
            runner,
        )
        self.assertIn(
            "27e6552a0451b1996f1c89098e7d35c566942c77ef66e4d0094e01db9eebb4d9",
            runner,
        )

    def test_04b_every_release_authority_gate_uses_the_complete_pin_spec(self):
        for name in (GATE_NAMES[0], GATE_NAMES[3], GATE_NAMES[5], GATE_NAMES[6]):
            source = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn(
                'release_field_authority(root, cfg.get("release_field_authority"))',
                source,
            )
            self.assertNotIn(
                'release_field_authority(root, cfg["inputs"]["prior_release_field_verdict"])',
                source,
            )

    def test_04c_v13_custody_rejects_each_missing_or_tampered_artifact(self):
        for failure in ("missing", "tampered"):
            for artifact_index in range(2):
                with self.subTest(failure=failure, artifact_index=artifact_index):
                    with tempfile.TemporaryDirectory() as temporary:
                        root = Path(temporary)
                        cfg = copy.deepcopy(self.cfg)
                        spec = cfg["prior_v1_3_attempt_custody"]
                        artifact_names = list(spec["artifacts"])
                        design_name = spec["design_verdict"]
                        for name in artifact_names:
                            path = root / name
                            if name == design_name:
                                write_json(path, copy.deepcopy(spec["expected_design_fields"]))
                            else:
                                write_bytes(path, b"role,path,status\nfixture,fixture,held\n")
                            spec["artifacts"][name]["sha256"] = repair.sha256(path)

                        baseline = common.prior_v1_3_attempt_custody_exact(root, cfg)
                        self.assertTrue(baseline["pass"], baseline)
                        target = root / artifact_names[artifact_index]
                        if failure == "missing":
                            target.unlink()
                        else:
                            target.write_bytes(target.read_bytes() + b"tamper\n")
                        held = common.prior_v1_3_attempt_custody_exact(root, cfg)
                        self.assertFalse(held["pass"], held)
                        self.assertEqual(held["artifact_digest_match_count"], 1)

    def test_04d_all_seven_gates_use_the_v13_custody_authority(self):
        for name in GATE_NAMES:
            with self.subTest(gate=name):
                source = (SCRIPTS / name).read_text(encoding="utf-8")
                tree = ast.parse(source)
                imported = any(
                    isinstance(node, ast.ImportFrom)
                    and any(
                        alias.name == "prior_v1_3_attempt_custody_exact"
                        for alias in node.names
                    )
                    for node in ast.walk(tree)
                )
                calls = [
                    node for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "prior_v1_3_attempt_custody_exact"
                ]
                self.assertTrue(imported)
                self.assertGreaterEqual(len(calls), 1)

    def test_04e_execution_gates_guard_and_recheck_v13_custody(self):
        smoke = (SCRIPTS / GATE_NAMES[2]).read_text(encoding="utf-8").split(
            "def main() -> int:", 1
        )[1]
        matrix = (SCRIPTS / GATE_NAMES[4]).read_text(encoding="utf-8").split(
            "def main() -> int:", 1
        )[1]
        adjudication = (SCRIPTS / GATE_NAMES[5]).read_text(encoding="utf-8").split(
            "def main() -> int:", 1
        )[1]

        for body, precheck, postcheck, execution_call, pass_expression in (
            (
                smoke,
                '"failed_v1_3_R3_custody_exact_before_smoke"',
                '"failed_v1_3_R3_custody_exact_after_smoke"',
                "run_offset(",
                "passed = all(checks.values())",
            ),
            (
                matrix,
                '"failed_v1_3_R3_custody_exact_before_matrix"',
                '"failed_v1_3_R3_custody_exact_after_matrix"',
                "run_offset(",
                "process_pass = matrix_complete and all(checks.values())",
            ),
            (
                adjudication,
                '"failed_v1_3_R3_custody_exact_before_live_replay"',
                '"failed_v1_3_R3_custody_exact_after_live_replay"',
                "execute_live_replay_only_after_prechecks(",
                "passed = all(checks.values())",
            ),
        ):
            with self.subTest(execution_call=execution_call):
                self.assertLess(body.index(precheck), body.index(execution_call))
                self.assertLess(body.index(execution_call), body.index(postcheck))
                self.assertIn(pass_expression, body)
        self.assertIn("if all(prerequisites.values()):", smoke)
        self.assertIn("if not all(prerequisites.values()):", matrix)

    def test_04f_acceptance_cannot_authorize_without_both_v13_custody_files(self):
        source = (SCRIPTS / GATE_NAMES[3]).read_text(encoding="utf-8")
        self.assertEqual(len(self.cfg["prior_v1_3_attempt_custody"]["artifacts"]), 2)
        self.assertIn('len(configured_v1_3_custody) != 2', source)
        self.assertIn('accepted_files[name] = record', source)
        self.assertIn('"failed_v1_3_R3_custody_exact_at_acceptance"', source)
        self.assertIn('"failed_v1_3_R3_custody_files_collision_free"', source)
        self.assertIn("passed = all(checks.values())", source)
        self.assertIn('"matrix_execution_authorized": passed', source)

    def test_04g_final_route_separates_and_freezes_both_custody_classes(self):
        v1_2 = self.cfg["prior_attempt_custody"]["artifacts"]
        v1_3 = self.cfg["prior_v1_3_attempt_custody"]["artifacts"]
        self.assertEqual(len(v1_2), 4)
        self.assertEqual(len(v1_3), 2)
        self.assertFalse(set(v1_2) & set(v1_3))
        source = (SCRIPTS / GATE_NAMES[6]).read_text(encoding="utf-8")
        for exact_fragment in (
            "custody_group_final_files_collision_free(v1_2_custody_records, 4)",
            "custody_group_final_files_collision_free(v1_3_custody_records, 2)",
            "len(custody_records) == 6",
            '"artifacts": v1_2_custody_records',
            '"artifacts": v1_3_custody_records',
        ):
            self.assertIn(exact_fragment, source)
        self.assertIn("for name, record in custody_records.items():", source)
        self.assertIn("final_files[name] = record", source)

    def test_04h_matrix_custody_hold_cannot_emit_a_sensitivity_outcome(self):
        source = (SCRIPTS / GATE_NAMES[4]).read_text(encoding="utf-8")
        self.assertIn(
            '"failed_v1_3_R3_custody_exact_after_matrix": (', source
        )
        self.assertIn("process_pass = matrix_complete and all(checks.values())", source)
        self.assertIn('"stage_invariance": invariance if process_pass else {}', source)
        self.assertIn(
            '"observable_evidence": observable_evidence if process_pass else []',
            source,
        )
        self.assertIn(
            '"selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved": resolved',
            source,
        )
        self.assertIn(
            '"selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected": rejected',
            source,
        )
        self.assertIn("resolved = process_pass and candidate_resolved", source)
        self.assertIn("rejected = process_pass and candidate_rejected", source)

    def test_05_four_stage_dependency_chain_and_three_executors_are_frozen(self):
        stages = self.cfg["stage_contracts"]
        self.assertEqual([item["stage"] for item in stages], repair.EXPECTED_STAGE_ORDER)
        self.assertEqual(len(stages), 4)
        self.assertEqual(len({item["executor"] for item in stages}), 3)
        self.assertEqual(len({item["manifest"] for item in stages}), 3)

    def test_05aa_design_gate_accepts_seven_exact_sources_plus_three_scaffolds(self):
        expected = {
            "scripts/84_run_tng50_canonical_generator3_phase_b.py",
            "scripts/85_screen_tng50_canonical_generator3_full_history_null.py",
            "scripts/89_screen_tng50_memory_generator4_pooled_innovation.py",
            "src/core/causal_memory.py",
            "src/core/innovation_memory.py",
            "src/core/memory_nulls.py",
            "src/core/predictive_memory.py",
        }
        self.assertEqual(set(self.cfg["exact_sources"]), expected)
        self.assertEqual(
            set(self.cfg["shadow_package_scaffolds"]["paths"]),
            {"scripts/__init__.py", "src/__init__.py", "src/core/__init__.py"},
        )
        self.assertTrue(repair.package_scaffold_contract_exact(self.cfg))
        self.assertEqual(
            len(set(self.cfg["exact_sources"]) | set(self.cfg["shadow_package_scaffolds"]["paths"])),
            10,
        )
        design_source = (SCRIPTS / GATE_NAMES[0]).read_text(encoding="utf-8")
        self.assertIn('"original_seven_exact"', design_source)
        self.assertIn('"scaffold_triplet_admissible"', design_source)

    def test_05ab_scaffold_source_states_accept_only_absent_or_exact_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            absent = repair.package_scaffold_source_census(source, self.cfg)
            self.assertTrue(absent["census_pass"], absent)
            self.assertEqual(set(absent["source_states"].values()), {"absent"})

            for relative in repair.PACKAGE_SCAFFOLD_PATHS:
                write_bytes(source / relative, b"")
            exact_empty = repair.package_scaffold_source_census(source, self.cfg)
            self.assertTrue(exact_empty["census_pass"], exact_empty)
            self.assertEqual(
                set(exact_empty["source_states"].values()), {"exact_empty"}
            )

            write_bytes(source / "src/__init__.py", b"not empty\n")
            nonempty = repair.package_scaffold_source_census(source, self.cfg)
            self.assertFalse(nonempty["census_pass"])
            self.assertEqual(
                nonempty["source_states"]["src/__init__.py"],
                "nonempty_regular",
            )

    def test_05a_all_production_stage_outputs_have_declared_and_derived_authorities(self):
        for stage in self.cfg["stage_contracts"]:
            contract = stage["fresh_output_contract"]
            self.assertEqual(
                contract["config_dotted_path_mapping"],
                {"root": "outputs.root", "label": "outputs.label"},
            )
            self.assertEqual(contract["filename_template"], "{outputs.label}_verdict.json")
            self.assertIsInstance(contract["expected_label"], str)
            self.assertEqual(
                repair.canonical_relative(contract["expected_relative_path"]),
                contract["expected_relative_path"],
            )

    def test_05b_generator4_output_path_and_derivation_policy_are_explicit(self):
        stage = self.cfg["stage_contracts"][-1]
        contract = stage["fresh_output_contract"]
        self.assertEqual(stage["stage"], "generator4_pooled_innovation_screen")
        self.assertEqual(
            contract["expected_label"],
            "bh_tng50_memory_generator4_pooled_innovation_screen",
        )
        self.assertEqual(
            contract["expected_relative_path"],
            "outputs/protocol/tng50_memory_generator4_pooled_innovation/"
            "bh_tng50_memory_generator4_pooled_innovation_screen_verdict.json",
        )
        self.assertEqual(
            contract["expected_relative_path_policy"],
            "declared_expected_path_must_equal_hash_pinned_config_root_label_and_filename_template",
        )

    def test_05c_declared_stage_output_must_equal_config_derived_output(self):
        config = {"outputs": {"root": "outputs/frozen", "label": "frozen_label"}}
        stage = {
            "stage": "synthetic_stage",
            "fresh_output_contract": {
                "config_dotted_path_mapping": {
                    "root": "outputs.root",
                    "label": "outputs.label",
                },
                "filename_template": "{outputs.label}_verdict.json",
                "expected_label": "frozen_label",
                "expected_relative_path": "outputs/frozen/frozen_label_verdict.json",
            },
        }
        self.assertEqual(
            repair.stage_expected_output(config, stage),
            "outputs/frozen/frozen_label_verdict.json",
        )
        changed_path = copy.deepcopy(stage)
        changed_path["fresh_output_contract"]["expected_relative_path"] = (
            "outputs/frozen/other_verdict.json"
        )
        with self.assertRaisesRegex(RuntimeError, "stage_output_path_changed:synthetic_stage"):
            repair.stage_expected_output(config, changed_path)
        changed_root = copy.deepcopy(config)
        changed_root["outputs"]["root"] = "outputs/changed"
        with self.assertRaisesRegex(RuntimeError, "stage_output_path_changed:synthetic_stage"):
            repair.stage_expected_output(changed_root, stage)

    def test_05d_declared_stage_output_cannot_downgrade_to_a_fixed_alias(self):
        config = {"outputs": {"root": "outputs/frozen", "label": "frozen_label"}}
        stage = {
            "stage": "synthetic_stage",
            "fresh_output_contract": {
                "fixed_relative_path": "outputs/alias.json",
                "config_dotted_path_mapping": {
                    "root": "outputs.root",
                    "label": "outputs.label",
                },
                "filename_template": "{outputs.label}_verdict.json",
                "expected_relative_path": "outputs/frozen/frozen_label_verdict.json",
            },
        }
        with self.assertRaisesRegex(RuntimeError, "fixed_stage_output_path_changed:synthetic_stage"):
            repair.stage_expected_output(config, stage)

    def test_05e_generator4_track_plan_binding_schema_is_exact(self):
        declarations = self.cfg["authority_resolution"][
            "schema_specific_config_integrity_bindings"
        ]
        self.assertEqual(declarations, [{
            "schema_version": 1,
            "binding_id": "generator4_exact_g3_track_plan_sha256_v1",
            "stage": "generator4_pooled_innovation_screen",
            "path_dotted_key": "data.canonical_g3_track_plan",
            "digest_dotted_key": "screen.exact_g3_track_plan_sha256",
            "algorithm": "sha256",
            "consumer_proof": "pinned_executor_ast_same_path_sha256_guard",
        }])
        generator4 = next(
            stage for stage in self.cfg["stage_contracts"]
            if stage["stage"] == "generator4_pooled_innovation_screen"
        )
        self.assertEqual(
            repair.bindings_for_document(self.cfg, generator4["config"]),
            tuple(copy.deepcopy(declarations)),
        )
        for stage in self.cfg["stage_contracts"]:
            if stage is not generator4:
                self.assertEqual(
                    repair.bindings_for_document(self.cfg, stage["config"]), ()
                )

    def test_06_exact_command_passes_required_manifest_and_shadow_root(self):
        text = (SCRIPTS / "bh_simba_shadow_exact_binding_source_state_lifecycle_recovery_v1_4.py").read_text(encoding="utf-8")
        command = text.split("def execute_stage(", 1)[1].split("environment =", 1)[0]
        for flag in ('"--config"', '"--freeze-manifest"', '"--repo-root"'):
            self.assertIn(flag, command)
        self.assertIn("stage[\"manifest\"]", command)
        self.assertIn("str(shadow)", command)

    def test_06a_adjudication_live_replay_implementation_is_hash_pinned(self):
        replay = self.cfg["adjudication_live_replay"]
        module = ROOT / replay["run_offset_module"]
        self.assertEqual(replay["schema_version"], 1)
        self.assertEqual(repair.sha256(module), replay["run_offset_module_sha256"])
        self.assertEqual(replay["expected_fresh_temporary_shadows"], 5)
        self.assertEqual(replay["expected_actual_executor_invocations"], 20)
        self.assertIn(
            replay["run_offset_module_sha256"],
            RUNNER.read_text(encoding="utf-8"),
        )

    def test_07_run_offset_has_no_generic_interstage_refresh(self):
        text = (SCRIPTS / "bh_simba_shadow_exact_binding_source_state_lifecycle_recovery_v1_4.py").read_text(encoding="utf-8")
        run_offset = text.split("def run_offset(", 1)[1]
        self.assertNotIn("refresh_integrity_records(", run_offset)
        self.assertNotIn("prepare_shadow(source_root, shadow, cfg, offset)", run_offset.split("for stage in stage_list:", 1)[1])
        self.assertEqual(self.cfg["repair_contract"]["generic_interstage_manifest_or_config_refresh"], False)

    def test_08_runner_is_no_exit_retains_terminal_and_uses_exact_test(self):
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn("set +e", text)
        self.assertNotIn("set -e", text)
        self.assertIn("Terminal retained.", text)
        self.assertIn("test_bh_simba_bondi_shadow_exact_binding_source_state_lifecycle_recovery.py", text)
        self.assertNotIn("test_*.py", text)
        self.assertTrue(text.rstrip().endswith("true"))

    def test_08a_runner_distinguishes_not_started_from_executed_holds(self):
        text = RUNNER.read_text(encoding="utf-8")
        state_function = text.split("print_gate_state() {", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('if [ "$GATE_EXECUTED" -eq 1 ]', state_function)
        self.assertIn("executed; exit code=", state_function)
        self.assertIn("not required; status code=0", state_function)
        self.assertIn("not started; initialized hold code=", state_function)
        for variable in (
            "QUARANTINE_EXECUTED", "RUN217AR3_EXECUTED", "RUN217AR4_EXECUTED",
            "RUN217BR3_EXECUTED", "RUN217CR3_EXECUTED", "RUN218R3_EXECUTED",
            "RUN219R3_EXECUTED", "CUSTODY_PRE220_EXECUTED", "RUN220R3_EXECUTED",
        ):
            self.assertIn(f"{variable}=0", text)
            self.assertIn(f'"${variable}"', text)
        self.assertNotIn(
            'echo "Run 217A-R3A exact-binding/source-state/lifecycle design exit code:',
            text,
        )

    def test_08b_cleanup_failures_cannot_be_presented_as_success(self):
        text = RUNNER.read_text(encoding="utf-8")
        for rc_name, executed_name in (
            ("ENTRY_HOLD_CLEANUP_RC", "ENTRY_HOLD_CLEANUP_EXECUTED"),
            ("MARKER_CLEANUP_RC", "MARKER_CLEANUP_EXECUTED"),
            ("FINAL_POST_STATE_RC", "FINAL_POST_STATE_EXECUTED"),
        ):
            self.assertIn(f"{rc_name}=125", text)
            self.assertIn(f"{executed_name}=0", text)
        success_assignment = text.rsplit("RUN_STATUS=0", 1)[0][-500:]
        self.assertIn('"$CORE_COMPLETION_PASS" -eq 1', success_assignment)
        self.assertIn('"$MARKER_CLEANUP_RC" -eq 0', success_assignment)
        self.assertIn('"$FINAL_POST_STATE_RC" -eq 0', success_assignment)
        for label, executed, rc_name in (
            ("Protocol Entry 128 completion guard", "ENTRY_GUARD_EXECUTED", "ENTRY_GUARD_RC"),
            ("held completion-artifact cleanup", "ENTRY_HOLD_CLEANUP_EXECUTED", "ENTRY_HOLD_CLEANUP_RC"),
            ("current-run marker cleanup", "MARKER_CLEANUP_EXECUTED", "MARKER_CLEANUP_RC"),
            ("final completion post-state", "FINAL_POST_STATE_EXECUTED", "FINAL_POST_STATE_RC"),
        ):
            self.assertIn(
                f'print_gate_state "{label}" "${executed}" "${rc_name}"',
                text,
            )

    def test_08ba_marker_cleanup_failure_demotes_and_recovers_before_post_state(self):
        text = RUNNER.read_text(encoding="utf-8")
        trigger = (
            'if [ "$CORE_COMPLETION_PASS" -eq 1 ] '
            '&& [ "$MARKER_CLEANUP_RC" -ne 0 ]; then'
        )
        fallback_start = text.index(trigger)
        post_state_start = text.index(
            "# The final state is checked after marker cleanup.", fallback_start
        )
        fallback = text[fallback_start:post_state_start]
        self.assertLess(
            fallback.index("CORE_COMPLETION_PASS=0"),
            fallback.index("authority.validate_entry_transaction("),
        )
        self.assertIn('"bh_simba_v14_marker_failure_fallback"', fallback)
        self.assertIn('allowed_states={"committed"}', fallback)
        self.assertIn("for path in (entry, final_route):", fallback)
        self.assertIn("marker.unlink()", fallback)
        self.assertLess(
            fallback.index("for path in (entry, final_route):"),
            fallback.index("marker.unlink()"),
        )
        self.assertIn("ENTRY_HOLD_CLEANUP_RC=$?", fallback)
        self.assertNotIn("MARKER_CLEANUP_RC=0", fallback)
        self.assertLess(fallback_start, post_state_start)

    def test_08c_footer_claims_are_conditional_and_observation_scoped(self):
        text = RUNNER.read_text(encoding="utf-8")
        footer = text.split(
            'echo "The configured historical scope for Runs 214--217 is selected semantic/path continuity',
            1,
        )[1]
        self.assertIn('if [ "$QUARANTINE_EXECUTED" -eq 1 ]', footer)
        self.assertIn(
            "actual recoverable moves, if any, are only those reported by [custody] lines above.",
            footer,
        )
        self.assertIn('if [ "$RUN217BR3_EXECUTED" -eq 0 ]', footer)
        self.assertIn('if [ "$RUN217AR3_RC" -eq 0 ]', footer)
        self.assertIn('if [ "$RUN219R3_EXECUTED" -eq 1 ]', footer)
        self.assertIn('if [ "$RUN220R3_EXECUTED" -eq 1 ]', footer)
        self.assertIn(
            'if [ "$RUN_STATUS" -eq 0 ] && [ "$ENTRY_GUARD_RC" -eq 0 ] '
            '&& [ "$FINAL_POST_STATE_RC" -eq 0 ]',
            footer.replace("\\\n  ", ""),
        )
        for unconditional_claim in (
            "prior v1.4 generated artifacts were recoverably quarantined when the gate chain opened.",
            "Every invoked exact executor was required to receive",
            "The frozen lifecycle permits Phase-B runtime-product binding",
            "Run 219-R3 required an independent current 20/20 live replay",
            "Only the transactionally written Entry 128 TeX was accepted",
            "The route supplied and authorized only the declared synthetic inputs",
        ):
            self.assertNotIn(f'echo "{unconditional_claim}', footer)

    def test_09_runner_and_scripts_never_mutate_git_history(self):
        text = RUNNER.read_text(encoding="utf-8") + "\n" + "\n".join(
            path.read_text(encoding="utf-8") for path in SCRIPT_PATHS
        )
        for command in ("git add", "git commit", "git tag", "git push", "git reset"):
            self.assertNotIn(command, text)

    def test_10_synthetic_matrix_is_exactly_five_by_four(self):
        synthetic = self.cfg["synthetic_contract"]
        self.assertEqual(len(synthetic["offsets"]), 5)
        self.assertEqual(len(self.cfg["stage_contracts"]) * len(synthetic["offsets"]), 20)
        self.assertEqual(synthetic["baseline_offset"], 0.0)

    def test_11_fixture_contract_is_1200_three_times_400(self):
        synthetic = self.cfg["synthetic_contract"]
        self.assertEqual(synthetic["track_count"], 1200)
        self.assertEqual(synthetic["complete_tracks_per_split"], 400)
        self.assertEqual(synthetic["required_splits"], ["train", "validation", "test"])
        self.assertEqual(synthetic["track_count"], 3 * synthetic["complete_tracks_per_split"])

    def test_12_runtime_receipt_contract_is_exact_unique_and_gate_accepted(self):
        required_list = self.cfg["runtime_binding"]["receipt_schema"]["required_fields"]
        required = set(required_list)
        expected = {
            "schema_version", "offset", "producer_stage", "producer_return_code",
            "target_relative_path",
            "product_payload_b64", "product_json_run_id", "product_json_schema_version",
            "target_sha256", "target_bytes", "template_manifest_relative_path",
            "template_manifest_source_sha256",
            "template_record_sha256", "preproducer_target_absent",
            "confirmation_manifest_expected_before_sha256", "manifest_mutations",
            "exact_mutation_scope_pass", "atomic_replacement_pass",
            "downstream_full_manifest_closure_pass",
            "downstream_three_of_three_input_concordance_pass",
            "receipt_payload_sha256", "receipt_sha256",
        }
        self.assertEqual(len(required_list), 22)
        self.assertEqual(len(required), 22)
        self.assertEqual(required, expected)
        self.assertEqual(self.cfg["runtime_binding"]["receipt_count_per_shadow"], 1)
        design_gate = load_gate(GATE_NAMES[0], "gate359_lifecycle_contract")
        self.assertTrue(design_gate.lifecycle_contract_exact(self.cfg))

        missing = copy.deepcopy(self.cfg)
        missing["runtime_binding"]["receipt_schema"]["required_fields"].pop()
        self.assertFalse(design_gate.lifecycle_contract_exact(missing))

        duplicate = copy.deepcopy(self.cfg)
        duplicate["runtime_binding"]["receipt_schema"]["required_fields"].append(
            required_list[0]
        )
        self.assertFalse(design_gate.lifecycle_contract_exact(duplicate))

        extra = copy.deepcopy(self.cfg)
        extra["runtime_binding"]["receipt_schema"]["required_fields"].append(
            "unapproved_receipt_field"
        )
        self.assertFalse(design_gate.lifecycle_contract_exact(extra))

    def test_13_physical_and_scientific_axes_remain_closed(self):
        authorization = self.cfg["execution_authorizations"]
        for key in (
            "network", "SIMBA_scientific_payload", "raw_SIMBA_values", "SIMBA_coordinate",
            "SIMBA_tracks", "zero_policy", "SIMBA_adapter", "scientific_memory_generator_execution",
        ):
            self.assertIs(authorization[key], False)
        self.assertIn("physical_units", self.cfg["claim_cap"])

    def test_14_all_python_files_parse_without_the_user_repository(self):
        for path in (*SCRIPT_PATHS, Path(__file__)):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_15_shipped_code_imports_no_network_or_simba_reader(self):
        forbidden = {"requests", "urllib", "httpx", "aiohttp", "h5py"}
        for path in SCRIPT_PATHS:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
            self.assertFalse(imports & forbidden, f"{path.name}: {imports & forbidden}")


class PathAndManifestTests(unittest.TestCase):
    def test_16_canonical_relative_accepts_one_shadow_relative_path(self):
        self.assertEqual(repair.canonical_relative("outputs/a.json"), "outputs/a.json")
        self.assertEqual(repair.safe_relative("outputs/a.json").as_posix(), "outputs/a.json")

    def test_17_canonical_relative_rejects_escape_absolute_and_drive_paths(self):
        for value in ("../escape", "a/../../escape", "/tmp/escape", "C:/escape", "", "a/../b"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                repair.canonical_relative(value)

    def test_18_noncanonical_alias_is_rejected_before_manifest_collision(self):
        manifest = {
            "files": {
                "data/a.bin": {"sha256": "a" * 64},
                "data\\a.bin": {"sha256": "a" * 64},
            }
        }
        with self.assertRaisesRegex(RuntimeError, "unsafe_shadow_path"):
            repair.exact_manifest_file_records(manifest)

    def test_19_manifest_requires_nonempty_top_level_files(self):
        for manifest in ({}, {"files": {}}, {"files": []}):
            with self.subTest(manifest=manifest), self.assertRaises(RuntimeError):
                repair.exact_manifest_file_records(manifest)

    def test_20_manifest_rejects_malformed_digest_and_record(self):
        for record in ({"sha256": "short"}, "not-a-record"):
            with self.subTest(record=record), self.assertRaises(RuntimeError):
                repair.exact_manifest_file_records({"files": {"data/a": record}})

    def test_20a_manifest_rejects_malformed_alternate_content_fields(self):
        for record in (
            {"sha256": "a" * 64, "digest": "short"},
            {"sha256": "a" * 64, "size": -1},
            {"sha256": "a" * 64, "bytes": True},
        ):
            with self.subTest(record=record), self.assertRaises(RuntimeError):
                repair.exact_manifest_file_records({"files": {"data/a": record}})

    def test_20b_manifest_rejects_unsupported_integrity_looking_fields(self):
        for field, value in (
            ("content_sha256", "b" * 64),
            ("content_length", 1),
            ("contentLength", 1),
            ("checksum", "b" * 64),
            ("contentSHA256", "b" * 64),
            ("payload_size", 1),
        ):
            record = {"sha256": "a" * 64, "bytes": 1, field: value}
            with self.subTest(field=field), self.assertRaisesRegex(
                RuntimeError, "unsupported_manifest_integrity_field"
            ):
                repair.exact_manifest_file_records({"files": {"data/a": record}})

    def test_21_full_top_level_manifest_closure_accepts_every_exact_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_bytes(root / "data/a", b"a")
            write_bytes(root / "data/b", b"b")
            write_json(root / "manifest.json", make_manifest({"data/a": (b"a", None), "data/b": (b"b", None)}))
            audit = repair.audit_executor_manifest_closure(root, "manifest.json")
            self.assertTrue(audit["closure_pass"])
            self.assertEqual(audit["manifest_file_record_count"], 2)
            self.assertEqual(audit["manifest_file_existing_count"], 2)
            self.assertEqual(audit["manifest_file_digest_match_count"], 2)

    def test_22_full_closure_rejects_unrelated_missing_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_bytes(root / "data/required", b"required")
            manifest = make_manifest({"data/required": (b"required", None), "data/unrelated": (b"missing", None)})
            write_json(root / "manifest.json", manifest)
            audit = repair.audit_executor_manifest_closure(root, "manifest.json")
            self.assertFalse(audit["closure_pass"])
            self.assertEqual(audit["manifest_file_record_count"], 2)
            self.assertEqual(audit["manifest_file_existing_count"], 1)

    def test_23_full_closure_rejects_unrelated_digest_tamper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_bytes(root / "data/required", b"required")
            write_bytes(root / "data/unrelated", b"tampered")
            manifest = make_manifest({"data/required": (b"required", None), "data/unrelated": (b"original", None)})
            write_json(root / "manifest.json", manifest)
            self.assertFalse(repair.audit_executor_manifest_closure(root, "manifest.json")["closure_pass"])

    def test_23a_full_closure_rejects_conflicting_alternate_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_bytes(root / "data/value", b"value")
            manifest = make_manifest({"data/value": (b"value", None)})
            manifest["files"]["data/value"]["digest"] = "f" * 64
            write_json(root / "manifest.json", manifest)
            self.assertFalse(
                repair.audit_executor_manifest_closure(root, "manifest.json")["closure_pass"]
            )

    def test_23b_sibling_integrity_uses_only_explicit_path_grammar(self):
        self.assertEqual(
            repair.sibling_integrity_fields(
                {"run_id": "not/a/path", "run_sha256": "a" * 64}, "run_id"
            ),
            ([], []),
        )
        self.assertEqual(
            repair.sibling_integrity_fields(
                {"path": "data/value", "sha256": "a" * 64, "bytes": 5}, "path"
            ),
            (["sha256"], ["bytes"]),
        )

    def test_23c_malformed_config_sibling_integrity_cannot_be_refreshed(self):
        for value in (
            {
                "track_plan": "data/plan.json",
                "track_plan_sha256": "bogus",
                "track_plan_bytes": 7,
            },
            {
                "track_plan": "data/plan.json",
                "track_plan_sha256": "a" * 64,
                "track_plan_bytes": -7,
            },
        ):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                repair.assert_unambiguous_sibling_integrity(value)

    def test_23d_alternate_sibling_hash_and_generic_path_forms_are_inventoried(self):
        claims = repair.manifest_sibling_integrity_claims({
            "files": {"data/x": {"sha256": "a" * 64}},
            "track_plan": "data/x",
            "track_plan_hash": "b" * 64,
        })
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["digest_field"], "track_plan_hash")
        generic = repair.manifest_sibling_integrity_claims({
            "files": {"data/x": {"sha256": "a" * 64}},
            "track_plan_path": "data/x",
            "sha256": "b" * 64,
        })
        self.assertEqual(len(generic), 1)
        self.assertEqual(generic[0]["digest_field"], "sha256")

    def test_23e_unsupported_and_orphan_sibling_integrity_fields_are_fatal(self):
        for value in (
            {
                "track_plan": "data/plan.json",
                "track_plan_sha256": "a" * 64,
                "track_plan_content_sha256": "b" * 64,
            },
            {
                "track_plan": "data/plan.json",
                "track_plan_sha256": "a" * 64,
                "track_plan_checksum": "b" * 64,
            },
            {"track_plan_sha256": "a" * 64},
            {
                "screen": {"exact_g3_track_plan_sha256": "a" * 64},
                "data": {"canonical_g3_track_plan": "data/plan.json"},
            },
            {"content_length": 9},
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                RuntimeError, "unsupported_or_orphan_sibling_integrity_fields"
            ):
                repair.assert_unambiguous_sibling_integrity(value)

    def test_23f_valid_prefixed_path_digest_and_size_fields_are_preserved(self):
        value = {
            "consumer_path": "scripts/consumer.py",
            "consumer_sha256": "a" * 64,
            "consumer_bytes": 17,
            "effect_size": 0.25,
        }
        repair.assert_unambiguous_sibling_integrity(value)
        claims = repair.manifest_sibling_integrity_claims({
            "files": {"data/x": {"sha256": "b" * 64}},
            **value,
        })
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["digest_field"], "consumer_sha256")
        self.assertEqual(claims[0]["size_fields"], {"consumer_bytes": 17})

    def test_24_full_closure_rejects_symlinked_manifest_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_bytes(root / "real", b"value")
            (root / "data").mkdir()
            (root / "data/link").symlink_to(root / "real")
            write_json(root / "manifest.json", make_manifest({"data/link": (b"value", None)}))
            audit = repair.audit_executor_manifest_closure(root, "manifest.json")
            self.assertFalse(audit["closure_pass"])
            self.assertTrue(audit["rows"][0]["target_symlink"])

    def test_25_single_link_policy_rejects_hardlinked_runtime_product(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_bytes(root / "product.json", b"{}\n")
            os.link(root / "product.json", root / "second-link.json")
            with self.assertRaisesRegex(RuntimeError, "unsafe_or_nonregular"):
                repair.contained_regular_file(root, "product.json", require_single_link=True)

    def test_26_required_input_concordance_includes_full_manifest_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_bytes(root / "data/required", b"required")
            write_bytes(root / "data/unrelated", b"tampered")
            write_bytes(root / "config.yaml", b"data:\n  required: data/required\n")
            manifest = make_manifest({"data/required": (b"required", None), "data/unrelated": (b"original", None)})
            write_json(root / "manifest.json", manifest)
            stage = {
                "stage": "test", "config": "config.yaml", "manifest": "manifest.json",
                "required_data_keys": ["data.required"],
            }
            result = repair.required_input_concordance(
                root, {"config.yaml": {"data": {"required": "data/required"}}}, stage
            )
            self.assertEqual(result["required_input_digest_match_count"], 1)
            self.assertFalse(result["executor_manifest_closure_pass"])
            self.assertFalse(result["manifest_config_concordant"])


class RuntimeBindingTests(unittest.TestCase):
    def test_27_runtime_binding_preflight_passes_only_with_pending_template_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            result = repair.runtime_binding_preflight(
                fixture["source"], fixture["shadow"], fixture["cfg"], fixture["configs"]
            )
            self.assertTrue(result["pass"], result)
            self.assertTrue(result["checks"]["runtime_target_absent_before_producer"])
            self.assertTrue(result["checks"]["confirmation_has_exactly_one_allowed_pending_target"])

    def test_28_preflight_rejects_premature_runtime_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            write_product(fixture)
            result = repair.runtime_binding_preflight(
                fixture["source"], fixture["shadow"], fixture["cfg"], fixture["configs"]
            )
            self.assertFalse(result["pass"])
            self.assertFalse(result["checks"]["runtime_target_absent_before_producer"])

    def test_29_preflight_rejects_confirmation_template_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            path = fixture["shadow"] / fixture["confirmation"]
            value = json.loads(path.read_text(encoding="utf-8"))
            value["files"][fixture["target"]]["role"] = "tampered"
            write_json(path, value)
            result = repair.runtime_binding_preflight(
                fixture["source"], fixture["shadow"], fixture["cfg"], fixture["configs"]
            )
            self.assertFalse(result["pass"])
            self.assertFalse(result["checks"]["shadow_confirmation_template_record_exact"])

    def test_29a_preflight_rejects_unauthorized_alternate_target_digest_field(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            for root in (fixture["source"], fixture["shadow"]):
                path = root / fixture["confirmation"]
                value = json.loads(path.read_text(encoding="utf-8"))
                value["files"][fixture["target"]]["digest"] = value["files"][
                    fixture["target"]
                ]["sha256"]
                write_json(path, value)
            confirmation_sha = repair.sha256(
                fixture["source"] / fixture["confirmation"]
            )
            for stage in fixture["cfg"]["stage_contracts"]:
                if stage["manifest"] == fixture["confirmation"]:
                    stage["manifest_sha256"] = confirmation_sha
            fixture["cfg"]["runtime_binding"]["source_manifest_sha256"][
                fixture["confirmation"]
            ] = confirmation_sha
            result = repair.runtime_binding_preflight(
                fixture["source"], fixture["shadow"], fixture["cfg"], fixture["configs"]
            )
            self.assertFalse(result["pass"])
            self.assertFalse(
                result["checks"][
                    "source_confirmation_template_content_fields_authorized_exact"
                ]
            )

    def _bind(self, fixture: dict[str, object], **overrides: object) -> dict[str, object]:
        return bind_fixture(fixture, **overrides)

    def test_30_binder_success_refreshes_both_shadow_manifests(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            product = write_product(fixture)
            receipt = self._bind(fixture)
            self.assertTrue(receipt["binding_pass"], receipt)
            for key in ("shared", "confirmation"):
                manifest = json.loads((fixture["shadow"] / fixture[key]).read_text(encoding="utf-8"))
                record = manifest["files"][fixture["target"]]
                self.assertEqual(record["sha256"], repair.sha256(product))
                self.assertEqual(record["bytes"], product.stat().st_size)
                self.assertEqual(record["role"], "phase_b_runtime_product")

    def test_31_success_receipt_has_every_declared_required_field(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            write_product(fixture)
            receipt = self._bind(fixture)
            missing = set(cfg["runtime_binding"]["receipt_schema"]["required_fields"]) - set(receipt)
            self.assertEqual(missing, set())
            self.assertEqual(len(receipt["manifest_mutations"]), 2)
            self.assertEqual(
                base64.b64decode(receipt["product_payload_b64"], validate=True),
                (fixture["shadow"] / fixture["target"]).read_bytes(),
            )

    def test_32_success_receipt_digest_is_self_verifying_for_late_gates(self):
        gate349 = load_gate("363_execute_simba_tng_shadow_translation_matrix.py", "gate349_receipt")
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            write_product(fixture)
            receipt = self._bind(fixture)
            self.assertTrue(gate349.receipt_exact(receipt, fixture["cfg"], fixture["source"]), receipt)
            with self.assertRaises(TypeError):
                gate349.receipt_exact(receipt)

    def test_33_success_preserves_source_manifest_authorities(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            frozen = {
                key: (fixture["source"] / fixture[key]).read_bytes()
                for key in ("shared", "confirmation")
            }
            write_product(fixture)
            self.assertTrue(self._bind(fixture)["binding_pass"])
            for key, original in frozen.items():
                self.assertEqual((fixture["source"] / fixture[key]).read_bytes(), original)

    def test_34_receipt_freezes_producer_to_consumer_manifest_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            before = repair.sha256(fixture["shadow"] / fixture["shared"])
            write_product(fixture)
            receipt = self._bind(fixture)
            self.assertEqual(receipt["producer_invocation_manifest_sha256"], before)
            self.assertEqual(receipt["shared_manifest_before_sha256"], before)
            self.assertEqual(
                receipt["shared_manifest_after_sha256"],
                repair.sha256(fixture["shadow"] / fixture["shared"]),
            )
            self.assertEqual(
                receipt["confirmation_manifest_after_sha256"],
                repair.sha256(fixture["shadow"] / fixture["confirmation"]),
            )

    def test_35_binder_rejects_nonzero_producer_return_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            write_product(fixture)
            receipt = self._bind(fixture, producer_return_code=2)
            self.assertFalse(receipt["binding_pass"])
            self.assertIn("producer_lifecycle_not_satisfied", receipt["hold_reason"])

    def test_36_binder_rejects_false_preproducer_absence_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            write_product(fixture)
            receipt = self._bind(fixture, product_absent_before=False)
            self.assertFalse(receipt["binding_pass"])
            self.assertFalse(receipt["preproducer_target_absent"])

    def test_37_binder_rejects_missing_product(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            receipt = self._bind(fixture)
            self.assertFalse(receipt["binding_pass"])
            self.assertIn("unsafe_or_nonregular_shadow_file", receipt["hold_reason"])

    def test_38_binder_rejects_malformed_product_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            write_bytes(fixture["shadow"] / fixture["target"], b"not json\n")
            receipt = self._bind(fixture)
            self.assertFalse(receipt["binding_pass"])
            self.assertIn("JSONDecodeError", receipt["hold_reason"])

    def test_39_binder_rejects_product_with_wrong_run_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            write_product(fixture, run_id="WRONG-RUN")
            receipt = self._bind(fixture)
            self.assertFalse(receipt["binding_pass"])
            self.assertIn("product_json_or_run_id_invalid", receipt["hold_reason"])

    def test_40_binder_rejects_symlinked_product(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            real = fixture["shadow"] / "outputs/real.json"
            write_json(real, {"schema_version": 1, "run_id": "SYNTHETIC-PRODUCER"})
            (fixture["shadow"] / fixture["target"]).symlink_to(real)
            receipt = self._bind(fixture)
            self.assertFalse(receipt["binding_pass"])
            self.assertIn("unsafe_or_nonregular_shadow_file", receipt["hold_reason"])

    def test_41_binder_rejects_hardlinked_product(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            product = write_product(fixture)
            os.link(product, fixture["shadow"] / "outputs/second-link.json")
            receipt = self._bind(fixture)
            self.assertFalse(receipt["binding_pass"])
            self.assertIn("unsafe_or_nonregular_shadow_file", receipt["hold_reason"])

    def test_42_binder_rejects_changed_source_template_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            write_product(fixture)
            source_template = fixture["source"] / fixture["confirmation"]
            value = json.loads(source_template.read_text(encoding="utf-8"))
            value["note"] = "changed"
            write_json(source_template, value)
            receipt = self._bind(fixture)
            self.assertFalse(receipt["binding_pass"])
            self.assertIn("hash_pinned_authority_changed", receipt["hold_reason"])

    def test_43_binder_rejects_shadow_template_record_schema_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            write_product(fixture)
            path = fixture["shadow"] / fixture["confirmation"]
            value = json.loads(path.read_text(encoding="utf-8"))
            value["files"][fixture["target"]]["new_field"] = "forbidden"
            write_json(path, value)
            receipt = self._bind(fixture)
            self.assertFalse(receipt["binding_pass"])
            self.assertIn("confirmation_template_record_changed", receipt["hold_reason"])

    def test_43b_binder_rejects_unrelated_confirmation_manifest_insertion(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            write_product(fixture)
            unrelated = "data/producer-inserted.bin"
            payload = b"valid but unauthorized\n"
            write_bytes(fixture["shadow"] / unrelated, payload)
            path = fixture["shadow"] / fixture["confirmation"]
            value = json.loads(path.read_text(encoding="utf-8"))
            value["files"][unrelated] = {
                "sha256": sha_bytes(payload),
                "bytes": len(payload),
            }
            write_json(path, value)
            receipt = self._bind(fixture)
            self.assertFalse(receipt["binding_pass"])
            self.assertIn("confirmation_manifest_prestate_changed", receipt["hold_reason"])

    def test_44_unrelated_manifest_record_tamper_blocks_postbind_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            write_product(fixture)
            path = fixture["shadow"] / fixture["shared"]
            value = json.loads(path.read_text(encoding="utf-8"))
            value["files"]["data/raw.bin"]["sha256"] = "0" * 64
            write_json(path, value)
            receipt = self._bind(
                fixture, producer_invocation_manifest_sha256=repair.sha256(path)
            )
            self.assertFalse(receipt["binding_pass"])
            self.assertFalse(receipt["downstream_full_manifest_closure_pass"])

    def test_45_target_tamper_after_binding_breaks_both_manifest_closures(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            product = write_product(fixture)
            self.assertTrue(self._bind(fixture)["binding_pass"])
            write_bytes(product, b'{"run_id":"tampered"}\n')
            for key in ("shared", "confirmation"):
                self.assertFalse(
                    repair.audit_executor_manifest_closure(fixture["shadow"], fixture[key])["closure_pass"]
                )

    def test_46_partial_atomic_group_failure_rolls_back_and_poisons_shadow(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_binding_fixture(Path(temporary))
            write_product(fixture)
            originals = {
                key: (fixture["shadow"] / fixture[key]).read_bytes()
                for key in ("shared", "confirmation")
            }
            real_replace = repair.os.replace
            calls = {"count": 0}

            def fail_second(source: object, destination: object) -> None:
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("injected second replacement failure")
                real_replace(source, destination)

            with mock.patch.object(repair.os, "replace", side_effect=fail_second):
                receipt = self._bind(fixture)
            self.assertFalse(receipt["binding_pass"])
            self.assertIn("injected second replacement failure", receipt["hold_reason"])
            for key, original in originals.items():
                self.assertEqual((fixture["shadow"] / fixture[key]).read_bytes(), original)
            self.assertTrue((fixture["shadow"] / ".bh_simba_shadow_poisoned").is_file())

    def test_47_run_offset_rejects_reordered_stages_before_any_execution(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        reordered = list(reversed(cfg["stage_contracts"]))
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
            RuntimeError, "four_stage_dependency_order_not_exact"
        ):
            repair.run_offset(Path(temporary), Path(temporary) / "out", cfg, 0.0, reordered)


class LiveAuthorityResolutionTests(unittest.TestCase):
    @staticmethod
    def _generator4_stage(fixture: dict[str, object]) -> dict[str, object]:
        return next(
            stage for stage in fixture["cfg"]["stage_contracts"]
            if stage["stage"] == "generator4_pooled_innovation_screen"
        )

    def test_66a_generator4_binding_proves_path_digest_source_manifest_and_executor(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            stage = self._generator4_stage(fixture)
            config = yaml.safe_load(
                (fixture["source"] / fixture["g4_config"]).read_text(encoding="utf-8")
            )
            manifest = json.loads(
                (fixture["source"] / fixture["g4"]).read_text(encoding="utf-8")
            )
            observed = repair.sha256(fixture["source"] / fixture["plan"])
            self.assertEqual(config["data"]["canonical_g3_track_plan"], fixture["plan"])
            self.assertEqual(
                config["screen"]["exact_g3_track_plan_sha256"], observed
            )
            self.assertEqual(manifest["files"][fixture["plan"]]["sha256"], observed)
            self.assertEqual(observed, fixture["historical_plan_sha256"])

            proof = repair.prove_schema_specific_config_integrity_bindings(
                fixture["source"], fixture["cfg"]
            )
            self.assertTrue(proof["binding_proof_pass"], proof)
            self.assertEqual(proof["declared_binding_count"], 1)
            self.assertEqual(proof["proven_binding_count"], 1)
            row = proof["rows"][0]
            self.assertEqual(row["config_relative_path"], stage["config"])
            self.assertEqual(row["executor_relative_path"], stage["executor"])
            self.assertEqual(row["manifest_relative_path"], stage["manifest"])
            self.assertEqual(row["relative_path"], fixture["plan"])
            self.assertEqual(
                {row["claimed_sha256"], row["manifest_sha256_claim"], row["observed_sha256"]},
                {observed},
            )
            self.assertTrue(all(row["checks"].values()), row)
            self.assertEqual(row["executor_ast_proof"]["guard_line"], 19)
            self.assertEqual(row["executor_ast_proof"]["first_plan_load_line"], 21)
            self.assertTrue(row["executor_ast_proof"]["pass"], row)

    def test_66b_generator4_binding_requires_one_unambiguous_digest_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            stage = self._generator4_stage(fixture)
            declarations = fixture["cfg"]["authority_resolution"][
                "schema_specific_config_integrity_bindings"
            ]
            duplicate = copy.deepcopy(declarations[0])
            duplicate["binding_id"] = "second_owner_forbidden"
            declarations.append(duplicate)
            with self.assertRaisesRegex(
                RuntimeError,
                "schema_specific_config_integrity_binding_duplicate_digest_owner",
            ):
                repair.bindings_for_document(fixture["cfg"], stage["config"])
            proof = repair.prove_schema_specific_config_integrity_bindings(
                fixture["source"], fixture["cfg"]
            )
            self.assertFalse(proof["binding_proof_pass"])
            self.assertIn("exactly_one_schema_specific_config_binding_required", proof["error"])

    def test_66c_generator4_binding_rejects_config_manifest_or_source_disagreement(self):
        for mutation in ("config", "manifest", "source"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                fixture = build_live_authority_fixture(Path(temporary))
                stage = self._generator4_stage(fixture)
                if mutation == "config":
                    path = fixture["source"] / fixture["g4_config"]
                    value = yaml.safe_load(path.read_text(encoding="utf-8"))
                    value["screen"]["exact_g3_track_plan_sha256"] = "f" * 64
                    write_yaml(path, value)
                    stage["config_sha256"] = repair.sha256(path)
                elif mutation == "manifest":
                    path = fixture["source"] / fixture["g4"]
                    value = json.loads(path.read_text(encoding="utf-8"))
                    value["files"][fixture["plan"]]["sha256"] = "f" * 64
                    write_json(path, value)
                    stage["manifest_sha256"] = repair.sha256(path)
                else:
                    write_bytes(
                        fixture["source"] / fixture["plan"],
                        b'{"schema_version":1,"selected_track_ids":{}}\n',
                    )

                proof = repair.prove_schema_specific_config_integrity_bindings(
                    fixture["source"], fixture["cfg"]
                )
                self.assertFalse(proof["binding_proof_pass"], proof)
                self.assertEqual(proof["error"], "")
                row = proof["rows"][0]
                self.assertFalse(row["binding_pass"])
                if mutation == "config":
                    self.assertFalse(row["checks"]["config_manifest_digest_equal"])
                    self.assertFalse(row["checks"]["config_observed_digest_equal"])
                    self.assertTrue(row["checks"]["manifest_observed_digest_equal"])
                elif mutation == "manifest":
                    self.assertFalse(row["checks"]["config_manifest_digest_equal"])
                    self.assertTrue(row["checks"]["config_observed_digest_equal"])
                    self.assertFalse(row["checks"]["manifest_observed_digest_equal"])
                else:
                    self.assertTrue(row["checks"]["config_manifest_digest_equal"])
                    self.assertFalse(row["checks"]["config_observed_digest_equal"])
                    self.assertFalse(row["checks"]["manifest_observed_digest_equal"])

    def test_66d_generator4_key_mentions_without_a_digest_guard_do_not_prove_binding(self):
        payload = b'''#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path


def load_unguarded_plan(config, repo_root):
    plan_path = Path(repo_root) / config["data"]["canonical_g3_track_plan"]
    expected_plan_sha256 = config["screen"]["exact_g3_track_plan_sha256"]
    observed_plan_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    return json.loads(plan_path.read_text(encoding="utf-8"))
'''
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            stage = self._generator4_stage(fixture)
            write_bytes(fixture["source"] / fixture["g4_executor"], payload)
            stage["executor_sha256"] = sha_bytes(payload)
            proof = repair.prove_schema_specific_config_integrity_bindings(
                fixture["source"], fixture["cfg"]
            )
            self.assertFalse(proof["binding_proof_pass"], proof)
            ast_proof = proof["rows"][0]["executor_ast_proof"]
            self.assertTrue(ast_proof["path_key_present"])
            self.assertTrue(ast_proof["digest_key_present"])
            self.assertTrue(ast_proof["repo_root_resolution_present"])
            self.assertTrue(ast_proof["sha256_operation_present"])
            self.assertFalse(ast_proof["path_digest_guard_present"])
            self.assertFalse(ast_proof["guard_before_first_plan_load"])
            self.assertFalse(ast_proof["pass"])

    def test_66e_generator4_digest_guard_must_precede_the_first_plan_load(self):
        payload = b'''#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path


def load_late_guarded_plan(config, repo_root):
    plan_path = Path(repo_root) / config["data"]["canonical_g3_track_plan"]
    expected_plan_sha256 = config["screen"]["exact_g3_track_plan_sha256"]
    observed_plan_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if observed_plan_sha256 != expected_plan_sha256:
        raise RuntimeError("canonical_g3_track_plan_digest_mismatch")
    return plan
'''
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            stage = self._generator4_stage(fixture)
            write_bytes(fixture["source"] / fixture["g4_executor"], payload)
            stage["executor_sha256"] = sha_bytes(payload)
            proof = repair.prove_schema_specific_config_integrity_bindings(
                fixture["source"], fixture["cfg"]
            )
            self.assertFalse(proof["binding_proof_pass"], proof)
            ast_proof = proof["rows"][0]["executor_ast_proof"]
            self.assertTrue(ast_proof["path_digest_guard_present"])
            self.assertGreater(ast_proof["guard_line"], ast_proof["first_plan_load_line"])
            self.assertFalse(ast_proof["guard_before_first_plan_load"])
            self.assertFalse(ast_proof["pass"])

    def test_66f_live_executor_stub_preserves_generator4_binding_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            install_live_executor_stub(fixture)
            proof = repair.prove_schema_specific_config_integrity_bindings(
                fixture["source"], fixture["cfg"]
            )
            self.assertTrue(proof["binding_proof_pass"], proof)
            ast_proof = proof["rows"][0]["executor_ast_proof"]
            self.assertTrue(ast_proof["pass"], ast_proof)
            self.assertLessEqual(
                ast_proof["guard_line"], ast_proof["first_plan_load_line"]
            )

    def test_67_live_resolution_selects_primary_and_recomputes_exact_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            receipt = repair.resolve_source_manifest_claims(fixture["source"], fixture["cfg"])
            self.assertTrue(receipt["resolution_pass"], receipt)
            self.assertTrue(receipt["known_prior_first_conflict_resolved_by_primary"])
            self.assertEqual(receipt["primary_manifest_disagreement_paths"], [fixture["consumer"]])
            self.assertEqual(receipt["source_manifest_count"], 3)
            self.assertTrue(
                repair.source_authority_resolution_exact(receipt, fixture["cfg"], fixture["source"])
            )
            self.assertFalse(
                repair.source_authority_resolution_exact(receipt, fixture["cfg"]),
                "a self-hash without live source reconstruction must fail closed",
            )

    def test_68_prepare_shadow_translates_only_shadow_manifest_claims(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            frozen = {
                relative: (fixture["source"] / relative).read_bytes()
                for relative in (
                    fixture["shared"], fixture["confirmation"], fixture["g4"],
                    fixture["g4_config"], fixture["plan"],
                )
            }
            configs, audit = prepare_live_fixture_only(fixture, -3.0)
            selected = audit["source_authority_resolution"]["selected_copy_digests"][fixture["consumer"]]
            self.assertTrue(audit["source_authority_resolution_pass"])
            self.assertTrue(audit["fixture_contract_pass"])
            self.assertEqual(audit["generic_interstage_refresh_count"], 0)
            for relative in (fixture["shared"], fixture["confirmation"], fixture["g4"]):
                shadow_manifest = json.loads((fixture["shadow"] / relative).read_text(encoding="utf-8"))
                self.assertEqual(shadow_manifest["files"][fixture["consumer"]]["sha256"], selected)
                self.assertEqual((fixture["source"] / relative).read_bytes(), frozen[relative])
            translated = [
                mutation
                for item in audit["construction_manifest_mutation_receipts"]
                for mutation in item["mutations"]
                if mutation["relative_path"] == fixture["consumer"] and mutation["kind"] == "digest"
            ]
            self.assertEqual(len(translated), 3)
            self.assertTrue(all(item["after"] == selected for item in translated))

            shadow_plan_sha256 = repair.sha256(fixture["shadow"] / fixture["plan"])
            self.assertEqual(
                configs[fixture["g4_config"]]["screen"]["exact_g3_track_plan_sha256"],
                shadow_plan_sha256,
            )
            binding_mutations = [
                mutation
                for item in audit["construction_config_mutation_receipts"]
                if item["relative_path"] == fixture["g4_config"]
                for mutation in item["mutations"]
            ]
            self.assertEqual(binding_mutations, [{
                "location": "$.screen.exact_g3_track_plan_sha256",
                "relative_path": fixture["plan"],
                "field": "exact_g3_track_plan_sha256",
                "kind": "digest",
                "before": fixture["historical_plan_sha256"],
                "after": shadow_plan_sha256,
            }])
            for relative, payload in frozen.items():
                self.assertEqual(
                    (fixture["source"] / relative).read_bytes(), payload,
                    f"source authority mutated: {relative}",
                )

    def test_69_live_binding_receipt_and_construction_audit_reconstruct_exactly(self):
        gate356 = load_gate(GATE_NAMES[4], "gate356_live_receipt")
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            _, audit, receipt = prepare_and_bind_live_fixture(fixture, 7.25)
            self.assertTrue(receipt["binding_pass"], receipt)
            self.assertTrue(
                repair.runtime_binding_receipt_exact(receipt, fixture["cfg"], fixture["source"])
            )
            self.assertTrue(
                repair.construction_audit_exact(audit, fixture["cfg"], receipt, fixture["source"])
            )
            self.assertTrue(gate356.receipt_exact(receipt, fixture["cfg"], fixture["source"]))

    def test_69a_prefixed_sibling_fields_survive_resolution_and_receipt_reconstruction(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            shared_path = fixture["source"] / fixture["shared"]
            shared = json.loads(shared_path.read_text(encoding="utf-8"))
            embedded = shared["files"][fixture["consumer"]]
            shared.update({
                "consumer_path": fixture["consumer"],
                "consumer_sha256": embedded["sha256"],
                "consumer_bytes": len(b"superseded embedded consumer\n"),
            })
            write_json(shared_path, shared)
            refresh_live_manifest_pins(fixture)

            _, audit, receipt = prepare_and_bind_live_fixture(fixture, 0.0)
            resolution = audit["source_authority_resolution"]
            sibling_rows = [
                row for row in resolution["rows"]
                if row["claim_kind"] == "manifest_sibling_integrity"
                and row["relative_path"] == fixture["consumer"]
            ]
            self.assertEqual(len(sibling_rows), 1)
            self.assertEqual(
                sibling_rows[0]["claimed_hash_fields"],
                {"consumer_sha256": embedded["sha256"]},
            )
            self.assertEqual(
                sibling_rows[0]["claimed_size_fields"],
                {"consumer_bytes": len(b"superseded embedded consumer\n")},
            )
            mutations = [
                mutation
                for item in audit["construction_manifest_mutation_receipts"]
                for mutation in item["mutations"]
                if mutation["field"] in {"consumer_sha256", "consumer_bytes"}
            ]
            self.assertEqual(
                {mutation["field"] for mutation in mutations},
                {"consumer_sha256", "consumer_bytes"},
            )
            self.assertTrue(
                repair.source_authority_resolution_exact(
                    resolution, fixture["cfg"], fixture["source"]
                )
            )
            self.assertTrue(
                repair.construction_audit_exact(
                    audit, fixture["cfg"], receipt, fixture["source"]
                )
            )

    def test_69b_generated_runtime_target_cannot_hide_unsupported_content_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            confirmation_path = fixture["source"] / fixture["confirmation"]
            confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
            confirmation["files"][fixture["target"]]["content_sha256"] = "f" * 64
            write_json(confirmation_path, confirmation)
            refresh_live_manifest_pins(fixture)
            with self.assertRaisesRegex(
                RuntimeError, "unsupported_manifest_integrity_field"
            ):
                repair.resolve_source_manifest_claims(
                    fixture["source"], fixture["cfg"]
                )

    def test_69c_nonproducer_generated_output_cannot_bypass_claim_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            shared_path = fixture["source"] / fixture["shared"]
            shared = json.loads(shared_path.read_text(encoding="utf-8"))
            screen_output = next(
                stage["fresh_output_contract"]["fixed_relative_path"]
                for stage in fixture["cfg"]["stage_contracts"]
                if stage["stage"] == "generator3_null_screen"
            )
            shared.update({
                "screen_verdict": screen_output,
                "screen_verdict_content_sha256": "f" * 64,
            })
            write_json(shared_path, shared)
            refresh_live_manifest_pins(fixture)
            with self.assertRaisesRegex(
                RuntimeError, "unsupported_or_orphan_sibling_integrity_fields"
            ):
                repair.resolve_source_manifest_claims(
                    fixture["source"], fixture["cfg"]
                )

    def test_70_self_consistent_receipt_forgery_fails_live_template_reconstruction(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            _, _, receipt = prepare_and_bind_live_fixture(fixture, 0.0)
            forged = copy.deepcopy(receipt)
            forged["template_record"]["role"] = "forged-role"
            forged["template_record_sha256"] = canonical_digest(forged["template_record"])
            payload = {
                key: value for key, value in forged.items()
                if key not in {"receipt_payload_sha256", "receipt_sha256"}
            }
            forged["receipt_payload_sha256"] = canonical_digest(payload)
            forged["receipt_sha256"] = forged["receipt_payload_sha256"]
            self.assertFalse(
                repair.runtime_binding_receipt_exact(forged, fixture["cfg"], fixture["source"])
            )

    def test_70a_arbitrary_product_digest_and_size_forgery_fails_snapshot_reconstruction(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            _, audit, receipt = prepare_and_bind_live_fixture(fixture, 0.0)
            forged = copy.deepcopy(receipt)
            forged_sha256 = "f" * 64
            forged_bytes = 777
            forged["product_sha256"] = forged_sha256
            forged["target_sha256"] = forged_sha256
            forged["product_bytes"] = forged_bytes
            forged["target_bytes"] = forged_bytes
            for field in repair.HASH_FIELDS & set(forged["refreshed_record"]):
                forged["refreshed_record"][field] = forged_sha256
            for field in repair.SIZE_FIELDS & set(forged["refreshed_record"]):
                forged["refreshed_record"][field] = forged_bytes

            shared_after = copy.deepcopy(forged["shared_manifest_before"])
            confirmation_after = copy.deepcopy(forged["confirmation_manifest_before"])
            shared_after["files"][fixture["target"]] = copy.deepcopy(forged["refreshed_record"])
            confirmation_after["files"][fixture["target"]] = copy.deepcopy(forged["refreshed_record"])
            forged["shared_manifest_after_sha256"] = sha_bytes(
                (json.dumps(shared_after, indent=2) + "\n").encode("utf-8")
            )
            forged["confirmation_manifest_after_sha256"] = sha_bytes(
                (json.dumps(confirmation_after, indent=2) + "\n").encode("utf-8")
            )
            forged["manifest_mutations"][0]["after_sha256"] = forged["shared_manifest_after_sha256"]
            forged["manifest_mutations"][1]["after_sha256"] = forged["confirmation_manifest_after_sha256"]
            payload = {
                key: value for key, value in forged.items()
                if key not in {"receipt_payload_sha256", "receipt_sha256"}
            }
            forged["receipt_payload_sha256"] = canonical_digest(payload)
            forged["receipt_sha256"] = forged["receipt_payload_sha256"]

            self.assertFalse(
                repair.runtime_binding_receipt_exact(forged, fixture["cfg"], fixture["source"])
            )
            self.assertFalse(
                repair.construction_audit_exact(
                    audit, fixture["cfg"], forged, fixture["source"]
                )
            )
            stripped = copy.deepcopy(receipt)
            stripped.pop("receipt_sha256")
            self.assertFalse(
                repair.construction_audit_exact(
                    audit, fixture["cfg"], stripped, fixture["source"]
                ),
                "a full receipt cannot evade snapshot validation by dropping one field",
            )

    def test_71_construction_audit_rejects_rehashed_mutation_forgery(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            _, audit, receipt = prepare_and_bind_live_fixture(fixture, 0.0)
            forged = copy.deepcopy(audit)
            manifest_receipt = next(
                item for item in forged["construction_manifest_mutation_receipts"]
                if item["mutations"]
            )
            manifest_receipt["mutations"][0]["after"] = "0" * 64
            manifest_receipt["mutations_sha256"] = canonical_digest(manifest_receipt["mutations"])
            self.assertFalse(
                repair.construction_audit_exact(forged, fixture["cfg"], receipt, fixture["source"])
            )

    def test_72_primary_observed_digest_mismatch_is_fatal(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            write_bytes(fixture["source"] / fixture["consumer"], b"mutated primary\n")
            receipt = repair.resolve_source_manifest_claims(fixture["source"], fixture["cfg"])
            self.assertFalse(receipt["resolution_pass"])
            self.assertIn(fixture["consumer"], receipt["observed_mismatch_paths"])
            self.assertEqual(
                receipt["path_resolutions"][fixture["consumer"]],
                "fatal_primary_observed_digest_mismatch",
            )

    def test_73_nonprimary_disagreement_is_fatal_after_complete_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            nonprimary = "records/nonprimary.bin"
            write_bytes(fixture["source"] / nonprimary, b"first authority\n")
            for relative, payload in (
                (fixture["shared"], b"first authority\n"),
                (fixture["confirmation"], b"first authority\n"),
                (fixture["g4"], b"second authority\n"),
            ):
                path = fixture["source"] / relative
                value = json.loads(path.read_text(encoding="utf-8"))
                value["files"][nonprimary] = {"sha256": sha_bytes(payload), "bytes": len(payload)}
                write_json(path, value)
            for stage in fixture["cfg"]["stage_contracts"]:
                stage["manifest_sha256"] = repair.sha256(fixture["source"] / stage["manifest"])
            fixture["cfg"]["runtime_binding"]["source_manifest_sha256"] = {
                fixture["shared"]: repair.sha256(fixture["source"] / fixture["shared"]),
                fixture["confirmation"]: repair.sha256(fixture["source"] / fixture["confirmation"]),
            }
            receipt = repair.resolve_source_manifest_claims(fixture["source"], fixture["cfg"])
            self.assertFalse(receipt["resolution_pass"])
            self.assertIn(nonprimary, receipt["unresolved_non_primary_paths"])
            self.assertEqual(receipt["unresolved_non_primary_conflict_count"], 1)
            self.assertGreater(receipt["claim_count"], 0)

    def test_74_prepare_shadow_rejects_shadow_nested_under_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            nested = fixture["source"] / "temporary-shadow"
            nested.mkdir()
            with self.assertRaisesRegex(RuntimeError, "temporary_shadow_must_be_outside_source_repository"):
                repair.prepare_shadow(fixture["source"], nested, fixture["cfg"], 0.0)

    def test_75_nonprimary_alternate_hash_conflict_is_fatal_not_repaired(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            relative = "records/static.bin"
            payload = b"one exact static authority\n"
            write_bytes(fixture["source"] / relative, payload)
            fixture["cfg"]["authority_resolution"][
                "allowed_non_primary_static_paths"
            ] = [relative]
            for index, manifest_relative in enumerate(
                (fixture["shared"], fixture["confirmation"], fixture["g4"])
            ):
                path = fixture["source"] / manifest_relative
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest["files"][relative] = {
                    "sha256": sha_bytes(payload),
                    "digest": ("e" if index == 2 else "d") * 64,
                    "bytes": len(payload),
                }
                write_json(path, manifest)
            refresh_live_manifest_pins(fixture)
            receipt = repair.resolve_source_manifest_claims(
                fixture["source"], fixture["cfg"]
            )
            self.assertFalse(receipt["resolution_pass"])
            self.assertEqual(
                receipt["path_resolutions"][relative],
                "fatal_unresolved_non_primary_digest_conflict",
            )

    def test_76_allowlisted_static_ancestor_of_synthetic_path_is_fatal(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            fixture["cfg"]["authority_resolution"][
                "allowed_non_primary_static_paths"
            ] = ["data"]
            receipt = repair.resolve_source_manifest_claims(
                fixture["source"], fixture["cfg"]
            )
            self.assertFalse(receipt["resolution_pass"])
            self.assertIn("data", receipt["authority_class_overlap_paths"])
            self.assertIn("data/candidate.parquet", receipt["authority_class_overlap_paths"])

    def test_77_package_initializers_are_source_state_censused_not_hash_pinned(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            fixture["cfg"]["exact_sources"]["scripts/__init__.py"] = sha_bytes(b"")
            with self.assertRaisesRegex(
                RuntimeError, "shadow_package_scaffold_contract_not_exact"
            ):
                repair.resolve_source_manifest_claims(
                    fixture["source"], fixture["cfg"]
                )
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            write_bytes(
                fixture["source"] / "scripts/__init__.py",
                b"nonempty package initializer\n",
            )
            receipt = repair.resolve_source_manifest_claims(
                fixture["source"], fixture["cfg"]
            )
            census = receipt["source_package_scaffold_census"]
            self.assertFalse(receipt["resolution_pass"])
            self.assertFalse(census["census_pass"])
            self.assertEqual(
                census["source_states"]["scripts/__init__.py"],
                "nonempty_regular",
            )

    def test_78_primary_executor_config_manifest_subroles_are_disjoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            stage = fixture["cfg"]["stage_contracts"][0]
            stage["config"] = stage["executor"]
            stage["config_sha256"] = stage["executor_sha256"]
            with self.assertRaisesRegex(RuntimeError, "primary_subrole_path_overlap"):
                repair.resolve_source_manifest_claims(fixture["source"], fixture["cfg"])

    def test_79_tampered_shadow_config_is_reparsed_before_concordance(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            configs, audit = prepare_live_fixture_only(fixture, 0.0)
            stage = fixture["cfg"]["stage_contracts"][0]
            tampered = copy.deepcopy(configs[stage["config"]])
            tampered["data"]["candidate_parquet"] = "../../outside"
            write_yaml(fixture["shadow"] / stage["config"], tampered)
            result = repair.required_input_concordance(
                fixture["shadow"],
                configs,
                stage,
                expected_config_sha256=next(
                    item["after_sha256"]
                    for item in audit["construction_config_mutation_receipts"]
                    if item["relative_path"] == stage["config"]
                ),
                expected_executor_sha256=stage["executor_sha256"],
            )
            self.assertFalse(result["manifest_config_concordant"])
            self.assertFalse(result["config_snapshot_exact"])

    def test_80_executor_substitution_holds_before_process_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            configs, audit = prepare_live_fixture_only(fixture, 0.0)
            stage = fixture["cfg"]["stage_contracts"][0]
            write_bytes(
                fixture["shadow"] / stage["executor"],
                b"#!/usr/bin/env python3\nraise SystemExit(0)\n",
            )
            manifest_digests = {
                item["relative_path"]: item["after_sha256"]
                for item in audit["construction_manifest_mutation_receipts"]
            }
            config_digest = next(
                item["after_sha256"]
                for item in audit["construction_config_mutation_receipts"]
                if item["relative_path"] == stage["config"]
            )
            row, _ = repair.execute_stage(
                fixture["source"], fixture["shadow"], fixture["cfg"], configs,
                stage, 0.0, manifest_digests, config_digest,
            )
            self.assertFalse(row["executor_invoked"])
            self.assertEqual(row["return_code"], 125)
            self.assertFalse(row["preinvoke_primary_snapshots_exact"])
            self.assertFalse(row["stage_lifecycle_pass"])

    def test_81_lingering_executor_process_group_is_killed_and_held(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary))
            configs, audit = prepare_live_fixture_only(fixture, 0.0)
            stage = fixture["cfg"]["stage_contracts"][0]
            manifest_digests = {
                item["relative_path"]: item["after_sha256"]
                for item in audit["construction_manifest_mutation_receipts"]
            }
            config_digest = next(
                item["after_sha256"]
                for item in audit["construction_config_mutation_receipts"]
                if item["relative_path"] == stage["config"]
            )
            process = mock.Mock()
            process.pid = 4242
            process.returncode = 0
            process.communicate.return_value = ("", "")
            with mock.patch.object(
                repair.subprocess, "Popen", return_value=process
            ), mock.patch.object(repair.os, "killpg") as killpg:
                row, _ = repair.execute_stage(
                    fixture["source"], fixture["shadow"], fixture["cfg"], configs,
                    stage, 0.0, manifest_digests, config_digest,
                )
            self.assertTrue(row["executor_invoked"])
            self.assertEqual(row["return_code"], 126)
            self.assertFalse(row["stage_lifecycle_pass"])
            self.assertIn("lingering_process_group", row["detail"])
            self.assertEqual(
                killpg.call_args_list,
                [mock.call(4242, 0), mock.call(4242, repair.signal.SIGKILL)],
            )


class FixtureAndSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_48_split_contract_accepts_only_train_validation_test_400_each(self):
        configs = [
            {"screen": {"split_order": ["train", "validation", "test"], "complete_tracks_per_split": 400}},
            {"screen": {"split_order": ["train", "validation", "test"], "complete_tracks_per_split": 400}},
        ]
        splits, count = repair._split_contract(configs, 1200)
        self.assertEqual(splits, ["train", "validation", "test"])
        self.assertEqual(count, 400)

    def test_49_split_contract_rejects_old_800_track_fixture(self):
        configs = [{"screen": {"split_order": ["train", "validation", "test"], "complete_tracks_per_split": 400}}]
        with self.assertRaisesRegex(RuntimeError, "synthetic_split_contract_not_exact"):
            repair._split_contract(configs, 800)

    def test_50_json_track_plan_has_selected_track_ids_and_exact_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "track_plan.json"
            repair.write_track_plan(path, 1200, 48, ["train", "validation", "test"], 400)
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("selected_track_ids", value)
            self.assertEqual(set(value["selected_track_ids"]), {"train", "validation", "test"})
            self.assertTrue(all(len(ids) == 400 for ids in value["selected_track_ids"].values()))
            self.assertEqual(len(value["tracks"]), 1200)

    def test_51_fixture_contract_requires_configured_memory_tau_columns(self):
        synthetic = self.cfg["synthetic_contract"]
        self.assertEqual(synthetic["memory_tau_source_config_key"], "selection.tau_track_fractions")
        self.assertEqual(synthetic["memory_tau_column_template"], "memory_tau_{tau:g}")
        self.assertTrue(synthetic["require_every_configured_memory_tau_column"])
        text = (SCRIPTS / "bh_simba_shadow_exact_binding_source_state_lifecycle_recovery_v1_4.py").read_text(encoding="utf-8")
        self.assertIn('data[tau_column_template.format(tau=tau)] = values', text)

    def test_52_fixture_contract_requires_selected_track_ids(self):
        synthetic = self.cfg["synthetic_contract"]
        self.assertEqual(synthetic["track_plan_required_key"], "selected_track_ids")
        self.assertEqual(synthetic["track_plan_each_required_split_exact_count"], 400)

    def test_53_observable_selection_reads_only_the_declared_stage_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = root / "declared.json"
            unrelated = root / "unrelated.json"
            write_json(expected, {"fractional_gain": 0.25, "status": "pass", "path": "ignored"})
            write_json(unrelated, {"fractional_gain": 999.0, "status": "hold"})
            selected = repair.select_observables(expected)
            self.assertEqual(selected, {"fractional_gain": 0.25, "status": "pass"})
            self.assertNotIn(999.0, selected.values())


class LateGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        cls.gate349 = load_gate(GATE_NAMES[4], "gate349_tests")
        cls.gate350 = load_gate(GATE_NAMES[5], "gate350_tests")
        cls.gate351 = load_gate(GATE_NAMES[6], "gate351_tests")

    def _matrix_rows(self, cfg: dict[str, object] | None = None) -> list[dict[str, object]]:
        cfg = self.cfg if cfg is None else cfg
        rows: list[dict[str, object]] = []
        for offset in cfg["synthetic_contract"]["offsets"]:
            for stage in cfg["stage_contracts"]:
                producer = stage["stage"] == "generator3_phase_b"
                required_count = len(stage["required_data_keys"])
                rows.append({
                    "offset": offset,
                    "stage": stage["stage"],
                    "executor_sha256": stage["executor_sha256"],
                    "observed_executor_sha256": stage["executor_sha256"],
                    "authority_config_sha256": stage["config_sha256"],
                    "shadow_config_sha256": "d" * 64,
                    "preinvoke_config_sha256": "d" * 64,
                    "preinvoke_primary_snapshots_exact": True,
                    "return_code": 0,
                    "executor_invoked": True,
                    "stage_executed": True,
                    "expected_output_fresh_exact": True,
                    "stage_verdict_fresh": True,
                    "stage_verdict_run_id_exact": True,
                    "required_verdict_keys_pass": True,
                    "required_truthy_keys_pass": True,
                    "observable_count": 1,
                    "classified_interface_hold": False,
                    "shadow_config_integrity_mutations_before_stage": 0,
                    "shadow_manifest_integrity_mutations_before_stage": 0,
                    "command_contract_exact": True,
                    "repo_root_is_explicit_shadow": True,
                    "config_path_shadow_relative": True,
                    "manifest_path_shadow_relative": True,
                    "required_input_count": required_count,
                    "required_input_existing_count": required_count,
                    "required_input_manifest_record_count": required_count,
                    "required_input_digest_match_count": required_count,
                    "manifest_config_concordant": True,
                    "executor_manifest_closure_pass": True,
                    "all_shadow_manifests_closure_pass": True,
                    "manifest_byte_invariance_pass": True,
                    "manifest_file_record_count": 2,
                    "manifest_file_existing_count": 2,
                    "manifest_file_digest_match_count": 2,
                    "post_stage_binding_required": producer,
                    "post_stage_binding_pass": True,
                    "stage_lifecycle_pass": True,
                    "numeric_and_categorical_invariant": True,
                    "stage_verdict_sha256": "a" * 64,
                    "invocation_manifest_sha256": "b" * 64,
                    "command_sha256": "c" * 64,
                    "stdout_sha256": "e" * 64,
                    "stderr_sha256": "f" * 64,
                    "runtime_binding_receipt_sha256": canonical_digest({"offset": float(offset)}) if producer else "",
                })
        return rows

    def _write_matrix_csv(self, output: Path, rows: list[dict[str, object]]) -> None:
        path = output / self.cfg["outputs"]["matrix_results"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def _matrix_with_observable_evidence(
        self,
        rows: list[dict[str, object]],
        cfg: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Build exact persisted verdict bytes from which invariance is recomputable."""
        cfg = self.cfg if cfg is None else cfg
        evidence: list[dict[str, object]] = []
        for row in rows:
            verdict = {
                "schema_version": 1,
                "effect_size": 0.25,
                "effect_size_gate_pass": True,
                "status": "pass",
            }
            payload = (
                json.dumps(verdict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                + "\n"
            ).encode("utf-8")
            observables = repair.select_observables_value(verdict)
            digest = sha_bytes(payload)
            row["stage_verdict_sha256"] = digest
            row["observable_count"] = len(observables)
            evidence.append({
                "offset": float(row["offset"]),
                "stage": row["stage"],
                "stage_verdict_sha256": digest,
                "stage_verdict_bytes": len(payload),
                "stage_verdict_payload_b64": base64.b64encode(payload).decode("ascii"),
                "observables": observables,
                "observables_sha256": canonical_digest(observables),
            })
        return {
            "stage_invariance": {
                stage["stage"]: True for stage in cfg["stage_contracts"]
            },
            "observable_evidence": evidence,
            "observable_evidence_sha256": canonical_digest(evidence),
        }

    def _live_replay_matrix(self, fixture: dict[str, object]) -> dict[str, object]:
        evidence: list[dict[str, object]] = []
        for offset in fixture["cfg"]["synthetic_contract"]["offsets"]:
            for stage in fixture["cfg"]["stage_contracts"]:
                config = yaml.safe_load(
                    (fixture["source"] / stage["config"]).read_text(encoding="utf-8")
                )
                value = {
                    "schema_version": 1,
                    "run_id": config["run_id"],
                    "effect_size": 0.25,
                    "effect_size_gate_pass": True,
                    "status": "pass",
                }
                evidence.append({
                    "offset": float(offset),
                    "stage": stage["stage"],
                    "observables": repair.select_observables_value(value),
                })
        return {
            "observable_evidence": evidence,
            "observable_evidence_sha256": canonical_digest(evidence),
            "stage_invariance": {
                stage["stage"]: True for stage in fixture["cfg"]["stage_contracts"]
            },
            "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved": True,
            "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected": False,
        }

    def _matrix_audits_exact(
        self,
        matrix: dict[str, object],
        cfg: dict[str, object],
        output: Path,
        source_root: Path,
    ) -> bool:
        with mock.patch(
            "pandas.DataFrame.to_parquet", new=deterministic_parquet_stub
        ):
            return self.gate350.matrix_audits_exact(
                matrix, cfg, output, source_root
            )

    def _attach_stage_output_evidence(
        self,
        audit: dict[str, object],
        rows: list[dict[str, object]],
        cfg: dict[str, object],
        fixture: dict[str, object],
        receipt: dict[str, object],
    ) -> list[dict[str, object]]:
        """Build the byte-level execution receipt used by late-gate fixtures."""
        by_stage = {row["stage"]: row for row in rows}
        items: list[dict[str, object]] = []
        matrix_items: list[dict[str, object]] = []
        for stage in cfg["stage_contracts"]:
            row = by_stage[stage["stage"]]
            source_config = yaml.safe_load(
                (fixture["source"] / stage["config"]).read_text(encoding="utf-8")
            )
            if stage["stage"] == cfg["runtime_binding"]["producer_stage"]:
                encoded = receipt["product_payload_b64"]
                payload = base64.b64decode(encoded, validate=True)
            else:
                value = {
                    "schema_version": 1,
                    "run_id": source_config["run_id"],
                    "effect_size": 0.25,
                    "effect_size_gate_pass": True,
                    "status": "pass",
                }
                payload = (
                    json.dumps(
                        value, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False,
                    ) + "\n"
                ).encode("utf-8")
                encoded = base64.b64encode(payload).decode("ascii")
            value = repair.strict_json_bytes(payload, stage["stage"])
            observables = repair.select_observables_value(value)
            digest = sha_bytes(payload)
            row["stage_verdict_sha256"] = digest
            row["observable_count"] = len(observables)
            row["observed_executor_sha256"] = stage["executor_sha256"]
            row["preinvoke_config_sha256"] = row["shadow_config_sha256"]
            row["preinvoke_primary_snapshots_exact"] = True
            row["required_truthy_keys_pass"] = True
            row["expected_output_relative_path"] = stage[
                "fresh_output_contract"
            ]["fixed_relative_path"]
            normalized_command = repair.normalized_stage_command(stage)
            item = {
                "schema_version": 1,
                "offset": float(row["offset"]),
                "stage": stage["stage"],
                "executor_sha256": stage["executor_sha256"],
                "observed_executor_sha256": stage["executor_sha256"],
                "authority_config_sha256": stage["config_sha256"],
                "shadow_config_sha256": row["shadow_config_sha256"],
                "preinvoke_config_sha256": row["shadow_config_sha256"],
                "preinvoke_primary_snapshots_exact": True,
                "invocation_manifest_sha256": row["invocation_manifest_sha256"],
                "expected_output_relative_path": row["expected_output_relative_path"],
                "stage_verdict_sha256": digest,
                "stage_verdict_bytes": len(payload),
                "stage_verdict_payload_b64": encoded,
                "observables": observables,
                "observables_sha256": canonical_digest(observables),
                "executor_invoked": True,
                "return_code": 0,
                "stage_output_fresh_exact": True,
                "stage_verdict_run_id_exact": True,
                "required_verdict_keys_pass": True,
                "required_truthy_keys_pass": True,
                "stage_lifecycle_pass": True,
                "normalized_command": normalized_command,
                "normalized_command_sha256": canonical_digest(normalized_command),
            }
            item["evidence_sha256"] = canonical_digest(item)
            items.append(item)
            matrix_items.append({
                "offset": item["offset"],
                "stage": item["stage"],
                "stage_verdict_sha256": digest,
                "stage_verdict_bytes": len(payload),
                "stage_verdict_payload_b64": encoded,
                "observables": observables,
                "observables_sha256": canonical_digest(observables),
            })
        audit["offset"] = float(rows[0]["offset"])
        audit["stage_output_evidence"] = items
        audit["stage_output_evidence_sha256"] = canonical_digest(items)
        return matrix_items

    def test_54_matrix_row_success_requires_existing_count_and_full_closure(self):
        row = self._matrix_rows()[0]
        row["observable_count"] = 1
        row.update({
            "command_contract_exact": True,
            "repo_root_is_explicit_shadow": True,
            "config_path_shadow_relative": True,
            "manifest_path_shadow_relative": True,
            "all_shadow_manifests_closure_pass": True,
            "manifest_byte_invariance_pass": True,
            "required_input_count": 1,
            "required_input_existing_count": 1,
            "required_input_manifest_record_count": 1,
            "required_input_digest_match_count": 1,
            "classified_interface_hold": False,
            "shadow_config_integrity_mutations_before_stage": 0,
            "shadow_manifest_integrity_mutations_before_stage": 0,
        })
        self.assertTrue(self.gate349.row_success(row))
        row["manifest_file_existing_count"] = 1
        self.assertFalse(self.gate349.row_success(row))

    def test_55_current_matrix_csv_recomputes_exact_twenty_lifecycles(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            rows = self._matrix_rows()
            matrix = self._matrix_with_observable_evidence(rows)
            self._write_matrix_csv(output, rows)
            self.assertTrue(self.gate350.matrix_csv_exact(output, self.cfg, matrix))

    def test_56_forged_nineteen_row_matrix_csv_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            rows = self._matrix_rows()[:-1]
            matrix = self._matrix_with_observable_evidence(rows)
            self._write_matrix_csv(output, rows)
            self.assertFalse(self.gate350.matrix_csv_exact(output, self.cfg, matrix))

    def test_57_reordered_or_duplicate_matrix_pair_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            rows = self._matrix_rows()
            rows[1]["stage"] = rows[0]["stage"]
            matrix = self._matrix_with_observable_evidence(rows)
            self._write_matrix_csv(output, rows)
            self.assertFalse(self.gate350.matrix_csv_exact(output, self.cfg, matrix))

    def test_57a_observable_evidence_is_recomputed_not_summary_trusted(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            rows = self._matrix_rows()
            matrix = self._matrix_with_observable_evidence(rows)
            self._write_matrix_csv(output, rows)
            forged = copy.deepcopy(matrix)
            forged_observables = forged["observable_evidence"][0]["observables"]
            forged_observables["effect_size"] = 999.0
            forged["observable_evidence"][0]["observables_sha256"] = canonical_digest(
                forged_observables
            )
            forged["observable_evidence_sha256"] = canonical_digest(
                forged["observable_evidence"]
            )
            self.assertFalse(self.gate350.matrix_csv_exact(output, self.cfg, forged))

    def test_58_five_audits_must_bind_exactly_one_receipt_per_offset(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            audits: list[dict[str, object]] = []
            fixtures: list[dict[str, object]] = []
            for index, offset in enumerate(self.cfg["synthetic_contract"]["offsets"]):
                fixture = build_live_authority_fixture(output / f"fixture_{index}")
                fixtures.append(fixture)
                _, audit, receipt = prepare_and_bind_live_fixture(fixture, float(offset))
                self.assertTrue(audit["runtime_binding_receipts_pass"], audit)
                self.assertTrue(
                    repair.construction_audit_exact(
                        audit, fixture["cfg"], receipt, fixture["source"]
                    )
                )
                audits.append(audit)
            synthetic_cfg = fixtures[0]["cfg"]
            rows = self._matrix_rows(synthetic_cfg)
            matrix_observable_evidence: list[dict[str, object]] = []
            for offset, audit, fixture in zip(self.cfg["synthetic_contract"]["offsets"], audits, fixtures):
                receipt = audit["runtime_product_binding_receipts"][0]
                offset_rows = {
                    row["stage"]: row for row in rows if float(row["offset"]) == float(offset)
                }
                construction_manifests = {
                    item["relative_path"]: item
                    for item in audit["construction_manifest_mutation_receipts"]
                }
                construction_configs = {
                    item["relative_path"]: item
                    for item in audit["construction_config_mutation_receipts"]
                }
                closures = {
                    item["manifest_relative_path"]: item
                    for item in audit["final_manifest_closures"]
                }
                for stage in synthetic_cfg["stage_contracts"]:
                    row = offset_rows[stage["stage"]]
                    row["shadow_config_sha256"] = construction_configs[stage["config"]]["after_sha256"]
                    closure = closures[stage["manifest"]]
                    row["manifest_file_record_count"] = closure["manifest_file_record_count"]
                    row["manifest_file_existing_count"] = closure["manifest_file_existing_count"]
                    row["manifest_file_digest_match_count"] = closure["manifest_file_digest_match_count"]
                phase = offset_rows["generator3_phase_b"]
                phase["runtime_binding_receipt_sha256"] = receipt["receipt_sha256"]
                phase["stage_verdict_sha256"] = receipt["target_sha256"]
                phase["invocation_manifest_sha256"] = receipt["producer_invocation_manifest_sha256"]
                offset_rows["generator3_null_screen"]["invocation_manifest_sha256"] = receipt["shared_manifest_after_sha256"]
                offset_rows["generator3_null_confirmation_2000"]["invocation_manifest_sha256"] = receipt["confirmation_manifest_after_sha256"]
                offset_rows["generator4_pooled_innovation_screen"]["invocation_manifest_sha256"] = (
                    construction_manifests[fixture["g4"]]["after_sha256"]
                )
                ordered_offset_rows = [
                    offset_rows[stage["stage"]]
                    for stage in synthetic_cfg["stage_contracts"]
                ]
                matrix_observable_evidence.extend(
                    self._attach_stage_output_evidence(
                        audit, ordered_offset_rows, synthetic_cfg, fixture, receipt
                    )
                )
            self._write_matrix_csv(output, rows)
            matrix = {
                "shadow_audits": audits,
                "observable_evidence": matrix_observable_evidence,
                "observable_evidence_sha256": canonical_digest(
                    matrix_observable_evidence
                ),
            }
            source_root = fixtures[0]["source"]
            self.assertTrue(
                self._matrix_audits_exact(matrix, synthetic_cfg, output, source_root)
            )
            spliced_rows = copy.deepcopy(rows)
            next(row for row in spliced_rows if row["stage"] == "generator3_phase_b")["stage_verdict_sha256"] = "0" * 64
            self._write_matrix_csv(output, spliced_rows)
            self.assertFalse(
                self._matrix_audits_exact(matrix, synthetic_cfg, output, source_root)
            )
            self._write_matrix_csv(output, rows)
            forged = copy.deepcopy(matrix)
            prestate_receipt = forged["shadow_audits"][0]["runtime_product_binding_receipts"][0]
            prestate_receipt["confirmation_manifest_expected_before_sha256"] = "0" * 64
            prestate_receipt["confirmation_manifest_before_sha256"] = "0" * 64
            prestate_receipt["manifest_mutations"][1]["before_sha256"] = "0" * 64
            payload = {
                key: value for key, value in prestate_receipt.items()
                if key not in {"receipt_sha256", "receipt_payload_sha256"}
            }
            prestate_receipt["receipt_payload_sha256"] = canonical_digest(payload)
            prestate_receipt["receipt_sha256"] = prestate_receipt["receipt_payload_sha256"]
            self.assertFalse(
                self._matrix_audits_exact(forged, synthetic_cfg, output, source_root)
            )
            incomplete = {"shadow_audits": audits[:-1]}
            self.assertFalse(
                self._matrix_audits_exact(
                    incomplete, synthetic_cfg, output, source_root
                )
            )

    def test_58a_missing_parquet_engine_fails_construction_verification_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary) / "fixture")
            _, audit, receipt = prepare_and_bind_live_fixture(fixture, 0.0)
            with (
                mock.patch.dict(repair._EXPECTED_SYNTHETIC_CACHE, {}, clear=True),
                mock.patch(
                    "pandas.DataFrame.to_parquet",
                    side_effect=ImportError("no parquet engine in test environment"),
                ),
            ):
                self.assertFalse(
                    repair.construction_audit_exact(
                        audit, fixture["cfg"], receipt, fixture["source"]
                    )
                )

    def test_58b_live_replay_is_never_called_before_all_nonreplay_prechecks(self):
        cfg = copy.deepcopy(self.cfg)
        matrix = {
            "observable_evidence_sha256": "a" * 64,
        }
        prechecks = {
            "current_acceptance_exact": True,
            "current_matrix_artifact_exact": False,
        }
        with mock.patch.object(
            self.gate350,
            "execute_live_replay",
            side_effect=AssertionError("replay must not be called"),
        ) as replay_call:
            passed, receipt, audit_payload = self.gate350.execute_live_replay_only_after_prechecks(
                ROOT, cfg, matrix, "b" * 64, prechecks
            )
        self.assertFalse(passed)
        replay_call.assert_not_called()
        self.assertEqual(receipt["attempted_stage_invocations"], 0)
        self.assertEqual(receipt["successful_stage_invocations"], 0)
        self.assertFalse(receipt["live_replay_pass"])
        self.assertEqual(audit_payload, {"rows": [], "metrics": [], "audits": []})
        self.assertEqual(
            receipt["receipt_sha256"],
            canonical_digest({
                key: value for key, value in receipt.items()
                if key != "receipt_sha256"
            }),
        )

    def test_58ba_v13_custody_hold_emits_no_replay_or_sensitivity_claim(self):
        cfg = copy.deepcopy(self.cfg)
        matrix = {
            "observable_evidence": [{"forged": "must_not_propagate"}],
            "stage_invariance": {"forged": True},
            "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved": True,
            "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected": False,
        }
        prechecks = {
            "failed_v1_3_R3_custody_exact_before_live_replay": False,
        }
        with mock.patch.object(
            self.gate350,
            "execute_live_replay",
            side_effect=AssertionError("custody hold must prevent replay"),
        ) as replay_call:
            passed, receipt, audit_payload = (
                self.gate350.execute_live_replay_only_after_prechecks(
                    ROOT, cfg, matrix, "b" * 64, prechecks
                )
            )
        self.assertFalse(passed)
        replay_call.assert_not_called()
        self.assertEqual(receipt["attempted_stage_invocations"], 0)
        self.assertEqual(receipt["successful_stage_invocations"], 0)
        self.assertEqual(receipt["stage_invariance"], {})
        self.assertFalse(
            receipt["selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved"]
        )
        self.assertFalse(
            receipt["selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected"]
        )
        self.assertEqual(audit_payload, {"rows": [], "metrics": [], "audits": []})
        self.assertIn(
            "failed_v1_3_R3_custody_exact_before_live_replay",
            receipt["hold_reason"],
        )

    def test_58c_live_replay_executes_exactly_twenty_real_popen_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary) / "fixture")
            enable_live_replay_multibinder_fixture(fixture)
            install_live_executor_stub(fixture)
            matrix = self._live_replay_matrix(fixture)
            real_popen = repair.subprocess.Popen
            with (
                mock.patch(
                    "pandas.DataFrame.to_parquet", new=deterministic_parquet_stub
                ),
                mock.patch.object(
                    repair.subprocess, "Popen", wraps=real_popen
                ) as popen_call,
            ):
                passed, receipt, audit_payload = self.gate350.execute_live_replay(
                    fixture["source"], fixture["cfg"], matrix, "b" * 64
                )
            self.assertTrue(passed, receipt)
            self.assertEqual(popen_call.call_count, 20)
            self.assertEqual(receipt["attempted_stage_invocations"], 20)
            self.assertEqual(receipt["successful_stage_invocations"], 20)
            adjudication = {
                "matrix_verdict_sha256": "b" * 64,
                "live_replay_pass": True,
                "live_replay_receipt": receipt,
                "live_replay_audit": audit_payload,
                "live_replay_receipt_sha256": receipt["receipt_sha256"],
                "live_replay_audit_sha256": receipt["replay_audit_sha256"],
                "live_replay_attestation_limit": receipt["attestation_limit"],
            }
            self.assertTrue(
                self.gate350.live_replay_receipt_exact(
                    adjudication, fixture["cfg"], matrix, fixture["source"]
                )
            )

            forged = copy.deepcopy(adjudication)
            forged["live_replay_audit"]["rows"][0]["executor_invoked"] = False
            forged["live_replay_receipt"]["row_receipt_sha256s"][0] = canonical_digest(
                forged["live_replay_audit"]["rows"][0]
            )
            forged_audit_sha = canonical_digest(forged["live_replay_audit"])
            forged["live_replay_receipt"]["replay_audit_sha256"] = forged_audit_sha
            forged["live_replay_audit_sha256"] = forged_audit_sha
            forged_receipt_payload = {
                key: value
                for key, value in forged["live_replay_receipt"].items()
                if key != "receipt_sha256"
            }
            forged["live_replay_receipt"]["receipt_sha256"] = canonical_digest(
                forged_receipt_payload
            )
            forged["live_replay_receipt_sha256"] = forged[
                "live_replay_receipt"
            ]["receipt_sha256"]
            self.assertFalse(
                self.gate350.live_replay_receipt_exact(
                    forged, fixture["cfg"], matrix, fixture["source"]
                ),
                "jointly rehashing a fabricated replay row must not pass",
            )
            replay_module = (
                fixture["source"]
                / fixture["cfg"]["adjudication_live_replay"]["run_offset_module"]
            )
            replay_module.write_bytes(replay_module.read_bytes() + b"\n# drift\n")
            self.assertFalse(
                self.gate350.live_replay_receipt_exact(
                    adjudication, fixture["cfg"], matrix, fixture["source"]
                ),
                "a current replay-implementation digest drift must not pass",
            )

    def test_58d_popen_exception_forces_live_replay_hold(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = build_live_authority_fixture(Path(temporary) / "fixture")
            enable_live_replay_multibinder_fixture(fixture)
            install_live_executor_stub(fixture)
            matrix = self._live_replay_matrix(fixture)
            with (
                mock.patch(
                    "pandas.DataFrame.to_parquet", new=deterministic_parquet_stub
                ),
                mock.patch.object(
                    repair.subprocess,
                    "Popen",
                    side_effect=OSError("forced executor launch failure"),
                ) as popen_call,
            ):
                passed, receipt, _ = self.gate350.execute_live_replay(
                    fixture["source"], fixture["cfg"], matrix, "b" * 64
                )
            self.assertFalse(passed)
            self.assertEqual(popen_call.call_count, 1)
            self.assertEqual(receipt["successful_stage_invocations"], 0)
            self.assertFalse(receipt["live_replay_pass"])

    def test_59_forged_receipt_payload_digest_is_rejected(self):
        receipt = {"binding_pass": True, "receipt_sha256": "0" * 64}
        with self.assertRaises(TypeError):
            self.gate349.receipt_exact(receipt)
        self.assertFalse(self.gate349.receipt_exact(receipt, self.cfg, ROOT))

    def test_60_matrix_and_adjudication_require_xor_sensitivity_outcome(self):
        for name in (GATE_NAMES[4], GATE_NAMES[5], GATE_NAMES[6]):
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertTrue("resolved ^ rejected" in text or "resolved ^ rejected" in text.replace("(", ""), name)

    def test_61_only_final_gate_can_write_entry_128(self):
        writers = [
            path.name for path in SCRIPT_PATHS
            if "install_text_exclusive(\n            entry_path" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(writers, [GATE_NAMES[6]])
        self.assertTrue(self.cfg["outputs"]["protocol_entry"].endswith(".tex"))

    def test_62_final_gate_writes_no_entry_for_incomplete_route(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg = copy.deepcopy(self.cfg)
            cfg["outputs"] = {
                **copy.deepcopy(self.cfg["outputs"]),
                "directory": "out",
                "design_verdict": "design.json",
                "preflight_verdict": "preflight.json",
                "smoke_verdict": "smoke.json",
                "acceptance_verdict": "acceptance.json",
                "matrix_results": "matrix.csv",
                "matrix_verdict": "matrix.json",
                "adjudication_verdict": "adjudication.json",
                "final_route": "final.json",
                "protocol_entry": "paper/entry.tex",
            }
            write_json(root / "config.json", cfg)
            for name in ("design", "preflight", "smoke", "acceptance", "matrix", "adjudication"):
                write_json(root / "out" / f"{name}.json", {"schema_version": 2, "run_id": "forged"})
            marker = root / "out/.runtime_manifest_recovery_current_20000101T000000Z_1.marker"
            marker.write_text(json.dumps({
                "schema_version": 1,
                "run_token": "20000101T000000Z_1",
                "owner_nonce": "a" * 64,
            }, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            argv = [
                "351", "--config", "config.json",
                "--design-verdict", "out/design.json",
                "--preflight-verdict", "out/preflight.json",
                "--smoke-verdict", "out/smoke.json",
                "--acceptance-verdict", "out/acceptance.json",
                "--matrix-verdict", "out/matrix.json",
                "--adjudication-verdict", "out/adjudication.json",
                "--transaction-owner-marker", marker.relative_to(root).as_posix(),
                "--repo-root", str(root),
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                self.gate351, "utc_now", return_value="2000-01-01T00:00:00Z"
            ), mock.patch("builtins.print"):
                return_code = self.gate351.main()
            self.assertEqual(return_code, 2)
            self.assertFalse((root / "paper/entry.tex").exists())
            final = json.loads((root / "out/final.json").read_text(encoding="utf-8"))
            self.assertFalse(final["final_route_pass"])
            self.assertFalse(final["logbook_entry_written"])

    def test_63_final_files_and_provenance_include_protocol_entry_on_success_path(self):
        text = (SCRIPTS / GATE_NAMES[6]).read_text(encoding="utf-8")
        self.assertIn("final_files[protocol_relative] = entry_record", text)
        self.assertIn('"protocol_entry": {', text)
        self.assertIn('"written_only_after_complete_route": passed', text)

    def test_63b_protocol_entry_rejects_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            outside = Path(temporary) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "paper").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "unsafe_protocol_entry_target"):
                self.gate351.atomic_text(root / "paper/entry.tex", "entry\n", root=root)
            self.assertFalse((outside / "entry.tex").exists())

    def test_63ba_protocol_entry_exclusive_install_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.mkdir(exist_ok=True)
            entry = root / "paper/entry.tex"
            transaction_id = "a" * 64
            self.gate351.install_text_exclusive(
                entry,
                "first\n",
                root=root,
                transaction_id=transaction_id,
            )
            self.assertEqual(entry.read_bytes(), b"first\n")
            self.assertEqual(entry.stat().st_nlink, 1)
            self.assertFalse(
                self.gate351.transaction_staging_path(entry, transaction_id).exists()
            )
            with self.assertRaises(FileExistsError):
                self.gate351.install_text_exclusive(
                    entry,
                    "second\n",
                    root=root,
                    transaction_id="b" * 64,
                )
            self.assertEqual(entry.read_bytes(), b"first\n")

    def test_63bb_pending_transaction_recovers_only_exact_owned_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "out"
            output.mkdir()
            entry = root / "paper/entry.tex"
            entry.parent.mkdir()
            final_route = output / "final.json"
            marker = output / ".runtime_manifest_recovery_current_20000101T000000Z_7.marker"
            marker_payload = json.dumps({
                "schema_version": 1,
                "run_token": "20000101T000000Z_7",
                "owner_nonce": "c" * 64,
            }, sort_keys=True, separators=(",", ":")) + "\n"
            marker.write_text(marker_payload, encoding="utf-8")
            transaction_id = "d" * 64
            run_id = "FINAL-RUN"
            entry_payload = (
                f"% entry_install_transaction_id: {transaction_id}\n"
                f"% final_route_run_id: {run_id}\n"
                "Protocol Entry 128\n"
            ).encode("utf-8")
            entry.write_bytes(entry_payload)
            transaction = {
                "transaction_id": transaction_id,
                "final_route_path": final_route.relative_to(root).as_posix(),
                "final_route_run_id": run_id,
                "final_route_staging_path": self.gate351.transaction_staging_path(
                    final_route, transaction_id
                ).relative_to(root).as_posix(),
                "protocol_entry_path": entry.relative_to(root).as_posix(),
                "protocol_entry_sha256": sha_bytes(entry_payload),
                "protocol_entry_bytes": len(entry_payload),
                "protocol_entry_staging_path": self.gate351.transaction_staging_path(
                    entry, transaction_id
                ).relative_to(root).as_posix(),
                "owner_marker_path": marker.relative_to(root).as_posix(),
                "owner_marker_sha256": sha_bytes(marker_payload.encode("utf-8")),
                "owner_marker_bytes": len(marker_payload.encode("utf-8")),
                "matrix_verdict_sha256": "e" * 64,
                "adjudication_verdict_sha256": "f" * 64,
            }
            write_json(final_route, {
                "run_id": run_id,
                "final_route_pass": False,
                "logbook_entry_written": False,
                "entry_install_transaction_state": "entry_pending",
                "entry_install_transaction": transaction,
                "disposition": "entry_install_precommit_pending",
                "checks": {"entry_128_written_atomically_and_exact": False},
                "files": {},
                "final_files": {},
            })
            recovered = self.gate351.pending_transaction_recovery_paths(
                root, output, entry, final_route, run_id
            )
            self.assertEqual(set(recovered), {marker, entry})
            entry.write_bytes(entry_payload + b"tampered\n")
            with self.assertRaisesRegex(RuntimeError, "snapshot_mismatch"):
                self.gate351.pending_transaction_recovery_paths(
                    root, output, entry, final_route, run_id
                )

    def test_63bba_pending_journal_without_entry_recovers_live_marker_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "out"
            output.mkdir()
            entry = root / "paper/entry.tex"
            entry.parent.mkdir()
            final_route = output / "final.json"
            marker = output / ".runtime_manifest_recovery_current_20000101T000000Z_8.marker"
            marker_payload = json.dumps({
                "schema_version": 1,
                "run_token": "20000101T000000Z_8",
                "owner_nonce": "a" * 64,
            }, sort_keys=True, separators=(",", ":")) + "\n"
            marker.write_text(marker_payload, encoding="utf-8")
            transaction_id = "b" * 64
            run_id = "FINAL-RUN-NO-ENTRY"
            entry_payload = (
                f"% entry_install_transaction_id: {transaction_id}\n"
                f"% final_route_run_id: {run_id}\n"
                "Protocol Entry 128\n"
            ).encode("utf-8")
            transaction = {
                "transaction_id": transaction_id,
                "final_route_path": final_route.relative_to(root).as_posix(),
                "final_route_run_id": run_id,
                "final_route_staging_path": self.gate351.transaction_staging_path(
                    final_route, transaction_id
                ).relative_to(root).as_posix(),
                "protocol_entry_path": entry.relative_to(root).as_posix(),
                "protocol_entry_sha256": sha_bytes(entry_payload),
                "protocol_entry_bytes": len(entry_payload),
                "protocol_entry_staging_path": self.gate351.transaction_staging_path(
                    entry, transaction_id
                ).relative_to(root).as_posix(),
                "owner_marker_path": marker.relative_to(root).as_posix(),
                "owner_marker_sha256": sha_bytes(marker_payload.encode("utf-8")),
                "owner_marker_bytes": len(marker_payload.encode("utf-8")),
                "matrix_verdict_sha256": "c" * 64,
                "adjudication_verdict_sha256": "d" * 64,
            }
            write_json(final_route, {
                "run_id": run_id,
                "final_route_pass": False,
                "logbook_entry_written": False,
                "entry_install_transaction_state": "entry_pending",
                "entry_install_transaction": transaction,
                "disposition": "entry_install_precommit_pending",
                "checks": {"entry_128_written_atomically_and_exact": False},
                "files": {},
                "final_files": {},
            })

            self.assertEqual(
                self.gate351.pending_transaction_recovery_paths(
                    root, output, entry, final_route, run_id
                ),
                [marker],
            )
            marker.unlink()
            self.assertEqual(
                self.gate351.pending_transaction_recovery_paths(
                    root, output, entry, final_route, run_id
                ),
                [],
            )
            self.assertTrue(final_route.is_file())

    def test_63bbb_committed_transaction_marker_is_ephemeral_after_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "out"
            output.mkdir()
            entry = root / "paper/entry.tex"
            entry.parent.mkdir()
            final_route = output / "final.json"
            marker = output / ".runtime_manifest_recovery_current_20000101T000000Z_9.marker"
            marker_payload = json.dumps({
                "schema_version": 1,
                "run_token": "20000101T000000Z_9",
                "owner_nonce": "e" * 64,
            }, sort_keys=True, separators=(",", ":")) + "\n"
            transaction_id = "f" * 64
            run_id = "FINAL-RUN-COMMITTED"
            entry_payload = (
                f"% entry_install_transaction_id: {transaction_id}\n"
                f"% final_route_run_id: {run_id}\n"
                "Protocol Entry 128\n"
            ).encode("utf-8")
            entry.write_bytes(entry_payload)
            entry_record = {"sha256": sha_bytes(entry_payload)}
            transaction = {
                "transaction_id": transaction_id,
                "final_route_path": final_route.relative_to(root).as_posix(),
                "final_route_run_id": run_id,
                "final_route_staging_path": self.gate351.transaction_staging_path(
                    final_route, transaction_id
                ).relative_to(root).as_posix(),
                "protocol_entry_path": entry.relative_to(root).as_posix(),
                "protocol_entry_sha256": entry_record["sha256"],
                "protocol_entry_bytes": len(entry_payload),
                "protocol_entry_staging_path": self.gate351.transaction_staging_path(
                    entry, transaction_id
                ).relative_to(root).as_posix(),
                "owner_marker_path": marker.relative_to(root).as_posix(),
                "owner_marker_sha256": sha_bytes(marker_payload.encode("utf-8")),
                "owner_marker_bytes": len(marker_payload.encode("utf-8")),
                "matrix_verdict_sha256": "1" * 64,
                "adjudication_verdict_sha256": "2" * 64,
            }
            write_json(final_route, {
                "run_id": run_id,
                "final_route_pass": True,
                "logbook_entry_written": True,
                "entry_install_transaction_state": "committed",
                "entry_install_transaction": transaction,
                "disposition": "process_pass_scientific_hold",
                "checks": {"entry_128_written_atomically_and_exact": True},
                "files": {entry.relative_to(root).as_posix(): entry_record},
                "final_files": {entry.relative_to(root).as_posix(): entry_record},
            })

            committed = self.gate351.validate_entry_transaction(
                root,
                output,
                entry,
                final_route,
                run_id,
                allowed_states={"committed"},
                require_entry=True,
            )
            self.assertEqual(committed["state"], "committed")
            self.assertIsNone(committed["owner_marker_payload"])
            with self.assertRaises((OSError, RuntimeError)):
                self.gate351.validate_entry_transaction(
                    root,
                    output,
                    entry,
                    final_route,
                    run_id,
                    allowed_states={"committed"},
                    require_entry=True,
                    expected_owner_marker=marker,
                )

    def test_63bbc_runner_normalizes_pending_links_before_ordered_recovery(self):
        runner = RUNNER.read_text(encoding="utf-8")
        normalize = runner.index(
            'if path.name.endswith(".pending"):'
        )
        unlink = runner.index("path.unlink()", normalize)
        revalidate = runner.index(
            "recovered_transaction_paths = recovery.pending_transaction_recovery_paths(",
            unlink,
        )
        entry_branch = runner.index(
            "if entry in recovered_transaction_paths:", revalidate
        )
        entry_append = runner.index("candidates.append(entry)", entry_branch)
        final_append = runner.index("candidates.append(final_route)", entry_append)
        self.assertLess(normalize, unlink)
        self.assertLess(unlink, revalidate)
        self.assertLess(revalidate, entry_append)
        self.assertLess(entry_append, final_append)

    def test_63bc_runner_serializes_mutations_and_cleanup_uses_exact_owner(self):
        runner = RUNNER.read_text(encoding="utf-8")
        lock = runner.index("flock -n 8")
        quarantine = runner.index("stale-artifact quarantine")
        unlock = runner.index("flock -u 8")
        held_cleanup = runner.index("bh_simba_v14_entry_cleanup")
        marker_cleanup = runner.index("bh_simba_v14_marker_cleanup")
        self.assertLess(lock, quarantine)
        self.assertLess(quarantine, held_cleanup)
        self.assertLess(held_cleanup, marker_cleanup)
        self.assertLess(marker_cleanup, unlock)
        self.assertIn("validate_entry_transaction(", runner[held_cleanup:unlock])
        self.assertIn("expected_owner_marker=marker", runner[held_cleanup:unlock])
        self.assertIn(
            "pending_transaction_recovery_paths(", runner[marker_cleanup:unlock]
        )
        self.assertIn("entry_install_transaction_state\") == \"committed", runner)
        self.assertIn("actual_executor_invoked_rc0_lifecycle_pass_count", runner)
        self.assertNotIn("st_mtime_ns < marker.stat().st_mtime_ns", runner)

    def test_63c_protocol_entry_rejects_every_custody_collision_class(self):
        entry = "paper/entry.tex"
        record = {"sha256": "a" * 64}
        self.assertFalse(self.gate351.protocol_entry_collision_free(entry, {entry: record}, {}, set()))
        self.assertFalse(self.gate351.protocol_entry_collision_free(entry, {}, {entry: record}, set()))
        self.assertFalse(self.gate351.protocol_entry_collision_free(entry, {}, {}, {entry}))
        self.assertTrue(self.gate351.protocol_entry_collision_free(entry, {}, {}, set()))
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("protocol_entry in current_paths", runner)
        self.assertIn("protocol_entry in protected_protocol_targets", runner)
        self.assertIn('final_file_record == {"sha256": entry_sha256}', runner)


class ReleaseFieldAuthorityTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, dict[str, object]]:
        directory = root / "outputs/protocol/release_field"
        evidence = directory / "evidence_209.csv"
        write_bytes(evidence, b"field,status\nMdot_bondi,exact\n")
        verdict = directory / "verdict_209.json"
        write_json(verdict, {
            "run_id": "DYNAMIC-RUN-209-AUTHORITY",
            "exact_expected_bondi_storage_field_resolved": True,
            "expected_bondi_physical_semantics_resolved": False,
            "artifacts": {evidence.name: {"sha256": repair.sha256(evidence)}},
        })
        spec: dict[str, object] = {
            "path": verdict.relative_to(root).as_posix(),
            "sha256": repair.sha256(verdict),
            "run_id": "DYNAMIC-RUN-209-AUTHORITY",
            "exact_expected_bondi_storage_field_resolved": True,
            "expected_bondi_physical_semantics_resolved": False,
            "files": {
                evidence.relative_to(root).as_posix(): {"sha256": repair.sha256(evidence)}
            },
        }
        return verdict, evidence, spec

    def test_64_release_field_authority_normalizes_and_freezes_current_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            verdict, evidence, spec = self._fixture(root)
            authority = common.release_field_authority(root, spec)
            self.assertIsNotNone(authority)
            self.assertEqual(authority["path"], verdict.relative_to(root).as_posix())
            self.assertEqual(authority["sha256"], repair.sha256(verdict))
            self.assertEqual(authority["run_id"], "DYNAMIC-RUN-209-AUTHORITY")
            self.assertEqual(authority["exact_expected_bondi_storage_field_resolved"], True)
            self.assertEqual(authority["expected_bondi_physical_semantics_resolved"], False)
            self.assertEqual(authority["files"], {
                evidence.relative_to(root).as_posix(): {"sha256": repair.sha256(evidence)},
            })

    def test_65_release_field_authority_rejects_artifact_or_flag_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            verdict, evidence, spec = self._fixture(root)
            write_bytes(evidence, b"mutated\n")
            self.assertIsNone(common.release_field_authority(root, spec))
            verdict, _, spec = self._fixture(root)
            value = json.loads(verdict.read_text(encoding="utf-8"))
            value["expected_bondi_physical_semantics_resolved"] = True
            write_json(verdict, value)
            forged_spec = copy.deepcopy(spec)
            forged_spec["sha256"] = repair.sha256(verdict)
            self.assertIsNone(common.release_field_authority(root, forged_spec))

    def test_66_release_field_authority_rejects_symlinked_verdict(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            verdict, _, spec = self._fixture(root)
            link = verdict.with_name("linked_verdict_209.json")
            link.symlink_to(verdict.name)
            linked_spec = copy.deepcopy(spec)
            linked_spec["path"] = link.relative_to(root).as_posix()
            self.assertIsNone(common.release_field_authority(root, linked_spec))

    def test_67_release_field_authority_rejects_unpinned_self_hashed_fake(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            verdict, _, _ = self._fixture(root)
            self.assertIsNone(
                common.release_field_authority(root, verdict.relative_to(root).as_posix())
            )

    def test_68_release_field_authority_rejects_rehashed_fake_against_frozen_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            verdict, evidence, frozen_spec = self._fixture(root)
            fake_evidence = b"field,status\nMdot_bondi,fabricated\n"
            write_bytes(evidence, fake_evidence)
            fake = json.loads(verdict.read_text(encoding="utf-8"))
            fake["run_id"] = "ARBITRARY-SELF-HASHED-FAKE"
            fake["artifacts"][evidence.name]["sha256"] = repair.sha256(evidence)
            write_json(verdict, fake)
            self.assertIsNone(common.release_field_authority(root, frozen_spec))

    def test_69_release_field_authority_requires_exact_only_evidence_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            verdict, evidence, spec = self._fixture(root)
            extra = root / "records/extra.json"
            write_bytes(extra, b"{}\n")
            value = json.loads(verdict.read_text(encoding="utf-8"))
            value["files"] = {
                extra.relative_to(root).as_posix(): {"sha256": repair.sha256(extra)}
            }
            write_json(verdict, value)
            changed = copy.deepcopy(spec)
            changed["sha256"] = repair.sha256(verdict)
            self.assertIsNone(common.release_field_authority(root, changed))


if __name__ == "__main__":
    unittest.main()
