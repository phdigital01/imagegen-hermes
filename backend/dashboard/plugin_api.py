"""Hermes dashboard entry; the implementation is the imagegen_engine package."""
from pathlib import Path
import sys

# Hermes imports this entry by file location under its own module name. The
# engine sits beside this folder (development sync) or under backend/ (package
# install). This directory deliberately has no __init__.py.
_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = str(_ROOT if (_ROOT / "imagegen_engine").is_dir() else _ROOT / "backend")
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from imagegen_engine.plugin_api import router  # noqa: E402, F401
