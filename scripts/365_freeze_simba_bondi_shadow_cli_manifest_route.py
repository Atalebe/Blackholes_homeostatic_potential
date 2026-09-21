#!/usr/bin/env python3
"""Freeze Run 220-R3 and atomically write Entry 128 only after a complete exact route."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Any

from bh_simba_runtime_manifest_common_v1_4 import (
    prior_attempt_custody_exact,
    prior_v1_3_attempt_custody_exact,
    read_json,
    release_field_authority,
    sha256,
    stable_csv_snapshot,
    stable_json_snapshot,
    utc_now,
)
from bh_simba_shadow_exact_binding_source_state_lifecycle_recovery_v1_4 import (
    resolve_source_manifest_claims,
    safe_relative,
    source_authority_resolution_exact,
)


HEX64 = re.compile(r"[0-9a-f]{64}")
CLAIM_CAP = (
    "synthetic_only_exact_TNG_CLI_manifest_interface_and_selected_observable_admission_"
    "sensitivity_to_tested_latent_signal_offsets_"
    "with_writer_semantics_physical_units_population_equivalence_SIMBA_coordinate_tracks_"
    "zero_policy_adapter_and_scientific_memory_execution_closed"
)
TRANSACTION_KEYS = {
    "transaction_id",
    "final_route_path",
    "final_route_run_id",
    "final_route_staging_path",
    "protocol_entry_path",
    "protocol_entry_sha256",
    "protocol_entry_bytes",
    "protocol_entry_staging_path",
    "owner_marker_path",
    "owner_marker_sha256",
    "owner_marker_bytes",
    "matrix_verdict_sha256",
    "adjudication_verdict_sha256",
}


def fsync_directory(path: Path) -> None:
    """Durably record same-directory namespace mutations."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def stable_regular_bytes(
    root: Path,
    path: Path,
    *,
    allowed_link_counts: frozenset[int] = frozenset({1}),
) -> bytes:
    """Take one stable, contained, non-symlink, single-link file snapshot."""
    root = root.resolve(strict=True)
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise RuntimeError("transaction_file_outside_repository") from error
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise RuntimeError("unsafe_transaction_file_ancestry")
        current.resolve(strict=True).relative_to(root)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink not in allowed_link_counts:
            raise RuntimeError("unsafe_transaction_file")
        chunks: list[bytes] = []
        while True:
            block = os.read(descriptor, 8 * 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(descriptor)
        current_leaf = path.lstat()
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_mode,
            value.st_nlink,
        )
        if identity(before) != identity(after) or (
            after.st_dev,
            after.st_ino,
        ) != (current_leaf.st_dev, current_leaf.st_ino):
            raise RuntimeError("transaction_file_changed_during_snapshot")
        current = root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink() or not current.is_dir():
                raise RuntimeError("transaction_file_ancestry_changed_during_snapshot")
            current.resolve(strict=True).relative_to(root)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def strict_json_object(payload: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise ValueError(f"duplicate_json_key:{key}")
            value[key] = child
        return value

    def reject_constant(value: str) -> Any:
        raise ValueError(f"nonfinite_json_constant:{value}")

    value = json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=unique,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("transaction_json_root_not_object")
    return value


def transaction_staging_path(entry_path: Path, transaction_id: str) -> Path:
    if HEX64.fullmatch(transaction_id) is None:
        raise RuntimeError("invalid_entry_transaction_id")
    return entry_path.parent / f".{entry_path.name}.{transaction_id}.pending"


def owner_marker_snapshot(root: Path, output: Path, marker_path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        relative = marker_path.relative_to(root).as_posix()
    except ValueError as error:
        raise RuntimeError("transaction_owner_marker_outside_repository") from error
    if marker_path.parent != output or not marker_path.name.startswith(
        ".runtime_manifest_recovery_current_"
    ) or not marker_path.name.endswith(".marker"):
        raise RuntimeError("transaction_owner_marker_path_not_exact")
    payload = stable_regular_bytes(root, marker_path)
    marker = strict_json_object(payload)
    if set(marker) != {"schema_version", "run_token", "owner_nonce"}:
        raise RuntimeError("transaction_owner_marker_schema_not_exact")
    token = marker.get("run_token")
    if (
        marker.get("schema_version") != 1
        or isinstance(marker.get("schema_version"), bool)
        or not isinstance(token, str)
        or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z_[0-9]+", token)
        or marker_path.name != f".runtime_manifest_recovery_current_{token}.marker"
        or not isinstance(marker.get("owner_nonce"), str)
        or HEX64.fullmatch(marker["owner_nonce"]) is None
        or len(payload) > 512
    ):
        raise RuntimeError(f"transaction_owner_marker_content_not_exact:{relative}")
    return payload, marker


def independently_validate_matrix_audits(
    root: Path,
    output: Path,
    matrix: dict[str, Any],
    cfg: dict[str, Any],
) -> bool:
    path = Path(__file__).with_name("364_adjudicate_simba_bondi_shadow_translation.py")
    if path.is_symlink() or not path.is_file():
        return False
    try:
        csv_rows, _, csv_digest = stable_csv_snapshot(
            output / cfg["outputs"]["matrix_results"]
        )
        if (
            csv_digest
            != matrix.get("artifacts", {})
            .get(cfg["outputs"]["matrix_results"], {})
            .get("sha256")
        ):
            return False
        spec = importlib.util.spec_from_file_location("bh_simba_v14_adjudication_verifier", path)
        if spec is None or spec.loader is None:
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return bool(
            module.matrix_csv_exact(output, cfg, matrix, csv_rows)
            and module.matrix_audits_exact(
                matrix, cfg, output, root, csv_rows
            )
        )
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False


def independently_validate_adjudication_live_replay(
    adjudication: dict[str, Any],
    matrix: dict[str, Any],
    cfg: dict[str, Any],
    root: Path,
) -> bool:
    """Bind Run 220 to Run 219's honest-code replay receipt and audit digest."""
    path = Path(__file__).with_name("364_adjudicate_simba_bondi_shadow_translation.py")
    if path.is_symlink() or not path.is_file():
        return False
    try:
        spec = importlib.util.spec_from_file_location(
            "bh_simba_v14_live_replay_receipt_verifier", path
        )
        if spec is None or spec.loader is None:
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return bool(
            module.live_replay_receipt_exact(adjudication, cfg, matrix, root)
        )
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False


def safe_existing_directory(root: Path, path: Path) -> bool:
    """Require a contained directory reached without any symlink component."""
    try:
        root = root.resolve(strict=True)
        relative = path.relative_to(root)
        if not relative.parts:
            return False
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink() or not current.is_dir():
                return False
            current.resolve(strict=True).relative_to(root)
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def paths_collide(left: str, right: str) -> bool:
    """Treat equality or a file/ancestor overlap as a custody collision."""
    left_path = safe_relative(left)
    right_path = safe_relative(right)
    return left_path == right_path or left_path in right_path.parents or right_path in left_path.parents


def configured_output_targets(cfg: dict[str, Any]) -> tuple[set[str], str]:
    """Resolve every configured file output; evidence/verdict names must be basenames."""
    outputs = cfg["outputs"]
    directory = safe_relative(outputs["directory"])
    targets: set[str] = set()
    declared_names = []
    for key, value in outputs.items():
        if key in {"directory", "protocol_entry"}:
            continue
        relative = safe_relative(value)
        if len(relative.parts) != 1:
            raise RuntimeError(f"configured_output_not_basename:{key}")
        declared_names.append(relative.as_posix())
        targets.add((directory / relative).as_posix())
    if len(targets) != len(declared_names):
        raise RuntimeError("configured_output_target_collision")
    protocol = safe_relative(outputs["protocol_entry"]).as_posix()
    return targets, protocol


def outputs_disjoint_from_authorities(
    outputs: set[str],
    protocol: str,
    authorities: set[str],
) -> tuple[bool, bool]:
    output_collision_free = all(
        not paths_collide(target, authority)
        for target in outputs
        for authority in authorities
    )
    entry_collision_free = all(
        not paths_collide(protocol, target)
        for target in outputs | authorities
    )
    return output_collision_free, entry_collision_free


def current_output_path(root: Path, output: Path, supplied: str, filename: str) -> tuple[Path, bool]:
    candidate = root / safe_relative(supplied)
    symlink = candidate.is_symlink()
    path = candidate.resolve()
    return path, path == (output / filename).resolve() and path.is_file() and not symlink


def records_exact(root: Path, output: Path, item: dict[str, Any]) -> bool:
    records = item.get("artifacts")
    base = output
    if records is None:
        records = item.get("files")
        base = root
    if not isinstance(records, dict) or not records:
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


def safe_entry_target(root: Path, path: Path, *, create_parents: bool) -> bool:
    """Require a repository-contained target with no symlinked ancestor."""
    try:
        root = root.resolve(strict=True)
        relative = path.relative_to(root)
        if not relative.parts:
            return False
        current = root
        for part in relative.parts[:-1]:
            current = current / part
            if os.path.lexists(current):
                if current.is_symlink() or not current.is_dir():
                    return False
            elif create_parents:
                parent = current.parent
                current.mkdir()
                fsync_directory(parent)
                fsync_directory(current)
            else:
                return False
            current.resolve(strict=True).relative_to(root)
        if os.path.lexists(path) and (path.is_symlink() or not path.is_file()):
            return False
        path.parent.resolve(strict=True).relative_to(root)
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def protocol_entry_collision_free(
    protocol_relative: str,
    route_records: dict[str, dict[str, str]],
    authority_records: dict[str, dict[str, str]],
    protected_targets: set[str],
) -> bool:
    return (
        protocol_relative not in route_records
        and protocol_relative not in authority_records
        and protocol_relative not in protected_targets
    )


def atomic_text(path: Path, text: str, *, root: Path) -> None:
    """Install a complete text artifact with one same-directory atomic replacement."""
    if not safe_entry_target(root, path, create_parents=True):
        raise RuntimeError("unsafe_protocol_entry_target")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary_name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        fsync_directory(path.parent)
        if not safe_entry_target(root, path, create_parents=False):
            raise RuntimeError("unsafe_protocol_entry_target_before_replace")
        os.replace(temporary_name, path)
        temporary_name = None
        fsync_directory(path.parent)
        if not safe_entry_target(root, path, create_parents=False):
            raise RuntimeError("unsafe_protocol_entry_target_after_replace")
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
                fsync_directory(path.parent)
            except FileNotFoundError:
                pass


def install_text_exclusive(
    path: Path,
    text: str,
    *,
    root: Path,
    transaction_id: str,
) -> None:
    """Atomically publish complete bytes without ever replacing an existing target."""
    if not safe_entry_target(root, path, create_parents=True):
        raise RuntimeError("unsafe_exclusive_install_target")
    if os.path.lexists(path):
        raise FileExistsError(f"exclusive_install_target_exists:{path}")
    staging = transaction_staging_path(path, transaction_id)
    if not safe_entry_target(root, staging, create_parents=False):
        raise RuntimeError("unsafe_exclusive_install_staging_target")
    if os.path.lexists(staging):
        raise FileExistsError(f"exclusive_install_staging_exists:{staging}")
    payload = text.encode("utf-8")
    descriptor: int | None = None
    try:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(staging, flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        fsync_directory(path.parent)
        if stable_regular_bytes(root, staging) != payload:
            raise RuntimeError("exclusive_install_staging_snapshot_mismatch")
        os.link(staging, path, follow_symlinks=False)
        fsync_directory(path.parent)
        # The published name was created from complete, fsync'd bytes. Remove
        # the deterministic staging link so accepted artifacts remain single-link.
        staging.unlink()
        fsync_directory(path.parent)
        if stable_regular_bytes(root, path) != payload:
            raise RuntimeError("exclusive_install_snapshot_mismatch")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if os.path.lexists(staging):
            try:
                staging.unlink()
                fsync_directory(path.parent)
            except (OSError, RuntimeError):
                pass
        # Never remove an installed canonical target here. A durable pending
        # journal owns recovery after any post-link failure or process crash.


def validate_entry_transaction(
    root: Path,
    output: Path,
    entry_path: Path,
    final_route_path: Path,
    expected_run_id: str,
    *,
    allowed_states: set[str],
    require_entry: bool,
    expected_owner_marker: Path | None = None,
) -> dict[str, Any]:
    """Validate one exact pending/committed Entry transaction from stable bytes."""
    final_payload = stable_regular_bytes(
        root,
        final_route_path,
        allowed_link_counts=frozenset({1, 2}),
    )
    route = strict_json_object(final_payload)
    state = route.get("entry_install_transaction_state")
    if state not in allowed_states:
        raise RuntimeError("entry_transaction_state_not_allowed")
    if route.get("run_id") != expected_run_id:
        raise RuntimeError("entry_transaction_run_id_mismatch")
    transaction = route.get("entry_install_transaction")
    if not isinstance(transaction, dict) or set(transaction) != TRANSACTION_KEYS:
        raise RuntimeError("entry_transaction_schema_not_exact")
    transaction_id = transaction.get("transaction_id")
    if not isinstance(transaction_id, str) or HEX64.fullmatch(transaction_id) is None:
        raise RuntimeError("entry_transaction_id_not_exact")
    final_relative = final_route_path.relative_to(root).as_posix()
    entry_relative = entry_path.relative_to(root).as_posix()
    staging_path = transaction_staging_path(entry_path, transaction_id)
    staging_relative = staging_path.relative_to(root).as_posix()
    final_staging_path = transaction_staging_path(final_route_path, transaction_id)
    final_staging_relative = final_staging_path.relative_to(root).as_posix()
    if (
        transaction.get("final_route_path") != final_relative
        or transaction.get("final_route_run_id") != expected_run_id
        or transaction.get("final_route_staging_path") != final_staging_relative
        or transaction.get("protocol_entry_path") != entry_relative
        or transaction.get("protocol_entry_staging_path") != staging_relative
        or not isinstance(transaction.get("protocol_entry_sha256"), str)
        or HEX64.fullmatch(transaction["protocol_entry_sha256"]) is None
        or not isinstance(transaction.get("protocol_entry_bytes"), int)
        or isinstance(transaction.get("protocol_entry_bytes"), bool)
        or transaction["protocol_entry_bytes"] <= 0
        or not isinstance(transaction.get("owner_marker_path"), str)
        or not isinstance(transaction.get("owner_marker_sha256"), str)
        or HEX64.fullmatch(transaction["owner_marker_sha256"]) is None
        or not isinstance(transaction.get("owner_marker_bytes"), int)
        or isinstance(transaction.get("owner_marker_bytes"), bool)
        or transaction["owner_marker_bytes"] <= 0
        or not isinstance(transaction.get("matrix_verdict_sha256"), str)
        or HEX64.fullmatch(transaction["matrix_verdict_sha256"]) is None
        or not isinstance(transaction.get("adjudication_verdict_sha256"), str)
        or HEX64.fullmatch(transaction["adjudication_verdict_sha256"]) is None
    ):
        raise RuntimeError("entry_transaction_claims_not_exact")
    marker_path = root / safe_relative(transaction["owner_marker_path"])
    if expected_owner_marker is not None and marker_path != expected_owner_marker:
        raise RuntimeError("entry_transaction_owner_marker_mismatch")
    if marker_path.parent != output or not marker_path.name.startswith(
        ".runtime_manifest_recovery_current_"
    ) or not marker_path.name.endswith(".marker"):
        raise RuntimeError("entry_transaction_owner_marker_path_not_exact")
    marker_payload: bytes | None = None
    # Pending recovery and completion-time validation require the live owner
    # marker. A committed transaction is self-contained after that marker has
    # been checked and durably removed by the runner.
    if state == "entry_pending" or expected_owner_marker is not None or os.path.lexists(marker_path):
        marker_payload, _ = owner_marker_snapshot(root, output, marker_path)
        if (
            hashlib.sha256(marker_payload).hexdigest() != transaction["owner_marker_sha256"]
            or len(marker_payload) != transaction["owner_marker_bytes"]
        ):
            raise RuntimeError("entry_transaction_owner_marker_snapshot_mismatch")

    expected_entry_sha = transaction["protocol_entry_sha256"]
    expected_entry_bytes = transaction["protocol_entry_bytes"]
    entry_exists = os.path.lexists(entry_path)
    staging_exists = os.path.lexists(staging_path)
    if require_entry and not entry_exists:
        raise RuntimeError("entry_transaction_protocol_entry_missing")
    entry_payload: bytes | None = None
    if entry_exists:
        entry_payload = stable_regular_bytes(
            root,
            entry_path,
            allowed_link_counts=frozenset({2}) if staging_exists else frozenset({1}),
        )
        if (
            hashlib.sha256(entry_payload).hexdigest() != expected_entry_sha
            or len(entry_payload) != expected_entry_bytes
        ):
            raise RuntimeError("entry_transaction_protocol_entry_snapshot_mismatch")
        text = entry_payload.decode("utf-8")
        if (
            f"% entry_install_transaction_id: {transaction_id}\n" not in text
            or f"% final_route_run_id: {expected_run_id}\n" not in text
        ):
            raise RuntimeError("entry_transaction_protocol_entry_binding_missing")
    if staging_exists:
        staging_payload = stable_regular_bytes(
            root,
            staging_path,
            allowed_link_counts=frozenset({2}) if entry_exists else frozenset({1}),
        )
        if (
            hashlib.sha256(staging_payload).hexdigest() != expected_entry_sha
            or len(staging_payload) != expected_entry_bytes
            or (entry_payload is not None and staging_payload != entry_payload)
        ):
            raise RuntimeError("entry_transaction_staging_snapshot_mismatch")
        if entry_exists:
            entry_stat = entry_path.lstat()
            staging_stat = staging_path.lstat()
            if (entry_stat.st_dev, entry_stat.st_ino) != (
                staging_stat.st_dev,
                staging_stat.st_ino,
            ):
                raise RuntimeError("entry_transaction_staging_not_install_hardlink")
    final_staging_exists = os.path.lexists(final_staging_path)
    if final_staging_exists:
        final_staging_payload = stable_regular_bytes(
            root,
            final_staging_path,
            allowed_link_counts=frozenset({2}),
        )
        final_stat = final_route_path.lstat()
        final_staging_stat = final_staging_path.lstat()
        if (
            final_staging_payload != final_payload
            or (final_stat.st_dev, final_stat.st_ino)
            != (final_staging_stat.st_dev, final_staging_stat.st_ino)
        ):
            raise RuntimeError("entry_transaction_final_staging_not_install_hardlink")
    elif final_route_path.lstat().st_nlink != 1:
        raise RuntimeError("entry_transaction_final_route_multilink_without_staging")
    if state == "entry_pending":
        if not (
            route.get("final_route_pass") is False
            and route.get("logbook_entry_written") is False
            and route.get("disposition") == "entry_install_precommit_pending"
            and route.get("checks", {}).get("entry_128_written_atomically_and_exact") is False
            and entry_relative not in route.get("files", {})
            and entry_relative not in route.get("final_files", {})
        ):
            raise RuntimeError("entry_pending_route_semantics_not_exact")
    else:
        if not (
            state == "committed"
            and route.get("final_route_pass") is True
            and route.get("logbook_entry_written") is True
            and route.get("disposition") == "process_pass_scientific_hold"
            and route.get("checks", {}).get("entry_128_written_atomically_and_exact") is True
            and route.get("files", {}).get(entry_relative) == {"sha256": expected_entry_sha}
            and route.get("final_files", {}).get(entry_relative) == {"sha256": expected_entry_sha}
        ):
            raise RuntimeError("committed_route_semantics_not_exact")
        if staging_exists or final_staging_exists:
            raise RuntimeError("committed_transaction_staging_still_exists")
    return {
        "state": state,
        "route": route,
        "route_payload": final_payload,
        "transaction": transaction,
        "entry_exists": entry_exists,
        "entry_payload": entry_payload,
        "staging_exists": staging_exists,
        "staging_path": staging_path,
        "final_staging_exists": final_staging_exists,
        "final_staging_path": final_staging_path,
        "owner_marker_path": marker_path,
        "owner_marker_payload": marker_payload,
    }


def pending_transaction_recovery_paths(
    root: Path,
    output: Path,
    entry_path: Path,
    final_route_path: Path,
    expected_run_id: str,
) -> list[Path]:
    """Return only artifacts proven to belong to one durable pending transaction."""
    entry_exists = os.path.lexists(entry_path)
    if not os.path.lexists(final_route_path):
        if entry_exists:
            raise RuntimeError("orphan_protocol_entry_without_pending_journal")
        return []
    try:
        route = strict_json_object(
            stable_regular_bytes(
                root,
                final_route_path,
                allowed_link_counts=frozenset({1, 2}),
            )
        )
    except (OSError, RuntimeError, UnicodeDecodeError, ValueError):
        if entry_exists:
            raise RuntimeError("protocol_entry_has_no_readable_pending_journal")
        return []
    if route.get("entry_install_transaction_state") != "entry_pending":
        if entry_exists:
            raise RuntimeError("preexisting_protocol_entry_not_owned_by_pending_transaction")
        return []
    # A malformed pending route with no canonical Entry has no authority to
    # identify additional recovery artifacts; its route file can still be
    # handled as an ordinary stale current artifact.
    raw_transaction = route.get("entry_install_transaction")
    raw_transaction_id = (
        raw_transaction.get("transaction_id") if isinstance(raw_transaction, dict) else None
    )
    if not entry_exists and (
        not isinstance(raw_transaction_id, str)
        or HEX64.fullmatch(raw_transaction_id) is None
    ):
        return []
    no_install_payload_names = bool(
        not entry_exists
        and isinstance(raw_transaction_id, str)
        and HEX64.fullmatch(raw_transaction_id) is not None
        and not os.path.lexists(transaction_staging_path(entry_path, raw_transaction_id))
        and not os.path.lexists(transaction_staging_path(final_route_path, raw_transaction_id))
    )
    if no_install_payload_names:
        try:
            raw_marker = root / safe_relative(raw_transaction["owner_marker_path"])
        except (KeyError, RuntimeError, TypeError, ValueError):
            return []
        # This is the restart state after the owned Entry and marker have
        # already been quarantined but the process died immediately before the
        # final pending journal rename. With no canonical install payload left,
        # the journal is safe to handle as an ordinary stale current artifact.
        if not os.path.lexists(raw_marker):
            return []
    transaction = validate_entry_transaction(
        root,
        output,
        entry_path,
        final_route_path,
        expected_run_id,
        allowed_states={"entry_pending"},
        require_entry=False,
    )
    recovered = [transaction["owner_marker_path"]]
    if transaction["final_staging_exists"]:
        recovered.append(transaction["final_staging_path"])
    if transaction["staging_exists"]:
        recovered.append(transaction["staging_path"])
    if transaction["entry_exists"]:
        recovered.append(entry_path)
    return recovered


def render_entry(
    matrix: dict[str, Any],
    adjudication: dict[str, Any],
    transaction_id: str,
    final_route_run_id: str,
) -> str:
    resolved = "true" if adjudication["selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved"] else "false"
    rejected = "true" if adjudication["selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected"] else "false"
    next_gate = str(adjudication["next_gate"]).replace("_", " ")
    return rf"""% entry_install_transaction_id: {transaction_id}
% final_route_run_id: {final_route_run_id}
\documentclass[11pt]{{article}}
\usepackage[margin=1in]{{geometry}}
\begin{{document}}
\section*{{Protocol Entry 128: synthetic TNG CLI/manifest lifecycle adjudication}}
\textbf{{What was tested.}} The exact hash-pinned Generator 3/4 stage chain was
tested in temporary synthetic shadows after the original Run 217 invocation
omitted the required freeze-manifest argument. The historical Runs 214--217 and
their selected semantic/path continuity and pinned supporting inventory/result
digests remain preserved. The failed Run 217A authorities, four v1.2 R1/R2
artifacts, and two failed v1.3 R3 artifacts remain byte-exact. The hash-pinned
source manifests remain historically
discordant for at least one embedded primary record; only temporary invocation
manifests were translated.

\textbf{{Methods.}} The versioned recovery gates froze the exact CLI binding,
validated the post-producer manifest lifecycle, required a sequential four-stage
zero-offset smoke, and only then authorized Run 218-R3. Run 218-R3 executed four
stages under five constant offsets to the latent synthetic signal, with coupled
regeneration of memory, target, and generic numeric features, for
{matrix['expected_stage_invocations']} total invocations. Every invocation
required a freshly written expected verdict, complete executor-manifest closure,
shadow-relative config and manifest paths, and an explicit absolute shadow root.
Each offset required exactly one deterministic Phase-B runtime-product binding
receipt and an exact producer-to-consumer manifest provenance chain.
Before adjudication could pass, Run 219-R3 independently repeated the complete
four-by-five chain in five new temporary shadows using the hash-pinned replay
implementation and required 20 additional executor-invoked, return-code-zero,
full-lifecycle rows. This is honest-code integrity evidence, not adversarial
process attestation.

\textbf{{Results.}} Expected, attempted, and successful invocations were all
{matrix['expected_stage_invocations']}. Synthetic-fixture latent-signal offset
perturbation invariance resolved is \texttt{{{resolved}}}; rejection is
\texttt{{{rejected}}}. Exactly one of those two sensitivity outcomes was admitted.
This closes only the tested five latent-signal offset perturbations for the
predeclared selected verdict observables and admission decisions of the pinned
generators on the synthetic fixture, within the frozen tolerances. It does not
claim a uniform additive translation of every input coordinate.

\textbf{{Failures and holds.}} Physical units, the physical offset magnitude,
the real unit transform, writer assignment and semantics, population equivalence,
SIMBA coordinates, tracks, zero policy, and adapter execution remain unresolved
or unauthorized. Real-SIMBA/scientific-data memory inference remains
unauthorized; no empirical black-hole-memory result was produced. This does not
authorize native-unit coordinate fallback.

\textbf{{Trust boundary.}} Synthetic containment is protocol-level and is
conditional on the hash-pinned executors honoring their declared configuration
and input contracts. It is not an operating-system filesystem or network
sandbox; child processes can technically access host paths. Adversarial local
code and same-user concurrent mutation are out of scope unless separately
enforced.

\textbf{{Next steps.}} {next_gate}.
\end{{document}}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--design-verdict", required=True)
    parser.add_argument("--preflight-verdict", required=True)
    parser.add_argument("--smoke-verdict", required=True)
    parser.add_argument("--acceptance-verdict", required=True)
    parser.add_argument("--matrix-verdict", required=True)
    parser.add_argument("--adjudication-verdict", required=True)
    parser.add_argument("--transaction-owner-marker", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    config_path = root / safe_relative(args.config)
    if config_path.is_symlink():
        raise RuntimeError("unsafe_current_config_path")
    try:
        config_path = config_path.resolve(strict=True)
        config_path.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise RuntimeError("unsafe_current_config_path") from error
    if not config_path.is_file():
        raise RuntimeError("unsafe_current_config_path")
    cfg = read_json(config_path)
    output = root / safe_relative(cfg["outputs"]["directory"])
    if not safe_existing_directory(root, output):
        raise RuntimeError("unsafe_or_missing_current_output_directory")
    owner_marker_path = root / safe_relative(args.transaction_owner_marker)
    try:
        owner_marker_payload, _ = owner_marker_snapshot(root, output, owner_marker_path)
        owner_marker_exact = True
    except (KeyError, OSError, RuntimeError, TypeError, UnicodeDecodeError, ValueError):
        owner_marker_payload = b""
        owner_marker_exact = False

    specifications = [
        ("design", args.design_verdict, cfg["outputs"]["design_verdict"]),
        ("preflight", args.preflight_verdict, cfg["outputs"]["preflight_verdict"]),
        ("smoke", args.smoke_verdict, cfg["outputs"]["smoke_verdict"]),
        ("acceptance", args.acceptance_verdict, cfg["outputs"]["acceptance_verdict"]),
        ("matrix", args.matrix_verdict, cfg["outputs"]["matrix_verdict"]),
        ("adjudication", args.adjudication_verdict, cfg["outputs"]["adjudication_verdict"]),
    ]
    paths: dict[str, Path] = {}
    paths_exact: dict[str, bool] = {}
    items: dict[str, dict[str, Any]] = {}
    digests: dict[str, str] = {}
    for role, supplied, filename in specifications:
        path, exact = current_output_path(root, output, supplied, filename)
        paths[role] = path
        paths_exact[role] = exact
        items[role], _, digests[role] = stable_json_snapshot(path)

    design = items["design"]
    preflight = items["preflight"]
    smoke = items["smoke"]
    acceptance = items["acceptance"]
    matrix = items["matrix"]
    adjudication = items["adjudication"]
    try:
        live_source_resolution = resolve_source_manifest_claims(root, cfg)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        live_source_resolution = {}
    prior_attempt = prior_attempt_custody_exact(root, cfg)
    prior_v1_3_attempt = prior_v1_3_attempt_custody_exact(root, cfg)
    custody_records: dict[str, dict[str, str]] = {}
    v1_2_custody_records: dict[str, dict[str, str]] = {}
    v1_3_custody_records: dict[str, dict[str, str]] = {}
    custody_record_classes_exact = True
    custody_groups = (
        (
            cfg.get("prior_attempt_custody", {}).get("artifacts"),
            4,
            v1_2_custody_records,
        ),
        (
            cfg.get("prior_v1_3_attempt_custody", {}).get("artifacts"),
            2,
            v1_3_custody_records,
        ),
    )
    for configured_custody_records, expected_count, group_records in custody_groups:
        if (
            not isinstance(configured_custody_records, dict)
            or len(configured_custody_records) != expected_count
        ):
            custody_record_classes_exact = False
            continue
        for name, record in configured_custody_records.items():
            digest = record.get("sha256") if isinstance(record, dict) else None
            try:
                canonical_name = safe_relative(name).as_posix()
            except (RuntimeError, TypeError, ValueError):
                custody_record_classes_exact = False
                continue
            if (
                not isinstance(name, str)
                or canonical_name != name
                or not isinstance(digest, str)
                or HEX64.fullmatch(digest) is None
            ):
                custody_record_classes_exact = False
                continue
            normalized_record = {"sha256": digest}
            if canonical_name in custody_records:
                custody_record_classes_exact = False
                continue
            group_records[canonical_name] = normalized_record
            custody_records[canonical_name] = normalized_record
    current_release_authority = release_field_authority(root, cfg.get("release_field_authority"))
    design_release_authority = design.get("prior_release_field_authority")
    acceptance_release_authority = acceptance.get("prior_release_field_authority")
    adjudication_release_authority = adjudication.get("prior_release_field_authority")
    adjudication_provenance = adjudication.get("provenance")
    provenance_release_authority = (
        adjudication_provenance.get("prior_release_field_authority")
        if isinstance(adjudication_provenance, dict)
        else None
    )
    acceptance_files = acceptance.get("files")
    authority_files_in_acceptance = False
    authority_records: dict[str, dict[str, str]] = {}
    authority_record_classes_collision_free = True
    if current_release_authority is not None and isinstance(acceptance_files, dict):
        authority_records[current_release_authority["path"]] = {
            "sha256": current_release_authority["sha256"]
        }
        for name, record in current_release_authority["files"].items():
            prior = authority_records.get(name)
            if prior is not None and prior != record:
                authority_record_classes_collision_free = False
            authority_records[name] = record
        authority_files_in_acceptance = all(
            acceptance_files.get(name) == record for name, record in authority_records.items()
        )
    authority_final_files_collision_free = bool(authority_records) and authority_record_classes_collision_free
    route_records: dict[str, dict[str, str]] = {}
    for role, _, _ in specifications:
        route_records[paths[role].relative_to(root).as_posix()] = {"sha256": digests[role]}
        records = items[role].get("artifacts", items[role].get("files", {}))
        base = output if "artifacts" in items[role] else root
        if not isinstance(records, dict):
            continue
        for name, record in records.items():
            digest = record.get("sha256") if isinstance(record, dict) else None
            if not isinstance(name, str) or not isinstance(digest, str):
                continue
            try:
                relative = (base / name).resolve().relative_to(root).as_posix()
            except (OSError, RuntimeError, ValueError):
                continue
            prior = route_records.get(relative)
            if prior is not None and prior != {"sha256": digest}:
                authority_final_files_collision_free = False
            route_records[relative] = {"sha256": digest}
    declared_output_targets, protocol_relative_prewrite = configured_output_targets(cfg)
    output_directory_relative = safe_relative(cfg["outputs"]["directory"])
    final_route_relative = (
        output_directory_relative / safe_relative(cfg["outputs"]["final_route"])
    ).as_posix()
    final_route_path = root / safe_relative(final_route_relative)
    protected_protocol_targets = {
        safe_relative(value).as_posix()
        for value in cfg.get("inputs", {}).values()
        if isinstance(value, str)
    }
    protected_protocol_targets.update(
        safe_relative(value).as_posix()
        for value in (
            cfg["failed_run_217A"]["verdict"],
            cfg["failed_run_217A"]["evidence"],
            *cfg.get("exact_sources", {}).keys(),
            *(
                field
                for stage in cfg["stage_contracts"]
                for field in (stage["executor"], stage["config"], stage["manifest"])
            ),
        )
    )
    protected_protocol_targets.update(
        safe_relative(value).as_posix()
        for value in custody_records
    )
    protected_protocol_targets.update(
        safe_relative(value).as_posix()
        for value in design.get("source_authority_resolution", {}).get("path_resolutions", {})
    )
    protected_protocol_targets.update(
        safe_relative(value).as_posix()
        for value in live_source_resolution.get("path_resolutions", {})
    )
    protected_protocol_targets.update(authority_records)
    protected_protocol_targets.update(
        safe_relative(value).as_posix()
        for value in (
            cfg["runtime_binding"]["target_relative_path"],
            cfg["runtime_binding"]["producer_manifest"],
            cfg["runtime_binding"]["shared_manifest"],
            cfg["runtime_binding"]["confirmation_manifest"],
            cfg["runtime_binding"]["confirmation_template_manifest"],
        )
    )
    protected_protocol_targets.update(
        safe_relative(contract["fresh_output_contract"]["expected_relative_path"]).as_posix()
        for contract in cfg["stage_contracts"]
        if isinstance(contract.get("fresh_output_contract", {}).get("expected_relative_path"), str)
    )
    try:
        config_relative = config_path.relative_to(root).as_posix()
        protected_protocol_targets.add(config_relative)
    except (OSError, RuntimeError, ValueError):
        protected_protocol_targets.add(protocol_relative_prewrite)
    declared_outputs_authority_collision_free, comprehensive_entry_collision_free = (
        outputs_disjoint_from_authorities(
            declared_output_targets,
            protocol_relative_prewrite,
            protected_protocol_targets,
        )
    )
    current_output_route_coverage_exact = (
        declared_output_targets - {final_route_relative}
    ).issubset(route_records)
    protocol_entry_target_collision_free = protocol_entry_collision_free(
        protocol_relative_prewrite,
        route_records,
        authority_records,
        protected_protocol_targets,
    ) and comprehensive_entry_collision_free and all(
        not paths_collide(protocol_relative_prewrite, target)
        for target in route_records
    )
    final_route_target_collision_free = (
        final_route_relative in declared_output_targets
        and all(
            not paths_collide(final_route_relative, authority)
            for authority in protected_protocol_targets
        )
        and all(
            not paths_collide(final_route_relative, target)
            for target in route_records
        )
        and not paths_collide(final_route_relative, protocol_relative_prewrite)
        and safe_entry_target(root, root / safe_relative(final_route_relative), create_parents=False)
        and not os.path.lexists(final_route_path)
    )
    for name, record in authority_records.items():
        if paths_collide(name, protocol_relative_prewrite):
            authority_final_files_collision_free = False
        for route_name, route_record in route_records.items():
            if paths_collide(name, route_name) and (
                name != route_name or record != route_record
            ):
                authority_final_files_collision_free = False
    def custody_group_final_files_collision_free(
        records: dict[str, dict[str, str]], expected_count: int
    ) -> bool:
        collision_free = len(records) == expected_count
        for name, record in records.items():
            for other_name, other_record in {
                **route_records,
                **authority_records,
            }.items():
                if paths_collide(name, other_name) and (
                    name != other_name or record != other_record
                ):
                    collision_free = False
        return collision_free

    v1_2_custody_final_files_collision_free = (
        custody_record_classes_exact
        and custody_group_final_files_collision_free(v1_2_custody_records, 4)
    )
    v1_3_custody_final_files_collision_free = (
        custody_record_classes_exact
        and custody_group_final_files_collision_free(v1_3_custody_records, 2)
    )
    custody_classes_cross_collision_free = (
        custody_record_classes_exact
        and len(custody_records) == 6
        and all(
            not paths_collide(v1_2_name, v1_3_name)
            for v1_2_name in v1_2_custody_records
            for v1_3_name in v1_3_custody_records
        )
    )
    prior_release_field_authority_chain_exact = (
        current_release_authority is not None
        and design_release_authority == current_release_authority
        and acceptance_release_authority == current_release_authority
        and adjudication_release_authority == current_release_authority
        and provenance_release_authority == current_release_authority
        and authority_files_in_acceptance
        and authority_final_files_collision_free
        and design.get("checks", {}).get("prior_release_field_authority_current_and_exact") is True
        and acceptance.get("checks", {}).get("prior_release_field_authority_matches_design_freeze") is True
        and adjudication.get("checks", {}).get("prior_release_field_authority_chain_exact") is True
        and adjudication.get("exact_expected_bondi_storage_field_resolved") is True
        and adjudication.get("expected_bondi_physical_semantics_resolved") is False
    )
    expected_ids = {
        "design": cfg["cli_repair_design_run_id"],
        "preflight": cfg["manifest_preflight_run_id"],
        "smoke": cfg["smoke_run_id"],
        "acceptance": cfg["acceptance_run_id"],
        "matrix": cfg["matrix_run_id"],
        "adjudication": cfg["adjudication_run_id"],
    }
    expected_count = len(cfg["stage_contracts"]) * len(cfg["synthetic_contract"]["offsets"])
    resolved = adjudication.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved") is True
    rejected = adjudication.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected") is True
    expected_next_gate = (
        "resolve_exact_writer_physical_semantics_units_and_population_equivalence_before_SIMBA_execution"
        if resolved
        else "resolve_physical_units_and_semantics_without_native_unit_fallback_before_SIMBA_execution"
    )
    matrix_complete = (
        expected_count == 20
        and matrix.get("matrix_complete") is True
        and matrix.get("all_four_stages_executed_at_all_offsets") is True
        and matrix.get("expected_stage_invocations") == expected_count
        and matrix.get("attempted_stage_invocations") == expected_count
        and matrix.get("successful_stage_invocations") == expected_count
        and matrix.get("matrix_process_pass") is True
        and matrix.get("interface_hold") is False
        and matrix.get("hold_reason") is None
    )
    matrix_audits_independently_exact = independently_validate_matrix_audits(
        root,
        output,
        matrix,
        cfg,
    )
    adjudication_live_replay_independently_exact = (
        independently_validate_adjudication_live_replay(
            adjudication, matrix, cfg, root
        )
    )
    adjudication_exact = (
        adjudication.get("adjudication_pass") is True
        and adjudication.get("matrix_complete") is True
        and adjudication.get("selected_output_admission_tested_synthetic_shift_axis_closed") is True
        and adjudication.get("exact_expected_bondi_storage_field_resolved") is True
        and adjudication.get("synthetic_input_rebinding_interface_resolved") is True
        and adjudication.get("next_gate") == expected_next_gate
        and (resolved ^ rejected)
        and matrix.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved") is resolved
        and matrix.get("selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected") is rejected
        and matrix.get("selected_output_admission_tested_synthetic_shift_axis_closed") is True
        and adjudication.get("matrix_verdict_sha256") == digests["matrix"]
        and adjudication.get("acceptance_verdict_sha256") == digests["acceptance"]
        and adjudication.get("live_replay_pass") is True
        and adjudication_live_replay_independently_exact
    )
    closed_axes_exact = all(
        adjudication.get(name) is expected
        for name, expected in {
            "expected_bondi_physical_semantics_resolved": False,
            "physical_units_resolved": False,
            "physical_unit_sensitivity_resolved": False,
            "real_unit_transformation_resolved": False,
            "physical_offset_magnitude_resolved": False,
            "exact_writer_assignment_resolved": False,
            "writer_semantics_resolved": False,
            "native_unit_coordinate_fallback_authorized": False,
            "population_equivalence_resolved": False,
            "scientific_execution_ready": False,
            "coordinate_execution_authorized": False,
            "track_construction_authorized": False,
            "zero_policy_execution_authorized": False,
            "SIMBA_adapter_execution_authorized": False,
            "scientific_generator_execution_authorized": False,
            "negative_memory_result": False,
        }.items()
    )
    early_digest_chain_exact = (
        preflight.get("predecessor_verdicts", {}).get("design_run_id") == design.get("run_id")
        and preflight.get("predecessor_verdicts", {}).get("design_verdict_sha256") == digests["design"]
        and smoke.get("predecessor_verdicts", {}).get("design_run_id") == design.get("run_id")
        and smoke.get("predecessor_verdicts", {}).get("design_verdict_sha256") == digests["design"]
        and smoke.get("predecessor_verdicts", {}).get("preflight_run_id") == preflight.get("run_id")
        and smoke.get("predecessor_verdicts", {}).get("preflight_verdict_sha256") == digests["preflight"]
        and acceptance.get("accepted_predecessor_verdicts", {}).get("design_run_id") == design.get("run_id")
        and acceptance.get("accepted_predecessor_verdicts", {}).get("design_verdict_sha256") == digests["design"]
        and acceptance.get("accepted_predecessor_verdicts", {}).get("preflight_run_id") == preflight.get("run_id")
        and acceptance.get("accepted_predecessor_verdicts", {}).get("preflight_verdict_sha256") == digests["preflight"]
        and acceptance.get("accepted_predecessor_verdicts", {}).get("smoke_run_id") == smoke.get("run_id")
        and acceptance.get("accepted_predecessor_verdicts", {}).get("smoke_verdict_sha256") == digests["smoke"]
        and matrix.get("predecessor_verdicts", {}).get("acceptance_run_id") == acceptance.get("run_id")
        and matrix.get("predecessor_verdicts", {}).get("acceptance_verdict_sha256") == digests["acceptance"]
        and adjudication.get("predecessor_verdicts", {}).get("acceptance_run_id") == acceptance.get("run_id")
        and adjudication.get("predecessor_verdicts", {}).get("acceptance_verdict_sha256") == digests["acceptance"]
        and adjudication.get("predecessor_verdicts", {}).get("matrix_run_id") == matrix.get("run_id")
        and adjudication.get("predecessor_verdicts", {}).get("matrix_verdict_sha256") == digests["matrix"]
    )
    accepted_lifecycle_evidence_exact = acceptance.get("accepted_lifecycle_evidence") == {
        "stage_invocations": 4,
        "fresh_exact_stage_verdicts": 4,
        "runtime_binding_receipts": 1,
        "full_manifest_closure_pass": True,
        "runtime_binding_provenance_chain_pass": True,
    }
    design_source_resolution_exact = source_authority_resolution_exact(
        design.get("source_authority_resolution"), cfg, root
    )
    prior_attempt_recheck = prior_attempt_custody_exact(root, cfg)
    prior_attempt_chain_exact = (
        prior_attempt.get("pass") is True
        and prior_attempt_recheck == prior_attempt
        and prior_attempt_recheck.get("pass") is True
        and design.get("checks", {}).get("failed_v1_2_R1_R2_custody_exact") is True
        and design.get("prior_attempt_custody", {}).get("bundle_version")
        == cfg["prior_attempt_custody"]["bundle_version"]
        and design.get("prior_attempt_custody", {}).get("bundle_sha256")
        == cfg["prior_attempt_custody"]["bundle_sha256"]
        and design.get("prior_attempt_custody", {}).get("artifacts")
        == cfg["prior_attempt_custody"]["artifacts"]
        and design.get("prior_attempt_custody", {}).get("disposition")
        == cfg["prior_attempt_custody"]["disposition"]
        and preflight.get("checks", {}).get("failed_v1_2_R1_R2_custody_exact") is True
        and preflight.get("checks", {}).get("failed_v1_2_evidence_unchanged") is True
        and preflight.get("failed_v1_2_attempt_custody", {}).get("artifacts")
        == cfg["prior_attempt_custody"]["artifacts"]
    )
    prior_v1_3_attempt_recheck = prior_v1_3_attempt_custody_exact(root, cfg)
    prior_v1_3_attempt_chain_exact = (
        prior_v1_3_attempt.get("pass") is True
        and prior_v1_3_attempt_recheck == prior_v1_3_attempt
        and prior_v1_3_attempt_recheck.get("pass") is True
        and design.get("checks", {}).get("failed_v1_3_R3_custody_exact") is True
        and design.get("prior_v1_3_attempt_custody", {}).get("artifacts")
        == cfg["prior_v1_3_attempt_custody"]["artifacts"]
        and design.get("prior_v1_3_attempt_custody", {}).get("verification")
        == prior_v1_3_attempt_recheck
        and preflight.get("checks", {}).get("failed_v1_3_R3_custody_exact") is True
        and preflight.get("checks", {}).get("failed_v1_3_R3_evidence_unchanged") is True
        and preflight.get("failed_v1_3_attempt_custody", {}).get("bundle_version")
        == cfg["prior_v1_3_attempt_custody"]["bundle_version"]
        and preflight.get("failed_v1_3_attempt_custody", {}).get("bundle_sha256")
        == cfg["prior_v1_3_attempt_custody"]["bundle_sha256"]
        and preflight.get("failed_v1_3_attempt_custody", {}).get("disposition")
        == cfg["prior_v1_3_attempt_custody"]["disposition"]
        and preflight.get("failed_v1_3_attempt_custody", {}).get("artifacts")
        == cfg["prior_v1_3_attempt_custody"]["artifacts"]
        and all(
            item.get("prior_v1_3_attempt_custody", {}).get("artifacts")
            == cfg["prior_v1_3_attempt_custody"]["artifacts"]
            and item.get("prior_v1_3_attempt_custody", {}).get("verification")
            == prior_v1_3_attempt_recheck
            for item in (smoke, acceptance, matrix, adjudication)
        )
        and adjudication.get("provenance", {}).get(
            "prior_v1_3_attempt_custody", {}
        ).get("artifacts") == cfg["prior_v1_3_attempt_custody"]["artifacts"]
        and adjudication.get("provenance", {}).get(
            "prior_v1_3_attempt_custody", {}
        ).get("verification") == prior_v1_3_attempt_recheck
    )
    closed_authorization_keys = (
        "network", "SIMBA_scientific_payload", "raw_SIMBA_values", "SIMBA_coordinate",
        "SIMBA_tracks", "zero_policy", "SIMBA_adapter", "scientific_memory_generator_execution",
    )
    scientific_claim_limits_exact = (
        cfg.get("claim_cap") == CLAIM_CAP
        and all(cfg["execution_authorizations"].get(key) is False for key in closed_authorization_keys)
        and all(item.get("claim_cap") == CLAIM_CAP for item in items.values())
        and matrix.get("synthetic_only_result") is True
        and matrix.get("negative_memory_result") is False
        and matrix.get("scientific_execution_authorized") is False
        and adjudication.get("negative_memory_result") is False
        and adjudication.get("scientific_execution_ready") is False
    )
    entry_path = root / safe_relative(cfg["outputs"]["protocol_entry"])
    checks = {
        "all_six_current_paths_exact": all(paths_exact.values()),
        "all_six_upstream_run_ids_exact": all(items[role].get("run_id") == run_id for role, run_id in expected_ids.items()),
        "all_upstream_process_gates_passed": (
            design.get("lifecycle_repair_design_freeze_pass") is True
            and preflight.get("runtime_manifest_preflight_pass") is True
            and smoke.get("smoke_process_pass") is True
            and acceptance.get("smoke_acceptance_freeze_pass") is True
            and acceptance.get("matrix_execution_authorized") is True
            and matrix.get("matrix_process_pass") is True
            and adjudication.get("adjudication_pass") is True
        ),
        "all_upstream_artifacts_exact": all(records_exact(root, output, item) for item in items.values()),
        "early_current_predecessor_digest_chain_exact": early_digest_chain_exact,
        "accepted_lifecycle_evidence_exact": accepted_lifecycle_evidence_exact,
        "design_source_authority_resolution_independently_exact": design_source_resolution_exact,
        "matrix_bound_to_current_acceptance_digest": matrix.get("acceptance_verdict_sha256") == digests["acceptance"],
        "adjudication_bound_to_current_matrix_and_acceptance_digests": adjudication_exact,
        "matrix_expected_attempted_successful_exactly_twenty": matrix_complete,
        "matrix_runtime_binding_closure_and_provenance_exact": (
            matrix.get("checks", {}).get("one_passing_runtime_binding_receipt_per_offset") is True
            and matrix.get("checks", {}).get("all_executor_manifests_full_closure") is True
            and matrix.get("checks", {}).get("manifest_provenance_chain_exact_each_offset") is True
            and matrix.get("checks", {}).get("all_expected_stage_verdicts_fresh_exact") is True
            and matrix.get("checks", {}).get("historical_authorities_unchanged") is True
        ),
        "matrix_shadow_audits_independently_exact": matrix_audits_independently_exact,
        "adjudication_honest_code_live_replay_receipt_and_audit_digest_exact": (
            adjudication_live_replay_independently_exact
        ),
        "failed_v1_2_R1_R2_custody_exact": prior_attempt_chain_exact,
        "failed_v1_2_R1_R2_custody_final_files_collision_free": v1_2_custody_final_files_collision_free,
        "failed_v1_3_R3_custody_exact": prior_v1_3_attempt_chain_exact,
        "failed_v1_3_R3_custody_final_files_collision_free": v1_3_custody_final_files_collision_free,
        "failed_attempt_custody_classes_cross_collision_free": custody_classes_cross_collision_free,
        "prior_release_field_authority_chain_exact": prior_release_field_authority_chain_exact,
        "prior_release_field_authority_final_files_collision_free": authority_final_files_collision_free,
        "all_declared_outputs_disjoint_from_all_authority_classes": declared_outputs_authority_collision_free,
        "all_current_output_targets_accounted_for": current_output_route_coverage_exact,
        "final_route_target_collision_free_and_safe": final_route_target_collision_free,
        "protocol_entry_target_collision_free": protocol_entry_target_collision_free,
        "protocol_entry_freshly_absent_and_safe": (
            not os.path.lexists(entry_path)
            and safe_entry_target(root, entry_path, create_parents=False)
        ),
        "transaction_owner_marker_current_stable_and_exact": owner_marker_exact,
        "exactly_one_synthetic_sensitivity_axis_closed": adjudication_exact,
        "physical_writer_population_and_scientific_axes_remain_closed": closed_axes_exact,
        "claim_cap_and_scientific_authorizations_exact_through_route": scientific_claim_limits_exact,
    }
    upstream_pass = all(checks.values())

    transaction_id = secrets.token_hex(32) if upstream_pass else ""
    entry_text = (
        render_entry(matrix, adjudication, transaction_id, cfg["final_route_run_id"])
        if upstream_pass
        else ""
    )
    entry_written = upstream_pass
    entry_record: dict[str, str] | None = None
    if upstream_pass:
        entry_record = {"sha256": hashlib.sha256(entry_text.encode("utf-8")).hexdigest()}
    checks["entry_128_two_file_transaction_preconditions_exact"] = upstream_pass
    checks["entry_128_written_atomically_and_exact"] = entry_written
    passed = upstream_pass

    final_files: dict[str, dict[str, str]] = {}
    provenance_upstream: dict[str, dict[str, str]] = {}
    for role, _, _ in specifications:
        relative = paths[role].relative_to(root).as_posix()
        record = {"sha256": digests[role]}
        final_files[relative] = record
        provenance_upstream[role] = {
            "path": relative,
            "sha256": digests[role],
            "run_id": str(items[role].get("run_id", "")),
        }
        records = items[role].get("artifacts", items[role].get("files", {}))
        base = output if "artifacts" in items[role] else root
        if isinstance(records, dict):
            for name, artifact_record in records.items():
                digest = artifact_record.get("sha256") if isinstance(artifact_record, dict) else None
                if not isinstance(name, str) or not isinstance(digest, str) or HEX64.fullmatch(digest) is None:
                    continue
                artifact_path = base / name
                try:
                    artifact_relative = artifact_path.resolve().relative_to(root).as_posix()
                except ValueError:
                    continue
                final_files[artifact_relative] = {"sha256": digest}
    protocol_relative = entry_path.relative_to(root).as_posix()
    entry_transaction: dict[str, Any] | None = None
    if passed and entry_record is not None:
        staging_relative = transaction_staging_path(entry_path, transaction_id).relative_to(root).as_posix()
        entry_transaction = {
            "transaction_id": transaction_id,
            "final_route_path": final_route_relative,
            "final_route_run_id": cfg["final_route_run_id"],
            "final_route_staging_path": transaction_staging_path(
                final_route_path, transaction_id
            ).relative_to(root).as_posix(),
            "protocol_entry_path": protocol_relative,
            "protocol_entry_sha256": entry_record["sha256"],
            "protocol_entry_bytes": len(entry_text.encode("utf-8")),
            "protocol_entry_staging_path": staging_relative,
            "owner_marker_path": owner_marker_path.relative_to(root).as_posix(),
            "owner_marker_sha256": hashlib.sha256(owner_marker_payload).hexdigest(),
            "owner_marker_bytes": len(owner_marker_payload),
            "matrix_verdict_sha256": digests["matrix"],
            "adjudication_verdict_sha256": digests["adjudication"],
        }
    if passed and entry_record is not None:
        final_files[protocol_relative] = entry_record
    if current_release_authority is not None:
        release_records = {
            current_release_authority["path"]: {"sha256": current_release_authority["sha256"]},
            **current_release_authority["files"],
        }
        for name, record in release_records.items():
            if name not in final_files:
                final_files[name] = record
    for name, record in custody_records.items():
        if name not in final_files:
            final_files[name] = record
    provenance = {
        "upstream_verdicts": provenance_upstream,
        "prior_release_field_authority": current_release_authority or {},
        "prior_attempt_custody": {
            "bundle_version": cfg["prior_attempt_custody"]["bundle_version"],
            "bundle_sha256": cfg["prior_attempt_custody"]["bundle_sha256"],
            "disposition": cfg["prior_attempt_custody"]["disposition"],
            "artifacts": v1_2_custody_records,
            "verification": prior_attempt_recheck,
        },
        "prior_v1_3_attempt_custody": {
            "bundle_version": cfg["prior_v1_3_attempt_custody"]["bundle_version"],
            "bundle_sha256": cfg["prior_v1_3_attempt_custody"]["bundle_sha256"],
            "disposition": cfg["prior_v1_3_attempt_custody"]["disposition"],
            "artifacts": v1_3_custody_records,
            "verification": prior_v1_3_attempt_recheck,
        },
        "protocol_entry": {
            "path": protocol_relative,
            "sha256": entry_record["sha256"] if entry_record is not None else "",
            "written_only_after_complete_route": passed,
        },
        "adjudication_live_replay": {
            "receipt_sha256": adjudication.get("live_replay_receipt_sha256", ""),
            "audit_sha256": adjudication.get("live_replay_audit_sha256", ""),
            "attestation_limit": adjudication.get("live_replay_attestation_limit", ""),
            "independently_exact": adjudication_live_replay_independently_exact,
        },
    }
    verdict = {
        "schema_version": 2,
        "run_id": cfg["final_route_run_id"],
        "generated_utc": utc_now(),
        "checks": checks,
        "final_route_pass": passed,
        "disposition": "process_pass_scientific_hold" if passed else "run_220_hold_no_entry_or_scientific_inference",
        "matrix_complete": matrix_complete and passed,
        "logbook_entry_written": entry_written and passed,
        "entry_install_transaction_state": "committed" if passed else "not_started",
        "adjudication_live_replay_receipt_sha256": (
            adjudication.get("live_replay_receipt_sha256", "") if passed else ""
        ),
        "adjudication_live_replay_audit_sha256": (
            adjudication.get("live_replay_audit_sha256", "") if passed else ""
        ),
        "entry_install_transaction": entry_transaction,
        "prior_release_field_authority": current_release_authority or {},
        "exact_expected_bondi_storage_field_resolved": (
            passed
            and prior_release_field_authority_chain_exact
            and adjudication.get("exact_expected_bondi_storage_field_resolved") is True
        ),
        "expected_bondi_physical_semantics_resolved": False,
        "physical_units_resolved": False,
        "physical_unit_sensitivity_resolved": False,
        "real_unit_transformation_resolved": False,
        "physical_offset_magnitude_resolved": False,
        "exact_writer_assignment_resolved": False,
        "writer_semantics_resolved": False,
        "synthetic_input_rebinding_interface_resolved": passed and adjudication.get("synthetic_input_rebinding_interface_resolved") is True,
        "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_resolved": passed and resolved,
        "selected_output_admission_invariance_to_tested_synthetic_constant_shifts_rejected": passed and rejected,
        "selected_output_admission_tested_synthetic_shift_axis_closed": passed and (resolved ^ rejected),
        "native_unit_coordinate_fallback_authorized": False,
        "population_equivalence_resolved": False,
        "scientific_execution_ready": False,
        "coordinate_execution_authorized": False,
        "track_construction_authorized": False,
        "zero_policy_execution_authorized": False,
        "SIMBA_adapter_execution_authorized": False,
        "scientific_generator_execution_authorized": False,
        "negative_memory_result": False,
        "files": final_files,
        "final_files": final_files,
        "provenance": provenance,
        "next_gate": adjudication.get("next_gate") if passed else "hold_run_220_until_exact_current_adjudication_and_complete_matrix",
        "claim_cap": cfg["claim_cap"],
    }
    if not final_route_target_collision_free:
        print(json.dumps(verdict, indent=2))
        return 2
    if passed:
        # Write an explicit precommit state before Entry 128.  If interrupted,
        # the durable route says that installation is pending rather than
        # falsely claiming that the entry already exists.
        precommit = copy.deepcopy(verdict)
        precommit["final_route_pass"] = False
        precommit["logbook_entry_written"] = False
        precommit["entry_install_transaction_state"] = "entry_pending"
        precommit["disposition"] = "entry_install_precommit_pending"
        precommit["checks"]["entry_128_written_atomically_and_exact"] = False
        precommit["files"].pop(protocol_relative, None)
        precommit["final_files"].pop(protocol_relative, None)
        precommit_text = json.dumps(precommit, indent=2) + "\n"
        install_text_exclusive(
            final_route_path,
            precommit_text,
            root=root,
            transaction_id=transaction_id,
        )
        pending = validate_entry_transaction(
            root,
            output,
            entry_path,
            final_route_path,
            cfg["final_route_run_id"],
            allowed_states={"entry_pending"},
            require_entry=False,
            expected_owner_marker=owner_marker_path,
        )
        if pending["route_payload"] != precommit_text.encode("utf-8"):
            raise RuntimeError("entry_precommit_snapshot_mismatch")
        install_text_exclusive(
            entry_path,
            entry_text,
            root=root,
            transaction_id=transaction_id,
        )
        pending_with_entry = validate_entry_transaction(
            root,
            output,
            entry_path,
            final_route_path,
            cfg["final_route_run_id"],
            allowed_states={"entry_pending"},
            require_entry=True,
            expected_owner_marker=owner_marker_path,
        )
        if (
            pending_with_entry["route_payload"] != precommit_text.encode("utf-8")
            or pending_with_entry["entry_payload"] != entry_text.encode("utf-8")
            or pending_with_entry["owner_marker_payload"] != owner_marker_payload
        ):
            raise RuntimeError("entry_pending_transaction_snapshot_mismatch")
        committed_text = json.dumps(verdict, indent=2) + "\n"
        atomic_text(final_route_path, committed_text, root=root)
        committed = validate_entry_transaction(
            root,
            output,
            entry_path,
            final_route_path,
            cfg["final_route_run_id"],
            allowed_states={"committed"},
            require_entry=True,
            expected_owner_marker=owner_marker_path,
        )
        if (
            committed["route_payload"] != committed_text.encode("utf-8")
            or committed["entry_payload"] != entry_text.encode("utf-8")
            or committed["owner_marker_payload"] != owner_marker_payload
        ):
            raise RuntimeError("entry_committed_transaction_snapshot_mismatch")
    else:
        install_text_exclusive(
            final_route_path,
            json.dumps(verdict, indent=2) + "\n",
            root=root,
            transaction_id=secrets.token_hex(32),
        )
    print(json.dumps(verdict, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
