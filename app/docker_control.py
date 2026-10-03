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
