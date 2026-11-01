"""Reentrant file locks shared by the Dashboard and the separate MCP process."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path


def process_alive(pid: int) -> bool:
    """Probe process existence without signalling or terminating it on Windows."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied: conservatively alive.
        try:
            code = wintypes.DWORD()
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class ProcessRLock:
    """Thread ownership plus an OS advisory lock on a stable sidecar file.

    The sidecar is never replaced or removed: every process must lock the
    same file even while the protected JSON is atomically replaced.
    """

    def __init__(self, path: Path, timeout: float = 30.0) -> None:
        self.path = path.with_name(path.name + ".lock")
        self.timeout = timeout
        self._thread = threading.RLock()
        self._depth = 0
        self._file = None

    def __enter__(self):
        self._thread.acquire()
        try:
            if self._depth == 0:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._file = self.path.open("a+b")
                if self._file.seek(0, os.SEEK_END) == 0:
                    self._file.write(b"\0")
                    self._file.flush()
                deadline = time.monotonic() + self.timeout
                while True:
                    self._file.seek(0)
                    try:
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"Storage lock timed out: {self.path.name}") from None
                        time.sleep(0.05)
            self._depth += 1
            return self
        except BaseException:
            if self._depth == 0 and self._file is not None:
                self._file.close()
                self._file = None
            self._thread.release()
            raise

    def __exit__(self, exc_type, exc, traceback):
        try:
            self._depth -= 1
            if self._depth == 0 and self._file is not None:
                try:
                    self._file.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                finally:
                    self._file.close()
                    self._file = None
        finally:
            self._thread.release()
