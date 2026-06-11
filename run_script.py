#!/usr/bin/env python3
import argparse
import runpy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("script")
    parser.add_argument("config")
    parser.add_argument("--n_boot", type=int, default=None)
    parser.add_argument("--n_perm", type=int, default=None)
    args = parser.parse_args()

    script_path = (REPO_ROOT / args.script).resolve() if not Path(args.script).is_absolute() else Path(args.script)
    config_path = (REPO_ROOT / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)

    runpy.run_path(
        str(script_path),
        init_globals={
            "CONFIG_PATH": str(config_path),
            "N_BOOT_OVERRIDE": args.n_boot,
            "N_PERM_OVERRIDE": args.n_perm,
            "__name__": "__main__",
        },
    )

if __name__ == "__main__":
    main()
