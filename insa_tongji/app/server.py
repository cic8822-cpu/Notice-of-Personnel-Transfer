import contextlib
import hmac
import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from ..core.excel_reader import ExcelFormatError
from ..core.template_registry import TemplateError
from .service import MAX_UPLOAD, ServiceError, Session

LOOPBACK = "127.0.0.1"
TOKEN_HEADER = "X-Session-Token"
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": ("default-src 'self'; style-src 'self' 'unsafe-inline'; frame-src blob:; "
                                "img-src 'self' blob:; frame-ancestors 'none'"),
}
STATIC_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "app" / "static"
USER_ERRORS = (ServiceError, TemplateError, ExcelFormatError)
BAD_REQUEST = (KeyError, ValueError, IndexError, TypeError, AttributeError)
UNLOCKED_ROUTES = {"/api/template", "/api/render"}
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"}


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, session: Session, port: int = 0):
        super().__init__((LOOPBACK, port), Handler)
        self.session = session
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return f"http://{LOOPBACK}:{self.server_address[1]}"

    @property
    def start_url(self) -> str:
        return f"{self.base_url}/?t={quote(self.token)}"


class Handler(BaseHTTPRequestHandler):
    server: AppServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def _allowed_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"{LOOPBACK}:{port}", f"localhost:{port}"}

    def _guard(self, token_from_query: str | None = None) -> bool:
        if self.headers.get("Host", "") not in self._allowed_hosts():
            self._send_json({"error": "허용되지 않는 Host"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{h}" for h in self._allowed_hosts()}:
            self._send_json({"error": "허용되지 않는 Origin"}, 403)
            return False
        supplied = self.headers.get(TOKEN_HEADER) or token_from_query or ""
        if not hmac.compare_digest(supplied.encode(), self.server.token.encode()):
            self._send_json({"error": "세션 토큰이 없거나 올바르지 않습니다"}, 401)
            return False
        return True

    def _send(self, body: bytes, status: int = 200, ctype: str = "application/json; charset=utf-8",
              extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload, status: int = 200) -> None:
        self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), status)

    def _download(self, name: str, data: bytes, ctype: str) -> None:
        disposition = f"attachment; filename*=UTF-8''{quote(name)}"
        self._send(data, 200, ctype, {"Content-Disposition": disposition})

    def _body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ServiceError("요청 형식이 올바르지 않습니다") from None
        if length < 0 or length > MAX_UPLOAD:
            raise ServiceError("업로드 크기가 올바르지 않거나 제한을 초과했습니다")
        return self.rfile.read(length)

    @staticmethod
    def _json(raw: bytes) -> dict:
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError as exc:
            raise ServiceError("요청 형식이 올바르지 않습니다") from exc
        if not isinstance(body, dict):
            raise ServiceError("요청 형식이 올바르지 않습니다")
        return body

    def do_GET(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path == "/favicon.ico":
            self._send(b"", 204, "image/x-icon")
            return
        if url.path in ("/", "/index.html"):
            if self._guard(query.get("t", [""])[0]):
                self._static("index.html")
            return
        if url.path.startswith("/static/"):
            if self.headers.get("Host", "") in self._allowed_hosts():
                self._static(url.path[len("/static/"):])
            else:
                self._send_json({"error": "허용되지 않는 Host"}, 403)
            return
        if not self._guard():
            return
        self._dispatch("GET", url.path, query)

    def do_POST(self):
        if not self._guard():
            return
        url = urlsplit(self.path)
        self._dispatch("POST", url.path, parse_qs(url.query))

    def do_PUT(self):
        self._send_json({"error": "지원하지 않는 메서드"}, 405)

    do_DELETE = do_PUT

    def _static(self, rel: str) -> None:
        path = (STATIC_DIR / rel).resolve()
        if STATIC_DIR.resolve() not in path.parents or not path.is_file():
            self._send_json({"error": "찾을 수 없습니다"}, 404)
            return
        self._send(path.read_bytes(), 200, MIME.get(path.suffix.lower(), "application/octet-stream"))

    def _dispatch(self, method: str, path: str, query: dict) -> None:
        s = self.server.session
        try:
            body = self._body() if method == "POST" else b""
            guard = contextlib.nullcontext() if path in UNLOCKED_ROUTES else self.server.lock
            with guard:
                self._route(method, path, query, s, body)
        except USER_ERRORS as exc:
            self.close_connection = True
            self._send_json({"error": str(exc)}, 400)
        except BAD_REQUEST:
            self.close_connection = True
            self._send_json({"error": "요청 형식이 올바르지 않습니다"}, 400)
        except Exception as exc:
            self._send_json({"error": f"처리 중 오류가 발생했습니다({type(exc).__name__})"}, 500)

    def _route(self, method: str, path: str, query: dict, s: Session, body: bytes) -> None:
        if method == "GET":
            routes = {
                "/api/precheck": lambda: self._send_json(s.precheck()),
                "/api/people": lambda: self._send_json(s.people_summary() if s.people else {"people": [], "total": 0}),
                "/api/results": lambda: self._send_json(s.result_summary()),
                "/api/preview": lambda: self._send_json(s.preview(int(query["row"][0]))),
            }
            if path in routes:
                routes[path]()
            elif path == "/api/render":
                self._send(s.render_pdf(int(query["row"][0])), 200, "application/pdf")
            elif path == "/api/download/zip":
                rows = [int(x) for x in query["rows"][0].split(",") if x] if "rows" in query else None
                self._download("인사발령통지서.zip", s.zip_bytes(rows), "application/zip")
            elif path == "/api/download/file":
                name, data = s.file_bytes(int(query["row"][0]))
                self._download(name, data, "application/octet-stream")
            elif path == "/api/download/errors":
                self._download("오류목록.xlsx", s.errors_xlsx(), XLSX)
            elif path == "/api/download/ledger":
                self._download("처리결과.xlsx", s.ledger_xlsx(), XLSX)
            else:
                self._send_json({"error": "찾을 수 없습니다"}, 404)
            return
        if path == "/api/excel":
            self._send_json(s.load_excel(body))
        elif path == "/api/template":
            self._send_json(s.register_template(query.get("kind", [""])[0], body))
        elif path == "/api/settings":
            self._send_json(s.update_settings(self._json(body)))
        elif path == "/api/edit":
            req = self._json(body)
            self._send_json(s.apply_edits(req.get("edits", []), req.get("choices", []), bool(req.get("save_alias"))))
        elif path == "/api/generate":
            req = self._json(body)
            self._send_json(s.generate(req.get("scope", "all"), req.get("rows")))
        elif path == "/api/reset":
            self._send_json(s.reset(bool(self._json(body).get("templates"))))
        elif path == "/api/shutdown":
            self._send_json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send_json({"error": "찾을 수 없습니다"}, 404)


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
