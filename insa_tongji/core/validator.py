from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from .excel_reader import RawRow
from .josa import needs_euro
from .normalizer import clean, format_date, parse_date
from .school_matcher import MatchResult, SchoolMatcher

ERROR, WARN, INFO = "오류", "경고", "정보"
KIND_NEW, KIND_TRANSFER = "신규", "전보"
KINDS = (KIND_NEW, KIND_TRANSFER)
REQUIRED = {
    KIND_NEW: ("직종", "성명", "발령교", "발령일"),
    KIND_TRANSFER: ("직종", "성명", "현임교", "발령교", "발령일"),
}
DATE_MODES = ("H_then_E", "E_then_H", "fixed")
DATE_WINDOW_DAYS = 366
MAX_NAME_LEN = 10
MAX_SCHOOL_LEN = 30
RAW_FIELDS = ("job", "name", "cur_school", "new_school", "kind")


@dataclass
class Issue:
    code: str
    level: str
    message: str


@dataclass
class Person:
    row_no: int
    kind: str = ""
    job: str = ""
    name: str = ""
    cur_school: str = ""
    new_school: str = ""
    order_date: date | None = None
    cur_match: MatchResult | None = None
    new_match: MatchResult | None = None
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == ERROR for i in self.issues)

    def codes(self) -> list[str]:
        return [i.code for i in self.issues]

    def values(self, date_style: str = "kor") -> dict[str, str]:
        out = {"직종": self.job, "성명": self.name, "발령교": self.new_school}
        if self.order_date:
            out["발령일"] = format_date(self.order_date, date_style)
        if self.kind == KIND_TRANSFER:
            out["현임교"] = self.cur_school
        return out


@dataclass
class Options:
    date_mode: str = "H_then_E"
    fixed_date: date | None = None
    today: date | None = None
    overrides: dict[tuple[int, str], str] = field(default_factory=dict)


def _add(person: Person, code: str, level: str, message: str) -> None:
    person.issues.append(Issue(code, level, message))


def _resolve_school(
    row_no: int, matcher: SchoolMatcher, raw: str, col: str, overrides: dict[tuple[int, str], str]
) -> tuple[str, MatchResult | None]:
    if raw == "":
        return "", None
    result = matcher.match(raw)
    if not result.confirmed and (row_no, col) in overrides:
        result = matcher.choose(overrides[(row_no, col)])
    return (result.value if result.confirmed else raw), result


def _pick_date(raw: RawRow, opts: Options, person: Person) -> date | None:
    order_text, appt_text = clean(raw.order), clean(raw.appt)
    order_d, appt_d = parse_date(raw.order), parse_date(raw.appt)
    if opts.date_mode == "fixed" and opts.fixed_date:
        return opts.fixed_date
    if order_d and appt_d and order_d != appt_d:
        _add(person, "V07", WARN, f"발령일({order_d})과 임용일({appt_d})이 다릅니다")
    first, second = (appt_d, order_d) if opts.date_mode == "E_then_H" else (order_d, appt_d)
    chosen = first or second
    if chosen is None:
        _add(person, "V06", ERROR, "발령일과 임용일을 모두 날짜로 해석할 수 없습니다")
        return None
    if order_text and order_d is None:
        _add(person, "V07", WARN, f"발령일을 해석할 수 없어 임용일({appt_d})을 사용합니다")
    if appt_text and appt_d is None:
        _add(person, "V07", WARN, f"임용일을 해석할 수 없어 발령일({order_d})을 사용합니다")
    return chosen


def _check_text(person: Person, raw: RawRow, overrides: dict[tuple[int, str], str]) -> None:
    values = [clean(getattr(raw, attr)) for attr in RAW_FIELDS]
    values += [clean(v) for (row, _), v in overrides.items() if row == raw.row_no]
    for value in values:
        if "{{" in value or "}}" in value:
            _add(person, "V14", ERROR, "값에 {{ 또는 }} 가 포함되어 있습니다")
            return


def prepare(rows: list[RawRow], matcher: SchoolMatcher, opts: Options | None = None) -> list[Person]:
    opts = opts or Options()
    today = opts.today or date.today()
    people: list[Person] = []
    for raw in rows:
        p = Person(row_no=raw.row_no)
        p.kind = clean(raw.kind).replace(" ", "")
        p.job, p.name = clean(raw.job), clean(raw.name)
        _check_text(p, raw, opts.overrides)
        if p.kind not in KINDS:
            _add(p, "V01", ERROR, "구분이 신규 또는 전보가 아닙니다")
        if not (p.job and p.name and clean(raw.new_school)):
            _add(p, "V02", ERROR, "직종·성명·발령교 중 빈 값이 있습니다")
        cur_text, new_text = clean(raw.cur_school), clean(raw.new_school)
        if p.kind == KIND_TRANSFER and not cur_text:
            _add(p, "V03", ERROR, "전보인데 현임교가 비어 있습니다")
        if p.kind == KIND_NEW and cur_text:
            _add(p, "V04", WARN, "신규인데 현임교 값이 있어 무시합니다")
            cur_text = ""
        p.new_school, p.new_match = _resolve_school(raw.row_no, matcher, new_text, "발령교", opts.overrides)
        if p.kind == KIND_TRANSFER:
            p.cur_school, p.cur_match = _resolve_school(raw.row_no, matcher, cur_text, "현임교", opts.overrides)
        for label, match in (("발령교", p.new_match), ("현임교", p.cur_match)):
            if match is not None and not match.confirmed:
                _add(p, "V11", ERROR, f"{label} 학교명을 확정할 수 없습니다({match.status})")
        if p.kind == KIND_TRANSFER and p.cur_school and p.cur_school == p.new_school:
            _add(p, "V05", WARN, "현임교와 발령교가 같습니다")
        p.order_date = _pick_date(raw, opts, p)
        if p.order_date and abs((p.order_date - today).days) > DATE_WINDOW_DAYS:
            _add(p, "V08", WARN, "발령일이 오늘 기준 1년 범위 밖입니다")
        if p.job and needs_euro(p.job) is None:
            _add(p, "V12", WARN, "직종 끝글자가 한글이 아니어서 조사를 교정하지 못합니다")
        if len(p.name) > MAX_NAME_LEN or max(len(p.new_school), len(p.cur_school)) > MAX_SCHOOL_LEN:
            _add(p, "V13", WARN, "성명 또는 학교명이 길어 줄바꿈에 영향이 있을 수 있습니다")
        people.append(p)
    _mark_duplicates(people)
    _mark_missing_required(people)
    return people


def _mark_duplicates(people: list[Person]) -> None:
    keys = Counter((p.name, p.job, p.new_school, p.kind) for p in people if p.name)
    names = Counter(p.name for p in people if p.name)
    for p in people:
        if not p.name:
            continue
        if keys[(p.name, p.job, p.new_school, p.kind)] > 1:
            _add(p, "V09", WARN, "같은 내용의 행이 중복되어 있습니다")
        elif names[p.name] > 1:
            _add(p, "V10", INFO, "동명이인이 있어 파일명에 행 번호를 붙입니다")


def _mark_missing_required(people: list[Person]) -> None:
    for p in people:
        if p.kind in REQUIRED and p.ok:
            missing = [f for f in REQUIRED[p.kind] if not p.values().get(f)]
            if missing:
                _add(p, "V15", ERROR, "필수 값이 없습니다: " + ", ".join(missing))
