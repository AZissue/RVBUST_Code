"""Identify the bundled customer trial edition."""
from pathlib import Path
import sys


def is_customer_trial():
    return getattr(sys, 'frozen', False) and (Path(sys._MEIPASS) / 'trial.marker').is_file()
