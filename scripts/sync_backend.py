#!/usr/bin/env python3
"""Deploy the canonical backend to Hermes only after an explicit --apply."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY_ROOT / "backend"
DEFAULT_HERMES_HOME = Path.home() / "AppData" / "Local" / "hermes"
IGNORED = shutil.ignore_patterns("data", "__pycache__", ".pytest_cache", ".pytest-tmp", ".pytest-basetemp", "*.pyc", "*.env")
ROOT_FILES = (".gitignore", "__init__.py", "imagegen_cli.py", "mcp_server.py", "plugin.yaml")
PACKAGE_DIRS = ("imagegen_engine", "dashboard")


def copy_source(source: Path, target: Path) -> None:
    for name in ROOT_FILES:
        source_file = source / name
        if source_file.exists():
            shutil.copy2(source_file, target / name)
    # The engine package and the Hermes dashboard entry; a rollback snapshot of
    # an older layout carries only dashboard/, so drop both before copying.
    for name in PACKAGE_DIRS:
        destination = target / name
        if destination.exists():
            shutil.rmtree(destination)
        if (source / name).is_dir():
            shutil.copytree(source / name, destination, ignore=IGNORED)


def snapshot(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = REPOSITORY_ROOT / ".snapshots" / f"backend-{stamp}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(target, destination, ignore=IGNORED)
    return destination


def ensure_plugin_enabled(hermes_home: Path, name: str, hermes_bin: str = "") -> bool:
    """Enable through the Hermes CLI, preserving config and registry semantics."""
    candidates = []
    if hermes_bin:
        candidates.append(Path(hermes_bin))
    candidates += [
        hermes_home / "hermes-agent" / "venv" / "Scripts" / "hermes.exe",
        hermes_home / "hermes-agent" / ".venv" / "Scripts" / "hermes.exe",
        hermes_home / "venv" / "Scripts" / "hermes.exe",
        hermes_home / "venv" / "bin" / "hermes",
    ]
    for exe in candidates:
        if not exe.exists():
            continue
        try:
            proc = subprocess.run(
                [str(exe), "plugins", "enable", name],
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "HERMES_HOME": str(hermes_home)},
            )
            if proc.returncode == 0:
                print(f"Enabled plugin '{name}' via {exe.name} plugins enable")
                return True
            print(f"  (hermes plugins enable returned {proc.returncode}: {proc.stderr.strip()[-200:]})")
        except Exception as exc:  # noqa: BLE001
            print(f"  (hermes plugins enable failed: {exc})")

    print(f"Could not enable {name} through the Hermes CLI; pass --hermes-bin with its executable.")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", type=Path, default=Path(os.environ.get("HERMES_HOME", DEFAULT_HERMES_HOME)))
    parser.add_argument("--apply", action="store_true", help="Write backend files after a snapshot.")
    parser.add_argument("--rollback", type=Path, help="Restore a snapshot instead of the canonical backend.")
    parser.add_argument("--hermes-bin", default="", help="Path to the hermes CLI used to enable the plugin.")
    parser.add_argument("--no-enable", action="store_true", help="Do not touch plugins.enabled in config.yaml.")
    args = parser.parse_args()

    target = args.hermes_home.resolve() / "plugins" / "imagegen"
    source = args.rollback.resolve() if args.rollback else SOURCE
    if not source.is_dir():
        parser.error(f"Source does not exist: {source}")
    if not (source / "dashboard").is_dir():
        parser.error(f"Backend source has no dashboard directory: {source}")

    mode = "rollback" if args.rollback else "deployment"
    print(f"Mode: {mode}")
    print(f"Source: {source}")
    print(f"Target: {target}")
    print("Runtime data and .env files are preserved.")
    if not args.apply:
        print("Dry-run only. Add --apply to change the installed backend.")
        return 0

    created = False
    if not target.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        created = True
        print(f"Installed backend did not exist — created {target}")

    backup = snapshot(target) if not created else None
    copy_source(source, target)
    print(f"Completed. Rollback snapshot: {backup}")
    if not args.no_enable and not args.rollback:
        if not ensure_plugin_enabled(args.hermes_home.resolve(), "imagegen", args.hermes_bin):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
