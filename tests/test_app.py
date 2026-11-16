import io
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

from insa_tongji.app.server import AppServer
from insa_tongji.app.service import Session

from .synth_gen import make_workbook, order_row, synth_rows

ROOT = Path(__file__).resolve().parents[1]
D1 = datetime(2026, 11, 1)


@pytest.fixture()
def server(tmp_path):
    session = Session(home=tmp_path / "home")
    srv = AppServer(session)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


class Client:
    def __init__(self, srv):
        self.srv = srv

    def call(self, method, path, body=None, headers=None, token=True):
        hdrs = {"Host": f"127.0.0.1:{self.srv.server_address[1]}"}
        if token:
            hdrs["X-Session-Token"] = self.srv.token
        hdrs.update(headers or {})
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        url = self.srv.base_url + urllib.parse.quote(path, safe="/?&=:%")
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as err:
            return err.code, err.read(), dict(err.headers)

    def json(self, *args, **kwargs):
        status, body, _ = self.call(*args, **kwargs)
        return status, json.loads(body)


@pytest.fixture()
def client(server):
    return Client(server)


def setup_templates(client):
    for kind in ("신규", "전보"):
        data = (ROOT / "templates" / f"{kind}.hwpx").read_bytes()
        status, body = client.json("POST", f"/api/template?kind={kind}", data)
        assert status == 200, body


def test_t32_token_host_origin_enforced(server, client):
    assert client.call("GET", "/api/precheck", token=False)[0] == 401
    assert client.call("GET", "/api/precheck", headers={"X-Session-Token": "wrong"})[0] == 401
    assert client.call("GET", "/api/precheck", headers={"Host": "evil.example.com"})[0] == 403
    assert client.call("GET", "/api/precheck", headers={"Origin": "http://evil.example.com"})[0] == 403
    assert client.call("GET", "/api/precheck", headers={"Origin": server.base_url})[0] == 200
    assert client.call("GET", "/", token=False)[0] == 401
    assert client.call("PUT", "/api/precheck")[0] == 405
    status, body, headers = client.call("GET", "/api/precheck")
    assert status == 200 and "Access-Control-Allow-Origin" not in headers
    assert headers["Cache-Control"] == "no-store"


def test_index_served_with_token_and_static_traversal_blocked(server, client):
    status, body, _ = client.call("GET", "/?t=" + server.token, token=False)
    assert status == 200 and "인사발령장 자동생성기" in body.decode()
    assert client.call("GET", "/static/..%2f..%2fpyproject.toml", token=False)[0] == 404
    assert client.call("GET", "/static/../service.py", token=False)[0] == 404
    status, css, headers = client.call("GET", "/static/style.css", token=False)
    assert status == 200 and "text/css" in headers["Content-Type"]


def test_t33_binds_loopback_only_and_no_external_urls_in_ui(server):
    assert server.server_address[0] == "127.0.0.1"
    static = ROOT / "insa_tongji" / "app" / "static"
    for path in static.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, path.name


def test_full_flow_and_downloads(client):
    rows = synth_rows(6)
    rows.append(order_row("조리원", "오류씨", D1, None, "없는학교", None, "신규"))
    setup_templates(client)
    status, data = client.json("POST", "/api/excel", make_workbook(rows))
    assert status == 200 and data["total"] == 7 and data["needs_check"] == 1
    assert client.json("GET", "/api/preview?row=2")[1]["ok"] is True
    status, result = client.json("POST", "/api/generate", {"scope": "all"})
    assert result["counts"] == {"PASS": 6, "FAIL": 0, "SKIP": 1}
    status, body, headers = client.call("GET", "/api/download/zip")
    zf = zipfile.ZipFile(io.BytesIO(body))
    names = zf.namelist()
    assert status == 200 and sum(n.endswith(".hwpx") for n in names) == 6
    assert "처리결과.xlsx" in names and "오류목록.xlsx" in names
    ledger = openpyxl.load_workbook(io.BytesIO(zf.read("처리결과.xlsx")))["처리결과"]
    assert ledger.max_row == 8
    status, body, headers = client.call("GET", "/api/download/file?row=2")
    assert status == 200 and "attachment" in headers["Content-Disposition"]
    assert client.call("GET", "/api/download/file?row=8")[0] == 400


def test_edit_and_school_choice_flow_and_alias_saved(client, server):
    setup_templates(client)
    rows = [order_row("조리원", "가나다", D1, None, "문정", None, "신규")]
    status, data = client.json("POST", "/api/excel", make_workbook(rows))
    person = data["people"][0]
    assert not person["ok"] and person["match"]["발령교"]["status"] == "ambiguous"
    status, data = client.json("POST", "/api/edit", {
        "edits": [], "choices": [{"row": 2, "field": "발령교", "value": "전주문정초등학교"}], "save_alias": True})
    assert data["people"][0]["ok"] and data["people"][0]["new_school"] == "전주문정초등학교"
    assert "문정" in (server.session.home / "aliases.csv").read_text(encoding="utf-8-sig")
    status, data = client.json("POST", "/api/edit", {"edits": [{"row": 2, "field": "성명", "value": "홍길동"}],
                                                    "choices": []})
    assert data["people"][0]["name"] == "홍길동"
    status, body = client.json("POST", "/api/edit", {"edits": [{"row": 2, "field": "주민등록번호", "value": "x"}]})
    assert status == 400


def test_settings_change_date_style_and_mode(client):
    setup_templates(client)
    rows = [order_row("조리원", "가나다", D1, None, "전라중학교", datetime(2026, 12, 1), "신규")]
    client.json("POST", "/api/excel", make_workbook(rows))
    client.json("POST", "/api/settings", {"date_style": "dot", "date_mode": "E_then_H"})
    status, preview = client.json("GET", "/api/preview?row=2")
    assert "2026. 11. 1." in preview["after"]
    status, body = client.json("POST", "/api/settings", {"date_mode": "fixed", "fixed_date": "내일"})
    assert status == 400


def test_bad_uploads_give_clean_errors(client):
    assert client.json("POST", "/api/excel", b"junk")[0] == 400
    assert client.json("POST", "/api/template?kind=신규", b"junk")[0] == 400
    assert client.json("POST", "/api/template?kind=기타", b"junk")[0] == 400
    assert client.json("POST", "/api/generate", {})[0] == 400
    assert client.json("POST", "/api/nope", {})[0] == 404


def test_templates_and_roster_persist_across_sessions(tmp_path):
    home = tmp_path / "h"
    first = Session(home=home)
    first.register_template("신규", (ROOT / "templates" / "신규.hwpx").read_bytes())
    first.load_excel(make_workbook([order_row("조리원", "가나다", D1, None, "전라중학교", None, "신규")]))
    second = Session(home=home)
    assert "신규" in second.templates and (home / "schools.txt").exists()
    no_school_sheet = openpyxl.Workbook()
    ws = no_school_sheet.active
    ws.title = "인사발령"
    ws.append(["순", "직종", "성명", "주민등록번호", "임용일", "현임교", "발령교", "발령일", "구분"])
    ws.append([1, "조리원", "가나다", None, D1, None, "전라중", None, "신규"])
    buf = io.BytesIO()
    no_school_sheet.save(buf)
    data = second.load_excel(buf.getvalue())
    assert data["people"][0]["new_school"] == "전라중학교"


def test_server_logs_nothing_with_personal_data(server, client, capsys):
    setup_templates(client)
    rows = [order_row("조리원", "비밀이름", D1, None, "전라중학교", None, "신규")]
    client.json("POST", "/api/excel", make_workbook(rows))
    captured = capsys.readouterr()
    assert "비밀이름" not in captured.out + captured.err
