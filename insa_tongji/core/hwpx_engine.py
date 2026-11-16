import io
import re
import zipfile
from dataclasses import dataclass, field

from .josa import needs_euro

ALLOWED_FIELDS = ("직종", "성명", "발령일", "현임교", "발령교")
BARRIER = "\x00"
FIELD_RE = re.compile(r"\{\{([^{}\x00]*)\}\}")
TOKEN_RE = re.compile(
    r"<hp:p\b[^>]*>|</hp:p>|<hp:t(?:\s[^>]*)?/>|<hp:t(?:\s[^>]*)?>.*?</hp:t>",
    re.S,
)
TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")
T_INNER_RE = re.compile(r"(<hp:t(?:\s[^>]*)?(?<!/)>)(.*?)(</hp:t>)", re.S)
SECTION_RE = re.compile(r"^Contents/(?:section|masterpage)\d+\.xml$")
ENTITY_RE = re.compile(r"&(#x[0-9a-fA-F]+|#\d+|lt|gt|amp|quot|apos);")
NAMED_ENTITIES = {"lt": "<", "gt": ">", "amp": "&", "quot": '"', "apos": "'"}
PREVIEW_TEXT = "Preview/PrvText.txt"
MIMETYPE = "mimetype"
JOB_KEY = "직종"
RO = "로"
EU = "으"


@dataclass
class Piece:
    start: int
    end: int
    text: str


@dataclass
class BuildReport:
    replaced: dict[str, int] = field(default_factory=dict)
    merged_splits: int = 0
    josa_fixed: int = 0
    unknown_fields: list[str] = field(default_factory=list)


def xml_unescape(text: str) -> str:
    def sub(m: re.Match) -> str:
        ref = m.group(1)
        if ref in NAMED_ENTITIES:
            return NAMED_ENTITIES[ref]
        code = int(ref[2:], 16) if ref[1] in "xX" else int(ref[1:])
        return chr(code) if 0 < code <= 0x10FFFF else m.group(0)

    return ENTITY_RE.sub(sub, text)


def escape_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\r", "&#13;")


def paragraph_pieces(xml: str) -> list[list[Piece]]:
    paragraphs: list[list[Piece]] = []
    stack: list[int] = []
    for m in TOKEN_RE.finditer(xml):
        token = m.group(0)
        if token == "</hp:p>":
            if stack:
                stack.pop()
            continue
        if token.startswith("<hp:p"):
            if stack:
                paragraphs[stack[-1]].append(Piece(-1, -1, BARRIER))
            paragraphs.append([])
            stack.append(len(paragraphs) - 1)
            continue
        if not stack or not token.endswith("</hp:t>"):
            continue
        open_len = token.index(">") + 1
        inner = token[open_len : -len("</hp:t>")]
        pos = m.start() + open_len
        for part in TAG_SPLIT_RE.split(inner):
            if part.startswith("<"):
                paragraphs[stack[-1]].append(Piece(-1, -1, BARRIER))
            elif part:
                paragraphs[stack[-1]].append(Piece(pos, pos + len(part), xml_unescape(part)))
            pos += len(part)
    return [p for p in paragraphs if any(piece.text != BARRIER for piece in p)]


def plain_text(xml: str) -> str:
    return "\n".join("".join(p.text for p in para).replace(BARRIER, "") for para in paragraph_pieces(xml))


def scan_fields(xml: str) -> list[str]:
    found: list[str] = []
    for para in paragraph_pieces(xml):
        found.extend(FIELD_RE.findall("".join(p.text for p in para)))
    return found


def broken_field_marks(xml: str) -> int:
    broken = 0
    for para in paragraph_pieces(xml):
        full = "".join(p.text for p in para)
        broken += full.count("{{") + full.count("}}") - 2 * len(FIELD_RE.findall(full))
    return broken


def _ops_for(full: str, values: dict[str, str], josa: bool, report: BuildReport) -> list[tuple[int, int, str]]:
    ops: list[tuple[int, int, str]] = []
    for m in FIELD_RE.finditer(full):
        key = m.group(1)
        if key not in values:
            report.unknown_fields.append(key)
            continue
        value = values[key]
        ops.append((m.start(), m.end(), value))
        report.replaced[key] = report.replaced.get(key, 0) + 1
        if josa and key == JOB_KEY and full.startswith(RO, m.end()) and needs_euro(value):
            ops.append((m.end(), m.end(), EU))
            report.josa_fixed += 1
    return ops


def _rewrite_pieces(
    pieces: list[Piece], ops: list[tuple[int, int, str]], report: BuildReport
) -> list[tuple[Piece, str]]:
    offsets = []
    g = 0
    for p in pieces:
        offsets.append(g)
        g += len(p.text)
    for start, end, _ in ops:
        first = max(i for i, o in enumerate(offsets) if o <= start)
        if end > offsets[first] + len(pieces[first].text):
            report.merged_splits += 1
    changes = []
    for piece, base in zip(pieces, offsets, strict=True):
        if piece.start < 0:
            continue
        out = []
        for i, ch in enumerate(piece.text):
            gi = base + i
            out.extend(rep for s, _, rep in ops if s == gi)
            if not any(s <= gi < e for s, e, _ in ops):
                out.append(ch)
        new = "".join(out)
        if new != piece.text:
            changes.append((piece, new))
    return changes


def replace_in_xml(xml: str, values: dict[str, str], josa: bool, report: BuildReport) -> str:
    edits: list[tuple[int, int, str]] = []
    for pieces in paragraph_pieces(xml):
        full = "".join(p.text for p in pieces)
        if "{{" not in full:
            continue
        ops = _ops_for(full, values, josa, report)
        if ops:
            edits.extend((p.start, p.end, escape_text(new)) for p, new in _rewrite_pieces(pieces, ops, report))
    for start, end, new in sorted(edits, reverse=True):
        xml = xml[:start] + new + xml[end:]
    return xml


def replace_in_preview(text: str, values: dict[str, str], josa: bool) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            return m.group(0)
        value = values[key]
        if josa and key == JOB_KEY and text.startswith(RO, m.end()) and needs_euro(value):
            return value + EU
        return value

    return FIELD_RE.sub(sub, text)


def decode_preview(raw: bytes) -> tuple[str, str] | None:
    try:
        if raw.startswith(b"\xff\xfe"):
            return raw[2:].decode("utf-16-le"), "utf-16-le-bom"
        if raw.startswith(b"\xfe\xff"):
            return raw[2:].decode("utf-16-be"), "utf-16-be-bom"
        if raw.startswith(b"\xef\xbb\xbf"):
            return raw[3:].decode("utf-8"), "utf-8-sig"
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return None


def encode_preview(text: str, encoding: str) -> bytes:
    if encoding == "utf-16-le-bom":
        return b"\xff\xfe" + text.encode("utf-16-le")
    if encoding == "utf-16-be-bom":
        return b"\xfe\xff" + text.encode("utf-16-be")
    if encoding == "utf-8-sig":
        return b"\xef\xbb\xbf" + text.encode("utf-8")
    return text.encode("utf-8")


def build(template: bytes, values: dict[str, str], josa: bool = True) -> tuple[bytes, BuildReport]:
    report = BuildReport()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(template)) as src, zipfile.ZipFile(out, "w") as dst:
        infos = sorted(src.infolist(), key=lambda i: i.filename != MIMETYPE)
        for info in infos:
            data = src.read(info)
            if SECTION_RE.match(info.filename):
                data = replace_in_xml(data.decode("utf-8"), values, josa, report).encode("utf-8")
            elif info.filename == PREVIEW_TEXT:
                decoded = decode_preview(data)
                if decoded is not None:
                    data = encode_preview(replace_in_preview(decoded[0], values, josa), decoded[1])
            new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new_info.compress_type = zipfile.ZIP_STORED if info.filename == MIMETYPE else info.compress_type
            new_info.external_attr = info.external_attr
            dst.writestr(new_info, data)
    return out.getvalue(), report


def strip_text(xml: str) -> str:
    return T_INNER_RE.sub(lambda m: m.group(1) + m.group(3), xml)
