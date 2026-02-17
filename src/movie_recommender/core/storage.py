"""Persistent JSON storage on Docker volume."""
import json
from pathlib import Path

DATA_DIR = Path("/app/data")


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_json(name: str, default=None):
    """Load JSON file from data dir."""
    path = DATA_DIR / f"{name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default if default is not None else {}
    return default if default is not None else {}


def save_json(name: str, data):
    """Save data to JSON file in data dir."""
    _ensure_dir()
    path = DATA_DIR / f"{name}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.rename(path)
