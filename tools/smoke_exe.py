import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


def fetch(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as err:
        return err.code


def main(exe: Path) -> int:
    with tempfile.TemporaryDirectory() as home:
        env = {**os.environ, "INSA_TONGJI_HOME": home, "INSA_TONGJI_NO_BROWSER": "1", "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
                                encoding="cp949", errors="replace")
        try:
            line = proc.stdout.readline()
            match = re.search(r"http://127\.0\.0\.1:\d+", line)
            if not match:
                print("시작 메시지에서 주소를 찾지 못했습니다:", line)
                return 1
            base = match.group(0)
            results = {
                "static css": (fetch(base + "/static/style.css"), 200),
                "static js": (fetch(base + "/static/app.js"), 200),
                "index without token": (fetch(base + "/"), 401),
                "api without token": (fetch(base + "/api/precheck"), 401),
            }
            for name, (got, want) in results.items():
                print(f"{name}: {got} (기대 {want})", "OK" if got == want else "FAIL")
            return 0 if all(got == want for got, want in results.values()) else 1
        finally:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
            proc.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
