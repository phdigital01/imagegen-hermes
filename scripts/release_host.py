#!/usr/bin/env python3
"""Release the canonical ImageGen plugin to the Hermes Desktop test host.

Pipeline (all steps must pass or the release aborts):

1. sync_frontend --apply  -> copy frontend/ into the host plugin tree
2. verify_workspace       -> hash-compare the synced tree against frontend/
3. typecheck              -> tsc for renderer, electron, and e2e projects
4. build                  -> Vite production build
5. bundle markers         -> confirm the new plugin markers exist in dist/assets
6. sync_backend --apply   -> deploy backend after successful checks

Run from the repository root. Uses the Hermes worktree at --host (default
the installed Hermes checkout).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# The test host is the installed Hermes checkout itself.
DEFAULT_HOST = Path.home() / "AppData/Local/hermes/hermes-agent"

# Markers that must be present in the built renderer bundle. They identify the
# current plugin feature set (provider status panel, always-visible reference
# strip, prompt panel without the collapsed technical toggle).
BUNDLE_MARKERS = ("providers-status", "localPath", "configured", "refsModeHint", "refDetails")

STEPS: list[str] = []


def npm_command() -> str:
    """Return the npm executable name (npm.cmd on Windows)."""
    npm = shutil.which("npm")
    if npm:
        return npm
    return "npm.cmd" if sys.platform == "win32" else "npm"


def run(command: list[str], cwd: Path, label: str) -> bool:
    print(f"\n[{label}]", " ".join(str(part) for part in command))
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError as error:
        print(f"  FAILED: command not found ({error})")
        return False
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-4000:])
        print(f"  FAILED with exit code {result.returncode}")
        return False
    tail = (result.stdout or "").strip().splitlines()[-3:]
    print("\n".join(f"  {line}" for line in tail))
    print("  OK")
    return True


def check_bundle_markers(desktop: Path) -> bool:
    assets = desktop / "dist" / "assets"
    if not assets.is_dir():
        print(f"[bundle markers] dist/assets not found: {assets}")
        return False
    bundles = sorted(assets.glob("index-*.js"))
    if not bundles:
        print("[bundle markers] no index-*.js bundle found")
        return False
    bundle = bundles[0]
    text = bundle.read_text(encoding="utf-8", errors="ignore")
    missing = [marker for marker in BUNDLE_MARKERS if marker not in text]
    if missing:
        print(f"[bundle markers] missing in {bundle.name}: {missing}")
        return False
    print(f"[bundle markers] {bundle.name} contains: {', '.join(BUNDLE_MARKERS)}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host", type=Path, default=DEFAULT_HOST,
        help="Hermes Desktop worktree used as the test host",
    )
    parser.add_argument(
        "--skip-build", action="store_true",
        help="Stop after sync + verify (do not typecheck or build)",
    )
    parser.add_argument(
        "--skip-marker-check", action="store_true",
        help="Skip the bundle marker verification step",
    )
    parser.add_argument("--hermes-home", type=Path, help="Backend profile; required for a custom checkout")
    args = parser.parse_args()

    host = args.host.resolve()
    if host != DEFAULT_HOST.resolve() and args.hermes_home is None:
        parser.error("A custom --host also requires --hermes-home to select the backend profile")
    profile = (args.hermes_home or Path(os.environ.get("HERMES_HOME", DEFAULT_HOST.parent))).resolve()
    desktop = host / "apps" / "desktop"
    plugin_target = desktop / "src" / "plugins" / "imagegen"
    host_git = host / ".git"
    if not host_git.exists():
        print(f"Host is not a Git checkout or worktree: {host}")
        return 1

    frontend_sync = run(
        [sys.executable, "scripts/sync_frontend.py", "--host", str(host), "--apply"],
        REPOSITORY_ROOT, "sync frontend",
    )
    if not frontend_sync:
        return 1
    e2e_sync = run(
        [sys.executable, "scripts/sync_e2e.py", "--host", str(host), "--apply"],
        REPOSITORY_ROOT, "sync e2e",
    )
    if not e2e_sync:
        return 1
    verify = run(
        [sys.executable, "scripts/verify_workspace.py", "--frontend", str(plugin_target)],
        REPOSITORY_ROOT, "verify hashes",
    )
    if not verify:
        return 1

    if args.skip_build:
        print("\nFrontend sync + verify passed. Backend deployment requires a successful build.")
        return 0

    npm = npm_command()
    typecheck = run([npm, "run", "typecheck"], desktop, "typecheck")
    if not typecheck:
        return 1
    build = run([npm, "run", "build"], desktop, "build")
    if not (typecheck and build):
        print("\nRelease ABORTED: typecheck or build failed.")
        return 1

    if not args.skip_marker_check and not check_bundle_markers(desktop):
        print("\nRelease ABORTED: built bundle lacks the current plugin markers.")
        return 1

    if not run([sys.executable, "scripts/sync_backend.py", "--hermes-home", str(profile), "--apply"], REPOSITORY_ROOT, "sync backend"):
        return 1

    print("\nRelease complete: host is consistent with the canonical frontend, "
          "backend deployed, typecheck + build passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
