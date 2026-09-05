# ADR 0003: One TimeBase per vehicle clock

**Status:** accepted · **Date:** 2026-09-05

## Context

The baseline gives every domain value a `sourceTime` and a `receiveTime` but
never says how `sourceTime` is obtained. Without an answer, two vehicles'
timestamps are not comparable, recordings cannot be aligned, and the Timing
axis of the conformance model has nothing to measure.

Time synchronisation was therefore pulled into the first slice rather than
deferred: the domain model cannot be corrected later without rewriting every
consumer of a timestamp.

## Decision

`domain::TimeBase` estimates offset and quality between one vehicle clock and
ours, from TIMESYNC round trips where available and arrival times otherwise.
Every timestamp carries a `TimeQuality` (`None`, `Arrival`, `Coarse`,
`Synchronised`) so a consumer can tell a synchronised value from a guess.

**A vehicle has more than one clock, and each needs its own TimeBase.** MAVLink
exposes `time_boot_ms` (milliseconds since the vehicle booted) and `tc1` /
`time_usec` (the vehicle's absolute clock). TIMESYNC synchronises only the
latter. Applying a TIMESYNC offset to `time_boot_ms` yields timestamps wrong by
however long the vehicle has been powered.

This was not caught by reading the specification. It appeared as an age of
1,788,575,238 ms on the headless station's first run against a vehicle that
answers TIMESYNC. `test_domain.cpp` now pins it.

`time_usec` is documented as "UNIX epoch **or** time since boot", so the
receiver must guess: values at or above 1e15 µs are treated as epoch, since no
vehicle has been powered for 32 years.

## Consequences

- Staleness (`lastHeard`) is measured on our clock from arrival, never from a
  vehicle-claimed timestamp. Otherwise age would depend on sync quality, which
  is backwards.
- The boot clock stays at `Arrival` quality permanently; no MAVLink mechanism
  synchronises it directly, and pretending otherwise would be a lie in the type.
