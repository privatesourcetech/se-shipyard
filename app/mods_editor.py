"""Add/remove Workshop mods from a world's Sandbox.sbc.

Sandbox.sbc can be 5MB+ with large embedded grid/entity data. To avoid any risk
of a full XML parse/reserialize subtly reformatting (or breaking) the rest of
the file, we only ever touch the isolated <Mods>...</Mods> span: read it with
ElementTree for listing (safe, nothing is written back), but write changes as
targeted text edits of just that span, leaving everything else byte-for-byte
untouched.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

_OPEN = "<Mods>"
_CLOSE = "</Mods>"


@dataclass
class ModItem:
    published_file_id: str
    friendly_name: str = ""


class ModNotFoundError(Exception):
    pass


def _mods_block_span(text: str) -> tuple[int, int]:
    start = text.index(_OPEN)
    end = text.index(_CLOSE, start) + len(_CLOSE)
    return start, end


def list_mods(sandbox_path: Path) -> list[ModItem]:
    text = sandbox_path.read_text(encoding="utf-8")
    start, end = _mods_block_span(text)
    root = ET.fromstring(text[start:end])
    mods = []
    for item in root.findall("ModItem"):
        pfid_el = item.find("PublishedFileId")
        mods.append(
            ModItem(
                published_file_id=pfid_el.text if pfid_el is not None and pfid_el.text else "",
                friendly_name=item.get("FriendlyName", ""),
            )
        )
    return mods


def add_mod(sandbox_path: Path, published_file_id: str, friendly_name: str = "") -> None:
    text = sandbox_path.read_text(encoding="utf-8")
    start, end = _mods_block_span(text)
    block = text[start:end]

    if f"<PublishedFileId>{published_file_id}</PublishedFileId>" in block:
        return  # already present, nothing to do

    new_item = (
        f"    <ModItem FriendlyName={quoteattr(friendly_name)}>\n"
        f"      <Name>{published_file_id}.sbm</Name>\n"
        f"      <PublishedFileId>{published_file_id}</PublishedFileId>\n"
        f"      <PublishedServiceName>Steam</PublishedServiceName>\n"
        f"    </ModItem>\n"
    )
    insert_at = block.rindex(_CLOSE)
    new_block = block[:insert_at] + new_item + "  " + block[insert_at:]

    sandbox_path.write_text(text[:start] + new_block + text[end:], encoding="utf-8")


_MOD_ITEM_RE_TEMPLATE = (
    r"[ \t]*<ModItem\b[^>]*>(?:(?!</ModItem>).)*?<PublishedFileId>{id}</PublishedFileId>"
    r"(?:(?!</ModItem>).)*?</ModItem>[ \t]*\n?"
)


def remove_mod(sandbox_path: Path, published_file_id: str) -> None:
    text = sandbox_path.read_text(encoding="utf-8")
    start, end = _mods_block_span(text)
    block = text[start:end]

    pattern = re.compile(
        _MOD_ITEM_RE_TEMPLATE.format(id=re.escape(published_file_id)),
        re.DOTALL,
    )
    new_block, count = pattern.subn("", block)
    if count == 0:
        raise ModNotFoundError(f"Mod {published_file_id} not found in {sandbox_path}")

    sandbox_path.write_text(text[:start] + new_block + text[end:], encoding="utf-8")
