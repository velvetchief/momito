"""SQLite-backed transcription history. Lives in ~/Library/Application Support/Momito."""

import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

DEFAULT_DB = Path.home() / "Library" / "Application Support" / "Momito" / "history.db"


def count_words(text: str) -> int:
    """The one definition of a word. Stats and detail views must agree."""
    return len(text.split())


@dataclass
class Replacement:
    id: int
    spoken: str
    written: str


@dataclass
class Entry:
    id: int
    ts: float
    text: str
    app_name: str
    seconds: float
    words: int = 0

    @property
    def chars(self) -> int:
        return len(self.text)


class History:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.path = db_path or DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                text TEXT NOT NULL,
                app_name TEXT NOT NULL DEFAULT '',
                seconds REAL NOT NULL DEFAULT 0,
                words INTEGER NOT NULL DEFAULT 0
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS replacements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spoken TEXT NOT NULL,
                written TEXT NOT NULL
            )"""
        )
        self._migrate()
        self._conn.commit()
        self._restrict_permissions()

    def _migrate(self) -> None:
        """Databases written before the words column stored no count, and the
        SQL that stood in for one (spaces plus one) miscounted anything with
        newlines or double spaces. Add the column once and backfill it."""
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(entries)")}
        if "words" in columns:
            return
        self._conn.execute("ALTER TABLE entries ADD COLUMN words INTEGER NOT NULL DEFAULT 0")
        rows = self._conn.execute("SELECT id, text FROM entries").fetchall()
        self._conn.executemany(
            "UPDATE entries SET words = ? WHERE id = ?",
            [(count_words(text), row_id) for row_id, text in rows],
        )

    def _restrict_permissions(self) -> None:
        """Every word the user has ever dictated is in this file. It has no
        business being world-readable on a shared or backed-up Mac."""
        try:
            self.path.parent.chmod(0o700)
            self.path.chmod(0o600)
        except OSError:
            pass  # a read-only or exotic filesystem must not stop the app

    def add(self, text: str, app_name: str = "", seconds: float = 0.0) -> Entry:
        ts = time.time()
        words = count_words(text)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO entries (ts, text, app_name, seconds, words) VALUES (?, ?, ?, ?, ?)",
                (ts, text, app_name, seconds, words),
            )
            self._conn.commit()
            assert cur.lastrowid is not None
            return Entry(cur.lastrowid, ts, text, app_name, seconds, words)

    def entries(self, search: str = "", limit: int = 500) -> List[Entry]:
        q = "SELECT id, ts, text, app_name, seconds, words FROM entries"
        args: tuple = ()
        if search:
            q += " WHERE text LIKE ? OR app_name LIKE ?"
            like = f"%{search}%"
            args = (like, like)
        q += " ORDER BY ts DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(q, args + (limit,)).fetchall()
        return [Entry(*row) for row in rows]

    def delete(self, entry_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM entries")
            self._conn.commit()

    # --- custom dictionary ---

    def add_replacement(self, spoken: str, written: str) -> Replacement:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO replacements (spoken, written) VALUES (?, ?)",
                (spoken, written),
            )
            self._conn.commit()
            assert cur.lastrowid is not None
            return Replacement(cur.lastrowid, spoken, written)

    def replacements(self) -> List[Replacement]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, spoken, written FROM replacements ORDER BY spoken COLLATE NOCASE"
            ).fetchall()
        return [Replacement(*row) for row in rows]

    def replacement_pairs(self) -> List[Tuple[str, str]]:
        """(spoken, written) pairs for the dictation pipeline."""
        return [(r.spoken, r.written) for r in self.replacements()]

    def delete_replacement(self, replacement_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM replacements WHERE id = ?", (replacement_id,))
            self._conn.commit()

    def stats(self) -> dict:
        day_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self._lock:
            total, words, seconds = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(words), 0), COALESCE(SUM(seconds), 0) FROM entries"
            ).fetchone()
            today, today_words = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(words), 0) FROM entries WHERE ts >= ?",
                (day_start,),
            ).fetchone()
        return {
            "total": total,
            "words": words,
            "seconds": round(seconds, 1),
            "today": today,
            "today_words": today_words,
        }
