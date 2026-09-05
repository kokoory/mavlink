"""Data model for MAVLink XML definitions.

The model mirrors the XML closely enough that a parsed message can be written
back out unchanged, which is what lets ``mavmsg build`` copy standard messages
into a generated dialect verbatim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

# Wire size in bytes of every scalar type MAVLink allows in a field.
TYPE_SIZES = {
    "char": 1,
    "int8_t": 1,
    "uint8_t": 1,
    "uint8_t_mavlink_version": 1,
    "int16_t": 2,
    "uint16_t": 2,
    "int32_t": 4,
    "uint32_t": 4,
    "int64_t": 8,
    "uint64_t": 8,
    "float": 4,
    "double": 8,
}

# The largest payload MAVLink 2 can carry.
MAX_PAYLOAD_BYTES = 255

ARRAY_RE = re.compile(r"^(?P<base>[a-z0-9_]+)\[(?P<count>\d+)\]$")
MESSAGE_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def split_type(type_str: str) -> tuple[str, int]:
    """Split ``uint16_t[4]`` into ``("uint16_t", 4)``; scalars get count 1."""
    match = ARRAY_RE.match(type_str)
    if match:
        return match.group("base"), int(match.group("count"))
    return type_str, 1


def type_size(type_str: str) -> int:
    """Wire size in bytes of a field type, or 0 if the base type is unknown."""
    base, count = split_type(type_str)
    return TYPE_SIZES.get(base, 0) * count


@dataclass
class Field:
    name: str
    type: str
    description: str = ""
    units: str = ""
    enum: str = ""
    display: str = ""
    increment: str = ""
    minValue: str = ""  # noqa: N815 - mirrors the XML attribute name
    maxValue: str = ""  # noqa: N815 - mirrors the XML attribute name
    invalid: str = ""
    instance: str = ""
    print_format: str = ""
    multiplier: str = ""
    default: str = ""
    is_extension: bool = False

    @property
    def size(self) -> int:
        return type_size(self.type)

    @property
    def base_type(self) -> str:
        return split_type(self.type)[0]

    @property
    def array_length(self) -> int:
        return split_type(self.type)[1]


@dataclass
class Param:
    """A ``<param>`` of a MAV_CMD enum entry."""

    index: int
    description: str = ""
    label: str = ""
    units: str = ""
    enum: str = ""
    increment: str = ""
    minValue: str = ""  # noqa: N815 - mirrors the XML attribute name
    maxValue: str = ""  # noqa: N815 - mirrors the XML attribute name
    reserved: str = ""
    default: str = ""


@dataclass
class Message:
    id: int
    name: str
    description: str = ""
    fields: list[Field] = dc_field(default_factory=list)
    dialect: str = ""
    deprecated: tuple[str, str, str] | None = None  # (since, replaced_by, text)
    #: Softer than deprecated: still valid, but a better message exists.
    superseded: tuple[str, str, str] | None = None
    wip: bool = False
    source_line: int = 0

    @property
    def payload_bytes(self) -> int:
        return sum(f.size for f in self.fields)

    @property
    def enum_refs(self) -> set[str]:
        return {f.enum for f in self.fields if f.enum}

    @property
    def has_extensions(self) -> bool:
        return any(f.is_extension for f in self.fields)


@dataclass
class EnumEntry:
    name: str
    value: str = ""
    description: str = ""
    params: list[Param] = dc_field(default_factory=list)
    deprecated: tuple[str, str, str] | None = None
    superseded: tuple[str, str, str] | None = None
    wip: bool = False
    hasLocation: str = ""  # noqa: N815 - mirrors the XML attribute name
    isDestination: str = ""  # noqa: N815 - mirrors the XML attribute name
    missionOnly: str = ""  # noqa: N815 - mirrors the XML attribute name

    @property
    def enum_refs(self) -> set[str]:
        return {p.enum for p in self.params if p.enum}


@dataclass
class Enum:
    name: str
    description: str = ""
    bitmask: bool = False
    entries: list[EnumEntry] = dc_field(default_factory=list)
    dialect: str = ""
    deprecated: tuple[str, str, str] | None = None
    superseded: tuple[str, str, str] | None = None

    def entry(self, name: str) -> EnumEntry | None:
        for e in self.entries:
            if e.name == name:
                return e
        return None


@dataclass
class Dialect:
    """One parsed ``message_definitions/v1.0/<name>.xml`` file."""

    name: str
    path: str
    includes: list[str] = dc_field(default_factory=list)
    version: str = ""
    dialect_number: str = ""
    messages: list[Message] = dc_field(default_factory=list)
    enums: list[Enum] = dc_field(default_factory=list)
