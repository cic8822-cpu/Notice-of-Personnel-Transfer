import csv
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

APP_DIR_NAME = "InsaTongji"
KINDS = ("신규", "전보")
DATE_MODES = ("H_then_E", "E_then_H", "fixed")
DATE_STYLES = ("kor", "dot")


def data_dir() -> Path:
    override = os.environ.get("INSA_TONGJI_HOME")
    base = Path(override) if override else Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class Config:
    date_style: str = "kor"
    josa_fix: bool = True
    date_mode: str = "H_then_E"
    region_prefix: str | None = None


def load_config(home: Path) -> Config:
    path = home / "config.json"
    cfg = Config()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cfg
        if isinstance(raw, dict):
            for key, value in raw.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
    if cfg.date_style not in DATE_STYLES:
        cfg.date_style = "kor"
    if cfg.date_mode not in DATE_MODES:
        cfg.date_mode = "H_then_E"
    if not isinstance(cfg.josa_fix, bool):
        cfg.josa_fix = True
    if cfg.region_prefix is not None and not isinstance(cfg.region_prefix, str):
        cfg.region_prefix = None
    return cfg


def save_config(home: Path, cfg: Config) -> None:
    (home / "config.json").write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")


def template_path(home: Path, kind: str) -> Path:
    return home / "templates" / f"{kind}.hwpx"


def save_template(home: Path, kind: str, data: bytes) -> None:
    path = template_path(home, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def load_template_bytes(home: Path, kind: str) -> bytes | None:
    path = template_path(home, kind)
    return path.read_bytes() if path.exists() else None


def load_aliases(home: Path) -> dict[str, str]:
    path = home / "aliases.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {row[0].strip(): row[1].strip() for row in csv.reader(fh) if len(row) >= 2 and row[0].strip()}


def save_alias(home: Path, alias: str, official: str) -> None:
    with (home / "aliases.csv").open("a", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh).writerow([alias, official])


def roster_path(home: Path) -> Path:
    return home / "schools.txt"
