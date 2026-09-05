"""YAML load/save helpers shared by the project, profile and MOSA layers."""

from __future__ import annotations

import os
from typing import Any

try:  # pragma: no cover - trivial import guard
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "mavstudio needs PyYAML. Install it with:  python3 -m pip install pyyaml"
    ) from exc


def load_yaml(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return {} if default is None else default
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return {} if data is None else data


def save_yaml(path: str, data: Any) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(
            data,
            handle,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=100,
        )


def slug(text: str) -> str:
    """Filesystem-safe identifier used for profile / interface file names."""
    keep = [c if (c.isalnum() or c in "-_.") else "-" for c in text.strip()]
    return "".join(keep).strip("-").lower() or "unnamed"


def ident(text: str) -> str:
    """Slug usable as a C identifier.

    mavgen derives preprocessor macros from the dialect filename, so a build
    artefact named ``my_uav_swan-h200_flight.xml`` yields the invalid macro
    ``MAVLINK_MY_UAV_SWAN-H200_FLIGHT_XML_HASH``. Keep build filenames to
    ``[A-Za-z0-9_]``.
    """
    cleaned = "".join(c if (c.isalnum() and c.isascii()) else "_" for c in text)
    cleaned = cleaned.strip("_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    if cleaned and cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned.lower() or "unnamed"
