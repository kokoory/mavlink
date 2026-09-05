"""Local browser UI for mavstudio.

A stdlib ``http.server`` serving a JSON API plus one static page. No web
framework, no build step -- run it and open the URL.

The server binds to loopback by default. It edits files in the project, so do
not expose it to a network you do not control.
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .bandwidth import compute_budget
from .build import build_profile_dialect, generate_sources
from .customdialect import (
    DialectError,
    add_message,
    build_message,
    check_id,
    deprecate_message,
    id_space_report,
    load_custom_dialect,
    load_metadata,
    remove_message,
    set_metadata,
    update_message,
)
from .icd import write_icd
from .mosa import compatibility_matrix, load_interfaces, load_modules
from .parser import message_xml
from .profile import MessageOverride, list_profiles
from .upstream import compare as upstream_compare
from .validate import validate_all
from .workspace import open_studio

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class StudioAPI:
    """All request handling that touches the project lives here."""

    def __init__(self, project_root: str):
        self.project_root = project_root
        self.lock = threading.Lock()

    def studio(self, vehicle: str = "", profile: str = ""):
        return open_studio(self.project_root, vehicle, profile)

    # -- reads ------------------------------------------------------------

    def state(self, vehicle: str, profile: str) -> dict:
        studio = self.studio(vehicle, profile)
        metadata = load_metadata(studio.project)
        custom = {m.name: m for m in load_custom_dialect(studio.project).messages}
        resolution = studio.resolution

        messages = []
        for state in sorted(resolution.states.values(), key=lambda s: s.id):
            meta = metadata.get(state.name, {})
            messages.append({
                "name": state.name,
                "id": state.id,
                "dialect": state.dialect,
                "origin": state.origin,
                "enabled": state.enabled,
                "reason": state.reason,
                "capability": state.capability,
                "capabilityTitle": state.capability_title,
                "category": state.category,
                "status": state.status,
                "bytes": state.payload_bytes,
                "tx": state.tx,
                "rx": state.rx,
                "rate": state.rate_hz,
                "priority": state.priority,
                "required": state.required,
                "deletable": state.deletable,
                "note": state.note,
                "interface": meta.get("interface", ""),
                "requirements": meta.get("requirements", []),
            })

        capabilities = []
        for group, items in studio.capability_set.groups().items():
            for capability in items:
                capabilities.append({
                    "key": capability.key,
                    "title": capability.title,
                    "group": group,
                    "category": capability.category,
                    "required": capability.required,
                    "enabled": resolution.capability_states.get(capability.key, False),
                    "messages": sorted(
                        studio.capability_set.messages_for(
                            capability.key, studio.catalog
                        )
                    ),
                })

        budget = compute_budget(resolution)
        report = validate_all(studio.project, studio.catalog,
                              studio.capability_set, resolution)
        status = upstream_compare(studio.project, studio.catalog, resolution)
        interfaces = load_interfaces(studio.project)
        modules = load_modules(studio.project)

        return {
            "project": {
                "name": studio.project.name,
                "root": studio.project.root,
                "dialect": studio.project.dialect.name,
                "dialectPath": studio.project.dialect.path,
                "base": studio.project.dialect.base,
                "idRange": list(studio.project.id_space.messages),
                "vehicles": {
                    name: {"description": v.description, "profiles": v.profiles}
                    for name, v in studio.project.vehicles.items()
                },
                "profiles": [
                    {"vehicle": v, "profile": p}
                    for v, p in list_profiles(studio.project)
                ],
            },
            "current": {
                "vehicle": resolution.profile.vehicle,
                "profile": resolution.profile.name,
                "description": resolution.profile.description,
                "components": resolution.profile.components,
                "link": {
                    "name": resolution.profile.link.name,
                    "bitrate": resolution.profile.link.bitrate,
                    "mavlinkVersion": resolution.profile.link.mavlink_version,
                    "signing": resolution.profile.link.signing,
                    "headroom": resolution.profile.link.headroom,
                },
            },
            "messages": messages,
            "capabilities": capabilities,
            "dialects": sorted(studio.catalog.dialects),
            "categories": sorted({m["category"] for m in messages}),
            "commands": [
                {"name": name, "enabled": resolution.command_states.get(name, False),
                 "value": entry.value,
                 "description": entry.description}
                for name, entry in sorted(studio.catalog.commands.items())
            ],
            "customMessages": sorted(custom),
            "idSpace": id_space_report(studio.project, studio.catalog),
            "bandwidth": {
                "linkName": budget.link_name,
                "bitrate": budget.bitrate,
                "totalBps": budget.total_bps,
                "payloadBps": budget.payload_bps,
                "overheadBps": budget.overhead_bps,
                "budgetBps": budget.budget_bps,
                "utilisation": budget.utilisation,
                "warnings": budget.warnings,
                "unrated": len(budget.unrated),
                "streams": [
                    {"name": s.name, "payload": s.payload_bytes,
                     "frame": s.frame_bytes, "rate": s.rate_hz,
                     "bps": s.bits_per_second, "share": s.share}
                    for s in budget.streams
                ],
            },
            "validation": {
                "counts": report.counts(),
                "issues": [
                    {"level": i.level, "check": i.check, "subject": i.subject,
                     "message": i.message, "hint": i.hint}
                    for i in report.issues
                ],
            },
            "upstream": {
                "commit": status.commit,
                "subject": status.commit_subject,
                "messageCount": status.upstream_message_count,
                "dialectCount": status.upstream_dialects,
                "baseDialect": status.base_dialect,
                "baseMessageCount": status.base_message_count,
                "added": status.added_messages,
                "addedCommands": status.added_commands,
                "addedEnums": status.added_enums,
                "enabled": status.enabled_messages,
                "disabled": status.disabled_messages,
                "modifiedStandard": status.modified_standard,
                "conflicts": {str(k): v for k, v in status.conflicts.items()},
            },
            "mosa": {
                "interfaces": [
                    {**interfaces[k].to_dict()} for k in sorted(interfaces)
                ],
                "modules": [
                    {**modules[k].to_dict()} for k in sorted(modules)
                ],
                "matrix": compatibility_matrix(interfaces, modules),
            },
            "enums": sorted(studio.catalog.enums),
        }

    def message_detail(self, vehicle: str, profile: str, name: str) -> dict:
        studio = self.studio(vehicle, profile)
        custom = {m.name: m for m in load_custom_dialect(studio.project).messages}
        message = custom.get(name) or studio.catalog.message(name)
        if message is None:
            raise KeyError(name)
        state = studio.resolution.states.get(name)
        return {
            "name": name,
            "description": message.description,
            "xml": "\n".join(message_xml(message, "")),
            "fields": [
                {"name": f.name, "type": f.type, "size": f.size,
                 "units": f.units, "enum": f.enum, "display": f.display,
                 "invalid": f.invalid, "instance": f.instance,
                 "extension": f.is_extension, "description": f.description}
                for f in message.fields
            ],
            "state": {
                "enabled": state.enabled if state else False,
                "reason": state.reason if state else "",
                "deletable": state.deletable if state else False,
                "required": state.required if state else False,
                "origin": state.origin if state else "standard",
            },
            "metadata": load_metadata(studio.project).get(name, {}),
        }

    # -- writes -----------------------------------------------------------

    def toggle_message(self, body: dict) -> dict:
        studio = self.studio(body.get("vehicle", ""), body.get("profile", ""))
        for name in body.get("names", []):
            override = studio.profile.messages.setdefault(name, MessageOverride())
            override.enabled = bool(body.get("enabled"))
        studio.profile.save(studio.project)
        return {"ok": True}

    def toggle_capability(self, body: dict) -> dict:
        studio = self.studio(body.get("vehicle", ""), body.get("profile", ""))
        key = body["key"]
        capability = studio.capability_set.get(key)
        if capability is None:
            raise KeyError(key)
        if capability.required and not body.get("enabled"):
            raise DialectError(f"'{capability.title}' is required and stays on")
        studio.profile.capabilities[key] = bool(body.get("enabled"))
        studio.profile.save(studio.project)
        return {"ok": True}

    def update_override(self, body: dict) -> dict:
        studio = self.studio(body.get("vehicle", ""), body.get("profile", ""))
        name = body["name"]
        override = studio.profile.messages.setdefault(name, MessageOverride())
        if "rate" in body:
            override.rate_hz = float(body["rate"] or 0)
        if "tx" in body:
            override.tx = [s.strip() for s in str(body["tx"]).split(",") if s.strip()]
        if "rx" in body:
            override.rx = [s.strip() for s in str(body["rx"]).split(",") if s.strip()]
        if "priority" in body:
            override.priority = body["priority"] or ""
        if "note" in body:
            override.note = body["note"] or ""
        studio.profile.save(studio.project)
        if "interface" in body or "requirements" in body:
            set_metadata(
                studio.project, name,
                interface=body.get("interface") or None,
                requirements=[
                    r.strip() for r in str(body.get("requirements", "")).split(",")
                    if r.strip()
                ] or None,
            )
        return {"ok": True}

    def add_message(self, body: dict) -> dict:
        studio = self.studio(body.get("vehicle", ""), body.get("profile", ""))
        message_id = body.get("id")
        if message_id in (None, "", "auto"):
            low, high = studio.project.id_space.messages
            message_id = studio.catalog.next_free_id(low, high)
            if message_id is None:
                raise DialectError(f"no free message id in {low}-{high}")
        message = build_message(
            body["name"], int(message_id), body.get("description", ""),
            body.get("fields", []),
        )
        if body.get("update"):
            path = update_message(studio.project, message, studio.catalog)
        else:
            path = add_message(studio.project, message, studio.catalog)
        if body.get("interface") or body.get("requirements"):
            set_metadata(
                studio.project, message.name,
                interface=body.get("interface") or None,
                requirements=[
                    r.strip() for r in str(body.get("requirements", "")).split(",")
                    if r.strip()
                ] or None,
                namespace=body.get("namespace") or None,
                category=body.get("category") or None,
            )
        return {"ok": True, "path": path, "id": message.id,
                "xml": "\n".join(message_xml(message, ""))}

    def preview_message(self, body: dict) -> dict:
        """Live XML preview + validation for the add-message form."""
        studio = self.studio(body.get("vehicle", ""), body.get("profile", ""))
        from .customdialect import validate_message

        message_id = body.get("id")
        if message_id in (None, "", "auto"):
            low, high = studio.project.id_space.messages
            message_id = studio.catalog.next_free_id(low, high) or low
        message = build_message(
            body.get("name") or "NEW_MESSAGE", int(message_id),
            body.get("description", ""), body.get("fields", []),
        )
        errors = validate_message(
            studio.project, studio.catalog, message,
            replacing=body.get("name", "") if body.get("update") else "",
        )
        return {
            "xml": "\n".join(message_xml(message, "")),
            "errors": errors,
            "bytes": message.payload_bytes,
            "id": message.id,
        }

    def check_id(self, body: dict) -> dict:
        studio = self.studio(body.get("vehicle", ""), body.get("profile", ""))
        check = check_id(studio.project, studio.catalog, int(body["id"]))
        return {
            "id": check.id, "available": check.available,
            "inRange": check.in_range, "ok": check.ok,
            "collisions": [{"dialect": d, "message": m} for d, m in check.collisions],
        }

    def delete_message(self, body: dict) -> dict:
        studio = self.studio(body.get("vehicle", ""), body.get("profile", ""))
        name = body["name"]
        action = body.get("action", "disable")
        if action == "disable":
            override = studio.profile.messages.setdefault(name, MessageOverride())
            override.enabled = False
            studio.profile.save(studio.project)
            return {"ok": True, "action": "disabled in profile"}
        if action == "deprecate":
            deprecate_message(studio.project, name, body.get("since", ""),
                              body.get("replacedBy", ""), body.get("text", ""))
            return {"ok": True, "action": "marked deprecated"}
        if action == "delete":
            state = studio.resolution.states.get(name)
            if state and state.origin == "standard":
                raise DialectError(
                    f"'{name}' is a standard message and is never deleted. "
                    "Disable it in this profile instead."
                )
            remove_message(studio.project, name)
            return {"ok": True, "action": "removed from custom dialect"}
        raise DialectError(f"unknown action '{action}'")

    def build(self, body: dict) -> dict:
        studio = self.studio(body.get("vehicle", ""), body.get("profile", ""))
        result = build_profile_dialect(studio.project, studio.catalog,
                                       studio.resolution)
        payload = {
            "ok": True,
            "path": result.dialect_path,
            "messages": result.message_count,
            "enums": result.enum_count,
            "commands": result.command_count,
            "warnings": result.warnings,
        }
        language = body.get("lang")
        if language:
            output_dir = os.path.join(
                studio.project.build_dir, "generated",
                language.replace("+", "p"),
            )
            ok, output = generate_sources(result.dialect_path, language, output_dir)
            payload["generator"] = {"ok": ok, "output": output, "dir": output_dir}
        return payload

    def icd(self, body: dict) -> dict:
        studio = self.studio(body.get("vehicle", ""), body.get("profile", ""))
        written = write_icd(studio.project, studio.catalog,
                            studio.capability_set, studio.resolution)
        return {"ok": True, "files": written}


class Handler(BaseHTTPRequestHandler):
    api: StudioAPI = None  # type: ignore[assignment]
    server_version = "mavstudio"

    def log_message(self, fmt, *args):  # noqa: A003 - quiet by default
        pass

    # -- helpers ----------------------------------------------------------

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200):
        self._send(code, json.dumps(data).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _static(self, name: str):
        safe = os.path.normpath(name).lstrip("/")
        path = os.path.join(STATIC_DIR, safe)
        if not os.path.abspath(path).startswith(STATIC_DIR) or not os.path.isfile(path):
            self._json({"error": "not found"}, 404)
            return
        types = {".html": "text/html; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}
        content_type = types.get(os.path.splitext(path)[1], "application/octet-stream")
        with open(path, "rb") as handle:
            self._send(200, handle.read(), content_type)

    # -- routes -----------------------------------------------------------

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        vehicle = (query.get("vehicle") or [""])[0]
        profile = (query.get("profile") or [""])[0]
        try:
            if parsed.path in ("/", "/index.html"):
                self._static("index.html")
            elif parsed.path.startswith("/static/"):
                self._static(parsed.path[len("/static/"):])
            elif parsed.path == "/api/state":
                with self.api.lock:
                    self._json(self.api.state(vehicle, profile))
            elif parsed.path == "/api/message":
                name = (query.get("name") or [""])[0]
                with self.api.lock:
                    self._json(self.api.message_detail(vehicle, profile, name))
            else:
                self._json({"error": "not found"}, 404)
        except KeyError as exc:
            self._json({"error": f"not found: {exc}"}, 404)
        except Exception as exc:  # noqa: BLE001 - surface errors in the UI
            self._json({"error": str(exc)}, 500)

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            self._json({"error": f"bad JSON: {exc}"}, 400)
            return
        routes = {
            "/api/toggle-message": self.api.toggle_message,
            "/api/toggle-capability": self.api.toggle_capability,
            "/api/override": self.api.update_override,
            "/api/message/add": self.api.add_message,
            "/api/message/preview": self.api.preview_message,
            "/api/message/delete": self.api.delete_message,
            "/api/check-id": self.api.check_id,
            "/api/build": self.api.build,
            "/api/icd": self.api.icd,
        }
        handler = routes.get(parsed.path)
        if handler is None:
            self._json({"error": "not found"}, 404)
            return
        try:
            with self.api.lock:
                self._json(handler(body))
        except DialectError as exc:
            self._json({"error": str(exc)}, 400)
        except KeyError as exc:
            self._json({"error": f"unknown: {exc}"}, 404)
        except Exception as exc:  # noqa: BLE001 - surface errors in the UI
            self._json({"error": str(exc)}, 500)


def serve(project_root: str = "uav", host: str = "127.0.0.1", port: int = 8770,
          open_browser: bool = True) -> None:
    Handler.api = StudioAPI(project_root)
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"UAV MAVLink Studio -- {url}")
    print(f"project: {os.path.abspath(project_root)}")
    print("Ctrl-C to stop.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
