"""JSON API consumed by the single-page UI in app/static."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from docker.errors import DockerException
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import activity_log, backups, cfg_editor, docker_control, mods_editor, steam, store
from app import instances as registry
from app.instances import Instance

router = APIRouter(prefix="/api")

_ID_RE = re.compile(r"^\d{1,20}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
_STEAM_KEY_RE = re.compile(r"^[A-Fa-f0-9]{32}$")


# ---------- helpers ----------


def _instance_or_404(name: str) -> Instance:
    instance = registry.get_instance(name)
    if instance is None:
        raise HTTPException(404, f"Server '{name}' not found")
    return instance


def _docker(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DockerException as exc:
        raise HTTPException(502, f"Docker error: {exc}") from exc


def _parse_docker_time(raw: str | None) -> datetime | None:
    if not raw or raw.startswith("0001"):
        return None
    # Docker emits nanosecond precision; datetime wants microseconds.
    raw = re.sub(r"(\.\d{6})\d*", r"\1", raw.replace("Z", "+00:00"))
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _uptime(started: datetime | None) -> str:
    if not started:
        return "—"
    secs = int((datetime.now(timezone.utc) - started).total_seconds())
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def _pending_restart(instance: Instance, info: dict) -> bool:
    pending = store.pending_since(instance.name)
    if pending is None:
        return False
    if info["status"] != "running":
        return False  # will pick the change up on next start anyway
    started = _parse_docker_time(info["started_at"])
    if started and started > pending:
        store.clear_pending(instance.name)
        return False
    return True


def _read_settings(instance: Instance):
    if not instance.cfg_path.exists():
        raise HTTPException(404, f"Config not found at {instance.cfg_path}")
    try:
        return cfg_editor.read_settings(instance.cfg_path, instance.sandbox_config_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Could not read settings: {exc}") from exc


def _mods_source(instance: Instance):
    return instance.sandbox_config_path if instance.sandbox_config_path.exists() else instance.sandbox_sbc_path


def _mod_ids(instance: Instance) -> list[mods_editor.ModItem]:
    source = _mods_source(instance)
    if not source.exists():
        return []
    try:
        return mods_editor.list_mods(source)
    except Exception:  # noqa: BLE001
        return []


def _settings_json(settings: cfg_editor.ServerSettings) -> dict:
    return {
        "server_name": settings.server_name,
        "game_mode": settings.game_mode,
        "total_pcu": settings.total_pcu,
        "pirate_pcu": settings.pirate_pcu,
        "max_players": settings.max_players,
        "max_backup_saves": settings.max_backup_saves,
        "backup_interval": settings.backup_interval,
        "administrators": settings.administrators,
        "banned": settings.banned,
        "reserved": settings.reserved,
        "has_password": settings.has_password,
        "server_port": settings.server_port,
    }


def _summary(instance: Instance) -> dict:
    info = _docker(docker_control.get_info, instance.container_name)
    out = {
        "name": instance.name,
        "container": instance.container_name,
        "status": info["status"],
        "health": info["health"],
        "cpu": info["cpu"],
        "mem_gb": info["mem_gb"],
        "uptime": _uptime(_parse_docker_time(info["started_at"])) if info["status"] == "running" else "—",
        "pending_restart": _pending_restart(instance, info),
        "settings": None,
        "mods": [],
        "error": None,
    }
    try:
        out["settings"] = _settings_json(_read_settings(instance))
    except HTTPException as exc:
        out["error"] = exc.detail
    out["mods"] = [m.published_file_id for m in _mod_ids(instance)]
    return out


# ---------- servers ----------


@router.get("/servers")
def list_servers():
    items = registry.load_instances()
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
        return list(pool.map(_summary, items))


class NewServer(BaseModel):
    name: str
    container_name: str
    dataset_mount: str
    instance_dir: str
    world_folder: str
    backup_mount: str
    use_defaults: bool = True

    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        v = v.strip()
        if not _NAME_RE.match(v):
            raise ValueError("Name may use letters, numbers, spaces, '_', '.', '-' (max 64).")
        return v


@router.post("/servers", status_code=201)
def add_server(body: NewServer):
    instance = Instance(**body.model_dump(exclude={"use_defaults"}))
    for label, path in (("Dataset mount", instance.dataset_mount), ("Backup mount", instance.backup_mount)):
        if not Path(path).is_dir():
            raise HTTPException(
                400,
                f"{label} '{path}' doesn't exist inside Shipyard. Add the bind-mount to Shipyard's compose file and redeploy first.",
            )
    try:
        registry.add_instance(instance)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if body.use_defaults and instance.cfg_path.exists():
        settings = _read_settings(instance)
        _apply_defaults_to(settings, store.get_defaults())
        cfg_editor.write_settings(instance.cfg_path, instance.sandbox_config_path, settings)
    return _summary(instance)


@router.delete("/servers/{name}")
def remove_server(name: str):
    _instance_or_404(name)
    registry.remove_instance(name)
    return {"ok": True}


@router.get("/servers/{name}")
def server_detail(name: str):
    instance = _instance_or_404(name)
    summary = _summary(instance)
    summary["mods"] = [
        {"id": m.published_file_id, "friendly_name": m.friendly_name} for m in _mod_ids(instance)
    ]
    details = steam.get_details([m["id"] for m in summary["mods"]])
    for m in summary["mods"]:
        d = details[m["id"]]
        m.update(name=d["name"] if not d["name"].startswith("Workshop item") else (m["friendly_name"] or d["name"]),
                 description=d["description"], preview_url=d["preview_url"], url=d["url"])
    summary["backups"] = [
        {"name": b.name, "modified": b.modified.strftime("%Y-%m-%d %H:%M:%S")}
        for b in backups.list_backups(instance)
    ]
    return summary


def _check_ids(v: list[str]) -> list[str]:
    out = [i.strip() for i in v if i.strip()]
    for i in out:
        if not _ID_RE.match(i):
            raise ValueError(f"'{i}' is not a valid SteamID (digits only).")
    return out


class SettingsIn(BaseModel):
    server_name: str = Field(max_length=128)
    game_mode: Literal["Survival", "Creative"]
    total_pcu: int = Field(ge=0, le=10_000_000)
    pirate_pcu: int = Field(ge=0, le=10_000_000)
    max_players: int = Field(ge=1, le=1000)
    max_backup_saves: int = Field(ge=0, le=1000)
    backup_interval: int = Field(ge=1, le=1440)
    administrators: list[str] = []
    banned: list[str] = []
    reserved: list[str] = []
    password: str | None = None
    clear_password: bool = False
    use_default_password: bool = False

    _ids_ok = field_validator("administrators", "banned", "reserved")(_check_ids)


@router.put("/servers/{name}/settings")
def save_settings(name: str, body: SettingsIn):
    instance = _instance_or_404(name)
    settings = _read_settings(instance)
    for field in ("server_name", "game_mode", "total_pcu", "pirate_pcu", "max_players",
                  "max_backup_saves", "backup_interval", "administrators", "banned", "reserved"):
        setattr(settings, field, getattr(body, field))
    cfg_editor.write_settings(instance.cfg_path, instance.sandbox_config_path, settings)

    password = body.password
    if body.use_default_password:
        password = store.get_defaults().get("password") or None
    if body.clear_password:
        cfg_editor.clear_password(instance.cfg_path)
    elif password:
        cfg_editor.set_password(instance.cfg_path, password)

    store.mark_pending(instance.name)
    return _summary(instance)


# ---------- mods on a server ----------


class ModIn(BaseModel):
    id: str

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        v = v.strip()
        if not steam.valid_id(v):
            raise ValueError("Workshop ID must be digits only.")
        return v


def _mod_file_paths(instance: Instance):
    return [p for p in (instance.sandbox_sbc_path, instance.sandbox_config_path) if p.exists()]


@router.post("/servers/{name}/mods")
def add_server_mod(name: str, body: ModIn):
    instance = _instance_or_404(name)
    paths = _mod_file_paths(instance)
    if not paths:
        raise HTTPException(404, "World save not found for this server.")
    friendly = steam.get_details([body.id])[body.id]["name"]
    friendly = "" if friendly.startswith("Workshop item") else friendly
    for path in paths:
        mods_editor.add_mod(path, body.id, friendly)
    store.mark_pending(instance.name)
    return {"ok": True}


@router.delete("/servers/{name}/mods/{mod_id}")
def remove_server_mod(name: str, mod_id: str):
    instance = _instance_or_404(name)
    if not steam.valid_id(mod_id):
        raise HTTPException(400, "Invalid mod id")
    for path in _mod_file_paths(instance):
        try:
            mods_editor.remove_mod(path, mod_id)
        except mods_editor.ModNotFoundError:
            pass
    store.mark_pending(instance.name)
    return {"ok": True}


# ---------- log & backups ----------


@router.get("/servers/{name}/log")
def server_log(name: str, tail: int = 200):
    instance = _instance_or_404(name)
    if docker_control.get_status(instance.container_name) != "running":
        return {"running": False, "lines": []}
    tail = max(10, min(tail, 1000))
    events = _docker(activity_log.recent_activity, instance.container_name, tail)
    return {
        "running": True,
        "lines": [
            {"time": e.timestamp, "category": e.category, "text": e.raw_line, "player": e.player_name}
            for e in events
        ],
    }


@router.post("/servers/{name}/backups")
def create_backup(name: str):
    instance = _instance_or_404(name)
    try:
        return {"name": backups.create_backup(instance)}
    except OSError as exc:
        raise HTTPException(500, f"Backup failed: {exc}") from exc


@router.post("/servers/{name}/backups/{backup_name}/restore")
def restore_backup(name: str, backup_name: str):
    instance = _instance_or_404(name)
    try:
        _docker(backups.restore_backup, instance, backup_name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


# ---------- default settings ----------


def _defaults_json(d: dict) -> dict:
    out = {k: v for k, v in d.items() if k != "password"}
    out["password_set"] = bool(d.get("password"))
    return out


def _apply_defaults_to(settings: cfg_editor.ServerSettings, d: dict) -> None:
    settings.game_mode = d["game_mode"]
    settings.total_pcu = d["total_pcu"]
    settings.pirate_pcu = d["pirate_pcu"]
    settings.max_players = d["max_players"]
    settings.max_backup_saves = d["max_backup_saves"]
    settings.backup_interval = d["backup_interval"]
    settings.administrators = list(d["administrators"])
    settings.banned = list(d["banned"])
    settings.reserved = list(d["reserved"])


class DefaultsIn(BaseModel):
    game_mode: Literal["Survival", "Creative"]
    total_pcu: int = Field(ge=0, le=10_000_000)
    pirate_pcu: int = Field(ge=0, le=10_000_000)
    max_players: int = Field(ge=1, le=1000)
    max_backup_saves: int = Field(ge=0, le=1000)
    backup_interval: int = Field(ge=1, le=1440)
    administrators: list[str] = []
    banned: list[str] = []
    reserved: list[str] = []
    password: str | None = None  # None = leave as is, "" = clear

    _ids_ok = field_validator("administrators", "banned", "reserved")(_check_ids)


@router.get("/defaults")
def get_defaults():
    return _defaults_json(store.get_defaults())


@router.put("/defaults")
def put_defaults(body: DefaultsIn):
    values = body.model_dump()
    if values["password"] is None:
        values["password"] = store.get_defaults().get("password", "")
    return _defaults_json(store.save_defaults(values))


@router.delete("/defaults")
def reset_defaults():
    return _defaults_json(store.reset_defaults())


# ---------- mod library & Workshop search ----------


@router.get("/mods")
def list_mods():
    instances = registry.load_instances()
    used: dict[str, list[str]] = {}
    for inst in instances:
        for m in _mod_ids(inst):
            used.setdefault(m.published_file_id, []).append(inst.name)
    ids = list(dict.fromkeys([*used, *store.get_library()]))
    details = steam.get_details(ids)
    return [{**details[i], "used_by": used.get(i, [])} for i in ids]


@router.post("/mods/library", status_code=201)
def add_library_mod(body: ModIn):
    store.add_to_library(body.id)
    steam.get_details([body.id])
    return {"ok": True}


@router.delete("/mods/library/{mod_id}")
def remove_library_mod(mod_id: str):
    if not steam.valid_id(mod_id):
        raise HTTPException(400, "Invalid mod id")
    store.remove_from_library(mod_id)
    return {"ok": True}


@router.get("/mods/search")
def search_mods(q: str):
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(400, "Type at least 2 characters.")
    if not store.get_steam_key():
        raise HTTPException(412, "No Steam API key configured.")
    try:
        return steam.search(q)
    except steam.SteamError as exc:
        raise HTTPException(502, str(exc)) from exc


# ---------- Steam API key ----------


class KeyIn(BaseModel):
    key: str


@router.get("/steam-key")
def steam_key_status():
    return {"set": store.get_steam_key() is not None, "source": store.steam_key_source()}


@router.put("/steam-key")
def set_steam_key(body: KeyIn):
    if not _STEAM_KEY_RE.match(body.key.strip()):
        raise HTTPException(400, "A Steam Web API key is 32 hex characters.")
    store.set_steam_key(body.key)
    return {"set": True, "source": "ui"}


@router.delete("/steam-key")
def delete_steam_key():
    store.clear_steam_key()
    return steam_key_status()


@router.post("/steam-key/test")
def test_steam_key():
    if not store.get_steam_key():
        raise HTTPException(412, "No Steam API key configured.")
    try:
        steam.test_key()
    except steam.SteamError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True}


# Registered last: its generic {action} path must not shadow /servers/{name}/mods etc.
@router.post("/servers/{name}/{action}")
def server_action(name: str, action: Literal["start", "stop", "restart"]):
    instance = _instance_or_404(name)
    _docker(getattr(docker_control, action), instance.container_name)
    if action != "stop":
        store.clear_pending(instance.name)
    return {"ok": True}
