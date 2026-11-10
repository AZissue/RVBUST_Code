"""Compatibility entry for the promoted production offline workspace."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from ui_v2.offline_stitch import OfflineStitchWindow
OfflineProductionWindow = OfflineStitchWindow
