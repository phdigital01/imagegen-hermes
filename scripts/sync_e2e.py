#!/usr/bin/env python3
"""Copy the canonical ImageGen e2e assets into a Hermes Desktop host.

Copies:
- e2e/imagegen-smoke.spec.ts      -> apps/desktop/e2e/imagegen-smoke.spec.ts
- e2e/host-fixtures.ts            -> apps/desktop/e2e/fixtures.ts (QA-patched)

The host fixture carries the QA patches the upstream removed (Windows
electron.exe resolution, desktopEnv passthrough). It is the canonical copy of
those patches; never edit the host fixture directly.

Dry-run by default. Use --apply to write.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY_ROOT / "e2e"

# Relative target paths inside the host checkout.
E2E_TARGET = Path("apps/desktop/e2e")
FILES = {
    "imagegen-smoke.spec.ts": E2E_TARGET / "imagegen-smoke.spec.ts",
    "host-fixtures.ts": E2E_TARGET / "fixtures.ts",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, required=True, help="Hermes Desktop checkout or worktree")
    parser.add_argument("--apply", action="store_true", help="Write files. The default is dry-run.")
    args = parser.parse_args()

    host = args.host.resolve()
    if not (host / ".git").exists():
        parser.error(f"Host is not a Git checkout or worktree: {host}")

    print(f"Source: {SOURCE}")
    print(f"Host: {host}")
    for name, relative in FILES.items():
        source_file = SOURCE / name
        target_file = host / relative
        if not source_file.is_file():
            print(f"  MISSING source: {source_file}")
            continue
        if target_file.exists() and target_file.read_bytes() == source_file.read_bytes():
            print(f"  up to date: {relative}")
            continue
        print(f"  would copy: {name} -> {relative}")
        if args.apply:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
            print(f"  copied: {relative}")

    if not args.apply:
        print("Dry-run only. Add --apply to copy the e2e files.")
        return 0
    print("E2E sync completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
