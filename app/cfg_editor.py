"""Read/write SpaceEngineers-Dedicated.cfg.

This file is small, clean XML (unlike Sandbox.sbc), so a full ElementTree
parse/rewrite is safe here. A change only takes effect after the container
is restarted -- callers (routes) are responsible for prompting that.

Known gap: setting a NEW server password is not implemented. The game hashes
it with an algorithm we have not confirmed (ServerPasswordHash/Salt), and
guessing wrong would silently produce a non-working password. Clearing the
password (removing protection entirely) is safe and is supported.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServerSettings:
    game_mode: str
    total_pcu: int
    pirate_pcu: int
    max_players: int
    max_backup_saves: int
    server_name: str
    world_name: str
    administrators: list[str] = field(default_factory=list)
    banned: list[str] = field(default_factory=list)
    reserved: list[str] = field(default_factory=list)
    has_password: bool = False


def _text(root: ET.Element, tag: str, default: str = "") -> str:
    el = root.find(tag)
    if el is None or el.text is None:
        return default
    return el.text


def _session_text(root: ET.Element, tag: str, default: str = "") -> str:
    return _text(root, f"SessionSettings/{tag}", default)


def _id_list(root: ET.Element, tag: str) -> list[str]:
    el = root.find(tag)
    if el is None:
        return []
    return [child.text for child in el.findall("unsignedLong") if child.text]


def read_settings(cfg_path: Path) -> ServerSettings:
    tree = ET.parse(cfg_path)
    root = tree.getroot()

    hash_el = root.find("ServerPasswordHash")
    has_password = bool(hash_el is not None and hash_el.text)

    return ServerSettings(
        game_mode=_session_text(root, "GameMode", "Survival"),
        total_pcu=int(_session_text(root, "TotalPCU", "0") or 0),
        pirate_pcu=int(_session_text(root, "PiratePCU", "0") or 0),
        max_players=int(_session_text(root, "MaxPlayers", "4") or 4),
        max_backup_saves=int(_session_text(root, "MaxBackupSaves", "10") or 10),
        server_name=_text(root, "ServerName", ""),
        world_name=_text(root, "WorldName", ""),
        administrators=_id_list(root, "Administrators"),
        banned=_id_list(root, "Banned"),
        reserved=_id_list(root, "Reserved"),
        has_password=has_password,
    )


def _set_text(root: ET.Element, tag: str, value: str) -> None:
    el = root.find(tag)
    if el is not None:
        el.text = value


def _set_session_text(root: ET.Element, tag: str, value: str) -> None:
    el = root.find(f"SessionSettings/{tag}")
    if el is not None:
        el.text = value


def _set_id_list(root: ET.Element, tag: str, ids: list[str]) -> None:
    el = root.find(tag)
    if el is None:
        return
    for child in list(el):
        el.remove(child)
    for steam_id in ids:
        child = ET.SubElement(el, "unsignedLong")
        child.text = steam_id


def write_settings(cfg_path: Path, settings: ServerSettings) -> None:
    tree = ET.parse(cfg_path)
    root = tree.getroot()

    _set_session_text(root, "GameMode", settings.game_mode)
    _set_session_text(root, "TotalPCU", str(settings.total_pcu))
    _set_session_text(root, "PiratePCU", str(settings.pirate_pcu))
    _set_session_text(root, "MaxPlayers", str(settings.max_players))
    _set_session_text(root, "MaxBackupSaves", str(settings.max_backup_saves))
    _set_text(root, "ServerName", settings.server_name)
    _set_id_list(root, "Administrators", settings.administrators)
    _set_id_list(root, "Banned", settings.banned)
    _set_id_list(root, "Reserved", settings.reserved)

    ET.indent(tree, space="  ")
    tree.write(cfg_path, encoding="utf-8", xml_declaration=True)


def clear_password(cfg_path: Path) -> None:
    tree = ET.parse(cfg_path)
    root = tree.getroot()
    _set_text(root, "ServerPasswordHash", "")
    _set_text(root, "ServerPasswordSalt", "")
    ET.indent(tree, space="  ")
    tree.write(cfg_path, encoding="utf-8", xml_declaration=True)
