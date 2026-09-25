"""The compiled launcher in installer/launcher.c.

Built the same way install.sh builds it (repo mode, macros baked) plus the
way scripts/make_release.sh builds it (packaged mode, paths resolved from a
fake bundle), with everything pointed at temp directories, so these run
without touching /Applications.
"""

import os
import shlex
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "installer" / "launcher.c"
VALIDATE = ROOT / "scripts" / "validate_bundle.sh"

pytestmark = [
    pytest.mark.skipif(shutil.which("cc") is None, reason="needs a C compiler"),
]


def _c_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _framework_flag() -> list[str]:
    """The launcher links CoreFoundation only on Apple platforms (the alert
    dialog); POSIX builds compile without it, so these tests run everywhere."""
    return ["-framework", "CoreFoundation"] if sys.platform == "darwin" else []


def _build(tmp_path: Path, dylib: str, run_py: Path) -> tuple[Path, Path]:
    """Repo mode: the macros install.sh bakes, pointed at tmp_path."""
    binary = tmp_path / "Momito"
    log = tmp_path / "momito.log"
    subprocess.run(
        [
            "cc", "-O2", "-o", str(binary), str(SOURCE),
            *_framework_flag(),
            f"-DPYTHON_DYLIB={_c_string(dylib)}",
            f"-DPY_VERSION={_c_string('3.14')}",
            f"-DPROJECT_DIR={_c_string(str(tmp_path))}",
            f"-DRUN_PY={_c_string(str(run_py))}",
            f"-DLOG_PATH={_c_string(str(log))}",
        ],
        check=True,
    )
    return binary, log


def _runtime_lib_name() -> str:
    """The shared libpython of the RUNNING interpreter, under the layout
    make_release.sh ships (Resources/python/lib/)."""
    suffix = "dylib" if sys.platform == "darwin" else "so"
    return (
        f"libpython{sys.version_info.major}.{sys.version_info.minor}.{suffix}"
    )


def _build_packaged(tmp_path: Path) -> Path:
    """Packaged mode: the flags make_release.sh bakes, into a fake bundle."""
    app = tmp_path / "Momito.app"
    (app / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "cc", "-O2", "-o", str(app / "Contents" / "MacOS" / "Momito"),
            str(SOURCE),
            *_framework_flag(),
            "-DMOMITO_PACKAGED",
            f"-DPYTHON_DYLIB_RELPATH={_c_string('python/lib/' + _runtime_lib_name())}",
            f"-DPY_VERSION={_c_string('3.14')}",
        ],
        check=True,
    )
    return app


def _run_packaged(binary: Path, home: Path) -> subprocess.CompletedProcess[bytes]:
    """Run a packaged launcher with HOME pointed at the test's tmp dir, away
    from the bundle, so path resolution cannot lean on either."""
    env = {
        **os.environ,
        "HOME": str(home),
        "MOMITO_LAUNCHER_NO_ALERT": "1",
    }
    result = subprocess.run(
        [str(binary)], env=env, cwd=str(home), timeout=60,
    )
    if result.returncode != 0:
        # The launcher redirects stdout/stderr into the log; dump it on
        # failure or the CI output has nothing to diagnose with.
        log = home / "Library" / "Logs" / "Momito" / "momito.log"
        if log.exists():
            print(f"--- launcher log ({log}) ---", file=sys.stderr)
            print(log.read_text(errors="replace"), file=sys.stderr)
    return result


def _packaged_log(home: Path) -> Path:
    return home / "Library" / "Logs" / "Momito" / "momito.log"


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


def test_packaged_missing_runtime_says_redownload(tmp_path: Path) -> None:
    """A release bundle without its dylib is a broken download; the repo-mode
    advice (cd into the checkout) makes no sense there."""
    app = _build_packaged(tmp_path)
    resources = app / "Contents" / "Resources"
    resources.mkdir(parents=True)
    (resources / "run.py").write_text("print('momito ran')\n")

    assert _run_packaged(app / "Contents" / "MacOS" / "Momito", tmp_path).returncode == 1
    text = _packaged_log(tmp_path).read_text()
    assert "cannot load Python" in text
    assert "github.com/velvetchief/momito/releases" in text
    assert "./install.sh" not in text


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


@pytest.mark.skipif(_shared_libpython() is None, reason="static-only Python")
def test_packaged_launcher_runs_the_bundle_script(tmp_path: Path) -> None:
    """Packaged mode: run.py, the package, and the dylib all come from the
    bundle, and the launcher announces the layout with MOMITO_PACKAGED=1 so
    momito.paths resolves from there too."""
    dylib = _shared_libpython()
    assert dylib is not None
    app = _build_packaged(tmp_path)
    resources = app / "Contents" / "Resources"
    shutil.copytree(
        ROOT / "momito", resources / "momito",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (resources / "run.py").write_text(
        "import os\n"
        "from momito.paths import assets_dir, site_packages_dir\n"
        "print('momito ran')\n"
        "print('packaged=%s' % os.environ.get('MOMITO_PACKAGED'))\n"
        "print('assets=%s' % assets_dir())\n"
        "print('site=%s' % site_packages_dir())\n"
    )
    runtime = resources / "python" / "lib"
    runtime.mkdir(parents=True)
    lib_name = _runtime_lib_name()
    shutil.copy(dylib, runtime / lib_name)
    if sys.platform == "darwin":
        # The packager re-signs every dylib it modifies (make_release.sh does
        # install_name_tool then codesign --force --sign -); a framework
        # dylib copied verbatim is refused by dlopen with "code signature
        # invalid". The fixture must mirror that signing step.
        subprocess.run(
            ["codesign", "--force", "--sign", "-", str(runtime / lib_name)],
            check=True,
        )
    # The launcher pins PYTHONHOME to Resources/python when it exists, so the
    # fake bundle must carry a real stdlib at the layout make_release.sh
    # ships: python/lib/pythonX.Y/ (lib-dynload included), or Python init
    # dies with nothing on the filesystem to import from.
    stdlib = sysconfig.get_paths()["stdlib"]
    shutil.copytree(
        stdlib, runtime / f"python{sys.version_info.major}.{sys.version_info.minor}",
        ignore=shutil.ignore_patterns("__pycache__", "test", "site-packages"),
    )

    binary = app / "Contents" / "MacOS" / "Momito"
    assert _run_packaged(binary, tmp_path).returncode == 0
    text = _packaged_log(tmp_path).read_text()
    assert "momito ran" in text
    assert "packaged=1" in text
    assert f"assets={resources / 'assets'}" in text
    assert f"site={resources / 'site-packages'}" in text


# --- scripts/validate_bundle.sh -------------------------------------------

PLIST_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<plist version="1.0">\n<dict>\n'
    "  <key>CFBundleShortVersionString</key><string>{version}</string>\n"
    "  <key>CFBundleIconFile</key><string>Momito</string>\n"
    "</dict>\n</plist>\n"
)


def _fake_bundle(tmp_path: Path, version: str) -> Path:
    """A minimal bundle for the validator: right structure, clean contents."""
    app = tmp_path / "Momito.app"
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources").mkdir()
    (contents / "Info.plist").write_text(PLIST_TEMPLATE.format(version=version))
    (contents / "MacOS" / "Momito").write_text("stub launcher\n")
    (contents / "Resources" / "run.py").write_text("print('ok')\n")
    (contents / "Resources" / "Momito.icns").write_text("stub icns\n")
    return app


def _validate(
    bundle: Path, fake_bin: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    env = None
    if fake_bin is not None:
        env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(
        ["bash", str(VALIDATE), str(bundle)], capture_output=True, timeout=60, env=env,
    )


def test_validation_passes_a_clean_bundle(tmp_path: Path) -> None:
    version = (ROOT / "VERSION").read_text().strip()
    result = _validate(_fake_bundle(tmp_path, version))
    assert result.returncode == 0, result.stderr


def test_validation_rejects_baked_absolute_paths(tmp_path: Path) -> None:
    """Deliberately baked build-machine paths must fail the build, wherever
    they sneak in: the CI runner home, any unix home, or this checkout."""
    for baked in (
        "/Users/runner/work/momito/momito/run.py",
        "/home/alice/repos/momito/run.py",
        str(ROOT / "run.py"),
    ):
        bundle = _fake_bundle(tmp_path, (ROOT / "VERSION").read_text().strip())
        (bundle / "Contents" / "Resources" / "momito").mkdir()
        (bundle / "Contents" / "Resources" / "momito" / "app.py").write_text(
            f'RUN = "{baked}"\n'
        )
        result = _validate(bundle)
        assert result.returncode != 0, baked
        assert "build-machine or checkout paths" in result.stderr.decode()
        shutil.rmtree(bundle)


def test_validation_rejects_version_drift(tmp_path: Path) -> None:
    bundle = _fake_bundle(tmp_path, "9.9.9")
    result = _validate(bundle)
    assert result.returncode != 0
    assert "Info.plist says 9.9.9" in result.stderr.decode()
    assert "VERSION says" in result.stderr.decode()


def test_validation_rejects_missing_app_icon(tmp_path: Path) -> None:
    """The v1.1.0 regression: the plist declares CFBundleIconFile=Momito, but
    the release packager staged assets only under Resources/assets/, so no
    Resources/Momito.icns existed and macOS showed the generic icon. Icon
    presence is now an invariant the build enforces, not a one-off fix."""
    bundle = _fake_bundle(tmp_path, (ROOT / "VERSION").read_text().strip())
    (bundle / "Contents" / "Resources" / "Momito.icns").unlink()
    result = _validate(bundle)
    assert result.returncode != 0
    assert "CFBundleIconFile=Momito" in result.stderr.decode()
    assert "Momito.icns is missing" in result.stderr.decode()


def test_validation_accepts_declared_icon_at_resources_root(tmp_path: Path) -> None:
    """The happy path install.sh always had: the icon the plist declares sits
    at the Resources root, and the icon check reports a pass rather than
    silently not running."""
    bundle = _fake_bundle(tmp_path, (ROOT / "VERSION").read_text().strip())
    result = _validate(bundle)
    assert result.returncode == 0, result.stderr
    assert "Checking the app icon" in result.stdout.decode()


OTOOL_LOAD_TEMPLATE = (
    "           cmd LC_LOAD_DYLIB\n"
    "       cmdsize 72\n"
    "              name {load_ref} (offset 24)\n"
    "           cmd LC_RPATH\n"
    "       cmdsize 40\n"
    "              path /Users/runner/work/portaudio/build (offset 12)\n"
)


def _fake_dylib(path: Path, metadata: str) -> Path:
    """Mach-O magic (the leading bytes of a real arm64/x86_64 binary) plus
    inert build-machine metadata, like a wheel-built portaudio binary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xcf\xfa\xed\xfe" + metadata.encode())
    return path


def _fake_otool(tmp_path: Path, load_ref: str, install_id: str) -> Path:
    """An otool reporting canned load commands and install IDs for any file,
    so the validator's Mach-O pass runs hermetically on any OS."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    otool = bin_dir / "otool"
    otool.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-l" ]; then\n'
        "cat <<'LOAD'\n" + OTOOL_LOAD_TEMPLATE.format(load_ref=load_ref) + "LOAD\n"
        'elif [ "$1" = "-D" ]; then\n'
        "printf '%s:\\n%s\\n' \"$2\" " + shlex.quote(install_id) + "\n"
        "fi\n"
    )
    otool.chmod(0o755)
    return bin_dir


def test_validation_exempts_inert_metadata_in_macho_binaries(tmp_path: Path) -> None:
    """A wheel binary built on a CI runner keeps stale build strings that
    nothing consults at load time. The raw scan flags them; the load-command
    pass clears them — and a stale LC_RPATH is exempt with them."""
    bundle = _fake_bundle(tmp_path, (ROOT / "VERSION").read_text().strip())
    dylib = _fake_dylib(
        bundle / "Contents/Resources/site-packages/_sounddevice_data"
        / "portaudio-binaries/libportaudio.dylib",
        "build dir was /Users/runner/work/portaudio\n",
    )
    fake_bin = _fake_otool(
        tmp_path, "@loader_path/../CoreAudio", "@rpath/libportaudio.dylib",
    )
    result = _validate(bundle, fake_bin)
    assert result.returncode == 0, result.stderr
    assert "inert build-path metadata" in result.stderr.decode()


def test_validation_rejects_active_macho_load_references(tmp_path: Path) -> None:
    """When a Mach-O file's load commands still name a build path, the binary
    genuinely depends on a machine no user has — hard fail, like text leaks."""
    bundle = _fake_bundle(tmp_path, (ROOT / "VERSION").read_text().strip())
    # The string lives in the binary's own bytes (string table), as it does in
    # any real offender — the raw grep must flag the file so the load-command
    # pass adjudicates it.
    _fake_dylib(
        bundle / "Contents/Resources/site-packages/_sounddevice_data"
        / "portaudio-binaries/libportaudio.dylib",
        "/Users/runner/work/portaudio/out/libportaudio.dylib\n",
    )
    fake_bin = _fake_otool(
        tmp_path,
        "/Users/runner/work/portaudio/out/libCoreAudio.dylib",
        "/Users/runner/work/portaudio/out/libportaudio.dylib",
    )
    result = _validate(bundle, fake_bin)
    assert result.returncode != 0
    assert "build-machine or checkout paths" in result.stderr.decode()


def test_validation_exempts_upstream_third_party_text(tmp_path: Path) -> None:
    """Upstream wheel content — docstrings, bytecode co_filenames, METADATA,
    SBOM records — ships strings naming its own build machines (numpy's
    _datasource.py docstring, huggingface_hub's METADATA). Nothing consults
    them at runtime, so a raw hit under site-packages is noted and exempt.
    App-owned text still fails: see test_validation_rejects_baked_absolute_paths."""
    bundle = _fake_bundle(tmp_path, (ROOT / "VERSION").read_text().strip())
    upstream = bundle / "Contents/Resources/site-packages/numpy/lib/_datasource.py"
    upstream.parent.mkdir(parents=True, exist_ok=True)
    upstream.write_text("EXAMPLE = 'save to /home/guido/data'\n")
    result = _validate(bundle)
    assert result.returncode == 0, result.stderr
    assert "upstream third-party metadata" in result.stderr.decode()
