"""Upstream vs project comparison.

Answers the question the dashboard asks on every open: how far has this project
drifted from upstream MAVLink, and is the drift all additive?
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field as dc_field

from .catalog import Catalog
from .customdialect import load_custom_dialect
from .profile import Resolution
from .project import Project
from .validate import detect_modified_standard


@dataclass
class UpstreamStatus:
    commit: str = ""
    commit_subject: str = ""
    definitions_dir: str = ""
    upstream_message_count: int = 0
    upstream_dialects: int = 0
    base_dialect: str = ""
    base_message_count: int = 0
    added_messages: list[str] = dc_field(default_factory=list)
    added_commands: list[str] = dc_field(default_factory=list)
    added_enums: list[str] = dc_field(default_factory=list)
    disabled_messages: int = 0
    enabled_messages: int = 0
    modified_standard: dict[str, str] = dc_field(default_factory=dict)
    conflicts: dict[int, list[str]] = dc_field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not self.modified_standard and not self.conflicts


def _git(args: list[str]) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def compare(project: Project, catalog: Catalog,
            resolution: Resolution | None = None) -> UpstreamStatus:
    status = UpstreamStatus(
        commit=_git(["rev-parse", "--short", "HEAD"]),
        commit_subject=_git(["log", "-1", "--pretty=%s"]),
        definitions_dir=project.definitions_dir,
        upstream_dialects=len(catalog.dialects),
    )
    base = os.path.splitext(project.dialect.base)[0]
    status.base_dialect = base
    base_closure = catalog.include_closure(base)
    status.base_message_count = len(catalog.messages_of(base_closure))
    status.upstream_message_count = len([
        e for e in catalog.messages.values() if e.dialect != project.dialect.name
    ])

    custom = load_custom_dialect(project)
    status.added_messages = sorted(m.name for m in custom.messages)
    status.added_enums = sorted(e.name for e in custom.enums if e.name != "MAV_CMD")
    status.added_commands = sorted(
        entry.name
        for enum in custom.enums if enum.name == "MAV_CMD"
        for entry in enum.entries
    )
    status.modified_standard = detect_modified_standard(project, catalog)
    status.conflicts = catalog.conflicts_in(base_closure + [project.dialect.name])

    if resolution is not None:
        status.enabled_messages = len(resolution.enabled_messages())
        status.disabled_messages = len(resolution.disabled_messages())
    return status
