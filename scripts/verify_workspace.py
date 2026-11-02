#!/usr/bin/env python3
"""Check that the ImageGen repository contains only source-controlled files."""

from __future__ import annotations

import argparse
import re
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {"__pycache__", ".pytest_cache", ".pytest-tmp", ".pytest-basetemp", "data", ".snapshots", ".desktop-user-data"}
FORBIDDEN_SUFFIXES = {".pyc", ".log"}


def _git_ignored(path: Path) -> bool:
    """True when git tracks nothing under path (respects .gitignore)."""
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=ROOT, capture_output=True,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object_body(lines: list[str], header: str) -> list[str]:
    """Return the lines inside the brace-balanced block opened by `header` (exported or not)."""
    start = next(i for i, line in enumerate(lines) if line.rstrip().removeprefix("export ") == header)
    depth, index = 0, start
    while True:
        depth += lines[index].count("{") - lines[index].count("}")
        if depth == 0 and index > start:
            return lines[start + 1:index]
        index += 1


def check_i18n() -> list[str]:
    """Keep the four language bundles in lockstep with `Messages`.

    `Messages` carries an index signature, so TypeScript cannot catch a key a
    language bundle forgot, a duplicate entry, or a `t('key')` call with no
    translation. Those only surface as a raw key rendered in the UI.
    """
    source = ROOT / "frontend" / "i18n.ts"
    if not source.is_file():
        return [f"Missing {source.relative_to(ROOT)}"]
    lines = source.read_text(encoding="utf-8").split("\n")
    errors: list[str] = []

    declared = re.findall(
        r"^  ([A-Za-z][\w]*)\??:",
        "\n".join(_object_body(lines, "interface Messages {")),
        re.M,
    )

    bundles: dict[str, list[str]] = {}
    for lang in ("en", "pt", "es", "zh"):
        body = _object_body(lines, f"const {lang}: Messages = {{")
        bundles[lang] = re.findall(r"^  ([A-Za-z][\w]*):", "\n".join(body), re.M)

    for lang, keys in bundles.items():
        seen = set(keys)
        missing = [key for key in declared if key not in seen]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if missing:
            errors.append(f"i18n[{lang}] missing keys: {', '.join(missing)}")
        if duplicates:
            errors.append(f"i18n[{lang}] duplicate keys: {', '.join(duplicates)}")

    used: set[str] = set()
    for path in list((ROOT / "frontend").rglob("*.ts")) + list((ROOT / "frontend").rglob("*.tsx")):
        if path.name == "i18n.ts":
            continue
        used |= set(re.findall(r"\bt\(\s*'([A-Za-z][\w]*)'", path.read_text(encoding="utf-8")))

    unresolved = sorted(used - set(bundles["en"]))
    if unresolved:
        errors.append(f"i18n call sites with no translation: {', '.join(unresolved)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", type=Path, help="Compare the canonical frontend with this source directory")
    args = parser.parse_args()

    errors: list[str] = []
    for current, directories, files in os.walk(ROOT):
        directory = Path(current)
        relative = directory.relative_to(ROOT)
        if relative == Path("."):
            directories[:] = [name for name in directories if name != ".git"]
        # Skip anything the user has git-ignored (runtime/QA data, caches).
        directories[:] = [name for name in directories
                          if name != ".git" and not _git_ignored(directory / name)]
        for name in list(files):
            if _git_ignored(directory / name):
                files.remove(name)
        generated = [name for name in directories if name in FORBIDDEN_PARTS]
        for name in generated:
            errors.append(f"Generated directory in repository: {relative / name}")
        for name in files:
            path = directory / name
            if path.suffix in FORBIDDEN_SUFFIXES or path.name == ".env" or path.name.endswith(".env"):
                errors.append(f"Generated or secret file in repository: {path.relative_to(ROOT)}")

    required = (ROOT / "frontend", ROOT / "backend" / "imagegen_engine", ROOT / "backend" / "dashboard", ROOT / "tests")
    for path in required:
        if not path.is_dir():
            errors.append(f"Missing required directory: {path.relative_to(ROOT)}")

    errors.extend(check_i18n())

    if args.frontend:
        expected = ROOT / "frontend"
        actual = args.frontend.resolve()
        expected_files = {path.relative_to(expected) for path in expected.rglob("*") if path.is_file()}
        actual_files = {path.relative_to(actual) for path in actual.rglob("*") if path.is_file()}
        if expected_files != actual_files:
            errors.append("Frontend file sets do not match")
        for relative in expected_files & actual_files:
            if digest(expected / relative) != digest(actual / relative):
                errors.append(f"Frontend file differs: {relative}")

    if errors:
        print("Workspace verification failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Workspace verification passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
