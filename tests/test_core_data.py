from datetime import date, datetime

import pytest

from insa_tongji.core import excel_reader, josa, normalizer
from insa_tongji.core.school_matcher import SchoolMatcher
from insa_tongji.core.validator import Options, prepare

from .synth_gen import make_workbook, order_row, school_names

TODAY = date(2026, 11, 16)
D1 = datetime(2026, 11, 1)


@pytest.fixture(scope="module")
def matcher():
    return SchoolMatcher(school_names())


def run(rows, matcher, **kw):
    raw = excel_reader.read_orders(make_workbook(rows))
    return prepare(raw, matcher, Options(today=TODAY, **kw))


def test_t01_t02_sample_file(matcher):
    path = excel_reader.Path(__file__).resolve().parents[1] / "fixtures" / "sample.xlsx"
    matcher_ = SchoolMatcher(excel_reader.read_schools(path))
    people = prepare(excel_reader.read_orders(path), matcher_, Options(today=TODAY))
    assert [p.kind for p in people] == ["신규", "전보"]
    new, transfer = people
    assert new.ok and new.values() == {
        "직종": "조리실무사", "성명": "홍길동", "발령교": "전주하가초등학교", "발령일": "2026년 11월 1일"
    }
    assert not transfer.ok and "V03" in transfer.codes()


def test_t03_mixed_kinds(matcher):
    rows = [order_row("조리원", f"가{i}", D1, "전주문정초등학교" if i % 2 else None, "전라중학교", None,
                      "전보" if i % 2 else "신규") for i in range(10)]
    people = run(rows, matcher)
    assert sum(p.kind == "신규" for p in people) == 5 and all(p.ok for p in people)


@pytest.mark.parametrize("kind,ok", [("신규 ", True), ("신​규", True), ("전 보", True), ("", False), (None, False)])
def test_t05_kind_normalized(matcher, kind, ok):
    cur = "전라중학교" if kind and "전" in kind else None
    p = run([order_row("조리원", "가나다", D1, cur, "전라중학교", None, kind)], matcher)[0]
    assert p.ok is ok
    if not ok:
        assert "V01" in p.codes()


def test_t06_unknown_kind(matcher):
    p = run([order_row("조리원", "가나다", D1, None, "전라중학교", None, "승진")], matcher)[0]
    assert "V01" in p.codes() and not p.ok


def test_t07_transfer_without_cur_school(matcher):
    p = run([order_row("조리원", "가나다", D1, None, "전라중학교", None, "전보")], matcher)[0]
    assert "V03" in p.codes() and not p.ok


def test_t08_new_with_cur_school_warns_and_ignores(matcher):
    p = run([order_row("조리원", "가나다", D1, "전라중학교", "전라중학교", None, "신규")], matcher)[0]
    assert "V04" in p.codes() and p.ok and "현임교" not in p.values()


def test_t09_order_date_priority(matcher):
    h = datetime(2026, 12, 1)
    p = run([order_row("조리원", "가나다", D1, None, "전라중학교", h, "신규")], matcher)[0]
    assert p.order_date == date(2026, 12, 1) and "V07" in p.codes()
    p = run([order_row("조리원", "가나다", D1, None, "전라중학교", None, "신규")], matcher)[0]
    assert p.order_date == date(2026, 11, 1)
    p = run([order_row("조리원", "가나다", D1, None, "전라중학교", h, "신규")], matcher, date_mode="E_then_H")[0]
    assert p.order_date == date(2026, 11, 1)
    p = run([order_row("조리원", "가나다", D1, None, "전라중학교", h, "신규")], matcher, date_mode="fixed",
            fixed_date=date(2026, 9, 1))[0]
    assert p.order_date == date(2026, 9, 1)


@pytest.mark.parametrize("text,expected", [
    ("2026-11-01", date(2026, 11, 1)), ("2026.11.1", date(2026, 11, 1)), ("2026. 11. 1.", date(2026, 11, 1)),
    ("20261101", date(2026, 11, 1)), ("2026년 11월 1일", date(2026, 11, 1)), ("2026/11/01", date(2026, 11, 1)),
    (46327, date(2026, 11, 1)), (datetime(2026, 11, 1), date(2026, 11, 1)),
    ("26.11.1", None), ("11월 1일", None), ("내일", None), ("2026-13-45", None), (True, None),
])
def test_t10_date_parsing(text, expected):
    assert normalizer.parse_date(text) == expected


def test_t10_unparsable_order_date_falls_back_with_warning(matcher):
    p = run([order_row("조리원", "가나다", D1, None, "전라중학교", "내일", "신규")], matcher)[0]
    assert p.ok and p.order_date == date(2026, 11, 1) and "V07" in p.codes()
    assert "2026-11-01" in next(i.message for i in p.issues if i.code == "V07")


def test_t10_both_dates_missing(matcher):
    p = run([order_row("조리원", "가나다", None, None, "전라중학교", None, "신규")], matcher)[0]
    assert "V06" in p.codes()


def test_t11_namesakes_and_t12_duplicates(matcher):
    rows = [order_row("조리원", "홍길동", D1, None, "전라중학교", None, "신규"),
            order_row("조리원", "홍길동", D1, None, "전주하가초등학교", None, "신규"),
            order_row("조리원", "김철수", D1, None, "전라중학교", None, "신규"),
            order_row("조리원", "김철수", D1, None, "전라중학교", None, "신규")]
    people = run(rows, matcher)
    assert "V10" in people[0].codes() and "V10" in people[1].codes()
    assert "V09" in people[2].codes() and "V09" in people[3].codes()


@pytest.mark.parametrize("text,expected,status", [
    ("전주하가초", "전주하가초등학교", "auto"), ("하가초", "전주하가초등학교", "auto"),
    ("전라중", "전라중학교", "auto"), ("전라중학교", "전라중학교", "exact"),
    ("전주 하가 초등학교", "전주하가초등학교", "exact"),
])
def test_t13_abbreviations(matcher, text, expected, status):
    r = matcher.match(text)
    assert (r.value, r.status) == (expected, status) and r.confirmed


def test_t14_level_less_is_ambiguous(matcher):
    r = matcher.match("문정")
    assert r.status == "ambiguous" and not r.confirmed
    assert "전주문정유치원" in r.candidates and "전주문정초등학교" in r.candidates


def test_t15_no_auto_confirm_for_fuzzy(matcher):
    r = matcher.match("전주전라중")
    assert r.status == "suggest" and not r.confirmed and "전라중학교" in r.candidates
    r = matcher.match("전주하가초등하교")
    assert r.status == "suggest" and "전주하가초등학교" in r.candidates


def test_t16_unregistered_and_manual_choice(matcher):
    p = run([order_row("조리원", "가나다", D1, None, "서울강남초등학교", None, "신규")], matcher)[0]
    assert "V11" in p.codes() and not p.ok
    p = run([order_row("조리원", "가나다", D1, None, "서울강남초등학교", None, "신규")], matcher,
            overrides={(2, "발령교"): "서울강남초등학교"})[0]
    assert p.ok and p.new_match.status == "manual" and p.new_school == "서울강남초등학교"
    p = run([order_row("조리원", "가나다", D1, None, "문정", None, "신규")], matcher,
            overrides={(2, "발령교"): "전주문정초등학교"})[0]
    assert p.ok and p.new_match.status == "selected"


def test_school_collisions_none_in_real_roster(matcher):
    assert matcher.collisions == {}


def test_aliases_only_to_known_schools():
    m = SchoolMatcher(["전주하가초등학교"], {"하가": "전주하가초등학교", "엉터리": "없는학교"})
    assert m.match("하가").status == "alias" and m.match("엉터리").status != "alias"


@pytest.mark.parametrize("job,expected", [("조리실무사", "로"), ("조리원", "으로"), ("특수교육지도사", "로"),
                                          ("돌봄전담사", "로"), ("행정실무원", "으로"), ("조리사A", None)])
def test_josa(job, expected):
    assert (josa.ro_euro(job) if expected else josa.needs_euro(job)) == (expected if expected else None)


def test_v12_v13_v14_v05(matcher):
    long_name = "가" * 11
    p = run([order_row("조리사A", long_name, D1, "전라중학교", "전라중학교", None, "전보")], matcher)[0]
    assert {"V12", "V13", "V05"} <= set(p.codes()) and p.ok
    p = run([order_row("조리원", "{{성명}}", D1, None, "전라중학교", None, "신규")], matcher)[0]
    assert "V14" in p.codes() and not p.ok


def test_v08_date_far_from_today(matcher):
    p = run([order_row("조리원", "가나다", datetime(2030, 1, 1), None, "전라중학교", None, "신규")], matcher)[0]
    assert "V08" in p.codes() and p.ok


def test_v02_missing_fields(matcher):
    p = run([order_row("", "가나다", D1, None, "전라중학교", None, "신규")], matcher)[0]
    assert "V02" in p.codes() and not p.ok


def test_reader_header_error_and_blank_rows():
    headers = ["순", "직종", "이름", "주민등록번호", "임용일", "현임교", "발령교", "발령일", "구분"]
    bad = make_workbook([], headers=headers)
    with pytest.raises(excel_reader.ExcelFormatError):
        excel_reader.read_orders(bad)
    rows = excel_reader.read_orders(make_workbook([order_row("조리원", "가나다", D1, None, "전라중학교", None, "신규"),
                                                  [None] * 8]))
    assert len(rows) == 1


def test_reader_does_not_expose_rrn():
    raw = excel_reader.read_orders(make_workbook([order_row("조리원", "가나다", D1, None, "전라중학교", None, "신규",
                                                           rrn="900101-1234567")]))
    assert "900101" not in repr(raw)


def test_reader_rejects_non_excel():
    with pytest.raises(excel_reader.ExcelFormatError):
        excel_reader.read_orders(b"not an excel file")


def test_region_prefix_auto_detected_and_configurable(matcher):
    assert matcher.region_prefix == "전주"
    other = SchoolMatcher(["군산가람초등학교", "군산나래초등학교", "군산한빛중학교", "익산중앙초등학교"])
    assert other.region_prefix == "군산"
    assert other.match("가람초").value == "군산가람초등학교"
    assert other.match("한빛중").status == "auto"
    none = SchoolMatcher(["가람초등학교", "나래초등학교"], region_prefix="")
    assert none.region_prefix == "" and none.match("가람초").status == "auto"


@pytest.mark.parametrize("text", ["중", "고", "유", "초", "유치원", "초등학교", "중학교", "고등학교"])
def test_review_generic_level_words_never_auto_confirm(matcher, text):
    r = matcher.match(text)
    assert not r.confirmed, (text, r)


def test_review_parenthesis_never_auto_confirms(matcher):
    for text in ("하가초(병설유치원)", "전주하가초등학교(병설유치원)", "전주하가초등학교(병설)"):
        r = matcher.match(text)
        assert r.status == "suggest" and r.candidates == ("전주하가초등학교",) and not r.confirmed, text
    exact_paren = SchoolMatcher(["전주하가초등학교(병설)"]).match("전주하가초등학교(병설)")
    assert exact_paren.status == "exact"


def test_review_special_schools_keep_level_marker_rule():
    m = SchoolMatcher(["전주선화학교", "전주하가초등학교", "전주문정초등학교"])
    assert m.match("선화학교").confirmed is False
    assert m.match("전주선화학교").status == "exact"


@pytest.mark.parametrize("value,expected", [
    (20261101, date(2026, 11, 1)), (20261101.0, date(2026, 11, 1)), (2026, None), (1, None), (46327.5, None),
    (99999999, None), (36525, None), (36526, date(2000, 1, 1)),
])
def test_review_numeric_date_cells(value, expected):
    assert normalizer.parse_date(value) == expected


def test_review_bidi_and_soft_hyphen_removed():
    assert normalizer.clean("홍\u202e길\u00ad동\u200f") == "홍길동"


def test_review_date_modes_follow_plan(matcher):
    bad_order, good_appt = "엉터리", D1
    p = run([order_row("조리원", "가나다", good_appt, None, "전라중학교", bad_order, "신규")], matcher,
            date_mode="E_then_H")[0]
    assert p.ok and p.order_date == date(2026, 11, 1)
    p = run([order_row("조리원", "가나다", good_appt, None, "전라중학교", bad_order, "신규")], matcher,
            date_mode="fixed", fixed_date=date(2026, 9, 1))[0]
    assert p.ok and p.order_date == date(2026, 9, 1) and "V07" not in p.codes()
    p = run([order_row("조리원", "가나다", None, None, "전라중학교", datetime(2026, 12, 1), "신규")], matcher,
            date_mode="E_then_H")[0]
    assert p.ok and p.order_date == date(2026, 12, 1)
    p = run([order_row("조리원", "가나다", "엉터리", None, "전라중학교", datetime(2026, 12, 1), "신규")], matcher)[0]
    assert p.ok and "V07" in p.codes()
    p = run([order_row("조리원", "가나다", good_appt, None, "전라중학교", None, "신규")], matcher,
            date_mode="fixed", fixed_date=None)[0]
    assert p.order_date == date(2026, 11, 1)


def test_review_v14_applies_to_user_overrides(matcher):
    p = run([order_row("조리원", "가나다", D1, None, "문정", None, "신규")], matcher,
            overrides={(2, "발령교"): "{{성명}}학교"})[0]
    assert "V14" in p.codes() and not p.ok
