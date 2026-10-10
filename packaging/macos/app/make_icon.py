"""Draw Screenwall.app's icon (AppIcon.icns) from the brand mark.

    python3 packaging/macos/app/make_icon.py        (macOS: needs Pillow, sips and iconutil)

The mark is frontend/public/favicon.svg (and frontend/src/ui/BrandMark.tsx), a 20x20 drawing:
a rounded square (x 1..19, rx 5, #2F6B4F) with two white rounded bars, 2.4 high with rx 1.2:
x 5, y 6.5, width 10; and x 5, y 11.1, width 6.5 at opacity .55. Here it is drawn at 1024 px on
the macOS icon grid (the 18-unit square becomes the 824 px body, 100 px from each edge) with a
soft shadow under it, then sips makes the smaller sizes and iconutil packs AppIcon.icns next to
this script. The build (packaging/build_release.sh) uses the committed AppIcon.icns; run this
again only when the mark changes. Nothing is deleted: an existing AppIcon.icns is moved to
AppIcon.icns.<time>.bak first.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
OUT = HERE / "AppIcon.icns"

CANVAS = 1024
BODY = 824  # Apple's macOS icon grid: the shape is 824 px on a 1024 px canvas
MARGIN = (CANVAS - BODY) / 2
SCALE = BODY / 18  # the mark's square is 18 units wide (x 1..19)
SUPERSAMPLE = 4  # draw at 4096 px and scale down for smooth edges

GREEN = (0x2F, 0x6B, 0x4F, 255)
WHITE = (255, 255, 255, 255)
SECOND_BAR_ALPHA = round(0.55 * 255)

# (iconset name, pixel size) as iconutil expects them
SIZES = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
]


def box(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    """A rectangle in mark units -> pixel box on the supersampled canvas."""
    k = SUPERSAMPLE
    left = (MARGIN + (x - 1) * SCALE) * k
    top = (MARGIN + (y - 1) * SCALE) * k
    return (left, top, left + w * SCALE * k, top + h * SCALE * k)


def draw_master() -> Image.Image:
    size = CANVAS * SUPERSAMPLE
    radius = 5 * SCALE * SUPERSAMPLE
    bar_radius = 1.2 * SCALE * SUPERSAMPLE

    # Soft shadow under the body, as on Apple's icon template.
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sx0, sy0, sx1, sy1 = box(1, 1, 18, 18)
    offset = 10 * SUPERSAMPLE
    ImageDraw.Draw(shadow).rounded_rectangle(
        (sx0, sy0 + offset, sx1, sy1 + offset), radius=radius, fill=(0, 0, 0, 80))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14 * SUPERSAMPLE))

    body = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    d.rounded_rectangle(box(1, 1, 18, 18), radius=radius, fill=GREEN)
    d.rounded_rectangle(box(5, 6.5, 10, 2.4), radius=bar_radius, fill=WHITE)

    second = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(second).rounded_rectangle(
        box(5, 11.1, 6.5, 2.4), radius=bar_radius, fill=(255, 255, 255, SECOND_BAR_ALPHA))

    master = Image.alpha_composite(shadow, body)
    master = Image.alpha_composite(master, second)
    return master.resize((CANVAS, CANVAS), Image.LANCZOS)


def main() -> int:
    for tool in ("sips", "iconutil"):
        if shutil.which(tool) is None:
            print(f"make_icon: {tool} not found (macOS only)", file=sys.stderr)
            return 1
    # A fresh temporary folder (left in $TMPDIR, which macOS clears on its own; nothing is deleted).
    work = Path(tempfile.mkdtemp(prefix="screenwall-icon."))
    master = work / "icon_1024.png"
    draw_master().save(master)
    iconset = work / "AppIcon.iconset"
    iconset.mkdir()
    for name, px in SIZES:
        subprocess.run(["sips", "-z", str(px), str(px), str(master), "--out",
                        str(iconset / name)], check=True, stdout=subprocess.DEVNULL)
    built = work / "AppIcon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(built)], check=True)
    if OUT.exists():
        aside = OUT.with_name(f"AppIcon.icns.{time.strftime('%Y%m%d-%H%M%S')}.bak")
        OUT.rename(aside)
        print(f"previous icon moved to {aside.name}")
    shutil.copyfile(built, OUT)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
