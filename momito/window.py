"""Native dashboard window: an NSWindow wrapping a WKWebView on the local server.

Process identity (Dock icon, menu bar name, permissions) is handled by the
compiled launcher in Momito.app (see installer/launcher.c). `setup_app_identity`
covers the leftovers: accessory policy so the app stays out of the Dock at
idle, and the schnauzer icon for dev runs from a plain terminal python, which
would otherwise surface as Python.app.
"""

from pathlib import Path
from typing import Any, Optional

import AppKit
import Foundation
import WebKit
import objc

ICON_PNG = Path(__file__).parent.parent / "assets" / "icon-1024.png"

WINDOW_BG = AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(0x1B / 255, 0x15 / 255, 0x12 / 255, 1.0)


def setup_app_identity() -> None:
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    if ICON_PNG.exists():
        icon = AppKit.NSImage.alloc().initWithContentsOfFile_(str(ICON_PNG))
        if icon:
            app.setApplicationIconImage_(icon)


def _item(title: str, action: Optional[str], key: str) -> Any:
    return AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)


def _build_main_menu() -> Any:
    """rumps apps have no main menu, so the menu bar keeps showing the previous
    app's menus even when Momito is frontmost. Give it a real one."""
    main = AppKit.NSMenu.alloc().initWithTitle_("MainMenu")

    app_root = _item("Momito", None, "")
    app_menu = AppKit.NSMenu.alloc().initWithTitle_("Momito")
    app_menu.addItem_(_item("Close Window", "performClose:", "w"))
    app_menu.addItem_(_item("Hide Momito", "hide:", "h"))
    app_menu.addItem_(AppKit.NSMenuItem.separatorItem())
    app_menu.addItem_(_item("Quit Momito", "terminate:", "q"))
    main.addItem_(app_root)
    main.setSubmenu_forItem_(app_menu, app_root)

    edit_root = _item("Edit", None, "")
    edit_menu = AppKit.NSMenu.alloc().initWithTitle_("Edit")
    edit_menu.addItem_(_item("Undo", "undo:", "z"))
    edit_menu.addItem_(_item("Redo", "redo:", "Z"))
    edit_menu.addItem_(AppKit.NSMenuItem.separatorItem())
    edit_menu.addItem_(_item("Cut", "cut:", "x"))
    edit_menu.addItem_(_item("Copy", "copy:", "c"))
    edit_menu.addItem_(_item("Paste", "paste:", "v"))
    edit_menu.addItem_(AppKit.NSMenuItem.separatorItem())
    edit_menu.addItem_(_item("Select All", "selectAll:", "a"))
    main.addItem_(edit_root)
    main.setSubmenu_forItem_(edit_menu, edit_root)

    return main


class _WindowDelegate(AppKit.NSObject):  # type: ignore[misc]
    def windowWillClose_(self, _note: Any) -> None:
        # back to menu-bar-only when the dashboard closes
        AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)


class _MainThreadCaller(AppKit.NSObject):  # type: ignore[misc]
    """AppKit is main-thread-only; this hops a show() call over from any thread."""

    def initWithWindow_(self, window: "DashboardWindow") -> Any:
        self = objc.super(_MainThreadCaller, self).init()
        self._dashboard = window
        return self

    def open_(self, _arg: Any) -> None:
        self._dashboard.show()

    def reactivate_(self, _arg: Any) -> None:
        # AppKit does not reliably hand the menu bar to an app that switched
        # Accessory -> Regular while already becoming active; a second
        # activation on a later runloop turn makes it stick.
        AppKit.NSRunningApplication.currentApplication().activateWithOptions_(
            AppKit.NSApplicationActivateIgnoringOtherApps
        )


class DashboardWindow:
    """Lazily built, reused across opens. Must be driven from the main thread."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._window: Optional[Any] = None
        self._web: Optional[Any] = None
        self._delegate = _WindowDelegate.alloc().init()
        self._caller = _MainThreadCaller.alloc().initWithWindow_(self)

    def show_async(self) -> None:
        """Safe to call from any thread (e.g. the dashboard server)."""
        self._caller.performSelectorOnMainThread_withObject_waitUntilDone_("open:", None, False)

    def _build(self) -> None:
        rect = Foundation.NSMakeRect(0, 0, 1120, 720)
        style = (
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskMiniaturizable
            | AppKit.NSWindowStyleMaskResizable
        )
        win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False
        )
        win.setTitle_("Momito")
        win.setReleasedWhenClosed_(False)
        win.setDelegate_(self._delegate)
        win.setContentMinSize_(Foundation.NSMakeSize(980, 520))
        win.setBackgroundColor_(WINDOW_BG)
        win.setTitlebarAppearsTransparent_(True)
        win.setAppearance_(AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua))
        web = WebKit.WKWebView.alloc().initWithFrame_(rect)
        web.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        win.setContentView_(web)
        win.center()
        self._window = win
        self._web = web

    def install_reopen_handler(self) -> bool:
        """Show the dashboard when the user opens Momito.app while it is already running.

        macOS sends the running instance a reopen event; rumps' app delegate
        does not implement it, so we graft the handler onto that class.

        This reaches into rumps' private module layout, so it is written to
        fail quietly: if a future rumps moves that class, reopening from the
        Dock stops working but the menu bar item still opens the dashboard.
        Returns whether the graft took, so the caller can say so in the log
        instead of leaving a silent dead feature.
        """
        try:
            from rumps.rumps import NSApp as RumpsDelegate
        except Exception:
            return False

        dashboard = self

        def applicationShouldHandleReopen_hasVisibleWindows_(
            _self: Any, _sender: Any, _has_windows: bool
        ) -> bool:
            dashboard.show()
            return False

        try:
            objc.classAddMethod(
                RumpsDelegate,
                b"applicationShouldHandleReopen:hasVisibleWindows:",
                objc.selector(
                    applicationShouldHandleReopen_hasVisibleWindows_,
                    selector=b"applicationShouldHandleReopen:hasVisibleWindows:",
                    signature=objc._C_NSBOOL + b"@:@" + objc._C_NSBOOL,
                ),
            )
        except Exception:
            return False
        return True

    def show(self) -> None:
        # while the dashboard is open, appear in the Dock like a regular app
        AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
        if AppKit.NSApp.mainMenu() is None:
            AppKit.NSApp.setMainMenu_(_build_main_menu())
        if self._window is None:
            self._build()
        assert self._web is not None and self._window is not None
        req = Foundation.NSURLRequest.requestWithURL_(Foundation.NSURL.URLWithString_(self.url))
        self._web.loadRequest_(req)
        self._window.makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        self._caller.performSelector_withObject_afterDelay_("reactivate:", None, 0.15)
