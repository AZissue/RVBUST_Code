"""Shared paths for direct scripts, unittest modules and discovery."""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for directory in (PROJECT_ROOT, PROJECT_ROOT / "src", PROJECT_ROOT / "tests"):
    value = str(directory)
    if value not in sys.path:
        sys.path.insert(0, value)
