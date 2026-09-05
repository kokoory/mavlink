# KM-GCS

An independent, protocol-independent ground control station, built to the
architecture baseline in
[`docs/architecture/`](docs/architecture/KM-GCS-Architecture-v0.1.md).

Not a QGroundControl fork. The goal of the first slice is not to reproduce a
ground station's feature list quickly, but to establish that
`Link → Protocol → Translation → Domain Event → Vehicle State → Service → UI`
holds in real code, so that DDS, UCI, payloads and conformance can be added
later without redesigning the core.

## Status

v0.1, MVP steps 0–7 of the baseline plan. Working today:

- UDP link, MAVLink 2 parsing, translation to canonical state
- Vehicle discovery, expiry, multi-vehicle on one link
- Attitude, position, velocity, GNSS, battery, armed state, flight mode
- Time synchronisation with per-clock quality
- PX4 and ArduPilot product adapters, command encoding
- Headless station; layering enforced by the build; 5 test binaries

Not yet: QML UI, mission, parameters, payload, plugins, conformance runner,
DDS/ROS 2/UCI adapters.

## Build

Needs CMake 3.22, a C++20 compiler, Python 3 and `pymavlink`. Qt 6 is optional
and only used by the UI; **everything else builds and tests without it.**

```bash
cmake -S km-gcs -B build/km-gcs -G Ninja
cmake --build build/km-gcs
ctest --test-dir build/km-gcs --output-on-failure
```

Then, against PX4 or ArduPilot SITL on the default port:

```bash
./build/km-gcs/km-gcs-headless --port 14550
```

## Where the MAVLink message set comes from

The headers KM-GCS compiles against are **generated at build time from the
mavstudio interface profile**, not checked in. Turning a capability off in the
profile removes it from the ground station's build, so the two cannot drift.

`cmake/KmGcsMavlink.cmake` prefers a profile build under
`build/mavstudio/`, and falls back to `my_uav.xml` or `common.xml` so a fresh
clone still configures.

## Layout

```
core/domain/     pure C++ value types: identity, time, state, commands
core/event/      type-erased event bus and the core event set
core/vehicle/    registry (identity) and state store (latest state)
core/app/        GcsCore, and the composition root
links/           ILink and a POSIX UDP implementation
protocols/       protocol abstraction and the MAVLink adapter + translator
adapters/        PX4 and ArduPilot product semantics
apps/headless/   the no-UI station
tests/           unit and integration
docs/            the baseline and the ADRs
```

Dependencies point down, always onto abstractions. `core/app/Composition.cpp`
is the single place allowed to see every layer at once.

## The rule the build enforces

Nothing below the adapter boundary may name MAVLink or Qt. This is checked two
ways on every build — the transitive link closure, and a grep of each layer's
sources and headers — and both were verified by deliberately injecting
violations. See [ADR 0001](docs/architecture/adr/0001-layering.md).

That is also why links use POSIX sockets rather than `QUdpSocket`: it keeps Qt
out of the core and makes the whole receive path testable headlessly.

## Decisions that differ from the baseline

Each has an ADR explaining the evidence.

| | Baseline | Here | Why |
| --- | --- | --- | --- |
| [0001](docs/architecture/adr/0001-layering.md) | P1/P2 as principles | build failures; POSIX sockets | a principle nothing checks is a wish |
| [0002](docs/architecture/adr/0002-vehicle-identity.md) | one UUID (and elsewhere, sysid) | handle + address + hardware id | MAVLink issues no UUID; sysid is reassigned |
| [0003](docs/architecture/adr/0003-time-base.md) | `sourceTime`, unspecified | one TimeBase per vehicle clock | boot clock and absolute clock are different clocks |
| [0004](docs/architecture/adr/0004-command-lifecycle.md) | ACK completes a command | Accepted, then Confirmed | `ACCEPTED` means "I will try" |
| [0005](docs/architecture/adr/0005-event-bus.md) | closed `std::variant` | type-erased | a variant cannot be extended by a plugin |
| [0006](docs/architecture/adr/0006-flight-mode.md) | two adapters map modes | `AVAILABLE_MODES` first | 84 ArduPilot modes, meaning depends on frame |

## Testing

`tests/unit` covers the domain, the bus, the registry and the adapters with no
I/O. `tests/integration/test_pipeline.cpp` drives real MAVLink frames over a
real UDP socket into the state store, including a garbage-injection case, so
the wire format is exercised rather than mocked.

The headless station has also been run against a `pymavlink`-driven vehicle —
an independent implementation of the wire format — which is how the two-clock
bug in ADR 0003 was found.
