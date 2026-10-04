"""Advanced server settings: a curated, typed whitelist of SpaceEngineers-Dedicated.cfg options.

Two scopes (see cfg_editor.py's docstring for why):
- "session": lives in <SessionSettings> of the cfg AND in <Settings> of the world's
  Sandbox_config.sbc, which is the live copy the running server actually uses.
  Written to both (only where the element already exists -- we never invent elements).
- "server": a direct child of the cfg root. Cfg only.

Only keys listed in SCHEMA can be read or written, and every value is validated
against its declared type/range/options before anything touches a file.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from app.cfg_editor import _write_tree


@dataclass(frozen=True)
class Field:
    key: str
    scope: str  # "session" | "server"
    type: str  # "bool" | "int" | "float" | "enum" | "text"
    group: str
    label: str
    hint: str = ""
    min: float | None = None
    max: float | None = None
    options: tuple[str, ...] = ()


def _b(key, scope, group, label, hint=""):
    return Field(key, scope, "bool", group, label, hint)


def _i(key, scope, group, label, lo=0, hi=1_000_000_000, hint=""):
    return Field(key, scope, "int", group, label, hint, lo, hi)


def _f(key, scope, group, label, lo=0, hi=100_000, hint=""):
    return Field(key, scope, "float", group, label, hint, lo, hi)


def _e(key, scope, group, label, options, hint=""):
    return Field(key, scope, "enum", group, label, hint, options=tuple(options))


def _t(key, scope, group, label, hint=""):
    return Field(key, scope, "text", group, label, hint)


S, V = "session", "server"
G_ENV, G_PLAYER, G_COMBAT, G_ECON = "Environment", "Players", "Combat & damage", "Economy & progression"
G_MULT, G_LIMITS, G_PERF, G_TRASH, G_OPS = "Multipliers", "Limits", "Performance", "Cleanup", "Server operation"

SCHEMA: list[Field] = [
    # -- Server operation (cfg root, plus OnlineMode which is a session setting) --
    _b("PauseGameWhenEmpty", V, G_OPS, "Pause game when empty",
       "Freezes the world simulation while no players are online."),
    _e("OnlineMode", S, G_OPS, "Online mode", ["OFFLINE", "PUBLIC", "FRIENDS", "PRIVATE"]),
    _t("MessageOfTheDay", V, G_OPS, "Message of the day"),
    _t("MessageOfTheDayUrl", V, G_OPS, "Message of the day URL"),
    _b("AutoRestartEnabled", V, G_OPS, "Auto restart enabled"),
    _i("AutoRestatTimeInMin", V, G_OPS, "Auto restart every (min, 0 = off)", hi=100_000,
       hint="Keen's own spelling of the setting name."),
    _b("AutoRestartSave", V, G_OPS, "Save before auto restart"),
    _b("AutoUpdateEnabled", V, G_OPS, "Auto update enabled"),
    _i("AutoUpdateCheckIntervalInMin", V, G_OPS, "Update check interval (min)", 1, 10_000),
    _i("AutoUpdateRestartDelayInMin", V, G_OPS, "Update restart delay (min)", 0, 10_000),
    _i("WatcherInterval", V, G_OPS, "Watcher interval (s)", 1, 100_000),
    _f("WatcherSimulationSpeedMinimum", V, G_OPS, "Watcher minimum sim speed", 0, 1),
    _b("SaveChatToLog", V, G_OPS, "Save chat to log"),
    _b("ChatAntiSpamEnabled", V, G_OPS, "Chat anti-spam"),
    _i("SameMessageTimeout", V, G_OPS, "Same-message timeout (s)", 0, 3600),
    _f("SpamMessagesTime", V, G_OPS, "Spam window (s)", 0, 3600),
    _i("SpamMessagesTimeout", V, G_OPS, "Spam timeout (s)", 0, 3600),
    # -- Environment --
    _e("EnvironmentHostility", S, G_ENV, "Environment hostility", ["SAFE", "NORMAL", "CATACLYSM", "CATACLYSM_UNREAL"]),
    _b("EnableOxygen", S, G_ENV, "Oxygen"),
    _b("EnableOxygenPressurization", S, G_ENV, "Oxygen pressurization"),
    _b("WeatherSystem", S, G_ENV, "Weather"),
    _b("EnableEncounters", S, G_ENV, "Random encounters"),
    _b("EnableDrones", S, G_ENV, "Hostile drones"),
    _b("EnableWolfs", S, G_ENV, "Wolves"),
    _b("EnableSpiders", S, G_ENV, "Spiders"),
    _b("CargoShipsEnabled", S, G_ENV, "Cargo ships"),
    _b("EnableContainerDrops", S, G_ENV, "Container drops"),
    # -- Players --
    _b("PermanentDeath", S, G_PLAYER, "Permanent death"),
    _b("EnableJetpack", S, G_PLAYER, "Jetpack"),
    _b("SpawnWithTools", S, G_PLAYER, "Spawn with tools"),
    _b("EnableSpectator", S, G_PLAYER, "Spectator mode"),
    _b("Enable3rdPersonView", S, G_PLAYER, "Third-person view"),
    _b("ShowPlayerNamesOnHud", S, G_PLAYER, "Show player names on HUD"),
    _b("EnableFriendlyFire", S, G_PLAYER, "Friendly fire"),
    _b("EnableTurretsFriendlyFire", S, G_PLAYER, "Turret friendly fire"),
    _b("AutoHealing", S, G_PLAYER, "Auto healing"),
    # -- Combat & damage --
    _b("WeaponsEnabled", S, G_COMBAT, "Weapons enabled"),
    _b("InfiniteAmmo", S, G_COMBAT, "Infinite ammo"),
    _b("ThrusterDamage", S, G_COMBAT, "Thruster damage"),
    _b("DestructibleBlocks", S, G_COMBAT, "Destructible blocks"),
    _b("EnableSubgridDamage", S, G_COMBAT, "Subgrid damage"),
    _f("EnvironmentDamageMultiplier", S, G_COMBAT, "Environment damage multiplier", 0, 100),
    # -- Economy & progression --
    _b("EnableEconomy", S, G_ECON, "Economy"),
    _b("EnableResearch", S, G_ECON, "Research"),
    _b("EnableBountyContracts", S, G_ECON, "Bounty contracts"),
    _b("EnablePcuTrading", S, G_ECON, "PCU trading"),
    _f("HarvestRatioMultiplier", S, G_ECON, "Harvest ratio multiplier", 0, 100),
    _i("TradeFactionsCount", S, G_ECON, "Trade factions", 0, 1000),
    # -- Multipliers --
    _f("InventorySizeMultiplier", S, G_MULT, "Inventory size", 0.01, 1000),
    _f("AssemblerSpeedMultiplier", S, G_MULT, "Assembler speed", 0.01, 1000),
    _f("AssemblerEfficiencyMultiplier", S, G_MULT, "Assembler efficiency", 0.01, 1000),
    _f("RefinerySpeedMultiplier", S, G_MULT, "Refinery speed", 0.01, 1000),
    _f("WelderSpeedMultiplier", S, G_MULT, "Welder speed", 0.01, 1000),
    _f("GrinderSpeedMultiplier", S, G_MULT, "Grinder speed", 0.01, 1000),
    _f("HackSpeedMultiplier", S, G_MULT, "Hack speed", 0.01, 1000),
    _f("CharacterSpeedMultiplier", S, G_MULT, "Character speed", 0.01, 100),
    # -- Limits --
    _i("MaxGridSize", S, G_LIMITS, "Max grid size (blocks, 0 = off)"),
    _i("MaxBlocksPerPlayer", S, G_LIMITS, "Max blocks per player (0 = off)"),
    _e("BlockLimitsEnabled", S, G_LIMITS, "Block limits", ["NONE", "GLOBALLY", "PER_FACTION", "PER_PLAYER"]),
    _i("MaxFloatingObjects", S, G_LIMITS, "Max floating objects", 1, 10_000),
    _i("MaxProductionQueueLength", S, G_LIMITS, "Max production queue length", 1, 10_000),
    _i("MaxPlanets", S, G_LIMITS, "Max planets", 0, 1000),
    # -- Performance --
    _i("ViewDistance", S, G_PERF, "View distance (m)", 1000, 50_000),
    _i("SyncDistance", S, G_PERF, "Sync distance (m)", 1000, 20_000),
    _i("PhysicsIterations", S, G_PERF, "Physics iterations", 1, 64),
    _b("AdaptiveSimulationQuality", S, G_PERF, "Adaptive simulation quality"),
    _b("SimplifiedSimulation", S, G_PERF, "Simplified simulation"),
    _b("EnableSelectivePhysicsUpdates", S, G_PERF, "Selective physics updates"),
    # -- Cleanup --
    _b("TrashRemovalEnabled", S, G_TRASH, "Trash removal"),
    _i("BlockCountThreshold", S, G_TRASH, "Trash: block count threshold", 0, 100_000),
    _i("PlayerDistanceThreshold", S, G_TRASH, "Trash: player distance threshold (m)", 0, 100_000),
    _i("StopGridsPeriodMin", S, G_TRASH, "Stop grids period (min)", 0, 100_000),
    _i("AFKTimeountMin", S, G_TRASH, "AFK kick after (min, 0 = off)", 0, 100_000,
       hint="Keen's own spelling of the setting name."),
]

BY_KEY = {f.key: f for f in SCHEMA}
_TEXT_MAX = 500


def schema_json() -> list[dict]:
    return [
        {
            "key": f.key, "type": f.type, "group": f.group, "label": f.label, "hint": f.hint,
            "min": f.min, "max": f.max, "options": list(f.options),
        }
        for f in SCHEMA
    ]


def _element(cfg_root: ET.Element, sbc_root: ET.Element | None, field: Field):
    """Elements to read/write for a field, live copy first."""
    if field.scope == "server":
        el = cfg_root.find(field.key)
        return [el] if el is not None else []
    out = []
    if sbc_root is not None:
        el = sbc_root.find(f"Settings/{field.key}")
        if el is not None:
            out.append(el)
    el = cfg_root.find(f"SessionSettings/{field.key}")
    if el is not None:
        out.append(el)
    return out


def _parse(field: Field, text: str):
    text = (text or "").strip() if field.type != "text" else (text or "")
    if field.type == "bool":
        return text.lower() == "true"
    if field.type == "int":
        return int(float(text))
    if field.type == "float":
        return float(text)
    return text


def read_values(cfg_path: Path, sandbox_config_path: Path) -> dict:
    """{key: value} for every schema key present in this server's files."""
    cfg_root = ET.parse(cfg_path).getroot()
    sbc_root = ET.parse(sandbox_config_path).getroot() if sandbox_config_path.exists() else None
    out = {}
    for field in SCHEMA:
        elements = _element(cfg_root, sbc_root, field)
        if not elements:
            continue
        try:
            out[field.key] = _parse(field, elements[0].text or "")
        except ValueError:
            continue  # unparseable value in the file: leave it alone, don't expose it
    return out


def validate(values: dict, current: dict) -> dict:
    """Returns normalized {key: value} or raises ValueError with a readable message."""
    clean = {}
    for key, value in values.items():
        field = BY_KEY.get(key)
        if field is None:
            raise ValueError(f"'{key}' is not an editable setting.")
        if key not in current:
            raise ValueError(f"'{field.label}' isn't present in this server's config.")
        if field.type == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"{field.label}: must be on or off.")
        elif field.type in ("int", "float"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field.label}: must be a number.")
            if field.type == "int":
                if int(value) != value:
                    raise ValueError(f"{field.label}: must be a whole number.")
                value = int(value)
            else:
                value = float(value)
            if (field.min is not None and value < field.min) or (field.max is not None and value > field.max):
                raise ValueError(f"{field.label}: must be between {field.min:g} and {field.max:g}.")
        elif field.type == "enum":
            if value not in field.options and value != current.get(key):
                raise ValueError(f"{field.label}: must be one of {', '.join(field.options)}.")
        else:  # text
            if not isinstance(value, str) or len(value) > _TEXT_MAX:
                raise ValueError(f"{field.label}: text only, up to {_TEXT_MAX} characters.")
        clean[key] = value
    return clean


def _to_text(field: Field, value) -> str:
    if field.type == "bool":
        return "true" if value else "false"
    if field.type == "int":
        return str(int(value))
    if field.type == "float":
        return f"{float(value):.6g}"
    return str(value)


def write_values(cfg_path: Path, sandbox_config_path: Path, values: dict) -> None:
    """Writes already-validated values. Only touches elements that exist."""
    if not values:
        return
    cfg_tree = ET.parse(cfg_path)
    sbc_tree = ET.parse(sandbox_config_path) if sandbox_config_path.exists() else None
    sbc_root = sbc_tree.getroot() if sbc_tree is not None else None
    touched_sbc = False
    for key, value in values.items():
        field = BY_KEY[key]
        text = _to_text(field, value)
        for el in _element(cfg_tree.getroot(), sbc_root, field):
            el.text = text
        if field.scope == "session" and sbc_root is not None and sbc_root.find(f"Settings/{key}") is not None:
            touched_sbc = True
    ET.indent(cfg_tree, space="  ")
    _write_tree(cfg_tree, cfg_path)
    if touched_sbc:
        ET.indent(sbc_tree, space="  ")
        _write_tree(sbc_tree, sandbox_config_path)
