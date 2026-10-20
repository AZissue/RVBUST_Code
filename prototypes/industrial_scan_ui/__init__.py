"""Independent industrial scanning presentation prototype for MCC."""
from pathlib import Path
import sys

# Standalone geometry tests also use the shared production scene implementation.
_shared_src = Path(__file__).resolve().parents[2] / 'src'
if _shared_src.is_dir() and str(_shared_src) not in sys.path:
    sys.path.insert(0, str(_shared_src))
