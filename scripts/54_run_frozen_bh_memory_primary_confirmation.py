#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = root / "outputs/protocol/memory_generator3_primary_confirmation_2000/bh_memory_primary_confirmation_freeze_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("freeze_authorized"):
        raise RuntimeError("Primary confirmation freeze was not authorized")
    changed = [name for name, record in manifest["files"].items() if digest(root / name) != record["sha256"]]
    if changed:
        raise RuntimeError(f"Frozen inputs changed after manifest creation: {changed}")
    command = [
        sys.executable,
        str(root / "scripts/46_screen_bh_memory_generator3_selection_null.py"),
        "--config", "configs/protocol/bh_memory_generator3_primary_confirmation_2000.yaml",
        "--repo-root", str(root),
    ]
    completed = subprocess.run(command, cwd=root, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
