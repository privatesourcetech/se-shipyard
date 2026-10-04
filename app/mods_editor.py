"""Add/remove Workshop mods from a world's Sandbox.sbc and/or Sandbox_config.sbc.

Both files carry their own <Mods>...</Mods> block, and Sandbox_config.sbc's
copy is the live, continuously-autosaved one that actually governs what loads
(see cfg_editor.py's docstring for how this was confirmed against a running
instance) -- so callers should treat Sandbox_config.sbc as authoritative for
*listing* current mods, but write changes to BOTH files' blocks to keep them
consistent (routes/instance_detail.py does this).

Sandbox.sbc specifically can be 5MB+ with large embedded grid/entity data
(Sandbox_config.sbc is small). To avoid any risk of a full XML parse/
reserialize subtly reformatting (or breaking) the rest of either file, these
functions only ever touch the isolated <Mods>...</Mods> span: read it with
ElementTree for listing (safe, nothing is written back), but write changes as
targeted text edits of just that span, leaving everything else byte-for-byte
untouched.

A world with zero mods serializes as a self-closing empty tag, `<Mods />`
(space before the slash) -- not `<Mods></Mods>`, and not omitted entirely.
Confirmed against a real save (ExampleB), the hard way: an earlier version
of this module checked for the literal substring "<Mods>" and didn't match
"<Mods />" at all, so add_mod() inserted a second, separate empty block
after <SessionName> instead of recognizing and expanding the existing one --
left two <Mods> elements in the file. Fixed by detecting and replacing the
self-closing form specifically; <SessionName> is only used as a fallback
anchor for the (so far never actually observed) case where no Mods element
exists at all.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

_OPEN = "<Mods>"
_CLOSE = "</Mods>"
_SELF_CLOSING_RE = re.compile(r"<Mods\s*/>")


@dataclass
class ModItem:
    published_file_id: str
    friendly_name: str = ""


class ModNotFoundError(Exception):
    pass


class ModsBlockMissingError(Exception):
    pass


def _mods_block_span(text: str) -> tuple[int, int]:
    start = text.index(_OPEN)
    end = text.index(_CLOSE, start) + len(_CLOSE)
    return start, end


_SESSION_NAME_CLOSE = "</SessionName>"


def _ensure_mods_block(text: str) -> str:
    """Make sure a <Mods>...</Mods> pair (not self-closing) exists to insert into."""
    if _OPEN in text:
        return text
    if _SELF_CLOSING_RE.search(text):
        return _SELF_CLOSING_RE.sub("<Mods>\n  </Mods>", text, count=1)
    # Never actually observed -- every real save checked so far has at least
    # the self-closing form -- but handle it rather than assume it can't happen.
    idx = text.find(_SESSION_NAME_CLOSE)
    if idx == -1:
        raise ModsBlockMissingError(
            "No <Mods> element (open/close or self-closing) and no <SessionName> anchor to insert one after"
        )
    insert_at = idx + len(_SESSION_NAME_CLOSE)
    return text[:insert_at] + "\n  <Mods>\n  </Mods>" + text[insert_at:]


def list_mods(sandbox_path: Path) -> list[ModItem]:
    text = sandbox_path.read_text(encoding="utf-8")
    if _OPEN not in text:
        return []  # absent entirely, or self-closing <Mods /> -- either way, no mods
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
    text = _ensure_mods_block(sandbox_path.read_text(encoding="utf-8"))
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
    if _OPEN not in text:
        raise ModNotFoundError(f"No mods present in {sandbox_path}")
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
