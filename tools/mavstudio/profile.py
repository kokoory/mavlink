"""Layer 4 -- UAV profiles and the enable/disable resolution engine.

A profile never deletes anything. It records, per vehicle configuration, which
capabilities are on, which individual messages deviate from their capability
default, and the direction / rate / priority metadata that drives the bandwidth
budget and the ICD.

Resolution order, lowest precedence first:

1. capability default (from :mod:`.capabilities`)
2. capability toggle in the profile
3. explicit per-message override in the profile
4. hard rules -- required capabilities and custom-dialect messages stay on
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field as dc_field

from .capabilities import CapabilitySet
from .catalog import Catalog
from .project import Project
from .store import load_yaml, save_yaml

PRIORITIES = ("LOW", "NORMAL", "HIGH", "CRITICAL")

#: Messages that must stay enabled for a MAVLink system to work at all.
ALWAYS_REQUIRED = {"HEARTBEAT"}


@dataclass
class LinkSettings:
    name: str = "Primary telemetry link"
    bitrate: int = 115200
    mavlink_version: int = 2
    signing: bool = False
    #: Fraction of the link reserved for retries, bursts and non-periodic traffic.
    headroom: float = 0.2


@dataclass
class MessageOverride:
    enabled: bool | None = None
    tx: list[str] = dc_field(default_factory=list)
    rx: list[str] = dc_field(default_factory=list)
    rate_hz: float = 0.0
    priority: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        data: dict = {}
        if self.enabled is not None:
            data["enabled"] = self.enabled
        if self.tx:
            data["tx"] = self.tx
        if self.rx:
            data["rx"] = self.rx
        if self.rate_hz:
            data["rate_hz"] = self.rate_hz
        if self.priority:
            data["priority"] = self.priority
        if self.note:
            data["note"] = self.note
        return data

    @classmethod
    def from_dict(cls, data) -> MessageOverride:
        # A bare boolean is accepted as shorthand for {enabled: <bool>}.
        if isinstance(data, bool):
            return cls(enabled=data)
        data = data or {}
        return cls(
            enabled=data.get("enabled"),
            tx=list(data.get("tx") or []),
            rx=list(data.get("rx") or []),
            rate_hz=float(data.get("rate_hz") or 0),
            priority=str(data.get("priority") or ""),
            note=str(data.get("note") or ""),
        )


@dataclass
class Profile:
    vehicle: str
    name: str
    description: str = ""
    link: LinkSettings = dc_field(default_factory=LinkSettings)
    capabilities: dict[str, bool] = dc_field(default_factory=dict)
    messages: dict[str, MessageOverride] = dc_field(default_factory=dict)
    commands: dict[str, bool] = dc_field(default_factory=dict)
    #: Component names participating in this configuration (FC, GCS, Motor, ...).
    components: list[str] = dc_field(default_factory=lambda: ["FC", "GCS"])
    #: MOSA interface contracts this configuration claims to implement.
    interfaces: list[str] = dc_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "vehicle": self.vehicle,
            "profile": self.name,
            "description": self.description,
            "components": self.components,
            "interfaces": self.interfaces,
            "link": {
                "name": self.link.name,
                "bitrate": self.link.bitrate,
                "mavlink_version": self.link.mavlink_version,
                "signing": self.link.signing,
                "headroom": self.link.headroom,
            },
            "capabilities": dict(sorted(self.capabilities.items())),
            "messages": {
                name: override.to_dict()
                for name, override in sorted(self.messages.items())
                if override.to_dict()
            },
            "commands": dict(sorted(self.commands.items())),
        }

    def save(self, project: Project) -> str:
        path = project.profile_path(self.vehicle, self.name)
        save_yaml(path, self.to_dict())
        return path


def load_profile(project: Project, vehicle: str, name: str) -> Profile:
    path = project.profile_path(vehicle, name)
    data = load_yaml(path)
    profile = Profile(vehicle=vehicle, name=name)
    if not data:
        return profile
    profile.description = data.get("description", "")
    profile.components = list(data.get("components") or ["FC", "GCS"])
    profile.interfaces = list(data.get("interfaces") or [])
    link = data.get("link") or {}
    profile.link = LinkSettings(
        name=link.get("name", "Primary telemetry link"),
        bitrate=int(link.get("bitrate", 115200)),
        mavlink_version=int(link.get("mavlink_version", 2)),
        signing=bool(link.get("signing", False)),
        headroom=float(link.get("headroom", 0.2)),
    )
    profile.capabilities = {k: bool(v) for k, v in (data.get("capabilities") or {}).items()}
    profile.messages = {
        name: MessageOverride.from_dict(value)
        for name, value in (data.get("messages") or {}).items()
    }
    profile.commands = {k: bool(v) for k, v in (data.get("commands") or {}).items()}
    return profile


def list_profiles(project: Project) -> list[tuple[str, str]]:
    """All (vehicle, profile) pairs that have a file on disk."""
    directory = project.profiles_dir
    if not os.path.isdir(directory):
        return []
    found = []
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith(".yaml"):
            continue
        data = load_yaml(os.path.join(directory, entry))
        if data.get("vehicle") and data.get("profile"):
            found.append((data["vehicle"], data["profile"]))
    return found


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


@dataclass
class MessageState:
    """The fully resolved state of one message under one profile."""

    name: str
    id: int
    dialect: str
    origin: str  # "standard" | "custom"
    enabled: bool
    reason: str
    capability: str
    capability_title: str
    category: str
    status: str  # standard | custom | experimental | deprecated | conflict
    payload_bytes: int
    tx: list[str] = dc_field(default_factory=list)
    rx: list[str] = dc_field(default_factory=list)
    rate_hz: float = 0.0
    priority: str = "NORMAL"
    required: bool = False
    deletable: bool = False
    note: str = ""


@dataclass
class Resolution:
    project: Project
    profile: Profile
    states: dict[str, MessageState]
    capability_states: dict[str, bool]
    command_states: dict[str, bool]

    def enabled_messages(self) -> list[MessageState]:
        return sorted(
            (s for s in self.states.values() if s.enabled), key=lambda s: s.id
        )

    def disabled_messages(self) -> list[MessageState]:
        return sorted(
            (s for s in self.states.values() if not s.enabled), key=lambda s: s.id
        )

    def enabled_commands(self) -> list[str]:
        return sorted(name for name, on in self.command_states.items() if on)


def resolve(
    project: Project,
    profile: Profile,
    catalog: Catalog,
    capability_set: CapabilitySet,
    custom_message_names: set[str] | None = None,
) -> Resolution:
    """Compute the effective message/command set for a profile."""
    custom_message_names = custom_message_names or set()

    # 1 + 2: capability states.
    capability_states: dict[str, bool] = {}
    for capability in capability_set.capabilities:
        if capability.required:
            capability_states[capability.key] = True
        else:
            capability_states[capability.key] = bool(
                profile.capabilities.get(capability.key, capability.default)
            )

    # Map every message to the capabilities that claim it.
    enabled_by_capability: dict[str, str] = {}
    disabled_by_capability: dict[str, str] = {}
    for capability in capability_set.capabilities:
        owned = capability_set.messages_for(capability.key, catalog)
        if capability_states[capability.key]:
            for name in owned:
                enabled_by_capability.setdefault(name, capability.key)
        else:
            for name in owned:
                disabled_by_capability.setdefault(name, capability.key)

    states: dict[str, MessageState] = {}
    for name, entry in catalog.messages.items():
        message = entry.message
        owner = capability_set.owner_of_message(name)
        capability_key = owner.key if owner else ""
        is_custom = name in custom_message_names

        if capability_key and capability_states.get(capability_key) is not None:
            enabled = capability_states[capability_key]
            reason = (
                f"capability '{capability_key}' on"
                if enabled
                else f"capability '{capability_key}' off"
            )
        elif name in enabled_by_capability:
            enabled = True
            reason = f"capability '{enabled_by_capability[name]}' on"
        else:
            # No capability claims it (vendor dialect message): off unless the
            # profile explicitly asks for it, or it is one of ours.
            enabled = is_custom
            reason = "custom dialect message" if is_custom else "no capability claims it"

        override = profile.messages.get(name)
        if override and override.enabled is not None:
            enabled = override.enabled
            reason = "explicit override in profile"

        required = name in ALWAYS_REQUIRED or (
            owner is not None and owner.required
        )
        if required and not enabled:
            enabled = True
            reason = "required -- cannot be disabled"

        if is_custom and override is None:
            enabled = True

        status = "custom" if is_custom else entry.status
        if len(catalog.id_owners.get(message.id, [])) > 1:
            status = "conflict"

        states[name] = MessageState(
            name=name,
            id=message.id,
            dialect=entry.dialect,
            origin="custom" if is_custom else "standard",
            enabled=enabled,
            reason=reason,
            capability=capability_key,
            capability_title=owner.title if owner else "",
            category=owner.category if owner else "Uncategorised",
            status=status,
            payload_bytes=message.payload_bytes,
            tx=list(override.tx) if override else [],
            rx=list(override.rx) if override else [],
            rate_hz=override.rate_hz if override else 0.0,
            priority=(override.priority if override and override.priority else "NORMAL"),
            required=required,
            deletable=is_custom,
            note=override.note if override else "",
        )

    # Commands follow the same precedence, capability then explicit override.
    command_states: dict[str, bool] = {}
    for capability in capability_set.capabilities:
        for command in capability_set.commands_for(capability.key, catalog):
            command_states[command] = (
                command_states.get(command, False) or capability_states[capability.key]
            )
    for command in catalog.commands:
        command_states.setdefault(command, True)
    for command, value in profile.commands.items():
        command_states[command] = value

    return Resolution(
        project=project,
        profile=profile,
        states=states,
        capability_states=capability_states,
        command_states=command_states,
    )
