"""Native package REST entry; implementation lives in the canonical backend/."""
from pathlib import Path
import sys

# Hermes imports this entry by file location under its own module name. Put the
# implementation first so dashboard.* resolves to backend/dashboard, as in the
# development sync layout. This directory deliberately has no __init__.py.
_BACKEND_ROOT = str(Path(__file__).resolve().parents[1] / "backend")
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from dashboard.plugin_api import router  # noqa: E402, F401
