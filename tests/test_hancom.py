import time
from pathlib import Path

import pytest

from insa_tongji.core import hwp_com, hwpx_engine
from insa_tongji.core.template_registry import register

ROOT = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.hancom, pytest.mark.skipif(not hwp_com.available(), reason="한컴오피스 없음")]

CASES = [
    ("신규", {"직종": "조리원", "성명": "홍길동", "발령교": "전주하가초등학교", "발령일": "2026년 11월 1일"}),
    ("신규", {"직종": "특수교육지도사", "성명": "남궁가나다라마", "발령교": "한국전통문화고등학교",
            "발령일": "2026년 11월 1일"}),
    ("전보", {"직종": "조리실무사", "성명": "성춘향", "현임교": "전주문정초등학교", "발령교": "전라중학교",
            "발령일": "2026년 11월 1일"}),
]


@pytest.mark.parametrize("kind,values", CASES)
def test_generated_file_opens_in_hancom_on_one_page(tmp_path, kind, values):
    template = register(kind, (ROOT / "templates" / f"{kind}.hwpx").read_bytes())
    data, _ = hwpx_engine.build(template.data, values)
    path = tmp_path / "out.hwpx"
    path.write_bytes(data)
    result = hwp_com.check_file(path)
    assert result.opened and result.pages == 1, result


def test_t28_hwp_to_hwpx_conversion_and_pdf(tmp_path):
    originals = [p for p in ROOT.glob("*.hwp") if "일반전보" in p.name or "임용통지서" in p.name]
    assert originals
    start = time.perf_counter()
    converted = hwp_com.convert_hwp_to_hwpx(originals[0].read_bytes())
    assert time.perf_counter() - start < 120
    template = register("신규" if "임용" in originals[0].name else "전보", converted)
    assert template.fields


def test_real_pdf_rendering_is_one_page_and_reuses_the_instance():
    template = register("신규", (ROOT / "templates" / "신규.hwpx").read_bytes())
    data, _ = hwpx_engine.build(template.data, CASES[0][1])
    start = time.perf_counter()
    first = hwp_com.renderer.render(data)
    first_seconds = time.perf_counter() - start
    start = time.perf_counter()
    second = hwp_com.renderer.render(data)
    second_seconds = time.perf_counter() - start
    print(f"PDF 변환 첫 회 {first_seconds:.1f}초, 재사용 {second_seconds:.1f}초")
    assert first.startswith(b"%PDF") and second.startswith(b"%PDF")
    fitz = pytest.importorskip("fitz")
    assert fitz.open(stream=first, filetype="pdf").page_count == 1
    assert second_seconds < first_seconds
