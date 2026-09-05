"""Convenience facade that wires the five layers together.

    catalog (upstream) -> custom dialect -> capabilities -> profile -> MOSA
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .capabilities import BUILTIN_CAPABILITIES, Capability, CapabilitySet
from .catalog import Catalog, load_catalog
from .customdialect import custom_message_names, load_custom_dialect
from .profile import Profile, Resolution, list_profiles, load_profile, resolve
from .project import DEFAULT_PROJECT_DIR, Project, load_project
from .store import load_yaml

CAPABILITIES_FILE = "capabilities.yaml"


def load_capability_set(project: Project) -> CapabilitySet:
    """Built-in capabilities, extended or overridden by ``uav/capabilities.yaml``."""
    path = os.path.join(project.root, CAPABILITIES_FILE)
    data = load_yaml(path)
    if not data:
        return CapabilitySet()
    capabilities = {c.key: c for c in BUILTIN_CAPABILITIES}
    for key, spec in (data.get("capabilities") or {}).items():
        spec = spec or {}
        existing = capabilities.get(key)
        capabilities[key] = Capability(
            key=key,
            title=spec.get("title", existing.title if existing else key),
            group=spec.get("group", existing.group if existing else "CUSTOM"),
            category=spec.get("category", existing.category if existing else "Custom"),
            description=spec.get("description", existing.description if existing else ""),
            messages=list(spec.get("messages", existing.messages if existing else [])),
            commands=list(spec.get("commands", existing.commands if existing else [])),
            required=bool(spec.get("required", existing.required if existing else False)),
            default=bool(spec.get("default", existing.default if existing else True)),
        )
    order = [c.key for c in BUILTIN_CAPABILITIES]
    order += [k for k in capabilities if k not in order]
    return CapabilitySet([capabilities[k] for k in order])


@dataclass
class Studio:
    project: Project
    catalog: Catalog
    capability_set: CapabilitySet
    profile: Profile
    resolution: Resolution

    @property
    def custom_names(self) -> set[str]:
        return {m.name for m in load_custom_dialect(self.project).messages}

    def reresolve(self) -> Resolution:
        self.resolution = resolve(
            self.project, self.profile, self.catalog, self.capability_set,
            custom_message_names(self.project),
        )
        return self.resolution


def default_target(project: Project) -> tuple[str, str]:
    """Pick a (vehicle, profile) when the user did not name one.

    Declaration order in ``project.yaml`` wins over filename order, so the
    first profile a vehicle lists is the one you get by default.
    """
    existing = list_profiles(project)
    for vehicle in project.vehicles.values():
        for profile_name in vehicle.profiles:
            if (vehicle.name, profile_name) in existing:
                return vehicle.name, profile_name
    if existing:
        return existing[0]
    if project.vehicles:
        vehicle = next(iter(project.vehicles.values()))
        return vehicle.name, (vehicle.profiles or ["flight"])[0]
    return "UAV", "flight"


def open_studio(root: str = DEFAULT_PROJECT_DIR, vehicle: str = "",
                profile_name: str = "") -> Studio:
    project = load_project(root)
    catalog = load_catalog(project.definitions_dir)
    capability_set = load_capability_set(project)
    if not vehicle or not profile_name:
        default_vehicle, default_profile = default_target(project)
        vehicle = vehicle or default_vehicle
        profile_name = profile_name or default_profile
    profile = load_profile(project, vehicle, profile_name)
    resolution = resolve(
        project, profile, catalog, capability_set, custom_message_names(project)
    )
    return Studio(project, catalog, capability_set, profile, resolution)
