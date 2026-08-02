"""The file a second launch reads to find the first one, and its API token."""

import json
import os
import stat
from pathlib import Path

from momito import instance


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "instance.json"
    instance.write(51234, "sekrit", pid=999, path=target)
    assert instance.read(target) == {"port": 51234, "token": "sekrit", "pid": 999}


def test_write_creates_the_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deeper" / "instance.json"
    instance.write(1, "t", path=target)
    assert target.exists()


def test_file_is_owner_only(tmp_path: Path) -> None:
    """It holds the token that unlocks every transcript."""
    target = tmp_path / "instance.json"
    instance.write(1, "t", path=target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_write_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    target = tmp_path / "instance.json"
    instance.write(1, "t", path=target)
    assert [p.name for p in tmp_path.iterdir()] == ["instance.json"]


def test_rewrite_replaces_cleanly(tmp_path: Path) -> None:
    target = tmp_path / "instance.json"
    instance.write(1, "old", path=target)
    instance.write(2, "new", path=target)
    got = instance.read(target)
    assert got is not None and got["port"] == 2 and got["token"] == "new"


def test_missing_file_reads_as_none(tmp_path: Path) -> None:
    assert instance.read(tmp_path / "nope.json") is None


def test_garbage_reads_as_none(tmp_path: Path) -> None:
    target = tmp_path / "instance.json"
    target.write_text("not json at all")
    assert instance.read(target) is None


def test_non_object_reads_as_none(tmp_path: Path) -> None:
    target = tmp_path / "instance.json"
    target.write_text("[1, 2, 3]")
    assert instance.read(target) is None


def test_bad_field_types_read_as_none(tmp_path: Path) -> None:
    target = tmp_path / "instance.json"
    for payload in (
        {"port": "47747", "token": "t"},  # port must be a real int
        {"port": 47747, "token": ""},  # empty token would authorize nothing
        {"port": 47747},
        {"token": "t"},
    ):
        target.write_text(json.dumps(payload))
        assert instance.read(target) is None, payload


def test_clear_removes_the_file_and_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "instance.json"
    instance.write(1, "t", path=target)
    instance.clear(target)
    assert not target.exists()
    instance.clear(target)  # a second quit must not raise


def test_pid_defaults_to_this_process(tmp_path: Path) -> None:
    target = tmp_path / "instance.json"
    instance.write(1, "t", path=target)
    got = instance.read(target)
    assert got is not None and got["pid"] == os.getpid()
