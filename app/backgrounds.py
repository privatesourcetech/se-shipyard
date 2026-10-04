"""Background slideshow images, kept on the data volume (never in the repo/image).

Sources: images the user uploads, and the official Space Engineers screenshots
from its public Steam store page (fetched on demand, for use on this private
instance only). Files are stored as <prefix>-<hash>.<ext>.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request

from app import store
from app.instances import DATA_DIR
from app.steam import APP_ID, SteamError

BG_DIR = DATA_DIR / "backgrounds"
MAX_BYTES = 15 * 1024 * 1024
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$")
_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def sniff_ext(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def list_images() -> list[str]:
    if not BG_DIR.is_dir():
        return []
    return sorted(p.name for p in BG_DIR.iterdir() if p.is_file() and p.suffix.lower() in _EXTS)


def path_for(name: str):
    """Resolved path for an existing image, or None. Rejects anything but a plain filename."""
    if not _NAME_RE.match(name) or name not in list_images():
        return None
    return BG_DIR / name


def save_upload(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise ValueError("Image is larger than 15 MB.")
    ext = sniff_ext(data)
    if ext is None:
        raise ValueError("Only JPEG, PNG and WebP images are supported.")
    name = f"upload-{hashlib.sha256(data).hexdigest()[:12]}{ext}"
    store.atomic_write_bytes(BG_DIR / name, data)
    return name


def delete(name: str) -> bool:
    p = path_for(name)
    if p is None:
        return False
    p.unlink()
    return True


def _get(url: str, limit: int = MAX_BYTES) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "se-shipyard"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read(limit + 1)
    except Exception as exc:  # noqa: BLE001
        raise SteamError(f"Could not reach Steam: {exc}") from exc
    if len(data) > limit:
        raise SteamError("Steam image was unexpectedly large.")
    return data


def fetch_steam_screenshots() -> dict:
    """Download the official store-page screenshots. Returns {"added": n, "total": n}."""
    raw = _get(f"https://store.steampowered.com/api/appdetails?appids={APP_ID}", limit=5 * 1024 * 1024)
    try:
        shots = json.loads(raw)[str(APP_ID)]["data"]["screenshots"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SteamError("Steam didn't return screenshots for Space Engineers.") from exc

    added = 0
    for shot in shots:
        url = shot.get("path_full") or ""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".steamstatic.com"):
            continue  # only ever download from Steam's CDN
        clean = parsed._replace(query="").geturl()
        name = f"steam-{hashlib.sha256(clean.encode()).hexdigest()[:12]}.jpg"
        if (BG_DIR / name).exists():
            continue
        data = _get(clean)
        if sniff_ext(data) is None:
            continue
        store.atomic_write_bytes(BG_DIR / name, data)
        added += 1
    return {"added": added, "total": len(list_images())}
