"""Steam Workshop lookups for Space Engineers (app id 244850).

- Mod details by ID use ISteamRemoteStorage/GetPublishedFileDetails, which
  needs no API key.
- Name search uses IPublishedFileService/QueryFiles, which requires a Steam
  Web API key (see store.get_steam_key).

Details are cached on the data volume so pages load fast and Steam is hit
rarely. The browser never talks to Steam directly (CORS, and the key must
not reach it).
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from app import store
from app.instances import DATA_DIR

APP_ID = 244850
_CACHE_PATH = DATA_DIR / "mod_cache.json"
_CACHE_TTL = 7 * 24 * 3600
_cache_lock = threading.Lock()
_ID_RE = re.compile(r"^\d{1,20}$")


class SteamError(Exception):
    pass


def valid_id(mod_id: str) -> bool:
    return bool(_ID_RE.match(mod_id))


def workshop_url(mod_id: str) -> str:
    return f"https://steamcommunity.com/sharedfiles/filedetails/?id={mod_id}"


def _http(url: str, data: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "se-shipyard"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SteamError("Steam rejected the API key.") from exc
        raise SteamError(f"Steam returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SteamError(f"Could not reach Steam: {exc}") from exc


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    store.atomic_write(_CACHE_PATH, json.dumps(cache))


def _normalize(item: dict) -> dict:
    desc = item.get("short_description") or item.get("description") or ""
    return {
        "id": str(item.get("publishedfileid")),
        "name": item.get("title") or f"Workshop item {item.get('publishedfileid')}",
        "description": desc.strip()[:400],
        "preview_url": item.get("preview_url") or "",
        "url": workshop_url(str(item.get("publishedfileid"))),
    }


def get_details(ids: list[str]) -> dict[str, dict]:
    """Returns {id: info}. IDs Steam can't resolve (or when offline) get a stub."""
    ids = [i for i in dict.fromkeys(ids) if valid_id(i)]
    now = time.time()
    with _cache_lock:
        cache = _load_cache()
        missing = [i for i in ids if i not in cache or now - cache[i].get("fetched", 0) > _CACHE_TTL]
        if missing:
            try:
                for start in range(0, len(missing), 50):
                    chunk = missing[start : start + 50]
                    form = {"itemcount": len(chunk)}
                    form.update({f"publishedfileids[{n}]": i for n, i in enumerate(chunk)})
                    payload = _http(
                        "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                        urllib.parse.urlencode(form).encode(),
                    )
                    for item in payload.get("response", {}).get("publishedfiledetails", []):
                        if item.get("result") == 1:
                            cache[str(item["publishedfileid"])] = {**_normalize(item), "fetched": now}
                _save_cache(cache)
            except SteamError:
                pass  # serve whatever we have; stubs fill the rest
    out = {}
    for i in ids:
        out[i] = cache.get(i) or {
            "id": i,
            "name": f"Workshop item {i}",
            "description": "",
            "preview_url": "",
            "url": workshop_url(i),
        }
    return out


def search(query: str, limit: int = 20) -> list[dict]:
    key = store.get_steam_key()
    if not key:
        raise SteamError("No Steam API key configured.")
    params = urllib.parse.urlencode(
        {
            "key": key,
            "appid": APP_ID,
            "search_text": query,
            "query_type": 12,  # ranked by text search
            "numperpage": limit,
            "page": 1,
            "return_short_description": "true",
            "return_previews": "true",
            "filetype": 0,
        }
    )
    payload = _http(f"https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/?{params}")
    results = [_normalize(i) for i in payload.get("response", {}).get("publishedfiledetails", [])]
    now = time.time()
    with _cache_lock:  # warm the details cache with what we just learned
        cache = _load_cache()
        for r in results:
            cache[r["id"]] = {**r, "fetched": now}
        _save_cache(cache)
    return results


def test_key() -> None:
    """Raises SteamError if the stored key doesn't work."""
    search("a", limit=1)
