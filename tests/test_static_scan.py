import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "insa_tongji").rglob("*.py"))
NETWORK_MODULES = {"urllib.request", "http.client", "requests", "httpx", "aiohttp", "smtplib", "ftplib", "telnetlib",
                   "socket", "ssl", "xmlrpc.client", "websocket", "websockets", "paramiko"}
URL_HOST_RE = re.compile(r"https?://([A-Za-z0-9][A-Za-z0-9.-]*)")
TELEMETRY_WORDS = ("analytics", "telemetry", "sentry", "google-analytics", "gtag")


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_sources_found():
    assert len(SOURCES) >= 15


def test_no_outbound_network_modules_imported():
    offenders = {p.name: sorted(imported_modules(p) & NETWORK_MODULES) for p in SOURCES}
    assert {k: v for k, v in offenders.items() if v} == {}


def test_no_telemetry_or_external_urls_in_sources():
    for path in SOURCES:
        text = path.read_text(encoding="utf-8").lower()
        hosts = {m for m in URL_HOST_RE.findall(text) if m != "127.0.0.1"}
        assert hosts == set(), (path.name, hosts)
        assert not any(word in text for word in TELEMETRY_WORDS), path.name


def test_no_hardcoded_institution_names_in_code_or_ui():
    forbidden = ("전주교육지원청", "전북특별자치도")
    files = [*SOURCES, *(ROOT / "insa_tongji" / "app" / "static").iterdir()]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not any(word in text for word in forbidden), path.name
