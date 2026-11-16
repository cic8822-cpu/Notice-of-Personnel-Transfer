import io
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from .normalizer import clean, compact

ORDER_SHEET = "인사발령"
SCHOOL_SHEET = "학교명"
SCHOOL_COL = "학교명"
HEADERS = {
    "직종": "job",
    "성명": "name",
    "임용일": "appt",
    "현임교": "cur_school",
    "발령교": "new_school",
    "발령일": "order",
    "구분": "kind",
}


class ExcelFormatError(Exception):
    pass


@dataclass
class RawRow:
    row_no: int
    job: object = None
    name: object = None
    appt: object = None
    cur_school: object = None
    new_school: object = None
    order: object = None
    kind: object = None

    def is_blank(self) -> bool:
        return all(clean(getattr(self, f)) == "" for f in HEADERS.values())


def _open(source) -> openpyxl.Workbook:
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    elif isinstance(source, Path):
        source = str(source)
    try:
        return openpyxl.load_workbook(source, data_only=True)
    except Exception as exc:
        raise ExcelFormatError(f"엑셀 파일을 열 수 없습니다({type(exc).__name__})") from exc


def _header_map(ws) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ()), start=0):
        name = compact(cell)
        if name in HEADERS and name not in mapping:
            mapping[name] = idx
    missing = [h for h in HEADERS if h not in mapping]
    if missing:
        raise ExcelFormatError("인사발령 시트 1행에서 열 제목을 찾을 수 없습니다: " + ", ".join(missing))
    return mapping


def read_orders(source) -> list[RawRow]:
    wb = _open(source)
    if ORDER_SHEET not in wb.sheetnames:
        raise ExcelFormatError(f"'{ORDER_SHEET}' 시트가 없습니다")
    ws = wb[ORDER_SHEET]
    cols = _header_map(ws)
    rows = []
    for row_no, values in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        raw = RawRow(row_no=row_no)
        for header, attr in HEADERS.items():
            idx = cols[header]
            setattr(raw, attr, values[idx] if idx < len(values) else None)
        if not raw.is_blank():
            rows.append(raw)
    return rows


def read_schools(source) -> list[str]:
    wb = _open(source)
    if SCHOOL_SHEET not in wb.sheetnames:
        raise ExcelFormatError(f"'{SCHOOL_SHEET}' 시트가 없습니다")
    ws = wb[SCHOOL_SHEET]
    header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
    col = next((i for i, h in enumerate(header) if compact(h) == SCHOOL_COL), None)
    if col is None:
        raise ExcelFormatError("학교명 시트에서 '학교명' 열을 찾을 수 없습니다")
    names = []
    for values in ws.iter_rows(min_row=2, values_only=True):
        if col < len(values) and compact(values[col]):
            names.append(compact(values[col]))
    return names
