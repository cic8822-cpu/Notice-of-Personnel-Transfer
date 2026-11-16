import http.client
import io
import threading
import time
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

from insa_tongji.app import config as cfgmod
from insa_tongji.app.server import AppServer
from insa_tongji.app.service import ServiceError, Session
from insa_tongji.core import hwp_com
from insa_tongji.core.template_registry import TemplateError, register
from tools import check_dist

from .synth_gen import make_workbook, order_row

ROOT = Path(__file__).resolve().parents[1]
D1 = datetime(2026, 11, 1)
NEW_BYTES = (ROOT / "templates" / "신규.hwpx").read_bytes()
TRANSFER_BYTES = (ROOT / "templates" / "전보.hwpx").read_bytes()


def session_with_templates(tmp_path) -> Session:
    session = Session(home=tmp_path / "home")
    session.register_template("신규", NEW_BYTES)
    session.register_template("전보", TRANSFER_BYTES)
    return session


def one_row(school="전라중학교", order=None):
    return make_workbook([order_row("조리원", "가나다", D1, None, school, order, "신규")])


def test_settings_change_invalidates_previous_results(tmp_path):
    s = session_with_templates(tmp_path)
    s.load_excel(one_row(order=datetime(2026, 12, 1)))
    s.generate("all")
    assert s.results
    s.update_settings({"date_mode": "E_then_H"})
    assert s.results == {}
    s.generate("all")
    assert s.results
    s.update_settings({"date_style": "dot"})
    assert s.results == {}


def test_template_registered_in_wrong_slot_is_rejected():
    with pytest.raises(TemplateError, match="현임교"):
        register("전보", NEW_BYTES)
    assert register("신규", TRANSFER_BYTES).required


def test_cell_edit_clears_previous_school_choice(tmp_path):
    s = session_with_templates(tmp_path)
    s.load_excel(one_row(school="문정"))
    s.apply_edits([], [{"row": 2, "field": "발령교", "value": "전주문정유치원"}])
    assert s.people[0].new_school == "전주문정유치원" and s.people[0].ok
    s.apply_edits([{"row": 2, "field": "발령교", "value": "없는학교"}], [])
    assert not s.people[0].ok and "V11" in s.people[0].codes()
    s.apply_edits([{"row": 2, "field": "발령교", "value": "문정"}], [])
    assert not s.people[0].ok


def test_edits_are_applied_all_or_nothing(tmp_path):
    s = session_with_templates(tmp_path)
    s.load_excel(one_row())
    with pytest.raises(ServiceError):
        edits = [{"row": 2, "field": "성명", "value": "바뀐이름"}, {"row": 2, "field": "주민등록번호", "value": "x"}]
        s.apply_edits(edits, [])
    assert s.edits == {} and s.people[0].name == "가나다"


def test_settings_applied_all_or_nothing(tmp_path):
    s = session_with_templates(tmp_path)
    before = (s.cfg.date_style, s.cfg.date_mode, s.fixed_date)
    with pytest.raises(ServiceError):
        s.update_settings({"date_style": "dot", "date_mode": "fixed", "fixed_date": "내일"})
    with pytest.raises(ServiceError):
        s.update_settings({"date_style": "dot", "date_mode": "fixed"})
    assert (s.cfg.date_style, s.cfg.date_mode, s.fixed_date) == before


def test_failed_excel_load_keeps_previous_state(tmp_path):
    s = session_with_templates(tmp_path)
    s.load_excel(one_row())
    (s.home / "schools.txt").unlink()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "인사발령"
    ws.append(["순", "직종", "성명", "주민등록번호", "임용일", "현임교", "발령교", "발령일", "구분"])
    ws.append([1, "조리원", "새사람", None, D1, None, "전라중학교", None, "신규"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ServiceError):
        s.load_excel(buf.getvalue())
    assert [p.name for p in s.people] == ["가나다"] and s.raw_rows[0].name == "가나다"


def test_alias_not_saved_for_names_outside_roster(tmp_path):
    s = session_with_templates(tmp_path)
    s.load_excel(one_row(school="서울강남초"))
    out = s.apply_edits([], [{"row": 2, "field": "발령교", "value": "서울강남초등학교"}], save_alias=True)
    assert "별칭" in out["notice"] and not (s.home / "aliases.csv").exists()


def test_corrupt_config_falls_back_to_defaults(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    (home / "config.json").write_text("[1, 2]", encoding="utf-8")
    assert cfgmod.load_config(home) == cfgmod.Config()
    (home / "config.json").write_text('{"date_mode": "weird", "date_style": 5, "josa_fix": "x"}', encoding="utf-8")
    cfg = cfgmod.load_config(home)
    assert (cfg.date_mode, cfg.date_style, cfg.josa_fix) == ("H_then_E", "kor", True)


def test_precheck_exposes_saved_settings(tmp_path):
    s = session_with_templates(tmp_path)
    s.update_settings({"date_style": "dot"})
    assert Session(home=s.home).precheck()["settings"]["date_style"] == "dot"


def test_hwp_conversion_times_out(monkeypatch):
    monkeypatch.setattr(hwp_com, "_convert", lambda data: time.sleep(5))
    start = time.perf_counter()
    with pytest.raises(RuntimeError, match="시간 초과"):
        hwp_com.convert_hwp_to_hwpx(b"x", timeout=0.2)
    assert time.perf_counter() - start < 3


@pytest.fixture()
def running(tmp_path):
    srv = AppServer(session_with_templates(tmp_path))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def raw_request(srv, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    hdrs = {"X-Session-Token": srv.token, **(headers or {})}
    conn.request(method, path, body=body, headers=hdrs)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data, dict(resp.getheaders())


def test_static_mime_types_are_fixed_regardless_of_registry(running):
    status, _, headers = raw_request(running, "GET", "/static/app.js")
    assert status == 200 and "javascript" in headers["Content-Type"]
    status, _, headers = raw_request(running, "GET", "/static/style.css")
    assert "text/css" in headers["Content-Type"]


@pytest.mark.parametrize("length", ["-1", "abc", "99999999999"])
def test_bad_content_length_returns_400_without_hanging(running, length):
    start = time.perf_counter()
    status, _, _ = raw_request(running, "POST", "/api/generate", {"Content-Length": length})
    assert status == 400 and time.perf_counter() - start < 3
    assert raw_request(running, "GET", "/api/precheck")[0] == 200


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/preview", None), ("GET", "/api/preview?row=abc", None), ("GET", "/api/download/file", None),
    ("POST", "/api/generate", b"[1,2]"), ("POST", "/api/edit", b"[]"), ("POST", "/api/settings", b"[]"),
    ("POST", "/api/edit", b'{"edits": "x", "choices": []}'),
])
def test_malformed_requests_are_400_not_500(running, method, path, body):
    assert raw_request(running, method, path, body=body)[0] == 400


def test_dist_check_allowlist_and_case_insensitive(tmp_path):
    dist = tmp_path / "d"
    (dist / "_internal").mkdir(parents=True)
    (dist / "insa_tongji.exe").write_bytes(b"x")
    (dist / "_internal" / "base_library.zip").write_bytes(b"x")
    assert check_dist.check(dist) == []
    (dist / "Fixtures").mkdir()
    (dist / "계획.md").write_text("x", encoding="utf-8")
    (dist / "_internal" / "표.XLSM").write_bytes(b"x")
    (dist / "_internal" / "명단.csv").write_bytes(b"x")
    (dist / "_internal" / "Templates").mkdir()
    problems = " | ".join(check_dist.check(dist))
    for needle in ("Fixtures", "계획.md", "표.XLSM", "명단.csv", "Templates"):
        assert needle in problems, needle


def test_favicon_is_silent_and_needs_no_token(running):
    conn = http.client.HTTPConnection("127.0.0.1", running.server_address[1], timeout=5)
    conn.request("GET", "/favicon.ico")
    resp = conn.getresponse()
    resp.read()
    conn.close()
    assert resp.status == 204


def test_ui_contains_dashboard_hooks():
    static = ROOT / "insa_tongji" / "app" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    js = (static / "app.js").read_text(encoding="utf-8")
    assert 'id="board"' in html and "renderDash" in js and "restoreSession" in js
    assert "innerHTML" not in js and "eval(" not in js


def test_reset_clears_work_but_keeps_templates_by_default(tmp_path):
    s = session_with_templates(tmp_path)
    s.load_excel(one_row())
    s.apply_edits([{"row": 2, "field": "성명", "value": "바뀜"}], [])
    s.generate("all")
    state = s.reset()
    assert (s.raw_rows, s.people, s.results, s.edits, s.overrides, s.matcher) == ([], [], {}, {}, {}, None)
    assert set(s.templates) == {"신규", "전보"} and state["excel_loaded"] is False
    assert Session(home=s.home).templates.keys() == {"신규", "전보"}
    with pytest.raises(ServiceError):
        s.validate()


def test_reset_can_also_delete_registered_templates(tmp_path):
    s = session_with_templates(tmp_path)
    s.load_excel(one_row())
    s.reset(delete_templates=True)
    assert s.templates == {} and Session(home=s.home).templates == {}


def test_reset_route_and_ui_hooks(running):
    running.session.load_excel(one_row())
    status, body, _ = raw_request(running, "POST", "/api/reset", body=b'{"templates": false}')
    assert status == 200 and raw_request(running, "GET", "/api/people")[1] == b'{"people": [], "total": 0}'
    assert raw_request(running, "POST", "/api/reset", body=b"[]")[0] == 400
    static = ROOT / "insa_tongji" / "app" / "static"
    assert 'id="reset"' in (static / "index.html").read_text(encoding="utf-8")
    assert "resetAll" in (static / "app.js").read_text(encoding="utf-8")


def test_nothing_is_preloaded_in_a_fresh_session(tmp_path):
    s = Session(home=tmp_path / "fresh")
    assert s.raw_rows == [] and s.people == [] and s.schools == []
    assert s.precheck()["excel_loaded"] is False
