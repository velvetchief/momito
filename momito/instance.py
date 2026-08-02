"""Where a running Momito publishes how to reach it.

A second launch needs two things the old code guessed at: which port the first
instance actually got (it falls back to a random one when 47747 is taken), and
the per-launch API token. Both live in one 0600 file next to the history
database, written atomically so a half-written file can never be read.
"""

import json
import os
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path.home() / "Library" / "Application Support" / "Momito" / "instance.json"


def write(port: int, token: str, pid: Optional[int] = None, path: Optional[Path] = None) -> None:
    target = path or DEFAULT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"port": port, "token": token, "pid": pid or os.getpid()})
    tmp = target.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(str(tmp), str(target))  # atomic: readers see old or new, never half


def read(path: Optional[Path] = None) -> Optional[dict]:
    """The running instance's {port, token, pid}, or None if there is no usable file."""
    target = path or DEFAULT_PATH
    try:
        data = json.loads(target.read_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    port, token = data.get("port"), data.get("token")
    if not isinstance(port, int) or not isinstance(token, str) or not token:
        return None
    return {"port": port, "token": token, "pid": data.get("pid")}


def clear(path: Optional[Path] = None) -> None:
    try:
        (path or DEFAULT_PATH).unlink()
    except OSError:
        pass
