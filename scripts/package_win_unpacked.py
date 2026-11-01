#!/usr/bin/env python3
"""Package the current ImageGen build into the Hermes Desktop win-unpacked.

Run this OUTSIDE Hermes Desktop (from a plain terminal) with the app CLOSED.
The desktop app executes from release/win-unpacked, so the directory is
locked while the app is running (EBUSY).

Steps:
1. npm run build       -> regenerate dist/ with the synced plugin (idempotent)
2. npm run builder -- --dir -> package dist/ into release/win-unpacked
3. Restore electron/main.cjs to the SOURCE file. The builder overwrites it
   with the bundled output; leaving the bundle in the git tree makes the
   Hermes updater think the checkout has local changes (update loop).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_DESKTOP = Path.home() / "AppData/Local/hermes/hermes-agent/apps/desktop"


def npm_command() -> str:
    npm = shutil.which("npm")
    return npm or ("npm.cmd" if sys.platform == "win32" else "npm")


def run(command: list[str], cwd: Path, label: str) -> bool:
    print(f"\n[{label}]", " ".join(str(part) for part in command))
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-4000:])
        print(f"FAILED with exit code {result.returncode}")
        return False
    print("\n".join((result.stdout or "").strip().splitlines()[-3:]))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", type=Path, default=DEFAULT_DESKTOP)
    args = parser.parse_args()

    desktop = args.desktop.resolve()
    if not (desktop / "package.json").exists():
        print(f"Desktop path not found: {desktop}")
        return 1

    npm = npm_command()
    main_cjs = desktop / "electron" / "main.cjs"
    original = main_cjs.read_bytes() if main_cjs.exists() else None
    try:
        if not run([npm, "run", "build"], desktop, "build"):
            return 1
        if not run([npm, "run", "builder", "--", "--dir"], desktop, "package win-unpacked"):
            return 1
    finally:
        # Restore exact pre-build bytes, including the user's uncommitted work.
        if original is not None:
            main_cjs.write_bytes(original)
    print("\nDone. Start Hermes Desktop again; the ImageGen plugin is now the")
    print("canonical version.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
