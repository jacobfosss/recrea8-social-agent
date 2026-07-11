"""
Looks for brand assets you provide — logo and font — and falls back
gracefully to sensible defaults if they're not there yet.

Drop your files at:
  content/branding/logo.png   (transparent background recommended)
  content/branding/font.ttf   (or .otf)
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRANDING_DIR = ROOT / "content" / "branding"

FALLBACK_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def get_logo_path():
    for ext in (".png", ".jpg", ".jpeg"):
        p = BRANDING_DIR / f"logo{ext}"
        if p.exists():
            return p
    return None


def get_font_path():
    for ext in (".ttf", ".otf"):
        p = BRANDING_DIR / f"font{ext}"
        if p.exists():
            return str(p)
    for fallback in FALLBACK_FONTS:
        if os.path.exists(fallback):
            return fallback
    return None
