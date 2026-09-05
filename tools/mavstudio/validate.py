"""Cross-layer validation.

Checks run against a resolved profile and cover the things that actually bite:
id collisions, payload limits, dangling references, standard files that have
been modified, capability coverage, MOSA conformance and the bandwidth budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .bandwidth import compute_budget
from .capabilities import CapabilitySet
from .catalog import Catalog
from .customdialect import (
    check_id,
    load_custom_dialect,
    load_metadata,
    validate_message,
)
from .mosa import check_interface, check_module, load_interfaces, load_modules
from .model import MAX_PAYLOAD_BYTES
from .profile import Resolution
from .project import Project

LEVELS = ("error", "warn", "info")


@dataclass
class Issue:
    level: str
    check: str
    subject: str
    message: str
    hint: str = ""


@dataclass
class Report:
    issues: list[Issue] = dc_field(default_factory=list)

    def add(self, level, check, subject, message, hint=""):
        self.issues.append(Issue(level, check, subject, message, hint))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warn"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def counts(self) -> dict[str, int]:
        return {level: sum(1 for i in self.issues if i.level == level)
                for level in LEVELS}


def validate_all(project: Project, catalog: Catalog,
                 capability_set: CapabilitySet,
                 resolution: Resolution) -> Report:
    report = Report()
    custom = load_custom_dialect(project)
    custom_names = {m.name for m in custom.messages}

    # -- custom dialect ---------------------------------------------------
    for message in custom.messages:
        for error in validate_message(project, catalog, message,
                                      replacing=message.name):
            report.add("error", "dialect", message.name, error)
        if message.payload_bytes > MAX_PAYLOAD_BYTES * 0.8:
            report.add(
                "warn", "dialect", message.name,
                f"payload is {message.payload_bytes} bytes, close to the "
                f"{MAX_PAYLOAD_BYTES} byte limit",
                "Split the message or move rarely-changing fields to extensions.",
            )
        check = check_id(project, catalog, message.id, ignore=message.name)
        if not check.in_range:
            low, high = project.id_space.messages
            report.add(
                "error", "id-space", message.name,
                f"id {message.id} is outside the reserved range {low}-{high}",
            )

    # -- id collisions in the dialect we actually ship ---------------------
    closure = catalog.include_closure(project.dialect.base.replace(".xml", ""))
    for message_id, names in catalog.conflicts_in(closure + [project.dialect.name]).items():
        report.add(
            "error", "id-collision", ", ".join(names),
            f"message id {message_id} is claimed by {len(names)} messages "
            "inside the dialect we build",
        )

    # -- upstream purity --------------------------------------------------
    modified = detect_modified_standard(project, catalog)
    for name, detail in modified.items():
        report.add(
            "error", "upstream-purity", name, detail,
            "Standard definitions must stay untouched. Revert the file and "
            "clone the message into the custom dialect instead.",
        )

    # -- profile ----------------------------------------------------------
    enabled = resolution.enabled_messages()
    if not any(s.name == "HEARTBEAT" for s in enabled):
        report.add("error", "profile", "HEARTBEAT",
                   "HEARTBEAT is disabled; the system cannot be discovered")
    for state in enabled:
        if state.status == "deprecated":
            report.add(
                "warn", "profile", state.name,
                "message is deprecated upstream but enabled in this profile",
                "Check the upstream replacement before flying this.",
            )
        if state.status == "superseded":
            message = catalog.message(state.name)
            replacement = message.superseded[1] if message else ""
            report.add(
                "warn", "profile", state.name,
                "message is superseded upstream but enabled in this profile",
                f"Prefer {replacement}." if replacement
                else "Check the upstream note for the preferred message.",
            )
        if state.status == "experimental":
            report.add(
                "info", "profile", state.name,
                "message is marked work-in-progress upstream and may change",
            )
    for name in resolution.profile.messages:
        if name not in catalog.messages and name not in custom_names:
            report.add(
                "error", "profile", name,
                "profile overrides a message that does not exist in any dialect",
            )

    # -- dangling enum references ----------------------------------------
    for state in enabled:
        message = catalog.message(state.name)
        if message is None:
            continue
        for enum_name in message.enum_refs:
            if enum_name not in catalog.enums:
                report.add("error", "dependency", state.name,
                           f"field references unknown enum '{enum_name}'")

    # -- capability coverage ----------------------------------------------
    _, unclaimed = capability_set.coverage(catalog)
    standard_unclaimed = sorted(
        n for n in unclaimed
        if catalog.dialect_of(n) in ("minimal", "standard", "common")
    )
    if standard_unclaimed:
        report.add(
            "warn", "capability", ", ".join(standard_unclaimed[:5]),
            f"{len(standard_unclaimed)} standard messages are not claimed by "
            "any capability and can only be toggled individually",
        )

    # -- MOSA -------------------------------------------------------------
    interfaces = load_interfaces(project)
    modules = load_modules(project)
    for contract in interfaces.values():
        for finding in check_interface(contract, catalog, custom_names,
                                       interfaces, modules):
            report.add(finding.level, "mosa-interface", finding.subject,
                       finding.message)
        disabled = [
            m for m in contract.required_messages
            if m in resolution.states and not resolution.states[m].enabled
        ]
        if disabled:
            report.add(
                "error", "mosa-interface", contract.name,
                f"required messages disabled in this profile: {', '.join(disabled)}",
                "Enable them, or drop them from the contract's required list.",
            )
    for manifest in modules.values():
        if not manifest.installed:
            continue  # candidate parts are evaluated by `swap`, not enforced here
        for check in check_module(manifest, interfaces):
            if check.compatible:
                continue
            detail = check.notes[:]
            if check.missing_messages:
                detail.append(
                    "missing required messages: " + ", ".join(check.missing_messages)
                )
            report.add("error", "mosa-module", f"{manifest.name} / {check.interface}",
                       "; ".join(detail) or "does not satisfy the contract")

    for name in resolution.profile.interfaces:
        if name not in interfaces:
            report.add("error", "mosa-interface", name,
                       "profile claims an interface that is not defined")

    # -- traceability -----------------------------------------------------
    metadata = load_metadata(project)
    for message in custom.messages:
        entry = metadata.get(message.name, {})
        if not entry.get("requirements"):
            report.add(
                "warn", "traceability", message.name,
                "custom message has no requirement id",
                "mavstudio meta set <MSG> --requirement <ID>",
            )
        if not entry.get("interface"):
            report.add(
                "warn", "traceability", message.name,
                "custom message is not attached to a MOSA interface contract",
            )

    # -- bandwidth --------------------------------------------------------
    budget = compute_budget(resolution)
    for warning in budget.warnings:
        level = "error" if budget.total_bps > budget.bitrate else "warn"
        report.add(level, "bandwidth", resolution.profile.link.name, warning)

    return report


def detect_modified_standard(project: Project, catalog: Catalog) -> dict[str, str]:
    """Report upstream dialect files that differ from git HEAD.

    Keeping this at zero is what makes upstream updates a fast-forward.
    """
    import subprocess

    try:
        changed = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", project.definitions_dir],
            capture_output=True, text=True, check=True,
        ).stdout.split()
    except (subprocess.CalledProcessError, OSError):
        return {}
    modified = {}
    for path in changed:
        if path == project.dialect.path:
            continue
        modified[path] = "upstream definition file has local modifications"
    return modified
