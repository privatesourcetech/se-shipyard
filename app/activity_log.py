"""Best-effort activity view parsed from `docker logs <container>`.

This is NOT an authoritative player list -- there is no working live API (see
the plan's Remote API finding). It's a read-only approximation: recent log
lines, with the patterns we've actually observed on a real running instance
highlighted. We have only confirmed join-side patterns so far (a client
connecting and its world load completing); we have not yet observed a
disconnect or chat-message line in the wild, so this does not claim to detect
those -- extend the patterns below once real examples are seen, rather than
guessing at a format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app import docker_control

_TIMESTAMP_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+): (?P<rest>.*)$")

_PATTERNS = [
    ("join_attempt", re.compile(r"^OnConnectedClient (?P<name>.+) attempt$")),
    ("world_loaded", re.compile(r"^World request received: (?P<name>.+)$")),
    ("autosave", re.compile(r"^Autosave$")),
]


@dataclass
class ActivityEvent:
    timestamp: str | None
    category: str  # one of the _PATTERNS labels, or "raw" for anything unrecognized
    raw_line: str
    player_name: str | None = None


def _parse_line(line: str) -> ActivityEvent:
    ts = None
    rest = line
    m = _TIMESTAMP_RE.match(line)
    if m:
        ts = m.group("ts")
        rest = m.group("rest")

    for category, pattern in _PATTERNS:
        pm = pattern.match(rest)
        if pm:
            groups = pm.groupdict()
            return ActivityEvent(
                timestamp=ts,
                category=category,
                raw_line=line,
                player_name=groups.get("name"),
            )

    return ActivityEvent(timestamp=ts, category="raw", raw_line=line)


def recent_activity(container_name: str, tail: int = 200) -> list[ActivityEvent]:
    raw = docker_control.get_logs(container_name, tail=tail)
    return [_parse_line(line) for line in raw.splitlines() if line.strip()]
