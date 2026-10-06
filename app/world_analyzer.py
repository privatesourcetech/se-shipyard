"""World analyzer: read-only statistics about a saved Space Engineers world.

Works on the files on disk, so the server can be offline. Parses the world's
sector file (SANDBOX_0_0_0_.sbs, often 100 MB+ of XML) in a separate low-priority
process so a big world can't stall the web app or starve the game servers.

Run as a module by app/routes/api.py:  python -m app.world_analyzer <sbs> <out.json> <progress.json>
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"
PREFIX = "MyObjectBuilder_"

# Category -> block type names (after stripping the MyObjectBuilder_ prefix).
CATEGORIES: dict[str, set[str]] = {
    "Thrusters": {"Thrust"},
    "Gyros": {"Gyro"},
    "Wheels & suspension": {"Wheel", "MotorSuspension"},
    "Rotors & hinges": {"MotorStator", "MotorAdvancedStator"},
    "Pistons": {"PistonBase", "ExtendedPistonBase"},
    "Turrets & weapons": {
        "LargeGatlingTurret", "LargeMissileTurret", "InteriorTurret", "SmallGatlingGun",
        "SmallMissileLauncher", "SmallMissileLauncherReload", "UserControllableGun",
    },
    "Timers": {"TimerBlock"},
    "Programmable blocks": {"ProgrammableBlock"},
    "Batteries": {"BatteryBlock"},
    "Reactors & engines": {"Reactor", "HydrogenEngine"},
    "Solar & wind": {"SolarPanel", "WindTurbine"},
    "Conveyors & sorters": {"Conveyor", "ConveyorConnector", "ConveyorSorter"},
    "Production": {"Assembler", "Refinery", "SurvivalKit"},
    "Drills, welders, grinders": {"ShipDrill", "ShipWelder", "ShipGrinder"},
    "Doors": {"Door", "AirtightHangarDoor", "AirtightSlideDoor", "AdvancedDoor"},
    "Life support": {"OxygenGenerator", "OxygenTank", "OxygenFarm", "AirVent"},
    "Screens": {"TextPanel", "LCDPanelsBlock"},
    "Lights": {"InteriorLight", "ReflectorLight"},
    "Seats & cryo": {"Cockpit", "CryoChamber"},
    "Landing gear": {"LandingGear"},
    "Jump drives": {"JumpDrive"},
    "Projectors": {"Projector"},
    "Sensors & cameras": {"SensorBlock", "Camera"},
    "Antennas & beacons": {"RadioAntenna", "LaserAntenna", "BeaconBlock"},
    "Warheads": {"Warhead"},
    "Armor & structure": {"CubeBlock"},
}
_TYPE_TO_CAT = {t: cat for cat, types in CATEGORIES.items() for t in types}

# Per-grid columns shown in the table (category -> short key).
GRID_COLUMNS = {
    "Thrusters": "thrusters",
    "Gyros": "gyros",
    "Wheels & suspension": "wheels",
    "Rotors & hinges": "rotors",
    "Pistons": "pistons",
    "Turrets & weapons": "turrets",
    "Timers": "timers",
    "Programmable blocks": "pbs",
    "Batteries": "batteries",
}

MAX_GRIDS_KEPT = 300


def _write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


class _Counting:
    """File wrapper that reports how many bytes have been consumed (for progress)."""

    def __init__(self, f, total: int, progress_path: Path):
        self.f, self.total, self.progress_path = f, total, progress_path
        self.read_bytes = 0
        self._last = 0.0

    def read(self, n=-1):
        data = self.f.read(n)
        self.read_bytes += len(data)
        now = time.monotonic()
        if now - self._last > 0.7:
            self._last = now
            _write_json(self.progress_path, {"bytes": self.read_bytes, "total": self.total})
        return data


def analyze(sbs_path: Path, progress_path: Path) -> dict:
    total = sbs_path.stat().st_size
    started = time.time()
    entities: Counter = Counter()
    categories: Counter = Counter()
    type_counts: Counter = Counter()
    grids: list[dict] = []
    totals = Counter()

    with open(sbs_path, "rb") as raw:
        wrapped = _Counting(raw, total, progress_path)
        for _, el in ET.iterparse(wrapped, events=("end",)):
            if el.tag != "MyObjectBuilder_EntityBase":
                continue
            etype = (el.get(XSI) or "?").removeprefix(PREFIX)
            entities[etype] += 1
            if etype == "CubeGrid":
                blocks_el = el.find("CubeBlocks")
                per_cat: Counter = Counter()
                n = 0
                if blocks_el is not None:
                    for b in blocks_el:
                        t = (b.get(XSI) or "?").removeprefix(PREFIX)
                        n += 1
                        type_counts[t] += 1
                        per_cat[_TYPE_TO_CAT.get(t, "Other")] += 1
                categories.update(per_cat)
                is_static = (el.findtext("IsStatic") or "false").strip().lower() == "true"
                size = (el.findtext("GridSizeEnum") or "?").strip()
                pos = el.find("PositionAndOrientation/Position")
                dist_km = None
                if pos is not None:
                    try:
                        x, y, z = (float(pos.get(a, 0)) for a in "xyz")
                        dist_km = round(math.sqrt(x * x + y * y + z * z) / 1000, 1)
                    except ValueError:
                        pass
                totals["grids"] += 1
                totals["blocks"] += n
                totals["static_grids" if is_static else "dynamic_grids"] += 1
                totals["large_grids" if size == "Large" else "small_grids"] += 1
                totals["static_blocks" if is_static else "dynamic_blocks"] += n
                grid = {
                    "name": (el.findtext("DisplayName") or "Unnamed grid")[:60],
                    "size": size,
                    "static": is_static,
                    "blocks": n,
                    "dist_km": dist_km,
                }
                for cat, key in GRID_COLUMNS.items():
                    grid[key] = per_cat.get(cat, 0)
                grids.append(grid)
            el.clear()

    grids.sort(key=lambda g: -g["blocks"])
    top_n = sum(g["blocks"] for g in grids[:5])
    return {
        "file_bytes": total,
        "entities": dict(entities),
        "totals": {
            "grids": totals["grids"], "blocks": totals["blocks"],
            "large_grids": totals["large_grids"], "small_grids": totals["small_grids"],
            "static_grids": totals["static_grids"], "dynamic_grids": totals["dynamic_grids"],
            "static_blocks": totals["static_blocks"], "dynamic_blocks": totals["dynamic_blocks"],
            "planets": entities.get("Planet", 0), "voxel_maps": entities.get("VoxelMap", 0),
            "characters": entities.get("Character", 0), "floating_objects": entities.get("FloatingObject", 0),
            "safe_zones": entities.get("SafeZone", 0),
            "top5_blocks": top_n,
            "tiny_grids": sum(1 for g in grids if g["blocks"] < 20),
        },
        "categories": [{"name": k, "count": v} for k, v in categories.most_common()],
        "block_types": [{"name": k, "count": v} for k, v in type_counts.most_common(25)],
        "grids": grids[:MAX_GRIDS_KEPT],
        "grids_total": len(grids),
        "duration_s": round(time.time() - started, 1),
    }


def main(argv: list[str]) -> int:
    sbs, out, progress = Path(argv[1]), Path(argv[2]), Path(argv[3])
    try:
        os.nice(15)  # never compete with the game servers for CPU
    except OSError:
        pass
    try:
        result = analyze(sbs, progress)
        result["analyzed_at"] = time.time()
        result["source_mtime"] = sbs.stat().st_mtime
        _write_json(out, result)
        return 0
    except Exception as exc:  # noqa: BLE001
        _write_json(out, {"error": f"{type(exc).__name__}: {exc}", "analyzed_at": time.time()})
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
