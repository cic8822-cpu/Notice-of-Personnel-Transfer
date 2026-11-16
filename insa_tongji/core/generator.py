from dataclasses import dataclass, field

from . import hwpx_engine, verifier
from .template_registry import Template
from .validator import Person

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


@dataclass
class Result:
    row_no: int
    kind: str
    status: str
    data: bytes = b""
    josa_fixed: int = 0
    failures: list[str] = field(default_factory=list)


def generate_one(person: Person, templates: dict[str, Template], date_style: str = "kor", josa: bool = True) -> Result:
    if not person.ok:
        return Result(person.row_no, person.kind, SKIP, failures=["검증 오류로 제외: " + ",".join(person.codes())])
    template = templates.get(person.kind)
    if template is None:
        return Result(person.row_no, person.kind, FAIL, failures=[f"{person.kind} 양식이 등록되지 않았습니다"])
    values = person.values(date_style)
    missing = [f for f in template.required if not values.get(f)]
    if missing:
        return Result(person.row_no, person.kind, FAIL, failures=["양식 필수 값 없음: " + ", ".join(missing)])
    try:
        data, report = hwpx_engine.build(template.data, values, josa)
        check = verifier.verify(template.data, data, {k: values[k] for k in template.required})
    except Exception as exc:
        return Result(person.row_no, person.kind, FAIL, failures=[f"생성 중 예외({type(exc).__name__})"])
    if report.unknown_fields:
        return Result(person.row_no, person.kind, FAIL, failures=["알 수 없는 필드가 남았습니다"])
    if not check.ok:
        return Result(person.row_no, person.kind, FAIL, josa_fixed=report.josa_fixed, failures=check.failures)
    return Result(person.row_no, person.kind, PASS, data, report.josa_fixed)


def generate_all(
    people: list[Person], templates: dict[str, Template], date_style: str = "kor", josa: bool = True
) -> list[Result]:
    return [generate_one(p, templates, date_style, josa) for p in people]
