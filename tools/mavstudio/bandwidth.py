"""Telemetry budget calculator.

Frame overhead follows the MAVLink wire format:

    v1:  6 byte header + payload + 2 byte checksum          =  8 + payload
    v2: 10 byte header + payload + 2 byte checksum          = 12 + payload
    v2 signed: the above plus a 13 byte signature           = 25 + payload

Payloads are costed at their full declared size (MAVLink 2 truncates trailing
zero bytes on the wire, so a real link is never worse than this estimate).
Serial links are costed at 10 bits per byte to account for 8N1 framing.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .profile import Profile, Resolution

V1_OVERHEAD = 8
V2_OVERHEAD = 12
SIGNATURE_BYTES = 13


def frame_bytes(payload_bytes: int, mavlink_version: int = 2,
                signing: bool = False) -> int:
    if mavlink_version == 1:
        return V1_OVERHEAD + payload_bytes
    overhead = V2_OVERHEAD + (SIGNATURE_BYTES if signing else 0)
    return overhead + payload_bytes


@dataclass
class StreamCost:
    name: str
    payload_bytes: int
    frame_bytes: int
    rate_hz: float
    bits_per_second: float
    share: float = 0.0


@dataclass
class Budget:
    link_name: str
    bitrate: int
    mavlink_version: int
    signing: bool
    bits_per_byte: int
    headroom: float
    streams: list[StreamCost] = dc_field(default_factory=list)
    payload_bps: float = 0.0
    overhead_bps: float = 0.0
    total_bps: float = 0.0
    utilisation: float = 0.0
    budget_bps: float = 0.0
    warnings: list[str] = dc_field(default_factory=list)
    unrated: list[str] = dc_field(default_factory=list)

    @property
    def over_budget(self) -> bool:
        return self.total_bps > self.budget_bps


def compute_budget(resolution: Resolution, profile: Profile | None = None,
                   bits_per_byte: int = 10) -> Budget:
    """Cost every enabled message that has a rate assigned in the profile."""
    profile = profile or resolution.profile
    link = profile.link
    budget = Budget(
        link_name=link.name,
        bitrate=link.bitrate,
        mavlink_version=link.mavlink_version,
        signing=link.signing,
        bits_per_byte=bits_per_byte,
        headroom=link.headroom,
    )
    budget.budget_bps = link.bitrate * (1.0 - link.headroom)

    for state in resolution.enabled_messages():
        if state.rate_hz <= 0:
            budget.unrated.append(state.name)
            continue
        framed = frame_bytes(state.payload_bytes, link.mavlink_version, link.signing)
        bps = framed * bits_per_byte * state.rate_hz
        budget.streams.append(
            StreamCost(
                name=state.name,
                payload_bytes=state.payload_bytes,
                frame_bytes=framed,
                rate_hz=state.rate_hz,
                bits_per_second=bps,
            )
        )
        budget.payload_bps += state.payload_bytes * bits_per_byte * state.rate_hz
        budget.total_bps += bps

    budget.overhead_bps = budget.total_bps - budget.payload_bps
    budget.streams.sort(key=lambda s: s.bits_per_second, reverse=True)
    for stream in budget.streams:
        stream.share = (
            stream.bits_per_second / budget.total_bps if budget.total_bps else 0.0
        )
    budget.utilisation = budget.total_bps / link.bitrate if link.bitrate else 0.0

    if budget.total_bps > link.bitrate:
        budget.warnings.append(
            f"Periodic traffic ({budget.total_bps / 1000:.1f} kbps) exceeds the "
            f"link rate ({link.bitrate / 1000:.1f} kbps). The link will drop packets."
        )
    elif budget.over_budget:
        budget.warnings.append(
            f"Periodic traffic uses {budget.utilisation * 100:.1f}% of the link, "
            f"over the {(1 - link.headroom) * 100:.0f}% budget. No headroom left "
            "for mission transfer, parameters or retries."
        )
    for stream in budget.streams[:1]:
        if stream.share > 0.5:
            budget.warnings.append(
                f"{stream.name} alone is {stream.share * 100:.0f}% of the "
                "periodic budget."
            )
    if budget.unrated:
        budget.warnings.append(
            f"{len(budget.unrated)} enabled messages have no rate set and are "
            "not costed (event-driven or on-demand traffic)."
        )
    return budget


def bar(fraction: float, width: int = 24) -> str:
    """Simple text meter used by the CLI dashboard."""
    filled = max(0, min(width, round(fraction * width)))
    return "#" * filled + "." * (width - filled)
