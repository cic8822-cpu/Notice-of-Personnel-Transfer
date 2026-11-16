import contextlib
import os
import queue
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

PROG_ID = "HWPFrame.HwpObject"
CONVERT_TIMEOUT_SEC = 120


@dataclass
class OpenCheck:
    opened: bool
    pages: int
    pdf: Path | None = None
    error: str = ""


def available() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, PROG_ID):
            return True
    except (ImportError, OSError):
        return False


@contextlib.contextmanager
def session():
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    hwp = None
    try:
        hwp = win32com.client.DispatchEx(PROG_ID)
        with contextlib.suppress(Exception):
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        with contextlib.suppress(Exception):
            hwp.XHwpWindows.Item(0).Visible = False
        yield hwp
    finally:
        if hwp is not None:
            with contextlib.suppress(Exception):
                hwp.Clear(1)
            with contextlib.suppress(Exception):
                hwp.Quit()
        pythoncom.CoUninitialize()


def _open(hwp, path: Path, fmt: str) -> bool:
    return bool(hwp.Open(str(path), fmt, "forceopen:true;versionwarning:false"))


def check_file(path: Path, pdf_dir: Path | None = None) -> OpenCheck:
    try:
        with session() as hwp:
            if not _open(hwp, path, "HWPX"):
                return OpenCheck(False, 0, error="열기 실패")
            pages = int(hwp.PageCount)
            pdf = None
            if pdf_dir is not None:
                pdf = pdf_dir / (path.stem + ".pdf")
                hwp.SaveAs(str(pdf), "PDF", "")
            return OpenCheck(True, pages, pdf)
    except Exception as exc:
        return OpenCheck(False, 0, error=type(exc).__name__)


def _convert(data: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="insa_conv_", ignore_cleanup_errors=True) as tmp:
        src = Path(tmp) / "src.hwp"
        dst = Path(tmp) / "dst.hwpx"
        src.write_bytes(data)
        with session() as hwp:
            if not _open(hwp, src, "HWP"):
                raise RuntimeError("HWP 열기 실패")
            hwp.SaveAs(str(dst), "HWPX", "")
            hwp.Clear(1)
        if not dst.exists() or os.path.getsize(dst) == 0:
            raise RuntimeError("HWPX 변환 결과 없음")
        return dst.read_bytes()


def hwpx_to_pdf(data: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="insa_pdf_", ignore_cleanup_errors=True) as tmp:
        src = Path(tmp) / "doc.hwpx"
        src.write_bytes(data)
        result = check_file(src, Path(tmp))
        if not result.opened or result.pdf is None or not result.pdf.exists():
            raise RuntimeError(result.error or "PDF 변환 실패")
        return result.pdf.read_bytes()


def convert_hwp_to_hwpx(data: bytes, timeout: float = CONVERT_TIMEOUT_SEC) -> bytes:
    box: queue.Queue = queue.Queue()

    def work():
        try:
            box.put(("ok", _convert(data)))
        except Exception as exc:
            box.put(("err", exc))

    threading.Thread(target=work, daemon=True).start()
    try:
        kind, value = box.get(timeout=timeout)
    except queue.Empty:
        raise RuntimeError("한컴오피스 응답 시간 초과(보안 확인 창이 떠 있는지 확인하세요)") from None
    if kind == "err":
        raise value
    return value


class PdfRenderer:
    def __init__(self, idle_seconds: float = 90, timeout: float = 120):
        self.idle_seconds = idle_seconds
        self.timeout = timeout
        self._jobs: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def render(self, data: bytes) -> bytes:
        done: queue.Queue = queue.Queue(maxsize=1)
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
            self._jobs.put((data, done))
        try:
            kind, value = done.get(timeout=self.timeout)
        except queue.Empty:
            raise RuntimeError("한컴오피스 응답 시간 초과(보안 확인 창이 떠 있는지 확인하세요)") from None
        if kind == "err":
            raise value
        return value

    def _run(self) -> None:
        try:
            with session() as hwp:
                while True:
                    try:
                        data, done = self._jobs.get(timeout=self.idle_seconds)
                    except queue.Empty:
                        with self._lock:
                            if self._jobs.empty():
                                self._thread = None
                                return
                        continue
                    try:
                        done.put(("ok", self._to_pdf(hwp, data)))
                    except Exception as exc:
                        done.put(("err", exc))
        except Exception as exc:
            with self._lock:
                self._thread = None
            while not self._jobs.empty():
                _, done = self._jobs.get_nowait()
                done.put(("err", exc))

    @staticmethod
    def _to_pdf(hwp, data: bytes) -> bytes:
        with tempfile.TemporaryDirectory(prefix="insa_view_", ignore_cleanup_errors=True) as tmp:
            src, pdf = Path(tmp) / "doc.hwpx", Path(tmp) / "doc.pdf"
            src.write_bytes(data)
            try:
                if not _open(hwp, src, "HWPX"):
                    raise RuntimeError("한컴오피스에서 문서를 열지 못했습니다")
                hwp.SaveAs(str(pdf), "PDF", "")
            finally:
                with contextlib.suppress(Exception):
                    hwp.Clear(1)
            if not pdf.exists() or pdf.stat().st_size == 0:
                raise RuntimeError("PDF 변환 결과가 없습니다")
            return pdf.read_bytes()


renderer = PdfRenderer()
