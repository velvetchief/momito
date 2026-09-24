#!/usr/bin/env python3
"""Momito: hold-to-talk local dictation.

Run directly (.venv/bin/python run.py) or via Momito.app's compiled launcher.
The launcher embeds Python without activating the venv, so the third-party
deps are put on sys.path here: .venv in dev, or Contents/Resources/
site-packages in a release bundle, where the launcher announces that layout
by setting MOMITO_PACKAGED=1 (see momito.paths).
"""

import sys

from momito.paths import site_packages_dir

_SITE = site_packages_dir()
if _SITE.is_dir() and str(_SITE) not in sys.path:
    sys.path.insert(0, str(_SITE))

from momito.app import main

if __name__ == "__main__":
    main()
