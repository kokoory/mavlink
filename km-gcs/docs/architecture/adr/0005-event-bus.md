# ADR 0005: The event bus is type-erased, not a closed variant

**Status:** accepted · **Date:** 2026-09-05

## Context

The baseline defines `DomainEvent` as a `std::variant` of the core's event
types (code sketch 20-6) while also requiring that plugins extend the system
(P7, section 13). Those contradict: a plugin cannot add an alternative to a
variant sealed when the core was compiled. A closed variant also recompiles
every translation unit that touches the bus whenever an event is added.

## Decision

Events are type-erased behind a `std::type_index`-derived `EventType`, with a
type-safe template front end (`publish<T>` / `subscribe<T>`). A plugin defines
its own struct and publishes it without the core knowing the type exists;
`test_event_bus.cpp` covers exactly that case.

Delivery policy lives on the subscription, giving the baseline's backpressure
table (section 10.2) somewhere to actually take effect:

| Policy | Behaviour | For |
| --- | --- | --- |
| `LatestValue` | supersede a queued event of the same type | attitude, position, battery |
| `Lossless` | queue everything | commands, acks, faults |
| `Bounded` | queue to a limit | raw log feeds |

A type is coalesced only while **every** subscriber to it agrees. One lossless
subscriber — a recorder — is enough to keep every sample, which is the correct
resolution and not obvious enough to leave implicit.

`publish()` is callable from any thread; delivery happens on whichever thread
calls `drain()`. That is how the core keeps a single owner for domain state
without every producer needing to know it. Handlers run outside the lock,
because a handler that publishes is normal and holding the mutex across user
code would deadlock the first time one does.

## Consequences

- Slightly more machinery than a variant, in exchange for a plugin boundary
  that works and build times that do not grow with the event count.
- `drain(budget)` bounds a burst so telemetry cannot monopolise the loop.
