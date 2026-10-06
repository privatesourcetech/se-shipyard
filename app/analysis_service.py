"""Runs world analyses in a child process and turns raw results into a dashboard payload.

The expensive parse lives in app/world_analyzer.py. This module starts it,
reports progress, and enriches the finished result with things that are cheap
and always current: world metadata, mods (with Workshop names), host
resources, and rule-based tuning hints.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from app import advanced, mods_editor, steam
from app.instances import DATA_DIR, Instance

ANALYSIS_DIR = DATA_DIR / "analysis"
SBS_NAME = "SANDBOX_0_0_0_.sbs"

_lock = threading.Lock()
_jobs: dict[str, subprocess.Popen] = {}

# Mods that are known to cost performance, by Workshop ID, plus title keywords
# for a softer "often costly" hint. Extend as more are confirmed.
HEAVY_MOD_IDS = {
    "2596208372": "AI bots: pathfinding and per-bot logic",
    "2336089504": "Spawns NPC bots",
}
HEAVY_MOD_KEYWORDS = ("aienabled", "bot_spawner", "bot spawner", "modular encounters", "weaponcore", "defense shield")


def _key(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def _paths(instance: Instance) -> tuple[Path, Path]:
    base = ANALYSIS_DIR / _key(instance.name)
    return base.with_suffix(".json"), base.with_suffix(".progress.json")


def sbs_path(instance: Instance) -> Path:
    return instance.world_path / SBS_NAME


def _alive(name: str) -> bool:
    proc = _jobs.get(name)
    return proc is not None and proc.poll() is None


def start(instance: Instance) -> None:
    src = sbs_path(instance)
    if not src.exists():
        raise FileNotFoundError(
            f"World sector file not found at {src}. Analysis needs the world's {SBS_NAME}."
        )
    with _lock:
        if any(_alive(n) for n in _jobs):
            raise RuntimeError("Another world analysis is already running. Wait for it to finish.")
        out, progress = _paths(instance)
        ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        for p in (out, progress):
            p.unlink(missing_ok=True)
        _jobs[instance.name] = subprocess.Popen(
            [sys.executable, "-m", "app.world_analyzer", str(src), str(out), str(progress)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def status(instance: Instance) -> dict:
    out, progress = _paths(instance)
    src = sbs_path(instance)
    base = {"world_file_exists": src.exists(), "world_file_mb": round(src.stat().st_size / 1e6, 1) if src.exists() else 0,
            "world_file_mtime": src.stat().st_mtime if src.exists() else None}
    if _alive(instance.name):
        p = _read_json(progress) or {}
        frac = (p.get("bytes", 0) / p["total"]) if p.get("total") else 0
        return {**base, "state": "running", "progress": round(min(frac, 0.99), 3)}
    result = _read_json(out)
    if result is None:
        return {**base, "state": "none"}
    if "error" in result:
        return {**base, "state": "error", "error": result["error"]}
    result["stale"] = bool(src.exists() and abs(src.stat().st_mtime - result.get("source_mtime", 0)) > 1)
    return {**base, "state": "done", "result": _enrich(instance, result)}


# ---------- enrichment ----------


def _world_meta(instance: Instance) -> dict:
    meta = {"session_name": None, "last_saved": None}
    path = instance.sandbox_sbc_path
    if not path.exists():
        return meta
    try:
        for _, el in ET.iterparse(path, events=("end",)):
            if el.tag == "SessionName":
                meta["session_name"] = el.text
            elif el.tag == "LastSaveTime":
                meta["last_saved"] = el.text
            if meta["session_name"] and meta["last_saved"]:
                break
    except ET.ParseError:
        pass
    return meta


def _mods(instance: Instance) -> list[dict]:
    source = instance.sandbox_config_path if instance.sandbox_config_path.exists() else instance.sandbox_sbc_path
    if not source.exists():
        return []
    try:
        items = mods_editor.list_mods(source)
    except Exception:  # noqa: BLE001
        return []
    details = steam.get_details([m.published_file_id for m in items])
    out = []
    for m in items:
        d = details[m.published_file_id]
        name = d["name"] if not d["name"].startswith("Workshop item") else (m.friendly_name or d["name"])
        note = HEAVY_MOD_IDS.get(m.published_file_id)
        if note is None and any(k in name.lower() for k in HEAVY_MOD_KEYWORDS):
            note = "Often costly on performance"
        out.append({"id": m.published_file_id, "name": name, "url": d["url"], "heavy_note": note})
    return out


def host_snapshot() -> dict:
    host = {"cpus": os.cpu_count(), "mem_total_gb": None, "mem_available_gb": None, "load1": None, "governor": None}
    try:
        meminfo = {l.split(":")[0]: int(l.split()[1]) for l in Path("/proc/meminfo").read_text().splitlines() if ":" in l}
        host["mem_total_gb"] = round(meminfo["MemTotal"] / 1024**2, 1)
        host["mem_available_gb"] = round(meminfo["MemAvailable"] / 1024**2, 1)
    except (OSError, KeyError, ValueError, IndexError):
        pass
    try:
        host["load1"] = float(Path("/proc/loadavg").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    try:
        host["governor"] = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip()
    except OSError:
        pass
    return host


def _hints(result: dict, mods: list[dict], settings: dict, host: dict) -> list[dict]:
    hints = []

    def add(level, text):
        hints.append({"level": level, "text": text})

    flagged = set()
    for g in result["grids"]:
        if not g["static"] and g["blocks"] >= 10_000:
            flagged.add(g["name"])
            add("high", f"“{g['name']}” is a moving (non-static) grid with {g['blocks']:,} blocks. Giant dynamic grids are "
                        "usually the most expensive things to simulate. Converting it to a station while parked, or splitting "
                        "it up, often helps the most.")
    for g in result["grids"]:
        if g["name"] in flagged or g["static"]:
            continue
        if g["thrusters"] >= 200 or g["gyros"] >= 200:
            add("medium", f"“{g['name']}” has {g['thrusters']:,} thrusters and {g['gyros']:,} gyros on a moving grid, "
                          "which adds per-tick work even when idle.")
    cats = {c["name"]: c["count"] for c in result["categories"]}
    wheels, rotors, pistons = cats.get("Wheels & suspension", 0), cats.get("Rotors & hinges", 0), cats.get("Pistons", 0)
    if wheels + rotors + pistons >= 100:
        add("medium", f"{wheels:,} wheel/suspension, {rotors:,} rotor/hinge and {pistons:,} piston blocks. Each one adds extra "
                      "physics bodies and constraints, which is costly in bulk.")
    if cats.get("Programmable blocks", 0):
        add("info", f"{cats['Programmable blocks']:,} programmable blocks. Scripts run every tick or on timers and can add up.")
    heavy = [m for m in mods if m["heavy_note"]]
    if heavy:
        add("medium", "Mods worth testing without: " + ", ".join(f"{m['name']} ({m['heavy_note']})" for m in heavy) + ".")
    if settings.get("EnableSelectivePhysicsUpdates") is False and result["totals"]["grids"] >= 50:
        add("info", "Selective physics updates is off. With this many grids, turning it on (Advanced settings → Performance) "
                    "may reduce load. Test that far-away grids still behave as you expect.")
    if settings.get("ViewDistance", 0) > 10_000:
        add("info", f"View distance is {settings['ViewDistance']:,} m. Lowering it (for example to 8,000) is a cheap thing to try.")
    if host.get("mem_available_gb") is not None and host["mem_available_gb"] < 8:
        add("medium", f"The host has only {host['mem_available_gb']} GB of RAM available. A large world plus other apps can run it short.")
    if host.get("governor") == "powersave":
        add("info", "The host CPU governor is “powersave”, which can hold clock speeds down under bursty load.")
    if host.get("load1") is not None and host.get("cpus") and host["load1"] / host["cpus"] > 0.6:
        add("info", f"The host is already busy (load {host['load1']} on {host['cpus']} threads), so other apps compete with the game.")
    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(hints, key=lambda h: order[h["level"]])


def _enrich(instance: Instance, result: dict) -> dict:
    mods = _mods(instance)
    try:
        settings = advanced.read_values(instance.cfg_path, instance.sandbox_config_path) if instance.cfg_path.exists() else {}
    except Exception:  # noqa: BLE001
        settings = {}
    host = host_snapshot()
    result["world"] = _world_meta(instance)
    result["mods"] = mods
    result["host"] = host
    result["hints"] = _hints(result, mods, settings, host)
    result["settings"] = {
        k: settings[k] for k in ("EnableSelectivePhysicsUpdates", "SimplifiedSimulation", "SyncDistance", "ViewDistance", "PhysicsIterations")
        if k in settings
    }
    return result
