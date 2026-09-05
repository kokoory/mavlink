# ADR 0001: Layering is enforced by the build, not by review

**Status:** accepted · **Date:** 2026-09-05

## Context

The architecture baseline states two principles: the core is
protocol-independent (P1) and the UI is separate from the core (P2). Neither is
testable as written. The usual failure mode of a design like this is that the
canonical model quietly becomes "MAVLink with different field names", one
convenient include at a time, and nobody notices until a second protocol has to
be added and cannot be.

## Decision

Both principles are enforced as build failures.

`cmake/KmGcsLayering.cmake` provides two independent checks:

- `kmgcs_forbid_link(target FROM libs...)` fails if the target's **transitive**
  link closure contains a forbidden library.
- `kmgcs_forbid_symbols(target PATTERNS ...)` greps the target's sources and
  headers and fails if a forbidden pattern appears.

Both are needed. A link check misses a hand-copied constant; a grep misses a
dependency pulled in three targets away. Comments are stripped before grepping,
so a layer may name in prose what it must not name in code.

`kmgcs_core_layer(target)` applies the standard rule: no MAVLink, no product
adapters, no Qt.

A second decision follows from this: **links use POSIX sockets, not
QUdpSocket.** The baseline specified Qt sockets, which would have put Qt in the
core and made P2 unenforceable. With plain sockets, everything below the UI
builds and tests headlessly, and "no Qt below the UI" becomes a rule the build
can check.

## Consequences

- Adding a legitimate cross-layer dependency requires editing the rule, which
  is the point: it becomes a decision rather than an accident.
- Generated MAVLink headers are included as `SYSTEM`, because third-party
  generated code cannot meet our warning bar and lowering the bar for our own
  code to accommodate it would be the wrong trade.
- Both guards were verified by deliberately injecting violations. A guard nobody
  has watched fail is not yet a guard.
