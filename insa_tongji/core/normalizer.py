import re
import unicodedata
from datetime import date, datetime, timedelta

ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff\u00ad]")
CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SPACE_RE = re.compile(r"\s+")

EXCEL_EPOCH = date(1899, 12, 30)
EXCEL_SERIAL_MIN, EXCEL_SERIAL_MAX = 36526, 73415
YMD_MIN, YMD_MAX = 19000101, 21001231

DATE_PATTERNS = [
    re.compile(r"^(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})\s*\.?$"),
    re.compile(r"^(\d{4})(\d{2})(\d{2})$"),
    re.compile(r"^(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일$"),
    re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T]\d{2}:\d{2}(:\d{2})?$"),
]

DATE_STYLES = {"kor", "dot"}


def clean(value) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = ZERO_WIDTH_RE.sub("", text)
    text = CONTROL_RE.sub("", text)
    return SPACE_RE.sub(" ", text).strip()


def compact(value) -> str:
    return SPACE_RE.sub("", clean(value))


def parse_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value != int(value):
            return None
        if YMD_MIN <= value <= YMD_MAX:
            return parse_date(str(int(value)))
        if EXCEL_SERIAL_MIN <= value <= EXCEL_SERIAL_MAX:
            return EXCEL_EPOCH + timedelta(days=int(value))
        return None
    text = clean(value)
    for pattern in DATE_PATTERNS:
        m = pattern.match(text)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def format_date(d: date, style: str = "kor") -> str:
    if style == "dot":
        return f"{d.year}. {d.month}. {d.day}."
    return f"{d.year}년 {d.month}월 {d.day}일"


def file_date(d: date) -> str:
    return d.strftime("%Y.%m.%d")
