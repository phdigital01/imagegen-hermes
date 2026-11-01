#!/usr/bin/env python3
"""Copy the canonical bundled frontend into a Hermes Desktop source host."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY_ROOT / "frontend"
RELATIVE_TARGET = Path("apps/desktop/src/plugins/imagegen")
IGNORED = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git", "*.pyc", "*.env")


def is_child(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, required=True, help="Hermes Git worktree or checkout")
    parser.add_argument("--apply", action="store_true", help="Write files. The default is dry-run.")
    args = parser.parse_args()

    host = args.host.resolve()
    target = host / RELATIVE_TARGET
    if not SOURCE.is_dir():
        parser.error(f"Frontend source does not exist: {SOURCE}")
    if not (host / ".git").exists():
        parser.error(f"Host is not a Git checkout or worktree: {host}")
    if not is_child(target, host):
        parser.error("Target is outside the supplied host")

    files = [path for path in SOURCE.rglob("*") if path.is_file()]
    print(f"Source: {SOURCE}")
    print(f"Target: {target}")
    print(f"Files: {len(files)}")
    if not args.apply:
        print("Dry-run only. Add --apply to copy the frontend.")
        return 0

    staging = target.with_name(f"{target.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(SOURCE, staging, ignore=IGNORED)
    if target.exists():
        shutil.rmtree(target)
    staging.replace(target)
    print("Frontend sync completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
