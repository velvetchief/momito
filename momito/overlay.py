"""Floating recording pill: a small bottom-center panel that shows dictation
state over any app, including full-screen ones. Never takes focus or clicks.

Main-thread only: build lazily and call update() from the rumps refresh timer.
"""

from typing import Optional, Tuple

import AppKit
import Foundation

WIDTH = 150.0
HEIGHT = 34.0
BOTTOM_MARGIN = 56.0

# warm palette matching the dashboard tokens
_BG = (0.133, 0.106, 0.090, 0.95)  # #221B17
_BORDER = (0.220, 0.173, 0.141, 1.0)  # #382C24
_TEXT = (0.957, 0.925, 0.890, 1.0)  # #F4ECE3
_STYLES = {
    "rec": ("Listening…", (0.898, 0.396, 0.306, 1.0)),  # dot #E5654E
    "busy": ("Typing…", (1.0, 0.702, 0.361, 1.0)),  # dot #FFB35C
}


def _color(rgba: Tuple[float, float, float, float]) -> AppKit.NSColor:
    return AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*rgba)


class RecordingOverlay:
    def __init__(self) -> None:
        self._panel: Optional[AppKit.NSPanel] = None
        self._label: Optional[AppKit.NSTextField] = None
        self._dot: Optional[AppKit.NSView] = None
        self._shown_state: Optional[str] = None

    def _build(self) -> None:
        rect = Foundation.NSMakeRect(0, 0, WIDTH, HEIGHT)
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(AppKit.NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setIgnoresMouseEvents_(True)
        panel.setHasShadow_(True)
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        content = AppKit.NSView.alloc().initWithFrame_(rect)
        content.setWantsLayer_(True)
        layer = content.layer()
        layer.setCornerRadius_(HEIGHT / 2)
        layer.setBackgroundColor_(_color(_BG).CGColor())
        layer.setBorderWidth_(1.0)
        layer.setBorderColor_(_color(_BORDER).CGColor())

        dot = AppKit.NSView.alloc().initWithFrame_(
            Foundation.NSMakeRect(16, HEIGHT / 2 - 4, 8, 8)
        )
        dot.setWantsLayer_(True)
        dot.layer().setCornerRadius_(4.0)
        content.addSubview_(dot)

        label = AppKit.NSTextField.labelWithString_("")
        label.setFont_(AppKit.NSFont.systemFontOfSize_weight_(13, AppKit.NSFontWeightMedium))
        label.setTextColor_(_color(_TEXT))
        label.setFrame_(Foundation.NSMakeRect(32, (HEIGHT - 18) / 2, WIDTH - 44, 18))
        content.addSubview_(label)

        panel.setContentView_(content)
        self._panel, self._label, self._dot = panel, label, dot

    def _position(self) -> None:
        assert self._panel is not None
        screen = AppKit.NSScreen.mainScreen()
        if screen is None:
            return
        frame = screen.visibleFrame()
        x = frame.origin.x + (frame.size.width - WIDTH) / 2
        self._panel.setFrameOrigin_(Foundation.NSMakePoint(x, frame.origin.y + BOTTOM_MARGIN))

    def update(self, state: str) -> None:
        """Show the pill for 'rec'/'busy', hide it for anything else."""
        if state == self._shown_state:
            return
        self._shown_state = state
        style = _STYLES.get(state)
        if style is None:
            if self._panel is not None:
                self._panel.orderOut_(None)
            return
        if self._panel is None:
            self._build()
        assert self._panel and self._label and self._dot
        text, dot_color = style
        self._label.setStringValue_(text)
        self._dot.layer().setBackgroundColor_(_color(dot_color).CGColor())
        self._position()
        self._panel.orderFrontRegardless()
