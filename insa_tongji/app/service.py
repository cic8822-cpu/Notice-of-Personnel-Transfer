import copy
import hashlib
import io
import threading
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .. import __version__
from ..core import excel_reader, hwp_com, hwpx_engine, packager, template_registry
from ..core.generator import PASS, Result, generate_all
from ..core.normalizer import parse_date
from ..core.school_matcher import SchoolMatcher
from ..core.template_registry import Template, TemplateError
from ..core.validator import DATE_MODES, Options, Person, prepare
from . import config as cfgmod

EDITABLE = {"직종": "job", "성명": "name", "현임교": "cur_school", "발령교": "new_school",
            "임용일": "appt", "발령일": "order", "구분": "kind"}
SCHOOL_COLUMNS = {"발령교": "new_school", "현임교": "cur_school"}
MAX_UPLOAD = 50 * 1024 * 1024


class ServiceError(Exception):
    pass


@dataclass
class Session:
    home: Path
    cfg: cfgmod.Config = field(default_factory=cfgmod.Config)
    raw_rows: list = field(default_factory=list)
    schools: list[str] = field(default_factory=list)
    matcher: SchoolMatcher | None = None
    people: list[Person] = field(default_factory=list)
    templates: dict[str, Template] = field(default_factory=dict)
    edits: dict[int, dict[str, str]] = field(default_factory=dict)
    overrides: dict[tuple[int, str], str] = field(default_factory=dict)
    fixed_date: date | None = None
    results: dict[int, Result] = field(default_factory=dict)
    pdf_cache: dict[int, bytes] = field(default_factory=dict)
    excel_sha256: str = ""
    lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self):
        self.cfg = cfgmod.load_config(self.home)
        for kind in cfgmod.KINDS:
            data = cfgmod.load_template_bytes(self.home, kind)
            if data:
                try:
                    self.templates[kind] = template_registry.register(kind, data)
                except TemplateError:
                    self.templates.pop(kind, None)

    def precheck(self) -> dict:
        return {
            "version": __version__,
            "hancom": hwp_com.available(),
            "can_render": hwp_com.available(),
            "templates": {k: {"fields": dict(t.fields), "sha256": t.sha256[:12], "warnings": t.warnings}
                          for k, t in self.templates.items()},
            "region_prefix": self.matcher.region_prefix if self.matcher else self.cfg.region_prefix or "",
            "collisions": sorted(self.matcher.collisions) if self.matcher else [],
            "offline": True,
            "excel_loaded": bool(self.raw_rows),
            "settings": {"date_style": self.cfg.date_style, "date_mode": self.cfg.date_mode,
                         "josa_fix": self.cfg.josa_fix,
                         "fixed_date": self.fixed_date.isoformat() if self.fixed_date else ""},
        }

    def _invalidate(self) -> None:
        self.results.clear()
        self.pdf_cache.clear()

    def reset(self, delete_templates: bool = False) -> dict:
        with self.lock:
            self.raw_rows, self.schools, self.people = [], [], []
            self.matcher = None
            self.edits.clear()
            self.overrides.clear()
            self.results.clear()
            self.pdf_cache.clear()
            self.fixed_date = None
            self.excel_sha256 = ""
            if delete_templates:
                self.templates.clear()
                for kind in cfgmod.KINDS:
                    cfgmod.template_path(self.home, kind).unlink(missing_ok=True)
            return self.precheck()

    def load_excel(self, data: bytes) -> dict:
        if len(data) > MAX_UPLOAD:
            raise ServiceError("엑셀 파일이 너무 큽니다")
        rows = excel_reader.read_orders(data)
        roster = cfgmod.roster_path(self.home)
        try:
            schools = excel_reader.read_schools(data)
            fresh_roster = True
        except excel_reader.ExcelFormatError:
            if not roster.exists():
                raise ServiceError("엑셀에 '학교명' 시트가 없고 저장된 학교 명부도 없습니다") from None
            schools = roster.read_text(encoding="utf-8").splitlines()
            fresh_roster = False
        matcher = SchoolMatcher(schools, cfgmod.load_aliases(self.home), self.cfg.region_prefix)
        if fresh_roster:
            roster.write_text("\n".join(schools), encoding="utf-8")
        with self.lock:
            self.raw_rows, self.schools, self.matcher = rows, schools, matcher
            self.excel_sha256 = hashlib.sha256(data).hexdigest()
            self.edits.clear()
            self.overrides.clear()
            self._invalidate()
            return self.validate()

    def register_template(self, kind: str, data: bytes) -> dict:
        if kind not in cfgmod.KINDS:
            raise ServiceError("양식 구분은 신규 또는 전보여야 합니다")
        template = template_registry.register(kind, data)
        with self.lock:
            self.templates[kind] = template
            cfgmod.save_template(self.home, kind, template.data)
            self._invalidate()
        return {"kind": kind, "fields": dict(template.fields), "sha256": template.sha256[:12],
                "warnings": template.warnings}

    def update_settings(self, body: dict) -> dict:
        date_style = body.get("date_style", self.cfg.date_style)
        date_mode = body.get("date_mode", self.cfg.date_mode)
        if date_style not in cfgmod.DATE_STYLES:
            raise ServiceError("날짜 표기 값이 올바르지 않습니다")
        if date_mode not in DATE_MODES:
            raise ServiceError("발령일 기준 값이 올바르지 않습니다")
        fixed = self.fixed_date
        if "fixed_date" in body:
            fixed = parse_date(body["fixed_date"]) if body["fixed_date"] else None
            if body["fixed_date"] and fixed is None:
                raise ServiceError("지정 발령일을 해석할 수 없습니다")
        if date_mode == "fixed" and fixed is None:
            raise ServiceError("전체 동일 일자를 선택한 경우 지정 일자를 입력해야 합니다")
        with self.lock:
            self.cfg.date_style, self.cfg.date_mode = date_style, date_mode
            if "josa_fix" in body:
                self.cfg.josa_fix = bool(body["josa_fix"])
            self.fixed_date = fixed
            cfgmod.save_config(self.home, self.cfg)
            self._invalidate()
            return self.validate() if self.raw_rows else {}

    def apply_edits(self, edits: list, choices: list, save_alias: bool = False) -> dict:
        if not isinstance(edits, list) or not isinstance(choices, list):
            raise ServiceError("요청 형식이 올바르지 않습니다")
        parsed_edits = []
        for item in edits:
            col = item.get("field")
            if col not in EDITABLE:
                raise ServiceError(f"수정할 수 없는 열입니다: {col}")
            parsed_edits.append((int(item["row"]), col, str(item.get("value", ""))))
        parsed_choices = []
        for item in choices:
            if item.get("field") not in SCHOOL_COLUMNS:
                raise ServiceError("학교 선택은 발령교·현임교에만 가능합니다")
            parsed_choices.append((int(item["row"]), item["field"], str(item["value"])))
        notice = ""
        with self.lock:
            for row, col, value in parsed_edits:
                self.edits.setdefault(row, {})[EDITABLE[col]] = value
                self.overrides.pop((row, col), None)
            for row, col, value in parsed_choices:
                self.overrides[(row, col)] = value
                if save_alias and self.matcher:
                    original = self._raw_value(row, SCHOOL_COLUMNS[col])
                    if original and original != value and value in self.matcher.schools:
                        cfgmod.save_alias(self.home, original, value)
                    elif save_alias:
                        notice = "명부에 없는 학교명은 별칭으로 저장되지 않습니다. 학교명 시트에 추가하세요."
            self._invalidate()
            summary = self.validate()
        if notice:
            summary["notice"] = notice
        return summary

    def _raw_value(self, row_no: int, attr: str) -> str:
        for raw in self.raw_rows:
            if raw.row_no == row_no:
                return str(self.edits.get(row_no, {}).get(attr, getattr(raw, attr)) or "")
        return ""

    def _effective_rows(self) -> list:
        rows = []
        for raw in self.raw_rows:
            clone = copy.copy(raw)
            for attr, value in self.edits.get(raw.row_no, {}).items():
                setattr(clone, attr, value)
            rows.append(clone)
        return rows

    def validate(self) -> dict:
        if not self.matcher:
            raise ServiceError("먼저 엑셀을 불러오세요")
        opts = Options(date_mode=self.cfg.date_mode, fixed_date=self.fixed_date, overrides=dict(self.overrides))
        self.people = prepare(self._effective_rows(), self.matcher, opts)
        return self.people_summary()

    def people_summary(self) -> dict:
        items = []
        for p in self.people:
            items.append({
                "row": p.row_no, "kind": p.kind, "job": p.job, "name": p.name, "cur_school": p.cur_school,
                "new_school": p.new_school, "date": p.order_date.isoformat() if p.order_date else "",
                "ok": p.ok,
                "issues": [{"code": i.code, "level": i.level, "message": i.message} for i in p.issues],
                "match": {col: {"status": m.status, "candidates": list(m.candidates), "basis": m.basis}
                          for col, m in (("발령교", p.new_match), ("현임교", p.cur_match)) if m is not None},
                "status": self.results[p.row_no].status if p.row_no in self.results else "",
            })
        kinds = [p.kind for p in self.people]
        return {
            "total": len(items), "new": kinds.count("신규"), "transfer": kinds.count("전보"),
            "ok": sum(p.ok for p in self.people), "needs_check": sum(not p.ok for p in self.people),
            "people": items,
        }

    def _person(self, row: int) -> Person:
        for p in self.people:
            if p.row_no == row:
                return p
        raise ServiceError("대상 행을 찾을 수 없습니다")

    def preview(self, row: int) -> dict:
        with self.lock:
            p = self._person(row)
            template = self.templates.get(p.kind)
            if template is None:
                raise ServiceError(f"{p.kind or '해당'} 양식이 등록되지 않았습니다")
            values = p.values(self.cfg.date_style)
            josa, ok = self.cfg.josa_fix, p.ok
        data, report = hwpx_engine.build(template.data, values, josa)
        return {"before": _body_text(template.data), "after": _body_text(data), "values": values,
                "josa_fixed": report.josa_fixed, "ok": ok}

    def generate(self, scope: str = "all", rows: list[int] | None = None) -> dict:
        with self.lock:
            if not self.people:
                raise ServiceError("먼저 엑셀을 불러오세요")
            chosen = [p for p in self.people if self._in_scope(p, scope, rows)]
            for result in generate_all(chosen, self.templates, self.cfg.date_style, self.cfg.josa_fix):
                self.results[result.row_no] = result
            return self.result_summary()

    @staticmethod
    def _in_scope(p: Person, scope: str, rows: list[int] | None) -> bool:
        if scope == "new":
            return p.kind == "신규"
        if scope == "transfer":
            return p.kind == "전보"
        if scope == "selected":
            return p.row_no in set(rows or [])
        return True

    def result_summary(self) -> dict:
        counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
        for r in self.results.values():
            counts[r.status] += 1
        return {"counts": counts, "josa_fixed": sum(1 for r in self.results.values() if r.josa_fixed),
                "people": self.people_summary()["people"]}

    def zip_bytes(self, rows: list[int] | None = None) -> bytes:
        data, _ = packager.build_zip(self.people, list(self.results.values()), None if rows is None else set(rows))
        return data

    def render_pdf(self, row: int) -> bytes:
        if not hwp_com.available():
            raise ServiceError("화면 보기·출력에는 한컴오피스가 필요합니다. 한컴이 없으면 HWPX를 내려받아 여세요")
        with self.lock:
            if row in self.pdf_cache:
                return self.pdf_cache[row]
            result = self.results.get(row)
            if result is None or result.status != PASS:
                raise ServiceError("생성된 파일이 없습니다")
            data = result.data
        try:
            pdf = hwp_com.renderer.render(data)
        except RuntimeError as exc:
            raise ServiceError(str(exc)) from exc
        with self.lock:
            if self.results.get(row) is not None and self.results[row].data == data:
                self.pdf_cache[row] = pdf
        return pdf

    def file_bytes(self, row: int) -> tuple[str, bytes]:
        result = self.results.get(row)
        if result is None or result.status != PASS:
            raise ServiceError("생성된 파일이 없습니다")
        name = packager.assign_filenames(self.people)[row]
        return name, result.data

    def errors_xlsx(self) -> bytes:
        return packager.errors_bytes(self.people, list(self.results.values()))

    def ledger_xlsx(self) -> bytes:
        names = packager.assign_filenames(self.people)
        return packager.ledger_bytes(self.people, list(self.results.values()), names)


def _body_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return "\n".join(hwpx_engine.plain_text(zf.read(n).decode("utf-8"))
                         for n in zf.namelist() if hwpx_engine.SECTION_RE.match(n))
