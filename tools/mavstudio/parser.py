"""Read and write MAVLink definition XML.

Parsing uses the standard library only. Writing produces the same layout
``xmllint -format`` produces (two-space indent, no self-closing shortcuts for
elements with text), so generated files survive ``scripts/format_xml.sh -c``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from .model import Dialect, Enum, EnumEntry, Field, Message, Param

# Attributes copied verbatim from <field> onto Field, keyed by XML name.
_FIELD_ATTRS = (
    "units",
    "enum",
    "display",
    "increment",
    "minValue",
    "maxValue",
    "invalid",
    "instance",
    "print_format",
    "multiplier",
    "default",
)

_PARAM_ATTRS = (
    "label",
    "units",
    "enum",
    "increment",
    "minValue",
    "maxValue",
    "reserved",
    "default",
)

_ENTRY_ATTRS = ("hasLocation", "isDestination", "missionOnly")


def _text(element: ET.Element | None) -> str:
    """Collapse an element's text into a single-line string."""
    if element is None or element.text is None:
        return ""
    return " ".join(element.text.split())


def _lifecycle(parent: ET.Element, tag: str) -> tuple[str, str, str] | None:
    """Read a <deprecated> or <superseded> element into (since, replaced_by, text)."""
    node = parent.find(tag)
    if node is None:
        return None
    return (
        node.get("since", ""),
        node.get("replaced_by", ""),
        _text(node),
    )


def _deprecated(parent: ET.Element) -> tuple[str, str, str] | None:
    return _lifecycle(parent, "deprecated")


def _superseded(parent: ET.Element) -> tuple[str, str, str] | None:
    return _lifecycle(parent, "superseded")


def parse_file(path: str) -> Dialect:
    """Parse one dialect XML file into a :class:`Dialect`."""
    tree = ET.parse(path)
    root = tree.getroot()
    name = os.path.splitext(os.path.basename(path))[0]
    dialect = Dialect(
        name=name,
        path=path,
        includes=[_text(i) for i in root.findall("include")],
        version=_text(root.find("version")),
        dialect_number=_text(root.find("dialect")),
    )

    enums_node = root.find("enums")
    if enums_node is not None:
        for enum_node in enums_node.findall("enum"):
            dialect.enums.append(_parse_enum(enum_node, name))

    messages_node = root.find("messages")
    if messages_node is not None:
        for message_node in messages_node.findall("message"):
            dialect.messages.append(_parse_message(message_node, name))

    return dialect


def _parse_enum(node: ET.Element, dialect_name: str) -> Enum:
    enum = Enum(
        name=node.get("name", ""),
        description=_text(node.find("description")),
        bitmask=node.get("bitmask", "").lower() == "true",
        dialect=dialect_name,
        deprecated=_deprecated(node),
        superseded=_superseded(node),
    )
    for entry_node in node.findall("entry"):
        entry = EnumEntry(
            name=entry_node.get("name", ""),
            value=entry_node.get("value", ""),
            description=_text(entry_node.find("description")),
            deprecated=_deprecated(entry_node),
            superseded=_superseded(entry_node),
            wip=entry_node.find("wip") is not None,
        )
        for attr in _ENTRY_ATTRS:
            setattr(entry, attr, entry_node.get(attr, ""))
        for param_node in entry_node.findall("param"):
            param = Param(
                index=int(param_node.get("index", "0")),
                description=_text(param_node),
            )
            for attr in _PARAM_ATTRS:
                setattr(param, attr, param_node.get(attr, ""))
            entry.params.append(param)
        enum.entries.append(entry)
    return enum


def _parse_message(node: ET.Element, dialect_name: str) -> Message:
    message = Message(
        id=int(node.get("id", "0")),
        name=node.get("name", ""),
        description=_text(node.find("description")),
        dialect=dialect_name,
        deprecated=_deprecated(node),
        superseded=_superseded(node),
        wip=node.find("wip") is not None,
    )
    in_extensions = False
    for child in node:
        if child.tag == "extensions":
            in_extensions = True
        elif child.tag == "field":
            field = Field(
                name=child.get("name", ""),
                type=child.get("type", ""),
                description=_text(child),
                is_extension=in_extensions,
            )
            for attr in _FIELD_ATTRS:
                setattr(field, attr, child.get(attr, ""))
            message.fields.append(field)
    return message


def load_registry_files(definitions_dir: str) -> list[Dialect]:
    """Parse every ``*.xml`` in a definitions directory, sorted by name."""
    dialects = []
    for entry in sorted(os.listdir(definitions_dir)):
        if entry.endswith(".xml"):
            dialects.append(parse_file(os.path.join(definitions_dir, entry)))
    return dialects


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------


def _attrs(pairs: list[tuple[str, str]]) -> str:
    return "".join(f" {k}={quoteattr(v)}" for k, v in pairs if v)


def _description_xml(text: str, indent: str) -> list[str]:
    if not text:
        return []
    return [f"{indent}<description>{escape(text)}</description>"]


def _lifecycle_xml(entry: tuple[str, str, str] | None, tag: str,
                   indent: str) -> list[str]:
    if entry is None:
        return []
    since, replaced_by, text = entry
    # mavschema.xsd requires both attributes to be present even when empty --
    # upstream writes replaced_by="" for entries with no replacement.
    attrs = f" since={quoteattr(since)} replaced_by={quoteattr(replaced_by)}"
    if text:
        return [f"{indent}<{tag}{attrs}>{escape(text)}</{tag}>"]
    return [f"{indent}<{tag}{attrs}/>"]


def _deprecated_xml(dep: tuple[str, str, str] | None, indent: str) -> list[str]:
    return _lifecycle_xml(dep, "deprecated", indent)


def _superseded_xml(sup: tuple[str, str, str] | None, indent: str) -> list[str]:
    return _lifecycle_xml(sup, "superseded", indent)


def field_xml(field: Field, indent: str) -> str:
    pairs = [("type", field.type), ("name", field.name)]
    pairs += [(a, getattr(field, a)) for a in _FIELD_ATTRS]
    attrs = _attrs(pairs)
    if field.description:
        return f"{indent}<field{attrs}>{escape(field.description)}</field>"
    return f"{indent}<field{attrs}/>"


def message_xml(message: Message, indent: str = "    ") -> list[str]:
    inner = indent + "  "
    lines = [f'{indent}<message id="{message.id}" name="{escape(message.name)}">']
    if message.wip:
        lines.append(f"{inner}<wip/>")
    lines += _deprecated_xml(message.deprecated, inner)
    lines += _superseded_xml(message.superseded, inner)
    lines += _description_xml(message.description, inner)
    emitted_extensions = False
    for field in message.fields:
        if field.is_extension and not emitted_extensions:
            lines.append(f"{inner}<extensions/>")
            emitted_extensions = True
        lines.append(field_xml(field, inner))
    lines.append(f"{indent}</message>")
    return lines


def enum_xml(enum: Enum, indent: str = "    ") -> list[str]:
    inner = indent + "  "
    attrs = _attrs([("name", enum.name), ("bitmask", "true" if enum.bitmask else "")])
    lines = [f"{indent}<enum{attrs}>"]
    lines += _deprecated_xml(enum.deprecated, inner)
    lines += _superseded_xml(enum.superseded, inner)
    lines += _description_xml(enum.description, inner)
    for entry in enum.entries:
        entry_inner = inner + "  "
        pairs = [("value", entry.value), ("name", entry.name)]
        pairs += [(a, getattr(entry, a)) for a in _ENTRY_ATTRS]
        entry_attrs = _attrs(pairs)
        body: list[str] = []
        if entry.wip:
            body.append(f"{entry_inner}<wip/>")
        body += _deprecated_xml(entry.deprecated, entry_inner)
        body += _superseded_xml(entry.superseded, entry_inner)
        body += _description_xml(entry.description, entry_inner)
        for param in entry.params:
            param_pairs = [("index", str(param.index))]
            param_pairs += [(a, getattr(param, a)) for a in _PARAM_ATTRS]
            param_attrs = _attrs(param_pairs)
            if param.description:
                body.append(
                    f"{entry_inner}<param{param_attrs}>"
                    f"{escape(param.description)}</param>"
                )
            else:
                body.append(f"{entry_inner}<param{param_attrs}/>")
        if body:
            lines.append(f"{inner}<entry{entry_attrs}>")
            lines += body
            lines.append(f"{inner}</entry>")
        else:
            lines.append(f"{inner}<entry{entry_attrs}/>")
    lines.append(f"{indent}</enum>")
    return lines


def dialect_xml(
    includes: list[str],
    version: str,
    dialect_number: str,
    enums: list[Enum],
    messages: list[Message],
    header_comment: str = "",
) -> str:
    """Render a complete dialect document."""
    lines = ['<?xml version="1.0"?>', "<mavlink>"]
    if header_comment:
        for line in header_comment.strip().splitlines():
            # A double hyphen is illegal inside an XML comment.
            text = line.strip().replace("--", "-")
            lines.append(f"  <!-- {text} -->")
    for include in includes:
        lines.append(f"  <include>{escape(include)}</include>")
    if version:
        lines.append(f"  <version>{escape(version)}</version>")
    if dialect_number:
        lines.append(f"  <dialect>{escape(dialect_number)}</dialect>")
    if enums:
        lines.append("  <enums>")
        for enum in enums:
            lines += enum_xml(enum, "    ")
        lines.append("  </enums>")
    if messages:
        lines.append("  <messages>")
        for message in messages:
            lines += message_xml(message, "    ")
        lines.append("  </messages>")
    lines.append("</mavlink>")
    return "\n".join(lines) + "\n"


def write_xml(path: str, content: str, normalise: bool = True) -> None:
    """Write a dialect document, normalising with xmllint when available.

    Normalising keeps generated files byte-identical to what
    ``scripts/format_xml.sh`` would produce, so CI's format check stays green.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    if not normalise or shutil.which("xmllint") is None:
        return
    try:
        formatted = subprocess.run(
            ["xmllint", "--format", path],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return
    stripped = "\n".join(line.rstrip() for line in formatted.splitlines()) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(stripped)
