import hashlib
import io
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import hwp_com
from .hwpx_engine import ALLOWED_FIELDS, JOB_KEY, SECTION_RE, broken_field_marks, plain_text, scan_fields
from .validator import REQUIRED

HWP_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
ZIP_MAGIC = b"PK\x03\x04"
MAX_TEMPLATE_BYTES = 50 * 1024 * 1024
MAX_PART_BYTES = 100 * 1024 * 1024
MAX_RATIO = 200
REQUIRED_PARTS = ("mimetype", "Contents/header.xml")
HWPX_MIMETYPE = b"application/hwp+zip"


class TemplateError(Exception):
    pass


@dataclass
class Template:
    kind: str
    data: bytes
    sha256: str
    fields: Counter = field(default_factory=Counter)
    unknown: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def required(self) -> tuple[str, ...]:
        return tuple(f for f in ALLOWED_FIELDS if self.fields.get(f))


def sniff(data: bytes) -> str:
    if data[:8] == HWP_MAGIC:
        return "hwp"
    if data[:4] == ZIP_MAGIC:
        return "hwpx"
    return "unknown"


def check_zip_safety(data: bytes) -> None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise TemplateError("HWPX(ZIP) 파일이 손상되었습니다") from exc
    total = 0
    for info in zf.infolist():
        name = info.filename
        if name.startswith(("/", "\\")) or ".." in Path(name).parts or ":" in name:
            raise TemplateError("허용되지 않는 경로가 포함되어 있습니다")
        if info.file_size > MAX_PART_BYTES:
            raise TemplateError("압축 파트가 너무 큽니다")
        if info.compress_size and info.file_size / info.compress_size > MAX_RATIO and info.file_size > 1024 * 1024:
            raise TemplateError("비정상적인 압축비의 파트가 있습니다")
        total += info.file_size
    if total > MAX_PART_BYTES:
        raise TemplateError("압축 해제 크기가 너무 큽니다")
    names = zf.namelist()
    if len(names) != len(set(names)):
        raise TemplateError("HWPX에 중복된 파트가 있습니다")
    for part in REQUIRED_PARTS:
        if part not in names:
            raise TemplateError(f"HWPX 필수 파트가 없습니다: {part}")
    if zf.read("mimetype").strip() != HWPX_MIMETYPE:
        raise TemplateError("HWPX mimetype이 올바르지 않습니다")
    if not any(SECTION_RE.match(n) for n in names):
        raise TemplateError("본문 섹션이 없습니다")


def scan_template(data: bytes) -> tuple[Counter, list[str], list[str]]:
    counts: Counter = Counter()
    warnings: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if not SECTION_RE.match(name):
                continue
            xml = zf.read(name).decode("utf-8")
            counts.update(scan_fields(xml))
            if broken_field_marks(xml):
                raise TemplateError("{{ }} 짝이 맞지 않거나 줄바꿈·표로 끊긴 필드가 있습니다")
            if "{{" + JOB_KEY + "}}으로" in plain_text(xml):
                warnings.append("양식에 '{{직종}}으로'가 고정되어 있어 받침 없는 직종은 조사가 어색할 수 있습니다")
    unknown = sorted(k for k in counts if k not in ALLOWED_FIELDS)
    return counts, unknown, warnings


def register(kind: str, data: bytes) -> Template:
    if len(data) > MAX_TEMPLATE_BYTES:
        raise TemplateError("양식 파일이 너무 큽니다")
    fmt = sniff(data)
    if fmt == "unknown":
        raise TemplateError("HWP 또는 HWPX 양식 파일이 아닙니다")
    if fmt == "hwp":
        if not hwp_com.available():
            raise TemplateError("HWP 양식은 한컴오피스가 있어야 변환할 수 있습니다. HWPX로 저장해 등록하세요")
        try:
            data = hwp_com.convert_hwp_to_hwpx(data)
        except Exception as exc:
            raise TemplateError(f"HWP를 HWPX로 변환하지 못했습니다({type(exc).__name__})") from exc
    check_zip_safety(data)
    counts, unknown, warnings = scan_template(data)
    if unknown:
        raise TemplateError("허용되지 않는 필드가 있습니다: " + ", ".join("{{" + u + "}}" for u in unknown))
    if not counts:
        raise TemplateError("양식에서 {{필드}}를 찾지 못했습니다")
    missing = [f for f in REQUIRED.get(kind, ()) if not counts.get(f)]
    if missing:
        raise TemplateError(f"{kind} 양식에 필요한 필드가 없습니다: " + ", ".join("{{" + m + "}}" for m in missing)
                            + " (신규·전보 양식을 바꿔 등록했는지 확인하세요)")
    return Template(kind, data, hashlib.sha256(data).hexdigest(), counts, unknown, warnings)
