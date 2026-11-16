import hashlib
import sys
from pathlib import Path

TOP_ALLOWED = {"insa_tongji.exe", "_internal", "실행.bat", "SHA256SUMS.txt", "사용설명서.md", "보안담당자용_안내.md",
               "유지관리자_문서.md", "CHANGELOG.md"}
FORBIDDEN_DIRS = {"fixtures", "real_data", "신규임명장", ".claude", "docs", "tests", "poc_out", "templates", "tools"}
FORBIDDEN_SUFFIXES = {".hwp", ".hwpx", ".hwt", ".hml", ".xlsx", ".xlsm", ".xls", ".csv", ".pdf", ".docx", ".pptx",
                      ".zip", ".jpg", ".jpeg"}
ALLOWED_FILES = {"base_library.zip"}


def check(dist: Path) -> list[str]:
    problems = []
    for entry in dist.iterdir():
        if entry.name not in TOP_ALLOWED:
            problems.append(f"허용되지 않은 최상위 항목: {entry.name}")
    for path in dist.rglob("*"):
        rel = path.relative_to(dist)
        names = [part.lower() for part in rel.parts]
        if any(part in FORBIDDEN_DIRS for part in names):
            problems.append(f"금지 폴더/경로: {rel}")
        elif path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES and path.name.lower() not in ALLOWED_FILES:
            problems.append(f"개인정보·양식 가능 파일 포함: {rel}")
    return problems


def write_hashes(dist: Path) -> Path:
    out = dist / "SHA256SUMS.txt"
    lines = []
    for path in sorted(p for p in dist.rglob("*") if p.is_file() and p.name != out.name):
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(dist).as_posix()}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1])
    issues = check(target)
    for issue in issues:
        print(issue)
    if issues:
        sys.exit(1)
    print("배포본 청결 검사 통과:", write_hashes(target))
