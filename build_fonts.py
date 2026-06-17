"""
Regenerate embedded font subsets (nba/fonts/archivo-*.b64).

You only need to run this if you want to change the font or the character set.
The GitHub Action does NOT run this — it just reads the pre-generated .b64 files.

Requirements:
    pip install fonttools brotli

Usage:
    1. Download the Archivo variable font to /tmp/archivo.ttf:
       https://github.com/google/fonts/raw/main/ofl/archivo/Archivo[wdth,wght].ttf
    2. python nba/build_fonts.py /tmp/archivo.ttf
"""

import io
import sys
import base64
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

FONTS_DIR = Path(__file__).parent / "fonts"

# Characters the card can render. Uppercase + lowercase + digits + punctuation.
CHARS = (
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    " -,.'"
    "\u2013"  # en dash used as score separator
)

WEIGHTS = (700, 900)


def build(src_ttf):
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    for weight in WEIGHTS:
        font = TTFont(src_ttf)
        instantiateVariableFont(font, {"wght": weight, "wdth": 100}, inplace=True)
        tmp = io.BytesIO()
        font.save(tmp)
        tmp.seek(0)

        f2 = TTFont(tmp)
        ss = subset.Subsetter()
        ss.populate(text=CHARS)
        ss.subset(f2)
        f2.flavor = "woff2"

        buf = io.BytesIO()
        f2.save(buf)
        data = buf.getvalue()

        b64 = base64.b64encode(data).decode("ascii")
        out = FONTS_DIR / f"archivo-{weight}.b64"
        out.write_text(b64)
        print(f"weight {weight}: {len(data)} bytes woff2 -> {out}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python nba/build_fonts.py <path-to-archivo-variable.ttf>")
        sys.exit(1)
    build(sys.argv[1])
