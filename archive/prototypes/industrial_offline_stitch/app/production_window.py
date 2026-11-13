"""Compatibility entry for the promoted production offline workspace."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
from ui_v2.offline_stitch import OfflineStitchWindow
OfflineProductionWindow = OfflineStitchWindow
