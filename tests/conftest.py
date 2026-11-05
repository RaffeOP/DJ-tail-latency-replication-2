"""
tests/conftest.py

Puts src/ on the import path so the analysis modules import as top-level packages,
the same way the scripts in src/ import them.
"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))
