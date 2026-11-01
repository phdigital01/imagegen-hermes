#!/usr/bin/env python3
"""Wait for the Hermes Desktop app to close, then repackage win-unpacked.

The packaged app executes from release/win-unpacked, which stays locked
(EBUSY) while Hermes runs. This helper runs detached from the agent, polls
for the Hermes.exe processes to disappear, then invokes
package_win_unpacked.py once the directory is free.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).with_name("package_win_unpacked.py")
LOG = Path(__file__).with_suffix(".log")
POLL_SECONDS = 10


def hermes_running() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Hermes.exe", "/NH"],
        capture_output=True,
        text=True,
    )
    return "Hermes.exe" in (result.stdout or "")


def main() -> int:
    with LOG.open("w", encoding="utf-8") as log:
        def write(message: str) -> None:
            print(message)
            log.write(message + "\n")
            log.flush()

        write(f"[watch] waiting for Hermes Desktop to close (poll {POLL_SECONDS}s)...")
        while hermes_running():
            time.sleep(POLL_SECONDS)

        # Grace period so the exe fully releases its file locks.
        time.sleep(5)
        write("[watch] Hermes closed; starting package_win_unpacked.py")

        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            text=True,
        )
        write(result.stdout or "")
        if result.stderr:
            write(result.stderr)
        write(f"[watch] packager exit code: {result.returncode}")
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())
