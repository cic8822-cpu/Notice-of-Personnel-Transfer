import hashlib
import io
import re
import socket
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from insa_tongji.app.service import Session
from insa_tongji.core.generator import PASS

from .synth_gen import make_workbook, order_row, synth_rows

ROOT = Path(__file__).resolve().parents[1]
RRN = "900101-1234567"
D1 = datetime(2026, 11, 1)
PROTECTED = [ROOT / "fixtures" / "sample.xlsx", ROOT / "templates" / "신규.hwpx", ROOT / "templates" / "전보.hwpx"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_session(tmp_path) -> Session:
    session = Session(home=tmp_path / "home")
    for kind in ("신규", "전보"):
        session.register_template(kind, (ROOT / "templates" / f"{kind}.hwpx").read_bytes())
    return session


def test_t04_bulk_120_people(tmp_path):
    session = new_session(tmp_path)
    session.load_excel(make_workbook(synth_rows(120)))
    start = time.perf_counter()
    summary = session.generate("all")
    elapsed = time.perf_counter() - start
    print(f"T04 120건 생성 {elapsed:.2f}초")
    assert summary["counts"] == {"PASS": 120, "FAIL": 0, "SKIP": 0}
    assert elapsed < 60
    names = zipfile.ZipFile(io.BytesIO(session.zip_bytes())).namelist()
    assert sum(n.startswith("신규/") for n in names) == 60 and sum(n.startswith("전보/") for n in names) == 60
    assert len({n.casefold() for n in names}) == len(names)


def test_t33_flow_works_with_non_loopback_sockets_blocked(tmp_path, monkeypatch):
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise AssertionError(f"외부 연결 시도: {host}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    session = new_session(tmp_path)
    session.load_excel(make_workbook(synth_rows(4)))
    assert session.generate("all")["counts"]["PASS"] == 4


def test_t34_originals_unchanged_after_run(tmp_path):
    before = {p: sha(p) for p in PROTECTED if p.exists()}
    session = new_session(tmp_path)
    session.load_excel((ROOT / "fixtures" / "sample.xlsx").read_bytes())
    session.generate("all")
    session.zip_bytes()
    assert {p: sha(p) for p in before} == before
    preflight = (ROOT / "docs" / "preflight.md").read_text(encoding="utf-8")
    for name, digest in re.findall(r"\| ([^|]+\.(?:hwpx?|xlsx)) \| ([0-9A-F]{64}) \|", preflight):
        path = ROOT / name.strip()
        if path.exists():
            assert sha(path).upper() == digest, name


def test_t35_no_rrn_in_outputs_or_logs(tmp_path, capsys):
    session = new_session(tmp_path)
    rows = [order_row("조리원", "비밀이름", D1, None, "전라중학교", None, "신규", rrn=RRN),
            order_row("조리원", "오류이름", D1, None, "없는학교", None, "신규", rrn=RRN)]
    session.load_excel(make_workbook(rows))
    session.generate("all")
    blobs = [session.zip_bytes(), session.ledger_xlsx(), session.errors_xlsx()]
    for blob in blobs:
        for text in (RRN, RRN.replace("-", ""), "900101"):
            assert text.encode() not in blob
    with zipfile.ZipFile(io.BytesIO(blobs[0])) as outer:
        for name in outer.namelist():
            data = outer.read(name)
            if name.endswith(".hwpx"):
                with zipfile.ZipFile(io.BytesIO(data)) as inner:
                    assert all(b"900101" not in inner.read(n) for n in inner.namelist())
    captured = capsys.readouterr()
    assert "비밀이름" not in captured.out + captured.err
    for path in session.home.rglob("*"):
        if path.is_file():
            assert b"900101" not in path.read_bytes() and "비밀이름".encode() not in path.read_bytes(), path.name


def test_t36_no_temp_leftovers(tmp_path):
    tmp = Path(tempfile.gettempdir())
    before = {p.name for p in tmp.glob("insa_*")}
    session = new_session(tmp_path)
    session.load_excel(make_workbook(synth_rows(3)))
    session.generate("all")
    session.zip_bytes()
    assert {p.name for p in tmp.glob("insa_*")} == before


def test_failure_isolation_across_whole_pipeline(tmp_path):
    session = new_session(tmp_path)
    rows = synth_rows(5)
    rows[2] = order_row("조리원", "{{성명}}", D1, None, "전라중학교", None, "신규")
    session.load_excel(make_workbook(rows))
    summary = session.generate("all")
    assert summary["counts"]["PASS"] == 4 and summary["counts"]["SKIP"] == 1
    assert all(r.status == PASS for row, r in session.results.items() if row != 4)


def test_selected_scope_only_generates_chosen_rows(tmp_path):
    session = new_session(tmp_path)
    session.load_excel(make_workbook(synth_rows(6)))
    session.generate("selected", [2, 3])
    assert set(session.results) == {2, 3}
