#!/usr/bin/env python3
"""Type-check and test the frontend inside a Hermes Desktop checkout, its only real host.

    python scripts/check_frontend.py [--host <checkout>] [--source <git url>] [--ref <tag>]

Without --host it clones Hermes to a temporary folder and removes it afterwards.
With --host it replaces that checkout's copy of the plugin frontend.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = "vitest.imagegen.config.ts"
HERMES_SOURCE = "https://github.com/NousResearch/hermes-agent.git"
# The oldest Hermes the plugin supports (requires_hermes in plugin.yaml).
HERMES_REF = "v0.22.5"


def _run(cwd: Path, *command: str) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run([shutil.which(command[0]) or command[0], *command[1:]], cwd=cwd, check=True)


def _check(host: Path) -> None:
    desktop = host / "apps/desktop"
    _run(ROOT, sys.executable, "sync_frontend.py", "--host", str(host), "--apply")
    _run(host, "npm", "ci", "--silent", "--no-audit", "--no-fund", "--ignore-scripts")
    _run(desktop, "npx", "tsc", "-p", ".", "--noEmit")
    shutil.copyfile(ROOT / CONFIG, desktop / CONFIG)
    try:
        _run(desktop, "npx", "vitest", "run", "--config", CONFIG)
    finally:
        (desktop / CONFIG).unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, help="an existing Hermes checkout")
    parser.add_argument("--source", default=HERMES_SOURCE, help="where to clone Hermes from")
    parser.add_argument("--ref", default=HERMES_REF, help="the Hermes tag to clone")
    args = parser.parse_args()
    try:
        if args.host:
            _check(args.host.resolve())
        else:
            with tempfile.TemporaryDirectory(prefix="imagegen-host-", ignore_cleanup_errors=True) as folder:
                host = Path(folder) / "hermes"
                _run(Path(folder), "git", "clone", "-q", "--depth", "1", "--branch", args.ref, args.source, str(host))
                _check(host)
    except subprocess.CalledProcessError as exc:
        print(f"Failed with exit code {exc.returncode}: {' '.join(map(str, exc.cmd))}", file=sys.stderr)
        return 1
    print("Frontend check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
