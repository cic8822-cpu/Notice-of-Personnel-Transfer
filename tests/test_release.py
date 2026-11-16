import re
from datetime import date
from pathlib import Path

from insa_tongji import __version__
from tools import build_dist

ROOT = Path(__file__).resolve().parents[1]
NAME_RE = re.compile(r"^인사발령장 자동생성기-\d{8}-v\d+\.\d+\.\d+$")


def test_version_is_single_sourced():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in pyproject
    assert re.search(r"^## (\d+\.\d+\.\d+)", changelog, re.M).group(1) == __version__


def test_release_name_follows_product_date_version_pattern():
    name = build_dist.release_name(date(2026, 11, 16))
    assert name == f"인사발령장 자동생성기-20261116-v{__version__}"
    assert NAME_RE.match(name)
    assert NAME_RE.match(build_dist.release_name())


def test_release_name_has_no_forbidden_filename_characters():
    assert not set(r'\/:*?"<>|') & set(build_dist.release_name())
