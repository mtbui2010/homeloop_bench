import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)
# homeloop_robot: the sibling checkout (worktree layout) unless it is installed / on PYTHONPATH already
try:
    import homeloop_robot  # noqa: F401
except ImportError:
    for cand in (ROOT.parent / "homeloop_robot", Path(os.environ.get("HOMELOOP_ROBOT", "")) if os.environ.get("HOMELOOP_ROBOT") else None):
        if cand and (cand / "homeloop_robot").is_dir():
            sys.path.insert(0, str(cand))
            break
