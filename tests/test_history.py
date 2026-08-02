"""History store tests: the dashboard's numbers have to be trustworthy."""

import sqlite3
import stat
import time
from pathlib import Path

import pytest

from momito.history import History, count_words


@pytest.fixture()
def store(tmp_path: Path) -> History:
    return History(db_path=tmp_path / "history.db")


def test_add_and_list(store: History) -> None:
    e = store.add("hello there world", app_name="Notes", seconds=2.5)
    assert e.id > 0
    assert e.chars == 17
    assert e.words == 3
    entries = store.entries()
    assert len(entries) == 1
    assert entries[0].text == "hello there world"
    assert entries[0].app_name == "Notes"
    assert entries[0].seconds == 2.5


def test_newest_first(store: History) -> None:
    store.add("first")
    store.add("second")
    texts = [e.text for e in store.entries()]
    assert texts == ["second", "first"]


def test_search_matches_text_and_app(store: History) -> None:
    store.add("buy schnauzer treats", app_name="Notes")
    store.add("meeting at noon", app_name="Slack")
    assert [e.text for e in store.entries(search="schnauzer")] == ["buy schnauzer treats"]
    assert [e.text for e in store.entries(search="slack")] == ["meeting at noon"]
    assert store.entries(search="zebra") == []


def test_delete(store: History) -> None:
    e = store.add("delete me")
    keep = store.add("keep me")
    store.delete(e.id)
    ids = [x.id for x in store.entries()]
    assert ids == [keep.id]


def test_clear(store: History) -> None:
    store.add("one")
    store.add("two")
    store.clear()
    assert store.entries() == []
    assert store.stats()["total"] == 0


def test_stats(store: History) -> None:
    store.add("one two three", seconds=3.0)
    store.add("four five", seconds=2.0)
    s = store.stats()
    assert s["total"] == 2
    assert s["words"] == 5
    assert s["seconds"] == 5.0
    # both entries were just added, so they count toward today
    assert s["today"] == 2
    assert s["today_words"] == 5


def test_stats_empty(store: History) -> None:
    s = store.stats()
    assert s == {"total": 0, "words": 0, "seconds": 0, "today": 0, "today_words": 0}


def test_replacements_crud(store: History) -> None:
    r = store.add_replacement("mo mito", "Momito")
    assert r.id > 0
    store.add_replacement("teh", "the")
    listed = store.replacements()
    assert [(x.spoken, x.written) for x in listed] == [("mo mito", "Momito"), ("teh", "the")]
    assert store.replacement_pairs() == [("mo mito", "Momito"), ("teh", "the")]
    store.delete_replacement(r.id)
    assert store.replacement_pairs() == [("teh", "the")]


def test_replacements_sorted_case_insensitively(store: History) -> None:
    store.add_replacement("zebra", "Zebra")
    store.add_replacement("Apple", "apple inc")
    assert [x.spoken for x in store.replacements()] == ["Apple", "zebra"]


# --- word counting: the stats view and the detail view have to agree ---


def test_stats_words_match_the_entries(store: History) -> None:
    """The old stats SQL counted spaces plus one, so a newline or a double
    space made the totals disagree with what each entry showed."""
    messy = ["one  two", "line one\nline two", "  padded  ", "single"]
    for text in messy:
        store.add(text)
    assert store.stats()["words"] == sum(e.words for e in store.entries())
    assert store.stats()["words"] == sum(count_words(t) for t in messy)


def test_empty_text_counts_as_no_words(store: History) -> None:
    store.add("   ")
    assert store.entries()[0].words == 0
    assert store.stats()["words"] == 0


def legacy_db(path: Path, rows: list) -> None:
    """A database written before the words column existed."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            text TEXT NOT NULL,
            app_name TEXT NOT NULL DEFAULT '',
            seconds REAL NOT NULL DEFAULT 0
        )"""
    )
    now = time.time()
    conn.executemany(
        "INSERT INTO entries (ts, text, app_name, seconds) VALUES (?, ?, '', 0)",
        [(now, text) for text in rows],
    )
    conn.commit()
    conn.close()


def test_migration_adds_and_backfills_the_words_column(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    legacy_db(path, ["one two three", "line one\nline two", "  padded  "])
    store = History(db_path=path)
    assert {e.text: e.words for e in store.entries()} == {
        "one two three": 3,
        "line one\nline two": 4,
        "  padded  ": 1,
    }
    assert store.stats()["words"] == 8


def test_migration_keeps_the_old_rows_intact(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    legacy_db(path, ["keep me"])
    store = History(db_path=path)
    assert [e.text for e in store.entries()] == ["keep me"]


def test_migration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    legacy_db(path, ["one two"])
    History(db_path=path)
    store = History(db_path=path)  # reopening must not re-migrate or double count
    assert store.stats()["words"] == 2


def test_database_is_owner_only(store: History) -> None:
    """It holds every word the user has ever dictated."""
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700
