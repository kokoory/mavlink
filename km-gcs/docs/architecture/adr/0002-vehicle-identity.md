# ADR 0002: Vehicle identity is three things, not one

**Status:** accepted · **Date:** 2026-09-05

## Context

The architecture baseline is inconsistent here. Section 6 lists identity as
`{VehicleUuid, SystemAddress, ProductType}`; the code sketch in section 20
reduces it to a bare 16-byte UUID; the MVP plan keys vehicles by sysid.

They cannot all be right. MAVLink hands out no UUID. A heartbeat carries a
one-byte system id that is reused across power cycles and reassigned by the
operator. The only durable hardware identifier, `AUTOPILOT_VERSION.uid2`,
arrives late and only when requested.

## Decision

Three types with three lifetimes:

| Type | Lifetime | Source |
| --- | --- | --- |
| `VehicleHandle` | this process and its recordings | minted locally on discovery |
| `SystemAddress` | until the operator renumbers | the wire |
| `HardwareId` | the airframe | `AUTOPILOT_VERSION`, late and optional |

`VehicleRegistry` is the only writer of identity. Handles are never derived
from anything on the wire, so renumbering a vehicle mid-session changes its
address without invalidating a single reference to it.

A vehicle is created only from a heartbeat, because product type decides how
the rest of the stream is interpreted. Telemetry arriving before the first
heartbeat is dropped rather than creating a half-identified vehicle.

## Consequences

- Recordings stay correlatable across a renumbering.
- Two vehicles that swap system ids are two vehicles, not one confused one.
- A vehicle that never sends `AUTOPILOT_VERSION` still works; it simply has no
  durable identity, which is the truth.
