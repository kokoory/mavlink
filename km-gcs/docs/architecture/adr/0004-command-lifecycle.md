# ADR 0004: A command has two outcomes, not one

**Status:** accepted · **Date:** 2026-09-05

## Context

The baseline's send path (figure 9-2) completes a command when `COMMAND_ACK`
arrives. That is unsafe for three separate reasons:

1. `COMMAND_ACK` carries no correlation id. It is matched on
   `(command, target)`, so two in-flight instances of the same command are
   indistinguishable.
2. `MAV_RESULT_IN_PROGRESS` is an intermediate ack. Treating it as terminal
   reports success while the vehicle is still working.
3. `MAV_RESULT_ACCEPTED` means "I will try", not "it happened". An arm command
   is complete when the heartbeat reports `SAFETY_ARMED`, not when the ack
   arrives.

## Decision

`CommandStage` distinguishes `Accepted` (the vehicle took the command) from
`Confirmed` (the state it targeted actually changed). `CommandOutcome::terminal()`
is false for `Accepted`; `acknowledged()` is true. A caller that only needs
"did the vehicle take it" stops at the first; a caller that needs "did it
happen" waits for the second.

`defaultPolicyFor()` supplies, per command, both the confirmation timeout and
the predicate that proves the effect:

| Command | Confirmed by |
| --- | --- |
| Arm / Takeoff | `snapshot.armed.armed` |
| Disarm | `!snapshot.armed.armed` |
| SetFlightMode | current mode matches the requested vendor code |
| Land / RTL | nothing — `Accepted` is terminal |

Land and RTL deliberately have no predicate: no single observable state proves
a landing started, and waiting for touchdown would block for minutes.

Commands are serialised per `(vehicle, command)` because of point 1.

## Consequences

- This is exactly what the conformance model's Behavior axis tests, so the
  runtime model and the conformance test agree by construction rather than by
  someone remembering to keep them aligned.
- An operator sees "accepted" and then "confirmed", which is more information
  than a GCS that only shows one, and it is honest about the gap between them.
