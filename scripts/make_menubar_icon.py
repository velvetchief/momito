"""Render assets/menubar-template.png (144x144) for the menu bar.

Template images use only the alpha channel, so the schnauzer's details must be
true transparency: draw the silhouette, then erase the holes (destination-out).
Rerun after editing menubar-silhouette.svg / menubar-holes.svg:

    .venv/bin/python scripts/make_menubar_icon.py
"""

from pathlib import Path

import AppKit
import Foundation

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZE = 144


def _render(path: Path, rep: AppKit.NSBitmapImageRep, op: int) -> None:
    img = AppKit.NSImage.alloc().initWithContentsOfFile_(str(path))
    if img is None or not img.isValid():
        raise SystemExit(f"could not load {path}")
    AppKit.NSGraphicsContext.saveGraphicsState()
    ctx = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    AppKit.NSGraphicsContext.setCurrentContext_(ctx)
    img.drawInRect_fromRect_operation_fraction_(
        Foundation.NSMakeRect(0, 0, SIZE, SIZE), Foundation.NSZeroRect, op, 1.0
    )
    ctx.flushGraphics()
    AppKit.NSGraphicsContext.restoreGraphicsState()


def main() -> None:
    rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, SIZE, SIZE, 8, 4, True, False, AppKit.NSCalibratedRGBColorSpace, 0, 0
    )
    _render(ASSETS / "menubar-silhouette.svg", rep, AppKit.NSCompositingOperationSourceOver)
    _render(ASSETS / "menubar-holes.svg", rep, AppKit.NSCompositingOperationDestinationOut)
    out = ASSETS / "menubar-template.png"
    png = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, None)
    png.writeToFile_atomically_(str(out), True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
