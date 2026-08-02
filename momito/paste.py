"""Deliver text into the frontmost app: clipboard swap, Cmd-V, put it all back.

Two things this file has to get right, because both of them are the product
promise rather than a nicety:

1. The clipboard is one global resource, so pastes are serialized. Two
   overlapping pastes could otherwise cross their swap and restore steps and
   leave a transcript sitting in the user's clipboard forever.
2. The snapshot copies every representation on the pasteboard, not just plain
   text. Reading it back as a string would turn a copied image, file, or styled
   snippet into an empty clipboard the moment we restored it.
"""

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
from pynput.keyboard import Controller, Key

SETTLE_DELAY = 0.08  # the pasteboard write is async-ish; give it a beat
RESTORE_DELAY = 0.6  # let slow apps finish pasting before the old clipboard returns

# One clipboard, one lock, shared by every Paster in the process.
_CLIPBOARD_LOCK = threading.RLock()

Snapshot = List[Dict[str, Any]]


class MacClipboard:
    """The real pasteboard. Snapshots keep every type each item carries."""

    def snapshot(self) -> Snapshot:
        pb = NSPasteboard.generalPasteboard()
        items: Snapshot = []
        for item in pb.pasteboardItems() or []:
            data: Dict[str, Any] = {}
            for kind in item.types() or []:
                # Promised (lazily provided) types come back as None; there is
                # nothing to copy and nothing we can restore.
                blob = item.dataForType_(kind)
                if blob is not None:
                    data[str(kind)] = blob
            if data:
                items.append(data)
        return items

    def set_text(self, text: str) -> None:
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, NSPasteboardTypeString)

    def restore(self, snapshot: Snapshot) -> None:
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        items = []
        for data in snapshot:
            item = NSPasteboardItem.alloc().init()
            for kind, blob in data.items():
                item.setData_forType_(blob, kind)
            items.append(item)
        if items:
            pb.writeObjects_(items)


def _press_cmd_v(kbd: Controller = Controller()) -> None:
    with kbd.pressed(Key.cmd):
        kbd.press("v")
        kbd.release("v")


class Paster:
    def __init__(
        self,
        clipboard: Any = None,
        keystroke: Optional[Callable[[], None]] = None,
        sleep: Callable[[float], None] = time.sleep,
        settle_delay: float = SETTLE_DELAY,
        restore_delay: float = RESTORE_DELAY,
    ) -> None:
        self.clipboard = clipboard if clipboard is not None else MacClipboard()
        self.keystroke = keystroke or _press_cmd_v
        self.sleep = sleep
        self.settle_delay = settle_delay
        self.restore_delay = restore_delay

    def paste(self, text: str) -> None:
        """Blocks for about `settle_delay + restore_delay`. Call it off the
        main thread; holding the lock the whole way is what keeps a second
        paste from clobbering this one's restore."""
        with _CLIPBOARD_LOCK:
            try:
                snapshot = self.clipboard.snapshot()
            except Exception:
                snapshot = None  # restore nothing rather than restore garbage
            self.clipboard.set_text(text)
            self.sleep(self.settle_delay)
            self.keystroke()
            self.sleep(self.restore_delay)
            if snapshot is not None:
                try:
                    self.clipboard.restore(snapshot)
                except Exception:
                    pass  # a failed restore must not take the dictation with it


_default = Paster()


def paste_text(text: str) -> None:
    _default.paste(text)
