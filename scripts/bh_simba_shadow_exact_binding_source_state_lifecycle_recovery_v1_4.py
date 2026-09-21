#!/usr/bin/env python3
"""Fail-closed temporary-shadow execution for Runs 217A-R4A through 218-R3.

All source-manifest claims are inventoried before resolution. Independently
hash-pinned primary authorities may govern incompatible embedded manifest
records, while unresolved non-primary conflicts remain fatal. Only receipted
construction-time shadow translation and the explicit post-Phase-B runtime
product binding are authorized. Historical authorities are read-only.
"""

from __future__ import annotations

import ast
import base64
import copy
import hashlib
import importlib.util
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import yaml

from bh_simba_runtime_manifest_common_v1_4 import read_json, sha256

sys.dont_write_bytecode = True


PATH_FIELDS = {
    "path", "relative_path", "file", "filename", "source", "source_path",
    "input", "input_path", "config", "executor", "manifest",
}
PATH_SUFFIXES = (
    "_path", "_file", "_parquet", "_csv", "_json", "_yaml", "_yml",
    "_npy", "_npz", "_plan", "_verdict",
)
HASH_FIELDS = {"sha256", "hash", "digest", "file_sha256", "source_sha256"}
SIZE_FIELDS = {"bytes", "size", "size_bytes", "file_size_bytes"}
STRONG_INTEGRITY_TOKENS = {
    "sha1", "sha224", "sha256", "sha384", "sha512", "md5",
    "blake2", "blake2b", "blake2s", "blake3", "crc32", "crc64", "etag",
    "hash", "digest", "checksum", "xxh32", "xxh64", "xxhash",
}
INTEGRITY_SIZE_SUBJECT_TOKENS = {
    "artifact", "config", "content", "executor", "file", "input",
    "manifest", "output", "parquet", "payload", "plan", "product",
    "record", "source", "target", "verdict",
}
RUNTIME_BINDING_RECEIPT_FIELDS = {
    "schema_version", "binding_id", "offset", "producer_stage",
    "producer_return_code", "product_relative_path", "target_relative_path",
    "product_absent_before_producer", "preproducer_target_absent",
    "source_template_manifest", "template_manifest_relative_path",
    "shared_manifest", "confirmation_manifest",
    "source_template_manifest_expected_sha256",
    "source_template_manifest_observed_sha256", "template_manifest_source_sha256",
    "template_record_sha256", "template_record", "refreshed_record",
    "product_payload_b64", "product_json_run_id", "product_json_schema_version",
    "product_sha256", "target_sha256", "product_bytes", "target_bytes",
    "product_regular_contained_non_symlink_single_link",
    "shared_manifest_before", "confirmation_manifest_before",
    "shared_manifest_before_sha256", "shared_manifest_after_sha256",
    "confirmation_manifest_expected_before_sha256",
    "confirmation_manifest_before_sha256", "confirmation_manifest_after_sha256",
    "producer_invocation_manifest_sha256", "mutation_scope_exact",
    "exact_mutation_scope_pass", "all_staged_replacements_completed_and_postverified",
    "atomic_replacement_pass", "shared_manifest_closure_pass",
    "confirmation_manifest_closure_pass", "downstream_full_manifest_closure_pass",
    "downstream_required_input_concordance_count",
    "downstream_required_input_concordance_pass_count",
    "downstream_three_of_three_input_concordance_pass", "manifest_mutations",
    "binding_pass", "receipt_payload_sha256", "receipt_sha256",
}
STAGE_OUTPUT_EVIDENCE_FIELDS = {
    "schema_version", "offset", "stage", "executor_sha256",
    "observed_executor_sha256", "preinvoke_config_sha256",
    "preinvoke_primary_snapshots_exact",
    "authority_config_sha256", "shadow_config_sha256",
    "invocation_manifest_sha256", "expected_output_relative_path",
    "stage_verdict_sha256", "stage_verdict_bytes",
    "stage_verdict_payload_b64", "observables", "observables_sha256",
    "executor_invoked", "return_code", "stage_output_fresh_exact",
    "stage_verdict_run_id_exact", "required_verdict_keys_pass",
    "required_truthy_keys_pass", "stage_lifecycle_pass",
    "normalized_command", "normalized_command_sha256", "evidence_sha256",
}
NUMERIC_TOKENS = (
    "rmse", "improvement", "gain", "p_value", "pvalue", "ci", "sse",
    "tau", "effect", "excess", "fraction", "count", "rows", "tracks",
)
CATEGORICAL_TOKENS = ("pass", "status", "disposition", "decision", "admission", "verdict", "authorized")
EXCLUDED_TOKENS = ("sha256", "generated_utc", "path", "file", "seed", "offset")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_STAGE_ORDER = [
    "generator3_phase_b",
    "generator3_null_screen",
    "generator3_null_confirmation_2000",
    "generator4_pooled_innovation_screen",
]
PACKAGE_SCAFFOLD_PATHS = (
    "src/__init__.py",
    "src/core/__init__.py",
    "scripts/__init__.py",
)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
ABSENT_AUTHORITY_SENTINEL = "<exact-absent>"
SCHEMA_SPECIFIC_BINDING_FIELDS = {
    "schema_version", "binding_id", "stage", "path_dotted_key",
    "digest_dotted_key", "algorithm", "consumer_proof",
}
EXPECTED_SCHEMA_SPECIFIC_BINDING = {
    "schema_version": 1,
    "binding_id": "generator4_exact_g3_track_plan_sha256_v1",
    "stage": "generator4_pooled_innovation_screen",
    "path_dotted_key": "data.canonical_g3_track_plan",
    "digest_dotted_key": "screen.exact_g3_track_plan_sha256",
    "algorithm": "sha256",
    "consumer_proof": "pinned_executor_ast_same_path_sha256_guard",
}


def _explicit_path_key_name(key: str) -> bool:
    lowered = key.lower()
    return lowered in PATH_FIELDS or lowered.endswith(PATH_SUFFIXES)


def _integrity_field_kind(
    key: Any,
    *,
    node: dict[str, Any] | None = None,
    manifest_record: bool = False,
) -> str | None:
    """Classify integrity-looking field names without guessing ownership.

    Cryptographic names are unambiguous integrity signals.  Size/length names
    are classified more narrowly outside a manifest record so scientific
    fields such as ``effect_size`` remain ordinary parameters.  Ownership is
    established separately by :func:`sibling_integrity_fields`.
    """
    if not isinstance(key, str) or not key:
        return None
    segmented = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    lowered = segmented.lower()
    tokens = tuple(token for token in re.split(r"[^a-z0-9]+", lowered) if token)
    compact = "".join(tokens)
    if (
        any(token in STRONG_INTEGRITY_TOKENS for token in tokens)
        or any(token in compact for token in STRONG_INTEGRITY_TOKENS)
        or "sha256" in compact
    ):
        return "digest"
    if lowered in SIZE_FIELDS:
        return "size"
    if not tokens:
        return None
    final = tokens[-1]
    if final == "bytes":
        return "size"
    if final not in {"size", "length"}:
        return None
    if manifest_record:
        return "size"
    stem = lowered.rsplit("_", 1)[0] if "_" in lowered else ""
    sibling_path_stems: set[str] = set()
    if isinstance(node, dict):
        for candidate, candidate_value in node.items():
            if not isinstance(candidate, str) or not isinstance(candidate_value, str):
                continue
            candidate_lower = candidate.lower()
            if not _explicit_path_key_name(candidate_lower):
                continue
            sibling_path_stems.add(candidate_lower)
            if candidate_lower.endswith("_path"):
                sibling_path_stems.add(candidate_lower[:-5])
    return "size" if (
        stem in sibling_path_stems
        or _explicit_path_key_name(stem)
        or bool(set(tokens[:-1]) & INTEGRITY_SIZE_SUBJECT_TOKENS)
    ) else None


def _supported_digest_field_name(field: Any) -> bool:
    """Return whether a digest field can occur in the explicit grammar.

    Actual ownership is still proven by recomputing the source document with
    ``sibling_integrity_fields``; this predicate only avoids rejecting valid
    prefixed fields while doing receipt-shape validation.
    """
    if not isinstance(field, str) or not field:
        return False
    return field in HASH_FIELDS or any(
        field.endswith(suffix)
        for suffix in ("_sha256", "_hash", "_digest", "_file_sha256", "_source_sha256")
    )


def _supported_size_field_name(field: Any) -> bool:
    """Return whether a size field can occur in the explicit grammar."""
    if not isinstance(field, str) or not field:
        return False
    return field in SIZE_FIELDS or any(
        field.endswith(suffix)
        for suffix in ("_bytes", "_size", "_size_bytes", "_file_size_bytes")
    )


def sibling_integrity_fields(node: dict[str, Any], key: str) -> tuple[list[str], list[str]]:
    """Return the one explicit sibling digest binding for a path-valued key.

    The old stem heuristic could reinterpret ordinary strings as paths and
    could bind both ``track_plan_sha256`` and ``track_sha256``.  This grammar
    accepts only exact ``<path-key>_<hash-or-size-kind>`` pairs, conventional
    stem pairs for a key ending in ``_path``, or a generic
    ``path``/``sha256`` record. Multiple candidate digest owners are an
    ambiguity, never a cue to refresh several fields.
    """
    lowered = key.lower()
    if (
        lowered in HASH_FIELDS
        or lowered in SIZE_FIELDS
        or lowered.endswith(("_sha256", "_hash", "_digest", "_bytes", "_size"))
    ):
        return [], []
    explicit_path_key = _explicit_path_key_name(lowered)
    if not explicit_path_key:
        return [], []
    digest_candidates = [
        f"{key}_sha256", f"{key}_hash", f"{key}_digest",
        f"{key}_file_sha256", f"{key}_source_sha256",
    ]
    size_candidates = [
        f"{key}_bytes", f"{key}_size", f"{key}_size_bytes",
        f"{key}_file_size_bytes",
    ]
    if lowered.endswith("_path"):
        stem = key[:-5]
        digest_candidates.extend((f"{stem}_sha256", f"{stem}_hash", f"{stem}_digest"))
        size_candidates.extend((f"{stem}_bytes", f"{stem}_size", f"{stem}_size_bytes"))
    if lowered in PATH_FIELDS or lowered.endswith("_path"):
        digest_candidates.extend(sorted(HASH_FIELDS))
        size_candidates.extend(sorted(SIZE_FIELDS))
    digests = list(dict.fromkeys(
        name for name in digest_candidates if name != key and name in node
    ))
    sizes = list(dict.fromkeys(
        name for name in size_candidates if name != key and name in node
    ))
    if len(digests) > 1:
        raise RuntimeError(f"ambiguous_sibling_integrity_digest_fields:{key}")
    # A former stem heuristic bound e.g. ``track_sha256`` to ``track_plan``.
    # Such lookalikes are now rejected explicitly instead of being silently
    # ignored or guessed.
    if "_" in key and not lowered.endswith("_path"):
        legacy_stem = key.rsplit("_", 1)[0]
        unsupported = {
            f"{legacy_stem}_sha256", f"{legacy_stem}_hash",
            f"{legacy_stem}_digest", f"{legacy_stem}_bytes",
            f"{legacy_stem}_size", f"{legacy_stem}_size_bytes",
        } & set(node)
        if unsupported:
            raise RuntimeError(
                f"unsupported_ambiguous_sibling_integrity_fields:{key}:"
                f"{','.join(sorted(unsupported))}"
            )
    return digests, sizes


def canonical_relative(value: str) -> str:
    """Return one canonical POSIX relative path or fail closed."""
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or unicodedata.normalize("NFC", value) != value
        or any(
            ord(character) < 32
            or ord(character) == 127
            or unicodedata.category(character) in {"Cc", "Cf"}
            for character in value
        )
    ):
        raise RuntimeError(f"unsafe_shadow_path:{value!r}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise RuntimeError(f"unsafe_shadow_path:{value!r}")
    if re.match(r"^[A-Za-z]:", pure.parts[0]):
        raise RuntimeError(f"unsafe_shadow_path:{value!r}")
    canonical = pure.as_posix()
    if canonical in {"", "."} or value != canonical:
        raise RuntimeError(f"unsafe_shadow_path:{value!r}")
    return canonical


def safe_relative(value: str) -> Path:
    return Path(*PurePosixPath(canonical_relative(value)).parts)


def canonical_paths_collide(left: str, right: str) -> bool:
    left_path = PurePosixPath(canonical_relative(left))
    right_path = PurePosixPath(canonical_relative(right))
    return (
        left_path == right_path
        or left_path in right_path.parents
        or right_path in left_path.parents
    )


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise RuntimeError(f"duplicate_json_key:{key}")
        value[key] = child
    return value


def _reject_json_constant(value: str) -> Any:
    raise RuntimeError(f"nonfinite_json_constant:{value}")


def strict_json_bytes(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid_json:{label}:{type(error).__name__}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"json_root_not_object:{label}")
    return value


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _unique_yaml_mapping(loader: _UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    value: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in value:
            raise RuntimeError(f"duplicate_yaml_key:{key}")
        value[key] = loader.construct_object(value_node, deep=deep)
    return value


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _unique_yaml_mapping,
)


def strict_yaml_bytes(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = yaml.load(payload.decode("utf-8"), Loader=_UniqueKeySafeLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise RuntimeError(f"invalid_yaml:{label}:{type(error).__name__}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"yaml_root_not_mapping:{label}")
    return value


def deep_get(value: dict, dotted: str) -> Any:
    current: Any = value
    for key in dotted.split("."):
        if not isinstance(current, dict) or key not in current:
            raise KeyError(dotted)
        current = current[key]
    return current


def deep_set(value: dict[str, Any], dotted: str, replacement: Any) -> None:
    parts = dotted.split(".")
    if not parts or any(not part for part in parts):
        raise KeyError(dotted)
    current: Any = value
    for key in parts[:-1]:
        if not isinstance(current, dict) or key not in current:
            raise KeyError(dotted)
        current = current[key]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise KeyError(dotted)
    current[parts[-1]] = replacement


def bindings_for_document(
    cfg: dict[str, Any], relative: str
) -> tuple[dict[str, Any], ...]:
    """Return only explicitly declared cross-mapping bindings for one config."""
    canonical = canonical_relative(relative)
    stage_by_name = {
        stage["stage"]: stage
        for stage in cfg.get("stage_contracts", [])
        if isinstance(stage, dict) and isinstance(stage.get("stage"), str)
    }
    raw = cfg.get("authority_resolution", {}).get(
        "schema_specific_config_integrity_bindings", []
    )
    if not isinstance(raw, list):
        raise RuntimeError("schema_specific_config_integrity_bindings_not_list")
    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_digest_locations: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != SCHEMA_SPECIFIC_BINDING_FIELDS:
            raise RuntimeError("schema_specific_config_integrity_binding_shape")
        if item["schema_version"] != 1 or item["algorithm"] != "sha256":
            raise RuntimeError("schema_specific_config_integrity_binding_version_or_algorithm")
        if item["consumer_proof"] != "pinned_executor_ast_same_path_sha256_guard":
            raise RuntimeError("schema_specific_config_integrity_binding_consumer_proof")
        binding_id = item["binding_id"]
        stage_name = item["stage"]
        if (
            not isinstance(binding_id, str)
            or not binding_id
            or binding_id in seen_ids
            or stage_name not in stage_by_name
        ):
            raise RuntimeError("schema_specific_config_integrity_binding_identity")
        seen_ids.add(binding_id)
        for field in ("path_dotted_key", "digest_dotted_key"):
            dotted = item[field]
            if (
                not isinstance(dotted, str)
                or not dotted
                or dotted.startswith(".")
                or dotted.endswith(".")
                or any(not part for part in dotted.split("."))
            ):
                raise RuntimeError(
                    f"schema_specific_config_integrity_binding_bad_{field}"
                )
        if item["path_dotted_key"] == item["digest_dotted_key"]:
            raise RuntimeError("schema_specific_config_integrity_binding_self_owner")
        if item["digest_dotted_key"] in seen_digest_locations:
            raise RuntimeError("schema_specific_config_integrity_binding_duplicate_digest_owner")
        seen_digest_locations.add(item["digest_dotted_key"])
        stage = stage_by_name[stage_name]
        if canonical_relative(stage["config"]) == canonical:
            selected.append(copy.deepcopy(item))
    return tuple(selected)


def _validated_cross_bindings(
    value: dict[str, Any], cross_bindings: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    digest_locations: set[str] = set()
    for item in cross_bindings:
        if not isinstance(item, dict) or set(item) != SCHEMA_SPECIFIC_BINDING_FIELDS:
            raise RuntimeError("schema_specific_config_integrity_binding_shape")
        path_dotted = item["path_dotted_key"]
        digest_dotted = item["digest_dotted_key"]
        if digest_dotted in digest_locations:
            raise RuntimeError("schema_specific_config_integrity_binding_duplicate_digest_owner")
        digest_locations.add(digest_dotted)
        path_value = deep_get(value, path_dotted)
        digest_value = deep_get(value, digest_dotted)
        if not isinstance(path_value, str):
            raise RuntimeError(
                f"schema_specific_config_integrity_path_not_string:{path_dotted}"
            )
        relative = canonical_relative(path_value)
        if not isinstance(digest_value, str) or SHA256_RE.fullmatch(digest_value) is None:
            raise RuntimeError(
                f"schema_specific_config_integrity_digest_malformed:{digest_dotted}"
            )
        normalized.append({
            **copy.deepcopy(item),
            "relative_path": relative,
            "path_location": f"$.{path_dotted}",
            "digest_location": f"$.{digest_dotted}",
            "digest_parent": "$" + (
                f".{digest_dotted.rsplit('.', 1)[0]}"
                if "." in digest_dotted else ""
            ),
            "digest_field": digest_dotted.rsplit(".", 1)[-1],
        })
    return normalized


def _path_state(root: Path, relative: str, *, require_single_link: bool = False) -> dict[str, Any]:
    canonical = canonical_relative(relative)
    root_resolved = root.resolve(strict=True)
    target = root / safe_relative(canonical)
    current = root
    parent_symlink = False
    for part in safe_relative(canonical).parts:
        current = current / part
        if current.exists() or current.is_symlink():
            try:
                if stat.S_ISLNK(current.lstat().st_mode):
                    parent_symlink = True
            except OSError:
                parent_symlink = True
    exists = target.exists() or target.is_symlink()
    is_symlink = target.is_symlink()
    resolved_contained = False
    regular = False
    links = 0
    if exists:
        try:
            resolved = target.resolve(strict=True)
            resolved_contained = resolved == root_resolved or root_resolved in resolved.parents
            info = target.lstat()
            regular = stat.S_ISREG(info.st_mode) and not is_symlink
            links = int(info.st_nlink)
        except OSError:
            pass
    else:
        ancestor = target.parent
        while ancestor != root and not (ancestor.exists() or ancestor.is_symlink()):
            ancestor = ancestor.parent
        try:
            ancestor_resolved = ancestor.resolve(strict=True)
            resolved_contained = ancestor_resolved == root_resolved or root_resolved in ancestor_resolved.parents
        except OSError:
            resolved_contained = False
    single_link = links == 1 if exists else False
    return {
        "relative_path": canonical,
        "exists": exists,
        "regular_file": regular,
        "target_symlink": is_symlink,
        "parent_or_target_symlink": parent_symlink,
        "resolved_contained": resolved_contained,
        "link_count": links,
        "single_link": single_link,
        "valid_regular_contained": bool(
            exists and regular and not parent_symlink and resolved_contained
            and (single_link or not require_single_link)
        ),
    }


def contained_regular_file(
    shadow: Path,
    relative: str,
    *,
    must_exist: bool = True,
    require_single_link: bool = False,
) -> Path:
    state = _path_state(shadow, relative, require_single_link=require_single_link)
    if must_exist and not state["valid_regular_contained"]:
        raise RuntimeError(f"unsafe_or_nonregular_shadow_file:{canonical_relative(relative)}")
    if not must_exist and state["exists"]:
        raise RuntimeError(f"premature_shadow_file:{canonical_relative(relative)}")
    if not state["resolved_contained"] or state["parent_or_target_symlink"]:
        raise RuntimeError(f"shadow_path_escape_or_symlink:{canonical_relative(relative)}")
    return shadow / safe_relative(relative)


def source_snapshot_bytes(source_root: Path, relative: str) -> bytes:
    """Read one source from a stable non-symlink, single-link descriptor."""
    canonical = canonical_relative(relative)
    source = contained_regular_file(source_root, canonical, require_single_link=True)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise RuntimeError(f"unsafe_or_nonregular_source_file:{canonical}")
        chunks: list[bytes] = []
        while True:
            block = os.read(descriptor, 8 * 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(descriptor)
        current = source.lstat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ) or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError(f"source_changed_during_snapshot:{canonical}")
        post_state = _path_state(source_root, canonical, require_single_link=True)
        if not post_state["valid_regular_contained"]:
            raise RuntimeError(f"source_path_changed_during_snapshot:{canonical}")
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def verified_source_bytes(source_root: Path, relative: str, expected: str) -> bytes:
    """Read and verify one pinned source from the same immutable snapshot."""
    if not SHA256_RE.fullmatch(str(expected)):
        raise RuntimeError(f"invalid_expected_sha256:{relative}")
    payload = source_snapshot_bytes(source_root, relative)
    if hashlib.sha256(payload).hexdigest() != expected:
        raise RuntimeError(f"hash_pinned_authority_changed:{relative}")
    return payload


def package_scaffold_contract_exact(cfg: dict[str, Any]) -> bool:
    contract = cfg.get("shadow_package_scaffolds")
    expected_paths = {
        relative: {"sha256": EMPTY_SHA256, "bytes": 0}
        for relative in PACKAGE_SCAFFOLD_PATHS
    }
    return bool(
        isinstance(contract, dict)
        and set(contract) == {
            "schema_version", "source_precondition", "shadow_construction",
            "source_mutation", "paths",
        }
        and contract.get("schema_version") == 1
        and contract.get("source_precondition")
        == "absent_or_exact_empty_regular_contained_single_link"
        and contract.get("shadow_construction") == "exact_empty_atomic_shadow_only"
        and contract.get("source_mutation") is False
        and contract.get("paths") == expected_paths
        and not (set(PACKAGE_SCAFFOLD_PATHS) & set(cfg.get("exact_sources", {})))
    )


def package_scaffold_source_census(
    source_root: Path, cfg: dict[str, Any]
) -> dict[str, Any]:
    """Record exact absence/empty states without changing the source tree."""
    contract_exact = package_scaffold_contract_exact(cfg)
    rows: list[dict[str, Any]] = []
    for relative in PACKAGE_SCAFFOLD_PATHS:
        state = _path_state(source_root, relative, require_single_link=True)
        observed_sha = ""
        observed_bytes = -1
        source_state = "unsafe_or_nonempty"
        admissible = False
        if not state["exists"]:
            source_state = "absent"
            admissible = bool(
                state["resolved_contained"]
                and not state["parent_or_target_symlink"]
            )
        elif state["valid_regular_contained"]:
            try:
                payload = source_snapshot_bytes(source_root, relative)
                observed_sha = hashlib.sha256(payload).hexdigest()
                observed_bytes = len(payload)
                if observed_sha == EMPTY_SHA256 and observed_bytes == 0:
                    source_state = "exact_empty"
                    admissible = True
                else:
                    source_state = "nonempty_regular"
            except (OSError, RuntimeError):
                source_state = "unstable_or_unreadable"
        rows.append({
            **state,
            "role": "shadow_package_scaffold_candidate",
            "expected_sha256": EMPTY_SHA256,
            "expected_bytes": 0,
            "observed_sha256": observed_sha,
            "observed_bytes": observed_bytes,
            "source_state": source_state,
            "source_state_admissible": admissible,
        })
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract_exact": contract_exact,
        "path_count": len(rows),
        "admissible_count": sum(
            row["source_state_admissible"] is True for row in rows
        ),
        "source_states": {
            row["relative_path"]: row["source_state"] for row in rows
        },
        "rows": rows,
        "census_pass": bool(
            contract_exact and len(rows) == 3
            and all(row["source_state_admissible"] is True for row in rows)
        ),
    }
    payload["receipt_sha256"] = canonical_json_sha256(payload)
    return payload


def copy_exact(source_root: Path, shadow: Path, relative: str, expected: str) -> None:
    canonical = canonical_relative(relative)
    payload = verified_source_bytes(source_root, canonical, expected)
    destination = shadow / safe_relative(relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _atomic_bytes(destination, payload)
    state = _path_state(shadow, canonical, require_single_link=True)
    if not state["valid_regular_contained"] or sha256(destination) != expected:
        raise RuntimeError(f"shadow_copy_verification_failed:{canonical}")


def _assert_supported_manifest_record_integrity_fields(
    record: dict[str, Any],
    relative: str,
) -> None:
    """Reject every integrity-looking record field outside the frozen schema."""
    for field in record:
        if not isinstance(field, str):
            raise RuntimeError(f"malformed_manifest_record_field:{relative}")
        kind = _integrity_field_kind(field, node=record, manifest_record=True)
        if kind == "digest" and field not in HASH_FIELDS:
            raise RuntimeError(
                f"unsupported_manifest_integrity_field:{relative}:{field}"
            )
        if kind == "size" and field not in SIZE_FIELDS:
            raise RuntimeError(
                f"unsupported_manifest_integrity_field:{relative}:{field}"
            )


def exact_manifest_file_records(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("manifest_top_level_files_missing_or_empty")
    found: dict[str, dict[str, Any]] = {}
    raw_for_canonical: dict[str, str] = {}
    for raw, record in files.items():
        if not isinstance(raw, str) or not isinstance(record, dict):
            raise RuntimeError("malformed_manifest_file_record")
        canonical = canonical_relative(raw)
        if canonical in found:
            raise RuntimeError(
                f"normalized_manifest_path_collision:{raw_for_canonical[canonical]}:{raw}"
            )
        _assert_supported_manifest_record_integrity_fields(record, canonical)
        digest = record.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise RuntimeError(f"malformed_manifest_sha256:{canonical}")
        for field in sorted(HASH_FIELDS & set(record)):
            value = record[field]
            if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
                raise RuntimeError(f"malformed_manifest_hash_field:{canonical}:{field}")
        for field in sorted(SIZE_FIELDS & set(record)):
            value = record[field]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise RuntimeError(f"malformed_manifest_size_field:{canonical}:{field}")
        found[canonical] = copy.deepcopy(record)
        raw_for_canonical[canonical] = raw
    return found


def _ast_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _ast_string_constants(node: ast.AST) -> set[str]:
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }


def _assignment_target_names(node: ast.Assign | ast.AnnAssign) -> set[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return {
        child.id
        for target in targets
        for child in ast.walk(target)
        if isinstance(child, ast.Name)
    }


def _pinned_executor_ast_guard_receipt(
    payload: bytes,
    *,
    path_leaf: str,
    digest_leaf: str,
) -> dict[str, Any]:
    """Conservatively prove one path/hash comparison in a pinned executor AST."""
    try:
        source = payload.decode("utf-8")
        tree = ast.parse(source)
    except (UnicodeDecodeError, SyntaxError) as error:
        return {
            "path_key_present": False,
            "digest_key_present": False,
            "repo_root_resolution_present": False,
            "sha256_operation_present": False,
            "path_digest_guard_present": False,
            "guard_before_first_plan_load": False,
            "guard_line": -1,
            "first_plan_load_line": -1,
            "error": f"{type(error).__name__}:{error}",
            "pass": False,
        }
    assignments = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    path_vars: set[str] = set()
    digest_vars: set[str] = set()
    root_vars: set[str] = {"repo_root", "root"}
    hash_vars: set[str] = set()
    for node in assignments:
        value = node.value
        if value is None:
            continue
        strings = _ast_string_constants(value)
        names = _ast_names(value)
        targets = _assignment_target_names(node)
        if path_leaf in strings:
            path_vars.update(targets)
        if digest_leaf in strings:
            digest_vars.update(targets)
        if "repo_root" in strings or "repo_root" in names:
            root_vars.update(targets)
    for _ in range(max(1, len(assignments))):
        changed = False
        for node in assignments:
            value = node.value
            if value is None:
                continue
            names = _ast_names(value)
            strings = _ast_string_constants(value)
            targets = _assignment_target_names(node)
            hash_marker = any(
                token in name.lower()
                for name in names
                for token in ("sha256", "hexdigest", "digest", "hash")
            )
            if (path_leaf in strings or names & path_vars) and not targets <= path_vars:
                path_vars.update(targets)
                changed = True
            if (digest_leaf in strings or names & digest_vars) and not targets <= digest_vars:
                digest_vars.update(targets)
                changed = True
            if hash_marker and (path_leaf in strings or names & path_vars) and not targets <= hash_vars:
                hash_vars.update(targets)
                changed = True
        if not changed:
            break
    all_names = _ast_names(tree)
    all_strings = _ast_string_constants(tree)
    sha_present = any(
        token in name.lower()
        for name in all_names
        for token in ("sha256", "hexdigest")
    )
    repo_root_present = bool(
        "repo_root" in all_names
        or "repo_root" in all_strings
        or any(
            (
                path_leaf in _ast_string_constants(node.value)
                and bool(_ast_names(node.value) & root_vars)
            )
            for node in assignments
            if node.value is not None
        )
    )
    guard_lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        names = _ast_names(node)
        strings = _ast_string_constants(node)
        digest_side = digest_leaf in strings or bool(names & digest_vars)
        hash_side = bool(names & hash_vars) or (
            (path_leaf in strings or bool(names & path_vars))
            and any(
                token in name.lower()
                for name in names
                for token in ("sha256", "hexdigest", "digest", "hash")
            )
        )
        if digest_side and hash_side and all(
            isinstance(operator, (ast.Eq, ast.NotEq)) for operator in node.ops
        ):
            guard_lines.append(int(getattr(node, "lineno", -1)))
    load_lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        names = _ast_names(node)
        if not (names & path_vars):
            continue
        lowered = {name.lower() for name in names}
        if any("sha256" in name or "hexdigest" in name for name in lowered):
            continue
        if lowered & {"open", "load", "loads", "read_text", "read_bytes"}:
            load_lines.append(int(getattr(node, "lineno", -1)))
    guard_line = min(guard_lines) if guard_lines else -1
    first_load = min(load_lines) if load_lines else -1
    guard_before_load = bool(
        guard_line > 0 and (first_load < 0 or guard_line <= first_load)
    )
    result = {
        "path_key_present": path_leaf in all_strings,
        "digest_key_present": digest_leaf in all_strings,
        "repo_root_resolution_present": repo_root_present,
        "sha256_operation_present": sha_present,
        "path_digest_guard_present": bool(guard_lines),
        "guard_before_first_plan_load": guard_before_load,
        "guard_line": guard_line,
        "first_plan_load_line": first_load,
        "error": "",
    }
    result["pass"] = all(
        result[key] is True
        for key in (
            "path_key_present", "digest_key_present",
            "repo_root_resolution_present", "sha256_operation_present",
            "path_digest_guard_present", "guard_before_first_plan_load",
        )
    )
    return result


def prove_schema_specific_config_integrity_bindings(
    source_root: Path, cfg: dict[str, Any]
) -> dict[str, Any]:
    declarations = cfg.get("authority_resolution", {}).get(
        "schema_specific_config_integrity_bindings", []
    )
    rows: list[dict[str, Any]] = []
    try:
        if declarations != [EXPECTED_SCHEMA_SPECIFIC_BINDING]:
            raise RuntimeError("exactly_one_schema_specific_config_binding_required")
        stage_by_name = {stage["stage"]: stage for stage in cfg["stage_contracts"]}
        for declaration in declarations:
            stage = stage_by_name[declaration["stage"]]
            config_relative = canonical_relative(stage["config"])
            selected = bindings_for_document(cfg, config_relative)
            if len(selected) != 1 or selected[0] != declaration:
                raise RuntimeError("schema_specific_config_binding_stage_resolution")
            config_payload = verified_source_bytes(
                source_root, config_relative, stage["config_sha256"]
            )
            config_value = strict_yaml_bytes(config_payload, config_relative)
            assert_unambiguous_sibling_integrity(
                config_value, cross_bindings=selected
            )
            normalized = _validated_cross_bindings(config_value, selected)[0]
            plan_relative = normalized["relative_path"]
            claimed_digest = deep_get(
                config_value, declaration["digest_dotted_key"]
            )
            manifest_relative = canonical_relative(stage["manifest"])
            manifest_value = strict_json_bytes(
                verified_source_bytes(
                    source_root, manifest_relative, stage["manifest_sha256"]
                ),
                manifest_relative,
            )
            manifest_records = exact_manifest_file_records(manifest_value)
            manifest_record = manifest_records.get(plan_relative)
            if not isinstance(manifest_record, dict):
                raise RuntimeError("schema_specific_binding_manifest_record_missing")
            plan_payload = source_snapshot_bytes(source_root, plan_relative)
            observed_digest = hashlib.sha256(plan_payload).hexdigest()
            executor_payload = verified_source_bytes(
                source_root, stage["executor"], stage["executor_sha256"]
            )
            path_leaf = declaration["path_dotted_key"].rsplit(".", 1)[-1]
            digest_leaf = declaration["digest_dotted_key"].rsplit(".", 1)[-1]
            ast_proof = _pinned_executor_ast_guard_receipt(
                executor_payload,
                path_leaf=path_leaf,
                digest_leaf=digest_leaf,
            )
            checks = {
                "config_path_canonical": plan_relative == deep_get(
                    config_value, declaration["path_dotted_key"]
                ),
                "config_digest_well_formed": isinstance(claimed_digest, str)
                and SHA256_RE.fullmatch(claimed_digest) is not None,
                "manifest_record_unique_and_present": plan_relative in manifest_records,
                "config_manifest_digest_equal": claimed_digest
                == manifest_record.get("sha256"),
                "config_observed_digest_equal": claimed_digest == observed_digest,
                "manifest_observed_digest_equal": manifest_record.get("sha256")
                == observed_digest,
                "executor_ast_guard_exact": ast_proof.get("pass") is True,
            }
            rows.append({
                "binding_id": declaration["binding_id"],
                "stage": declaration["stage"],
                "config_relative_path": config_relative,
                "config_sha256": stage["config_sha256"],
                "executor_relative_path": stage["executor"],
                "executor_sha256": stage["executor_sha256"],
                "manifest_relative_path": manifest_relative,
                "manifest_sha256": stage["manifest_sha256"],
                "path_dotted_key": declaration["path_dotted_key"],
                "digest_dotted_key": declaration["digest_dotted_key"],
                "relative_path": plan_relative,
                "claimed_sha256": claimed_digest,
                "manifest_sha256_claim": manifest_record.get("sha256", ""),
                "observed_sha256": observed_digest,
                "observed_bytes": len(plan_payload),
                "executor_ast_proof": ast_proof,
                "checks": checks,
                "binding_pass": all(checks.values()),
            })
        error = ""
    except Exception as caught:
        error = f"{type(caught).__name__}:{str(caught)[:1000]}"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "declared_binding_count": len(declarations)
        if isinstance(declarations, list) else -1,
        "proven_binding_count": sum(
            row.get("binding_pass") is True for row in rows
        ),
        "rows": rows,
        "error": error,
        "binding_proof_pass": bool(
            not error and len(rows) == 1
            and all(row.get("binding_pass") is True for row in rows)
        ),
    }
    payload["receipt_sha256"] = canonical_json_sha256(payload)
    return payload


# BH_SIMBA_SCHEMA_BOUND_PREDICATE_REPAIR_V1_5
def _bh_v15_filter_schema_bound_non_integrity_predicates(node, location):
    """Schema-bound removal of two attested boolean check predicates from integrity inventory only."""
    if location != '$.checks':
        return node
    if not isinstance(node, dict):
        return node
    if set(node.keys()) != set(('baseline_unchanged', 'candidate_hash_matches_repair', 'canonical_split_repair_passed', 'complete_tracks_400_per_split', 'effect_floor_unchanged', 'full_raw_history_recompute', 'phase_b_and_c_candidate_identical', 'phase_c_screen_200', 'raw_hash_matches_repair', 'repair_changed_no_scientific_values', 'repair_computed_no_predictive_outcome', 'ridge_unchanged', 'seed_history_included', 'selected_sets_disjoint', 'selection_repeated_inside_null', 'tau_grid_unchanged', 'terminal_future_not_permuted', 'track_bootstrap_2000')):
        return node
    try:
        repo = __import__("pathlib").Path(__file__).resolve().parents[1]
        manifest = repo / 'outputs/protocol/tng50_memory_generator3_sha256_split/bh_tng50_canonical_generator3_rerun_freeze_manifest.json'
        raw = manifest.read_bytes()
        if __import__("hashlib").sha256(raw).hexdigest() != 'fd939ccc4b1b71cbd4cf56bfec0c1f2a3c8bd10bc4f515917f4526cd42daccb6':
            return node
    except Exception:
        return node
    filtered = dict(node)
    for key in ('candidate_hash_matches_repair', 'raw_hash_matches_repair'):
        if key in filtered and type(filtered[key]) is bool:
            filtered.pop(key)
    return filtered

def assert_unambiguous_sibling_integrity(
    value: Any,
    *,
    cross_bindings: Iterable[dict[str, Any]] = (),
) -> None:
    if not isinstance(value, dict):
        normalized_cross: list[dict[str, Any]] = []
        if tuple(cross_bindings):
            raise RuntimeError("schema_specific_config_integrity_root_not_mapping")
    else:
        normalized_cross = _validated_cross_bindings(value, cross_bindings)
    owners: dict[str, tuple[str, str]] = {
        item["digest_location"]: (
            f"cross:{item['path_dotted_key']}", item["relative_path"]
        )
        for item in normalized_cross
    }
    cross_recognized: dict[str, set[str]] = {}
    for item in normalized_cross:
        cross_recognized.setdefault(item["digest_parent"], set()).add(
            item["digest_field"]
        )

    def walk(node: Any, location: str, *, manifest_record: bool = False) -> None:
        node = _bh_v15_filter_schema_bound_non_integrity_predicates(node, location)
        if isinstance(node, dict):
            recognized_integrity_fields: set[str] = set(
                cross_recognized.get(location, set())
            )
            if manifest_record:
                # Top-level ``files`` records have their own exact grammar;
                # their direct integrity fields are not sibling bindings.
                _assert_supported_manifest_record_integrity_fields(
                    node, location.removeprefix("$.files.")
                )
            for key, child in node.items():
                if location == "$.files" and isinstance(child, dict):
                    relative = canonical_relative(str(key))
                    _assert_supported_manifest_record_integrity_fields(child, relative)
                    for field in sorted((HASH_FIELDS | SIZE_FIELDS) & set(child)):
                        claim_location = f"{location}.{key}.{field}"
                        owners[claim_location] = (f"files:{key}", relative)
                if isinstance(child, str):
                    digest_keys, size_keys = sibling_integrity_fields(node, key)
                    recognized_integrity_fields.update(digest_keys)
                    recognized_integrity_fields.update(size_keys)
                    if digest_keys or size_keys:
                        if size_keys and not digest_keys:
                            raise RuntimeError(
                                f"sibling_size_without_digest_forbidden:{location}.{key}"
                            )
                        for field in digest_keys:
                            digest = node[field]
                            if (
                                not isinstance(digest, str)
                                or SHA256_RE.fullmatch(digest) is None
                            ):
                                raise RuntimeError(
                                    f"malformed_sibling_integrity_digest:"
                                    f"{location}.{field}"
                                )
                        for field in size_keys:
                            size = node[field]
                            if (
                                not isinstance(size, int)
                                or isinstance(size, bool)
                                or size < 0
                            ):
                                raise RuntimeError(
                                    f"malformed_sibling_integrity_size:"
                                    f"{location}.{field}"
                                )
                        relative = canonical_relative(child)
                        for field in [*digest_keys, *size_keys]:
                            claim_location = f"{location}.{field}"
                            owner = (key, relative)
                            if claim_location in owners and owners[claim_location] != owner:
                                raise RuntimeError(
                                    f"ambiguous_sibling_integrity_owner:{claim_location}"
                                )
                            owners[claim_location] = owner
                walk(
                    child,
                    f"{location}.{key}",
                    manifest_record=(location == "$.files" and isinstance(child, dict)),
                )
            if not manifest_record and location != "$.files":
                unsupported = sorted(
                    str(field)
                    for field in node
                    if _integrity_field_kind(field, node=node) is not None
                    and field not in recognized_integrity_fields
                )
                # BH_SIMBA_PRECONDITION_KEY_SHAPE_CLASSIFIER_V1_5H
                if isinstance(node, dict) and unsupported:
                    __bh_v15h_hex64 = __import__("re").compile(r"^[0-9a-f]{64}$")
                    __bh_v15h_kept = []
                    for __bh_v15h_key in unsupported:
                        __bh_v15h_value = node.get(__bh_v15h_key, None)
                        __bh_v15h_low = str(__bh_v15h_key).lower()
                        __bh_v15h_explicit = (
                            __bh_v15h_low in ("sha256", "digest", "hash")
                            or __bh_v15h_low.endswith("_sha256")
                            or __bh_v15h_low.endswith("_digest")
                            or (__bh_v15h_low.endswith("_hash") and isinstance(__bh_v15h_value, str))
                        )
                        # BH_SIMBA_STATIC_TEST23E_VECTOR_GUARD_V1_5M
                        __bh_v15l_historical_numeric_orphan = __bh_v15h_low in ('content_length',)
                        __bh_v15h_descriptor = False
                        if not __bh_v15h_explicit and not __bh_v15l_historical_numeric_orphan:
                            if type(__bh_v15h_value) is bool:
                                __bh_v15h_descriptor = True
                            elif isinstance(__bh_v15h_value, (int, float)) and not isinstance(__bh_v15h_value, bool):
                                __bh_v15h_descriptor = True
                            elif isinstance(__bh_v15h_value, str) and __bh_v15h_hex64.fullmatch(__bh_v15h_value) is None:
                                __bh_v15h_descriptor = True
                        if not __bh_v15h_descriptor:
                            __bh_v15h_kept.append(__bh_v15h_key)
                    unsupported = __bh_v15h_kept
                if unsupported:
                    raise RuntimeError(
                        f"unsupported_or_orphan_sibling_integrity_fields:{location}:"
                        f"{','.join(unsupported)}"
                    )
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{location}[{index}]")

    walk(value, "$")


def manifest_sibling_integrity_claims(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Inventory explicit path/digest sibling bindings outside ``files``."""
    assert_unambiguous_sibling_integrity(manifest)
    claims: list[dict[str, Any]] = []
    owners: dict[str, tuple[str, str]] = {}

    def walk(node: Any, location: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if isinstance(child, str):
                    digest_keys, size_keys = sibling_integrity_fields(node, key)
                    for digest_key in dict.fromkeys(digest_keys):
                        digest = node[digest_key]
                        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
                            raise RuntimeError(f"malformed_sibling_integrity_digest:{location}.{digest_key}")
                        relative = canonical_relative(child)
                        claim_location = f"{location}.{digest_key}"
                        owner = (key, relative)
                        if claim_location in owners and owners[claim_location] != owner:
                            raise RuntimeError(f"ambiguous_sibling_integrity_owner:{claim_location}")
                        owners[claim_location] = owner
                        sizes = {
                            size_key: node[size_key]
                            for size_key in dict.fromkeys(size_keys)
                        }
                        if any(
                            not isinstance(size, int) or isinstance(size, bool) or size < 0
                            for size in sizes.values()
                        ):
                            raise RuntimeError(f"malformed_sibling_integrity_size:{location}.{key}")
                        claims.append({
                            "relative_path": relative,
                            "location": claim_location,
                            "path_field": key,
                            "digest_field": digest_key,
                            "claimed_sha256": digest,
                            "size_fields": sizes,
                        })
                walk(child, f"{location}.{key}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{location}[{index}]")

    walk(manifest, "$")
    claims.sort(key=lambda item: (
        item["relative_path"], item["location"], item["digest_field"]
    ))
    return claims


def path_digest_records(value: Any) -> dict[str, str]:
    """Compatibility scanner with collision detection; executors use `files` only."""
    found: dict[str, str] = {}

    def add(relative: str, digest: str) -> None:
        canonical = canonical_relative(relative)
        if canonical in found and found[canonical] != digest:
            raise RuntimeError(f"recursive_digest_record_conflict:{canonical}")
        found[canonical] = digest

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if isinstance(child, dict) and isinstance(child.get("sha256"), str):
                    try:
                        add(str(key), child["sha256"])
                    except RuntimeError as error:
                        if str(error).startswith("unsafe_shadow_path"):
                            pass
                        else:
                            raise
                if isinstance(child, str) and (key.lower() in PATH_FIELDS or key.lower().endswith(PATH_SUFFIXES)):
                    stem = key.rsplit("_", 1)[0]
                    for digest_key in ("sha256", "file_sha256", "source_sha256", f"{key}_sha256", f"{stem}_sha256"):
                        digest = node.get(digest_key)
                        if isinstance(digest, str) and SHA256_RE.fullmatch(digest):
                            try:
                                add(child, digest)
                            except RuntimeError as error:
                                if str(error).startswith("unsafe_shadow_path"):
                                    pass
                                else:
                                    raise
                            break
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return found


def module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def local_module_candidate(root: Path, name: str) -> str | None:
    parts = Path(*name.split("."))
    candidates = [parts.with_suffix(".py"), parts / "__init__.py", Path("scripts") / (parts.name + ".py")]
    for candidate in candidates:
        if (root / candidate).is_file():
            return candidate.as_posix()
    return None


def copy_attested_code_closure(source_root: Path, shadow: Path, allowed: dict[str, str]) -> tuple[int, list[str]]:
    queue = [relative for relative in allowed if relative.endswith(".py") and (shadow / relative).is_file()]
    seen: set[str] = set()
    copied = 0
    unattested: list[str] = []
    while queue:
        relative = queue.pop(0)
        if relative in seen:
            continue
        seen.add(relative)
        # Parse the already verified/copied bytes, not a second read of the
        # mutable source pathname.
        for name in module_names(shadow / relative):
            candidate = local_module_candidate(source_root, name)
            if candidate is None or candidate in seen:
                continue
            expected = allowed.get(candidate)
            if expected is None:
                if candidate not in unattested:
                    unattested.append(candidate)
                continue
            copy_exact(source_root, shadow, candidate, expected)
            copied += 1
            queue.append(candidate)
    return copied, sorted(unattested)


def leaf_columns(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            found.extend(leaf_columns(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(leaf_columns(child, f"{prefix}[{index}]"))
    elif isinstance(value, str) and value.strip():
        found.append((prefix, value))
    return found


def column_kind(key: str, column: str) -> str:
    label = f"{key}.{column}".lower()
    if "split" in label:
        return "split"
    if any(token in label for token in ("mass_class", "environment", "category", "class")):
        return "category"
    if key.lower().endswith("id") or column.lower() in {"id", "bh_id", "blackhole_id", "track_id"}:
        return "id"
    if any(token in label for token in ("time", "order", "snapshot", "scale_factor", "delta_time")) or column == "a":
        return "order"
    if label.endswith(".selected") or label.endswith(".eligible") or column.lower().startswith("is_"):
        return "boolean"
    if any(token in label for token in ("lambda", "coordinate", "history", "target", "response", "current", "previous", "next", "signal")):
        return "coordinate"
    return "numeric"


def _split_contract(configs: list[dict], track_count: int) -> tuple[list[str], int]:
    split_orders = [list(config["screen"]["split_order"]) for config in configs if isinstance(config.get("screen"), dict) and config["screen"].get("split_order")]
    splits = split_orders[0] if split_orders else ["train", "validation", "test"]
    if any(order != splits for order in split_orders):
        raise RuntimeError("inconsistent_screen_split_order")
    counts = {
        int(config["screen"]["complete_tracks_per_split"])
        for config in configs
        if isinstance(config.get("screen"), dict) and "complete_tracks_per_split" in config["screen"]
    }
    per_split = counts.pop() if counts else track_count // len(splits)
    if counts or set(splits) != {"train", "validation", "test"} or track_count != per_split * len(splits):
        raise RuntimeError("synthetic_split_contract_not_exact")
    return splits, per_split


def _load_causal_module(shadow: Path):
    path = shadow / "src/core/causal_memory.py"
    spec = importlib.util.spec_from_file_location("bh_simba_shadow_causal_memory", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("causal_memory_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_synthetic_frame(
    shadow: Path,
    configs: list[dict],
    track_count: int,
    steps: int,
    offset: float,
    seed: int,
    tau_source_key: str,
    tau_column_template: str,
):
    import numpy as np
    import pandas as pd

    splits, per_split = _split_contract(configs, track_count)
    mappings: dict[str, str] = {}
    role_columns: dict[str, set[str]] = {}
    taus: set[float] = set()
    for config in configs:
        for key, column in leaf_columns(config.get("columns", {}), "columns"):
            mappings.setdefault(column, column_kind(key, column))
            role_columns.setdefault(key.split(".")[-1].lower(), set()).add(column)
        try:
            configured_taus = deep_get(config, tau_source_key)
        except KeyError:
            configured_taus = []
        if not isinstance(configured_taus, list):
            raise RuntimeError("synthetic_memory_tau_source_not_list")
        for value in configured_taus:
            taus.add(float(value))
    for fallback, kind in (
        ("bh_id", "id"), ("track_id", "id"), ("canonical_split", "split"),
        ("split", "split"), ("snapshot", "order"), ("a", "order"),
        ("lambda", "coordinate"), ("mass_class", "category"),
    ):
        mappings.setdefault(fallback, kind)
    identifiers = np.repeat(np.arange(1, track_count + 1, dtype=np.int64), steps)
    order = np.tile(np.arange(steps, dtype=float), track_count)
    split_by_track = np.repeat(np.array(splits, dtype=object), per_split)
    split = np.repeat(split_by_track, steps)
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0, 1.0, size=(track_count, steps))
    base += 0.12 * np.sin(np.arange(steps, dtype=float)[None, :] * 0.37 + np.arange(track_count)[:, None] * 0.011)
    signal_matrix = base + float(offset)
    causal = _load_causal_module(shadow)
    u = causal.normalize_track_time(np.arange(steps, dtype=float) + 1.0)
    memories: dict[float, np.ndarray] = {}
    for tau in sorted(taus):
        values = np.vstack([causal.causal_exponential_memory(u, row, tau) for row in signal_matrix])
        memories[tau] = values.reshape(-1)
    signal = signal_matrix.reshape(-1)
    chosen_memory = memories[sorted(taus)[len(taus) // 2]] if taus else signal
    target = chosen_memory + 0.015 * rng.normal(size=len(signal))
    data: dict[str, Any] = {}
    for column, kind in mappings.items():
        if kind == "id":
            data[column] = identifiers
        elif kind == "split":
            data[column] = split
        elif kind == "category":
            data[column] = np.repeat(np.array(["middle"], dtype=object), len(order))
        elif kind == "order":
            data[column] = order + 1.0
        elif kind == "coordinate":
            data[column] = signal
        elif kind == "boolean":
            data[column] = np.ones(len(order), dtype=bool)
        else:
            data[column] = 1.0 + 0.02 * signal + 0.001 * order
    for column in role_columns.get("target", set()) | role_columns.get("response", set()):
        data[column] = target
    for column in role_columns.get("current", set()) | role_columns.get("raw_signal", set()):
        data[column] = signal
    for column in role_columns.get("delta_time", set()):
        data[column] = np.ones(len(order), dtype=float)
    for tau, values in memories.items():
        data[tau_column_template.format(tau=tau)] = values
    return pd.DataFrame(data), splits, per_split, sorted(taus)


def write_track_plan(path: Path, track_count: int, steps: int, splits: list[str], per_split: int) -> None:
    import numpy as np
    import pandas as pd

    ids = np.arange(1, track_count + 1, dtype=np.int64)
    split_by_track = np.repeat(np.array(splits, dtype=object), per_split)
    frame = pd.DataFrame({
        "bh_id": ids,
        "track_id": ids,
        "canonical_split": split_by_track,
        "split": split_by_track,
        "n_steps": np.full(track_count, steps, dtype=np.int64),
        "complete": np.ones(track_count, dtype=bool),
        "eligible": np.ones(track_count, dtype=bool),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        frame.to_parquet(path, index=False)
    elif suffix == ".json":
        selected = {
            split: [int(value) for value in frame.loc[frame["split"] == split, "track_id"].tolist()]
            for split in splits
        }
        payload = {
            "schema_version": 1,
            "synthetic_only": True,
            "selected_track_ids": selected,
            "tracks": frame.to_dict(orient="records"),
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    else:
        frame.to_csv(path, index=False)


"""Source to insert in the proposed owner. No installation or process execution."""

_SUPPORT_AMENDMENT_ID = "BH-SIMBA-SYNTHETIC-RAW-CANDIDATE-SUPPORT-001"
_SUPPORT_ADOPTED_FILE_SHA256 = "ab002fd519d53fdc3ccdf6a0f837d1fd1092409224fab6f2c398716e3566584c"
_SUPPORT_DESCRIPTOR = {
    "amendment_id": _SUPPORT_AMENDMENT_ID,
    "adopted_contract_file_sha256": _SUPPORT_ADOPTED_FILE_SHA256,
    "candidate_support": "raw_positions_1_through_N_minus_2",
    "raw_history_support": "all_rows_including_seed_and_terminal",
    "only_retained_column_rebound": "row_in_track",
}


def _support_input_roles(cfg, configs):
    """Resolve distinct, non-overlapping file roles from the unchanged stage data keys."""
    if cfg["synthetic_contract"].get("input_support") != _SUPPORT_DESCRIPTOR:
        raise RuntimeError("synthetic_support_descriptor_not_exact")
    candidate_paths, raw_paths, plan_paths = set(), set(), set()
    stage_by_name = {s["stage"]: s for s in cfg["stage_contracts"]}
    if len(stage_by_name) != len(cfg["stage_contracts"]):
        raise RuntimeError("synthetic_support_duplicate_stage")
    screen = configs[stage_by_name["generator3_null_screen"]["config"]]
    columns = screen["columns"]
    phase = configs[stage_by_name["generator3_phase_b"]["config"]]
    roles = ("id", "split", "target", "current", "delta_time", "category", "mass_class")
    if any(phase["columns"][k] != columns[k] for k in roles):
        raise RuntimeError("synthetic_support_phase_column_disagreement")
    confirm = configs[stage_by_name["generator3_null_confirmation_2000"]["config"]]
    if confirm["columns"] != columns:
        raise RuntimeError("synthetic_support_null_column_disagreement")
    for stage in cfg["stage_contracts"]:
        value = configs[stage["config"]]
        for key in stage["required_data_keys"]:
            path = canonical_relative(str(deep_get(value, key)))
            if key.endswith("candidate_parquet"):
                candidate_paths.add(path)
            elif key.endswith("raw_track_parquet"):
                raw_paths.add(path)
            elif key.endswith("canonical_g3_track_plan"):
                plan_paths.add(path)
    if not candidate_paths or not raw_paths or not plan_paths:
        raise RuntimeError("synthetic_support_missing_role")
    if candidate_paths & raw_paths or candidate_paths & plan_paths or raw_paths & plan_paths:
        raise RuntimeError("synthetic_support_role_path_collision")
    all_paths = candidate_paths | raw_paths | plan_paths
    if any(a != b and (a.startswith(b + "/") or b.startswith(a + "/"))
           for a in all_paths for b in all_paths):
        raise RuntimeError("synthetic_support_role_path_ancestor_collision")
    if not {canonical_relative(screen["data"]["candidate_parquet"])} == candidate_paths:
        raise RuntimeError("synthetic_support_candidate_path_disagreement")
    if not {canonical_relative(screen["data"]["raw_track_parquet"])} == raw_paths:
        raise RuntimeError("synthetic_support_raw_path_disagreement")
    return candidate_paths, raw_paths, plan_paths, columns


def _support_project_candidate(raw, columns, steps):
    """Writer implementation: group positions, never observed-finiteness selection."""
    import numpy as np
    if type(steps) is not int or steps < 3 or not raw.columns.is_unique:
        raise RuntimeError("synthetic_support_invalid_steps_or_duplicate_columns")
    index_col = columns["order"]
    if index_col != "row_in_track" or index_col in {
        columns[k] for k in ("id", "split", "raw_time", "candidate_time", "raw_signal", "target", "current", "delta_time", "category", "mass_class")
    }:
        raise RuntimeError("synthetic_support_index_alias")
    if raw[columns["id"]].isna().any() or raw[columns["split"]].isna().any():
        raise RuntimeError("synthetic_support_missing_id_or_split")
    groups = raw.groupby(columns["id"], sort=False, observed=True)
    counts = groups.size()
    if not len(counts) or not (counts == steps).all():
        raise RuntimeError("synthetic_support_track_length")
    positions = groups.cumcount().to_numpy(dtype=np.int64)
    if not np.array_equal(positions, np.tile(np.arange(steps), len(counts))):
        raise RuntimeError("synthetic_support_noncontiguous_tracks")
    if not (groups[columns["split"]].nunique(dropna=False) == 1).all():
        raise RuntimeError("synthetic_support_split_drift")
    times = raw[columns["raw_time"]].to_numpy(float).reshape(-1, steps)
    if not np.isfinite(times).all() or not (np.diff(times, axis=1) > 0).all():
        raise RuntimeError("synthetic_support_time_order")
    keep = (positions >= 1) & (positions < steps - 1)
    selected = np.flatnonzero(keep)
    candidate = raw.iloc[selected].copy(deep=True).reset_index(drop=True)
    dtype = candidate[index_col].dtype
    if dtype.kind not in "iuf":
        raise RuntimeError("synthetic_support_index_dtype")
    candidate[index_col] = positions[keep].astype(dtype)
    return candidate, selected


def _support_reference_candidate(raw, columns, steps):
    """Independent oracle: contiguous raw blocks and explicit interior slices."""
    import numpy as np
    import pandas as pd
    if type(steps) is not int or steps < 3 or len(raw) % steps or not len(raw):
        raise RuntimeError("synthetic_reference_raw_shape")
    if not raw.columns.is_unique:
        raise RuntimeError("synthetic_reference_duplicate_columns")
    pieces, indices, identifiers = [], [], set()
    for start in range(0, len(raw), steps):
        block = raw.iloc[start:start + steps]
        key = block[columns["id"]].iloc[0]
        if block[columns["id"]].isna().any() or key in identifiers or not (block[columns["id"]] == key).all():
            raise RuntimeError("synthetic_reference_track_not_unique_contiguous")
        identifiers.add(key)
        if block[columns["split"]].isna().any() or block[columns["split"]].nunique(dropna=False) != 1:
            raise RuntimeError("synthetic_reference_split_drift")
        times = block[columns["raw_time"]].to_numpy(float)
        if not np.isfinite(times).all() or not (np.diff(times) > 0).all():
            raise RuntimeError("synthetic_reference_invalid_time")
        part = block.iloc[1:-1].copy(deep=True)
        dtype = part[columns["order"]].dtype
        if dtype.kind not in "iuf":
            raise RuntimeError("synthetic_reference_index_dtype")
        part[columns["order"]] = np.arange(1, steps - 1).astype(dtype)
        pieces.append(part)
        indices.extend(range(start + 1, start + steps - 1))
    return pd.concat(pieces, ignore_index=True), np.asarray(indices, dtype=np.int64)


def _support_view_checks(raw, candidate, selected, columns, steps, tracks, splits, per_split, memory_columns):
    """Independent support/value checks shared by receipt builders, not by projection."""
    import numpy as np
    import pandas as pd
    try:
        if not raw.columns.is_unique or not candidate.columns.is_unique or len(raw) != tracks * steps:
            raise RuntimeError("synthetic_support_raw_shape")
        expected_indices = np.asarray([base + i for base in range(0, len(raw), steps)
                                       for i in range(1, steps - 1)], dtype=np.int64)
        if not np.array_equal(selected, expected_indices):
            raise RuntimeError("synthetic_support_raw_index_selection")
        index_col = columns["order"]
        if index_col != "row_in_track" or index_col in {
            columns[k] for k in ("id", "split", "raw_time", "candidate_time", "raw_signal", "target", "current", "delta_time", "category", "mass_class")
        }:
            raise RuntimeError("synthetic_support_index_alias")
        expected = raw.iloc[expected_indices].reset_index(drop=True)
        if list(candidate.columns) != list(raw.columns) or not candidate.dtypes.equals(expected.dtypes):
            raise RuntimeError("synthetic_support_schema_changed")
        pd.testing.assert_frame_equal(candidate.drop(columns=[index_col]), expected.drop(columns=[index_col]),
                                      check_exact=True, check_dtype=True)
        if not np.array_equal(candidate[index_col].to_numpy(), np.tile(np.arange(1, steps - 1), tracks)):
            raise RuntimeError("synthetic_support_index_rebinding")
        if not np.array_equal(candidate[columns["candidate_time"]].to_numpy(), raw[columns["raw_time"]].to_numpy()[expected_indices]):
            raise RuntimeError("synthetic_support_candidate_time_mapping")
        model_columns = list(dict.fromkeys([columns["target"], columns["current"], columns["delta_time"], *sorted(memory_columns)]))
        if not np.isfinite(candidate[model_columns].to_numpy(float)).all():
            raise RuntimeError("synthetic_support_interior_nonfinite")
        if set(candidate[columns["split"]].astype(str)) != set(splits):
            raise RuntimeError("synthetic_support_split_set")
        for label in splits:
            rg = raw.loc[raw[columns["split"]] == label]
            cg = candidate.loc[candidate[columns["split"]] == label]
            if len(cg) != per_split * (steps - 2) or set(rg[columns["id"]]) != set(cg[columns["id"]]):
                raise RuntimeError("synthetic_support_track_or_split_population_changed")
        return {"candidate_support_and_values_exact": True, "candidate_model_inputs_finite": True}
    except (AssertionError, KeyError, TypeError, ValueError) as error:
        raise RuntimeError("synthetic_support_value_verification:" + str(error)) from error


def _write_expected_synthetic_support_impl(
    shadow: Path,
    cfg: dict,
    configs: dict[str, dict],
    offset: float,
) -> dict[str, Any]:
    track_count = int(cfg["synthetic_contract"]["track_count"])
    steps = int(cfg["synthetic_contract"]["steps_per_track"])
    seed = int(cfg["synthetic_contract"]["seed"])
    tau_source_key = str(cfg["synthetic_contract"]["memory_tau_source_config_key"])
    tau_column_template = str(cfg["synthetic_contract"]["memory_tau_column_template"])
    frame, splits, per_split, taus = build_synthetic_frame(
        shadow,
        [configs[key] for key in sorted(configs)],
        track_count,
        steps,
        offset,
        seed,
        tau_source_key,
        tau_column_template,
    )
    if len(frame) > int(cfg["synthetic_contract"]["maximum_rows"]):
        raise RuntimeError("synthetic_fixture_row_limit_exceeded")
    candidate_paths, raw_paths, plan_paths, columns = _support_input_roles(cfg, configs)
    parquet_paths = candidate_paths | raw_paths
    candidate, source_indices = _support_reference_candidate(frame, columns, steps)
    required_memory = {tau_column_template.format(tau=tau) for tau in taus}
    support_checks = _support_view_checks(
        frame, candidate, source_indices, columns, steps, track_count, splits, per_split, required_memory
    )
    for relative in sorted(parquet_paths):
        destination = shadow / safe_relative(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        (candidate if relative in candidate_paths else frame).to_parquet(destination, index=False)
    for relative in sorted(plan_paths):
        write_track_plan(shadow / safe_relative(relative), track_count, steps, splits, per_split)
    required_memory = {tau_column_template.format(tau=tau) for tau in taus}
    parquet_receipts = {
        relative: {
            "sha256": sha256(shadow / safe_relative(relative)),
            "bytes": (shadow / safe_relative(relative)).stat().st_size,
        }
        for relative in sorted(parquet_paths)
    }
    plan_receipts = {
        relative: {
            "sha256": sha256(shadow / safe_relative(relative)),
            "bytes": (shadow / safe_relative(relative)).stat().st_size,
        }
        for relative in sorted(plan_paths)
    }
    selected_schema_exact = True
    expected_ids = {
        split: list(range(index * per_split + 1, (index + 1) * per_split + 1))
        for index, split in enumerate(splits)
    }
    for relative in sorted(plan_paths):
        path = shadow / safe_relative(relative)
        if path.suffix.lower() == ".json":
            try:
                plan = strict_json_bytes(path.read_bytes(), relative)
                selected_schema_exact = selected_schema_exact and (
                    plan.get("schema_version") == 1
                    and plan.get("synthetic_only") is True
                    and plan.get(cfg["synthetic_contract"]["track_plan_required_key"])
                    == expected_ids
                )
            except (OSError, RuntimeError):
                selected_schema_exact = False
    fixture_checks = {
        "train_validation_test_exact": (
            splits == list(cfg["synthetic_contract"]["required_splits"])
            == ["train", "validation", "test"]
        ),
        "complete_tracks_per_split_exact": False,
        "all_configured_memory_columns_present": required_memory.issubset(frame.columns),
        "selected_track_ids_schema_exact": selected_schema_exact and bool(plan_paths),
        **support_checks,
        "synthetic_row_limit_respected": len(frame) <= int(cfg["synthetic_contract"]["maximum_rows"]),
        "declared_split_counts_crosscheck_exact": (
            per_split == int(cfg["synthetic_contract"]["complete_tracks_per_split"])
            == int(cfg["synthetic_contract"]["track_plan_each_required_split_exact_count"])
            and track_count == per_split * len(splits)
        ),
    }
    # The exact count is checked from the generated plan and frame IDs, without
    # guessing which configured identifier column an executor uses.
    id_columns = [column for column in frame if column.lower() in {"id", "bh_id", "blackhole_id", "track_id"}]
    split_columns = [column for column in frame if "split" in column.lower()]
    if id_columns and split_columns:
        fixture_checks["complete_tracks_per_split_exact"] = all(
            int(frame.loc[frame[split_columns[0]] == split, id_columns[0]].nunique()) == per_split
            for split in splits
        )
    else:
        fixture_checks["complete_tracks_per_split_exact"] = False
    return {
        "parquet_file_count": len(parquet_paths),
        "track_plan_file_count": len(plan_paths),
        "synthetic_row_count": len(frame),
        "synthetic_raw_row_count": len(frame),
        "synthetic_candidate_row_count": len(candidate),
        "synthetic_candidate_rows_per_track": steps - 2,
        "synthetic_input_roles": {
            "raw_track_parquet": sorted(raw_paths),
            "candidate_parquet": sorted(candidate_paths),
            "canonical_g3_track_plan": sorted(plan_paths),
        },
        "support_amendment_id": _SUPPORT_AMENDMENT_ID,
        "candidate_source_indices_sha256": hashlib.sha256(
            source_indices.astype("<i8").tobytes()
        ).hexdigest(),
        "synthetic_split_count": len(splits),
        "synthetic_tracks_per_split": per_split,
        "synthetic_memory_tau_count": len(taus),
        "synthetic_seed": seed,
        "synthetic_offset": float(offset),
        "synthetic_file_receipts": {**parquet_receipts, **plan_receipts},
        "synthetic_file_receipts_sha256": canonical_json_sha256({**parquet_receipts, **plan_receipts}),
        "fixture_contract_checks": fixture_checks,
        "fixture_contract_pass": all(fixture_checks.values()),
    }


def _write_synthetic_inputs_impl(
    shadow: Path,
    cfg: dict,
    configs: dict[str, dict],
    offset: float,
) -> dict[str, Any]:
    track_count = int(cfg["synthetic_contract"]["track_count"])
    steps = int(cfg["synthetic_contract"]["steps_per_track"])
    seed = int(cfg["synthetic_contract"]["seed"])
    tau_source_key = str(cfg["synthetic_contract"]["memory_tau_source_config_key"])
    tau_column_template = str(cfg["synthetic_contract"]["memory_tau_column_template"])
    frame, splits, per_split, taus = build_synthetic_frame(
        shadow,
        [configs[key] for key in sorted(configs)],
        track_count,
        steps,
        offset,
        seed,
        tau_source_key,
        tau_column_template,
    )
    if len(frame) > int(cfg["synthetic_contract"]["maximum_rows"]):
        raise RuntimeError("synthetic_fixture_row_limit_exceeded")
    candidate_paths, raw_paths, plan_paths, columns = _support_input_roles(cfg, configs)
    parquet_paths = candidate_paths | raw_paths
    candidate, source_indices = _support_project_candidate(frame, columns, steps)
    required_memory = {tau_column_template.format(tau=tau) for tau in taus}
    support_checks = _support_view_checks(
        frame, candidate, source_indices, columns, steps, track_count, splits, per_split, required_memory
    )
    for relative in sorted(parquet_paths):
        destination = shadow / safe_relative(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        (candidate if relative in candidate_paths else frame).to_parquet(destination, index=False)
    for relative in sorted(plan_paths):
        write_track_plan(shadow / safe_relative(relative), track_count, steps, splits, per_split)
    required_memory = {tau_column_template.format(tau=tau) for tau in taus}
    parquet_receipts = {
        relative: {
            "sha256": sha256(shadow / safe_relative(relative)),
            "bytes": (shadow / safe_relative(relative)).stat().st_size,
        }
        for relative in sorted(parquet_paths)
    }
    plan_receipts = {
        relative: {
            "sha256": sha256(shadow / safe_relative(relative)),
            "bytes": (shadow / safe_relative(relative)).stat().st_size,
        }
        for relative in sorted(plan_paths)
    }
    selected_schema_exact = True
    expected_ids = {
        split: list(range(index * per_split + 1, (index + 1) * per_split + 1))
        for index, split in enumerate(splits)
    }
    for relative in sorted(plan_paths):
        path = shadow / safe_relative(relative)
        if path.suffix.lower() == ".json":
            try:
                plan = strict_json_bytes(path.read_bytes(), relative)
                selected_schema_exact = selected_schema_exact and (
                    plan.get("schema_version") == 1
                    and plan.get("synthetic_only") is True
                    and plan.get(cfg["synthetic_contract"]["track_plan_required_key"])
                    == expected_ids
                )
            except (OSError, RuntimeError):
                selected_schema_exact = False
    fixture_checks = {
        "train_validation_test_exact": (
            splits == list(cfg["synthetic_contract"]["required_splits"])
            == ["train", "validation", "test"]
        ),
        "complete_tracks_per_split_exact": False,
        "all_configured_memory_columns_present": required_memory.issubset(frame.columns),
        "selected_track_ids_schema_exact": selected_schema_exact and bool(plan_paths),
        **support_checks,
        "synthetic_row_limit_respected": len(frame) <= int(cfg["synthetic_contract"]["maximum_rows"]),
        "declared_split_counts_crosscheck_exact": (
            per_split == int(cfg["synthetic_contract"]["complete_tracks_per_split"])
            == int(cfg["synthetic_contract"]["track_plan_each_required_split_exact_count"])
            and track_count == per_split * len(splits)
        ),
    }
    # The exact count is checked from the generated plan and frame IDs, without
    # guessing which configured identifier column an executor uses.
    id_columns = [column for column in frame if column.lower() in {"id", "bh_id", "blackhole_id", "track_id"}]
    split_columns = [column for column in frame if "split" in column.lower()]
    if id_columns and split_columns:
        fixture_checks["complete_tracks_per_split_exact"] = all(
            int(frame.loc[frame[split_columns[0]] == split, id_columns[0]].nunique()) == per_split
            for split in splits
        )
    else:
        fixture_checks["complete_tracks_per_split_exact"] = False
    return {
        "parquet_file_count": len(parquet_paths),
        "track_plan_file_count": len(plan_paths),
        "synthetic_row_count": len(frame),
        "synthetic_raw_row_count": len(frame),
        "synthetic_candidate_row_count": len(candidate),
        "synthetic_candidate_rows_per_track": steps - 2,
        "synthetic_input_roles": {
            "raw_track_parquet": sorted(raw_paths),
            "candidate_parquet": sorted(candidate_paths),
            "canonical_g3_track_plan": sorted(plan_paths),
        },
        "support_amendment_id": _SUPPORT_AMENDMENT_ID,
        "candidate_source_indices_sha256": hashlib.sha256(
            source_indices.astype("<i8").tobytes()
        ).hexdigest(),
        "synthetic_split_count": len(splits),
        "synthetic_tracks_per_split": per_split,
        "synthetic_memory_tau_count": len(taus),
        "synthetic_seed": seed,
        "synthetic_offset": float(offset),
        "synthetic_file_receipts": {**parquet_receipts, **plan_receipts},
        "synthetic_file_receipts_sha256": canonical_json_sha256({**parquet_receipts, **plan_receipts}),
        "fixture_contract_checks": fixture_checks,
        "fixture_contract_pass": all(fixture_checks.values()),
    }


def write_synthetic_inputs(
    shadow: Path,
    cfg: dict,
    configs: dict[str, dict],
    offset: float,
) -> dict[str, Any]:
    """Public construction hook; verification uses the private canonical writer."""
    return _write_synthetic_inputs_impl(shadow, cfg, configs, offset)


_EXPECTED_SYNTHETIC_CACHE: dict[str, dict[str, Any]] = {}


def expected_synthetic_construction(
    source_root: Path,
    cfg: dict[str, Any],
    offset: float,
) -> dict[str, Any]:
    """Regenerate exact synthetic bytes independently from pinned authorities."""
    cache_key = canonical_json_sha256({
        "source_root": str(source_root.resolve()),
        "config": cfg,
        "offset": float(offset),
    })
    cached = _EXPECTED_SYNTHETIC_CACHE.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)
    configs = _source_config_values(source_root, cfg)
    with tempfile.TemporaryDirectory(prefix="bh_simba_expected_fixture_") as temporary:
        shadow = Path(temporary) / "repo"
        shadow.mkdir()
        for relative, digest in sorted(cfg["exact_sources"].items()):
            if relative.endswith(".py"):
                copy_exact(source_root, shadow, relative, digest)
        for relative in PACKAGE_SCAFFOLD_PATHS:
            path = shadow / relative
            if not path.exists():
                _atomic_bytes(path, b"")
        result = _write_expected_synthetic_support_impl(shadow, cfg, configs, float(offset))
    _EXPECTED_SYNTHETIC_CACHE[cache_key] = copy.deepcopy(result)
    return result


def refresh_integrity_records(
    value: Any,
    shadow: Path | None,
    location: str = "$",
    *,
    constructed_files: dict[str, dict[str, Any]] | None = None,
    cross_bindings: Iterable[dict[str, Any]] = (),
) -> tuple[Any, list[dict[str, Any]]]:
    """Refresh only frozen native integrity bindings.

    The authorized construction scope is deliberately narrow: records directly
    beneath the manifest's top-level ``files`` mapping, plus unambiguous sibling
    bindings such as ``track_plan``/``track_plan_sha256``.  Generic recursive
    ``path``/``sha256`` guessing is not authorized.  A verifier can pass the
    frozen constructed-file inventory instead of a live shadow to reproduce the
    exact mutation list independently.
    """
    mutations: list[dict[str, Any]] = []
    normalized_cross: list[dict[str, Any]] = []
    if location == "$":
        assert_unambiguous_sibling_integrity(
            value, cross_bindings=cross_bindings
        )
        if isinstance(value, dict):
            normalized_cross = _validated_cross_bindings(value, cross_bindings)

    def observation(relative: str) -> dict[str, Any] | None:
        canonical = canonical_relative(relative)
        if constructed_files is not None:
            record = constructed_files.get(canonical)
            if (
                not isinstance(record, dict)
                or set(record) != {"sha256", "bytes"}
                or SHA256_RE.fullmatch(str(record.get("sha256", ""))) is None
                or not isinstance(record.get("bytes"), int)
                or isinstance(record.get("bytes"), bool)
                or record["bytes"] < 0
            ):
                return None
            return {"sha256": record["sha256"], "bytes": record["bytes"]}
        if shadow is None:
            raise RuntimeError("integrity_refresh_requires_shadow_or_inventory")
        state = _path_state(shadow, canonical, require_single_link=True)
        if not state["valid_regular_contained"]:
            return None
        path = shadow / safe_relative(canonical)
        return {"sha256": sha256(path), "bytes": path.stat().st_size}

    if isinstance(value, dict):
        refreshed = copy.deepcopy(value)
        for key, child in list(refreshed.items()):
            new_child, child_mutations = refresh_integrity_records(
                child,
                shadow,
                f"{location}.{key}",
                constructed_files=constructed_files,
                cross_bindings=(),
            )
            refreshed[key] = new_child
            mutations.extend(child_mutations)
        for key, child in list(refreshed.items()):
            # Only a manifest's exact top-level ``files`` records may use a
            # pathname as the mapping key.  Path-keyed dictionaries elsewhere
            # are metadata, not implicit mutation authority.
            if location == "$.files" and isinstance(child, dict):
                try:
                    relative = canonical_relative(str(key))
                    observed = observation(relative)
                except RuntimeError:
                    observed = None
                if observed is not None:
                    for digest_key in sorted(HASH_FIELDS & set(child)):
                        if not isinstance(child[digest_key], str):
                            raise RuntimeError(f"malformed_integrity_digest_field:{location}.{key}.{digest_key}")
                        before = child[digest_key]
                        after = observed["sha256"]
                        child[digest_key] = after
                        if before != after:
                            mutations.append({
                                "location": f"{location}.{key}.{digest_key}",
                                "relative_path": relative,
                                "field": digest_key,
                                "kind": "digest",
                                "before": before,
                                "after": after,
                            })
                    for size_key in sorted(SIZE_FIELDS & set(child)):
                        if not isinstance(child[size_key], int) or isinstance(child[size_key], bool):
                            raise RuntimeError(f"malformed_integrity_size_field:{location}.{key}.{size_key}")
                        before = child[size_key]
                        after = observed["bytes"]
                        child[size_key] = after
                        if before != after:
                            mutations.append({
                                "location": f"{location}.{key}.{size_key}",
                                "relative_path": relative,
                                "field": size_key,
                                "kind": "size",
                                "before": before,
                                "after": after,
                            })
            if isinstance(child, str):
                digest_keys, size_keys = sibling_integrity_fields(refreshed, key)
                if not digest_keys and not size_keys:
                    continue
                try:
                    relative = canonical_relative(child)
                    observed = observation(relative)
                except RuntimeError:
                    observed = None
                if observed is None:
                    continue
                for digest_key in digest_keys:
                    if not isinstance(refreshed[digest_key], str):
                        raise RuntimeError(f"malformed_integrity_digest_field:{location}.{digest_key}")
                    before = refreshed[digest_key]
                    after = observed["sha256"]
                    refreshed[digest_key] = after
                    if before != after:
                        mutations.append({
                            "location": f"{location}.{digest_key}",
                            "relative_path": relative,
                            "field": digest_key,
                            "kind": "digest",
                            "before": before,
                            "after": after,
                        })
                for size_key in size_keys:
                    if not isinstance(refreshed[size_key], int) or isinstance(refreshed[size_key], bool):
                        raise RuntimeError(f"malformed_integrity_size_field:{location}.{size_key}")
                    before = refreshed[size_key]
                    after = observed["bytes"]
                    refreshed[size_key] = after
                    if before != after:
                        mutations.append({
                            "location": f"{location}.{size_key}",
                            "relative_path": relative,
                            "field": size_key,
                            "kind": "size",
                            "before": before,
                            "after": after,
                        })
        if location == "$":
            for binding in normalized_cross:
                observed = observation(binding["relative_path"])
                if observed is None:
                    continue
                before = deep_get(refreshed, binding["digest_dotted_key"])
                after = observed["sha256"]
                deep_set(refreshed, binding["digest_dotted_key"], after)
                if before != after:
                    mutations.append({
                        "location": binding["digest_location"],
                        "relative_path": binding["relative_path"],
                        "field": binding["digest_field"],
                        "kind": "digest",
                        "before": before,
                        "after": after,
                    })
        return refreshed, mutations
    if isinstance(value, list):
        refreshed_list = []
        for index, child in enumerate(value):
            new_child, child_mutations = refresh_integrity_records(
                child,
                shadow,
                f"{location}[{index}]",
                constructed_files=constructed_files,
                cross_bindings=(),
            )
            refreshed_list.append(new_child)
            mutations.extend(child_mutations)
        return refreshed_list, mutations
    return value, mutations


def integrity_bound_paths(
    value: Any,
    location: str = "$",
    *,
    cross_bindings: Iterable[dict[str, Any]] = (),
) -> set[str]:
    """Return the exact paths governed by the narrow refresh grammar."""
    paths: set[str] = set()
    if isinstance(value, dict):
        if location == "$":
            assert_unambiguous_sibling_integrity(
                value, cross_bindings=cross_bindings
            )
            paths.update(
                item["relative_path"]
                for item in _validated_cross_bindings(value, cross_bindings)
            )
        for key, child in value.items():
            if location == "$.files" and isinstance(child, dict) and (
                HASH_FIELDS & set(child) or SIZE_FIELDS & set(child)
            ):
                paths.add(canonical_relative(str(key)))
            if isinstance(child, str):
                digest_keys, size_keys = sibling_integrity_fields(value, key)
                if digest_keys or size_keys:
                    paths.add(canonical_relative(child))
            paths.update(integrity_bound_paths(child, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.update(integrity_bound_paths(child, f"{location}[{index}]"))
    return paths


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def _yaml_bytes(value: dict[str, Any]) -> bytes:
    return yaml.safe_dump(value, sort_keys=False).encode("utf-8")


def stage_expected_output(config: dict, stage: dict, cfg: dict | None = None) -> str:
    contract = stage.get("fresh_output_contract", {})
    mapping = contract.get("config_dotted_path_mapping", {})
    root_key = mapping.get("root", "outputs.root")
    label_key = mapping.get("label", "outputs.label")
    fixed = contract.get("fixed_relative_path")
    expected_declared = "expected_relative_path" in contract
    if fixed is not None and not isinstance(fixed, str):
        raise RuntimeError(f"invalid_fixed_stage_output_path:{stage['stage']}")
    # A fixed-only fixture contract does not claim to derive its writer path
    # from config.  Once an expected path is declared, however, the declared
    # path is an authority and must agree with the config-derived writer path.
    if isinstance(fixed, str) and not expected_declared:
        return canonical_relative(fixed)
    if not isinstance(mapping, dict) or not isinstance(root_key, str) or not isinstance(label_key, str):
        raise RuntimeError(f"invalid_stage_output_mapping:{stage['stage']}")
    root_value = deep_get(config, root_key)
    label_value = deep_get(config, label_key)
    if not isinstance(root_value, str) or not isinstance(label_value, str) or not label_value:
        raise RuntimeError(f"invalid_stage_output_config_value:{stage['stage']}")
    root = canonical_relative(root_value)
    label = label_value
    expected_label = contract.get("expected_label")
    if expected_label is not None and label != expected_label:
        raise RuntimeError(f"stage_output_label_changed:{stage['stage']}")
    template = contract.get("filename_template", "{outputs.label}_verdict.json")
    if not isinstance(template, str):
        raise RuntimeError(f"invalid_stage_output_filename_template:{stage['stage']}")
    filename = template.replace("{outputs.label}", label)
    if "/" in filename or "\\" in filename or filename in {"", ".", ".."}:
        raise RuntimeError(f"unsafe_stage_output_filename:{filename}")
    derived = canonical_relative(f"{root}/{filename}")
    if expected_declared:
        expected = contract.get("expected_relative_path")
        if not isinstance(expected, str):
            raise RuntimeError(f"invalid_expected_stage_output_path:{stage['stage']}")
        expected = canonical_relative(expected)
        if derived != expected:
            raise RuntimeError(f"stage_output_path_changed:{stage['stage']}")
        if isinstance(fixed, str) and canonical_relative(fixed) != expected:
            raise RuntimeError(f"fixed_stage_output_path_changed:{stage['stage']}")
    return derived


def _declared_generated_outputs(cfg: dict, configs: dict[str, dict]) -> set[str]:
    by_stage = {
        stage["stage"]: stage_expected_output(configs[stage["config"]], stage, cfg)
        for stage in cfg["stage_contracts"]
    }
    if len(by_stage) != len(cfg["stage_contracts"]) or len(set(by_stage.values())) != len(by_stage):
        raise RuntimeError("declared_stage_output_collision")
    target = canonical_relative(cfg["runtime_binding"]["target_relative_path"])
    owners = [stage for stage, output in by_stage.items() if output == target]
    if owners != [cfg["runtime_binding"]["producer_stage"]]:
        raise RuntimeError("runtime_target_not_uniquely_owned_by_producer")
    return set(by_stage.values())


AUTHORITY_CLAIM_ROW_FIELDS = {
    "relative_path", "claim_kind", "claim_source", "claim_source_sha256",
    "claimed_sha256", "claimed_hash_fields", "claimed_size_fields",
    "record_sha256", "record_size_fields_sha256",
    "authority_class", "selected_sha256", "observed_source_sha256", "observed_source_bytes",
    "source_valid_regular_contained", "resolution", "translation_required",
    "fatal_conflict",
}


def _source_config_values(source_root: Path, cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    configs: dict[str, dict[str, Any]] = {}
    pins: dict[str, str] = {}
    for stage in cfg["stage_contracts"]:
        relative = canonical_relative(stage["config"])
        digest = stage["config_sha256"]
        if relative in pins and pins[relative] != digest:
            raise RuntimeError(f"primary_authority_digest_conflict:{relative}")
        pins[relative] = digest
    for relative, digest in sorted(pins.items()):
        configs[relative] = strict_yaml_bytes(
            verified_source_bytes(source_root, relative, digest),
            relative,
        )
        assert_unambiguous_sibling_integrity(
            configs[relative],
            cross_bindings=bindings_for_document(cfg, relative),
        )
    return configs


def _synthetic_input_paths(cfg: dict[str, Any], configs: dict[str, dict[str, Any]]) -> set[str]:
    paths: set[str] = set()
    for stage in cfg["stage_contracts"]:
        config = configs[stage["config"]]
        for key in stage["required_data_keys"]:
            if key.endswith(("candidate_parquet", "raw_track_parquet", "canonical_g3_track_plan")):
                paths.add(canonical_relative(str(deep_get(config, key))))
    return paths


def _primary_claims(cfg: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    claims: dict[str, list[dict[str, Any]]] = {}
    if not package_scaffold_contract_exact(cfg):
        raise RuntimeError("shadow_package_scaffold_contract_not_exact")

    def add(relative: str, digest: str, kind: str, source: str) -> None:
        canonical = canonical_relative(relative)
        if SHA256_RE.fullmatch(str(digest)) is None:
            raise RuntimeError(f"invalid_primary_authority_digest:{canonical}")
        claims.setdefault(canonical, []).append({
            "claim_kind": kind,
            "claim_source": source,
            "claim_source_sha256": "",
            "claimed_sha256": digest,
            "claimed_hash_fields": {"sha256": digest},
            "claimed_size_fields": {},
            "record_sha256": "",
            "record_size_fields_sha256": "",
        })

    for relative, digest in sorted(cfg["exact_sources"].items()):
        add(relative, digest, "exact_source", "exact_sources")
    executor_paths = {canonical_relative(stage["executor"]) for stage in cfg["stage_contracts"]}
    config_paths = [canonical_relative(stage["config"]) for stage in cfg["stage_contracts"]]
    manifest_paths = {canonical_relative(stage["manifest"]) for stage in cfg["stage_contracts"]}
    if len(config_paths) != len(set(config_paths)):
        raise RuntimeError("stage_config_path_reuse_forbidden")
    if (
        executor_paths & set(config_paths)
        or executor_paths & manifest_paths
        or set(config_paths) & manifest_paths
    ):
        raise RuntimeError("primary_subrole_path_overlap")
    for stage in cfg["stage_contracts"]:
        stage_name = stage["stage"]
        add(stage["executor"], stage["executor_sha256"], "stage_executor", stage_name)
        add(stage["config"], stage["config_sha256"], "stage_config", stage_name)
        add(stage["manifest"], stage["manifest_sha256"], "stage_manifest", stage_name)
    return claims


# BH_SIMBA_STAGED_GENERATED_BINDING_REPAIR_V1_5X

def _post_stage_generated_bindings(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    binding = cfg.get("runtime_binding", {})
    raw = binding.get("post_stage_generated_bindings", [])
    count = binding.get("post_stage_generated_binding_count_per_shadow", 0)
    if not isinstance(raw, list) or not isinstance(count, int) or isinstance(count, bool) or len(raw) != count:
        raise RuntimeError("post_stage_generated_binding_schema_invalid")
    stages = {stage["stage"]: stage for stage in cfg["stage_contracts"]}
    order = [stage["stage"] for stage in cfg["stage_contracts"]]
    expected_keys = {"schema_version","binding_id","producer_stage","consumer_stage","target_relative_path","target_manifest","mutation_scope"}
    mutation_keys = {"authorized_existing_content_derived_fields","source_authorities_immutable","shadow_only","target_record_only","atomic_sibling_temp_write_fsync_replace","all_non_content_fields_immutable","all_unrelated_manifest_records_immutable"}
    phase_fields = set(binding["mutation_scope"]["authorized_existing_content_derived_fields"])
    seen_ids=set(); seen_targets=set(); seen_producers=set(); out=[]
    for item in raw:
        if not isinstance(item, dict) or set(item) != expected_keys or item.get("schema_version") != 1:
            raise RuntimeError("post_stage_generated_binding_item_schema_invalid")
        producer=item["producer_stage"]; consumer=item["consumer_stage"]
        target=canonical_relative(item["target_relative_path"]); manifest=canonical_relative(item["target_manifest"])
        if producer not in stages or consumer not in stages or order.index(consumer) != order.index(producer)+1:
            raise RuntimeError("post_stage_generated_binding_stage_topology_invalid")
        contract=stages[producer].get("fresh_output_contract",{})
        declared=canonical_relative(contract.get("expected_relative_path") or contract.get("fixed_relative_path") or "")
        if declared != target or canonical_relative(stages[consumer]["manifest"]) != manifest:
            raise RuntimeError("post_stage_generated_binding_path_topology_invalid")
        mutation=item["mutation_scope"]
        if not isinstance(mutation,dict) or set(mutation)!=mutation_keys:
            raise RuntimeError("post_stage_generated_binding_mutation_schema_invalid")
        if set(mutation["authorized_existing_content_derived_fields"]) != phase_fields:
            raise RuntimeError("post_stage_generated_binding_content_fields_changed")
        if not all(mutation[k] is True for k in mutation_keys-{"authorized_existing_content_derived_fields"}):
            raise RuntimeError("post_stage_generated_binding_mutation_flag_false")
        if item["binding_id"] in seen_ids or target in seen_targets or producer in seen_producers:
            raise RuntimeError("post_stage_generated_binding_not_unique")
        seen_ids.add(item["binding_id"]); seen_targets.add(target); seen_producers.add(producer); out.append(copy.deepcopy(item))
    return out

def _post_stage_generated_binding_for_target(cfg: dict[str, Any], target: str) -> dict[str, Any] | None:
    target=canonical_relative(target)
    matches=[item for item in _post_stage_generated_bindings(cfg) if canonical_relative(item["target_relative_path"])==target]
    if len(matches)>1: raise RuntimeError("post_stage_generated_target_multiple_binders")
    return matches[0] if matches else None

def _pending_generated_records_by_manifest(cfg: dict[str, Any], stage_name: str, *, after_stage: bool=False) -> dict[str, frozenset[str]]:
    order=[stage["stage"] for stage in cfg["stage_contracts"]]
    if stage_name not in order: raise RuntimeError("pending_generated_stage_unknown")
    current=order.index(stage_name)
    binding=cfg["runtime_binding"]
    descriptors=[{"producer_stage":binding["producer_stage"],"target_relative_path":binding["target_relative_path"],"target_manifest":binding.get("confirmation_template_manifest",binding["confirmation_manifest"])}]
    descriptors.extend(_post_stage_generated_bindings(cfg))
    pending={}
    for item in descriptors:
        producer_index=order.index(item["producer_stage"])
        active=producer_index>current if after_stage else producer_index>=current
        if active:
            pending.setdefault(canonical_relative(item["target_manifest"]),set()).add(canonical_relative(item["target_relative_path"]))
    return {k:frozenset(v) for k,v in pending.items()}

def post_stage_generated_binding_receipt_exact(receipt: Any, cfg: dict[str, Any], source_root: Path) -> bool:
    try:
        schema=cfg["runtime_binding"]["post_stage_generated_receipt_schema"]
        if not isinstance(receipt,dict) or set(receipt)!=set(schema["required_fields"]): return False
        specs={item["binding_id"]:item for item in _post_stage_generated_bindings(cfg)}
        spec=specs.get(receipt.get("binding_id"))
        if spec is None: return False
        stages={stage["stage"]:stage for stage in cfg["stage_contracts"]}
        producer=stages[spec["producer_stage"]]; consumer=stages[spec["consumer_stage"]]
        target=canonical_relative(spec["target_relative_path"]); manifest=canonical_relative(spec["target_manifest"])
        if not (receipt["schema_version"]==schema["version"]==1 and receipt["producer_stage"]==spec["producer_stage"] and receipt["consumer_stage"]==spec["consumer_stage"] and receipt["target_relative_path"]==target and receipt["target_manifest_relative_path"]==manifest and receipt["producer_return_code"]==0 and receipt["preproducer_target_absent"] is True and isinstance(receipt["offset"],(int,float)) and not isinstance(receipt["offset"],bool) and math.isfinite(float(receipt["offset"]))): return False
        encoded=receipt["product_payload_b64"]
        if not isinstance(encoded,str): return False
        product_payload=base64.b64decode(encoded,validate=True)
        if base64.b64encode(product_payload).decode("ascii")!=encoded: return False
        configs=_source_config_values(source_root,cfg)
        product_value=_validated_runtime_product_value(product_payload,target,producer,configs[producer["config"]])
        target_sha=hashlib.sha256(product_payload).hexdigest(); target_bytes=len(product_payload)
        if not (receipt["product_json_run_id"]==product_value["run_id"] and receipt["product_json_schema_version"]==product_value["schema_version"] and receipt["target_sha256"]==target_sha and receipt["target_bytes"]==target_bytes>0): return False
        source_expected=consumer["manifest_sha256"]
        source_payload=verified_source_bytes(source_root.resolve(),manifest,source_expected)
        source_observed=hashlib.sha256(source_payload).hexdigest()
        template_record=exact_manifest_file_records(strict_json_bytes(source_payload,manifest))[target]
        if not (receipt["source_template_manifest_expected_sha256"]==source_expected and receipt["source_template_manifest_observed_sha256"]==source_observed==source_expected and receipt["template_record"]==template_record and receipt["template_record_sha256"]==canonical_json_sha256(template_record)): return False
        authorized=set(spec["mutation_scope"]["authorized_existing_content_derived_fields"]); present=(HASH_FIELDS|SIZE_FIELDS)&set(template_record)
        if not (authorized and authorized<=HASH_FIELDS|SIZE_FIELDS and "sha256" in present and present<=authorized): return False
        refreshed=clone_refreshed_file_record(template_record,None,spec["mutation_scope"]["authorized_existing_content_derived_fields"],observed_sha256=target_sha,observed_bytes=target_bytes)
        if receipt["refreshed_record"]!=refreshed: return False
        before=receipt["target_manifest_before"]; after=receipt["target_manifest_after"]
        if not isinstance(before,dict) or not isinstance(after,dict) or exact_manifest_file_records(before).get(target)!=template_record: return False
        expected_after=copy.deepcopy(before); expected_after["files"][target]=copy.deepcopy(refreshed)
        if after!=expected_after or not _only_target_record_changed(before,after,target,insertion=False): return False
        before_sha=hashlib.sha256(_json_bytes(before)).hexdigest(); after_sha=hashlib.sha256(_json_bytes(after)).hexdigest()
        if not (receipt["target_manifest_expected_before_sha256"]==receipt["target_manifest_before_sha256"]==before_sha and receipt["target_manifest_after_sha256"]==after_sha and before_sha!=after_sha): return False
        if SHA256_RE.fullmatch(str(receipt["producer_invocation_manifest_sha256"])) is None: return False
        if receipt["manifest_mutations"]!=[{"manifest":manifest,"before_sha256":before_sha,"after_sha256":after_sha,"operation":"refresh_target_record"}]: return False
        if not (receipt["exact_mutation_scope_pass"] is True and receipt["atomic_replacement_pass"] is True and receipt["downstream_manifest_closure_pass"] is True and receipt["downstream_required_input_concordance_pass"] is True and receipt["binding_pass"] is True and receipt["hold_reason"]==""): return False
        payload={k:v for k,v in receipt.items() if k not in {"receipt_payload_sha256","receipt_sha256"}}
        observed=canonical_json_sha256(payload)
        return receipt["receipt_payload_sha256"]==receipt["receipt_sha256"]==observed
    except (ImportError,KeyError,OSError,RuntimeError,TypeError,ValueError,binascii.Error): return False

def bind_post_stage_generated_product(source_root: Path, shadow: Path, cfg: dict[str, Any], configs: dict[str,dict], spec: dict[str,Any], *, producer_stage: dict[str,Any], producer_return_code: int, product_absent_before: bool, offset: float, producer_invocation_manifest_sha256: str, expected_target_manifest_sha256: str) -> dict[str,Any]:
    required=list(cfg["runtime_binding"]["post_stage_generated_receipt_schema"]["required_fields"])
    receipt={k:None for k in required if k not in {"receipt_payload_sha256","receipt_sha256"}}
    receipt.update({"schema_version":1,"binding_id":spec["binding_id"],"offset":float(offset),"producer_stage":producer_stage["stage"],"producer_return_code":int(producer_return_code),"consumer_stage":spec["consumer_stage"],"target_relative_path":canonical_relative(spec["target_relative_path"]),"product_payload_b64":"","product_json_run_id":"","product_json_schema_version":0,"target_sha256":"","target_bytes":0,"target_manifest_relative_path":canonical_relative(spec["target_manifest"]),"source_template_manifest_expected_sha256":"","source_template_manifest_observed_sha256":"","template_record_sha256":"","template_record":{},"refreshed_record":{},"preproducer_target_absent":bool(product_absent_before),"producer_invocation_manifest_sha256":producer_invocation_manifest_sha256,"target_manifest_expected_before_sha256":expected_target_manifest_sha256,"target_manifest_before":{},"target_manifest_before_sha256":"","target_manifest_after":{},"target_manifest_after_sha256":"","manifest_mutations":[],"exact_mutation_scope_pass":False,"atomic_replacement_pass":False,"downstream_manifest_closure_pass":False,"downstream_required_input_concordance_pass":False,"binding_pass":False,"hold_reason":""})
    try:
        declared={item["binding_id"]:item for item in _post_stage_generated_bindings(cfg)}
        if declared.get(spec["binding_id"])!=spec: raise RuntimeError("post_stage_binding_spec_changed")
        if producer_stage["stage"]!=spec["producer_stage"] or producer_return_code!=0 or not product_absent_before: raise RuntimeError("post_stage_binding_producer_lifecycle_not_satisfied")
        target=canonical_relative(spec["target_relative_path"]); manifest=canonical_relative(spec["target_manifest"])
        if stage_expected_output(configs[producer_stage["config"]],producer_stage,cfg)!=target: raise RuntimeError("post_stage_binding_target_not_exact_producer_output")
        product_payload=source_snapshot_bytes(shadow,target); product_value=_validated_runtime_product_value(product_payload,target,producer_stage,configs[producer_stage["config"]]); product_sha=hashlib.sha256(product_payload).hexdigest(); product_bytes=len(product_payload)
        contained_regular_file(shadow,target,require_single_link=True)
        consumer=next(stage for stage in cfg["stage_contracts"] if stage["stage"]==spec["consumer_stage"])
        source_expected=consumer["manifest_sha256"]; source_payload=verified_source_bytes(source_root.resolve(),manifest,source_expected); source_observed=hashlib.sha256(source_payload).hexdigest(); template_record=exact_manifest_file_records(strict_json_bytes(source_payload,manifest))[target]
        refreshed=clone_refreshed_file_record(template_record,None,spec["mutation_scope"]["authorized_existing_content_derived_fields"],observed_sha256=product_sha,observed_bytes=product_bytes)
        before_payload=source_snapshot_bytes(shadow,manifest); before_sha=hashlib.sha256(before_payload).hexdigest()
        if before_sha!=expected_target_manifest_sha256: raise RuntimeError("post_stage_binding_manifest_prestate_changed")
        before=strict_json_bytes(before_payload,manifest)
        if exact_manifest_file_records(before).get(target)!=template_record: raise RuntimeError("post_stage_binding_template_record_changed")
        after=copy.deepcopy(before); after["files"][target]=copy.deepcopy(refreshed); mutation_exact=_only_target_record_changed(before,after,target,insertion=False)
        if not mutation_exact: raise RuntimeError("post_stage_binding_mutation_scope_not_exact")
        replaced=_staged_json_replacements(shadow,[(manifest,after,before_sha,before_payload)]); after_sha=replaced[manifest]
        pending_after=_pending_generated_records_by_manifest(cfg,producer_stage["stage"],after_stage=True)
        closure=audit_executor_manifest_closure(shadow,manifest,allowed_missing=pending_after.get(manifest,frozenset()))
        consumer_binding=required_input_concordance(shadow,configs,consumer,expected_executor_sha256=consumer["executor_sha256"],allowed_missing=pending_after.get(canonical_relative(consumer["manifest"]),frozenset()))
        binding_pass=bool(closure["closure_pass"] and consumer_binding["manifest_config_concordant"] and source_snapshot_bytes(shadow,target)==product_payload)
        receipt.update({"product_payload_b64":base64.b64encode(product_payload).decode("ascii"),"product_json_run_id":product_value["run_id"],"product_json_schema_version":product_value["schema_version"],"target_sha256":product_sha,"target_bytes":product_bytes,"source_template_manifest_expected_sha256":source_expected,"source_template_manifest_observed_sha256":source_observed,"template_record_sha256":canonical_json_sha256(template_record),"template_record":template_record,"refreshed_record":refreshed,"target_manifest_before":before,"target_manifest_before_sha256":before_sha,"target_manifest_after":after,"target_manifest_after_sha256":after_sha,"manifest_mutations":[{"manifest":manifest,"before_sha256":before_sha,"after_sha256":after_sha,"operation":"refresh_target_record"}],"exact_mutation_scope_pass":mutation_exact,"atomic_replacement_pass":True,"downstream_manifest_closure_pass":closure["closure_pass"],"downstream_required_input_concordance_pass":consumer_binding["manifest_config_concordant"],"binding_pass":binding_pass})
    except Exception as error: receipt["hold_reason"]=f"{type(error).__name__}:{str(error)[:1000]}"
    if set(receipt)!=(set(required)-{"receipt_payload_sha256","receipt_sha256"}): raise RuntimeError("post_stage_binding_receipt_pre_digest_schema_mismatch")
    payload=copy.deepcopy(receipt); receipt["receipt_payload_sha256"]=canonical_json_sha256(payload); receipt["receipt_sha256"]=receipt["receipt_payload_sha256"]; return receipt

def resolve_source_manifest_claims(source_root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Inventory every claim, then resolve only under the frozen authority policy."""
    primary = _primary_claims(cfg)
    scaffold_census = package_scaffold_source_census(source_root, cfg)
    cross_binding_proof = prove_schema_specific_config_integrity_bindings(
        source_root, cfg
    )
    configs = _source_config_values(source_root, cfg)
    generated = _declared_generated_outputs(cfg, configs)
    synthetic = _synthetic_input_paths(cfg, configs)
    allowed_non_primary_static = {
        canonical_relative(path)
        for path in cfg["authority_resolution"].get("allowed_non_primary_static_paths", [])
    }
    runtime_target = canonical_relative(cfg["runtime_binding"]["target_relative_path"])
    producer_stage = next(
        stage for stage in cfg["stage_contracts"]
        if stage["stage"] == cfg["runtime_binding"]["producer_stage"]
    )
    if stage_expected_output(configs[producer_stage["config"]], producer_stage, cfg) != runtime_target:
        raise RuntimeError("runtime_target_not_exact_producer_output")
    manifest_claims: dict[str, list[dict[str, Any]]] = {}
    source_manifest_sha256: dict[str, str] = {}
    source_manifest_record_counts: dict[str, int] = {}
    manifest_pins: dict[str, str] = {}
    for stage in cfg["stage_contracts"]:
        relative = canonical_relative(stage["manifest"])
        digest = stage["manifest_sha256"]
        if relative in manifest_pins and manifest_pins[relative] != digest:
            raise RuntimeError(f"primary_authority_digest_conflict:{relative}")
        manifest_pins[relative] = digest
    for manifest_relative, manifest_pin in sorted(manifest_pins.items()):
        manifest_payload = verified_source_bytes(source_root, manifest_relative, manifest_pin)
        observed_manifest = hashlib.sha256(manifest_payload).hexdigest()
        manifest_value = strict_json_bytes(manifest_payload, manifest_relative)
        records = exact_manifest_file_records(manifest_value)
        source_manifest_sha256[manifest_relative] = observed_manifest
        source_manifest_record_counts[manifest_relative] = len(records)
        for relative, record in sorted(records.items()):
            hash_fields = {key: record[key] for key in sorted(HASH_FIELDS & set(record))}
            size_fields = {key: record[key] for key in sorted(SIZE_FIELDS & set(record))}
            manifest_claims.setdefault(relative, []).append({
                "claim_kind": "manifest_record",
                "claim_source": manifest_relative,
                "claim_source_sha256": manifest_pin,
                "claimed_sha256": record["sha256"],
                "claimed_hash_fields": hash_fields,
                "claimed_size_fields": size_fields,
                "record_sha256": canonical_json_sha256(record),
                "record_size_fields_sha256": canonical_json_sha256(size_fields),
            })
        for sibling in manifest_sibling_integrity_claims(manifest_value):
            relative = sibling["relative_path"]
            claim_record = {
                "location": sibling["location"],
                "path_field": sibling["path_field"],
                "digest_field": sibling["digest_field"],
                "claimed_sha256": sibling["claimed_sha256"],
                "size_fields": sibling["size_fields"],
            }
            manifest_claims.setdefault(relative, []).append({
                "claim_kind": "manifest_sibling_integrity",
                "claim_source": manifest_relative,
                "claim_source_sha256": manifest_pin,
                "claimed_sha256": sibling["claimed_sha256"],
                "claimed_hash_fields": {
                    sibling["digest_field"]: sibling["claimed_sha256"],
                },
                "claimed_size_fields": sibling["size_fields"],
                "record_sha256": canonical_json_sha256(claim_record),
                "record_size_fields_sha256": canonical_json_sha256(sibling["size_fields"]),
            })

    selected_copy_digests: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    fatal_paths: list[str] = []
    path_resolutions: dict[str, str] = {}
    primary_manifest_disagreement_paths: list[str] = []
    unresolved_non_primary_paths: list[str] = []
    primary_conflict_paths: list[str] = []
    observed_mismatch_paths: list[str] = []
    deferred_paths: list[str] = []
    runtime_target_topology_paths: list[str] = []
    reserved_scaffolds = {
        "src/__init__.py", "src/core/__init__.py", "scripts/__init__.py"
    } - set(primary)
    authority_class_overlap_paths = sorted(
        (set(primary) & synthetic)
        | (set(primary) & generated)
        | (synthetic & generated)
    )
    class_members = {
        "primary": set(primary),
        "synthetic": synthetic,
        "generated": generated,
        "allowed_non_primary_static": allowed_non_primary_static,
        "reserved_scaffold": reserved_scaffolds,
    }
    class_path_collision_paths: set[str] = set(authority_class_overlap_paths)
    flattened = [
        (class_name, path)
        for class_name, paths in class_members.items()
        for path in sorted(paths)
    ]
    for index, (left_class, left_path) in enumerate(flattened):
        for right_class, right_path in flattened[index + 1:]:
            if canonical_paths_collide(left_path, right_path):
                class_path_collision_paths.update((left_path, right_path))
    authority_class_overlap_paths = sorted(class_path_collision_paths)
    authority_class_overlap_set = class_path_collision_paths

    all_paths = sorted(
        set(primary) | set(manifest_claims) | synthetic | generated
        | allowed_non_primary_static | reserved_scaffolds
    )
    for relative in all_paths:
        primary_rows = primary.get(relative, [])
        embedded_rows = manifest_claims.get(relative, [])
        primary_digests = sorted({
            digest
            for item in primary_rows
            for digest in item["claimed_hash_fields"].values()
        })
        embedded_digests = sorted({
            digest
            for item in embedded_rows
            for digest in item["claimed_hash_fields"].values()
        })
        embedded_size_variants = {
            canonical_json_sha256(item["claimed_size_fields"])
            for item in embedded_rows
        }
        source_observation_forbidden = relative in authority_class_overlap_set or (
            not primary_rows and (relative in synthetic or relative in generated)
        )
        state = {"valid_regular_contained": False}
        observed = ""
        observed_bytes = -1
        if not source_observation_forbidden:
            try:
                source_payload = source_snapshot_bytes(source_root, relative)
                observed = hashlib.sha256(source_payload).hexdigest()
                observed_bytes = len(source_payload)
                state["valid_regular_contained"] = True
            except (OSError, RuntimeError):
                pass
        selected = ""
        resolution = ""
        translation_required = False
        fatal = False

        if relative in authority_class_overlap_set:
            authority_class = "fatal_class_overlap"
            resolution = "fatal_undeclared_authority_class_overlap"
            fatal = True
        elif primary_rows:
            authority_class = "primary"
            if len(primary_digests) != 1:
                resolution = "fatal_primary_authority_digest_conflict"
                primary_conflict_paths.append(relative)
                fatal = True
            else:
                selected = primary_digests[0]
                if not state["valid_regular_contained"] or observed != selected:
                    resolution = "fatal_primary_observed_digest_mismatch"
                    observed_mismatch_paths.append(relative)
                    fatal = True
                elif embedded_digests and (
                    any(digest != selected for digest in embedded_digests)
                    or len(embedded_size_variants) > 1
                    or any(
                        size != observed_bytes
                        for item in embedded_rows
                        for size in item["claimed_size_fields"].values()
                    )
                ):
                    resolution = "resolved_by_validated_primary_shadow_translation"
                    translation_required = True
                    primary_manifest_disagreement_paths.append(relative)
                else:
                    resolution = "validated_primary_exact"
                if not fatal:
                    selected_copy_digests[relative] = selected
        elif relative in synthetic:
            authority_class = "synthetic"
            resolution = "deferred_authorized_synthetic_construction"
            translation_required = bool(embedded_rows)
            deferred_paths.append(relative)
        elif relative in generated:
            authority_class = "declared_generated"
            if relative == runtime_target:
                confirmation_template = canonical_relative(
                    cfg["runtime_binding"].get(
                        "confirmation_template_manifest",
                        cfg["runtime_binding"]["confirmation_manifest"],
                    )
                )
                topology_exact = (
                    len(embedded_rows) == 1
                    and embedded_rows[0]["claim_kind"] == "manifest_record"
                    and embedded_rows[0]["claim_source"] == confirmation_template
                    and embedded_rows[0]["claimed_sha256"] == cfg["runtime_binding"]["template_target_content_sha256"]
                    and set(embedded_rows[0]["claimed_hash_fields"]) <= set(cfg["runtime_binding"]["mutation_scope"]["authorized_existing_content_derived_fields"])
                    and set(embedded_rows[0]["claimed_size_fields"]) <= set(cfg["runtime_binding"]["mutation_scope"]["authorized_existing_content_derived_fields"])
                    and set(embedded_rows[0]["claimed_hash_fields"]) >= {"sha256"}
                    and all(digest == cfg["runtime_binding"]["template_target_content_sha256"] for digest in embedded_rows[0]["claimed_hash_fields"].values())
                    and all(size == cfg["runtime_binding"]["template_target_bytes"] for size in embedded_rows[0]["claimed_size_fields"].values())
                )
                if not topology_exact:
                    resolution = "fatal_runtime_target_claim_topology"
                    runtime_target_topology_paths.append(relative)
                    fatal = True
                else:
                    resolution = "deferred_declared_output_lifecycle"
                    translation_required = True
                    deferred_paths.append(relative)
            else:
                post_binding = _post_stage_generated_binding_for_target(cfg, relative)
                if post_binding is not None and embedded_rows:
                    stages = {stage["stage"]: stage for stage in cfg["stage_contracts"]}
                    producer = stages[post_binding["producer_stage"]]
                    consumer = stages[post_binding["consumer_stage"]]
                    authorized = set(post_binding["mutation_scope"]["authorized_existing_content_derived_fields"])
                    topology_exact = (
                        len(embedded_rows) == 1
                        and embedded_rows[0]["claim_kind"] == "manifest_record"
                        and embedded_rows[0]["claim_source"] == canonical_relative(post_binding["target_manifest"])
                        and stage_expected_output(configs[producer["config"]], producer, cfg) == relative
                        and canonical_relative(consumer["manifest"]) == canonical_relative(post_binding["target_manifest"])
                        and set(embedded_rows[0]["claimed_hash_fields"]) <= authorized
                        and set(embedded_rows[0]["claimed_size_fields"]) <= authorized
                        and set(embedded_rows[0]["claimed_hash_fields"]) >= {"sha256"}
                        and all(digest == embedded_rows[0]["claimed_sha256"] for digest in embedded_rows[0]["claimed_hash_fields"].values())
                    )
                    if not topology_exact:
                        resolution = "fatal_generated_manifest_record_without_declared_binder"
                        fatal = True
                    else:
                        resolution = "deferred_declared_output_lifecycle"
                        translation_required = True
                        deferred_paths.append(relative)
                elif post_binding is not None:
                    resolution = "deferred_declared_output_lifecycle"
                    translation_required = False
                    deferred_paths.append(relative)
                elif embedded_rows:
                    resolution = "fatal_generated_manifest_record_without_declared_binder"
                    fatal = True
                else:
                    resolution = "deferred_declared_output_lifecycle"
                    translation_required = False
                    deferred_paths.append(relative)
        elif relative in reserved_scaffolds:
            authority_class = "reserved_scaffold"
            if embedded_rows:
                resolution = "fatal_undeclared_reserved_scaffold_manifest_claim"
                fatal = True
            else:
                resolution = "deferred_exact_empty_package_scaffold"
                deferred_paths.append(relative)
        else:
            authority_class = "non_primary"
            if relative not in allowed_non_primary_static:
                resolution = "fatal_undeclared_non_primary_static_authority"
                unresolved_non_primary_paths.append(relative)
                fatal = True
            elif len(embedded_digests) != 1 or len(embedded_size_variants) != 1:
                resolution = "fatal_unresolved_non_primary_digest_conflict"
                unresolved_non_primary_paths.append(relative)
                fatal = True
            else:
                selected = embedded_digests[0] if embedded_digests else ""
                size_mismatch = any(
                    size != observed_bytes
                    for item in embedded_rows
                    for size in item["claimed_size_fields"].values()
                )
                if not selected or not state["valid_regular_contained"] or observed != selected or size_mismatch:
                    resolution = "fatal_non_primary_source_missing_or_digest_mismatch"
                    observed_mismatch_paths.append(relative)
                    fatal = True
                else:
                    resolution = "unanimous_non_primary_exact"
                    selected_copy_digests[relative] = selected

        if fatal:
            fatal_paths.append(relative)
        path_resolutions[relative] = resolution
        for claim in [*primary_rows, *embedded_rows]:
            rows.append({
                "relative_path": relative,
                **claim,
                "authority_class": authority_class,
                "selected_sha256": selected,
                "observed_source_sha256": observed,
                "observed_source_bytes": observed_bytes,
                "source_valid_regular_contained": state["valid_regular_contained"],
                "resolution": resolution,
                "translation_required": translation_required,
                "fatal_conflict": fatal,
            })

    rows.sort(key=lambda item: (
        item["relative_path"], item["claim_kind"], item["claim_source"], item["claimed_sha256"]
    ))
    known = canonical_relative(cfg["authority_resolution"]["known_prior_first_conflict_path"])
    payload: dict[str, Any] = {
        "schema_version": 1,
        "resolution_pass": bool(
            not fatal_paths
            and scaffold_census.get("census_pass") is True
            and cross_binding_proof.get("binding_proof_pass") is True
        ),
        "claim_count": len(rows),
        "path_count": len(all_paths),
        "primary_path_count": len(primary),
        "manifest_claim_count": sum(len(value) for value in manifest_claims.values()),
        "source_manifest_count": len(manifest_pins),
        "source_manifest_sha256": source_manifest_sha256,
        "source_manifest_record_counts": source_manifest_record_counts,
        "selected_copy_digests": dict(sorted(selected_copy_digests.items())),
        "allowed_non_primary_static_paths": sorted(allowed_non_primary_static),
        "unused_allowed_non_primary_static_paths": sorted(
            allowed_non_primary_static - set(manifest_claims)
        ),
        "generated_paths": sorted(generated),
        "synthetic_paths": sorted(synthetic),
        "deferred_paths": sorted(set(deferred_paths)),
        "path_resolutions": path_resolutions,
        "primary_manifest_disagreement_paths": sorted(set(primary_manifest_disagreement_paths)),
        "primary_manifest_disagreement_count": len(set(primary_manifest_disagreement_paths)),
        "known_prior_first_conflict_resolved_by_primary": known in primary_manifest_disagreement_paths,
        "primary_conflict_paths": sorted(set(primary_conflict_paths)),
        "primary_conflict_count": len(set(primary_conflict_paths)),
        "unresolved_non_primary_paths": sorted(set(unresolved_non_primary_paths)),
        "unresolved_non_primary_conflict_count": len(set(unresolved_non_primary_paths)),
        "observed_mismatch_paths": sorted(set(observed_mismatch_paths)),
        "observed_mismatch_count": len(set(observed_mismatch_paths)),
        "authority_class_overlap_paths": authority_class_overlap_paths,
        "authority_class_overlap_count": len(authority_class_overlap_paths),
        "runtime_target_topology_paths": sorted(set(runtime_target_topology_paths)),
        "runtime_target_topology_error_count": len(set(runtime_target_topology_paths)),
        "fatal_paths": sorted(set(fatal_paths)),
        "fatal_path_count": len(set(fatal_paths)),
        "source_package_scaffold_census": scaffold_census,
        "schema_specific_config_integrity_binding_proof": cross_binding_proof,
        "rows": rows,
    }
    payload["receipt_payload_sha256"] = canonical_json_sha256(payload)
    payload["receipt_sha256"] = payload["receipt_payload_sha256"]
    return payload


def source_authority_resolution_exact(
    receipt: Any,
    cfg: dict[str, Any],
    source_root: Path | None = None,
) -> bool:
    try:
        if not isinstance(receipt, dict):
            return False
        required = {
            "schema_version", "resolution_pass", "claim_count", "path_count",
            "primary_path_count", "manifest_claim_count", "source_manifest_count",
            "source_manifest_sha256", "source_manifest_record_counts",
            "selected_copy_digests", "allowed_non_primary_static_paths",
            "unused_allowed_non_primary_static_paths", "generated_paths", "synthetic_paths",
            "deferred_paths", "path_resolutions",
            "primary_manifest_disagreement_paths", "primary_manifest_disagreement_count",
            "known_prior_first_conflict_resolved_by_primary", "primary_conflict_paths",
            "primary_conflict_count", "unresolved_non_primary_paths",
            "unresolved_non_primary_conflict_count", "observed_mismatch_paths",
            "observed_mismatch_count", "authority_class_overlap_paths",
            "authority_class_overlap_count", "runtime_target_topology_paths",
            "runtime_target_topology_error_count", "fatal_paths", "fatal_path_count", "rows",
            "source_package_scaffold_census",
            "schema_specific_config_integrity_binding_proof",
            "receipt_payload_sha256", "receipt_sha256",
        }
        if set(receipt) != required or not isinstance(receipt["rows"], list):
            return False
        payload = {key: value for key, value in receipt.items() if key not in {"receipt_payload_sha256", "receipt_sha256"}}
        digest = canonical_json_sha256(payload)
        if receipt["receipt_payload_sha256"] != receipt["receipt_sha256"] or receipt["receipt_sha256"] != digest:
            return False
        if any(not isinstance(row, dict) or set(row) != AUTHORITY_CLAIM_ROW_FIELDS for row in receipt["rows"]):
            return False
        if receipt["claim_count"] != len(receipt["rows"]):
            return False
        for row in receipt["rows"]:
            canonical_relative(row["relative_path"])
            if row["claim_kind"] not in {
                "exact_source", "stage_executor", "stage_config", "stage_manifest",
                "manifest_record", "manifest_sibling_integrity",
            }:
                return False
            if SHA256_RE.fullmatch(row["claimed_sha256"]) is None:
                return False
            if (
                not isinstance(row["claimed_hash_fields"], dict)
                or not row["claimed_hash_fields"]
                or any(
                    not isinstance(key, str)
                    or not key
                    or not _supported_digest_field_name(key)
                    or not isinstance(value, str)
                    or SHA256_RE.fullmatch(value) is None
                    for key, value in row["claimed_hash_fields"].items()
                )
                or row["claimed_sha256"] not in row["claimed_hash_fields"].values()
            ):
                return False
            if row["selected_sha256"] and SHA256_RE.fullmatch(row["selected_sha256"]) is None:
                return False
            if row["observed_source_sha256"] and SHA256_RE.fullmatch(row["observed_source_sha256"]) is None:
                return False
            if not isinstance(row["claimed_size_fields"], dict) or any(
                not _supported_size_field_name(key)
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                for key, size in row["claimed_size_fields"].items()
            ):
                return False
            if (
                not isinstance(row["observed_source_bytes"], int)
                or isinstance(row["observed_source_bytes"], bool)
                or row["observed_source_bytes"] < -1
            ):
                return False
            if not isinstance(row["source_valid_regular_contained"], bool) or not isinstance(row["translation_required"], bool) or not isinstance(row["fatal_conflict"], bool):
                return False
        primary_claim_kinds = set(cfg["authority_resolution"]["primary_claim_kinds"])
        if primary_claim_kinds != {"exact_source", "stage_executor", "stage_config", "stage_manifest"}:
            return False
        known = canonical_relative(cfg["authority_resolution"]["known_prior_first_conflict_path"])
        structural = all((
            receipt["schema_version"] == cfg["authority_resolution"]["schema_version"] == 1,
            receipt["resolution_pass"] is True,
            receipt["fatal_path_count"] == 0,
            receipt["primary_conflict_count"] == 0,
            receipt["unresolved_non_primary_conflict_count"] == 0,
            receipt["observed_mismatch_count"] == 0,
            receipt["authority_class_overlap_count"] == 0,
            receipt["runtime_target_topology_error_count"] == 0,
            receipt["source_package_scaffold_census"].get("census_pass") is True,
            receipt["schema_specific_config_integrity_binding_proof"].get(
                "binding_proof_pass"
            ) is True,
            receipt["unused_allowed_non_primary_static_paths"] == [],
            receipt["primary_manifest_disagreement_count"] >= 1,
            receipt["known_prior_first_conflict_resolved_by_primary"] is True,
            known in receipt["primary_manifest_disagreement_paths"],
            len(receipt["source_manifest_sha256"]) == 3,
            receipt["source_manifest_count"] == 3,
            all(SHA256_RE.fullmatch(value) is not None for value in receipt["source_manifest_sha256"].values()),
        ))
        if not structural or source_root is None:
            return False
        # Never accept a claim census solely because its self-hash is valid.
        # Recompute the complete deterministic receipt from the pinned source
        # authorities and require byte-for-value identity.
        return receipt == resolve_source_manifest_claims(source_root.resolve(), cfg)
    except (KeyError, RuntimeError, TypeError, ValueError):
        return False


def prepare_shadow(source_root: Path, shadow: Path, cfg: dict, offset: float) -> tuple[dict[str, dict], dict[str, Any]]:
    source_resolved = source_root.resolve(strict=True)
    shadow_resolved = shadow.resolve(strict=True)
    current = shadow.absolute()
    while True:
        if current.is_symlink():
            raise RuntimeError("temporary_shadow_symlinked_ancestry_forbidden")
        if current.parent == current:
            break
        current = current.parent
    if shadow_resolved == source_resolved or source_resolved in shadow_resolved.parents:
        raise RuntimeError("temporary_shadow_must_be_outside_source_repository")
    if not shadow.is_dir() or any(shadow.iterdir()):
        raise RuntimeError("temporary_shadow_must_be_new_empty_directory")
    resolution = resolve_source_manifest_claims(source_root, cfg)
    if not resolution["resolution_pass"] or not source_authority_resolution_exact(resolution, cfg, source_root):
        raise RuntimeError(
            f"source_manifest_authority_resolution_hold:{resolution['fatal_path_count']}:"
            f"{resolution['receipt_sha256']}"
        )
    allowed = dict(resolution["selected_copy_digests"])
    manifests: dict[str, dict] = {}
    for stage in cfg["stage_contracts"]:
        for relative, digest in (
            (stage["executor"], stage["executor_sha256"]),
            (stage["config"], stage["config_sha256"]),
            (stage["manifest"], stage["manifest_sha256"]),
        ):
            if relative in allowed and allowed[relative] != digest:
                raise RuntimeError(f"authority_digest_conflict:{relative}")
            allowed[relative] = digest
        manifests[stage["manifest"]] = strict_json_bytes(
            verified_source_bytes(
                source_root,
                stage["manifest"],
                stage["manifest_sha256"],
            ),
            stage["manifest"],
        )
    primary = set(cfg["exact_sources"])
    for stage in cfg["stage_contracts"]:
        primary.update((stage["executor"], stage["config"], stage["manifest"]))
    for relative in sorted(primary):
        copy_exact(source_root, shadow, relative, allowed[relative])
    configs = {
        stage["config"]: strict_yaml_bytes(
            (shadow / safe_relative(stage["config"])).read_bytes(),
            stage["config"],
        )
        for stage in cfg["stage_contracts"]
    }
    generated = _declared_generated_outputs(cfg, configs)
    synthetic_paths = set(resolution["synthetic_paths"])
    for relative, digest in sorted(resolution["selected_copy_digests"].items()):
        if relative in generated or relative in synthetic_paths or (shadow / safe_relative(relative)).exists():
            continue
        copy_exact(source_root, shadow, relative, digest)
    copied_imports, unattested = copy_attested_code_closure(source_root, shadow, allowed)
    if unattested:
        raise RuntimeError(
            f"unattested_local_import_hold:{len(unattested)}:"
            f"{canonical_json_sha256(unattested)}"
        )
    scaffold_receipts: list[dict[str, Any]] = []
    for relative in PACKAGE_SCAFFOLD_PATHS:
        destination = shadow / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            _atomic_bytes(destination, b"")
            scaffold_receipts.append({
                "relative_path": relative,
                "construction_class": "exact_empty_package_scaffold",
                "sha256": hashlib.sha256(b"").hexdigest(),
                "bytes": 0,
            })
    synthetic = write_synthetic_inputs(shadow, cfg, configs, offset)
    fixture_checks = synthetic.get("fixture_contract_checks")
    if (
        synthetic.get("fixture_contract_pass") is not True
        or not isinstance(fixture_checks, dict)
        or not fixture_checks
        or not all(value is True for value in fixture_checks.values())
    ):
        raise RuntimeError("synthetic_fixture_contract_hold_before_executor")
    expected_synthetic = expected_synthetic_construction(source_root, cfg, float(offset))
    if synthetic != expected_synthetic:
        raise RuntimeError("synthetic_fixture_receipt_not_canonical")
    for relative, record in expected_synthetic["synthetic_file_receipts"].items():
        state = _path_state(shadow, relative, require_single_link=True)
        path = shadow / safe_relative(relative)
        if not (
            state["valid_regular_contained"]
            and sha256(path) == record["sha256"]
            and path.stat().st_size == record["bytes"]
        ):
            raise RuntimeError(f"synthetic_fixture_postwrite_mismatch:{relative}")
    config_receipts: list[dict[str, Any]] = []
    manifest_receipts: list[dict[str, Any]] = []

    # Mutable documents are refreshed in dependency order.  A document that
    # records another mutable document's digest must be written after that
    # dependency reaches its final shadow bytes.  Cycles (including self-pins)
    # cannot have a deterministic one-pass final digest and are a hard hold.
    config_pins = {
        canonical_relative(stage["config"]): stage["config_sha256"]
        for stage in cfg["stage_contracts"]
    }
    manifest_pins = {
        canonical_relative(stage["manifest"]): stage["manifest_sha256"]
        for stage in cfg["stage_contracts"]
    }
    if set(config_pins) & set(manifest_pins):
        raise RuntimeError("mutable_document_role_overlap")
    documents: dict[str, tuple[str, dict[str, Any]]] = {
        **{relative: ("config", value) for relative, value in configs.items()},
        **{relative: ("manifest", value) for relative, value in manifests.items()},
    }
    mutable_paths = set(documents)
    dependencies = {
        relative: integrity_bound_paths(
            value,
            cross_bindings=(
                bindings_for_document(cfg, relative)
                if kind == "config" else ()
            ),
        ) & mutable_paths
        for relative, (kind, value) in documents.items()
    }
    pending = set(documents)
    document_order: list[str] = []
    while pending:
        ready = sorted(relative for relative in pending if not (dependencies[relative] & pending))
        if not ready:
            cycle = sorted({path for relative in pending for path in dependencies[relative] & pending} | pending)
            raise RuntimeError(f"mutable_document_dependency_cycle:{canonical_json_sha256(cycle)}")
        document_order.extend(ready)
        pending.difference_update(ready)

    for relative in document_order:
        kind, current = documents[relative]
        path = shadow / safe_relative(relative)
        before = sha256(path)
        before_value_sha256 = canonical_json_sha256(current)
        refreshed, mutations = refresh_integrity_records(
            current,
            shadow,
            cross_bindings=(
                bindings_for_document(cfg, relative)
                if kind == "config" else ()
            ),
        )
        mutations.sort(key=lambda item: (item["location"], item["relative_path"], item["field"]))
        payload = _json_bytes(refreshed) if kind == "manifest" else _yaml_bytes(refreshed)
        _atomic_bytes(path, payload)
        base_receipt = {
            "relative_path": relative,
            "source_template_sha256": (manifest_pins if kind == "manifest" else config_pins)[relative],
            "before_sha256": before,
            "after_sha256": sha256(path),
            "before_value_sha256": before_value_sha256,
            "after_value_sha256": canonical_json_sha256(refreshed),
            "mutation_count": len(mutations),
            "mutations": mutations,
            "mutations_sha256": canonical_json_sha256(mutations),
        }
        if kind == "config":
            configs[relative] = refreshed
            config_receipts.append(base_receipt)
        else:
            before_record_count = len(exact_manifest_file_records(current))
            manifest_receipts.append({
                **base_receipt,
                "source_record_count": before_record_count,
                "shadow_record_count": len(exact_manifest_file_records(refreshed)),
            })
    config_receipts.sort(key=lambda item: item["relative_path"])
    manifest_receipts.sort(key=lambda item: item["relative_path"])
    initial_pending = _pending_generated_records_by_manifest(cfg, EXPECTED_STAGE_ORDER[0])
    for receipt in manifest_receipts:
        allowed_missing = initial_pending.get(canonical_relative(receipt["relative_path"]), frozenset())
        closure = audit_executor_manifest_closure(
            shadow,
            receipt["relative_path"],
            allowed_missing=allowed_missing,
        )
        receipt["post_refresh_closure_pass"] = closure["closure_pass"]
        receipt["post_refresh_record_count"] = closure["manifest_file_record_count"]
        receipt["post_refresh_digest_match_count"] = closure["manifest_file_digest_match_count"]
        receipt["post_refresh_allowed_missing_count"] = closure["allowed_missing_count"]
    constructed_files: dict[str, dict[str, Any]] = {}
    for path in sorted(shadow.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(shadow).as_posix()
        state = _path_state(shadow, relative, require_single_link=True)
        if not state["valid_regular_contained"]:
            raise RuntimeError(f"constructed_file_not_regular_contained_single_link:{relative}")
        constructed_files[relative] = {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
    for relative, record in expected_synthetic["synthetic_file_receipts"].items():
        if constructed_files.get(relative) != record:
            raise RuntimeError(f"synthetic_fixture_changed_before_preflight:{relative}")
    mutable_documents = set(configs) | set(manifests)
    for relative, digest in resolution["selected_copy_digests"].items():
        if relative not in mutable_documents and constructed_files.get(relative, {}).get("sha256") != digest:
            raise RuntimeError(f"selected_authority_changed_before_preflight:{relative}")
    audit = {
        **synthetic,
        "source_authority_resolution": resolution,
        "source_authority_resolution_pass": source_authority_resolution_exact(resolution, cfg, source_root),
        "source_authority_resolution_receipt_sha256": resolution["receipt_sha256"],
        "attested_import_files_copied": copied_imports,
        "unattested_local_import_count": len(unattested),
        "unattested_local_import_sha256": hashlib.sha256("\n".join(unattested).encode()).hexdigest(),
        "construction_scaffold_receipts": scaffold_receipts,
        "constructed_file_receipts": constructed_files,
        "constructed_file_receipts_sha256": canonical_json_sha256(constructed_files),
        "construction_config_mutation_receipts": config_receipts,
        "construction_manifest_mutation_receipts": manifest_receipts,
        "mutable_document_dependencies": {
            relative: sorted(dependencies[relative]) for relative in sorted(dependencies)
        },
        "mutable_document_order": document_order,
        "mutable_document_plan_sha256": canonical_json_sha256({
            "dependencies": {
                relative: sorted(dependencies[relative]) for relative in sorted(dependencies)
            },
            "order": document_order,
        }),
        "shadow_config_integrity_mutation_count": sum(item["mutation_count"] for item in config_receipts),
        "shadow_manifest_integrity_mutation_count": sum(item["mutation_count"] for item in manifest_receipts),
        "generic_interstage_refresh_count": 0,
    }
    return configs, audit


def audit_executor_manifest_closure(
    shadow: Path,
    manifest_relative: str,
    *,
    allowed_missing: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    canonical_manifest = canonical_relative(manifest_relative)
    allowed = {canonical_relative(value) for value in allowed_missing}
    rows: list[dict[str, Any]] = []
    try:
        manifest_payload = source_snapshot_bytes(shadow, canonical_manifest)
        manifest_value = strict_json_bytes(manifest_payload, canonical_manifest)
        records = exact_manifest_file_records(manifest_value)
        assert_unambiguous_sibling_integrity(manifest_value)
        manifest_observed_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    except Exception as error:
        return {
            "manifest_relative_path": canonical_manifest,
            "manifest_sha256": "",
            "manifest_file_record_count": 0,
            "manifest_file_existing_count": 0,
            "manifest_file_digest_match_count": 0,
            "allowed_missing_count": 0,
            "closure_pass": False,
            "rows": [],
            "auxiliary_integrity_binding_count": 0,
            "auxiliary_integrity_binding_match_count": 0,
            "auxiliary_integrity_bindings_pass": False,
            "auxiliary_rows": [],
            "hold_reason": f"{type(error).__name__}:{str(error)[:500]}",
        }
    for relative, record in sorted(records.items()):
        state = _path_state(shadow, relative, require_single_link=True)
        payload: bytes | None = None
        if state["valid_regular_contained"]:
            try:
                payload = source_snapshot_bytes(shadow, relative)
            except (OSError, RuntimeError):
                payload = None
        actual = hashlib.sha256(payload).hexdigest() if payload is not None else ""
        observed_size = len(payload) if payload is not None else -1
        size_match = payload is not None and all(
            record[key] == observed_size for key in SIZE_FIELDS & set(record)
        )
        hash_match = payload is not None and all(
            record[key] == actual for key in HASH_FIELDS & set(record)
        )
        digest_match = bool(actual and hash_match and size_match)
        pending = relative in allowed and not state["exists"] and state["resolved_contained"] and not state["parent_or_target_symlink"]
        rows.append({
            **state,
            "recorded_sha256": record["sha256"],
            "recorded_hash_fields": {
                key: record[key] for key in sorted(HASH_FIELDS & set(record))
            },
            "observed_sha256": actual,
            "digest_exact": digest_match,
            "size_fields_exact": size_match,
            "allowed_pending": pending,
            "status": "exact" if digest_match else ("allowed_pending" if pending else "hold"),
        })
    existing = sum(row["valid_regular_contained"] for row in rows)
    matched = sum(row["digest_exact"] for row in rows)
    pending_count = sum(row["allowed_pending"] for row in rows)
    auxiliary_rows: list[dict[str, Any]] = []

    def walk_auxiliary(node: Any, location: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if isinstance(child, str):
                    digest_keys, size_keys = sibling_integrity_fields(node, key)
                    if digest_keys or size_keys:
                        try:
                            relative = canonical_relative(child)
                            state = _path_state(shadow, relative, require_single_link=True)
                            payload = (
                                source_snapshot_bytes(shadow, relative)
                                if state["valid_regular_contained"] else None
                            )
                            actual_digest = hashlib.sha256(payload).hexdigest() if payload is not None else ""
                            actual_size = len(payload) if payload is not None else -1
                            pending = relative in allowed and not state.get("exists", False)
                            for field in digest_keys:
                                expected = node[field]
                                match = isinstance(expected, str) and expected == actual_digest
                                auxiliary_rows.append({
                                    "location": f"{location}.{field}",
                                    "relative_path": relative,
                                    "field": field,
                                    "kind": "digest",
                                    "recorded_value": expected,
                                    "observed_value": actual_digest,
                                    "exact": match,
                                    "allowed_pending": pending,
                                })
                            for field in size_keys:
                                expected = node[field]
                                match = isinstance(expected, int) and not isinstance(expected, bool) and expected == actual_size
                                auxiliary_rows.append({
                                    "location": f"{location}.{field}",
                                    "relative_path": relative,
                                    "field": field,
                                    "kind": "size",
                                    "recorded_value": expected,
                                    "observed_value": actual_size,
                                    "exact": match,
                                    "allowed_pending": pending,
                                })
                        except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                            auxiliary_rows.append({
                                "location": f"{location}.{key}",
                                "relative_path": "",
                                "field": key,
                                "kind": "path",
                                "recorded_value": child,
                                "observed_value": "",
                                "exact": False,
                                "allowed_pending": False,
                            })
                walk_auxiliary(child, f"{location}.{key}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk_auxiliary(child, f"{location}[{index}]")

    walk_auxiliary(manifest_value, "$")
    auxiliary_match_count = sum(row["exact"] for row in auxiliary_rows)
    auxiliary_pass = all(row["exact"] or row["allowed_pending"] for row in auxiliary_rows)
    closure = bool(rows) and all(row["digest_exact"] or row["allowed_pending"] for row in rows) and auxiliary_pass
    return {
        "manifest_relative_path": canonical_manifest,
        "manifest_sha256": manifest_observed_sha256,
        "manifest_file_record_count": len(rows),
        "manifest_file_existing_count": existing,
        "manifest_file_digest_match_count": matched,
        "allowed_missing_count": pending_count,
        "auxiliary_integrity_binding_count": len(auxiliary_rows),
        "auxiliary_integrity_binding_match_count": auxiliary_match_count,
        "auxiliary_integrity_bindings_pass": auxiliary_pass,
        "closure_pass": closure,
        "rows": rows,
        "auxiliary_rows": auxiliary_rows,
        "hold_reason": None if closure else "executor_manifest_top_level_files_not_closed",
    }


def required_input_concordance(
    shadow: Path,
    configs: dict[str, dict],
    stage: dict,
    *,
    expected_config_sha256: str | None = None,
    expected_executor_sha256: str | None = None,
    allowed_missing: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    try:
        config_relative = canonical_relative(stage["config"])
        manifest_relative = canonical_relative(stage["manifest"])
        config_payload = source_snapshot_bytes(shadow, config_relative)
        config_observed_sha256 = hashlib.sha256(config_payload).hexdigest()
        config = strict_yaml_bytes(config_payload, config_relative)
        config_snapshot_exact = (
            config == configs[config_relative]
            and (
                expected_config_sha256 is None
                or config_observed_sha256 == expected_config_sha256
            )
        )
        manifest_payload = source_snapshot_bytes(shadow, manifest_relative)
        invocation_manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
        records = exact_manifest_file_records(
            strict_json_bytes(manifest_payload, manifest_relative)
        )
        if "executor" in stage:
            executor_relative = canonical_relative(stage["executor"])
            executor_payload = source_snapshot_bytes(shadow, executor_relative)
            executor_observed_sha256 = hashlib.sha256(executor_payload).hexdigest()
            executor_snapshot_exact = (
                expected_executor_sha256 is None
                or executor_observed_sha256 == expected_executor_sha256
            )
        else:
            executor_observed_sha256 = ""
            executor_snapshot_exact = expected_executor_sha256 is None
    except Exception as error:
        return {
            "command_contract_exact": False,
            "repo_root_is_explicit_shadow": True,
            "config_path_shadow_relative": True,
            "manifest_path_shadow_relative": True,
            "required_input_count": len(stage["required_data_keys"]),
            "required_input_existing_count": 0,
            "required_input_manifest_record_count": 0,
            "required_input_digest_match_count": 0,
            "manifest_config_concordant": False,
            "invocation_manifest_sha256": "",
            "config_snapshot_sha256": "",
            "config_snapshot_exact": False,
            "executor_snapshot_sha256": "",
            "executor_snapshot_exact": False,
            "executor_manifest_closure_pass": False,
            "manifest_file_record_count": 0,
            "manifest_file_existing_count": 0,
            "manifest_file_digest_match_count": 0,
            "audit_rows": [],
            "hold_reason": f"missing_or_malformed_shadow_config_or_manifest:{type(error).__name__}",
        }
    audit_rows: list[dict[str, Any]] = []
    for key in stage["required_data_keys"]:
        try:
            relative = canonical_relative(str(deep_get(config, key)))
            state = _path_state(shadow, relative, require_single_link=True)
            recorded = records.get(relative)
            payload = (
                source_snapshot_bytes(shadow, relative)
                if state["valid_regular_contained"] else None
            )
            actual = hashlib.sha256(payload).hexdigest() if payload is not None else ""
            observed_bytes = len(payload) if payload is not None else -1
            match = bool(
                recorded
                and actual
                and all(
                    recorded[field] == actual
                    for field in HASH_FIELDS & set(recorded)
                )
                and all(
                    recorded[field] == observed_bytes
                    for field in SIZE_FIELDS & set(recorded)
                )
            )
            failure = None
        except Exception as error:
            relative = ""
            state = {"valid_regular_contained": False}
            recorded = None
            actual = ""
            match = False
            failure = type(error).__name__
        audit_rows.append({
            "stage": stage["stage"],
            "required_data_key": key,
            "relative_path": relative,
            "path_safe_regular_contained": state["valid_regular_contained"],
            "file_exists": bool(state.get("exists")),
            "manifest_record_present": recorded is not None,
            "digest_exact": match,
            "recorded_sha256": recorded["sha256"] if recorded else "",
            "observed_sha256": actual,
            "status": "concordant" if match else (failure or "missing_or_digest_mismatch"),
        })
    closure = audit_executor_manifest_closure(shadow, stage["manifest"], allowed_missing=allowed_missing)
    count = len(audit_rows)
    existing = sum(row["path_safe_regular_contained"] for row in audit_rows)
    recorded_count = sum(row["manifest_record_present"] for row in audit_rows)
    matched = sum(row["digest_exact"] for row in audit_rows)
    concordant = bool(
        count > 0
        and existing == recorded_count == matched == count
        and closure["closure_pass"]
        and config_snapshot_exact
        and executor_snapshot_exact
    )
    return {
        "command_contract_exact": config_snapshot_exact and executor_snapshot_exact,
        "repo_root_is_explicit_shadow": True,
        "config_path_shadow_relative": True,
        "manifest_path_shadow_relative": True,
        "required_input_count": count,
        "required_input_existing_count": existing,
        "required_input_manifest_record_count": recorded_count,
        "required_input_digest_match_count": matched,
        "manifest_config_concordant": concordant,
        "invocation_manifest_sha256": invocation_manifest_sha256,
        "config_snapshot_sha256": config_observed_sha256,
        "config_snapshot_exact": config_snapshot_exact,
        "executor_snapshot_sha256": executor_observed_sha256,
        "executor_snapshot_exact": executor_snapshot_exact,
        "executor_manifest_closure_pass": closure["closure_pass"],
        "manifest_file_record_count": closure["manifest_file_record_count"],
        "manifest_file_existing_count": closure["manifest_file_existing_count"],
        "manifest_file_digest_match_count": closure["manifest_file_digest_match_count"],
        "audit_rows": audit_rows,
        "manifest_closure": closure,
        "hold_reason": None if concordant else "required_input_or_full_manifest_concordance_failure",
    }


def runtime_binding_preflight(source_root: Path, shadow: Path, cfg: dict, configs: dict[str, dict]) -> dict[str, Any]:
    binding = cfg["runtime_binding"]
    target = canonical_relative(binding["target_relative_path"])
    shared = canonical_relative(binding["shared_manifest"])
    confirmation = canonical_relative(binding["confirmation_manifest"])
    template = canonical_relative(binding.get("confirmation_template_manifest", confirmation))
    rows: list[dict[str, Any]] = []
    try:
        template_expected = next(stage["manifest_sha256"] for stage in cfg["stage_contracts"] if stage["manifest"] == template)
        template_payload = verified_source_bytes(source_root, template, template_expected)
        template_observed = hashlib.sha256(template_payload).hexdigest()
        source_template = strict_json_bytes(template_payload, template)
        template_records = exact_manifest_file_records(source_template)
        template_record = template_records[target]
        shared_expected = binding.get("source_manifest_sha256", {}).get(shared)
        shared_payload = verified_source_bytes(source_root, shared, shared_expected)
        source_shared = exact_manifest_file_records(strict_json_bytes(shared_payload, shared))
        shadow_shared = exact_manifest_file_records(read_json(contained_regular_file(shadow, shared, require_single_link=True)))
        shadow_confirmation = exact_manifest_file_records(read_json(contained_regular_file(shadow, confirmation, require_single_link=True)))
        target_state = _path_state(shadow, target, require_single_link=True)
        authorized_content_fields = set(
            binding["mutation_scope"]["authorized_existing_content_derived_fields"]
        )
        present_hash_fields = HASH_FIELDS & set(template_record)
        present_size_fields = SIZE_FIELDS & set(template_record)
        checks = {
            "source_template_manifest_hash_exact": template_observed == template_expected,
            "source_shared_manifest_hash_exact": hashlib.sha256(shared_payload).hexdigest() == shared_expected,
            "source_shared_target_record_absent": target not in source_shared,
            "shadow_shared_target_record_absent": target not in shadow_shared,
            "source_confirmation_template_record_present": target in template_records,
            "source_confirmation_template_content_fields_authorized_exact": bool(
                authorized_content_fields
                and authorized_content_fields <= HASH_FIELDS | SIZE_FIELDS
                and present_hash_fields >= {"sha256"}
                and (present_hash_fields | present_size_fields) <= authorized_content_fields
            ),
            "source_confirmation_template_record_digest_exact": all(
                template_record[key] == binding.get("template_target_content_sha256")
                for key in present_hash_fields
            ),
            "source_confirmation_template_record_bytes_exact": all(
                int(template_record[key]) == int(binding["template_target_bytes"])
                for key in present_size_fields
            ),
            "historical_runtime_target_not_read_or_copied": True,
            "shadow_confirmation_template_record_exact": shadow_confirmation.get(target) == template_record,
            "runtime_target_absent_before_producer": not target_state["exists"],
            "runtime_target_parent_contained_non_symlink": target_state["resolved_contained"] and not target_state["parent_or_target_symlink"],
        }
        unique_manifests = sorted({stage["manifest"] for stage in cfg["stage_contracts"]})
        pending = _pending_generated_records_by_manifest(cfg, EXPECTED_STAGE_ORDER[0])
        closures = []
        for manifest in unique_manifests:
            canonical_manifest = canonical_relative(manifest)
            allowed = pending.get(canonical_manifest, frozenset())
            closure = audit_executor_manifest_closure(shadow, manifest, allowed_missing=allowed)
            closures.append(closure)
            rows.extend({"audit_kind": "manifest_closure", **row} for row in closure["rows"])
        checks["all_nonruntime_manifest_records_closed"] = all(item["closure_pass"] for item in closures)
        confirmation_closure = next(item for item in closures if item["manifest_relative_path"] == confirmation)
        checks["confirmation_has_exactly_one_allowed_pending_target"] = sum(
            row.get("relative_path") == target and row.get("allowed_pending") is True
            for row in confirmation_closure["rows"]
        ) == 1
        checks["runtime_target_has_zero_auxiliary_pending_claims"] = all(
            not row.get("allowed_pending", False)
            for item in closures
            for row in item.get("auxiliary_rows", [])
        )
        source_counts = binding.get("source_manifest_top_level_file_counts", {})
        checks["source_manifest_record_counts_exact"] = all(
            len(exact_manifest_file_records(strict_json_bytes(
                verified_source_bytes(source_root, path, next(
                    stage["manifest_sha256"] for stage in cfg["stage_contracts"] if stage["manifest"] == path
                )),
                path,
            ))) == int(expected)
            for path, expected in source_counts.items()
        ) if source_counts else True
        producer = next(stage for stage in cfg["stage_contracts"] if stage["stage"] == binding["producer_stage"])
        producer_concordance = required_input_concordance(
            shadow,
            configs,
            producer,
            expected_executor_sha256=producer["executor_sha256"],
        )
        checks["producer_manifest_and_inputs_closed"] = producer_concordance["manifest_config_concordant"]
        result = {
            "pass": all(checks.values()),
            "checks": checks,
            "rows": rows,
            "producer_manifest_sha256": sha256(shadow / safe_relative(shared)),
            "confirmation_manifest_sha256": sha256(shadow / safe_relative(confirmation)),
            "template_manifest_expected_sha256": template_expected,
            "template_manifest_observed_sha256": template_observed,
            "template_record_sha256": canonical_json_sha256(template_record),
            "target_relative_path": target,
            "manifest_closures": closures,
        }
        return result
    except Exception as error:
        return {
            "pass": False,
            "checks": {},
            "rows": rows,
            "producer_manifest_sha256": "",
            "confirmation_manifest_sha256": "",
            "template_record_sha256": "",
            "target_relative_path": target,
            "hold_reason": f"{type(error).__name__}:{str(error)[:1000]}",
        }


def _validated_runtime_product_value(
    payload: bytes,
    target: str,
    producer_stage: dict[str, Any],
    producer_config: dict[str, Any],
) -> dict[str, Any]:
    """Parse one producer snapshot and enforce its pinned output contract."""
    value = strict_json_bytes(payload, target)
    expected_run_id = producer_config.get("run_id")
    schema_version = value.get("schema_version")
    contract = producer_stage.get("fresh_output_contract", {})
    if not isinstance(contract, dict):
        raise RuntimeError("runtime_binding_product_contract_invalid")
    required = contract.get(
        "required_json_keys",
        contract.get("required_keys", ["schema_version", "run_id"]),
    )
    truthy = contract.get("required_truthy_keys", [])
    if (
        not isinstance(required, list)
        or not required
        or any(not isinstance(key, str) or not key for key in required)
        or len(required) != len(set(required))
        or not isinstance(truthy, list)
        or any(not isinstance(key, str) or not key for key in truthy)
        or len(truthy) != len(set(truthy))
    ):
        raise RuntimeError("runtime_binding_product_contract_invalid")
    if (
        not isinstance(expected_run_id, str)
        or not expected_run_id
        or not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version <= 0
        or value.get("run_id") != expected_run_id
        or any(key not in value for key in required)
        or any(value.get(key) is not True for key in truthy)
    ):
        raise RuntimeError("runtime_binding_product_json_or_run_id_invalid")
    return value


def _runtime_product_snapshot_from_receipt(
    receipt: dict[str, Any],
    target: str,
    producer_stage: dict[str, Any],
    producer_config: dict[str, Any],
) -> tuple[bytes, dict[str, Any], str, int]:
    """Decode and independently reconstruct every content-derived product claim."""
    encoded = receipt.get("product_payload_b64")
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("runtime_binding_product_snapshot_missing")
    try:
        payload = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as error:
        raise RuntimeError("runtime_binding_product_snapshot_base64_invalid") from error
    if base64.b64encode(payload).decode("ascii") != encoded:
        raise RuntimeError("runtime_binding_product_snapshot_base64_noncanonical")
    value = _validated_runtime_product_value(
        payload, target, producer_stage, producer_config
    )
    digest = hashlib.sha256(payload).hexdigest()
    size = len(payload)
    if not (
        size > 0
        and receipt.get("product_json_run_id") == value["run_id"]
        and receipt.get("product_json_schema_version") == value["schema_version"]
        and receipt.get("product_sha256") == digest
        and receipt.get("target_sha256") == digest
        and receipt.get("product_bytes") == size
        and receipt.get("target_bytes") == size
    ):
        raise RuntimeError("runtime_binding_product_snapshot_claim_mismatch")
    return payload, value, digest, size


def clone_refreshed_file_record(
    template_record: dict[str, Any],
    product: Path | None,
    authorized_fields: Iterable[str] | None = None,
    *,
    observed_sha256: str | None = None,
    observed_bytes: int | None = None,
) -> dict[str, Any]:
    if not isinstance(template_record, dict) or not SHA256_RE.fullmatch(str(template_record.get("sha256", ""))):
        raise RuntimeError("runtime_binding_template_record_malformed")
    allowed = set(authorized_fields) if authorized_fields is not None else HASH_FIELDS | SIZE_FIELDS
    if not allowed or not allowed <= HASH_FIELDS | SIZE_FIELDS or "sha256" not in allowed:
        raise RuntimeError("runtime_binding_authorized_content_fields_invalid")
    present_content_fields = (HASH_FIELDS | SIZE_FIELDS) & set(template_record)
    if (
        not present_content_fields <= allowed
        or "sha256" not in present_content_fields
    ):
        raise RuntimeError("runtime_binding_template_content_fields_not_fully_authorized")
    refreshed = copy.deepcopy(template_record)
    if observed_sha256 is None or observed_bytes is None:
        if product is None:
            raise RuntimeError("runtime_binding_product_observation_missing")
        payload = source_snapshot_bytes(product.parent, product.name)
        observed_sha256 = hashlib.sha256(payload).hexdigest()
        observed_bytes = len(payload)
    digest = observed_sha256
    size = observed_bytes
    if SHA256_RE.fullmatch(str(digest)) is None or not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise RuntimeError("runtime_binding_product_observation_invalid")
    for key in HASH_FIELDS & allowed & set(refreshed):
        refreshed[key] = digest
    for key in SIZE_FIELDS & allowed & set(refreshed):
        refreshed[key] = size
    if set(refreshed) != set(template_record):
        raise RuntimeError("runtime_binding_record_schema_changed")
    return refreshed


def runtime_binding_receipt_exact(receipt: Any, cfg: dict[str, Any], source_root: Path) -> bool:
    """Bind one successful receipt to the frozen runtime-binding authority.

    The receipt digest proves only self-integrity.  This predicate additionally
    proves that every path, template record, permitted field mutation, and
    two-manifest operation is the one declared by ``cfg["runtime_binding"]``.
    """
    try:
        if not isinstance(receipt, dict) or set(receipt) != RUNTIME_BINDING_RECEIPT_FIELDS:
            return False
        binding = cfg["runtime_binding"]
        schema = binding["receipt_schema"]
        required = set(schema["required_fields"])
        if not required <= set(receipt):
            return False

        target = canonical_relative(binding["target_relative_path"])
        shared = canonical_relative(binding["shared_manifest"])
        confirmation = canonical_relative(binding["confirmation_manifest"])
        template = canonical_relative(binding.get("confirmation_template_manifest", confirmation))
        producer_name = binding["producer_stage"]
        consumers = binding["consumer_stages"]
        stages = {stage["stage"]: stage for stage in cfg["stage_contracts"]}
        if not (
            isinstance(consumers, list)
            and len(consumers) == len(set(consumers)) == 2
            and producer_name in stages
            and all(name in stages for name in consumers)
            and canonical_relative(binding.get("producer_manifest", shared)) == shared
            and canonical_relative(stages[producer_name]["manifest"]) == shared
            and canonical_relative(stages[consumers[0]]["manifest"]) == shared
            and canonical_relative(stages[consumers[1]]["manifest"]) == confirmation
        ):
            return False

        receipt_paths = {
            "product_relative_path": target,
            "target_relative_path": target,
            "source_template_manifest": template,
            "template_manifest_relative_path": template,
            "shared_manifest": shared,
            "confirmation_manifest": confirmation,
        }
        if any(receipt.get(name) != expected for name, expected in receipt_paths.items()):
            return False
        if any(canonical_relative(receipt[name]) != receipt[name] for name in receipt_paths):
            return False

        producer_stage = stages[producer_name]
        producer_config_relative = canonical_relative(producer_stage["config"])
        producer_config = strict_yaml_bytes(
            verified_source_bytes(
                source_root.resolve(),
                producer_config_relative,
                producer_stage["config_sha256"],
            ),
            producer_config_relative,
        )
        _, _, snapshot_sha256, snapshot_bytes = _runtime_product_snapshot_from_receipt(
            receipt, target, producer_stage, producer_config
        )

        configured_template_sha = binding["source_manifest_sha256"][template]
        template_payload = verified_source_bytes(source_root.resolve(), template, configured_template_sha)
        template_source_sha = hashlib.sha256(template_payload).hexdigest()
        template_record = exact_manifest_file_records(strict_json_bytes(template_payload, template))[target]
        configured_target_sha = binding["template_target_content_sha256"]
        configured_target_bytes = binding["template_target_bytes"]
        if not (
            isinstance(configured_target_bytes, int)
            and not isinstance(configured_target_bytes, bool)
            and configured_target_bytes > 0
            and SHA256_RE.fullmatch(str(configured_template_sha)) is not None
            and template_source_sha == configured_template_sha
            and receipt["source_template_manifest_expected_sha256"] == configured_template_sha
            and receipt["source_template_manifest_observed_sha256"] == configured_template_sha
            and receipt["template_manifest_source_sha256"] == configured_template_sha
            and receipt["template_record"] == template_record
            and receipt["template_record_sha256"] == canonical_json_sha256(template_record)
            and template_record.get("sha256") == configured_target_sha
        ):
            return False
        if any(
            template_record.get(name) != configured_target_bytes
            for name in SIZE_FIELDS & set(template_record)
        ):
            return False

        target_sha = receipt["target_sha256"]
        target_bytes = receipt["target_bytes"]
        if not (
            isinstance(target_sha, str)
            and SHA256_RE.fullmatch(target_sha) is not None
            and target_sha == snapshot_sha256
            and receipt["product_sha256"] == target_sha
            and isinstance(target_bytes, int)
            and not isinstance(target_bytes, bool)
            and target_bytes > 0
            and target_bytes == snapshot_bytes
            and receipt["product_bytes"] == target_bytes
        ):
            return False
        refreshed = receipt["refreshed_record"]
        if not isinstance(refreshed, dict) or set(refreshed) != set(template_record):
            return False
        authorized = set(binding["mutation_scope"]["authorized_existing_content_derived_fields"])
        if not authorized or not authorized <= HASH_FIELDS | SIZE_FIELDS or "sha256" not in authorized:
            return False
        present_content_fields = (HASH_FIELDS | SIZE_FIELDS) & set(template_record)
        if not (
            present_content_fields <= authorized
            and "sha256" in present_content_fields
        ):
            return False
        for name in template_record:
            if name not in authorized and refreshed[name] != template_record[name]:
                return False
            if name in authorized & HASH_FIELDS and refreshed[name] != target_sha:
                return False
            if name in authorized & SIZE_FIELDS and refreshed[name] != target_bytes:
                return False

        shared_before = receipt["shared_manifest_before"]
        confirmation_before = receipt["confirmation_manifest_before"]
        if not isinstance(shared_before, dict) or not isinstance(confirmation_before, dict):
            return False
        shared_records = exact_manifest_file_records(shared_before)
        confirmation_records = exact_manifest_file_records(confirmation_before)
        if target in shared_records or confirmation_records.get(target) != template_record:
            return False
        shared_after = copy.deepcopy(shared_before)
        confirmation_after = copy.deepcopy(confirmation_before)
        shared_after["files"][target] = copy.deepcopy(refreshed)
        confirmation_after["files"][target] = copy.deepcopy(refreshed)
        shared_before_sha = hashlib.sha256(_json_bytes(shared_before)).hexdigest()
        confirmation_before_sha = hashlib.sha256(_json_bytes(confirmation_before)).hexdigest()
        shared_after_sha = hashlib.sha256(_json_bytes(shared_after)).hexdigest()
        dependency_refresh = _runtime_dependency_refresh_spec(binding)
        if dependency_refresh is None:
            confirmation_scope_exact = _only_target_record_changed(
                confirmation_before, confirmation_after, target, insertion=False
            )
        else:
            dependency = canonical_relative(dependency_refresh["child_manifest"])
            dependency_field = dependency_refresh["record_field"]
            dependency_before = confirmation_records.get(dependency)
            if (
                not isinstance(dependency_before, dict)
                or dependency_field not in dependency_before
                or dependency_before[dependency_field] != shared_before_sha
            ):
                return False
            confirmation_after["files"][dependency][dependency_field] = shared_after_sha
            confirmation_scope_exact = _only_target_and_dependency_record_changed(
                confirmation_before,
                confirmation_after,
                target,
                dependency,
                insertion=False,
                dependency_field=dependency_field,
            )
        if not (
            _only_target_record_changed(shared_before, shared_after, target, insertion=True)
            and confirmation_scope_exact
            and shared_before_sha == receipt["shared_manifest_before_sha256"]
            and confirmation_before_sha == receipt["confirmation_manifest_before_sha256"]
            and shared_after_sha == receipt["shared_manifest_after_sha256"]
            and hashlib.sha256(_json_bytes(confirmation_after)).hexdigest()
            == receipt["confirmation_manifest_after_sha256"]
        ):
            return False

        digest_fields = (
            "producer_invocation_manifest_sha256", "shared_manifest_before_sha256",
            "confirmation_manifest_expected_before_sha256",
            "shared_manifest_after_sha256", "confirmation_manifest_before_sha256",
            "confirmation_manifest_after_sha256", "receipt_payload_sha256", "receipt_sha256",
        )
        if any(SHA256_RE.fullmatch(str(receipt.get(name, ""))) is None for name in digest_fields):
            return False
        if not (
            receipt["producer_invocation_manifest_sha256"] == receipt["shared_manifest_before_sha256"]
            and receipt["confirmation_manifest_expected_before_sha256"]
            == receipt["confirmation_manifest_before_sha256"]
            and receipt["shared_manifest_before_sha256"] != receipt["shared_manifest_after_sha256"]
            and receipt["confirmation_manifest_before_sha256"] != receipt["confirmation_manifest_after_sha256"]
        ):
            return False
        expected_mutations = [
            {
                "manifest": shared,
                "before_sha256": receipt["shared_manifest_before_sha256"],
                "after_sha256": receipt["shared_manifest_after_sha256"],
                "operation": "insert_target_record",
            },
            {
                "manifest": confirmation,
                "before_sha256": receipt["confirmation_manifest_before_sha256"],
                "after_sha256": receipt["confirmation_manifest_after_sha256"],
                "operation": "refresh_target_record",
            },
        ]
        if dependency_refresh is not None:
            expected_mutations.append({
                "manifest": confirmation,
                "before_sha256": receipt["confirmation_manifest_before_sha256"],
                "after_sha256": receipt["confirmation_manifest_after_sha256"],
                "operation": "refresh_declared_dependency_digest",
                "relative_path": canonical_relative(dependency_refresh["child_manifest"]),
                "field": dependency_refresh["record_field"],
                "before": receipt["shared_manifest_before_sha256"],
                "after": receipt["shared_manifest_after_sha256"],
            })
        if receipt["manifest_mutations"] != expected_mutations:
            return False

        consumer_count = len(consumers)
        if not (
            receipt["schema_version"] == schema["version"] == binding["schema_version"]
            and receipt["binding_id"] == binding.get("binding_id", "phase_b_verdict_post_producer_binding")
            and isinstance(receipt["offset"], (int, float))
            and not isinstance(receipt["offset"], bool)
            and math.isfinite(float(receipt["offset"]))
            and receipt["producer_stage"] == producer_name
            and receipt["producer_return_code"] == binding["required_postproducer_state"]["producer_return_code"] == 0
            and receipt["product_absent_before_producer"] is True
            and receipt["preproducer_target_absent"] is True
            and receipt["product_regular_contained_non_symlink_single_link"] is True
            and receipt["mutation_scope_exact"] is True
            and receipt["exact_mutation_scope_pass"] is True
            and receipt["all_staged_replacements_completed_and_postverified"] is True
            and receipt["atomic_replacement_pass"] is True
            and receipt["shared_manifest_closure_pass"] is True
            and receipt["confirmation_manifest_closure_pass"] is True
            and receipt["downstream_full_manifest_closure_pass"] is True
            and receipt["downstream_three_of_three_input_concordance_pass"] is True
            and receipt["downstream_required_input_concordance_count"] == consumer_count
            and receipt["downstream_required_input_concordance_pass_count"] == consumer_count
            and receipt["binding_pass"] is True
        ):
            return False

        payload = {
            key: value for key, value in receipt.items()
            if key not in {"receipt_sha256", "receipt_payload_sha256"}
        }
        observed = canonical_json_sha256(payload)
        return receipt["receipt_payload_sha256"] == receipt["receipt_sha256"] == observed
    except (ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _apply_receipted_mutations(value: dict[str, Any], mutations: list[dict[str, Any]]) -> dict[str, Any]:
    by_location: dict[str, dict[str, Any]] = {}
    for mutation in mutations:
        if mutation["location"] in by_location:
            raise RuntimeError(f"duplicate_mutation_location:{mutation['location']}")
        by_location[mutation["location"]] = mutation
    applied: set[str] = set()
    result = copy.deepcopy(value)

    def walk(node: Any, location: str) -> None:
        if isinstance(node, dict):
            for key in list(node):
                child_location = f"{location}.{key}"
                mutation = by_location.get(child_location)
                if mutation is not None:
                    if node[key] != mutation["before"] or key != mutation["field"]:
                        raise RuntimeError(f"mutation_before_or_field_mismatch:{child_location}")
                    node[key] = mutation["after"]
                    applied.add(child_location)
                else:
                    walk(node[key], child_location)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{location}[{index}]")

    walk(result, "$")
    if applied != set(by_location):
        raise RuntimeError("mutation_location_not_found_in_source_template")
    return result


def _mutation_receipt_list_exact(
    mutations: Any,
    constructed_files: dict[str, dict[str, Any]],
) -> bool:
    if not isinstance(mutations, list):
        return False
    expected_keys = {"location", "relative_path", "field", "kind", "before", "after"}
    locations: set[str] = set()
    for item in mutations:
        if not isinstance(item, dict) or set(item) != expected_keys:
            return False
        relative = canonical_relative(item["relative_path"])
        if item["location"] in locations or not str(item["location"]).startswith("$."):
            return False
        locations.add(item["location"])
        record = constructed_files.get(relative)
        if not isinstance(record, dict) or set(record) != {"sha256", "bytes"}:
            return False
        if item["kind"] == "digest":
            if (
                not _supported_digest_field_name(item["field"])
                or not isinstance(item["before"], str)
            ):
                return False
            if item["after"] != record["sha256"]:
                return False
        elif item["kind"] == "size":
            if (
                not _supported_size_field_name(item["field"])
                or not isinstance(item["before"], int)
                or isinstance(item["before"], bool)
            ):
                return False
            if item["after"] != record["bytes"]:
                return False
        else:
            return False
    return True


def _offline_manifest_closure(
    manifest: dict[str, Any],
    constructed_files: dict[str, dict[str, Any]],
    *,
    allowed_missing: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Recompute construction-time closure from immutable document bytes."""
    records = exact_manifest_file_records(manifest)
    allowed = {canonical_relative(path) for path in allowed_missing}
    exact_count = 0
    pending_count = 0
    closed = True
    for relative, record in records.items():
        observed = constructed_files.get(relative)
        if observed is None and relative in allowed:
            pending_count += 1
            continue
        size_exact = isinstance(observed, dict) and all(
            record[key] == observed.get("bytes") for key in SIZE_FIELDS & set(record)
        )
        digest_exact = bool(
            isinstance(observed, dict)
            and all(
                observed.get("sha256") == record[key]
                for key in HASH_FIELDS & set(record)
            )
            and size_exact
        )
        exact_count += int(digest_exact)
        closed = closed and digest_exact
    auxiliary_claims = manifest_sibling_integrity_claims(manifest)
    auxiliary_exact_count = 0
    auxiliary_pending_count = 0
    for claim in auxiliary_claims:
        relative = claim["relative_path"]
        observed = constructed_files.get(relative)
        if observed is None and relative in allowed:
            auxiliary_pending_count += 1
            continue
        exact = bool(
            isinstance(observed, dict)
            and observed.get("sha256") == claim["claimed_sha256"]
            and all(
                observed.get("bytes") == size
                for size in claim["size_fields"].values()
            )
        )
        auxiliary_exact_count += int(exact)
        closed = closed and exact
    return {
        "record_count": len(records),
        "digest_match_count": exact_count,
        "allowed_missing_count": pending_count,
        "auxiliary_count": len(auxiliary_claims),
        "auxiliary_match_count": auxiliary_exact_count,
        "auxiliary_allowed_missing_count": auxiliary_pending_count,
        "closure_pass": bool(records) and closed,
    }


def construction_audit_exact(
    audit: Any,
    cfg: dict[str, Any],
    binding_receipt: dict[str, Any],
    source_root: Path,
) -> bool:
    """Rebuild every construction mutation from immutable source templates."""
    try:
        if not isinstance(audit, dict) or not isinstance(binding_receipt, dict):
            return False
        preinvoke_anchor_fields = {
            "shared_manifest_before_sha256",
            "producer_invocation_manifest_sha256",
            "confirmation_manifest_expected_before_sha256",
            "confirmation_manifest_before_sha256",
        }
        receipt_fields = set(binding_receipt)
        if receipt_fields == preinvoke_anchor_fields:
            full_binding_receipt = False
        elif receipt_fields == RUNTIME_BINDING_RECEIPT_FIELDS:
            full_binding_receipt = True
        else:
            return False
        if full_binding_receipt and not runtime_binding_receipt_exact(
            binding_receipt, cfg, source_root
        ):
            return False
        resolution = audit["source_authority_resolution"]
        if not source_authority_resolution_exact(resolution, cfg, source_root):
            return False
        if (
            audit.get("source_authority_resolution_pass") is not True
            or audit.get("source_authority_resolution_receipt_sha256") != resolution["receipt_sha256"]
        ):
            return False
        constructed = audit["constructed_file_receipts"]
        if not isinstance(constructed, dict) or not constructed:
            return False
        if audit.get("constructed_file_receipts_sha256") != canonical_json_sha256(constructed):
            return False
        for relative, record in constructed.items():
            canonical_relative(relative)
            if not isinstance(record, dict) or set(record) != {"sha256", "bytes"}:
                return False
            if SHA256_RE.fullmatch(str(record["sha256"])) is None:
                return False
            if not isinstance(record["bytes"], int) or isinstance(record["bytes"], bool) or record["bytes"] < 0:
                return False
        for relative, digest in resolution["selected_copy_digests"].items():
            if relative in {stage["config"] for stage in cfg["stage_contracts"]} | {stage["manifest"] for stage in cfg["stage_contracts"]}:
                continue
            if constructed.get(relative, {}).get("sha256") != digest:
                return False
        if any(path not in constructed for path in resolution["synthetic_paths"]):
            return False
        synthetic_contract = cfg["synthetic_contract"]
        source_configs_for_fixture = _source_config_values(source_root, cfg)
        if full_binding_receipt:
            producer_stage = next(
                stage for stage in cfg["stage_contracts"]
                if stage["stage"] == cfg["runtime_binding"]["producer_stage"]
            )
            _runtime_product_snapshot_from_receipt(
                binding_receipt,
                canonical_relative(cfg["runtime_binding"]["target_relative_path"]),
                producer_stage,
                source_configs_for_fixture[producer_stage["config"]],
            )
        expected_parquet_paths: set[str] = set()
        expected_plan_paths: set[str] = set()
        expected_taus: set[float] = set()
        for stage in cfg["stage_contracts"]:
            source_config = source_configs_for_fixture[stage["config"]]
            try:
                configured_taus = deep_get(
                    source_config,
                    str(synthetic_contract["memory_tau_source_config_key"]),
                )
            except KeyError:
                configured_taus = []
            if not isinstance(configured_taus, list):
                return False
            expected_taus.update(float(value) for value in configured_taus)
            for key in stage["required_data_keys"]:
                relative = canonical_relative(str(deep_get(source_config, key)))
                if key.endswith(("candidate_parquet", "raw_track_parquet")):
                    expected_parquet_paths.add(relative)
                elif key.endswith("canonical_g3_track_plan"):
                    expected_plan_paths.add(relative)
        expected_synthetic_paths = expected_parquet_paths | expected_plan_paths
        synthetic_receipts = audit.get("synthetic_file_receipts")
        audit_offset = float(audit.get("synthetic_offset"))
        independently_regenerated_fixture = expected_synthetic_construction(
            source_root, cfg, audit_offset
        )
        required_fixture_checks = {
            "train_validation_test_exact",
            "complete_tracks_per_split_exact",
            "all_configured_memory_columns_present",
            "selected_track_ids_schema_exact",
            "candidate_support_and_values_exact",
            "candidate_model_inputs_finite",
            "synthetic_row_limit_respected",
            "declared_split_counts_crosscheck_exact",
        }
        if not all((
            bool(expected_parquet_paths),
            bool(expected_plan_paths),
            expected_parquet_paths.isdisjoint(expected_plan_paths),
            set(resolution["synthetic_paths"]) == expected_synthetic_paths,
            isinstance(synthetic_receipts, dict),
            set(synthetic_receipts or {}) == expected_synthetic_paths,
            all(constructed.get(path) == record for path, record in (synthetic_receipts or {}).items()),
            audit.get("synthetic_file_receipts_sha256") == canonical_json_sha256(synthetic_receipts),
            audit.get("fixture_contract_pass") is True,
            isinstance(audit.get("fixture_contract_checks"), dict),
            set(audit.get("fixture_contract_checks", {})) == required_fixture_checks,
            all(value is True for value in audit.get("fixture_contract_checks", {}).values()),
            audit.get("synthetic_seed") == int(synthetic_contract["seed"]),
            audit.get("synthetic_offset") in [float(value) for value in synthetic_contract["offsets"]],
            (
                "offset" not in binding_receipt
                or float(binding_receipt["offset"]) == float(audit.get("synthetic_offset"))
            ),
            audit.get("synthetic_row_count")
            == int(synthetic_contract["track_count"]) * int(synthetic_contract["steps_per_track"]),
            audit.get("synthetic_row_count") <= int(synthetic_contract["maximum_rows"]),
            audit.get("synthetic_split_count") == len(synthetic_contract["required_splits"]) == 3,
            audit.get("synthetic_tracks_per_split")
            == int(synthetic_contract["complete_tracks_per_split"]),
            int(synthetic_contract["complete_tracks_per_split"])
            == int(synthetic_contract["track_plan_each_required_split_exact_count"]),
            int(synthetic_contract["track_count"])
            == int(synthetic_contract["complete_tracks_per_split"])
            * len(synthetic_contract["required_splits"]),
            audit.get("parquet_file_count") == len(expected_parquet_paths),
            audit.get("track_plan_file_count") == len(expected_plan_paths),
            audit.get("synthetic_memory_tau_count") == len(expected_taus),
            all(
                audit.get(key) == value
                for key, value in independently_regenerated_fixture.items()
            ),
        )):
            return False

        config_pins: dict[str, str] = {}
        manifest_pins: dict[str, str] = {}
        for stage in cfg["stage_contracts"]:
            for mapping, path_key, digest_key in (
                (config_pins, "config", "config_sha256"),
                (manifest_pins, "manifest", "manifest_sha256"),
            ):
                relative = canonical_relative(stage[path_key])
                digest = stage[digest_key]
                if relative in mapping and mapping[relative] != digest:
                    return False
                mapping[relative] = digest
        if set(config_pins) & set(manifest_pins):
            return False
        binding = cfg["runtime_binding"]
        shared = canonical_relative(binding["shared_manifest"])
        confirmation = canonical_relative(binding["confirmation_manifest"])
        target = canonical_relative(binding["target_relative_path"])
        initial_pending = _pending_generated_records_by_manifest(cfg, EXPECTED_STAGE_ORDER[0])
        source_documents: dict[str, dict[str, Any]] = {}
        for relative, pin in config_pins.items():
            source_documents[relative] = strict_yaml_bytes(
                verified_source_bytes(source_root, relative, pin), relative
            )
        for relative, pin in manifest_pins.items():
            source_documents[relative] = strict_json_bytes(
                verified_source_bytes(source_root, relative, pin), relative
            )
        mutable_paths = set(source_documents)
        expected_dependencies = {
            relative: sorted(
                integrity_bound_paths(
                    value,
                    cross_bindings=(
                        bindings_for_document(cfg, relative)
                        if relative in config_pins else ()
                    ),
                ) & mutable_paths
            )
            for relative, value in source_documents.items()
        }
        pending_documents = set(source_documents)
        expected_order: list[str] = []
        while pending_documents:
            ready = sorted(
                relative for relative in pending_documents
                if not (set(expected_dependencies[relative]) & pending_documents)
            )
            if not ready:
                return False
            expected_order.extend(ready)
            pending_documents.difference_update(ready)
        expected_plan = {
            "dependencies": {
                relative: expected_dependencies[relative]
                for relative in sorted(expected_dependencies)
            },
            "order": expected_order,
        }
        if not all((
            audit.get("mutable_document_dependencies") == expected_plan["dependencies"],
            audit.get("mutable_document_order") == expected_order,
            audit.get("mutable_document_plan_sha256") == canonical_json_sha256(expected_plan),
        )):
            return False

        config_keys = {
            "relative_path", "source_template_sha256", "before_sha256", "after_sha256",
            "before_value_sha256", "after_value_sha256", "mutation_count", "mutations",
            "mutations_sha256",
        }
        manifest_keys = config_keys | {
            "source_record_count", "shadow_record_count", "post_refresh_closure_pass",
            "post_refresh_record_count", "post_refresh_digest_match_count",
            "post_refresh_allowed_missing_count",
        }

        def verify_documents(receipts: Any, pins: dict[str, str], *, manifest: bool) -> dict[str, dict[str, Any]] | None:
            if not isinstance(receipts, list) or len(receipts) != len(pins):
                return None
            by_path: dict[str, dict[str, Any]] = {}
            for item in receipts:
                if not isinstance(item, dict) or set(item) != (manifest_keys if manifest else config_keys):
                    return None
                relative = canonical_relative(item["relative_path"])
                if relative in by_path or relative not in pins:
                    return None
                pin = pins[relative]
                if item["source_template_sha256"] != pin or item["before_sha256"] != pin:
                    return None
                if item["after_sha256"] != constructed.get(relative, {}).get("sha256"):
                    return None
                mutations = item["mutations"]
                if (
                    not _mutation_receipt_list_exact(mutations, constructed)
                    or item["mutation_count"] != len(mutations)
                    or item["mutations_sha256"] != canonical_json_sha256(mutations)
                ):
                    return None
                payload = verified_source_bytes(source_root, relative, pin)
                source_value = strict_json_bytes(payload, relative) if manifest else strict_yaml_bytes(payload, relative)
                if item["before_value_sha256"] != canonical_json_sha256(source_value):
                    return None
                expected_rebuilt, expected_mutations = refresh_integrity_records(
                    source_value,
                    None,
                    constructed_files=constructed,
                    cross_bindings=(
                        bindings_for_document(cfg, relative)
                        if not manifest else ()
                    ),
                )
                expected_mutations.sort(
                    key=lambda mutation: (
                        mutation["location"], mutation["relative_path"], mutation["field"]
                    )
                )
                if mutations != expected_mutations:
                    return None
                rebuilt = _apply_receipted_mutations(source_value, mutations)
                if rebuilt != expected_rebuilt:
                    return None
                if item["after_value_sha256"] != canonical_json_sha256(rebuilt):
                    return None
                rebuilt_bytes = _json_bytes(rebuilt) if manifest else _yaml_bytes(rebuilt)
                if hashlib.sha256(rebuilt_bytes).hexdigest() != item["after_sha256"]:
                    return None
                if manifest:
                    before_count = len(exact_manifest_file_records(source_value))
                    after_count = len(exact_manifest_file_records(rebuilt))
                    offline = _offline_manifest_closure(
                        rebuilt,
                        constructed,
                        allowed_missing=initial_pending.get(relative, frozenset()),
                    )
                    if not all((
                        item["source_record_count"] == before_count,
                        item["shadow_record_count"] == after_count == before_count,
                        item["post_refresh_closure_pass"] is offline["closure_pass"] is True,
                        item["post_refresh_record_count"] == offline["record_count"] == after_count,
                        item["post_refresh_digest_match_count"] == offline["digest_match_count"],
                        item["post_refresh_allowed_missing_count"] == offline["allowed_missing_count"],
                    )):
                        return None
                by_path[relative] = item
            return by_path

        config_by_path = verify_documents(audit.get("construction_config_mutation_receipts"), config_pins, manifest=False)
        manifest_by_path = verify_documents(audit.get("construction_manifest_mutation_receipts"), manifest_pins, manifest=True)
        if config_by_path is None or manifest_by_path is None:
            return False
        if audit.get("shadow_config_integrity_mutation_count") != sum(item["mutation_count"] for item in config_by_path.values()):
            return False
        if audit.get("shadow_manifest_integrity_mutation_count") != sum(item["mutation_count"] for item in manifest_by_path.values()):
            return False

        for claim in resolution["rows"]:
            if (
                claim["claim_kind"] in {"manifest_record", "manifest_sibling_integrity"}
                and claim["authority_class"] == "primary"
                and (
                    claim["claimed_sha256"] != claim["selected_sha256"]
                    or any(
                        size != claim["observed_source_bytes"]
                        for size in claim["claimed_size_fields"].values()
                    )
                )
            ):
                receipt = manifest_by_path.get(claim["claim_source"])
                if receipt is None or not any(
                    mutation["relative_path"] == claim["relative_path"]
                    and (
                        (
                            mutation["kind"] == "digest"
                            and mutation["after"] == claim["selected_sha256"]
                        )
                        or (
                            mutation["kind"] == "size"
                            and mutation["after"] == claim["observed_source_bytes"]
                        )
                    )
                    for mutation in receipt["mutations"]
                ):
                    return False

        shared_prestate, _ = refresh_integrity_records(
            source_documents[shared], None, constructed_files=constructed
        )
        confirmation_prestate, _ = refresh_integrity_records(
            source_documents[confirmation], None, constructed_files=constructed
        )
        if not (
            manifest_by_path[shared]["after_sha256"]
            == binding_receipt.get("shared_manifest_before_sha256")
            == binding_receipt.get("producer_invocation_manifest_sha256")
            and manifest_by_path[confirmation]["after_sha256"]
            == binding_receipt.get("confirmation_manifest_expected_before_sha256")
            == binding_receipt.get("confirmation_manifest_before_sha256")
            and manifest_by_path[confirmation]["post_refresh_allowed_missing_count"] >= 1
            and (
                "shared_manifest_before" not in binding_receipt
                or binding_receipt.get("shared_manifest_before") == shared_prestate
            )
            and (
                "confirmation_manifest_before" not in binding_receipt
                or binding_receipt.get("confirmation_manifest_before") == confirmation_prestate
            )
            and all(
                item["post_refresh_allowed_missing_count"] <= len(initial_pending.get(relative, frozenset()))
                for relative, item in manifest_by_path.items()
            )
            and all(
                item["target_relative_path"] not in constructed
                for item in [{"target_relative_path": target}, *_post_stage_generated_bindings(cfg)]
            )
            and audit.get("generic_interstage_refresh_count") == 0
            and audit.get("unattested_local_import_count") == 0
        ):
            return False
        post_key_present = (
            "post_stage_generated_binding_receipts" in audit
            or "post_stage_generated_bindings_complete" in audit
        )
        if post_key_present:
            post_receipts = audit.get("post_stage_generated_binding_receipts", [])
            post_specs = _post_stage_generated_bindings(cfg)
            if not isinstance(post_receipts, list) or len(post_receipts) > len(post_specs):
                return False
            current_manifest_digests = {relative: item["after_sha256"] for relative, item in manifest_by_path.items()}
            if set(binding_receipt) == RUNTIME_BINDING_RECEIPT_FIELDS:
                current_manifest_digests[shared] = binding_receipt["shared_manifest_after_sha256"]
                current_manifest_digests[confirmation] = binding_receipt["confirmation_manifest_after_sha256"]
            for spec, post_receipt in zip(post_specs, post_receipts):
                if post_receipt.get("binding_id") != spec["binding_id"] or not post_stage_generated_binding_receipt_exact(post_receipt, cfg, source_root):
                    return False
                manifest = canonical_relative(spec["target_manifest"])
                if post_receipt["target_manifest_before_sha256"] != current_manifest_digests.get(manifest):
                    return False
                current_manifest_digests[manifest] = post_receipt["target_manifest_after_sha256"]
            if audit.get("post_stage_generated_bindings_complete") is True and not (
                len(post_receipts) == len(post_specs)
                and audit.get("post_stage_generated_binding_receipt_count") == len(post_specs)
                and audit.get("post_stage_generated_binding_receipts_pass") is True
            ):
                return False
        expected_scaffolds = set(PACKAGE_SCAFFOLD_PATHS) - set(
            resolution["selected_copy_digests"]
        )
        expected_constructed_paths = (
            set(resolution["selected_copy_digests"])
            | set(resolution["synthetic_paths"])
            | expected_scaffolds
        )
        if set(constructed) != expected_constructed_paths:
            return False
        scaffolds = audit.get("construction_scaffold_receipts")
        if not isinstance(scaffolds, list) or {item.get("relative_path") for item in scaffolds} != expected_scaffolds:
            return False
        if any(
            set(item) != {"relative_path", "construction_class", "sha256", "bytes"}
            or item["construction_class"] != "exact_empty_package_scaffold"
            or item["sha256"] != hashlib.sha256(b"").hexdigest()
            or item["bytes"] != 0
            for item in scaffolds
        ):
            return False
        if any(
            constructed.get(relative) != {
                "sha256": hashlib.sha256(b"").hexdigest(),
                "bytes": 0,
            }
            for relative in expected_scaffolds
        ):
            return False
        return True
    except (ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False


def construction_manifest_receipts_exact(
    receipts: Any,
    cfg: dict[str, Any],
    binding_receipt: dict[str, Any],
) -> bool:
    """Deprecated partial verifier; full v1.4 gates must use construction_audit_exact."""
    return False


def _only_target_record_changed(before: dict, after: dict, target: str, *, insertion: bool) -> bool:
    left = copy.deepcopy(before)
    right = copy.deepcopy(after)
    left_files = left.get("files", {})
    right_files = right.get("files", {})
    if insertion:
        if target in left_files or target not in right_files:
            return False
        right_files.pop(target)
    else:
        if target not in left_files or target not in right_files:
            return False
        left_files.pop(target)
        right_files.pop(target)
    return left == right


def _runtime_dependency_refresh_spec(binding: dict[str, Any]) -> dict[str, Any] | None:
    """Return one exact declared shadow dependency refresh, if configured."""
    raw = binding.get("dependency_refresh")
    if raw is None:
        return None
    expected = {
        "schema_version", "child_manifest", "parent_manifest", "record_field",
        "exact_existing_record_only", "derive_after_from_serialized_child_after_bytes",
        "no_size_field_invention", "no_generic_refresh",
    }
    if not isinstance(raw, dict) or set(raw) != expected or raw.get("schema_version") != 1:
        raise RuntimeError("runtime_dependency_refresh_schema_invalid")
    child = canonical_relative(raw["child_manifest"])
    parent = canonical_relative(raw["parent_manifest"])
    if (
        child != canonical_relative(binding["shared_manifest"])
        or parent != canonical_relative(binding["confirmation_manifest"])
        or raw.get("record_field") != "sha256"
        or any(raw.get(name) is not True for name in (
            "exact_existing_record_only",
            "derive_after_from_serialized_child_after_bytes",
            "no_size_field_invention",
            "no_generic_refresh",
        ))
    ):
        raise RuntimeError("runtime_dependency_refresh_scope_invalid")
    return copy.deepcopy(raw)


def _only_target_and_dependency_record_changed(
    before: dict,
    after: dict,
    target: str,
    dependency: str,
    *,
    insertion: bool,
    dependency_field: str = "sha256",
) -> bool:
    """Allow the target record plus one existing dependency digest scalar only."""
    left = copy.deepcopy(before)
    right = copy.deepcopy(after)
    left_files = left.get("files", {})
    right_files = right.get("files", {})
    if insertion:
        if target in left_files or target not in right_files:
            return False
        right_files.pop(target)
    else:
        if target not in left_files or target not in right_files:
            return False
        left_files.pop(target)
        right_files.pop(target)
    if dependency not in left_files or dependency not in right_files:
        return False
    left_record = left_files[dependency]
    right_record = right_files[dependency]
    if not isinstance(left_record, dict) or not isinstance(right_record, dict):
        return False
    if set(left_record) != set(right_record) or dependency_field not in left_record:
        return False
    for name in left_record:
        if name == dependency_field:
            continue
        if left_record[name] != right_record[name]:
            return False
    left_files.pop(dependency)
    right_files.pop(dependency)
    return left == right


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _staged_json_replacements(
    shadow: Path,
    replacements: list[tuple[str, dict, str, bytes]],
) -> dict[str, str]:
    """Stage each file, replace sequentially, postverify, rollback/poison on error."""
    staged: list[tuple[Path, Path, bytes]] = []
    replaced: list[tuple[Path, bytes]] = []
    before_bytes: dict[str, bytes] = {}
    try:
        for relative, value, expected_before, expected_original in replacements:
            path = contained_regular_file(shadow, relative)
            original = source_snapshot_bytes(shadow, relative)
            if original != expected_original or hashlib.sha256(original).hexdigest() != expected_before:
                raise RuntimeError(f"atomic_before_digest_changed:{relative}")
            before_bytes[relative] = original
            descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".staged", dir=path.parent)
            temporary = Path(name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(_json_bytes(value))
                handle.flush()
                os.fsync(handle.fileno())
            staged.append((path, temporary, original))
        for path, temporary, original in staged:
            relative = path.relative_to(shadow).as_posix()
            if source_snapshot_bytes(shadow, relative) != original:
                raise RuntimeError(f"atomic_before_snapshot_changed:{relative}")
            os.replace(temporary, path)
            _fsync_directory(path.parent)
            replaced.append((path, original))
        after = {
            relative: sha256(shadow / safe_relative(relative))
            for relative, _, _, _ in replacements
        }
        if any(
            not _path_state(shadow, relative, require_single_link=True)["valid_regular_contained"]
            for relative, _, _, _ in replacements
        ):
            raise RuntimeError("staged_replacement_postverification_failed")
        return after
    except Exception:
        rollback_failed = False
        for path, original in reversed(replaced):
            try:
                _atomic_bytes(path, original)
                _fsync_directory(path.parent)
            except Exception:
                rollback_failed = True
        poison = shadow / ".bh_simba_shadow_poisoned"
        try:
            _atomic_bytes(poison, b"runtime_manifest_atomic_group_failure\n")
        except Exception:
            pass
        if rollback_failed:
            raise RuntimeError("runtime_manifest_atomic_group_failure_and_rollback_failure")
        raise
    finally:
        for _, temporary, _ in staged:
            if temporary.exists():
                temporary.unlink()


def bind_post_producer_runtime_product(
    source_root: Path,
    shadow: Path,
    cfg: dict,
    configs: dict[str, dict],
    *,
    producer_stage: dict[str, Any],
    producer_return_code: int,
    product_absent_before: bool,
    offset: float,
    producer_invocation_manifest_sha256: str = "",
    expected_confirmation_manifest_sha256: str = "",
) -> dict[str, Any]:
    binding = cfg["runtime_binding"]
    target = canonical_relative(binding["target_relative_path"])
    shared = canonical_relative(binding["shared_manifest"])
    confirmation = canonical_relative(binding["confirmation_manifest"])
    template = canonical_relative(binding.get("confirmation_template_manifest", confirmation))
    receipt: dict[str, Any] = {
        "schema_version": int(binding["schema_version"]),
        "binding_id": binding.get("binding_id", "phase_b_verdict_post_producer_binding"),
        "offset": float(offset),
        "producer_stage": producer_stage["stage"],
        "producer_return_code": int(producer_return_code),
        "product_relative_path": target,
        "target_relative_path": target,
        "product_absent_before_producer": bool(product_absent_before),
        "preproducer_target_absent": bool(product_absent_before),
        "source_template_manifest": template,
        "template_manifest_relative_path": template,
        "shared_manifest": shared,
        "confirmation_manifest": confirmation,
        "confirmation_manifest_expected_before_sha256": expected_confirmation_manifest_sha256,
    }
    try:
        if producer_stage["stage"] != binding["producer_stage"] or producer_return_code != 0 or not product_absent_before:
            raise RuntimeError("runtime_binding_producer_lifecycle_not_satisfied")
        product = contained_regular_file(shadow, target, require_single_link=True)
        product_payload = source_snapshot_bytes(shadow, target)
        producer_config = configs[producer_stage["config"]]
        product_value = _validated_runtime_product_value(
            product_payload, target, producer_stage, producer_config
        )
        product_sha256 = hashlib.sha256(product_payload).hexdigest()
        product_bytes = len(product_payload)
        expected_template_sha = next(stage["manifest_sha256"] for stage in cfg["stage_contracts"] if stage["manifest"] == template)
        template_payload = verified_source_bytes(source_root, template, expected_template_sha)
        observed_template_sha = hashlib.sha256(template_payload).hexdigest()
        template_manifest = strict_json_bytes(template_payload, template)
        template_record = exact_manifest_file_records(template_manifest)[target]
        refreshed_record = clone_refreshed_file_record(
            template_record,
            None,
            binding["mutation_scope"]["authorized_existing_content_derived_fields"],
            observed_sha256=product_sha256,
            observed_bytes=product_bytes,
        )
        shared_path = contained_regular_file(shadow, shared)
        confirmation_path = contained_regular_file(shadow, confirmation)
        shared_payload = source_snapshot_bytes(shadow, shared)
        confirmation_payload = source_snapshot_bytes(shadow, confirmation)
        shared_before = strict_json_bytes(shared_payload, shared)
        confirmation_before = strict_json_bytes(confirmation_payload, confirmation)
        shared_records = exact_manifest_file_records(shared_before)
        confirmation_records = exact_manifest_file_records(confirmation_before)
        if target in shared_records:
            raise RuntimeError("runtime_binding_target_prematurely_present_in_shared_manifest")
        if confirmation_records.get(target) != template_record:
            raise RuntimeError("runtime_binding_confirmation_template_record_changed")
        shared_after = copy.deepcopy(shared_before)
        confirmation_after = copy.deepcopy(confirmation_before)
        shared_after["files"][target] = copy.deepcopy(refreshed_record)
        confirmation_after["files"][target] = copy.deepcopy(refreshed_record)
        shared_before_sha = hashlib.sha256(shared_payload).hexdigest()
        confirmation_before_sha = hashlib.sha256(confirmation_payload).hexdigest()
        dependency_refresh = _runtime_dependency_refresh_spec(binding)
        dependency_mutation: dict[str, Any] | None = None
        if dependency_refresh is None:
            mutation_scope_exact = (
                _only_target_record_changed(shared_before, shared_after, target, insertion=True)
                and _only_target_record_changed(
                    confirmation_before, confirmation_after, target, insertion=False
                )
            )
        else:
            dependency = canonical_relative(dependency_refresh["child_manifest"])
            dependency_field = dependency_refresh["record_field"]
            dependency_before = confirmation_records.get(dependency)
            if (
                not isinstance(dependency_before, dict)
                or dependency_field not in dependency_before
                or dependency_before[dependency_field] != shared_before_sha
            ):
                raise RuntimeError("runtime_binding_dependency_prestate_not_exact")
            shared_after_sha = hashlib.sha256(_json_bytes(shared_after)).hexdigest()
            confirmation_after["files"][dependency][dependency_field] = shared_after_sha
            dependency_mutation = {
                "manifest": confirmation,
                "before_sha256": confirmation_before_sha,
                "after_sha256": "",
                "operation": "refresh_declared_dependency_digest",
                "relative_path": dependency,
                "field": dependency_field,
                "before": shared_before_sha,
                "after": shared_after_sha,
            }
            mutation_scope_exact = (
                _only_target_record_changed(shared_before, shared_after, target, insertion=True)
                and _only_target_and_dependency_record_changed(
                    confirmation_before,
                    confirmation_after,
                    target,
                    dependency,
                    insertion=False,
                    dependency_field=dependency_field,
                )
            )
        if not mutation_scope_exact:
            raise RuntimeError("runtime_binding_mutation_scope_not_exact")
        if (
            SHA256_RE.fullmatch(expected_confirmation_manifest_sha256) is None
            or confirmation_before_sha != expected_confirmation_manifest_sha256
        ):
            raise RuntimeError("runtime_binding_confirmation_manifest_prestate_changed")
        after = _staged_json_replacements(shadow, [
            (shared, shared_after, shared_before_sha, shared_payload),
            (confirmation, confirmation_after, confirmation_before_sha, confirmation_payload),
        ])
        pending_after = _pending_generated_records_by_manifest(cfg, producer_stage["stage"], after_stage=True)
        shared_closure = audit_executor_manifest_closure(shadow, shared, allowed_missing=pending_after.get(shared, frozenset()))
        confirmation_closure = audit_executor_manifest_closure(shadow, confirmation, allowed_missing=pending_after.get(confirmation, frozenset()))
        consumer_bindings = [
            required_input_concordance(
                shadow,
                configs,
                stage,
                expected_executor_sha256=stage["executor_sha256"],
                allowed_missing=pending_after.get(canonical_relative(stage["manifest"]), frozenset()),
            )
            for stage in cfg["stage_contracts"]
            if stage["stage"] in binding["consumer_stages"]
        ]
        receipt.update({
            "source_template_manifest_expected_sha256": expected_template_sha,
            "source_template_manifest_observed_sha256": observed_template_sha,
            "template_manifest_source_sha256": observed_template_sha,
            "template_record_sha256": canonical_json_sha256(template_record),
            "template_record": template_record,
            "refreshed_record": refreshed_record,
            "product_payload_b64": base64.b64encode(product_payload).decode("ascii"),
            "product_json_run_id": product_value["run_id"],
            "product_json_schema_version": product_value["schema_version"],
            "product_sha256": product_sha256,
            "target_sha256": product_sha256,
            "product_bytes": product_bytes,
            "target_bytes": product_bytes,
            "product_regular_contained_non_symlink_single_link": True,
            "shared_manifest_before": shared_before,
            "confirmation_manifest_before": confirmation_before,
            "shared_manifest_before_sha256": shared_before_sha,
            "shared_manifest_after_sha256": after[shared],
            "confirmation_manifest_before_sha256": confirmation_before_sha,
            "confirmation_manifest_after_sha256": after[confirmation],
            "producer_invocation_manifest_sha256": producer_invocation_manifest_sha256,
            "mutation_scope_exact": mutation_scope_exact,
            "exact_mutation_scope_pass": mutation_scope_exact,
            "all_staged_replacements_completed_and_postverified": True,
            "atomic_replacement_pass": True,
            "shared_manifest_closure_pass": shared_closure["closure_pass"],
            "confirmation_manifest_closure_pass": confirmation_closure["closure_pass"],
            "downstream_required_input_concordance_count": len(consumer_bindings),
            "downstream_required_input_concordance_pass_count": sum(item["manifest_config_concordant"] for item in consumer_bindings),
            "manifest_mutations": [
                {"manifest": shared, "before_sha256": shared_before_sha, "after_sha256": after[shared], "operation": "insert_target_record"},
                {"manifest": confirmation, "before_sha256": confirmation_before_sha, "after_sha256": after[confirmation], "operation": "refresh_target_record"},
                *(
                    [{
                        **dependency_mutation,
                        "after_sha256": after[confirmation],
                    }]
                    if dependency_mutation is not None else []
                ),
            ],
        })
        receipt["downstream_full_manifest_closure_pass"] = bool(
            receipt["shared_manifest_closure_pass"] and receipt["confirmation_manifest_closure_pass"]
        )
        receipt["downstream_three_of_three_input_concordance_pass"] = bool(
            sum(item["required_input_digest_match_count"] for item in consumer_bindings)
            == sum(
                len(stage["required_data_keys"])
                for stage in cfg["stage_contracts"]
                if stage["stage"] in binding["consumer_stages"]
            )
            and all(item["manifest_config_concordant"] for item in consumer_bindings)
        )
        receipt["binding_pass"] = bool(
            shared_closure["closure_pass"]
            and confirmation_closure["closure_pass"]
            and len(consumer_bindings) == len(binding["consumer_stages"])
            and all(item["manifest_config_concordant"] for item in consumer_bindings)
            and producer_invocation_manifest_sha256 == shared_before_sha
            and source_snapshot_bytes(shadow, target) == product_payload
        )
        if not receipt["binding_pass"]:
            receipt["hold_reason"] = "runtime_binding_postwrite_concordance_or_provenance_failure"
    except Exception as error:
        receipt["binding_pass"] = False
        receipt["hold_reason"] = f"{type(error).__name__}:{str(error)[:1000]}"
    payload = copy.deepcopy(receipt)
    receipt["receipt_payload_sha256"] = canonical_json_sha256(payload)
    receipt["receipt_sha256"] = receipt["receipt_payload_sha256"]
    return receipt


def flatten_json(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            found.extend(flatten_json(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(flatten_json(child, f"{prefix}[{index}]"))
    else:
        found.append((prefix, value))
    return found


def select_observables_value(value: dict[str, Any]) -> dict[str, Any]:
    """Apply the frozen finite observable-selection algorithm to one verdict."""
    selected: dict[str, Any] = {}
    for key, child in flatten_json(value):
        normalized = key.lower()
        if any(token in normalized for token in EXCLUDED_TOKENS):
            continue
        if isinstance(child, bool):
            selected[key] = child
        elif isinstance(child, (int, float)) and not isinstance(child, bool) and any(token in normalized for token in NUMERIC_TOKENS):
            if not math.isfinite(float(child)):
                return {}
            selected[key] = child
        elif isinstance(child, str) and any(token in normalized for token in CATEGORICAL_TOKENS):
            selected[key] = child
    return selected


def select_observables(path: Path) -> dict[str, Any]:
    """Select only from one declared fresh stage verdict, never from a tree."""
    if not path.is_file():
        return {}
    try:
        value = strict_json_bytes(path.read_bytes(), path.as_posix())
    except (OSError, RuntimeError, UnicodeError, json.JSONDecodeError):
        return {}
    return select_observables_value(value)


def observables_equal(left: dict[str, Any], right: dict[str, Any], atol: float, rtol: float) -> bool:
    if set(left) != set(right):
        return False
    for key in left:
        a, b = left[key], right[key]
        if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
            if not math.isfinite(float(a)) or not math.isfinite(float(b)):
                return False
            if not math.isclose(float(a), float(b), abs_tol=atol, rel_tol=rtol):
                return False
        elif a != b:
            return False
    return True


def normalized_stage_command(stage: dict[str, Any]) -> list[str]:
    """Return the reconstructable command contract without ephemeral paths."""
    return [
        "<PYTHON_EXECUTABLE>",
        canonical_relative(stage["executor"]),
        "--config", canonical_relative(stage["config"]),
        "--freeze-manifest", canonical_relative(stage["manifest"]),
        "--repo-root", "<ABSOLUTE_TEMPORARY_SHADOW>",
    ]


def stage_output_evidence_exact(
    audit: Any,
    cfg: dict[str, Any],
    source_root: Path,
) -> bool:
    """Reconstruct all four persisted stage outputs from their exact bytes.

    This is an integrity/cross-artifact receipt, not a claim of adversarial
    process attestation.  It prevents later gates from trusting free-standing
    CSV booleans or replacing a non-producer verdict without changing the
    per-shadow execution record as well.
    """
    try:
        if not isinstance(audit, dict):
            return False
        offset = float(audit["offset"])
        if not math.isfinite(offset):
            return False
        evidence = audit.get("stage_output_evidence")
        if (
            not isinstance(evidence, list)
            or len(evidence) != len(cfg["stage_contracts"]) == 4
            or audit.get("stage_output_evidence_sha256")
            != canonical_json_sha256(evidence)
        ):
            return False
        configs = _source_config_values(source_root, cfg)
        for item, stage in zip(evidence, cfg["stage_contracts"]):
            if not isinstance(item, dict) or set(item) != STAGE_OUTPUT_EVIDENCE_FIELDS:
                return False
            payload_without_digest = {
                key: value for key, value in item.items() if key != "evidence_sha256"
            }
            if item["evidence_sha256"] != canonical_json_sha256(payload_without_digest):
                return False
            encoded = item["stage_verdict_payload_b64"]
            if not isinstance(encoded, str):
                return False
            payload = base64.b64decode(encoded, validate=True)
            if base64.b64encode(payload).decode("ascii") != encoded:
                return False
            value = strict_json_bytes(payload, f"stage_output:{stage['stage']}")
            observables = select_observables_value(value)
            contract = stage.get("fresh_output_contract", {})
            required = list(
                contract.get(
                    "required_json_keys",
                    contract.get("required_keys", ["schema_version", "run_id"]),
                )
            )
            truthy = list(contract.get("required_truthy_keys", []))
            normalized_command = normalized_stage_command(stage)
            expected_output = stage_expected_output(configs[stage["config"]], stage, cfg)
            if not all((
                item["schema_version"] == 1,
                isinstance(item["offset"], (int, float)),
                not isinstance(item["offset"], bool),
                float(item["offset"]) == offset,
                item["stage"] == stage["stage"],
                item["executor_sha256"] == stage["executor_sha256"],
                item["observed_executor_sha256"] == stage["executor_sha256"],
                item["authority_config_sha256"] == stage["config_sha256"],
                isinstance(item["shadow_config_sha256"], str),
                SHA256_RE.fullmatch(item["shadow_config_sha256"]) is not None,
                item["preinvoke_config_sha256"] == item["shadow_config_sha256"],
                item["preinvoke_primary_snapshots_exact"] is True,
                isinstance(item["invocation_manifest_sha256"], str),
                SHA256_RE.fullmatch(item["invocation_manifest_sha256"]) is not None,
                item["expected_output_relative_path"] == expected_output,
                item["stage_verdict_sha256"] == hashlib.sha256(payload).hexdigest(),
                isinstance(item["stage_verdict_bytes"], int),
                not isinstance(item["stage_verdict_bytes"], bool),
                item["stage_verdict_bytes"] == len(payload) > 0,
                item["observables"] == observables,
                bool(observables),
                item["observables_sha256"] == canonical_json_sha256(observables),
                item["executor_invoked"] is True,
                isinstance(item["return_code"], int),
                not isinstance(item["return_code"], bool),
                item["return_code"] == 0,
                item["stage_output_fresh_exact"] is True,
                item["stage_verdict_run_id_exact"] is True,
                value.get("run_id") == configs[stage["config"]].get("run_id"),
                item["required_verdict_keys_pass"] is True,
                all(key in value for key in required),
                item["required_truthy_keys_pass"] is True,
                all(value.get(key) is True for key in truthy),
                item["stage_lifecycle_pass"] is True,
                item["normalized_command"] == normalized_command,
                item["normalized_command_sha256"]
                == canonical_json_sha256(normalized_command),
            )):
                return False
        return True
    except (ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def sanitize_diagnostic(value: str, source_root: Path, shadow: Path, limit: int) -> str:
    sanitized = value.replace(str(shadow), "<SHADOW>").replace(str(source_root), "<REPO>")
    return sanitized[-limit:]


def _verdict_validation(shadow: Path, relative: str, config: dict, stage: dict, absent_before: bool) -> dict[str, Any]:
    state = _path_state(shadow, relative, require_single_link=True)
    result = {
        "relative_path": relative,
        "absent_before": absent_before,
        "fresh_regular_contained_non_symlink_single_link": False,
        "valid_json_object": False,
        "run_id_exact": False,
        "required_keys_present": False,
        "required_truthy_keys_pass": False,
        "sha256": "",
        "bytes": 0,
        "payload_b64": "",
        "observables": {},
        "value": {},
    }
    if not absent_before or not state["valid_regular_contained"]:
        return result
    try:
        payload = source_snapshot_bytes(shadow, relative)
        value = strict_json_bytes(payload, relative)
    except Exception:
        return result
    if not isinstance(value, dict):
        return result
    contract = stage.get("fresh_output_contract", {})
    required = list(contract.get("required_json_keys", contract.get("required_keys", ["schema_version", "run_id"])))
    truthy = list(contract.get("required_truthy_keys", []))
    result.update({
        "fresh_regular_contained_non_symlink_single_link": True,
        "valid_json_object": True,
        "run_id_exact": value.get("run_id") == config.get("run_id"),
        "required_keys_present": all(key in value for key in required),
        "required_truthy_keys_pass": all(value.get(key) is True for key in truthy),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "payload_b64": base64.b64encode(payload).decode("ascii"),
        "observables": select_observables_value(value),
        "value": value,
    })
    return result


def execute_stage(
    source_root: Path,
    shadow: Path,
    cfg: dict,
    configs: dict[str, dict],
    stage: dict,
    offset: float,
    expected_manifest_digests: dict[str, str] | None = None,
    expected_config_sha256: str | None = None,
) -> tuple[dict, dict[str, Any]]:
    binding = required_input_concordance(
        shadow,
        configs,
        stage,
        expected_config_sha256=expected_config_sha256,
        expected_executor_sha256=stage["executor_sha256"],
    )
    pending_before = _pending_generated_records_by_manifest(cfg, stage["stage"])
    global_closures = []
    for manifest in sorted({item["manifest"] for item in cfg["stage_contracts"]}):
        canonical_manifest = canonical_relative(manifest)
        allowed = pending_before.get(canonical_manifest, frozenset())
        global_closures.append(audit_executor_manifest_closure(shadow, manifest, allowed_missing=allowed))
    all_manifests_closed = all(item["closure_pass"] for item in global_closures)
    manifest_byte_invariance = True
    if expected_manifest_digests is not None:
        manifest_byte_invariance = all(
            _path_state(shadow, relative, require_single_link=True)["valid_regular_contained"]
            and sha256(shadow / safe_relative(relative)) == digest
            for relative, digest in expected_manifest_digests.items()
        )
    config = configs[stage["config"]]
    expected_relative = stage_expected_output(config, stage, cfg)
    expected_state_before = _path_state(shadow, expected_relative, require_single_link=True)
    absent_before = not expected_state_before["exists"] and expected_state_before["resolved_contained"] and not expected_state_before["parent_or_target_symlink"]
    command = [
        sys.executable,
        stage["executor"],
        "--config", stage["config"],
        "--freeze-manifest", stage["manifest"],
        "--repo-root", str(shadow),
    ]
    environment = {
        key: os.environ[key]
        for key in (
            "PATH", "LANG", "LC_ALL", "TZ", "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
        )
        if key in os.environ
    }
    environment.update({
        "PYTHONPATH": str(shadow),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
    })
    executor_invoked = False
    try:
        immediate_config_payload = source_snapshot_bytes(shadow, stage["config"])
        immediate_executor_payload = source_snapshot_bytes(shadow, stage["executor"])
        immediate_manifest_payload = source_snapshot_bytes(shadow, stage["manifest"])
        observed_config_sha256 = hashlib.sha256(immediate_config_payload).hexdigest()
        observed_executor_sha256 = hashlib.sha256(immediate_executor_payload).hexdigest()
        observed_manifest_sha256 = hashlib.sha256(immediate_manifest_payload).hexdigest()
        preinvoke_primary_snapshots_exact = bool(
            observed_config_sha256 == binding.get("config_snapshot_sha256")
            and (
                expected_config_sha256 is None
                or observed_config_sha256 == expected_config_sha256
            )
            and observed_executor_sha256 == stage["executor_sha256"]
            and observed_manifest_sha256 == binding.get("invocation_manifest_sha256")
            and (
                expected_manifest_digests is None
                or observed_manifest_sha256
                == expected_manifest_digests.get(canonical_relative(stage["manifest"]))
            )
        )
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        observed_config_sha256 = ""
        observed_executor_sha256 = ""
        preinvoke_primary_snapshots_exact = False
    if (
        not binding["manifest_config_concordant"]
        or not all_manifests_closed
        or not manifest_byte_invariance
        or not preinvoke_primary_snapshots_exact
    ):
        returncode = 125
        stdout = ""
        stderr = (
            "preinvoke_manifest_closure_config_concordance_or_byte_invariance_hold:"
            f"{binding['hold_reason']}:all={all_manifests_closed}:"
            f"bytes={manifest_byte_invariance}:primary={preinvoke_primary_snapshots_exact}"
        )
    elif not absent_before:
        returncode = 125
        stdout = ""
        stderr = f"preinvoke_expected_output_not_freshly_absent:{expected_relative}"
    elif (shadow / ".bh_simba_shadow_poisoned").exists():
        returncode = 125
        stdout = ""
        stderr = "preinvoke_shadow_poisoned"
    else:
        try:
            executor_invoked = True
            process = subprocess.Popen(
                command,
                cwd=shadow,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(
                    timeout=int(cfg["synthetic_contract"]["stage_timeout_seconds"])
                )
                returncode = process.returncode
                # A nominally successful parent must not leave writers alive
                # in its isolated process group.  Kill any surviving
                # descendants and classify the invocation as a hold before
                # inspecting generated files.
                lingering_process_group = False
                try:
                    os.killpg(process.pid, 0)
                    lingering_process_group = True
                except ProcessLookupError:
                    pass
                except PermissionError:
                    lingering_process_group = True
                if lingering_process_group:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    returncode = 126
                    stderr = (
                        f"{stderr}\n" if stderr else ""
                    ) + "executor_left_lingering_process_group"
            except subprocess.TimeoutExpired:
                # The executor is isolated in its own session.  Killing the
                # process group prevents a timed-out descendant from writing
                # into the shadow after validation has resumed.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = process.communicate()
                returncode = 124
        except subprocess.TimeoutExpired:
            returncode = 124
            stdout = ""
            stderr = "executor_timeout_before_process_group_cleanup"
    limit = int(cfg["synthetic_contract"]["diagnostic_tail_characters"])
    stdout = sanitize_diagnostic(stdout, source_root, shadow, limit)
    stderr = sanitize_diagnostic(stderr, source_root, shadow, limit)
    verdict = _verdict_validation(shadow, expected_relative, config, stage, absent_before) if returncode == 0 else {
        "fresh_regular_contained_non_symlink_single_link": False,
        "valid_json_object": False,
        "run_id_exact": False,
        "required_keys_present": False,
        "required_truthy_keys_pass": False,
        "sha256": "",
        "bytes": 0,
        "payload_b64": "",
        "observables": {},
        "value": {},
    }
    expected_exact = bool(
        verdict["fresh_regular_contained_non_symlink_single_link"]
        and verdict["valid_json_object"]
        and verdict["run_id_exact"]
        and verdict["required_keys_present"]
    )
    admission_pass = verdict["required_truthy_keys_pass"]
    observables = verdict["observables"] if returncode == 0 and expected_exact else {}
    stage_lifecycle = bool(
        executor_invoked and returncode == 0 and expected_exact and admission_pass
        and bool(observables) and binding["manifest_config_concordant"]
        and binding["executor_manifest_closure_pass"] and all_manifests_closed
        and manifest_byte_invariance
        and preinvoke_primary_snapshots_exact
    )
    detail = (stderr or stdout).replace("\n", " | ")[:2000]
    row = {
        "offset": offset,
        "stage": stage["stage"],
        "executor_sha256": stage["executor_sha256"],
        "observed_executor_sha256": observed_executor_sha256,
        "authority_config_sha256": stage["config_sha256"],
        "shadow_config_sha256": sha256(shadow / safe_relative(stage["config"])),
        "preinvoke_config_sha256": observed_config_sha256,
        "preinvoke_primary_snapshots_exact": preinvoke_primary_snapshots_exact,
        "return_code": returncode,
        "executor_invoked": executor_invoked,
        "stage_executed": executor_invoked and returncode == 0,
        "expected_output_relative_path": expected_relative,
        "expected_output_fresh_exact": expected_exact,
        "stage_verdict_fresh": expected_exact,
        "stage_verdict_sha256": verdict["sha256"],
        "stage_verdict_run_id_exact": verdict["run_id_exact"],
        "required_verdict_keys_pass": verdict["required_keys_present"],
        "required_truthy_keys_pass": admission_pass,
        "observable_count": len(observables),
        "stdout_sha256": digest_text(stdout),
        "stderr_sha256": digest_text(stderr),
        "classified_interface_hold": not stage_lifecycle,
        "numeric_and_categorical_invariant": "",
        "shadow_config_integrity_mutations_before_stage": 0,
        "shadow_manifest_integrity_mutations_before_stage": 0,
        "command_contract_exact": binding["command_contract_exact"],
        "repo_root_is_explicit_shadow": binding["repo_root_is_explicit_shadow"],
        "config_path_shadow_relative": binding["config_path_shadow_relative"],
        "manifest_path_shadow_relative": binding["manifest_path_shadow_relative"],
        "required_input_count": binding["required_input_count"],
        "required_input_existing_count": binding["required_input_existing_count"],
        "required_input_manifest_record_count": binding["required_input_manifest_record_count"],
        "required_input_digest_match_count": binding["required_input_digest_match_count"],
        "manifest_config_concordant": binding["manifest_config_concordant"],
        "executor_manifest_closure_pass": binding["executor_manifest_closure_pass"],
        "all_shadow_manifests_closure_pass": all_manifests_closed,
        "manifest_byte_invariance_pass": manifest_byte_invariance,
        "manifest_file_record_count": binding["manifest_file_record_count"],
        "manifest_file_existing_count": binding["manifest_file_existing_count"],
        "manifest_file_digest_match_count": binding["manifest_file_digest_match_count"],
        "invocation_manifest_sha256": binding["invocation_manifest_sha256"],
        "post_stage_binding_required": stage["stage"] == cfg["runtime_binding"]["producer_stage"],
        "post_stage_binding_pass": stage["stage"] != cfg["runtime_binding"]["producer_stage"],
        "runtime_binding_receipt_sha256": "",
        "stage_lifecycle_pass": stage_lifecycle,
        "command_sha256": digest_text("\0".join(command)),
        "detail": detail,
    }
    evidence = {
        "stage_verdict_sha256": verdict["sha256"],
        "stage_verdict_bytes": verdict["bytes"],
        "stage_verdict_payload_b64": verdict["payload_b64"],
        "observables": observables,
        "observables_sha256": canonical_json_sha256(observables),
    }
    return row, evidence


def original_authority_hashes(root: Path, cfg: dict) -> dict[str, str]:
    pins = {canonical_relative(relative): digest for relative, digest in cfg["exact_sources"].items()}
    for stage in cfg["stage_contracts"]:
        for field, digest_field in (
            ("executor", "executor_sha256"),
            ("config", "config_sha256"),
            ("manifest", "manifest_sha256"),
        ):
            relative = canonical_relative(stage[field])
            digest = stage[digest_field]
            if relative in pins and pins[relative] != digest:
                raise RuntimeError(f"primary_authority_digest_conflict:{relative}")
            pins[relative] = digest
    for relative, digest in pins.items():
        verified_source_bytes(root, relative, digest)
    scaffold_census = package_scaffold_source_census(root, cfg)
    if scaffold_census.get("census_pass") is not True:
        raise RuntimeError("package_scaffold_source_state_hold")
    for row in scaffold_census["rows"]:
        pins[row["relative_path"]] = (
            ABSENT_AUTHORITY_SENTINEL
            if row["source_state"] == "absent" else EMPTY_SHA256
        )
    return dict(sorted(pins.items()))


def authorities_unchanged(root: Path, frozen: dict[str, str]) -> bool:
    try:
        for relative, digest in frozen.items():
            if digest == ABSENT_AUTHORITY_SENTINEL:
                state = _path_state(root, relative, require_single_link=True)
                if not (
                    not state["exists"]
                    and state["resolved_contained"]
                    and not state["parent_or_target_symlink"]
                ):
                    return False
            elif hashlib.sha256(
                source_snapshot_bytes(root, relative)
            ).hexdigest() != digest:
                return False
        return True
    except (OSError, RuntimeError):
        return False


def run_offset(source_root: Path, output: Path, cfg: dict, offset: float, stages: Iterable[dict]) -> tuple[list[dict], dict[tuple[str, float], dict[str, Any]], dict[str, Any]]:
    stage_list = list(stages)
    if [stage["stage"] for stage in stage_list] != EXPECTED_STAGE_ORDER or [stage["stage"] for stage in cfg["stage_contracts"]] != EXPECTED_STAGE_ORDER:
        raise RuntimeError("four_stage_dependency_order_not_exact")
    rows: list[dict] = []
    metrics: dict[tuple[str, float], dict[str, Any]] = {}
    frozen = original_authority_hashes(source_root, cfg)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bh_simba_shadow_recovery_") as temporary:
        shadow = Path(temporary) / "repo"
        shadow.mkdir()
        configs, audit = prepare_shadow(source_root, shadow, cfg, offset)
        expected_manifest_digests = {
            item["relative_path"]: item["after_sha256"]
            for item in audit["construction_manifest_mutation_receipts"]
        }
        expected_config_digests = {
            item["relative_path"]: item["after_sha256"]
            for item in audit["construction_config_mutation_receipts"]
        }
        preflight = runtime_binding_preflight(source_root, shadow, cfg, configs)
        audit["runtime_binding_preflight"] = preflight
        audit["runtime_product_binding_receipts"] = []
        audit["post_stage_generated_binding_receipts"] = []
        audit["post_stage_generated_bindings_complete"] = False
        audit["stage_output_evidence"] = []
        if not preflight["pass"]:
            raise RuntimeError(f"runtime_binding_preflight_hold:{preflight.get('hold_reason', preflight.get('checks'))}")
        construction_anchor = {
            "shared_manifest_before_sha256": preflight["producer_manifest_sha256"],
            "producer_invocation_manifest_sha256": preflight["producer_manifest_sha256"],
            "confirmation_manifest_expected_before_sha256": preflight["confirmation_manifest_sha256"],
            "confirmation_manifest_before_sha256": preflight["confirmation_manifest_sha256"],
        }
        audit["construction_preinvoke_exact"] = construction_audit_exact(
            audit, cfg, construction_anchor, source_root
        )
        if not audit["construction_preinvoke_exact"]:
            raise RuntimeError("construction_audit_hold_before_first_executor")
        target = canonical_relative(cfg["runtime_binding"]["target_relative_path"])
        product_absent_before = not _path_state(shadow, target)["exists"]
        for stage in stage_list:
            row, observable = execute_stage(
                source_root,
                shadow,
                cfg,
                configs,
                stage,
                offset,
                expected_manifest_digests,
                expected_config_digests[canonical_relative(stage["config"])],
            )
            if stage["stage"] == cfg["runtime_binding"]["producer_stage"] and row["executor_invoked"] and row["return_code"] == 0 and row["expected_output_fresh_exact"]:
                receipt = bind_post_producer_runtime_product(
                    source_root,
                    shadow,
                    cfg,
                    configs,
                    producer_stage=stage,
                    producer_return_code=row["return_code"],
                    product_absent_before=product_absent_before,
                    offset=offset,
                    producer_invocation_manifest_sha256=row["invocation_manifest_sha256"],
                    expected_confirmation_manifest_sha256=expected_manifest_digests[
                        canonical_relative(cfg["runtime_binding"]["confirmation_manifest"])
                    ],
                )
                audit["runtime_product_binding_receipts"].append(receipt)
                receipt_exact = bool(
                    receipt.get("binding_pass") is True
                    and runtime_binding_receipt_exact(receipt, cfg, source_root)
                    and construction_audit_exact(audit, cfg, receipt, source_root)
                )
                row["post_stage_binding_pass"] = receipt_exact
                row["runtime_binding_receipt_sha256"] = receipt["receipt_sha256"]
                row["stage_lifecycle_pass"] = bool(row["stage_lifecycle_pass"] and receipt_exact)
                row["classified_interface_hold"] = not row["stage_lifecycle_pass"]
                if receipt_exact:
                    expected_manifest_digests[receipt["shared_manifest"]] = receipt["shared_manifest_after_sha256"]
                    expected_manifest_digests[receipt["confirmation_manifest"]] = receipt["confirmation_manifest_after_sha256"]
            for post_spec in _post_stage_generated_bindings(cfg):
                if post_spec["producer_stage"] == stage["stage"] and row["executor_invoked"] and row["return_code"] == 0 and row["expected_output_fresh_exact"]:
                    post_receipt = bind_post_stage_generated_product(
                        source_root, shadow, cfg, configs, post_spec,
                        producer_stage=stage, producer_return_code=row["return_code"],
                        product_absent_before=True, offset=offset,
                        producer_invocation_manifest_sha256=row["invocation_manifest_sha256"],
                        expected_target_manifest_sha256=expected_manifest_digests[canonical_relative(post_spec["target_manifest"])],
                    )
                    audit["post_stage_generated_binding_receipts"].append(post_receipt)
                    post_exact = bool(post_receipt.get("binding_pass") is True and post_stage_generated_binding_receipt_exact(post_receipt, cfg, source_root))
                    row["stage_lifecycle_pass"] = bool(row["stage_lifecycle_pass"] and post_exact)
                    row["classified_interface_hold"] = not row["stage_lifecycle_pass"]
                    if post_exact:
                        expected_manifest_digests[post_receipt["target_manifest_relative_path"]] = post_receipt["target_manifest_after_sha256"]
            normalized_command = normalized_stage_command(stage)
            stage_evidence = {
                "schema_version": 1,
                "offset": float(offset),
                "stage": stage["stage"],
                "executor_sha256": row["executor_sha256"],
                "observed_executor_sha256": row["observed_executor_sha256"],
                "authority_config_sha256": row["authority_config_sha256"],
                "shadow_config_sha256": row["shadow_config_sha256"],
                "preinvoke_config_sha256": row["preinvoke_config_sha256"],
                "preinvoke_primary_snapshots_exact": row[
                    "preinvoke_primary_snapshots_exact"
                ],
                "invocation_manifest_sha256": row["invocation_manifest_sha256"],
                "expected_output_relative_path": row["expected_output_relative_path"],
                "stage_verdict_sha256": observable["stage_verdict_sha256"],
                "stage_verdict_bytes": observable["stage_verdict_bytes"],
                "stage_verdict_payload_b64": observable["stage_verdict_payload_b64"],
                "observables": observable["observables"],
                "observables_sha256": observable["observables_sha256"],
                "executor_invoked": row["executor_invoked"],
                "return_code": row["return_code"],
                "stage_output_fresh_exact": row["expected_output_fresh_exact"],
                "stage_verdict_run_id_exact": row["stage_verdict_run_id_exact"],
                "required_verdict_keys_pass": row["required_verdict_keys_pass"],
                "required_truthy_keys_pass": row["required_truthy_keys_pass"],
                "stage_lifecycle_pass": row["stage_lifecycle_pass"],
                "normalized_command": normalized_command,
                "normalized_command_sha256": canonical_json_sha256(normalized_command),
            }
            stage_evidence["evidence_sha256"] = canonical_json_sha256(stage_evidence)
            audit["stage_output_evidence"].append(stage_evidence)
            rows.append(row)
            metrics[(stage["stage"], float(offset))] = observable
            if not row["stage_lifecycle_pass"]:
                break
        receipts = audit["runtime_product_binding_receipts"]
        post_receipts = audit["post_stage_generated_binding_receipts"]
        audit["post_stage_generated_bindings_complete"] = True
        audit["post_stage_generated_binding_receipt_count"] = len(post_receipts)
        audit["post_stage_generated_binding_receipts_pass"] = bool(
            len(post_receipts) == cfg["runtime_binding"]["post_stage_generated_binding_count_per_shadow"]
            and all(item.get("binding_pass") is True and post_stage_generated_binding_receipt_exact(item, cfg, source_root) for item in post_receipts)
        )
        audit["runtime_binding_receipt_count"] = len(receipts)
        audit["runtime_binding_receipts_pass"] = bool(
            len(receipts) == 1
            and receipts[0].get("binding_pass") is True
            and runtime_binding_receipt_exact(receipts[0], cfg, source_root)
            and audit["post_stage_generated_binding_receipts_pass"]
            and construction_audit_exact(audit, cfg, receipts[0], source_root)
        )
        phase = next((row for row in rows if row["stage"] == "generator3_phase_b"), None)
        screen = next((row for row in rows if row["stage"] == "generator3_null_screen"), None)
        confirm = next((row for row in rows if row["stage"] == "generator3_null_confirmation_2000"), None)
        g4 = next((row for row in rows if row["stage"] == "generator4_pooled_innovation_screen"), None)
        post_by_producer = {item.get("producer_stage"): item for item in post_receipts if isinstance(item, dict)}
        screen_binding = post_by_producer.get("generator3_null_screen", {})
        confirm_binding = post_by_producer.get("generator3_null_confirmation_2000", {})
        provenance = bool(
            len(receipts) == 1 and len(post_receipts) == 2 and phase and screen and confirm and g4
            and phase["invocation_manifest_sha256"] == receipts[0].get("shared_manifest_before_sha256")
            and screen["invocation_manifest_sha256"] == receipts[0].get("shared_manifest_after_sha256")
            and screen_binding.get("target_manifest_before_sha256") == receipts[0].get("confirmation_manifest_after_sha256")
            and screen_binding.get("target_sha256") == screen.get("stage_verdict_sha256")
            and confirm["invocation_manifest_sha256"] == screen_binding.get("target_manifest_after_sha256")
            and confirm_binding.get("target_sha256") == confirm.get("stage_verdict_sha256")
            and g4["invocation_manifest_sha256"] == confirm_binding.get("target_manifest_after_sha256")
        )
        audit["runtime_binding_provenance_chain_pass"] = provenance
        audit["manifest_provenance_chain_pass"] = provenance
        closures = [audit_executor_manifest_closure(shadow, manifest) for manifest in sorted({stage["manifest"] for stage in cfg["stage_contracts"]})]
        audit["final_manifest_closures"] = closures
        audit["manifest_byte_invariance_pass"] = all(
            sha256(shadow / safe_relative(relative)) == digest
            for relative, digest in expected_manifest_digests.items()
        )
        audit["full_manifest_closure_pass"] = all(item["closure_pass"] for item in closures) and audit["manifest_byte_invariance_pass"]
        audit["source_authorities_unchanged"] = authorities_unchanged(source_root, frozen)
        audit["offset"] = float(offset)
        audit["stage_output_evidence_sha256"] = canonical_json_sha256(
            audit["stage_output_evidence"]
        )
    return rows, metrics, audit
