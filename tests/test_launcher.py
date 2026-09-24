"""The compiled launcher in installer/launcher.c.

Built the same way install.sh builds it, with the macros pointed at a temp
directory, so these run without touching /Applications.
"""

import os
import shutil
import subprocess
import sysconfig
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "installer" / "launcher.c"

pytestmark = pytest.mark.skipif(
    shutil.which("cc") is None, reason="needs a C compiler"
)


def _c_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _build(tmp_path: Path, dylib: str, run_py: Path) -> tuple[Path, Path]:
    binary = tmp_path / "Momito"
    log = tmp_path / "momito.log"
    subprocess.run(
        [
            "cc", "-O2", "-o", str(binary), str(SOURCE),
            "-framework", "CoreFoundation",
            f"-DPYTHON_DYLIB={_c_string(dylib)}",
            f"-DPY_VERSION={_c_string('3.14')}",
            f"-DPROJECT_DIR={_c_string(str(tmp_path))}",
            f"-DRUN_PY={_c_string(str(run_py))}",
            f"-DLOG_PATH={_c_string(str(log))}",
        ],
        check=True,
    )
    return binary, log


def _run(binary: Path) -> subprocess.CompletedProcess[bytes]:
    env = {**os.environ, "MOMITO_LAUNCHER_NO_ALERT": "1"}
    return subprocess.run([str(binary)], env=env, timeout=60)


def test_missing_python_explains_the_fix(tmp_path: Path) -> None:
    """Homebrew removing Python used to make the app vanish without a word."""
    binary, log = _build(tmp_path, "/nonexistent/Python", tmp_path / "run.py")

    assert _run(binary).returncode == 1
    text = log.read_text()
    assert "cannot load Python" in text
    assert "brew install python@3.14" in text
    assert f'cd "{tmp_path}" && ./install.sh' in text


def _shared_libpython() -> str | None:
    prefix = sysconfig.get_config_var("PYTHONFRAMEWORKPREFIX")
    ld = sysconfig.get_config_var("LDLIBRARY")
    libdir = sysconfig.get_config_var("LIBDIR")
    if not ld:
        return None
    path = os.path.join(prefix, ld) if prefix else os.path.join(libdir or "", ld)
    return path if os.path.exists(path) else None


@pytest.mark.skipif(_shared_libpython() is None, reason="static-only Python")
def test_runs_the_script_when_python_is_there(tmp_path: Path) -> None:
    dylib = _shared_libpython()
    assert dylib is not None
    run_py = tmp_path / "run.py"
    run_py.write_text("print('momito ran')\n")
    binary, log = _build(tmp_path, dylib, run_py)

    assert _run(binary).returncode == 0
    text = log.read_text()
    assert "momito ran" in text
    assert "can't start" not in text and "cannot load" not in text
