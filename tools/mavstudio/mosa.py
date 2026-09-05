"""Layer 5 -- MOSA / K-MOSA interface contracts.

A MAVLink message is a data packet. An *interface contract* is the agreement
between two modules: a named, versioned bundle of required and optional
messages and commands, with declared providers and consumers. Modules publish a
*manifest* saying which interface versions they implement; the studio then
answers "can I swap this ESC for that one" mechanically.

K-MOSA is still being formalised as a standard-and-certification framework, so
this module deliberately implements the structural pieces that any modular
open-systems approach needs -- named interfaces, semantic versioning,
provider/consumer declarations, manifests and conformance checking -- rather
than hard-coding clauses from a specification that may still move.

Deliberately transport-neutral: MAVLink is one data model among several. A
contract can require ``mavlink:UAV_MOTOR_STATUS`` alongside
``dds:PropulsionTelemetry`` or ``uci:SystemStatus``. Only ``mavlink:`` refs are
checked against the catalog; the rest are recorded and reported as unverified,
so the architecture can be modelled before every data model is loadable.

Compatibility is not only about messages. A module swap also has to survive
mechanical, power and link aspects, so a contract can declare ``aspects`` and a
module declares which it satisfies. That is what turns "the messages match"
into a replacement score.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field as dc_field

from .catalog import Catalog
from .project import Project
from .store import load_yaml, save_yaml, slug

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

#: Data models a contract can draw message names from. Only "mavlink" is
#: verifiable today; the others are modelled and reported as unverified.
DATA_MODELS = ("mavlink", "uci", "dds", "dronecan", "ros2", "custom")
DEFAULT_DATA_MODEL = "mavlink"

#: Non-message aspects a module swap has to survive.
STANDARD_ASPECTS = (
    "mechanical", "power", "thermal", "electrical", "network", "video", "timing",
)


def split_ref(ref: str) -> tuple[str, str]:
    """Split ``"dds:PropulsionTelemetry"`` into ``("dds", "PropulsionTelemetry")``.

    A bare name means the default data model, so existing MAVLink-only
    contracts keep working unchanged.
    """
    if ":" in ref:
        model, _, name = ref.partition(":")
        model = model.strip().lower()
        if model in DATA_MODELS:
            return model, name.strip()
    return DEFAULT_DATA_MODEL, ref.strip()


def mavlink_refs(refs: list[str]) -> list[str]:
    """Just the MAVLink names, unqualified -- the ones the catalog can check."""
    return [name for model, name in map(split_ref, refs) if model == "mavlink"]


def external_refs(refs: list[str]) -> list[tuple[str, str]]:
    """(model, name) pairs from data models this tool cannot verify yet."""
    return [(m, n) for m, n in map(split_ref, refs) if m != "mavlink"]


def parse_semver(text: str) -> tuple[int, int, int]:
    match = SEMVER_RE.match(str(text).strip())
    if not match:
        raise ValueError(
            f"'{text}' is not a semantic version (expected MAJOR.MINOR.PATCH)"
        )
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def satisfies(available: str, required: str) -> bool:
    """Does ``available`` satisfy a ``>=`` style requirement, same major only?

    SemVer for interfaces: a major bump is a breaking interface change, so
    1.5.0 does not satisfy a requirement for 2.0.0 and vice versa.
    """
    a_major, a_minor, a_patch = parse_semver(available)
    r_major, r_minor, r_patch = parse_semver(required)
    if a_major != r_major:
        return False
    return (a_minor, a_patch) >= (r_minor, r_patch)


@dataclass
class InterfaceContract:
    name: str                       # e.g. PROPULSION.MONITORING
    version: str = "1.0.0"
    description: str = ""
    transport: list[str] = dc_field(default_factory=lambda: ["mavlink2"])
    providers: list[str] = dc_field(default_factory=list)
    consumers: list[str] = dc_field(default_factory=list)
    required_messages: list[str] = dc_field(default_factory=list)
    optional_messages: list[str] = dc_field(default_factory=list)
    commands: list[str] = dc_field(default_factory=list)
    #: {"TIME_SYNC": "1.0.0"} -- other interfaces this one builds on.
    dependencies: dict[str, str] = dc_field(default_factory=dict)
    requirements: list[str] = dc_field(default_factory=list)
    #: Non-message aspects a provider must satisfy, e.g.
    #: {"mechanical": "ARINC-600 size 2", "power": "28VDC 40W"}.
    aspects: dict[str, str] = dc_field(default_factory=dict)
    #: Recorded history so version bumps can be checked for honesty.
    history: list[dict] = dc_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "interface": self.name,
            "version": self.version,
            "description": self.description,
            "transport": self.transport,
            "providers": self.providers,
            "consumers": self.consumers,
            "required_messages": self.required_messages,
            "optional_messages": self.optional_messages,
            "commands": self.commands,
            "dependencies": self.dependencies,
            "requirements": self.requirements,
            "aspects": self.aspects,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict) -> InterfaceContract:
        return cls(
            name=data.get("interface", data.get("name", "")),
            version=str(data.get("version", "1.0.0")),
            description=data.get("description", ""),
            transport=list(data.get("transport") or ["mavlink2"]),
            providers=list(data.get("providers") or []),
            consumers=list(data.get("consumers") or []),
            required_messages=list(data.get("required_messages") or []),
            optional_messages=list(data.get("optional_messages") or []),
            commands=list(data.get("commands") or []),
            dependencies=dict(data.get("dependencies") or {}),
            requirements=list(data.get("requirements") or []),
            aspects=dict(data.get("aspects") or {}),
            history=list(data.get("history") or []),
        )

    @property
    def all_messages(self) -> list[str]:
        return self.required_messages + self.optional_messages

    @property
    def required_mavlink(self) -> list[str]:
        return mavlink_refs(self.required_messages)

    @property
    def data_models(self) -> list[str]:
        models = {m for m, _ in map(split_ref, self.all_messages)}
        return sorted(models)


@dataclass
class ModuleManifest:
    name: str
    vendor: str = ""
    version: str = "1.0.0"
    description: str = ""
    #: Where the module sits in the architecture: fc, mission_computer,
    #: payload, sensor, datalink, gcs, actuator, other.
    kind: str = "other"
    #: Physical / logical ports the module exposes, e.g.
    #: {"ethernet": "1000BASE-T", "power": "28VDC 40W"}.
    ports: dict[str, str] = dc_field(default_factory=dict)
    #: Non-message aspects the module satisfies; matched against contract
    #: aspects during a swap check.
    aspects: dict[str, str] = dc_field(default_factory=dict)
    #: False for a part that is only being evaluated. Candidates take part in
    #: swap checks but are not held to the project's contracts by `validate`.
    installed: bool = True
    #: {"PROPULSION.MONITORING": "1.3.0"} -- interface versions implemented.
    interfaces: dict[str, str] = dc_field(default_factory=dict)
    transport: list[str] = dc_field(default_factory=lambda: ["mavlink2"])
    tx: list[str] = dc_field(default_factory=list)
    rx: list[str] = dc_field(default_factory=list)
    commands: list[str] = dc_field(default_factory=list)
    capabilities: dict[str, bool] = dc_field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "module": self.name,
            "vendor": self.vendor,
            "version": self.version,
            "description": self.description,
            "kind": self.kind,
            "installed": self.installed,
            "ports": self.ports,
            "aspects": self.aspects,
            "interfaces": self.interfaces,
            "transport": self.transport,
            "messages": {"tx": self.tx, "rx": self.rx},
            "commands": self.commands,
            "capabilities": self.capabilities,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ModuleManifest:
        messages = data.get("messages") or {}
        return cls(
            name=data.get("module", data.get("name", "")),
            vendor=data.get("vendor", ""),
            version=str(data.get("version", "1.0.0")),
            description=data.get("description", ""),
            kind=data.get("kind", "other"),
            installed=bool(data.get("installed", True)),
            ports=dict(data.get("ports") or {}),
            aspects=dict(data.get("aspects") or {}),
            interfaces={k: str(v) for k, v in (data.get("interfaces") or {}).items()},
            transport=list(data.get("transport") or ["mavlink2"]),
            tx=list(messages.get("tx") or []),
            rx=list(messages.get("rx") or []),
            commands=list(data.get("commands") or []),
            capabilities=dict(data.get("capabilities") or {}),
        )


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


def _load_dir(directory: str, factory):
    items = {}
    if not os.path.isdir(directory):
        return items
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith((".yaml", ".yml")):
            continue
        data = load_yaml(os.path.join(directory, entry))
        if not data:
            continue
        item = factory(data)
        if item.name:
            items[item.name] = item
    return items


def load_interfaces(project: Project) -> dict[str, InterfaceContract]:
    return _load_dir(project.interfaces_dir, InterfaceContract.from_dict)


def load_modules(project: Project) -> dict[str, ModuleManifest]:
    return _load_dir(project.modules_dir, ModuleManifest.from_dict)


def save_interface(project: Project, contract: InterfaceContract) -> str:
    path = os.path.join(project.interfaces_dir, f"{slug(contract.name)}.yaml")
    save_yaml(path, contract.to_dict())
    return path


def save_module(project: Project, manifest: ModuleManifest) -> str:
    path = os.path.join(project.modules_dir, f"{slug(manifest.name)}.yaml")
    save_yaml(path, manifest.to_dict())
    return path


# --------------------------------------------------------------------------
# Conformance
# --------------------------------------------------------------------------


@dataclass
class Finding:
    level: str   # ok | warn | error
    subject: str
    message: str


def check_interface(contract: InterfaceContract, catalog: Catalog,
                    custom_names: set[str],
                    interfaces: dict[str, InterfaceContract],
                    modules: dict[str, ModuleManifest] | None = None) -> list[Finding]:
    """Validate one contract against the catalog and its dependencies."""
    findings: list[Finding] = []
    modules = modules or {}
    try:
        parse_semver(contract.version)
    except ValueError as exc:
        findings.append(Finding("error", contract.name, str(exc)))

    known = set(catalog.messages) | custom_names
    for message in mavlink_refs(contract.all_messages):
        if message not in known:
            findings.append(
                Finding("error", contract.name,
                        f"references undefined MAVLink message '{message}'")
            )
    for model, name in external_refs(contract.all_messages):
        findings.append(
            Finding("info", contract.name,
                    f"'{name}' comes from the {model} data model and is not "
                    "verified by this tool")
        )
    for aspect in contract.aspects:
        if aspect not in STANDARD_ASPECTS:
            findings.append(
                Finding("info", contract.name,
                        f"aspect '{aspect}' is project-specific "
                        f"(standard aspects: {', '.join(STANDARD_ASPECTS)})")
            )
    for command in contract.commands:
        if command not in catalog.commands:
            findings.append(
                Finding("error", contract.name,
                        f"references undefined command '{command}'")
            )
    if not contract.providers:
        findings.append(
            Finding("warn", contract.name, "no provider module declared")
        )
    if not contract.consumers:
        findings.append(
            Finding("warn", contract.name, "no consumer module declared")
        )
    if not contract.required_messages:
        findings.append(
            Finding("warn", contract.name,
                    "no required messages -- the contract guarantees nothing")
        )
    for role, names in (("provider", contract.providers),
                        ("consumer", contract.consumers)):
        for name in names:
            if name not in modules:
                findings.append(
                    Finding("info", contract.name,
                            f"{role} '{name}' has no module manifest yet")
                )
    for dependency, version in contract.dependencies.items():
        other = interfaces.get(dependency)
        if other is None:
            findings.append(
                Finding("error", contract.name,
                        f"depends on unknown interface '{dependency}'")
            )
        elif not satisfies(other.version, version):
            findings.append(
                Finding("error", contract.name,
                        f"needs {dependency} >= {version} but the project "
                        f"defines {other.version}")
            )
    return findings


@dataclass
class ModuleCheck:
    module: str
    interface: str
    required_version: str
    module_version: str
    compatible: bool
    missing_messages: list[str] = dc_field(default_factory=list)
    missing_commands: list[str] = dc_field(default_factory=list)
    notes: list[str] = dc_field(default_factory=list)


def check_module(manifest: ModuleManifest,
                 interfaces: dict[str, InterfaceContract]) -> list[ModuleCheck]:
    """Does a module actually implement the interfaces it claims?"""
    results: list[ModuleCheck] = []
    provided = set(manifest.tx) | set(manifest.rx)
    for interface_name, claimed_version in manifest.interfaces.items():
        contract = interfaces.get(interface_name)
        if contract is None:
            results.append(
                ModuleCheck(
                    module=manifest.name,
                    interface=interface_name,
                    required_version="?",
                    module_version=claimed_version,
                    compatible=False,
                    notes=[f"interface '{interface_name}' is not defined in this project"],
                )
            )
            continue
        missing = [m for m in contract.required_mavlink if m not in provided]
        missing_commands = [c for c in contract.commands if c not in manifest.commands]
        missing_aspects = [
            f"{k} (needs {v})" for k, v in contract.aspects.items()
            if k not in manifest.aspects
        ]
        try:
            version_ok = satisfies(claimed_version, contract.version)
        except ValueError as exc:
            version_ok = False
            missing.append(str(exc))
        notes = []
        if not version_ok:
            notes.append(
                f"module implements {interface_name} {claimed_version} but the "
                f"project requires {contract.version}"
            )
        for aspect in missing_aspects:
            notes.append(f"aspect not declared: {aspect}")
        results.append(
            ModuleCheck(
                module=manifest.name,
                interface=interface_name,
                required_version=contract.version,
                module_version=claimed_version,
                compatible=version_ok and not missing and not missing_aspects,
                missing_messages=missing,
                missing_commands=missing_commands,
                notes=notes,
            )
        )
    return results


def compatibility_matrix(interfaces: dict[str, InterfaceContract],
                         modules: dict[str, ModuleManifest]) -> dict:
    """Interface x module grid.

    Cell legend: ``P``/``C``/``PC`` for the declared role, suffixed with

    ``!``  the module claims the interface but does not satisfy it
    ``?``  the contract names the module but the module never declares it
    ``~``  the module is a candidate, not installed
    ``-``  the module has no role in this interface
    """
    module_names = sorted(modules)
    rows = []
    for name in sorted(interfaces):
        contract = interfaces[name]
        cells = []
        for module in module_names:
            manifest = modules[module]
            role = ""
            if module in contract.providers:
                role += "P"
            if module in contract.consumers:
                role += "C"
            if not role:
                cells.append("-")
                continue
            if not manifest.installed:
                cells.append(f"{role}~")
                continue
            if name not in manifest.interfaces:
                cells.append(f"{role}?")
                continue
            checks = [c for c in check_module(manifest, interfaces)
                      if c.interface == name]
            ok = all(c.compatible for c in checks)
            if ok and "C" in role:
                # A consumer must actually be able to receive what it consumes.
                receivable = set(manifest.rx) | set(manifest.tx)
                ok = all(m in receivable for m in contract.required_messages)
            cells.append(role if ok else f"{role}!")
        rows.append({"interface": name, "version": contract.version, "cells": cells})
    return {"modules": module_names, "rows": rows}


@dataclass
class AspectCheck:
    aspect: str
    required: str
    offered: str
    ok: bool


@dataclass
class SwapReport:
    interface: str
    current: str
    replacement: str
    verdict: str            # compatible | partial | incompatible
    missing_messages: list[str] = dc_field(default_factory=list)
    missing_commands: list[str] = dc_field(default_factory=list)
    unverified: list[str] = dc_field(default_factory=list)
    aspects: list[AspectCheck] = dc_field(default_factory=list)
    version_note: str = ""
    #: Fraction of checked items the replacement satisfies, 0.0 - 1.0.
    score: float = 0.0


def _aspect_checks(contract: InterfaceContract | None,
                   replacement: ModuleManifest) -> list[AspectCheck]:
    if contract is None:
        return []
    checks = []
    for aspect, required in contract.aspects.items():
        offered = replacement.aspects.get(aspect, "")
        # A declared aspect matches when the module names it; when the contract
        # pins a value, the module has to state the same one.
        ok = bool(offered) and (not required or offered == required)
        checks.append(AspectCheck(aspect, required, offered, ok))
    return checks


def compare_modules(current: ModuleManifest, replacement: ModuleManifest,
                    interfaces: dict[str, InterfaceContract]) -> list[SwapReport]:
    """What breaks if ``current`` is swapped for ``replacement``?

    Each interface is scored over everything checkable: required MAVLink
    messages, commands, and declared non-message aspects. Refs from data models
    this tool cannot load are listed as unverified and left out of the score
    rather than silently counted as passing.
    """
    reports: list[SwapReport] = []
    replacement_messages = set(replacement.tx) | set(replacement.rx)
    for interface_name, current_version in current.interfaces.items():
        contract = interfaces.get(interface_name)
        replacement_version = replacement.interfaces.get(interface_name)
        if replacement_version is None:
            reports.append(
                SwapReport(
                    interface=interface_name,
                    current=current_version,
                    replacement="-",
                    verdict="incompatible",
                    score=0.0,
                    version_note=f"{replacement.name} does not implement "
                                 f"{interface_name}",
                )
            )
            continue

        required = contract.required_mavlink if contract else []
        missing = [m for m in required if m not in replacement_messages]
        commands = contract.commands if contract else []
        missing_commands = [c for c in commands if c not in replacement.commands]
        aspects = _aspect_checks(contract, replacement)
        unverified = [
            f"{model}:{name}"
            for model, name in external_refs(
                contract.required_messages if contract else []
            )
        ]

        checked = len(required) + len(commands) + len(aspects)
        failed = len(missing) + len(missing_commands) + sum(
            1 for a in aspects if not a.ok
        )
        score = 1.0 if checked == 0 else (checked - failed) / checked

        note = ""
        try:
            downgrade = not satisfies(replacement_version, current_version)
        except ValueError as exc:
            downgrade = True
            note = str(exc)
        if downgrade and not note:
            note = (
                f"{replacement.name} implements {interface_name} "
                f"{replacement_version}, older than the current {current_version}"
            )

        if failed and downgrade:
            verdict = "incompatible"
        elif failed or downgrade:
            verdict = "partial"
        else:
            verdict = "compatible"

        reports.append(
            SwapReport(
                interface=interface_name,
                current=current_version,
                replacement=replacement_version,
                verdict=verdict,
                missing_messages=missing,
                missing_commands=missing_commands,
                unverified=unverified,
                aspects=aspects,
                version_note=note,
                score=score,
            )
        )
    return reports


def swap_score(reports: list[SwapReport]) -> float:
    """Overall replacement compatibility across every interface, 0.0 - 1.0."""
    if not reports:
        return 1.0
    return sum(r.score for r in reports) / len(reports)


def classify_change(before: InterfaceContract,
                    after: InterfaceContract) -> tuple[str, list[str]]:
    """Classify a contract change as major / minor / patch, with reasons."""
    reasons: list[str] = []
    removed = set(before.required_messages) - set(after.required_messages)
    added_required = set(after.required_messages) - set(before.required_messages)
    removed_commands = set(before.commands) - set(after.commands)
    added_optional = set(after.optional_messages) - set(before.optional_messages)

    for name in sorted(removed):
        reasons.append(f"required message '{name}' removed")
    for name in sorted(removed_commands):
        reasons.append(f"command '{name}' removed")
    for name in sorted(added_required):
        reasons.append(f"required message '{name}' added")
    for name in sorted(added_optional):
        reasons.append(f"optional message '{name}' added")

    if removed or removed_commands or added_required:
        return "major", reasons
    if added_optional or set(after.commands) - set(before.commands):
        return "minor", reasons
    return "patch", reasons or ["no structural change"]


def expected_version(before: InterfaceContract, level: str) -> str:
    major, minor, patch = parse_semver(before.version)
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"
