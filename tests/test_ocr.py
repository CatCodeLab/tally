import sys
from pathlib import Path

import pytest

from tally.ocr import load_pages, ocr_image

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Vision OCR needs macOS")


@pytest.fixture
def fixtures():
    return Path(__file__).parent / "fixtures"


def test_ocr_reads_total(fixtures):
    assert "12.50" in ocr_image(load_pages(fixtures / "mcd.png")[0])


def test_ocr_reads_chinese(fixtures):
    assert "合计" in ocr_image(load_pages(fixtures / "market_zh.png")[0])


def test_pdf_pages_split(fixtures):
    pages = load_pages(fixtures / "two_receipts.pdf")
    assert len(pages) == 2
    assert "Corner Cafe" in ocr_image(pages[1])
    assert "McDonald" in ocr_image(pages[0])


def test_heic_loads(fixtures):
    pages = load_pages(fixtures / "mcd.heic")
    assert pages[0].size[0] > 0
    assert "12.50" in ocr_image(pages[0])


def test_exif_rotated_jpeg_is_upright(fixtures):
    page = load_pages(fixtures / "mcd_rotated.jpg")[0]
    assert page.size[0] > page.size[1]  # landscape-ish receipt, not sideways
    assert "12.50" in ocr_image(page)


def test_row_grouping_and_order(monkeypatch):
    from ocrmac import ocrmac
    from PIL import Image

    canned = [
        ("19.00", 1.0, (0.7, 0.502, 0.2, 0.05)),   # same row as "Latte", to its right
        ("Bottom", 1.0, (0.1, 0.1, 0.2, 0.05)),
        ("Top", 1.0, (0.1, 0.9, 0.2, 0.05)),
        ("Latte", 1.0, (0.1, 0.5, 0.2, 0.05)),
    ]

    class FakeOCR:
        def __init__(self, *a, **k):
            pass

        def recognize(self):
            return canned

    monkeypatch.setattr(ocrmac, "OCR", FakeOCR)
    assert ocr_image(Image.new("RGB", (10, 10))) == "Top\nLatte 19.00\nBottom"


def test_unsupported_type_raises(tmp_path):
    with pytest.raises(ValueError):
        load_pages(tmp_path / "x.txt")
