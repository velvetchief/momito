"""Clipboard delivery tests, against a fake pasteboard.

What these protect: the user's clipboard. Momito borrows it for every
dictation, so an ordering slip or an interleaved second paste means someone's
copied image or password is gone.
"""

import threading
import time
from typing import Any, Dict, List, Optional

from momito.paste import Paster

TEXT = "public.utf8-plain-text"
PNG = "public.png"


class FakeClipboard:
    """Records what was asked of it, in order, and holds typed items."""

    def __init__(self, contents: Optional[List[Dict[str, Any]]] = None) -> None:
        self.contents: List[Dict[str, Any]] = list(contents or [])
        self.ops: List[str] = []
        self.snapshot_error: Optional[Exception] = None
        self.restore_error: Optional[Exception] = None

    def snapshot(self) -> List[Dict[str, Any]]:
        self.ops.append("snapshot")
        if self.snapshot_error:
            raise self.snapshot_error
        return [dict(item) for item in self.contents]

    def set_text(self, text: str) -> None:
        self.ops.append("set_text")
        self.contents = [{TEXT: text}]

    def restore(self, snapshot: List[Dict[str, Any]]) -> None:
        self.ops.append("restore")
        if self.restore_error:
            raise self.restore_error
        self.contents = [dict(item) for item in snapshot]


def make(clipboard: FakeClipboard, keystroke: Any = None, sleep: Any = None) -> Paster:
    return Paster(
        clipboard=clipboard,
        keystroke=keystroke or (lambda: None),
        sleep=sleep or (lambda _s: None),
        settle_delay=0,
        restore_delay=0,
    )


def test_order_is_snapshot_write_paste_restore() -> None:
    clip = FakeClipboard([{TEXT: "before"}])
    order: List[str] = []
    paster = make(clip, keystroke=lambda: order.append("keystroke"))
    paster.paste("dictated ")
    assert clip.ops == ["snapshot", "set_text", "restore"]
    assert order == ["keystroke"]


def test_keystroke_happens_while_the_transcript_is_on_the_clipboard() -> None:
    clip = FakeClipboard([{TEXT: "before"}])
    seen: List[Any] = []
    make(clip, keystroke=lambda: seen.append(clip.contents)).paste("dictated ")
    assert seen == [[{TEXT: "dictated "}]]


def test_original_contents_come_back() -> None:
    clip = FakeClipboard([{TEXT: "before"}])
    make(clip).paste("dictated ")
    assert clip.contents == [{TEXT: "before"}]


def test_non_text_clipboard_survives() -> None:
    """A copied image is not a string. Reading the clipboard as text and
    writing it back would have destroyed this."""
    original = [{PNG: b"\x89PNG-ish", TEXT: "alt text"}]
    clip = FakeClipboard(original)
    make(clip).paste("dictated ")
    assert clip.contents == original


def test_multiple_items_survive() -> None:
    original = [{TEXT: "one"}, {TEXT: "two"}]
    clip = FakeClipboard(original)
    make(clip).paste("dictated ")
    assert clip.contents == original


def test_empty_clipboard_restores_empty() -> None:
    clip = FakeClipboard([])
    make(clip).paste("dictated ")
    assert clip.contents == []


def test_snapshot_failure_leaves_the_transcript_rather_than_restoring_garbage() -> None:
    clip = FakeClipboard([{TEXT: "before"}])
    clip.snapshot_error = RuntimeError("pasteboard busy")
    make(clip).paste("dictated ")
    assert clip.ops == ["snapshot", "set_text"]  # no restore attempted
    assert clip.contents == [{TEXT: "dictated "}]


def test_restore_failure_does_not_raise() -> None:
    clip = FakeClipboard([{TEXT: "before"}])
    clip.restore_error = RuntimeError("pasteboard busy")
    make(clip).paste("dictated ")  # must not propagate


def test_delays_are_awaited_in_order() -> None:
    clip = FakeClipboard([{TEXT: "before"}])
    slept: List[float] = []
    paster = Paster(
        clipboard=clip,
        keystroke=lambda: slept.append(-1.0),
        sleep=slept.append,
        settle_delay=0.08,
        restore_delay=0.6,
    )
    paster.paste("x")
    assert slept == [0.08, -1.0, 0.6]  # settle, then paste, then wait to restore


def test_concurrent_pastes_do_not_interleave() -> None:
    """Two dictations finishing at once must not cross their swap and restore
    steps; whoever loses the lock waits."""
    clip = FakeClipboard([{TEXT: "before"}])

    def slow_keystroke() -> None:
        time.sleep(0.05)

    paster = Paster(
        clipboard=clip,
        keystroke=slow_keystroke,
        sleep=time.sleep,
        settle_delay=0.01,
        restore_delay=0.01,
    )
    threads = [threading.Thread(target=paster.paste, args=(f"text {i} ",)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert clip.ops == ["snapshot", "set_text", "restore"] * 3
    assert clip.contents == [{TEXT: "before"}]
