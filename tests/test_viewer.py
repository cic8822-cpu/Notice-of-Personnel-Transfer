import http.client
import io
import threading
import time
import zipfile
from pathlib import Path

import pytest

from insa_tongji.app.server import AppServer
from insa_tongji.app.service import ServiceError, Session
from insa_tongji.core import hwp_com

from .synth_gen import make_workbook, synth_rows

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "insa_tongji" / "app" / "static"
FAKE_PDF = b"%PDF-1.4 fake"


def prepared_session(tmp_path, count=4) -> Session:
    s = Session(home=tmp_path / "home")
    s.register_template("신규", (ROOT / "templates" / "신규.hwpx").read_bytes())
    s.register_template("전보", (ROOT / "templates" / "전보.hwpx").read_bytes())
    s.load_excel(make_workbook(synth_rows(count)))
    s.generate("all")
    return s


class FakeRenderer:
    def __init__(self):
        self.calls = 0

    def render(self, data: bytes) -> bytes:
        self.calls += 1
        return FAKE_PDF


@pytest.fixture()
def fake_render(monkeypatch):
    fake = FakeRenderer()
    monkeypatch.setattr(hwp_com, "available", lambda: True)
    monkeypatch.setattr(hwp_com, "renderer", fake)
    return fake


def test_render_pdf_is_cached_per_document(tmp_path, fake_render):
    s = prepared_session(tmp_path)
    assert s.render_pdf(2) == FAKE_PDF and s.render_pdf(2) == FAKE_PDF
    assert fake_render.calls == 1
    assert s.render_pdf(3) == FAKE_PDF and fake_render.calls == 2


def test_cache_is_dropped_when_results_change(tmp_path, fake_render):
    s = prepared_session(tmp_path)
    s.render_pdf(2)
    s.update_settings({"date_style": "dot"})
    assert s.pdf_cache == {}
    s.generate("all")
    s.render_pdf(2)
    s.reset()
    assert s.pdf_cache == {} and fake_render.calls == 2


def test_render_requires_hancom_and_a_generated_file(tmp_path, monkeypatch, fake_render):
    s = prepared_session(tmp_path)
    with pytest.raises(ServiceError, match="생성된 파일이 없습니다"):
        s.render_pdf(999)
    monkeypatch.setattr(hwp_com, "available", lambda: False)
    with pytest.raises(ServiceError, match="한컴오피스가 필요합니다"):
        s.render_pdf(2)


def test_render_failure_becomes_a_user_error(tmp_path, monkeypatch):
    s = prepared_session(tmp_path)

    class Broken:
        def render(self, data):
            raise RuntimeError("한컴오피스 응답 시간 초과")

    monkeypatch.setattr(hwp_com, "available", lambda: True)
    monkeypatch.setattr(hwp_com, "renderer", Broken())
    with pytest.raises(ServiceError, match="응답 시간 초과"):
        s.render_pdf(2)


def test_zip_contains_only_the_picked_documents(tmp_path):
    s = prepared_session(tmp_path, count=5)
    everything = zipfile.ZipFile(io.BytesIO(s.zip_bytes())).namelist()
    chosen = zipfile.ZipFile(io.BytesIO(s.zip_bytes([2, 4]))).namelist()
    assert sum(n.endswith(".hwpx") for n in everything) == 5
    assert sum(n.endswith(".hwpx") for n in chosen) == 2
    assert "처리결과.xlsx" in chosen and "오류목록.xlsx" in chosen
    assert sum(n.endswith(".hwpx") for n in zipfile.ZipFile(io.BytesIO(s.zip_bytes([]))).namelist()) == 0


@pytest.fixture()
def running(tmp_path):
    srv = AppServer(prepared_session(tmp_path))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def request(srv, path, method="GET"):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    conn.request(method, path, headers={"X-Session-Token": srv.token})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body, dict(resp.getheaders())


def test_render_route_serves_pdf_and_rejects_bad_input(running, fake_render):
    status, body, headers = request(running, "/api/render?row=2")
    assert status == 200 and body == FAKE_PDF and headers["Content-Type"] == "application/pdf"
    assert request(running, "/api/render")[0] == 400
    assert request(running, "/api/render?row=abc")[0] == 400
    assert request(running, "/api/render?row=999")[0] == 400


def test_render_does_not_block_other_requests(running, monkeypatch):
    release = threading.Event()

    class Slow:
        def render(self, data):
            release.wait(5)
            return FAKE_PDF

    monkeypatch.setattr(hwp_com, "available", lambda: True)
    monkeypatch.setattr(hwp_com, "renderer", Slow())
    worker = threading.Thread(target=lambda: request(running, "/api/render?row=2"))
    worker.start()
    time.sleep(0.3)
    start = time.perf_counter()
    assert request(running, "/api/precheck")[0] == 200
    assert time.perf_counter() - start < 2
    release.set()
    worker.join(5)


def test_selected_zip_route_and_csp_allows_only_blob_frames(running):
    status, body, headers = request(running, "/api/download/zip?rows=2,3")
    assert status == 200 and sum(n.endswith(".hwpx") for n in zipfile.ZipFile(io.BytesIO(body)).namelist()) == 2
    csp = headers["Content-Security-Policy"]
    assert "frame-src blob:" in csp and "default-src 'self'" in csp and "unsafe-eval" not in csp
    assert request(running, "/api/download/zip?rows=abc")[0] == 400


def test_ui_flow_is_generate_then_view_then_download_or_print():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "미리보기" not in html and "미리보기" not in js
    for hook in ('id="vPrint"', 'id="vDownload"', 'id="vBody"', 'data-step="5"'):
        assert hook in html, hook
    assert 'data-step="6"' not in html
    for hook in ("openViewer", "printViewer", "downloadSelected", "/api/render", "/api/download/zip?rows="):
        assert hook in js, hook
    assert "innerHTML" not in js and "eval(" not in js


class FakeHwp:
    def __init__(self):
        self.opened = 0
        self.cleared = 0

    def Open(self, path, fmt, opt):
        self.opened += 1
        return True

    def SaveAs(self, path, fmt, opt):
        Path(path).write_bytes(FAKE_PDF)

    def Clear(self, option):
        self.cleared += 1


def test_pdf_renderer_reuses_one_instance_and_exits_when_idle(monkeypatch):
    fake = FakeHwp()
    started = []

    class Ctx:
        def __enter__(self):
            started.append(1)
            return fake

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(hwp_com, "session", lambda: Ctx())
    renderer = hwp_com.PdfRenderer(idle_seconds=0.4, timeout=5)
    assert renderer.render(b"a") == FAKE_PDF and renderer.render(b"b") == FAKE_PDF
    assert len(started) == 1 and fake.opened == 2 and fake.cleared == 2
    time.sleep(1.0)
    assert renderer._thread is None
    assert renderer.render(b"c") == FAKE_PDF and len(started) == 2


def test_pdf_renderer_reports_startup_failure_without_hanging(monkeypatch):
    class Boom:
        def __enter__(self):
            raise OSError("no hancom")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(hwp_com, "session", lambda: Boom())
    renderer = hwp_com.PdfRenderer(idle_seconds=0.2, timeout=5)
    with pytest.raises(OSError):
        renderer.render(b"x")
    with pytest.raises(OSError):
        renderer.render(b"y")


def test_pdf_renderer_times_out_instead_of_hanging(monkeypatch):
    class Stuck:
        def __enter__(self):
            threading.Event().wait(3)
            return FakeHwp()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(hwp_com, "session", lambda: Stuck())
    renderer = hwp_com.PdfRenderer(idle_seconds=0.2, timeout=0.3)
    with pytest.raises(RuntimeError, match="시간 초과"):
        renderer.render(b"x")


def test_viewer_copy_drops_background_picture_fill_only():
    import io
    import zipfile

    original = (ROOT / "templates" / "전보.hwpx").read_bytes()
    stripped = hwp_com.strip_background_pictures(original)
    before, after = zipfile.ZipFile(io.BytesIO(original)), zipfile.ZipFile(io.BytesIO(stripped))
    assert b"imgBrush" in before.read("Contents/header.xml")
    assert b"imgBrush" not in after.read("Contents/header.xml")
    assert after.namelist() == before.namelist() and after.namelist()[0] == "mimetype"
    for name in before.namelist():
        if name != "Contents/header.xml":
            assert after.read(name) == before.read(name), name
