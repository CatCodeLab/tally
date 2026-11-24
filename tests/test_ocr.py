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
    assert len(load_pages(fixtures / "two_receipts.pdf")) == 2


def test_heic_loads(fixtures):
    assert load_pages(fixtures / "mcd.heic")[0].size[0] > 0


def test_unsupported_type_raises(tmp_path):
    with pytest.raises(ValueError):
        load_pages(tmp_path / "x.txt")
