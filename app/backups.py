"""List and restore world backups.

Confirmed by inspecting a real backup folder: each one is a flat mirror of the
world's save directory (Sandbox.sbc, Sandbox_config.sbc, SANDBOX_0_0_0_.sbs(B5),
all .vx2 voxel files, thumb.jpg) -- no nested Backup/ subfolder of its own.

Restore overlays the chosen backup's files onto the live world folder
(overwriting anything with the same name) without deleting anything the live
folder has that the backup doesn't -- e.g. newer voxel files a since-removed
asteroid left behind. That's a deliberate conservative choice: a restore
should never delete data it doesn't have to.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app import docker_control
from app.instances import Instance


@dataclass
class BackupEntry:
    name: str
    path: Path
    modified: datetime


def list_backups(instance: Instance) -> list[BackupEntry]:
    if not instance.backup_path.is_dir():
        return []
    entries = [
        BackupEntry(
            name=child.name,
            path=child,
            modified=datetime.fromtimestamp(child.stat().st_mtime),
        )
        for child in instance.backup_path.iterdir()
        if child.is_dir()
    ]
    return sorted(entries, key=lambda e: e.modified, reverse=True)


def restore_backup(instance: Instance, backup_name: str) -> None:
    backup_dir = instance.backup_path / backup_name
    if not backup_dir.is_dir():
        raise FileNotFoundError(f"Backup '{backup_name}' not found for {instance.name}")

    docker_control.stop(instance.container_name)
    try:
        shutil.copytree(backup_dir, instance.world_path, dirs_exist_ok=True)
    finally:
        docker_control.start(instance.container_name)
