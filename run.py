#!/usr/bin/env python3
"""Momito: hold-to-talk local dictation.

Run directly (.venv/bin/python run.py) or via Momito.app's compiled launcher.
The launcher embeds Python without activating the venv, so the venv's
site-packages is put on sys.path here.
"""

import sys
from pathlib import Path

_SITE = (
    Path(__file__).resolve().parent
    / ".venv"
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
if _SITE.is_dir() and str(_SITE) not in sys.path:
    sys.path.insert(0, str(_SITE))

from momito.app import main

if __name__ == "__main__":
    main()
