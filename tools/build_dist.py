import hashlib
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from insa_tongji import __version__  # noqa: E402

PRODUCT = "인사발령장 자동생성기"
DIST_ROOT = ROOT / "dist"
STAGING = DIST_ROOT / "_pyinstaller"
LAUNCHER = "@echo off\r\ncd /d \"%~dp0\"\r\nstart \"\" \"%~dp0insa_tongji.exe\"\r\n"
BUNDLED_DOCS = {
    "manual.md": "사용설명서.md",
    "security_notice.md": "보안담당자용_안내.md",
    "maintainer.md": "유지관리자_문서.md",
    "CHANGELOG.md": "CHANGELOG.md",
}


def release_name(today: date | None = None) -> str:
    return f"{PRODUCT}-{(today or date.today()).strftime('%Y%m%d')}-v{__version__}"


def run(cmd: list[str]) -> None:
    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def zip_folder(folder: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, Path(folder.name) / path.relative_to(folder))


def main() -> None:
    name = release_name()
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    shutil.rmtree(DIST_ROOT, ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "insa_tongji",
         "--distpath", str(STAGING), "--add-data", "insa_tongji/app/static;app/static", "--exclude-module", "tkinter",
         "--exclude-module", "pytest", "--exclude-module", "numpy", "--exclude-module", "PIL", "run_app.py"])
    final = DIST_ROOT / name
    shutil.move(str(STAGING / "insa_tongji"), final)
    shutil.rmtree(STAGING, ignore_errors=True)
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    (ROOT / "insa_tongji.spec").unlink(missing_ok=True)
    (final / "실행.bat").write_bytes(LAUNCHER.encode("ascii"))
    for src, dst in BUNDLED_DOCS.items():
        shutil.copy(ROOT / "docs" / src, final / dst)
    run([sys.executable, "tools/check_dist.py", str(final)])
    run([sys.executable, "tools/smoke_exe.py", str(final / "insa_tongji.exe")])
    archive = DIST_ROOT / f"{name}.zip"
    zip_folder(final, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (DIST_ROOT / f"{name}.zip.sha256.txt").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"\n결과물 폴더: {final}\n결과물 압축: {archive}\nSHA-256: {digest}")


if __name__ == "__main__":
    main()
