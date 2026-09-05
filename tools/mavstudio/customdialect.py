"""Layer 2 -- the custom dialect.

Everything the user adds lives in one real MAVLink dialect file that
``<include>``s the upstream base. Upstream XML is never touched, so pulling a
new MAVLink release is an ordinary fast-forward.

This module owns creation, editing and deletion of custom messages, enums and
commands, plus the id-space bookkeeping that keeps them collision-free.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .catalog import Catalog, load_catalog
from .model import (
    FIELD_NAME_RE,
    MAX_PAYLOAD_BYTES,
    MESSAGE_NAME_RE,
    TYPE_SIZES,
    Enum,
    EnumEntry,
    Field,
    Message,
    Param,
    split_type,
)
from .parser import dialect_xml, parse_file, write_xml
from .project import Project
from .store import load_yaml, save_yaml

METADATA_FILE = "message_meta.yaml"

HEADER_COMMENT = (
    "Custom dialect generated and maintained by tools/mavstudio.\n"
    "Upstream definitions are never modified; this file only adds.\n"
    "Message and command ids must stay inside the project id_space."
)


class DialectError(Exception):
    """Raised for any edit that would produce an invalid or colliding dialect."""


@dataclass
class IdCheck:
    id: int
    available: bool
    in_range: bool
    collisions: list[tuple[str, str]]  # (dialect, message name)

    @property
    def ok(self) -> bool:
        return self.available and self.in_range


# --------------------------------------------------------------------------
# Loading / creating
# --------------------------------------------------------------------------


def load_custom_dialect(project: Project):
    """Parse the custom dialect, returning an empty one if it does not exist."""
    from .model import Dialect

    path = project.dialect.path
    if os.path.exists(path):
        return parse_file(path)
    return Dialect(
        name=project.dialect.name,
        path=path,
        includes=[project.dialect.base],
        version=project.dialect.version,
        dialect_number=project.dialect.dialect_number,
    )


def save_custom_dialect(project: Project, dialect) -> str:
    """Serialise the custom dialect, sorted by id, xmllint-normalised."""
    content = dialect_xml(
        includes=dialect.includes or [project.dialect.base],
        version="",  # version lives in the included base dialect
        dialect_number=dialect.dialect_number or project.dialect.dialect_number,
        enums=sorted(dialect.enums, key=lambda e: e.name),
        messages=sorted(dialect.messages, key=lambda m: m.id),
        header_comment=HEADER_COMMENT,
    )
    write_xml(project.dialect.path, content)
    return project.dialect.path


def custom_message_names(project: Project) -> set[str]:
    dialect = load_custom_dialect(project)
    return {m.name for m in dialect.messages}


# --------------------------------------------------------------------------
# Id space
# --------------------------------------------------------------------------


def check_id(project: Project, catalog: Catalog, message_id: int,
             ignore: str = "") -> IdCheck:
    """Check one message id against every dialect in the catalog."""
    low, high = project.id_space.messages
    collisions = []
    for dialect_name, dialect in catalog.dialects.items():
        if dialect_name == project.dialect.name:
            continue
        for message in dialect.messages:
            if message.id == message_id and message.name != ignore:
                collisions.append((dialect_name, message.name))
    return IdCheck(
        id=message_id,
        available=not collisions,
        in_range=low <= message_id <= high,
        collisions=collisions,
    )


def id_space_report(project: Project, catalog: Catalog) -> dict:
    """Occupancy of the project's reserved message-id window."""
    low, high = project.id_space.messages
    ours = {m.name: m.id for m in load_custom_dialect(project).messages}
    used_by_others = sorted(
        mid
        for mid, names in catalog.id_owners.items()
        if low <= mid <= high and not set(names) & set(ours)
    )
    total = high - low + 1
    return {
        "range": [low, high],
        "total": total,
        "used_by_project": len(ours),
        "used_by_others": len(used_by_others),
        "available": total - len(ours) - len(used_by_others),
        "conflicts": used_by_others,
        "next_free": catalog.next_free_id(low, high),
        "assignments": dict(sorted(ours.items(), key=lambda kv: kv[1])),
    }


# --------------------------------------------------------------------------
# Validation of a proposed message
# --------------------------------------------------------------------------


def validate_message(project: Project, catalog: Catalog, message: Message,
                     replacing: str = "") -> list[str]:
    """Return a list of blocking errors for a proposed custom message."""
    errors: list[str] = []

    if not MESSAGE_NAME_RE.match(message.name):
        errors.append(
            f"message name '{message.name}' must be UPPER_SNAKE_CASE "
            "starting with a letter"
        )
    existing = catalog.messages.get(message.name)
    if existing and message.name != replacing:
        errors.append(
            f"message name '{message.name}' already exists in "
            f"{existing.dialect}.xml (id {existing.id})"
        )

    check = check_id(project, catalog, message.id, ignore=replacing)
    if not check.in_range:
        low, high = project.id_space.messages
        errors.append(
            f"message id {message.id} is outside the project id range {low}-{high}"
        )
    for dialect_name, name in check.collisions:
        errors.append(
            f"message id {message.id} collides with {name} in {dialect_name}.xml"
        )

    if not message.fields:
        errors.append("a message needs at least one field")
    if not message.description:
        errors.append("a message needs a description (required for the ICD)")

    seen: set[str] = set()
    saw_extension = False
    for field in message.fields:
        if not FIELD_NAME_RE.match(field.name):
            errors.append(f"field '{field.name}' must be lower_snake_case")
        if field.name in seen:
            errors.append(f"duplicate field name '{field.name}'")
        seen.add(field.name)
        base, count = split_type(field.type)
        if base not in TYPE_SIZES:
            errors.append(
                f"field '{field.name}' has unknown type '{field.type}'; "
                f"valid base types: {', '.join(sorted(TYPE_SIZES))}"
            )
        elif count < 1 or count > 255:
            errors.append(f"field '{field.name}' array length must be 1..255")
        if field.enum and field.enum not in catalog.enums:
            errors.append(
                f"field '{field.name}' references unknown enum '{field.enum}'"
            )
        if field.is_extension:
            saw_extension = True
        elif saw_extension:
            errors.append(
                f"field '{field.name}' is a non-extension field after an "
                "extension field; extension fields must come last"
            )

    if message.payload_bytes > MAX_PAYLOAD_BYTES:
        errors.append(
            f"payload is {message.payload_bytes} bytes, over the MAVLink "
            f"limit of {MAX_PAYLOAD_BYTES}"
        )
    return errors


def build_message(name: str, message_id: int, description: str,
                  fields: list[dict]) -> Message:
    """Build a :class:`Message` from plain dicts (CLI / web API input)."""
    message = Message(id=int(message_id), name=name.strip().upper(),
                      description=description.strip())
    for spec in fields:
        message.fields.append(
            Field(
                name=str(spec.get("name", "")).strip(),
                type=str(spec.get("type", "")).strip(),
                description=str(spec.get("description", "")).strip(),
                units=str(spec.get("units", "")).strip(),
                enum=str(spec.get("enum", "")).strip(),
                display=str(spec.get("display", "")).strip(),
                instance=str(spec.get("instance", "")).strip(),
                invalid=str(spec.get("invalid", "")).strip(),
                is_extension=bool(spec.get("extension", False)),
            )
        )
    return message


def parse_field_spec(spec: str) -> dict:
    """Parse the compact CLI form ``name:type[:units[:enum[:description]]]``."""
    parts = spec.split(":")
    if len(parts) < 2:
        raise DialectError(
            f"field spec '{spec}' must be at least 'name:type' "
            "(e.g. 'accel_x:float:m/s2')"
        )
    field = {"name": parts[0].strip(), "type": parts[1].strip()}
    if len(parts) > 2 and parts[2].strip():
        field["units"] = parts[2].strip()
    if len(parts) > 3 and parts[3].strip():
        field["enum"] = parts[3].strip()
    if len(parts) > 4:
        # Tolerate extra separators: name:type:units::desc and
        # name:type:units:::desc both mean "no enum, this description".
        field["description"] = ":".join(parts[4:]).lstrip(":").strip()
    return field


# --------------------------------------------------------------------------
# Mutations
# --------------------------------------------------------------------------


def add_message(project: Project, message: Message,
                catalog: Catalog | None = None) -> str:
    catalog = catalog or load_catalog(project.definitions_dir)
    dialect = load_custom_dialect(project)
    if any(m.name == message.name for m in dialect.messages):
        raise DialectError(
            f"'{message.name}' already exists in {project.dialect.name}.xml; "
            "use 'message update' to change it"
        )
    errors = validate_message(project, catalog, message)
    if errors:
        raise DialectError("\n".join(errors))
    message.dialect = project.dialect.name
    dialect.messages.append(message)
    return save_custom_dialect(project, dialect)


def update_message(project: Project, message: Message,
                   catalog: Catalog | None = None) -> str:
    catalog = catalog or load_catalog(project.definitions_dir)
    dialect = load_custom_dialect(project)
    index = next(
        (i for i, m in enumerate(dialect.messages) if m.name == message.name), None
    )
    if index is None:
        raise DialectError(
            f"'{message.name}' is not in {project.dialect.name}.xml. Standard "
            "messages cannot be edited -- clone it as a custom message instead."
        )
    errors = validate_message(project, catalog, message, replacing=message.name)
    if errors:
        raise DialectError("\n".join(errors))
    message.dialect = project.dialect.name
    dialect.messages[index] = message
    return save_custom_dialect(project, dialect)


def remove_message(project: Project, name: str) -> str:
    """Permanently delete a custom message. Standard messages are refused."""
    dialect = load_custom_dialect(project)
    if not any(m.name == name for m in dialect.messages):
        raise DialectError(
            f"'{name}' is not a custom message. Standard messages are never "
            "deleted -- disable it in the profile instead."
        )
    dialect.messages = [m for m in dialect.messages if m.name != name]
    return save_custom_dialect(project, dialect)


def deprecate_message(project: Project, name: str, since: str,
                      replaced_by: str = "", text: str = "") -> str:
    dialect = load_custom_dialect(project)
    message = next((m for m in dialect.messages if m.name == name), None)
    if message is None:
        raise DialectError(f"'{name}' is not a custom message")
    message.deprecated = (since, replaced_by, text)
    return save_custom_dialect(project, dialect)


def clone_as_custom(project: Project, catalog: Catalog, source_name: str,
                    new_name: str, new_id: int | None = None) -> Message:
    """Copy a standard message into the custom dialect under a new name/id."""
    entry = catalog.messages.get(source_name)
    if entry is None:
        raise DialectError(f"unknown message '{source_name}'")
    low, high = project.id_space.messages
    message_id = new_id if new_id is not None else catalog.next_free_id(low, high)
    if message_id is None:
        raise DialectError(f"no free message id in range {low}-{high}")
    clone = Message(
        id=int(message_id),
        name=new_name.strip().upper(),
        description=entry.message.description,
        fields=[Field(**{**f.__dict__}) for f in entry.message.fields],
    )
    add_message(project, clone, catalog)
    return clone


# --------------------------------------------------------------------------
# Custom enums and commands
# --------------------------------------------------------------------------


def add_enum(project: Project, name: str, description: str,
             entries: list[dict], bitmask: bool = False,
             catalog: Catalog | None = None) -> str:
    catalog = catalog or load_catalog(project.definitions_dir)
    if name in catalog.enums:
        raise DialectError(f"enum '{name}' already exists in "
                           f"{catalog.enums[name].dialect}.xml")
    dialect = load_custom_dialect(project)
    enum = Enum(name=name, description=description, bitmask=bitmask)
    for spec in entries:
        enum.entries.append(
            EnumEntry(
                name=str(spec["name"]),
                value=str(spec.get("value", "")),
                description=str(spec.get("description", "")),
            )
        )
    dialect.enums.append(enum)
    return save_custom_dialect(project, dialect)


def add_command(project: Project, name: str, value: int, description: str,
                params: list[dict], catalog: Catalog | None = None) -> str:
    """Append a MAV_CMD entry to the custom dialect's MAV_CMD extension enum."""
    catalog = catalog or load_catalog(project.definitions_dir)
    low, high = project.id_space.commands
    if not low <= value <= high:
        raise DialectError(
            f"command value {value} is outside the project command range "
            f"{low}-{high}"
        )
    if name in catalog.commands:
        raise DialectError(f"command '{name}' already exists")
    for enum in catalog.enums.values():
        if enum.name != "MAV_CMD":
            continue
        for entry in enum.entries:
            if entry.value == str(value):
                raise DialectError(
                    f"command value {value} already used by {entry.name}"
                )

    dialect = load_custom_dialect(project)
    mav_cmd = next((e for e in dialect.enums if e.name == "MAV_CMD"), None)
    if mav_cmd is None:
        mav_cmd = Enum(
            name="MAV_CMD",
            description="Commands added by this dialect.",
        )
        dialect.enums.append(mav_cmd)
    entry = EnumEntry(name=name, value=str(value), description=description)
    for index, spec in enumerate(params, start=1):
        entry.params.append(
            Param(
                index=int(spec.get("index", index)),
                description=str(spec.get("description", "")),
                label=str(spec.get("label", "")),
                units=str(spec.get("units", "")),
                enum=str(spec.get("enum", "")),
            )
        )
    mav_cmd.entries.append(entry)
    mav_cmd.entries.sort(key=lambda e: int(e.value or 0))
    return save_custom_dialect(project, dialect)


# --------------------------------------------------------------------------
# Studio-level message metadata (K-MOSA traceability)
# --------------------------------------------------------------------------


def metadata_path(project: Project) -> str:
    return os.path.join(project.root, METADATA_FILE)


def load_metadata(project: Project) -> dict:
    return load_yaml(metadata_path(project)) or {}


def save_metadata(project: Project, metadata: dict) -> str:
    path = metadata_path(project)
    save_yaml(path, dict(sorted(metadata.items())))
    return path


def set_metadata(project: Project, message: str, **values) -> dict:
    metadata = load_metadata(project)
    entry = metadata.setdefault(message, {})
    for key, value in values.items():
        if value in (None, "", []):
            entry.pop(key, None)
        else:
            entry[key] = value
    if not entry:
        metadata.pop(message, None)
    save_metadata(project, metadata)
    return metadata.get(message, {})
