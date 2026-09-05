"""Layer 2/4 -- the UAV project: custom dialect settings, vehicles and profiles.

Everything the studio owns lives under ``uav/`` except the custom dialect XML
itself, which stays in ``message_definitions/v1.0/`` so that ``<include>``
resolution and ``mavgen`` work exactly as they do for any upstream dialect.

    uav/project.yaml                 project + dialect + id-space settings
    uav/profiles/<vehicle>.<profile>.yaml
    uav/interfaces/<interface>.yaml  MOSA interface contracts
    uav/modules/<module>.yaml        MOSA module manifests
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field as dc_field

from .store import load_yaml, save_yaml, slug

DEFAULT_PROJECT_DIR = "uav"
PROJECT_FILE = "project.yaml"

# 42000/42001 are already taken by icarous.xml, and 50000-52699 by cubepilot,
# csAirLink, marsh and stemstudios. 52700-52799 is free in upstream today.
DEFAULT_MESSAGE_ID_RANGE = (52700, 52799)
DEFAULT_COMMAND_ID_RANGE = (52700, 52799)


@dataclass
class DialectSettings:
    name: str = "my_uav"
    path: str = os.path.join("message_definitions", "v1.0", "my_uav.xml")
    base: str = "common.xml"
    dialect_number: str = "100"
    version: str = "3"
    namespace: str = "MY_UAV"


@dataclass
class IdSpace:
    messages: tuple[int, int] = DEFAULT_MESSAGE_ID_RANGE
    commands: tuple[int, int] = DEFAULT_COMMAND_ID_RANGE


@dataclass
class Vehicle:
    name: str
    description: str = ""
    profiles: list[str] = dc_field(default_factory=lambda: ["flight"])


@dataclass
class Project:
    root: str = DEFAULT_PROJECT_DIR
    name: str = "UAV Interface Project"
    description: str = ""
    definitions_dir: str = os.path.join("message_definitions", "v1.0")
    dialect: DialectSettings = dc_field(default_factory=DialectSettings)
    id_space: IdSpace = dc_field(default_factory=IdSpace)
    vehicles: dict[str, Vehicle] = dc_field(default_factory=dict)
    build_dir: str = os.path.join("build", "mavstudio")

    # -- paths ------------------------------------------------------------

    @property
    def path(self) -> str:
        return os.path.join(self.root, PROJECT_FILE)

    @property
    def profiles_dir(self) -> str:
        return os.path.join(self.root, "profiles")

    @property
    def interfaces_dir(self) -> str:
        return os.path.join(self.root, "interfaces")

    @property
    def modules_dir(self) -> str:
        return os.path.join(self.root, "modules")

    def profile_path(self, vehicle: str, profile: str) -> str:
        return os.path.join(self.profiles_dir, f"{slug(vehicle)}.{slug(profile)}.yaml")

    # -- serialisation ----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "definitions_dir": self.definitions_dir,
            "build_dir": self.build_dir,
            "dialect": {
                "name": self.dialect.name,
                "path": self.dialect.path,
                "base": self.dialect.base,
                "dialect_number": self.dialect.dialect_number,
                "version": self.dialect.version,
                "namespace": self.dialect.namespace,
            },
            "id_space": {
                "messages": list(self.id_space.messages),
                "commands": list(self.id_space.commands),
            },
            "vehicles": {
                name: {
                    "description": vehicle.description,
                    "profiles": vehicle.profiles,
                }
                for name, vehicle in self.vehicles.items()
            },
        }

    def save(self) -> None:
        save_yaml(self.path, self.to_dict())


def load_project(root: str = DEFAULT_PROJECT_DIR) -> Project:
    """Load ``<root>/project.yaml``, falling back to defaults when absent."""
    project = Project(root=root)
    data = load_yaml(os.path.join(root, PROJECT_FILE))
    if not data:
        return project
    project.name = data.get("name", project.name)
    project.description = data.get("description", "")
    project.definitions_dir = data.get("definitions_dir", project.definitions_dir)
    project.build_dir = data.get("build_dir", project.build_dir)

    dialect = data.get("dialect", {})
    project.dialect = DialectSettings(
        name=dialect.get("name", "my_uav"),
        path=dialect.get(
            "path", os.path.join("message_definitions", "v1.0", "my_uav.xml")
        ),
        base=dialect.get("base", "common.xml"),
        dialect_number=str(dialect.get("dialect_number", "100")),
        version=str(dialect.get("version", "3")),
        namespace=dialect.get("namespace", "MY_UAV"),
    )

    id_space = data.get("id_space", {})
    messages = id_space.get("messages", list(DEFAULT_MESSAGE_ID_RANGE))
    commands = id_space.get("commands", list(DEFAULT_COMMAND_ID_RANGE))
    project.id_space = IdSpace(
        messages=(int(messages[0]), int(messages[1])),
        commands=(int(commands[0]), int(commands[1])),
    )

    for name, vehicle in (data.get("vehicles") or {}).items():
        vehicle = vehicle or {}
        project.vehicles[name] = Vehicle(
            name=name,
            description=vehicle.get("description", ""),
            profiles=list(vehicle.get("profiles") or ["flight"]),
        )
    return project
