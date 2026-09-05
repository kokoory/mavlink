"""Layer 1 -- the read-only catalog of upstream MAVLink definitions.

The catalog is the "original DB" view of ``message_definitions/v1.0``: every
dialect is parsed, the ``<include>`` graph is resolved, and messages, enums and
MAV_CMD entries are indexed by name and id. Nothing here ever writes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field as dc_field

from .model import Dialect, Enum, EnumEntry, Message
from .parser import load_registry_files

DEFAULT_DEFINITIONS_DIR = os.path.join("message_definitions", "v1.0")

# Dialects that only exist to exercise the generators; they are parsed (so that
# id-collision checks stay honest) but hidden from the catalog UI by default.
TEST_DIALECTS = {"python_array_test", "test"}

# The layering upstream MAVLink itself documents.
STANDARD_LAYERS = ("minimal", "standard", "common")


@dataclass
class CatalogEntry:
    """A message as seen by the catalog, with its provenance."""

    message: Message
    dialect: str

    @property
    def name(self) -> str:
        return self.message.name

    @property
    def id(self) -> int:
        return self.message.id

    @property
    def layer(self) -> str:
        """Which structural layer the message belongs to."""
        if self.dialect in STANDARD_LAYERS:
            return "standard"
        if self.dialect == "development":
            return "development"
        if self.dialect in TEST_DIALECTS:
            return "test"
        return "vendor"

    @property
    def status(self) -> str:
        """Lifecycle status used for the coloured status dot in the UI."""
        if self.message.deprecated is not None:
            return "deprecated"
        if self.message.superseded is not None:
            return "superseded"
        if self.message.wip:
            return "experimental"
        return "standard"


@dataclass
class Catalog:
    definitions_dir: str
    dialects: dict[str, Dialect] = dc_field(default_factory=dict)
    messages: dict[str, CatalogEntry] = dc_field(default_factory=dict)
    enums: dict[str, Enum] = dc_field(default_factory=dict)
    #: name -> list of (dialect, entry) for every MAV_CMD-style enum entry
    commands: dict[str, EnumEntry] = dc_field(default_factory=dict)
    #: message id -> list of message names claiming it (len > 1 means conflict)
    id_owners: dict[int, list[str]] = dc_field(default_factory=dict)

    # -- lookup helpers ---------------------------------------------------

    def message(self, name: str) -> Message | None:
        entry = self.messages.get(name)
        return entry.message if entry else None

    def dialect_of(self, name: str) -> str:
        entry = self.messages.get(name)
        return entry.dialect if entry else ""

    def include_closure(self, dialect_name: str) -> list[str]:
        """Dialect plus everything it includes, transitively, in include order."""
        seen: list[str] = []
        stack = [dialect_name]
        while stack:
            current = stack.pop(0)
            if current in seen or current not in self.dialects:
                continue
            seen.append(current)
            for include in self.dialects[current].includes:
                stack.append(os.path.splitext(include)[0])
        return seen

    def messages_of(self, dialect_names: list[str]) -> list[CatalogEntry]:
        result = [e for e in self.messages.values() if e.dialect in dialect_names]
        return sorted(result, key=lambda e: e.id)

    def enums_of(self, dialect_names: list[str]) -> list[Enum]:
        selected = [e for e in self.enums.values() if e.dialect in dialect_names]
        return sorted(selected, key=lambda e: e.name)

    def conflicts(self) -> dict[int, list[str]]:
        """Message ids claimed by more than one message name, catalog-wide.

        Upstream has known benign cases (paparazzi and ardupilotmega both use
        180-184) because those dialects are never combined. Use
        :meth:`conflicts_in` for the check that actually matters.
        """
        return {mid: names for mid, names in self.id_owners.items() if len(names) > 1}

    def conflicts_in(self, dialect_names: list[str]) -> dict[int, list[str]]:
        """Message ids claimed twice *within one include closure* -- real errors."""
        by_id: dict[int, list[str]] = {}
        for name in dialect_names:
            dialect = self.dialects.get(name)
            if dialect is None:
                continue
            for message in dialect.messages:
                by_id.setdefault(message.id, []).append(message.name)
        return {
            mid: names
            for mid, names in by_id.items()
            if len({n for n in names}) > 1
        }

    def next_free_id(self, low: int, high: int) -> int | None:
        """Lowest unused message id inside ``[low, high]``."""
        for candidate in range(low, high + 1):
            if candidate not in self.id_owners:
                return candidate
        return None

    def free_ids(self, low: int, high: int) -> int:
        used = sum(1 for mid in self.id_owners if low <= mid <= high)
        return (high - low + 1) - used


def load_catalog(definitions_dir: str = DEFAULT_DEFINITIONS_DIR) -> Catalog:
    """Parse every dialect under ``definitions_dir`` into a :class:`Catalog`."""
    catalog = Catalog(definitions_dir=definitions_dir)
    for dialect in load_registry_files(definitions_dir):
        catalog.dialects[dialect.name] = dialect
        for message in dialect.messages:
            # First definition wins; later ones are recorded as id conflicts.
            catalog.messages.setdefault(
                message.name, CatalogEntry(message=message, dialect=dialect.name)
            )
            owners = catalog.id_owners.setdefault(message.id, [])
            if message.name not in owners:
                owners.append(message.name)
        for enum in dialect.enums:
            existing = catalog.enums.get(enum.name)
            if existing is None:
                catalog.enums[enum.name] = enum
            else:
                # Dialects extend upstream enums; merge the extra entries in so
                # command lookups see the full set.
                known = {e.name for e in existing.entries}
                existing.entries.extend(
                    e for e in enum.entries if e.name not in known
                )
    for enum in catalog.enums.values():
        if enum.name.endswith("MAV_CMD") or enum.name == "MAV_CMD":
            for entry in enum.entries:
                catalog.commands.setdefault(entry.name, entry)
    return catalog
