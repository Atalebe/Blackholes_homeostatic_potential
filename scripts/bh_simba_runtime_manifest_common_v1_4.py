#!/usr/bin/env python3
"""Small deterministic helpers for the SIMBA shadow-rebinding rung."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import stat
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _stable_regular_bytes(path: Path) -> bytes:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise OSError(f"symlinked_ancestry_forbidden:{path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OSError(f"nonregular_or_multilink_file:{path}")
        chunks: list[bytes] = []
        while True:
            block = os.read(descriptor, 8 * 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(descriptor)
        current = path.lstat()
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise OSError(f"file_changed_during_snapshot:{path}")
        # Rewalk after the read as well.  A directory component replaced by a
        # symlink during the snapshot must not be accepted merely because the
        # already-open leaf descriptor itself stayed stable.
        current_path = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current_path = current_path / part
            if current_path.is_symlink():
                raise OSError(f"symlinked_ancestry_after_snapshot:{path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def sha256(path: Path) -> str:
    payload = _stable_regular_bytes(path)
    return hashlib.sha256(payload).hexdigest()


def _reject_constant(value: str) -> Any:
    raise ValueError(f"nonfinite_json_constant:{value}")


def _json_object_bytes(payload: bytes) -> dict[str, Any]:
    value = json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("json_root_not_object")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate_json_key:{key}")
        value[key] = child
    return value


def read_json(path: Path) -> dict:
    return _json_object_bytes(_stable_regular_bytes(path))


def stable_json_snapshot(path: Path) -> tuple[dict[str, Any], bytes, str]:
    """Parse and hash one immutable regular-file snapshot.

    Callers that need both semantics and provenance must not reopen the path
    between those two operations: a concurrent replacement could otherwise
    make the parsed object and recorded digest describe different bytes.
    """
    payload = _stable_regular_bytes(path)
    return _json_object_bytes(payload), payload, hashlib.sha256(payload).hexdigest()


def stable_csv_snapshot(path: Path) -> tuple[list[dict[str, str]], bytes, str]:
    """Parse and hash one immutable UTF-8 CSV snapshot."""
    payload = _stable_regular_bytes(path)
    text = payload.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    return rows, payload, hashlib.sha256(payload).hexdigest()


def _canonical_relative(value: str) -> Path:
    """Return a strict POSIX relative path for authority records."""
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
        raise ValueError("invalid_relative_path")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or re.match(r"^[A-Za-z]:", pure.parts[0])
        or pure.as_posix() != value
    ):
        raise ValueError("invalid_relative_path")
    return Path(*pure.parts)


def _contained_regular_file(root: Path, candidate: Path) -> Path | None:
    """Resolve one single-link regular file with no symlinked ancestry."""
    try:
        root_resolved = root.resolve(strict=True)
        lexical = candidate.absolute()
        relative = lexical.relative_to(root_resolved)
        current = root_resolved
        for part in relative.parts:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                return None
        path = candidate.resolve(strict=True)
        path.relative_to(root_resolved)
        info = path.stat()
    except (OSError, RuntimeError, ValueError):
        return None
    return path if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 else None


def _normalized_declared_files(
    root: Path,
    verdict_path: Path,
    verdict: dict[str, Any],
) -> dict[str, dict[str, str]] | None:
    """Validate and normalize every declared ``files``/``artifacts`` record.

    ``files`` keys are repository-relative.  Historical verdicts commonly use
    basenames in ``artifacts``; those are resolved without guessing by accepting
    exactly one matching file from the repository root or verdict directory.
    """
    normalized: dict[str, dict[str, str]] = {}
    observed_digests: dict[Path, str] = {}
    declared = False
    root = root.resolve()
    for collection_name in ("files", "artifacts"):
        if collection_name not in verdict:
            continue
        records = verdict[collection_name]
        if not isinstance(records, dict):
            return None
        for name, record in records.items():
            declared = True
            expected = record.get("sha256") if isinstance(record, dict) else None
            if not isinstance(name, str) or not isinstance(expected, str) or HEX64.fullmatch(expected) is None:
                return None
            try:
                relative = _canonical_relative(name)
            except ValueError:
                return None
            candidates = [root / relative]
            if collection_name == "artifacts":
                candidates.append(verdict_path.parent / relative)
            matches: dict[Path, Path] = {}
            for candidate in candidates:
                path = _contained_regular_file(root, candidate)
                if path is None:
                    continue
                if path not in observed_digests:
                    try:
                        payload = _stable_regular_bytes(path)
                    except OSError:
                        return None
                    observed_digests[path] = hashlib.sha256(payload).hexdigest()
                if observed_digests[path] == expected:
                    matches[path] = path
            if len(matches) != 1:
                return None
            path = next(iter(matches))
            normalized_name = path.relative_to(root).as_posix()
            prior = normalized.get(normalized_name)
            current = {"sha256": expected}
            if prior is not None and prior != current:
                return None
            normalized[normalized_name] = current
    if not declared or not normalized:
        return None
    return {name: normalized[name] for name in sorted(normalized)}


def release_field_authority(root: Path, pin_spec: Any) -> dict[str, Any] | None:
    """Return the hash-pinned Run-209 release-field authority, or fail closed.

    A path alone is deliberately insufficient.  The caller must supply the
    complete frozen verdict identity and its exact normalized evidence-file
    set; otherwise a locally fabricated, internally self-consistent verdict
    could promote itself to historical authority.
    """
    root = root.resolve()
    if not isinstance(pin_spec, dict) or set(pin_spec) != {
        "path",
        "sha256",
        "run_id",
        "exact_expected_bondi_storage_field_resolved",
        "expected_bondi_physical_semantics_resolved",
        "files",
    }:
        return None
    relative = pin_spec.get("path")
    expected_verdict_sha256 = pin_spec.get("sha256")
    expected_run_id = pin_spec.get("run_id")
    expected_files = pin_spec.get("files")
    if (
        not isinstance(expected_verdict_sha256, str)
        or HEX64.fullmatch(expected_verdict_sha256) is None
        or not isinstance(expected_run_id, str)
        or not expected_run_id.strip()
        or pin_spec.get("exact_expected_bondi_storage_field_resolved") is not True
        or pin_spec.get("expected_bondi_physical_semantics_resolved") is not False
        or not isinstance(expected_files, dict)
        or len(expected_files) != 1
    ):
        return None
    normalized_expected_files: dict[str, dict[str, str]] = {}
    for name, record in expected_files.items():
        if (
            not isinstance(name, str)
            or not isinstance(record, dict)
            or set(record) != {"sha256"}
            or not isinstance(record.get("sha256"), str)
            or HEX64.fullmatch(record["sha256"]) is None
        ):
            return None
        try:
            normalized_name = _canonical_relative(name).as_posix()
        except ValueError:
            return None
        if normalized_name != name:
            return None
        normalized_expected_files[name] = {"sha256": record["sha256"]}
    try:
        canonical = _canonical_relative(relative)
    except ValueError:
        return None
    path = _contained_regular_file(root, root / canonical)
    if path is None:
        return None
    try:
        verdict_payload = _stable_regular_bytes(path)
        if hashlib.sha256(verdict_payload).hexdigest() != expected_verdict_sha256:
            return None
        verdict = _json_object_bytes(verdict_payload)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    run_id = verdict.get("run_id")
    if (
        run_id != expected_run_id
        or verdict.get("exact_expected_bondi_storage_field_resolved") is not True
        or verdict.get("expected_bondi_physical_semantics_resolved") is not False
    ):
        return None
    files = _normalized_declared_files(root, path, verdict)
    if files != normalized_expected_files:
        return None
    return {
        "path": canonical.as_posix(),
        "sha256": expected_verdict_sha256,
        "run_id": run_id,
        "exact_expected_bondi_storage_field_resolved": True,
        "expected_bondi_physical_semantics_resolved": False,
        "files": files,
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    rows, _, _ = stable_csv_snapshot(path)
    return rows


def expected_subset_exact(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and expected_subset_exact(actual[key], value)
            for key, value in expected.items()
        )
    return actual == expected


def prior_attempt_custody_exact(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Verify all immutable v1.2 R1/R2 artifacts and their failed semantics."""
    result: dict[str, Any] = {
        "pass": False,
        "artifact_count": 0,
        "artifact_digest_match_count": 0,
        "design_fields_exact": False,
        "preflight_fields_exact": False,
        "preflight_evidence_rows_exact": False,
        "protocol_entry_absent": False,
    }
    try:
        spec = cfg["prior_attempt_custody"]
        if spec.get("bundle_version") != "1.2" or spec.get("disposition") != "immutable_failed_prerequisite_not_overwritten":
            return result
        artifacts = spec["artifacts"]
        if not isinstance(artifacts, dict) or len(artifacts) != 4:
            return result
        matches = 0
        snapshots: dict[str, bytes] = {}
        for relative, record in artifacts.items():
            expected = record.get("sha256") if isinstance(record, dict) else None
            if not isinstance(expected, str) or HEX64.fullmatch(expected) is None:
                return result
            canonical = _canonical_relative(relative)
            path = _contained_regular_file(root.resolve(), root / canonical)
            if path is not None:
                payload = _stable_regular_bytes(path)
                if hashlib.sha256(payload).hexdigest() == expected:
                    matches += 1
                    snapshots[canonical.as_posix()] = payload
        result["artifact_count"] = len(artifacts)
        result["artifact_digest_match_count"] = matches
        design_key = _canonical_relative(spec["design_verdict"]).as_posix()
        preflight_key = _canonical_relative(spec["preflight_verdict"]).as_posix()
        evidence_key = _canonical_relative(spec["preflight_evidence"]).as_posix()
        design = _json_object_bytes(snapshots[design_key])
        preflight = _json_object_bytes(snapshots[preflight_key])
        result["design_fields_exact"] = expected_subset_exact(design, spec["expected_design_fields"])
        result["preflight_fields_exact"] = expected_subset_exact(preflight, spec["expected_preflight_fields"])
        result["preflight_evidence_rows_exact"] = (
            len(list(csv.DictReader(io.StringIO(snapshots[evidence_key].decode("utf-8-sig")))))
            == int(spec["expected_preflight_evidence_rows"])
        )
        prior_entry = root / "paper/protocol_audit/bh_simba_bondi_shadow_rebinding_entry_128_v1_2.tex"
        result["protocol_entry_absent"] = not os.path.lexists(prior_entry)
        result["pass"] = all((
            matches == len(artifacts),
            result["design_fields_exact"],
            result["preflight_fields_exact"],
            result["preflight_evidence_rows_exact"],
            result["protocol_entry_absent"],
            spec.get("accepted_downstream_stage_invocations") == 0,
            spec.get("protocol_entry_written") is False,
        ))
        return result
    except (KeyError, OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return result


def prior_v1_3_attempt_custody_exact(
    root: Path, cfg: dict[str, Any]
) -> dict[str, Any]:
    """Verify the immutable failed v1.3 R3 design attempt and no Entry 128."""
    result: dict[str, Any] = {
        "pass": False,
        "artifact_count": 0,
        "artifact_digest_match_count": 0,
        "design_fields_exact": False,
        "protocol_entry_absent": False,
    }
    try:
        spec = cfg["prior_v1_3_attempt_custody"]
        if (
            spec.get("bundle_version") != "1.3"
            or spec.get("bundle_sha256")
            != "229f4fc33fa6cafc3ff9e7476bc02e8770d705aa6e43833d162366d75d71fa2c"
            or spec.get("disposition")
            != "immutable_failed_prerequisite_not_overwritten"
        ):
            return result
        artifacts = spec["artifacts"]
        if not isinstance(artifacts, dict) or len(artifacts) != 2:
            return result
        matches = 0
        snapshots: dict[str, bytes] = {}
        for relative, record in artifacts.items():
            expected = record.get("sha256") if isinstance(record, dict) else None
            if not isinstance(expected, str) or HEX64.fullmatch(expected) is None:
                return result
            canonical = _canonical_relative(relative)
            path = _contained_regular_file(root.resolve(), root / canonical)
            if path is not None:
                payload = _stable_regular_bytes(path)
                if hashlib.sha256(payload).hexdigest() == expected:
                    matches += 1
                    snapshots[canonical.as_posix()] = payload
        result["artifact_count"] = len(artifacts)
        result["artifact_digest_match_count"] = matches
        design_key = _canonical_relative(spec["design_verdict"]).as_posix()
        design = _json_object_bytes(snapshots[design_key])
        result["design_fields_exact"] = expected_subset_exact(
            design, spec["expected_design_fields"]
        )
        prior_entry = root / (
            "paper/protocol_audit/"
            "bh_simba_bondi_shadow_rebinding_entry_128_v1_3.tex"
        )
        result["protocol_entry_absent"] = not os.path.lexists(prior_entry)
        result["pass"] = all((
            matches == len(artifacts),
            result["design_fields_exact"],
            result["protocol_entry_absent"],
            spec.get("accepted_downstream_stage_invocations") == 0,
            spec.get("protocol_entry_written") is False,
        ))
        return result
    except (
        KeyError, OSError, RuntimeError, TypeError, ValueError,
        json.JSONDecodeError,
    ):
        return result


def write_csv(path: Path, rows: Iterable[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    candidate = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(candidate, path)
    finally:
        if candidate.exists():
            candidate.unlink()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    candidate = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(candidate, path)
    finally:
        if candidate.exists():
            candidate.unlink()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
