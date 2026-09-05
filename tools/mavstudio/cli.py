"""Command line interface for mavstudio.

    python3 -m mavstudio <command> ...

Every command works on a (vehicle, profile) pair; omit --vehicle/--profile and
the first one defined in the project is used.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .bandwidth import bar, compute_budget
from .build import MAVGEN_LANGUAGES, build_profile_dialect, generate_sources
from .customdialect import (
    DialectError,
    add_command,
    add_enum,
    build_message,
    check_id,
    clone_as_custom,
    deprecate_message,
    id_space_report,
    load_custom_dialect,
    load_metadata,
    parse_field_spec,
    remove_message,
    set_metadata,
)
from .icd import write_icd
from .mosa import (
    DATA_MODELS,
    STANDARD_ASPECTS,
    InterfaceContract,
    ModuleManifest,
    compare_modules,
    compatibility_matrix,
    external_refs,
    load_interfaces,
    load_modules,
    save_interface,
    save_module,
    split_ref,
    swap_score,
)
from .parser import message_xml
from .profile import MessageOverride, Profile, list_profiles
from .project import Vehicle, load_project
from .upstream import compare as upstream_compare
from .validate import validate_all
from .workspace import open_studio

STATUS_MARK = {
    "standard": " ",
    "custom": "*",
    "experimental": "~",
    "superseded": "s",
    "deprecated": "!",
    "conflict": "X",
}


def _studio(args):
    return open_studio(args.project, args.vehicle, args.profile)


def _print_table(rows, headers):
    if not rows:
        print("(nothing to show)")
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------


def cmd_init(args):
    project = load_project(args.project)
    project.name = args.name or project.name
    vehicle_name = args.vehicle or "UAV"
    if vehicle_name not in project.vehicles:
        project.vehicles[vehicle_name] = Vehicle(
            name=vehicle_name,
            description=args.description or "",
            profiles=list(args.profiles),
        )
    if args.dialect:
        project.dialect.name = args.dialect
        project.dialect.path = os.path.join(
            os.path.dirname(project.dialect.path), f"{args.dialect}.xml"
        )
    if args.id_range:
        low, high = args.id_range
        project.id_space.messages = (low, high)
        project.id_space.commands = (low, high)
    project.save()
    print(f"wrote {project.path}")

    for profile_name in project.vehicles[vehicle_name].profiles:
        path = project.profile_path(vehicle_name, profile_name)
        if os.path.exists(path):
            continue
        profile = Profile(vehicle=vehicle_name, name=profile_name)
        profile.description = f"{profile_name} configuration for {vehicle_name}"
        if profile_name in ("dev", "development", "sitl", "maintenance"):
            # Development-style profiles start with the heavy telemetry on.
            profile.capabilities = {
                "telemetry_imu": True,
                "debug_messages": True,
                "log_download": True,
                "ftp": True,
                "param_ext": True,
            }
        print(f"wrote {profile.save(project)}")
    print(
        f"\nMessage id range: {project.id_space.messages[0]}-"
        f"{project.id_space.messages[1]}   custom dialect: "
        f"{project.dialect.path}"
    )
    print("Next:  python3 -m mavstudio dashboard")


# --------------------------------------------------------------------------
# inspection
# --------------------------------------------------------------------------


def cmd_dashboard(args):
    studio = _studio(args)
    resolution = studio.resolution
    profile = studio.profile
    status = upstream_compare(studio.project, studio.catalog, resolution)
    budget = compute_budget(resolution)
    report = validate_all(
        studio.project, studio.catalog, studio.capability_set, resolution
    )
    counts = report.counts()

    print(f"{studio.project.name}")
    print(f"Vehicle {profile.vehicle}   Profile {profile.name}   "
          f"MAVLink {profile.link.mavlink_version}.0"
          f"{' (signed)' if profile.link.signing else ''}")
    print()
    print(f"  upstream        {status.commit or '?'}  "
          f"{status.upstream_message_count} messages in "
          f"{status.upstream_dialects} dialects")
    print(f"  base dialect    {status.base_dialect}.xml "
          f"({status.base_message_count} messages)")
    print(f"  custom          {len(status.added_messages)} messages, "
          f"{len(status.added_commands)} commands, "
          f"{len(status.added_enums)} enums")
    print(f"  profile         {status.enabled_messages} enabled / "
          f"{status.disabled_messages} disabled")
    print(f"  modified std    {len(status.modified_standard)}"
          f"{'  <- should be 0' if status.modified_standard else ''}")
    print(f"  id conflicts    {len(status.conflicts)}")
    print()
    print(f"  link            {profile.link.name}  "
          f"{profile.link.bitrate} bit/s")
    print(f"  periodic load   {budget.total_bps / 1000:7.1f} kbps  "
          f"[{bar(budget.utilisation)}] {budget.utilisation * 100:.1f}%")
    print(f"  validation      {counts['error']} errors, "
          f"{counts['warn']} warnings, {counts['info']} notes")
    if report.errors:
        print()
        for issue in report.errors[:5]:
            print(f"    ERROR [{issue.check}] {issue.subject}: {issue.message}")
        if len(report.errors) > 5:
            print(f"    ... and {len(report.errors) - 5} more "
                  "(run 'mavstudio validate')")


def cmd_list(args):
    studio = _studio(args)
    metadata = load_metadata(studio.project)
    rows = []
    for state in sorted(studio.resolution.states.values(), key=lambda s: s.id):
        if args.enabled_only and not state.enabled:
            continue
        if args.disabled_only and state.enabled:
            continue
        if args.custom_only and state.origin != "custom":
            continue
        if args.dialect_filter and state.dialect != args.dialect_filter:
            continue
        if args.category and state.category != args.category:
            continue
        if args.capability and state.capability != args.capability:
            continue
        if args.search and args.search.upper() not in state.name:
            continue
        rows.append([
            "ON" if state.enabled else "--",
            STATUS_MARK.get(state.status, " "),
            state.id,
            state.name,
            state.dialect,
            state.category,
            f"{state.rate_hz:g}" if state.rate_hz else "-",
            state.payload_bytes,
            metadata.get(state.name, {}).get("interface", "-"),
        ])
    _print_table(rows, ["ON", "S", "ID", "MESSAGE", "SOURCE", "CATEGORY",
                        "RATE", "BYTES", "INTERFACE"])
    print(f"\n{len(rows)} messages  "
          "(S: * custom  ~ experimental  s superseded  ! deprecated  "
          "X id conflict)")


def cmd_show(args):
    studio = _studio(args)
    name = args.message.upper()
    state = studio.resolution.states.get(name)
    if state is None:
        raise SystemExit(f"unknown message '{name}'")
    custom = {m.name: m for m in load_custom_dialect(studio.project).messages}
    message = custom.get(name) or studio.catalog.message(name)
    metadata = load_metadata(studio.project).get(name, {})

    print(f"{state.name}  (id {state.id})")
    print(f"  origin       {state.dialect}.xml ({state.origin})")
    print(f"  status       {state.status}")
    print(f"  enabled      {'yes' if state.enabled else 'no'}  -- {state.reason}")
    print(f"  capability   {state.capability_title or '-'} "
          f"[{state.capability or '-'}]")
    print(f"  category     {state.category}")
    print(f"  payload      {message.payload_bytes} bytes")
    print(f"  direction    TX {', '.join(state.tx) or '-'}   "
          f"RX {', '.join(state.rx) or '-'}")
    print(f"  rate         {state.rate_hz or '-'} Hz   priority {state.priority}")
    print(f"  deletable    {'yes (custom)' if state.deletable else 'no (standard)'}")
    if metadata:
        print(f"  metadata     {json.dumps(metadata, ensure_ascii=False)}")
    if message.description:
        print(f"\n  {message.description}")
    print()
    rows = [
        [index, f.name, f.type, f.size, f.units or "-", f.enum or "-",
         "ext" if f.is_extension else "", f.description[:60]]
        for index, f in enumerate(message.fields, start=1)
    ]
    _print_table(rows, ["#", "FIELD", "TYPE", "B", "UNITS", "ENUM", "", "DESCRIPTION"])
    if args.xml:
        print()
        print("\n".join(message_xml(message, "")))


def cmd_capabilities(args):
    studio = _studio(args)
    rows = []
    for group, capabilities in studio.capability_set.groups().items():
        for capability in capabilities:
            on = studio.resolution.capability_states.get(capability.key, False)
            owned = studio.capability_set.messages_for(
                capability.key, studio.catalog
            )
            rows.append([
                group,
                "ON" if on else "--",
                "req" if capability.required else "",
                capability.key,
                capability.title,
                len(owned),
                len(studio.capability_set.commands_for(capability.key, studio.catalog)),
            ])
    _print_table(rows, ["GROUP", "ST", "", "KEY", "CAPABILITY", "MSGS", "CMDS"])


def cmd_ids(args):
    studio = _studio(args)
    report = id_space_report(studio.project, studio.catalog)
    low, high = report["range"]
    print(f"Message id space  {low}-{high}   total {report['total']}")
    print(f"  used by project     {report['used_by_project']}")
    print(f"  used by others      {report['used_by_others']}"
          f"{'  <- conflict' if report['used_by_others'] else ''}")
    print(f"  available           {report['available']}")
    print(f"  next free           {report['next_free']}")
    if report["conflicts"]:
        print(f"  conflicting ids     {report['conflicts']}")
    if report["assignments"]:
        print()
        _print_table(
            [[i, n] for n, i in report["assignments"].items()], ["ID", "MESSAGE"]
        )
    if args.check is not None:
        check = check_id(studio.project, studio.catalog, args.check)
        print(f"\nid {args.check}: "
              f"{'available' if check.available else 'TAKEN'}, "
              f"{'in range' if check.in_range else 'OUT OF RANGE'}")
        for dialect, name in check.collisions:
            print(f"  collides with {name} in {dialect}.xml")


# --------------------------------------------------------------------------
# profile edits
# --------------------------------------------------------------------------


def _save_profile(studio):
    path = studio.profile.save(studio.project)
    print(f"wrote {path}")


def cmd_enable(args):
    studio = _studio(args)
    for name in args.messages:
        name = name.upper()
        if name not in studio.resolution.states:
            raise SystemExit(f"unknown message '{name}'")
        override = studio.profile.messages.setdefault(name, MessageOverride())
        override.enabled = not args.off
    _save_profile(studio)
    print(f"{'disabled' if args.off else 'enabled'}: {', '.join(args.messages)}")


def cmd_capability(args):
    studio = _studio(args)
    capability = studio.capability_set.get(args.key)
    if capability is None:
        raise SystemExit(
            f"unknown capability '{args.key}' "
            f"(see 'mavstudio capabilities')"
        )
    if capability.required and args.off:
        raise SystemExit(
            f"capability '{args.key}' is required and cannot be turned off"
        )
    studio.profile.capabilities[args.key] = not args.off
    _save_profile(studio)
    owned = sorted(studio.capability_set.messages_for(args.key, studio.catalog))
    print(f"{capability.title}: {'OFF' if args.off else 'ON'} "
          f"-- {len(owned)} messages follow")
    if owned:
        print("  " + ", ".join(owned[:12]) + (" ..." if len(owned) > 12 else ""))


def cmd_set(args):
    studio = _studio(args)
    name = args.message.upper()
    if name not in studio.resolution.states:
        raise SystemExit(f"unknown message '{name}'")
    override = studio.profile.messages.setdefault(name, MessageOverride())
    if args.rate is not None:
        override.rate_hz = args.rate
    if args.tx is not None:
        override.tx = [c.strip() for c in args.tx.split(",") if c.strip()]
    if args.rx is not None:
        override.rx = [c.strip() for c in args.rx.split(",") if c.strip()]
    if args.priority:
        override.priority = args.priority
    if args.note:
        override.note = args.note
    _save_profile(studio)
    cmd_show(argparse.Namespace(**{**vars(args), "xml": False}))


def cmd_profiles(args):
    project = load_project(args.project)
    rows = [[v, p] for v, p in list_profiles(project)]
    _print_table(rows, ["VEHICLE", "PROFILE"])


def cmd_diff(args):
    """Compare two profiles."""
    left = open_studio(args.project, args.vehicle, args.profile)
    right = open_studio(args.project, args.other_vehicle or args.vehicle,
                        args.other_profile)
    rows = []
    for name in sorted(set(left.resolution.states) | set(right.resolution.states)):
        a = left.resolution.states.get(name)
        b = right.resolution.states.get(name)
        a_on = a.enabled if a else False
        b_on = b.enabled if b else False
        a_rate = a.rate_hz if a else 0
        b_rate = b.rate_hz if b else 0
        if a_on == b_on and a_rate == b_rate:
            continue
        rows.append([
            name,
            f"{'ON' if a_on else '--'} {a_rate:g}Hz" if a_rate else
            ("ON" if a_on else "--"),
            f"{'ON' if b_on else '--'} {b_rate:g}Hz" if b_rate else
            ("ON" if b_on else "--"),
        ])
    _print_table(rows, ["MESSAGE",
                        f"{left.profile.vehicle}/{left.profile.name}",
                        f"{right.profile.vehicle}/{right.profile.name}"])
    print(f"\n{len(rows)} differences")


# --------------------------------------------------------------------------
# custom dialect
# --------------------------------------------------------------------------


def cmd_message_add(args):
    studio = _studio(args)
    from .customdialect import add_message

    fields = [parse_field_spec(spec) for spec in args.field]
    message_id = args.id
    if message_id is None:
        low, high = studio.project.id_space.messages
        message_id = studio.catalog.next_free_id(low, high)
        if message_id is None:
            raise SystemExit(f"no free message id in range {low}-{high}")
        print(f"auto-assigned id {message_id}")
    message = build_message(args.name, message_id, args.description, fields)
    try:
        path = add_message(studio.project, message, studio.catalog)
    except DialectError as exc:
        detail = str(exc).replace("\n", "\n  ")
        raise SystemExit(f"cannot add message:\n  {detail}")
    print(f"wrote {path}")
    print("\n".join(message_xml(message, "")))
    if args.interface or args.requirement:
        set_metadata(
            studio.project, message.name,
            interface=args.interface or None,
            requirements=list(args.requirement) or None,
            namespace=args.namespace or None,
            category=args.category or None,
        )
        print(f"metadata recorded for {message.name}")


def cmd_message_rm(args):
    studio = _studio(args)
    name = args.name.upper()
    state = studio.resolution.states.get(name)
    if state is not None and state.origin == "standard":
        raise SystemExit(
            f"'{name}' is a standard message from {state.dialect}.xml and is "
            "never deleted.\n"
            f"Disable it for this vehicle instead:\n"
            f"  python3 -m mavstudio disable {name} "
            f"--vehicle {studio.profile.vehicle} --profile {studio.profile.name}"
        )
    try:
        path = remove_message(studio.project, name)
    except DialectError as exc:
        raise SystemExit(str(exc))
    print(f"removed {name} from {path}")


def cmd_message_deprecate(args):
    studio = _studio(args)
    try:
        path = deprecate_message(studio.project, args.name.upper(), args.since,
                                 args.replaced_by, args.text)
    except DialectError as exc:
        raise SystemExit(str(exc))
    print(f"marked {args.name.upper()} deprecated in {path}")


def cmd_message_clone(args):
    studio = _studio(args)
    try:
        clone = clone_as_custom(studio.project, studio.catalog, args.source.upper(),
                                args.name.upper(), args.id)
    except DialectError as exc:
        raise SystemExit(str(exc))
    print(f"cloned {args.source.upper()} -> {clone.name} (id {clone.id})")


def cmd_enum_add(args):
    studio = _studio(args)
    entries = []
    for index, spec in enumerate(args.entry):
        parts = spec.split(":", 2)
        entries.append({
            "name": parts[0],
            "value": parts[1] if len(parts) > 1 and parts[1] else str(index),
            "description": parts[2] if len(parts) > 2 else "",
        })
    try:
        path = add_enum(studio.project, args.name.upper(), args.description,
                        entries, args.bitmask, studio.catalog)
    except DialectError as exc:
        raise SystemExit(str(exc))
    print(f"wrote {path}")


def cmd_command_add(args):
    studio = _studio(args)
    params = []
    for index, spec in enumerate(args.param, start=1):
        parts = spec.split(":", 2)
        params.append({
            "index": index,
            "label": parts[0],
            "units": parts[1] if len(parts) > 1 else "",
            "description": parts[2] if len(parts) > 2 else parts[0],
        })
    try:
        path = add_command(studio.project, args.name.upper(), args.value,
                           args.description, params, studio.catalog)
    except DialectError as exc:
        raise SystemExit(str(exc))
    print(f"wrote {path}")


def cmd_meta_set(args):
    studio = _studio(args)
    name = args.message.upper()
    values = {}
    if args.interface is not None:
        values["interface"] = args.interface
    if args.requirement:
        values["requirements"] = list(args.requirement)
    if args.namespace is not None:
        values["namespace"] = args.namespace
    if args.category is not None:
        values["category"] = args.category
    if args.provider is not None:
        values["provider"] = args.provider
    if args.consumer:
        values["consumers"] = list(args.consumer)
    entry = set_metadata(studio.project, name, **values)
    print(f"{name}: {json.dumps(entry, ensure_ascii=False)}")


# --------------------------------------------------------------------------
# MOSA
# --------------------------------------------------------------------------


def _normalise_ref(ref: str) -> str:
    """Upper-case bare MAVLink names, but leave other data models' names alone.

    ``uav_motor_status`` -> ``UAV_MOTOR_STATUS`` while ``dds:TargetTrack``
    keeps its CamelCase, because that is the name in the DDS type system.
    """
    model, name = split_ref(ref)
    return name.upper() if model == "mavlink" else f"{model}:{name}"


def cmd_interface_add(args):
    project = load_project(args.project)
    contract = InterfaceContract(
        name=args.name.upper(),
        version=args.version,
        description=args.description,
        providers=list(args.provider),
        consumers=list(args.consumer),
        required_messages=[_normalise_ref(m) for m in args.required],
        optional_messages=[_normalise_ref(m) for m in args.optional],
        commands=[c.upper() for c in args.command],
        dependencies=dict(
            part.split(">=", 1) if ">=" in part else (part, "1.0.0")
            for part in args.depends
        ),
        requirements=list(args.requirement),
        aspects=dict(
            part.split("=", 1) if "=" in part else (part, "")
            for part in args.aspect
        ),
        transport=list(args.transport or ["mavlink2"]),
    )
    contract.dependencies = {k.strip(): v.strip()
                             for k, v in contract.dependencies.items()}
    print(f"wrote {save_interface(project, contract)}")
    external = external_refs(contract.all_messages)
    if external:
        models = ", ".join(sorted({m for m, _ in external}))
        print(f"  note: {len(external)} refs come from {models} and are not "
              "verified against the MAVLink catalog")


def cmd_module_add(args):
    project = load_project(args.project)
    manifest = ModuleManifest(
        name=args.name,
        vendor=args.vendor,
        version=args.version,
        description=args.description,
        interfaces=dict(
            part.split("=", 1) if "=" in part else (part, "1.0.0")
            for part in args.implements
        ),
        kind=args.kind,
        installed=not args.candidate,
        tx=[m.upper() for m in args.tx],
        rx=[m.upper() for m in args.rx],
        commands=[c.upper() for c in args.command],
        ports=dict(
            part.split("=", 1) if "=" in part else (part, "")
            for part in args.port
        ),
        aspects=dict(
            part.split("=", 1) if "=" in part else (part, "")
            for part in args.aspect
        ),
    )
    print(f"wrote {save_module(project, manifest)}")


def cmd_mosa(args):
    studio = _studio(args)
    interfaces = load_interfaces(studio.project)
    modules = load_modules(studio.project)
    if not interfaces and not modules:
        print("No interface contracts or module manifests defined yet.\n"
              "  python3 -m mavstudio interface add PROPULSION.MONITORING "
              "--required UAV_MOTOR_STATUS --provider ESC --consumer FC")
        return
    print("INTERFACE CONTRACTS")
    rows = [
        [c.name, c.version, ", ".join(c.providers) or "-",
         ", ".join(c.consumers) or "-", len(c.required_messages),
         len(c.optional_messages), len(c.commands)]
        for c in (interfaces[k] for k in sorted(interfaces))
    ]
    _print_table(rows, ["INTERFACE", "VERSION", "PROVIDERS", "CONSUMERS",
                        "REQ", "OPT", "CMDS"])
    if modules:
        print("\nCOMPATIBILITY MATRIX  (P provider, C consumer, "
              "! claimed but not satisfied,\n"
              "                       ? role never declared, ~ candidate part)")
        matrix = compatibility_matrix(interfaces, modules)
        rows = [[r["interface"], r["version"], *r["cells"]] for r in matrix["rows"]]
        _print_table(rows, ["INTERFACE", "VER", *matrix["modules"]])


def cmd_swap(args):
    project = load_project(args.project)
    modules = load_modules(project)
    interfaces = load_interfaces(project)
    current = modules.get(args.current)
    replacement = modules.get(args.replacement)
    if current is None or replacement is None:
        raise SystemExit(
            f"unknown module(s). Known: {', '.join(sorted(modules)) or '(none)'}"
        )
    print(f"Current module      {current.name} v{current.version} "
          f"({current.vendor or 'no vendor'})")
    print(f"Replacement         {replacement.name} v{replacement.version} "
          f"({replacement.vendor or 'no vendor'})")
    print()
    reports = compare_modules(current, replacement, interfaces)
    worst = "compatible"
    for report in reports:
        print(f"  {report.interface}: {report.current} -> {report.replacement}"
              f"   {report.verdict.upper()}  ({report.score * 100:.0f}%)")
        if report.version_note:
            print(f"    {report.version_note}")
        for message in report.missing_messages:
            print(f"    FAIL  message  {message}")
        for command in report.missing_commands:
            print(f"    FAIL  command  {command}")
        for aspect in report.aspects:
            mark = "PASS" if aspect.ok else "FAIL"
            detail = aspect.offered or "not declared"
            required = f" (needs {aspect.required})" if aspect.required else ""
            print(f"    {mark}  aspect   {aspect.aspect}: {detail}{required}")
        for ref in report.unverified:
            print(f"    ----  unverified  {ref} (data model not loadable here)")
        if report.verdict == "incompatible":
            worst = "incompatible"
        elif report.verdict == "partial" and worst != "incompatible":
            worst = "partial"
    total = swap_score(reports)
    print(f"\nReplacement compatibility  {total * 100:.0f}%")
    print(f"Verdict                    {worst.upper()}")
    if worst != "compatible":
        raise SystemExit(1)


# --------------------------------------------------------------------------
# build / validate / report
# --------------------------------------------------------------------------


def cmd_validate(args):
    studio = _studio(args)
    report = validate_all(studio.project, studio.catalog, studio.capability_set,
                          studio.resolution)
    for level in ("error", "warn", "info"):
        issues = [i for i in report.issues if i.level == level]
        if not issues:
            continue
        print(f"\n{level.upper()}  ({len(issues)})")
        for issue in issues:
            print(f"  [{issue.check}] {issue.subject}")
            print(f"      {issue.message}")
            if issue.hint:
                print(f"      -> {issue.hint}")
    counts = report.counts()
    print(f"\n{counts['error']} errors, {counts['warn']} warnings, "
          f"{counts['info']} notes")
    if report.errors:
        raise SystemExit(1)


def cmd_bandwidth(args):
    studio = _studio(args)
    budget = compute_budget(studio.resolution)
    print(f"Link  {budget.link_name}   {budget.bitrate} bit/s   "
          f"MAVLink {budget.mavlink_version}.0"
          f"{' signed' if budget.signing else ''}")
    print()
    rows = [
        [s.name, s.payload_bytes, s.frame_bytes, f"{s.rate_hz:g}",
         f"{s.bits_per_second / 1000:.1f}", f"{s.share * 100:.1f}%"]
        for s in budget.streams
    ]
    _print_table(rows, ["MESSAGE", "PAYLOAD", "FRAME", "RATE", "KBPS", "SHARE"])
    print()
    print(f"  payload      {budget.payload_bps / 1000:8.1f} kbps")
    print(f"  overhead     {budget.overhead_bps / 1000:8.1f} kbps")
    print(f"  total        {budget.total_bps / 1000:8.1f} kbps")
    print(f"  budget       {budget.budget_bps / 1000:8.1f} kbps "
          f"({(1 - budget.headroom) * 100:.0f}% of link)")
    print(f"  utilisation  {budget.utilisation * 100:7.1f} %  "
          f"[{bar(budget.utilisation)}]")
    for warning in budget.warnings:
        print(f"\n  WARNING  {warning}")


def cmd_build(args):
    studio = _studio(args)
    if not args.skip_validate:
        report = validate_all(studio.project, studio.catalog,
                              studio.capability_set, studio.resolution)
        if report.errors:
            print(f"{len(report.errors)} validation errors -- refusing to build.")
            for issue in report.errors[:10]:
                print(f"  [{issue.check}] {issue.subject}: {issue.message}")
            print("\nFix them, or re-run with --skip-validate.")
            raise SystemExit(1)
    result = build_profile_dialect(
        studio.project, studio.catalog, studio.resolution,
        output_path=args.output, prune_enums=not args.keep_all_enums,
    )
    print(f"wrote {result.dialect_path}")
    print(f"  {result.message_count} messages, {result.enum_count} enums, "
          f"{result.command_count} commands "
          f"({result.disabled_count} messages left out)")
    for warning in result.warnings:
        print(f"  WARNING {warning}")
    if args.lang:
        output_dir = args.generated or os.path.join(
            studio.project.build_dir, "generated", args.lang.replace("+", "p")
        )
        print(f"\nrunning mavgen ({args.lang}) -> {output_dir}")
        ok, output = generate_sources(result.dialect_path, args.lang, output_dir,
                                      args.wire_protocol)
        print(output.strip() or ("done" if ok else "failed"))
        if not ok:
            raise SystemExit(1)


def cmd_icd(args):
    studio = _studio(args)
    formats = tuple(args.format)
    written = write_icd(studio.project, studio.catalog, studio.capability_set,
                        studio.resolution, args.output, formats)
    for path in written:
        print(f"wrote {path}")


def cmd_upstream(args):
    studio = _studio(args)
    status = upstream_compare(studio.project, studio.catalog, studio.resolution)
    print(f"UPSTREAM   commit {status.commit or '?'}  {status.commit_subject}")
    print(f"           {status.definitions_dir}: "
          f"{status.upstream_message_count} messages, "
          f"{status.upstream_dialects} dialects")
    print(f"           base {status.base_dialect}.xml: "
          f"{status.base_message_count} messages")
    print()
    print(f"PROJECT    added   {len(status.added_messages)} messages, "
          f"{len(status.added_commands)} commands, "
          f"{len(status.added_enums)} enums")
    print(f"           enabled {status.enabled_messages}, "
          f"disabled {status.disabled_messages}")
    print(f"           modified standard files: "
          f"{len(status.modified_standard)}"
          f"{'   <- must be 0' if status.modified_standard else '   (good)'}")
    print(f"           id conflicts: {len(status.conflicts)}")
    for path, detail in status.modified_standard.items():
        print(f"             {path}: {detail}")
    for message_id, names in status.conflicts.items():
        print(f"             id {message_id}: {', '.join(names)}")
    if status.added_messages:
        print(f"\n  added: {', '.join(status.added_messages)}")


def cmd_web(args):
    from .web import serve

    serve(args.project, host=args.host, port=args.port, open_browser=not args.no_open)


def cmd_qt(args):
    from .qtapp import run

    raise SystemExit(run(args.project, args.vehicle, args.profile))


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------


class _SubparsersWithCommon:
    """Thin wrapper so every subparser inherits the global --vehicle/--profile."""

    def __init__(self, parser, common, dest="command"):
        self._actions = parser.add_subparsers(dest=dest, required=True)
        self._common = common

    def add_parser(self, name, **kwargs):
        parents = list(kwargs.pop("parents", [])) + [self._common]
        return self._actions.add_parser(name, parents=parents, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mavstudio",
        description="UAV MAVLink Studio -- browse, profile and extend MAVLink "
                    "message sets without editing upstream definitions.",
    )
    parser.add_argument("--project", default="uav",
                        help="project directory (default: uav)")
    parser.add_argument("--vehicle", default="", help="vehicle name")
    parser.add_argument("--profile", default="", help="profile name")

    # Repeated on every subcommand so that both orderings work:
    #   mavstudio --vehicle X list      and      mavstudio list --vehicle X
    # SUPPRESS keeps an omitted subcommand flag from clobbering the global one.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    common.add_argument("--vehicle", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    common.add_argument("--profile", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)

    sub = _SubparsersWithCommon(parser, common)

    p = sub.add_parser("init", help="create a project, vehicle and profiles")
    p.add_argument("--name", default="", help="project name")
    p.add_argument("--description", default="")
    p.add_argument("--dialect", default="", help="custom dialect name")
    p.add_argument("--profiles", nargs="+", default=["flight", "development"])
    p.add_argument("--id-range", nargs=2, type=int, metavar=("LOW", "HIGH"))
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("dashboard", help="one-screen project overview")
    p.set_defaults(func=cmd_dashboard)

    p = sub.add_parser("list", help="list messages with their profile state")
    p.add_argument("-s", "--search", default="", help="substring of the name")
    p.add_argument("-d", "--dialect", dest="dialect_filter", default="")
    p.add_argument("-c", "--category", default="")
    p.add_argument("--capability", default="")
    p.add_argument("--enabled", dest="enabled_only", action="store_true")
    p.add_argument("--disabled", dest="disabled_only", action="store_true")
    p.add_argument("--custom", dest="custom_only", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="inspect one message")
    p.add_argument("message")
    p.add_argument("--xml", action="store_true", help="also print the XML")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("capabilities", help="list capabilities and their state")
    p.set_defaults(func=cmd_capabilities)

    p = sub.add_parser("ids", help="message id space report")
    p.add_argument("--check", type=int, help="check one candidate id")
    p.set_defaults(func=cmd_ids)

    p = sub.add_parser("enable", help="enable messages in this profile")
    p.add_argument("messages", nargs="+")
    p.set_defaults(func=cmd_enable, off=False)

    p = sub.add_parser("disable", help="disable messages in this profile")
    p.add_argument("messages", nargs="+")
    p.set_defaults(func=cmd_enable, off=True)

    p = sub.add_parser("capability", help="turn a capability on or off")
    p.add_argument("key")
    p.add_argument("--off", action="store_true")
    p.set_defaults(func=cmd_capability)

    p = sub.add_parser("set", help="set rate / direction / priority")
    p.add_argument("message")
    p.add_argument("--rate", type=float, help="stream rate in Hz")
    p.add_argument("--tx", help="comma separated producers, e.g. FC")
    p.add_argument("--rx", help="comma separated consumers, e.g. GCS,Payload")
    p.add_argument("--priority", choices=["LOW", "NORMAL", "HIGH", "CRITICAL"])
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("profiles", help="list profiles in this project")
    p.set_defaults(func=cmd_profiles)

    p = sub.add_parser("diff", help="compare two profiles")
    p.add_argument("other_profile")
    p.add_argument("--other-vehicle", default="")
    p.set_defaults(func=cmd_diff)

    msg = sub.add_parser("message", help="custom dialect message editing")
    msg_sub = _SubparsersWithCommon(msg, common)

    p = msg_sub.add_parser("add", help="add a custom message")
    p.add_argument("name")
    p.add_argument("--id", type=int, help="message id (default: next free)")
    p.add_argument("-d", "--description", required=True)
    p.add_argument("-f", "--field", action="append", default=[],
                   metavar="NAME:TYPE[:UNITS[:ENUM[:DESC]]]",
                   help="repeatable, e.g. -f accel_x:float:m/s2")
    p.add_argument("--interface", default="")
    p.add_argument("--requirement", action="append", default=[])
    p.add_argument("--namespace", default="")
    p.add_argument("--category", default="")
    p.set_defaults(func=cmd_message_add)

    p = msg_sub.add_parser("rm", help="permanently delete a custom message")
    p.add_argument("name")
    p.set_defaults(func=cmd_message_rm)

    p = msg_sub.add_parser("deprecate", help="mark a custom message deprecated")
    p.add_argument("name")
    p.add_argument("--since", required=True, help="e.g. 2026-09")
    p.add_argument("--replaced-by", default="")
    p.add_argument("--text", default="")
    p.set_defaults(func=cmd_message_deprecate)

    p = msg_sub.add_parser("clone", help="clone a standard message as custom")
    p.add_argument("source")
    p.add_argument("name")
    p.add_argument("--id", type=int)
    p.set_defaults(func=cmd_message_clone)

    p = sub.add_parser("enum", help="add a custom enum")
    enum_sub = _SubparsersWithCommon(p, common)
    q = enum_sub.add_parser("add")
    q.add_argument("name")
    q.add_argument("-d", "--description", default="")
    q.add_argument("-e", "--entry", action="append", default=[],
                   metavar="NAME[:VALUE[:DESC]]")
    q.add_argument("--bitmask", action="store_true")
    q.set_defaults(func=cmd_enum_add)

    p = sub.add_parser("command", help="add a custom MAV_CMD")
    command_sub = _SubparsersWithCommon(p, common)
    q = command_sub.add_parser("add")
    q.add_argument("name")
    q.add_argument("value", type=int)
    q.add_argument("-d", "--description", required=True)
    q.add_argument("-p", "--param", action="append", default=[],
                   metavar="LABEL[:UNITS[:DESC]]")
    q.set_defaults(func=cmd_command_add)

    p = sub.add_parser("meta", help="message metadata (traceability)")
    meta_sub = _SubparsersWithCommon(p, common)
    q = meta_sub.add_parser("set")
    q.add_argument("message")
    q.add_argument("--interface")
    q.add_argument("--requirement", action="append", default=[])
    q.add_argument("--namespace")
    q.add_argument("--category")
    q.add_argument("--provider")
    q.add_argument("--consumer", action="append", default=[])
    q.set_defaults(func=cmd_meta_set)

    p = sub.add_parser("interface", help="MOSA interface contracts")
    interface_sub = _SubparsersWithCommon(p, common)
    q = interface_sub.add_parser("add")
    q.add_argument("name")
    q.add_argument("--version", default="1.0.0")
    q.add_argument("-d", "--description", default="")
    q.add_argument("--provider", action="append", default=[])
    q.add_argument("--consumer", action="append", default=[])
    q.add_argument("--required", action="append", default=[],
                   metavar="[MODEL:]NAME",
                   help="required message; prefix with a data model to go "
                        "beyond MAVLink, e.g. dds:PropulsionTelemetry. "
                        "Models: " + ", ".join(DATA_MODELS))
    q.add_argument("--optional", action="append", default=[],
                   metavar="[MODEL:]NAME")
    q.add_argument("--command", action="append", default=[])
    q.add_argument("--depends", action="append", default=[],
                   metavar="INTERFACE>=VERSION")
    q.add_argument("--requirement", action="append", default=[])
    q.add_argument("--aspect", action="append", default=[],
                   metavar="ASPECT[=VALUE]",
                   help="non-message aspect a provider must satisfy, e.g. "
                        "--aspect power=28VDC-40W. Standard aspects: "
                        + ", ".join(STANDARD_ASPECTS))
    # action="append" appends to its default, so default to None and fill in
    # the fallback afterwards rather than getting ["mavlink2", "mavlink2", ...].
    q.add_argument("--transport", action="append", default=None)
    q.set_defaults(func=cmd_interface_add)

    p = sub.add_parser("module", help="MOSA module manifests")
    module_sub = _SubparsersWithCommon(p, common)
    q = module_sub.add_parser("add")
    q.add_argument("name")
    q.add_argument("--vendor", default="")
    q.add_argument("--version", default="1.0.0")
    q.add_argument("-d", "--description", default="")
    q.add_argument("--implements", action="append", default=[],
                   metavar="INTERFACE=VERSION")
    q.add_argument("--kind", default="other",
                   choices=["fc", "mission_computer", "payload", "sensor",
                            "datalink", "gcs", "actuator", "other"])
    q.add_argument("--candidate", action="store_true",
                   help="a part being evaluated, not installed: takes part in "
                        "'swap' checks but is not enforced by 'validate'")
    q.add_argument("--tx", action="append", default=[])
    q.add_argument("--rx", action="append", default=[])
    q.add_argument("--command", action="append", default=[])
    q.add_argument("--port", action="append", default=[],
                   metavar="PORT[=VALUE]",
                   help="physical/logical port, e.g. --port ethernet=1000BASE-T")
    q.add_argument("--aspect", action="append", default=[],
                   metavar="ASPECT[=VALUE]",
                   help="non-message aspect this module satisfies")
    q.set_defaults(func=cmd_module_add)

    p = sub.add_parser("mosa", help="interface / module compatibility matrix")
    p.set_defaults(func=cmd_mosa)

    p = sub.add_parser("swap", help="check a module replacement")
    p.add_argument("current")
    p.add_argument("replacement")
    p.set_defaults(func=cmd_swap)

    p = sub.add_parser("validate", help="run every check")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("bandwidth", help="telemetry budget")
    p.set_defaults(func=cmd_bandwidth)

    p = sub.add_parser("build", help="emit the profile dialect (and sources)")
    p.add_argument("-o", "--output", default="")
    p.add_argument("--lang", choices=MAVGEN_LANGUAGES,
                   help="also run mavgen for this language")
    p.add_argument("--generated", default="", help="mavgen output directory")
    p.add_argument("--wire-protocol", default="2.0", choices=["1.0", "2.0"])
    p.add_argument("--keep-all-enums", action="store_true")
    p.add_argument("--skip-validate", action="store_true")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("icd", help="generate the interface control document")
    p.add_argument("-o", "--output", default="")
    p.add_argument("--format", nargs="+", default=["md", "html", "csv"],
                   choices=["md", "html", "csv"])
    p.set_defaults(func=cmd_icd)

    p = sub.add_parser("upstream", help="compare the project against upstream")
    p.set_defaults(func=cmd_upstream)

    p = sub.add_parser("web", help="run the browser UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(func=cmd_web)

    p = sub.add_parser("qt", help="run the Qt desktop UI (needs PySide6)")
    p.set_defaults(func=cmd_qt)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except DialectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
