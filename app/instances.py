"""Instance registry: the list of SE dedicated server instances SE Shipyard knows about.

Persisted as YAML on SE Shipyard's own data volume. Each instance's dataset and backup
folder must already be bind-mounted into this container (see compose.yaml) at the paths
recorded here -- adding a new instance means adding those two mounts and redeploying,
then registering it here through the UI.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel

DATA_DIR = Path(os.environ.get("SE_SHIPYARD_DATA_DIR", "/app/data"))
REGISTRY_PATH = DATA_DIR / "instances.yaml"


class Instance(BaseModel):
    name: str
    container_name: str
    dataset_mount: str  # bind-mounted root of <dataset>/server, e.g. /mnt/instances/plateau
    instance_dir: str  # INSTANCE_NAME subfolder under dataset_mount, e.g. "Plateau"
    world_folder: str  # world name under Saves/, matches <WorldName> in the cfg
    backup_mount: str  # bind-mounted Backup folder for this world, e.g. /mnt/backups/plateau

    @property
    def cfg_path(self) -> Path:
        return Path(self.dataset_mount) / self.instance_dir / "SpaceEngineers-Dedicated.cfg"

    @property
    def world_path(self) -> Path:
        return Path(self.dataset_mount) / self.instance_dir / "Saves" / self.world_folder

    @property
    def sandbox_sbc_path(self) -> Path:
        return self.world_path / "Sandbox.sbc"

    @property
    def sandbox_config_path(self) -> Path:
        """Live, continuously-autosaved settings + mods -- see cfg_editor.py docstring."""
        return self.world_path / "Sandbox_config.sbc"

    @property
    def backup_path(self) -> Path:
        return Path(self.backup_mount)


def load_instances() -> list[Instance]:
    if not REGISTRY_PATH.exists():
        return []
    raw = yaml.safe_load(REGISTRY_PATH.read_text()) or []
    return [Instance(**item) for item in raw]


def save_instances(instances: list[Instance]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = [instance.model_dump() for instance in instances]
    REGISTRY_PATH.write_text(yaml.safe_dump(raw, sort_keys=False))


def get_instance(name: str) -> Instance | None:
    for instance in load_instances():
        if instance.name == name:
            return instance
    return None


def add_instance(instance: Instance) -> None:
    instances = load_instances()
    if any(i.name == instance.name for i in instances):
        raise ValueError(f"Instance '{instance.name}' already exists")
    instances.append(instance)
    save_instances(instances)


def update_instance(name: str, instance: Instance) -> None:
    instances = load_instances()
    for i, existing in enumerate(instances):
        if existing.name == name:
            instances[i] = instance
            save_instances(instances)
            return
    raise ValueError(f"Instance '{name}' not found")


def remove_instance(name: str) -> None:
    instances = [i for i in load_instances() if i.name != name]
    save_instances(instances)
