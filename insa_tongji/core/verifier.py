import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field

from .hwpx_engine import PREVIEW_TEXT, SECTION_RE, decode_preview, plain_text, strip_text

MIMETYPE = "mimetype"


@dataclass
class VerifyResult:
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(template: bytes, output: bytes, expected: dict[str, str]) -> VerifyResult:
    result = VerifyResult()
    try:
        out = zipfile.ZipFile(io.BytesIO(output))
        tpl = zipfile.ZipFile(io.BytesIO(template))
    except zipfile.BadZipFile:
        result.failures.append("C1:ZIP 손상")
        return result
    if out.testzip() is not None:
        result.failures.append("C1:ZIP 무결성 오류")
    first = out.infolist()[0]
    if first.filename != MIMETYPE or first.compress_type != zipfile.ZIP_STORED:
        result.failures.append("C1:mimetype 위치·무압축 위반")
    if sorted(out.namelist()) != sorted(tpl.namelist()):
        result.failures.append("C4:파트 목록이 양식과 다릅니다")
        return result
    body = ""
    for name in out.namelist():
        data, base = out.read(name), tpl.read(name)
        if SECTION_RE.match(name):
            xml = data.decode("utf-8")
            body += plain_text(xml) + "\n"
            if "{{" in xml or "}}" in xml:
                result.failures.append("C2:본문에 {{ 또는 }} 가 남아 있습니다")
            if strip_text(xml) != strip_text(base.decode("utf-8")):
                result.failures.append("C5:본문 구조가 양식과 다릅니다")
        elif name == PREVIEW_TEXT:
            decoded = decode_preview(data)
            text = decoded[0] if decoded else data.decode("utf-8", errors="ignore")
            if "{{" in text or "}}" in text:
                result.failures.append("C2:미리보기 텍스트에 {{ 가 남아 있습니다")
        elif _digest(data) != _digest(base):
            result.failures.append(f"C4:비텍스트 파트가 변경됨({name})")
    flat = re.sub(r"\s+", "", body)
    for key, value in expected.items():
        if re.sub(r"\s+", "", value) not in flat:
            result.failures.append(f"C3:기대값 없음({key})")
    return result
