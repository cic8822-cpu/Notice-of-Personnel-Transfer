"""Stop 훅: 린트(ruff)·테스트(pytest)가 통과하기 전에는 Claude의 완료 보고를 막는다.

- 실패하면 {"decision": "block", "reason": ...}을 출력해 수정 작업으로 되돌린다.
- 무한 반복 방지: 연속 차단 횟수가 MAX_BLOCKS를 넘으면 차단을 풀고 사용자에게 실패 사실을 알린다.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COUNTER = ROOT / ".claude" / "hooks" / ".gate_blocks"
MAX_BLOCKS = 8
PYTEST_NO_TESTS = 5


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr)[-3000:]


def main() -> None:
    try:
        json.load(sys.stdin)
    except Exception:
        pass
    if not (ROOT / "insa_tongji").exists():
        return
    failures = []
    code, out = run([sys.executable, "-m", "ruff", "check", "insa_tongji", "tests"])
    if code != 0:
        failures.append("[ruff]\n" + out)
    code, out = run([sys.executable, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"])
    if code not in (0, PYTEST_NO_TESTS):
        failures.append("[pytest]\n" + out)

    blocks = int(COUNTER.read_text()) if COUNTER.exists() else 0
    if not failures:
        COUNTER.unlink(missing_ok=True)
        return
    if blocks >= MAX_BLOCKS:
        COUNTER.unlink(missing_ok=True)
        msg = f"품질 게이트가 {MAX_BLOCKS}회 연속 실패해 차단을 해제했습니다. 실패 내용을 사용자에게 그대로 보고하세요."
        print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
        return
    COUNTER.write_text(str(blocks + 1))
    reason = "린트/테스트 실패. 완료 보고 전에 수정하세요.\n" + "\n".join(failures)
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


if __name__ == "__main__":
    main()
