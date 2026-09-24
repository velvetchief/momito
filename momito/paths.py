"""Where Momito finds its files, in both run layouts.

In dev, the repo root is one level above this package and third-party deps
live in .venv. In a release bundle, scripts/make_release.sh puts this
package, run.py, assets/, and site-packages/ side by side in
Contents/Resources, and the compiled launcher (installer/launcher.c, built
with -DMOMITO_PACKAGED) sets MOMITO_PACKAGED=1 so the lookups below follow
the bundle layout. Stdlib only: run.py imports this module before the
site-packages path exists.
"""

import os
import sys
from pathlib import Path

PACKAGED_ENV = "MOMITO_PACKAGED"


def is_packaged() -> bool:
    """True when running from a release bundle, where the launcher set the
    MOMITO_PACKAGED marker."""
    return os.environ.get(PACKAGED_ENV) == "1"


def app_root() -> Path:
    """The repo root in dev, Contents/Resources in a bundle. Both are the
    parent of this package, and both hold assets/ as a sibling of it."""
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    """Icons and cue sounds; a sibling of the package in both layouts."""
    return app_root() / "assets"


def site_packages_dir() -> Path:
    """Where third-party deps live: .venv in dev, Resources/site-packages in
    a bundle (installed there by scripts/make_release.sh)."""
    if is_packaged():
        return app_root() / "site-packages"
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return app_root() / ".venv" / "lib" / version / "site-packages"
