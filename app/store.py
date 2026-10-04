"""Small persistent stores kept on Shipyard's own data volume (/app/data).

- defaults.yaml  -- default settings template applied to servers on request
- library.yaml   -- Workshop mod IDs the user has added to their list
- pending.yaml   -- per-instance "settings saved at" timestamps, used to show
                    a "restart needed" banner until the container restarts
- steam_key      -- Steam Web API key (0600). Never returned by the API.
                    Falls back to the STEAM_API_KEY env var.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.instances import DATA_DIR

_lock = threading.Lock()

DEFAULT_DEFAULTS = {
    "game_mode": "Survival",
    "password": "",
    "total_pcu": 60000,
    "pirate_pcu": 25000,
    "max_players": 6,
    "max_backup_saves": 7,
    "backup_interval": 30,
    "pause_when_empty": True,
    "administrators": [],
    "banned": [],
    "reserved": [],
}


def atomic_write(path: Path, text: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _load(name: str, default):
    path = DATA_DIR / name
    if not path.exists():
        return default
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return default
    return default if data is None else data


def _save(name: str, data) -> None:
    atomic_write(DATA_DIR / name, yaml.safe_dump(data, sort_keys=False))


# -- default settings --


def get_defaults() -> dict:
    with _lock:
        stored = _load("defaults.yaml", {})
    return {**DEFAULT_DEFAULTS, **stored}


def save_defaults(values: dict) -> dict:
    merged = {**DEFAULT_DEFAULTS, **{k: v for k, v in values.items() if k in DEFAULT_DEFAULTS}}
    with _lock:
        _save("defaults.yaml", merged)
    return merged


def reset_defaults() -> dict:
    return save_defaults(dict(DEFAULT_DEFAULTS))


# -- mod library --


def get_library() -> list[str]:
    with _lock:
        return [str(i) for i in _load("library.yaml", [])]


def add_to_library(mod_id: str) -> None:
    with _lock:
        ids = [str(i) for i in _load("library.yaml", [])]
        if mod_id not in ids:
            ids.append(mod_id)
            _save("library.yaml", ids)


def remove_from_library(mod_id: str) -> None:
    with _lock:
        ids = [str(i) for i in _load("library.yaml", [])]
        _save("library.yaml", [i for i in ids if i != mod_id])


# -- pending restart --


def mark_pending(instance_name: str) -> None:
    with _lock:
        data = _load("pending.yaml", {})
        data[instance_name] = datetime.now(timezone.utc).isoformat()
        _save("pending.yaml", data)


def pending_since(instance_name: str) -> datetime | None:
    with _lock:
        raw = _load("pending.yaml", {}).get(instance_name)
    return datetime.fromisoformat(raw) if raw else None


def clear_pending(instance_name: str) -> None:
    with _lock:
        data = _load("pending.yaml", {})
        if data.pop(instance_name, None) is not None:
            _save("pending.yaml", data)


# -- Steam API key --

_KEY_PATH = DATA_DIR / "steam_key"


def get_steam_key() -> str | None:
    try:
        key = _KEY_PATH.read_text().strip()
        if key:
            return key
    except FileNotFoundError:
        pass
    return os.environ.get("STEAM_API_KEY", "").strip() or None


def steam_key_source() -> str | None:
    if _KEY_PATH.exists() and _KEY_PATH.read_text().strip():
        return "ui"
    if os.environ.get("STEAM_API_KEY", "").strip():
        return "env"
    return None


def set_steam_key(key: str) -> None:
    atomic_write(_KEY_PATH, key.strip() + "\n", mode=0o600)


def clear_steam_key() -> None:
    try:
        _KEY_PATH.unlink()
    except FileNotFoundError:
        pass
