import io
import random
from datetime import datetime
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "fixtures" / "sample.xlsx"
HEADERS = ["순", "직종", "성명", "주민등록번호", "임용일", "현임교", "발령교", "발령일", "구분"]
JOBS = ["조리실무사", "조리원", "특수교육지도사", "늘봄실무사", "돌봄전담사"]
SURNAMES = "김이박최정강조윤장임한오서신권황안송류홍"
GIVEN = "가나다라마바사아자차카타파하서연민준지우현"


def school_names() -> list[str]:
    ws = openpyxl.load_workbook(SAMPLE, data_only=True)["학교명"]
    return [r[2] for r in ws.iter_rows(min_row=3, values_only=True) if r[2]]


def make_workbook(rows: list[list], schools: list[str] | None = None, headers: list[str] | None = None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "인사발령"
    ws.append(headers or HEADERS)
    for idx, row in enumerate(rows, start=1):
        ws.append([idx, *row])
    sc = wb.create_sheet("학교명")
    sc.append(["순", "급별", "학교명"])
    sc.append([None, None, None])
    for i, name in enumerate(schools if schools is not None else school_names(), start=1):
        sc.append([i, "", name])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def order_row(job, name, appt, cur, new, order, kind, rrn=None) -> list:
    return [job, name, rrn, appt, cur, new, order, kind]


def synth_rows(count: int, seed: int = 7) -> list[list]:
    rng = random.Random(seed)
    schools = school_names()
    rows = []
    for i in range(count):
        name = rng.choice(SURNAMES) + rng.choice(GIVEN) + rng.choice(GIVEN) + str(i)[:0]
        kind = "신규" if i % 2 == 0 else "전보"
        cur = None if kind == "신규" else rng.choice(schools)
        new = rng.choice(schools)
        rows.append(order_row(rng.choice(JOBS), name, datetime(2026, 11, 1), cur, new, None, kind))
    return rows
