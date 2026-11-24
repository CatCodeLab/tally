"""Generate receipt fixtures (PNG, HEIC, two-page PDF). Run: uv run python tests/fixtures/make_fixtures.py"""
from pathlib import Path

import pillow_heif
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent
LATIN = "/System/Library/Fonts/Helvetica.ttc"
# PingFang is not directly loadable on all macOS versions; fall back to other CJK system fonts.
CJK_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
]


def pick_cjk() -> str:
    for p in CJK_CANDIDATES:
        try:
            ImageFont.truetype(p, 12)
            return p
        except OSError:
            continue
    raise SystemExit("no CJK system font found")


def receipt(lines: list[str], font_path: str) -> Image.Image:
    font = ImageFont.truetype(font_path, 36)
    img = Image.new("RGB", (640, 80 + 60 * len(lines)), "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((30, 40 + 60 * i), line, fill="black", font=font)
    return img


MCD = ["McDonald's", "2024-03-15", "Big Mac 8.00", "Fries 4.50", "TOTAL 12.50"]
ZH = ["好邻居超市", "2024-03-16", "苹果 15.00", "牛奶 20.00", "合计 35.00"]
OTHER = ["Corner Cafe", "2024-03-17", "Latte 5.00", "TOTAL 5.00"]

if __name__ == "__main__":
    mcd = receipt(MCD, LATIN)
    mcd.save(OUT / "mcd.png", optimize=True)
    pillow_heif.from_pillow(mcd).save(OUT / "mcd.heic", quality=60)
    receipt(ZH, pick_cjk()).save(OUT / "market_zh.png", optimize=True)
    pages = [mcd, receipt(OTHER, LATIN)]
    pages[0].save(OUT / "two_receipts.pdf", save_all=True, append_images=pages[1:], resolution=100)
