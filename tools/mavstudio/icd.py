"""Interface Control Document generation.

The ICD is generated from the same profile the firmware is built from, so the
document cannot drift from the code. Markdown is the source format; HTML and
CSV are rendered from the same data for review and for import into a
requirements tool.
"""

from __future__ import annotations

import csv
import io
import os
from datetime import date

from .bandwidth import compute_budget, frame_bytes
from .capabilities import CapabilitySet
from .catalog import Catalog
from .customdialect import load_custom_dialect, load_metadata
from .mosa import load_interfaces, load_modules
from .profile import Resolution
from .project import Project


def _escape_md(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def generate_markdown(project: Project, catalog: Catalog,
                      capability_set: CapabilitySet,
                      resolution: Resolution) -> str:
    profile = resolution.profile
    metadata = load_metadata(project)
    custom = load_custom_dialect(project)
    custom_names = {m.name for m in custom.messages}
    interfaces = load_interfaces(project)
    modules = load_modules(project)
    budget = compute_budget(resolution)
    enabled = resolution.enabled_messages()

    out: list[str] = []
    add = out.append

    add(f"# Interface Control Document -- {profile.vehicle} / {profile.name}")
    add("")
    add(f"**Project:** {project.name}  ")
    add(f"**Custom dialect:** `{project.dialect.name}.xml` "
        f"(includes `{project.dialect.base}`)  ")
    add(f"**MAVLink:** {profile.link.mavlink_version}.0"
        f"{', signed' if profile.link.signing else ''}  ")
    add(f"**Generated:** {date.today().isoformat()} by `tools/mavstudio`  ")
    if project.description:
        add("")
        add(project.description)
    add("")

    # -- summary ----------------------------------------------------------
    add("## 1. Summary")
    add("")
    add("| Item | Value |")
    add("| --- | --- |")
    add(f"| Messages enabled | {len(enabled)} |")
    add(f"| Messages available but disabled | {len(resolution.disabled_messages())} |")
    add(f"| Custom messages | {len(custom_names)} |")
    add(f"| Capabilities on | "
        f"{sum(1 for v in resolution.capability_states.values() if v)} "
        f"of {len(resolution.capability_states)} |")
    add(f"| Components | {', '.join(profile.components)} |")
    add(f"| Link | {profile.link.name}, {profile.link.bitrate} bit/s |")
    add(f"| Periodic load | {budget.total_bps / 1000:.1f} kbps "
        f"({budget.utilisation * 100:.1f}% of link) |")
    add("")

    # -- capabilities -----------------------------------------------------
    add("## 2. Enabled capabilities")
    add("")
    add("| Group | Capability | State | Messages |")
    add("| --- | --- | --- | --- |")
    for group, capabilities in capability_set.groups().items():
        for capability in capabilities:
            on = resolution.capability_states.get(capability.key, False)
            count = len([
                s for s in enabled if s.capability == capability.key
            ])
            add(f"| {group} | {capability.title} | "
                f"{'ON' if on else 'off'} | {count} |")
    add("")

    # -- message list -----------------------------------------------------
    add("## 3. Enabled messages")
    add("")
    add("| ID | Message | Source | Category | TX | RX | Rate (Hz) | Bytes | "
        "Interface | Requirements |")
    add("| ---: | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |")
    for state in enabled:
        meta = metadata.get(state.name, {})
        add(
            f"| {state.id} | `{state.name}` | {state.dialect} | {state.category} "
            f"| {', '.join(state.tx) or '-'} | {', '.join(state.rx) or '-'} "
            f"| {state.rate_hz or '-'} | {state.payload_bytes} "
            f"| {meta.get('interface', '-')} "
            f"| {', '.join(meta.get('requirements', [])) or '-'} |"
        )
    add("")

    # -- field detail -----------------------------------------------------
    add("## 4. Message definitions")
    add("")
    for state in enabled:
        message = next(
            (m for m in custom.messages if m.name == state.name), None
        ) or catalog.message(state.name)
        if message is None:
            continue
        meta = metadata.get(state.name, {})
        add(f"### {state.id} `{state.name}`")
        add("")
        if message.description:
            add(_escape_md(message.description))
            add("")
        details = [f"Source: `{state.dialect}.xml`", f"Payload: {message.payload_bytes} B"]
        if state.rate_hz:
            details.append(f"Rate: {state.rate_hz} Hz")
            details.append(
                f"Load: {frame_bytes(message.payload_bytes, profile.link.mavlink_version, profile.link.signing) * 10 * state.rate_hz / 1000:.1f} kbps"
            )
        if state.tx:
            details.append(f"TX: {', '.join(state.tx)}")
        if state.rx:
            details.append(f"RX: {', '.join(state.rx)}")
        if meta.get("interface"):
            details.append(f"Interface: {meta['interface']}")
        add("*" + " &middot; ".join(details) + "*")
        add("")
        add("| # | Field | Type | Units | Enum | Ext | Description |")
        add("| ---: | --- | --- | --- | --- | :-: | --- |")
        for index, field in enumerate(message.fields, start=1):
            add(
                f"| {index} | `{field.name}` | `{field.type}` "
                f"| {field.units or '-'} | {field.enum or '-'} "
                f"| {'Y' if field.is_extension else ''} "
                f"| {_escape_md(field.description)} |"
            )
        add("")

    # -- commands ---------------------------------------------------------
    commands = resolution.enabled_commands()
    add("## 5. Enabled commands")
    add("")
    add(f"{len(commands)} MAV_CMD entries are enabled in this profile.")
    add("")
    add("| Value | Command | Description |")
    add("| ---: | --- | --- |")
    for name in commands:
        entry = catalog.commands.get(name)
        if entry is None:
            continue
        add(f"| {entry.value} | `{name}` | {_escape_md(entry.description)} |")
    add("")

    # -- MOSA -------------------------------------------------------------
    add("## 6. Interface contracts (MOSA)")
    add("")
    if not interfaces:
        add("_No interface contracts defined._")
        add("")
    for name in sorted(interfaces):
        contract = interfaces[name]
        add(f"### {name} v{contract.version}")
        add("")
        if contract.description:
            add(_escape_md(contract.description))
            add("")
        add("| Item | Value |")
        add("| --- | --- |")
        add(f"| Transport | {', '.join(contract.transport)} |")
        add(f"| Providers | {', '.join(contract.providers) or '-'} |")
        add(f"| Consumers | {', '.join(contract.consumers) or '-'} |")
        add(f"| Required messages | "
            f"{', '.join(f'`{m}`' for m in contract.required_messages) or '-'} |")
        add(f"| Optional messages | "
            f"{', '.join(f'`{m}`' for m in contract.optional_messages) or '-'} |")
        add(f"| Commands | "
            f"{', '.join(f'`{c}`' for c in contract.commands) or '-'} |")
        add(f"| Dependencies | "
            f"{', '.join(f'{k} >= {v}' for k, v in contract.dependencies.items()) or '-'} |")
        add(f"| Requirements | {', '.join(contract.requirements) or '-'} |")
        add("")

    if modules:
        add("### Module manifests")
        add("")
        add("| Module | Vendor | Version | Interfaces |")
        add("| --- | --- | --- | --- |")
        for name in sorted(modules):
            manifest = modules[name]
            claims = ", ".join(f"{k} {v}" for k, v in manifest.interfaces.items())
            add(f"| {name} | {manifest.vendor or '-'} | {manifest.version} "
                f"| {claims or '-'} |")
        add("")

    # -- traceability -----------------------------------------------------
    add("## 7. Requirement traceability")
    add("")
    rows = [
        (requirement, state.name, metadata.get(state.name, {}).get("interface", "-"))
        for state in enabled
        for requirement in metadata.get(state.name, {}).get("requirements", [])
    ]
    if rows:
        add("| Requirement | Message | Interface |")
        add("| --- | --- | --- |")
        for requirement, message_name, interface in sorted(rows):
            add(f"| {requirement} | `{message_name}` | {interface} |")
    else:
        add("_No requirement ids recorded. Attach them with_ "
            "`mavstudio meta set <MESSAGE> --requirement <ID>`.")
    add("")

    # -- bandwidth --------------------------------------------------------
    add("## 8. Telemetry budget")
    add("")
    add(f"Link: **{profile.link.name}**, {profile.link.bitrate} bit/s, "
        f"{profile.link.headroom * 100:.0f}% headroom reserved.")
    add("")
    add("| Message | Bytes/frame | Rate (Hz) | kbps | Share |")
    add("| --- | ---: | ---: | ---: | ---: |")
    for stream in budget.streams:
        add(f"| `{stream.name}` | {stream.frame_bytes} | {stream.rate_hz} "
            f"| {stream.bits_per_second / 1000:.1f} | {stream.share * 100:.1f}% |")
    add(f"| **Total** | | | **{budget.total_bps / 1000:.1f}** "
        f"| {budget.utilisation * 100:.1f}% of link |")
    add("")
    for warning in budget.warnings:
        add(f"> **Warning** {warning}")
        add("")
    return "\n".join(out) + "\n"


def generate_csv(project: Project, catalog: Catalog,
                 resolution: Resolution) -> str:
    """Flat message/field export for import into a requirements tool."""
    metadata = load_metadata(project)
    custom = {m.name: m for m in load_custom_dialect(project).messages}
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "message_id", "message", "source", "category", "enabled", "tx", "rx",
        "rate_hz", "payload_bytes", "interface", "requirements",
        "field_index", "field", "type", "units", "enum", "extension",
        "description",
    ])
    for state in sorted(resolution.states.values(), key=lambda s: s.id):
        message = custom.get(state.name) or catalog.message(state.name)
        if message is None:
            continue
        meta = metadata.get(state.name, {})
        base = [
            state.id, state.name, state.dialect, state.category,
            "yes" if state.enabled else "no",
            ";".join(state.tx), ";".join(state.rx), state.rate_hz or "",
            state.payload_bytes, meta.get("interface", ""),
            ";".join(meta.get("requirements", [])),
        ]
        for index, field in enumerate(message.fields, start=1):
            writer.writerow(base + [
                index, field.name, field.type, field.units, field.enum,
                "yes" if field.is_extension else "", field.description,
            ])
    return buffer.getvalue()


def markdown_to_html(markdown: str, title: str) -> str:
    """Minimal Markdown -> HTML for the tables this module emits."""
    lines = markdown.splitlines()
    html: list[str] = []
    in_table = False

    def close_table():
        nonlocal in_table
        if in_table:
            html.append("</tbody></table>")
            in_table = False

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            separator = (
                index + 1 < len(lines)
                and set(lines[index + 1].strip().strip("|").replace("|", "")) <= set("-: ")
                and "-" in lines[index + 1]
            )
            if not in_table and separator:
                html.append('<table><thead><tr>'
                            + "".join(f"<th>{_inline(c)}</th>" for c in cells)
                            + "</tr></thead><tbody>")
                in_table = True
                index += 2
                continue
            if in_table:
                html.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells)
                            + "</tr>")
                index += 1
                continue
        close_table()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            html.append(f"<h{level}>{_inline(stripped[level:].strip())}</h{level}>")
        elif stripped.startswith(">"):
            html.append(f"<blockquote>{_inline(stripped[1:].strip())}</blockquote>")
        elif stripped:
            html.append(f"<p>{_inline(stripped)}</p>")
        index += 1
    close_table()

    body = "\n".join(html)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font: 14px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif;
       max-width: 1100px; margin: 2rem auto; padding: 0 1.5rem; color: #1a1a1a; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: .4rem; }}
h2 {{ margin-top: 2.4rem; border-bottom: 1px solid #ddd; padding-bottom: .3rem; }}
h3 {{ margin-top: 1.8rem; }}
table {{ border-collapse: collapse; width: 100%; margin: .8rem 0; font-size: 13px; }}
th, td {{ border: 1px solid #d8d8d8; padding: .35rem .55rem; text-align: left;
          vertical-align: top; }}
th {{ background: #f2f4f7; }}
tr:nth-child(even) td {{ background: #fafbfc; }}
code {{ background: #f2f4f7; padding: 1px 4px; border-radius: 3px;
        font-family: ui-monospace, Menlo, Consolas, monospace; }}
blockquote {{ border-left: 4px solid #e0a800; background: #fffbf0;
              margin: 1rem 0; padding: .6rem 1rem; }}
</style></head><body>
{body}
</body></html>
"""


def _inline(text: str) -> str:
    import html as html_module
    import re

    escaped = html_module.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
    return escaped.replace("&amp;middot;", "&middot;")


def write_icd(project: Project, catalog: Catalog,
              capability_set: CapabilitySet, resolution: Resolution,
              output_dir: str = "", formats=("md", "html", "csv")) -> list[str]:
    from .store import slug

    output_dir = output_dir or os.path.join(project.build_dir, "icd")
    os.makedirs(output_dir, exist_ok=True)
    stem = f"icd_{slug(resolution.profile.vehicle)}_{slug(resolution.profile.name)}"
    markdown = generate_markdown(project, catalog, capability_set, resolution)
    written = []
    if "md" in formats:
        path = os.path.join(output_dir, f"{stem}.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(markdown)
        written.append(path)
    if "html" in formats:
        path = os.path.join(output_dir, f"{stem}.html")
        title = (
            f"ICD -- {resolution.profile.vehicle} / {resolution.profile.name}"
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(markdown_to_html(markdown, title))
        written.append(path)
    if "csv" in formats:
        path = os.path.join(output_dir, f"{stem}.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(generate_csv(project, catalog, resolution))
        written.append(path)
    return written
