import io
import re
import zipfile
from dataclasses import dataclass

import openpyxl

from .generator import PASS, Result
from .normalizer import file_date
from .validator import Person

FORBIDDEN_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_STEM = 150
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
LEDGER_NAME = "처리결과.xlsx"
LEDGER_HEADERS = [
    "행", "구분", "직종", "성명", "현임교", "발령교", "발령일",
    "학교명 확정", "상태", "조사교정", "파일명", "코드", "비고",
]


@dataclass
class Packed:
    row_no: int
    folder: str
    filename: str


def safe_part(text: str) -> str:
    return FORBIDDEN_RE.sub("_", text).strip(" .") or "_"


def build_filename(person: Person, taken: set[str], force_suffix: bool = False) -> str:
    d = file_date(person.order_date) if person.order_date else "날짜없음"
    stem = "_".join(safe_part(x) for x in (d, person.kind, person.job, person.name, person.new_school))
    suffix = f"_{person.row_no:03d}"
    stem = stem[:MAX_STEM]
    candidate = stem + (suffix if force_suffix else "")
    n = 0
    while f"{candidate}.hwpx".casefold() in taken:
        n += 1
        candidate = f"{stem}{suffix}" + ("" if n == 1 else f"_{n}")
    return f"{candidate}.hwpx"


def assign_filenames(people: list[Person]) -> dict[int, str]:
    taken: set[str] = set()
    names: dict[int, str] = {}
    for p in people:
        name = build_filename(p, taken, force_suffix="V10" in p.codes())
        taken.add(name.casefold())
        names[p.row_no] = name
    return names


def excel_safe(value):
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def ledger_bytes(people: list[Person], results: list[Result], names: dict[int, str]) -> bytes:
    by_row = {r.row_no: r for r in results}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "처리결과"
    ws.append(LEDGER_HEADERS)
    for p in people:
        r = by_row.get(p.row_no)
        status = r.status if r else "미처리"
        notes = "; ".join(r.failures) if r and r.failures else ""
        matches = ",".join(m.status for m in (p.cur_match, p.new_match) if m is not None)
        ws.append([excel_safe(v) for v in (
            p.row_no, p.kind, p.job, p.name, p.cur_school, p.new_school,
            p.order_date.isoformat() if p.order_date else "", matches, status,
            "로→으로" if r and r.josa_fixed else "", names.get(p.row_no, "") if status == PASS else "",
            ",".join(p.codes()), notes,
        )])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def errors_bytes(people: list[Person], results: list[Result]) -> bytes:
    by_row = {r.row_no: r for r in results}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "오류목록"
    ws.append(["행", "구분", "성명", "코드", "내용"])
    for p in people:
        r = by_row.get(p.row_no)
        issues = [i for i in p.issues if i.level == "오류"]
        if (r and r.status != PASS) or issues:
            msgs = "; ".join(i.message for i in issues) or "; ".join(r.failures if r else [])
            ws.append([excel_safe(v) for v in (p.row_no, p.kind, p.name, ",".join(i.code for i in issues), msgs)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_zip(
    people: list[Person], results: list[Result], only_rows: set[int] | None = None
) -> tuple[bytes, list[Packed]]:
    names = assign_filenames(people)
    by_row = {r.row_no: r for r in results}
    packed: list[Packed] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in people:
            r = by_row.get(p.row_no)
            if r and r.status == PASS and (only_rows is None or p.row_no in only_rows):
                zf.writestr(f"{p.kind}/{names[p.row_no]}", r.data)
                packed.append(Packed(p.row_no, p.kind, names[p.row_no]))
        zf.writestr(LEDGER_NAME, ledger_bytes(people, results, names))
        zf.writestr("오류목록.xlsx", errors_bytes(people, results))
    return buf.getvalue(), packed
