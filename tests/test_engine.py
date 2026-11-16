import io
import zipfile
from datetime import date
from pathlib import Path

import pytest
from lxml import etree

from insa_tongji.core import hwp_com, hwpx_engine, packager, template_registry, verifier
from insa_tongji.core.generator import FAIL, PASS, SKIP, generate_all, generate_one
from insa_tongji.core.template_registry import TemplateError, register
from insa_tongji.core.validator import Issue, Person

ROOT = Path(__file__).resolve().parents[1]
NEW_BYTES = (ROOT / "templates" / "신규.hwpx").read_bytes()
TRANSFER_BYTES = (ROOT / "templates" / "전보.hwpx").read_bytes()
SECTION = "Contents/section0.xml"


@pytest.fixture(scope="module")
def templates():
    return {"신규": register("신규", NEW_BYTES), "전보": register("전보", TRANSFER_BYTES)}


def person(row=2, kind="신규", job="조리원", name="홍길동", cur="", new="전주하가초등학교"):
    return Person(row_no=row, kind=kind, job=job, name=name, cur_school=cur, new_school=new,
                  order_date=date(2026, 11, 1))


def rewrite(data: bytes, part: str, fn) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            content = src.read(info)
            if info.filename == part:
                content = fn(content)
            clone = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            clone.compress_type = info.compress_type
            dst.writestr(clone, content)
    return out.getvalue()


def test_t17_field_scan(templates):
    assert dict(templates["신규"].fields) == {"직종": 2, "성명": 1, "발령교": 1, "발령일": 1}
    assert dict(templates["전보"].fields) == {"현임교": 1, "직종": 1, "성명": 1, "발령교": 1, "발령일": 1}
    assert "현임교" not in templates["신규"].required and "현임교" in templates["전보"].required


def test_t18_unknown_field_rejected():
    broken = rewrite(NEW_BYTES, SECTION, lambda b: b.replace("{{성명}}".encode(), "{{성 명}}".encode()))
    with pytest.raises(TemplateError, match="허용되지 않는 필드"):
        register("신규", broken)


def test_t19_split_field_is_merged():
    xml = '<hp:p id="1"><hp:run><hp:t>이름 {{성</hp:t></hp:run><hp:run><hp:t>명}} 님</hp:t></hp:run></hp:p>'
    report = hwpx_engine.BuildReport()
    out = hwpx_engine.replace_in_xml(xml, {"성명": "홍길동"}, True, report)
    assert hwpx_engine.plain_text(out) == "이름 홍길동 님"
    assert report.merged_splits == 1 and "{{" not in out


def test_field_in_nested_table_paragraph():
    xml = ('<hp:p id="1"><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p id="2"><hp:run><hp:t>{{성명}}</hp:t></hp:run>'
           "</hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>")
    out = hwpx_engine.replace_in_xml(xml, {"성명": "가나다"}, True, hwpx_engine.BuildReport())
    assert "가나다" in out and "{{" not in out


@pytest.mark.parametrize("job,josa", [("조리실무사", "로"), ("조리원", "으로"), ("특수교육지도사", "로")])
def test_t20_josa_in_output(templates, job, josa):
    r = generate_one(person(job=job), templates)
    assert r.status == PASS
    text = hwpx_engine.plain_text(zipfile.ZipFile(io.BytesIO(r.data)).read(SECTION).decode())
    assert f"{job}{josa} 임함" in text


def test_t21_xml_escape(templates):
    p = person(name="A&B<C>", new="가&나<다>학교")
    r = generate_one(p, templates)
    assert r.status == PASS
    xml = zipfile.ZipFile(io.BytesIO(r.data)).read(SECTION)
    etree.fromstring(xml)
    assert "A&B<C>" in hwpx_engine.plain_text(xml.decode())


def test_t22_template_injection_blocked(templates):
    r = generate_one(person(name="{{성명}}"), templates)
    assert r.status == FAIL and any(f.startswith("C2") for f in r.failures)


def test_t23_long_values_build(templates):
    r = generate_one(person(name="가" * 12, new="한국전통문화고등학교"), templates)
    assert r.status == PASS


def test_t24_non_text_parts_identical_and_tamper_detected(templates):
    r = generate_one(person(), templates)
    assert verifier.verify(NEW_BYTES, r.data, {"성명": "홍길동"}).ok
    tampered = rewrite(r.data, "BinData/image2.jpg", lambda b: b + b"x")
    result = verifier.verify(NEW_BYTES, tampered, {"성명": "홍길동"})
    assert not result.ok and any(f.startswith("C4") for f in result.failures)


def test_structure_tamper_detected(templates):
    r = generate_one(person(), templates)
    changed = rewrite(r.data, SECTION, lambda b: b.replace(b"<hp:p ", b"<hp:p data-x=\"1\" ", 1))
    assert any(f.startswith("C5") for f in verifier.verify(NEW_BYTES, changed, {}).failures)


def test_t25_failed_files_excluded_from_zip(templates):
    people = [person(row=2), person(row=3, name="김철수")]
    results = generate_all(people, templates)
    results[1].status = FAIL
    results[1].failures = ["C2:본문에 {{ 또는 }} 가 남아 있습니다"]
    data, packed = packager.build_zip(people, results)
    assert [p.row_no for p in packed] == [2]
    assert "오류목록.xlsx" in zipfile.ZipFile(io.BytesIO(data)).namelist()


@pytest.mark.parametrize("payload", [b"hello", b"", b"\xd0\xcf\x11\xe0" + b"\x00" * 4])
def test_t26_bad_template_rejected(payload):
    with pytest.raises(TemplateError):
        register("신규", payload)


def test_t26_zip_slip_and_missing_parts_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("../evil.xml", "x")
    with pytest.raises(TemplateError):
        register("신규", buf.getvalue())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "x")
    with pytest.raises(TemplateError):
        register("신규", buf.getvalue())


def test_t27_no_hancom_hwp_registration_message(monkeypatch):
    monkeypatch.setattr(hwp_com, "available", lambda: False)
    with pytest.raises(TemplateError, match="한컴오피스"):
        register("신규", bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 64)
    assert generate_one(person(), {"신규": register("신규", NEW_BYTES)}).status == PASS


def test_t28_conversion_failure_message(monkeypatch):
    monkeypatch.setattr(hwp_com, "available", lambda: True)

    def boom(_data):
        raise RuntimeError("x")

    monkeypatch.setattr(hwp_com, "convert_hwp_to_hwpx", boom)
    with pytest.raises(TemplateError, match="변환하지 못했습니다"):
        register("신규", bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 64)


def test_skip_and_missing_template(templates):
    bad = person()
    bad.issues.append(Issue("V01", "오류", "x"))
    assert generate_one(bad, templates).status == SKIP
    assert generate_one(person(), {}).status == FAIL


def test_t29_zip_structure_and_korean_names(templates):
    people = [person(row=2), person(row=3, kind="전보", name="성춘향", cur="전주문정초등학교", new="전라중학교")]
    data, packed = packager.build_zip(people, generate_all(people, templates))
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    assert names[0].startswith("신규/") and any(n.startswith("전보/") for n in names)
    assert "처리결과.xlsx" in names and len(packed) == 2
    assert all(i.flag_bits & 0x800 for i in zf.infolist() if not i.filename.isascii())
    assert zf.testzip() is None


def test_t30_filenames_safe_unique_and_short():
    taken: set[str] = set()
    p = person(job='조리:원/?', name='홍*길"동', new="가나다.")
    name = packager.build_filename(p, taken)
    assert not set('\\/:*?"<>|') & set(name)
    taken.add(name.casefold())
    assert packager.build_filename(p, taken) != name
    long_person = person(new="가" * 400)
    assert len(packager.build_filename(long_person, set())) < 200
    assert name.startswith("2026.11.01_신규_")


def test_namesake_files_get_row_suffix():
    a, b = person(row=2), person(row=3, new="전라중학교")
    for p in (a, b):
        p.issues.append(Issue("V10", "정보", "x"))
    names = packager.assign_filenames([a, b])
    assert names[2].endswith("_002.hwpx") and names[3].endswith("_003.hwpx")


def test_t31_partial_failure_keeps_others(templates):
    people = [person(row=2), person(row=3, kind="전보", cur="전주문정초등학교")]
    results = generate_all(people, {"신규": templates["신규"]})
    assert [r.status for r in results] == [PASS, FAIL]
    data, packed = packager.build_zip(people, results)
    assert len(packed) == 1


def test_ledger_formula_injection_and_no_rrn():
    assert packager.excel_safe("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
    assert packager.excel_safe("@SUM(1)") == "'@SUM(1)" and packager.excel_safe("홍길동") == "홍길동"
    assert "주민" not in "".join(packager.LEDGER_HEADERS)


def test_preview_text_replaced(templates):
    r = generate_one(person(), templates)
    raw = zipfile.ZipFile(io.BytesIO(r.data)).read("Preview/PrvText.txt")
    text, _ = hwpx_engine.decode_preview(raw)
    assert "홍길동" in text and "{{" not in text


def test_registry_helpers():
    assert template_registry.sniff(NEW_BYTES) == "hwpx"
    assert template_registry.sniff(b"zzzz") == "unknown"


def nested(text_before, text_after):
    return ('<hp:p id="1"><hp:run><hp:t>' + text_before + '</hp:t><hp:tbl><hp:subList><hp:p id="2"><hp:run>'
            '<hp:t>x</hp:t></hp:run></hp:p></hp:subList></hp:tbl><hp:t>' + text_after + '</hp:t></hp:run></hp:p>')


def test_review_nested_table_is_a_barrier():
    out = hwpx_engine.replace_in_xml(nested("{{직종}}", "로봇"), {"직종": "조리원"}, True, hwpx_engine.BuildReport())
    assert "조리원</hp:t>" in out and "으로봇" not in out and "로봇" in out
    report = hwpx_engine.BuildReport()
    out = hwpx_engine.replace_in_xml(nested("{{성", "명}}"), {"성명": "홍길동"}, True, report)
    assert "홍길동" not in out and report.replaced == {}
    assert hwpx_engine.broken_field_marks(nested("{{성", "명}}")) == 2


def test_review_child_tag_inside_text_is_a_barrier():
    xml = '<hp:p id="1"><hp:run><hp:t>{{성<hp:lineBreak/>명}}</hp:t></hp:run></hp:p>'
    assert hwpx_engine.broken_field_marks(xml) == 2
    broken = rewrite(NEW_BYTES, SECTION, lambda b: b.replace("{{성명}}".encode(), "{{성명".encode()))
    with pytest.raises(TemplateError, match="짝이 맞지 않"):
        register("신규", broken)


@pytest.mark.parametrize("raw,expected", [("&#x80;", "\x80"), ("&#13;", "\r"), ("&lt;&amp;&gt;&quot;&apos;", "<&>\"'"),
                                          ("&unknown;", "&unknown;"), ("&#0;", "&#0;")])
def test_review_xml_entities_follow_xml_rules(raw, expected):
    assert hwpx_engine.xml_unescape(raw) == expected


def test_review_cr_in_value_is_escaped_and_xml_stays_valid():
    xml = '<hp:p id="1"><hp:run><hp:t>{{성명}}</hp:t></hp:run></hp:p>'
    out = hwpx_engine.replace_in_xml(xml, {"성명": "가\r나"}, True, hwpx_engine.BuildReport())
    assert "&#13;" in out and "\r" not in out
    etree.fromstring(out.replace("<hp:p", '<hp:p xmlns:hp="urn:x"', 1).encode())


@pytest.mark.parametrize("encoding", ["utf-16-le-bom", "utf-16-be-bom", "utf-8-sig", "utf-8"])
def test_review_preview_encoding_preserved(encoding):
    raw = hwpx_engine.encode_preview("이름 {{성명}}", encoding)
    text, enc = hwpx_engine.decode_preview(raw)
    assert enc == encoding and text == "이름 {{성명}}"
    assert hwpx_engine.decode_preview(hwpx_engine.encode_preview("홍", enc))[0] == "홍"


BAD_PREVIEW = bytes([0x80, 0x81]) + "{{성명}}".encode() + bytes([0x82])


def test_review_undecodable_preview_left_untouched():
    assert hwpx_engine.decode_preview(BAD_PREVIEW) is None
    broken = rewrite(NEW_BYTES, "Preview/PrvText.txt", lambda b: BAD_PREVIEW)
    data, _ = hwpx_engine.build(broken, {"성명": "홍", "직종": "a", "발령교": "b", "발령일": "c"})
    assert zipfile.ZipFile(io.BytesIO(data)).read("Preview/PrvText.txt") == BAD_PREVIEW


def test_review_mimetype_first_and_stored_even_if_template_is_not():
    reordered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(NEW_BYTES)) as src, zipfile.ZipFile(reordered, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in sorted(src.infolist(), key=lambda i: i.filename == "mimetype"):
            dst.writestr(info.filename, src.read(info), zipfile.ZIP_DEFLATED)
    values = {"직종": "조리원", "성명": "홍", "발령교": "가", "발령일": "나"}
    data, _ = hwpx_engine.build(reordered.getvalue(), values)
    first = zipfile.ZipFile(io.BytesIO(data)).infolist()[0]
    assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    assert verifier.verify(reordered.getvalue(), data, {"성명": "홍"}).ok


def test_review_duplicate_zip_entries_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(NEW_BYTES)) as src, zipfile.ZipFile(buf, "w") as dst:
        for info in src.infolist():
            dst.writestr(info.filename, src.read(info))
        dst.writestr(SECTION, src.read(SECTION))
    with pytest.raises(TemplateError, match="중복"):
        register("신규", buf.getvalue())


def test_review_fixed_euro_template_warns():
    patched = rewrite(NEW_BYTES, SECTION, lambda b: b.replace("로 임함".encode(), "으로 임함".encode()))
    assert any("으로" in w for w in register("신규", patched).warnings)
    assert register("신규", NEW_BYTES).warnings == []


def test_review_masterpage_fields_are_scanned_and_replaced():
    masterpage = '<hp:p id="9"><hp:run><hp:t>{{성명}} 귀하</hp:t></hp:run></hp:p>'
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(NEW_BYTES)) as src, zipfile.ZipFile(buf, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info))
        dst.writestr("Contents/masterpage0.xml", masterpage)
    template = register("신규", buf.getvalue())
    assert template.fields["성명"] == 2
    data, _ = hwpx_engine.build(template.data, {"직종": "a", "성명": "홍", "발령교": "b", "발령일": "c"})
    assert "홍 귀하" in zipfile.ZipFile(io.BytesIO(data)).read("Contents/masterpage0.xml").decode()
