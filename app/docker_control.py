"""Docker control for configured SE instance containers only.

Talks to the host's Docker daemon over the socket mounted into this container
(see compose.yaml: /var/run/docker.sock). Every function takes a container name
that must match an entry in the instance registry -- this module never lists or
touches containers outside that set.
"""

from __future__ import annotations

import docker
from docker.errors import NotFound

_client: docker.DockerClient | None = None


def _get_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def get_status(container_name: str) -> str:
    """Returns 'running', 'exited', 'restarting', etc., or 'not_found'."""
    try:
        container = _get_client().containers.get(container_name)
        return container.status
    except NotFound:
        return "not_found"


def start(container_name: str) -> None:
    _get_client().containers.get(container_name).start()


def stop(container_name: str, timeout: int = 30) -> None:
    _get_client().containers.get(container_name).stop(timeout=timeout)


def restart(container_name: str, timeout: int = 30) -> None:
    _get_client().containers.get(container_name).restart(timeout=timeout)


def get_logs(container_name: str, tail: int = 200) -> str:
    container = _get_client().containers.get(container_name)
    return container.logs(tail=tail).decode("utf-8", errors="replace")


def get_info(container_name: str) -> dict:
    """Status, health, start time and (when running) CPU/memory for one container."""
    info = {"status": "not_found", "health": None, "started_at": None, "cpu": 0.0, "mem_gb": 0.0}
    try:
        container = _get_client().containers.get(container_name)
    except NotFound:
        return info
    state = container.attrs.get("State", {})
    info["status"] = container.status
    info["health"] = (state.get("Health") or {}).get("Status")
    info["started_at"] = state.get("StartedAt")
    if container.status == "running":
        try:
            stats = container.stats(stream=False)
            cpu = stats["cpu_stats"]
            pre = stats["precpu_stats"]
            cpu_delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
            sys_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
            ncpu = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or [1])
            if sys_delta > 0 and cpu_delta >= 0:
                info["cpu"] = round(cpu_delta / sys_delta * ncpu * 100, 1)
            mem = stats["memory_stats"]
            used = mem.get("usage", 0) - mem.get("stats", {}).get("inactive_file", 0)
            info["mem_gb"] = round(max(used, 0) / 1024**3, 1)
        except Exception:  # noqa: BLE001 - stats are decoration, never fail the page
            pass
    return info
