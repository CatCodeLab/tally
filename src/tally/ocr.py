"""Page loading (images, HEIC, PDF) and on-device OCR via macOS Vision."""
from pathlib import Path

import pillow_heif
import pypdfium2
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()

SUPPORTED = {".jpg", ".jpeg", ".png", ".heic", ".pdf"}
# Chinese first: with en-US first, Vision misreads Chinese text (verified on this machine).
LANGUAGES = ["zh-Hans", "zh-Hant", "en-US"]
PDF_SCALE = 200 / 72


def load_pages(path: Path) -> list[Image.Image]:
    suffix = Path(path).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"unsupported file type: {suffix or path}")
    if suffix == ".pdf":
        pdf = pypdfium2.PdfDocument(str(path))
        try:
            return [pdf[i].render(scale=PDF_SCALE).to_pil().convert("RGB") for i in range(len(pdf))]
        finally:
            pdf.close()
    with Image.open(path) as img:
        # Apply EXIF orientation (phone JPEGs) so Vision sees the page upright.
        return [ImageOps.exif_transpose(img).convert("RGB")]


def ocr_image(img: Image.Image) -> str:
    from ocrmac import ocrmac

    results = ocrmac.OCR(img, language_preference=LANGUAGES, recognition_level="accurate").recognize()
    # bbox is (x, y, w, h) normalized, origin bottom-left: higher y is higher on the page.
    # Group lines into rows by vertical centre, rows top-to-bottom, then left-to-right.
    items = [(text, x, y + h / 2, h) for text, _conf, (x, y, w, h) in results]
    items.sort(key=lambda t: -t[2])
    rows: list[list[tuple]] = []
    for it in items:
        if rows and abs(rows[-1][0][2] - it[2]) < it[3] / 2:
            rows[-1].append(it)
        else:
            rows.append([it])
    return "\n".join(" ".join(t[0] for t in sorted(r, key=lambda t: t[1])) for r in rows)
