# ADR 0006: Flight mode prefers what the vehicle says over what we assume

**Status:** accepted · **Date:** 2026-09-05

## Context

The baseline models flight mode as "canonical mode + optional vendor detail"
and assigns mapping to two product adapters, PX4 and ArduPilot. The shape is
right; the sizing is not.

Counted from `message_definitions/v1.0/ardupilotmega.xml`, ArduPilot alone
defines 84 modes across five enums — `COPTER_MODE` 26, `PLANE_MODE` 26,
`ROVER_MODE` 14, `SUB_MODE` 11, `TRACKER_MODE` 7 — and which applies depends on
the **frame type**, of which `MAV_TYPE` lists 50. Mode 5 is `Loiter` on a
Copter and `FBWA` on a Plane. An adapter selected by autopilot alone cannot get
this right, and `IAutopilotAdapter::mapFlightMode(const ProductTelemetryView&)`
as sketched does not receive the frame type at all.

Upstream MAVLink has meanwhile solved most of this and the baseline does not
mention it: `AVAILABLE_MODES` (435), `CURRENT_MODE` (436), `MAV_STANDARD_MODE`
and `MAV_CMD_DO_SET_STANDARD_MODE` let a vehicle enumerate its own modes, by
name, at runtime.

## Decision

Precedence, best first:

1. `AVAILABLE_MODES` — the vehicle's own list. Authoritative.
2. `CURRENT_MODE.standard_mode` — a standardised mode identifier.
3. A vendor table in the product adapter, selected by `(autopilot, frame)`.
4. Nothing: the mode is displayed by its numeric code.

`domain::FlightMode` carries the name as a **string** plus a `ModeSource`
recording which rule produced it. The UI can therefore render and select a mode
no adapter has ever heard of, which a closed enum forbids and which would
otherwise be a functional regression against existing ground stations.

An adapter returns `std::nullopt` rather than guessing when the frame type is
unknown. A mode shown by number is honest; a Plane mode labelled with a Copter
name is not.

## Consequences

- Vendor tables shrink to a fallback and stop being a maintenance treadmill.
- Capability discovery (baseline section 13.2) and mode handling become the
  same mechanism rather than two.
- `test_adapters.cpp` pins the Copter/Plane divergence so the frame-type
  dependency cannot be quietly dropped.
