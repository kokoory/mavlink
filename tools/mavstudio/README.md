# UAV MAVLink Studio

A message-set browser, custom-dialect editor and interface manager for a UAV
programme, built on top of this repository's `message_definitions/v1.0`.

The central rule: **upstream MAVLink definitions are never edited.** Standard
messages are enabled and disabled per vehicle configuration; your own messages
live in a separate dialect that `<include>`s the upstream base. Pulling a new
MAVLink release stays a fast-forward.

```
python3 -m pip install pyyaml            # required
python3 -m pip install pymavlink         # optional, for code generation
python3 -m pip install PySide6           # optional, for the desktop UI

export PYTHONPATH=tools
python3 -m mavstudio init --name "SWAN-H200" --vehicle SWAN-H200
python3 -m mavstudio qt                  # desktop UI
python3 -m mavstudio web                 # browser UI
python3 -m mavstudio dashboard           # terminal
```

## The five layers

```
1  Catalog            message_definitions/v1.0/*.xml, read only
2  Custom dialect     message_definitions/v1.0/my_uav.xml, additive only
3  Capabilities       protocol features that own groups of messages
4  UAV profile        per vehicle + configuration: what is on, at what rate
5  Interface contract MOSA agreements between modules, versioned
```

Each layer only reads the ones above it. A profile cannot corrupt the catalog;
a contract cannot silently enable a message. `validate` checks across all five.

## Enable/disable, never delete

A standard message you do not use is not removed from `common.xml` — it is
switched off in the profile:

```
HIGHRES_IMU
  Origin        MAVLink common.xml
  Available     yes
  This profile  DISABLED (capability 'telemetry_imu' off)
  Deletable     no
```

`mavstudio message rm` refuses standard messages and tells you to disable
instead. Only messages in your own dialect can be deleted, and even then
`message deprecate` is usually the better move.

## Capabilities

Ticking 83 checkboxes to strip a build is miserable, so messages are grouped
into protocol capabilities. Turning one off takes its whole message set with
it:

```
python3 -m mavstudio capability gimbal_protocol --off
# Gimbal Protocol: OFF -- 16 messages follow
```

Groups: CORE, TELEMETRY, SERVICES, NETWORK, SECURITY, PAYLOAD, SIMULATION.
Capabilities marked *required* (heartbeat, command protocol) cannot be turned
off — MAVLink stops working without them.

Precedence, lowest first:

1. the capability's default
2. the capability toggle in the profile
3. an explicit per-message override in the profile
4. hard rules — required capabilities and your own custom messages stay on

`mavstudio show <MESSAGE>` prints which rule decided, so a surprising state is
never a mystery.

Add or override capabilities in `uav/capabilities.yaml`.

## Profiles

One dialect, several configurations. `uav/profiles/<vehicle>.<profile>.yaml`:

```yaml
vehicle: SWAN-H200
profile: flight
link: {name: Telemetry radio, bitrate: 115200, mavlink_version: 2, headroom: 0.2}
capabilities:
  ftp: false
  telemetry_imu: false
messages:
  ATTITUDE: {enabled: true, rate_hz: 50, tx: [FC], rx: [GCS]}
```

`mavstudio diff development` shows what a second profile changes.

## Custom messages

```
python3 -m mavstudio message add UAV_MOTOR_VIBRATION \
    -d "Motor-mounted IMU vibration data." \
    -f "time_usec:uint64_t:us::Timestamp." \
    -f "motor_id:uint8_t::UAV_MOTOR:Motor this sample came from." \
    -f "accel_x:float:m/s/s::Vibration acceleration, X body axis."
```

Field spec is `name:type[:units[:enum[:description]]]`. The id is auto-assigned
from the project's reserved range if you omit `--id`. Before anything is
written the message is checked for:

- name and field-name conventions, duplicate names across every dialect
- id inside the reserved range, and no collision anywhere in the catalog
- known field types, array bounds, known enum references
- payload ≤ 255 bytes
- extension fields last
- a description (the ICD needs one)

### The id range matters

`42000`/`42001` are already taken by `icarous.xml`, and 50000–52699 by
cubepilot, csAirLink, marsh and stemstudios. The default reserved range is
**52700–52799**, free in upstream today. `mavstudio ids --check 42001` shows
exactly what a candidate id would collide with.

## Telemetry budget

Frame cost is the real wire cost: MAVLink 2 adds 12 bytes (25 signed), serial
links are costed at 10 bits/byte for 8N1 framing.

```
MESSAGE              PAYLOAD  FRAME  RATE  KBPS  SHARE
UAV_MOTOR_VIBRATION  33       45     100   45.0  61.3%
ATTITUDE             28       40     50    20.0  27.2%
...
  total            73.4 kbps
  budget           92.2 kbps (80% of link)
  utilisation     63.7 %  [###############.........]

  WARNING  UAV_MOTOR_VIBRATION alone is 61% of the periodic budget.
```

Messages with no rate are event-driven and left out of the periodic total —
the report says how many.

## Interface contracts (MOSA / K-MOSA)

A MAVLink message is a data packet. An **interface contract** is the agreement
between modules: a named, versioned bundle of required and optional messages,
commands, and non-message aspects, with declared providers and consumers.

```
python3 -m mavstudio interface add PROPULSION.MONITORING --version 1.2.0 \
    --provider "Motor Controller Module" --consumer "Flight Controller" \
    --required UAV_MOTOR_STATUS --required UAV_MOTOR_VIBRATION \
    --command MAV_CMD_UAV_MOTOR_TEST \
    --aspect power=28VDC-40W --aspect mechanical=M3x4-100mm --aspect timing
```

**Transport-neutral by design.** MAVLink is one data model among several. A
contract can require `dds:TargetTrack` or `uci:TargetStatus` alongside MAVLink
names. Only `mavlink:` refs are checked against the catalog; the rest are
recorded and reported as *unverified* rather than silently assumed to pass.

Modules declare what they implement:

```
python3 -m mavstudio module add "Motor Controller Module" --vendor ABC \
    --version 2.1.0 --kind actuator \
    --implements PROPULSION.MONITORING=1.3.0 \
    --tx UAV_MOTOR_STATUS --tx UAV_MOTOR_VIBRATION \
    --aspect power=28VDC-40W --aspect timing=PTP
```

`--candidate` marks a part you are evaluating: it takes part in swap checks but
is not enforced by `validate`.

### Replacement compatibility

```
$ python3 -m mavstudio swap "Motor Controller Module" "XYZ ESC v4"

  PROPULSION.MONITORING: 1.3.0 -> 1.2.0   INCOMPATIBLE  (50%)
    XYZ ESC v4 implements PROPULSION.MONITORING 1.2.0, older than 1.3.0
    FAIL  message  UAV_MOTOR_VIBRATION
    FAIL  command  MAV_CMD_UAV_MOTOR_TEST
    PASS  aspect   power: 28VDC-40W (needs 28VDC-40W)
    PASS  aspect   mechanical: M3x4-100mm (needs M3x4-100mm)
    FAIL  aspect   timing: not declared
  CORE.TIMEBASE: 1.0.0 -> -   INCOMPATIBLE  (0%)

Replacement compatibility  25%
```

Exit status is non-zero for anything short of compatible, so it works in CI.

### Interface versioning

SemVer with interface semantics — a major bump is a breaking interface change,
so 1.5.0 does not satisfy a requirement for 2.0.0 or vice versa.
`mosa.classify_change()` classifies a contract edit as major/minor/patch and
`mosa.expected_version()` gives the version it should carry.

### On K-MOSA specifically

K-MOSA is still being built out as a standard-and-certification framework. This
tool implements the structural pieces any modular open-systems approach needs —
named interfaces, semantic versioning, provider/consumer declarations, module
manifests, conformance checking, and generated interface documentation — rather
than hard-coding clauses from a specification that may still move. When you
have the actual requirement text, the checks live in `mosa.py` and
`validate.py` and are straightforward to extend.

For orientation, the US MOSA landscape these ideas come from is not a single
stack — FACE (software portability), SOSA (sensor/processing hardware), OMS
(mission-system service interfaces), UCI (machine-to-machine mission-level C2
message set) and UCS (unmanned control-segment architecture, SAE AS6512) each
solve a different problem. MAVLink sits at vehicle/autopilot C2, below the
mission-level C2 that UCI addresses. The `transport` and data-model fields
above exist so that a contract can span those layers instead of assuming
MAVLink is the architecture.

## ICD generation

```
python3 -m mavstudio icd            # Markdown + HTML + CSV
```

Generated from the same profile the firmware is built from, so the document
cannot drift from the code. Sections: summary, enabled capabilities, message
list, full field definitions, enabled commands, interface contracts and module
manifests, requirement traceability, telemetry budget.

Attach traceability with `mavstudio meta set <MESSAGE> --interface X
--requirement SRS-...`, or in either UI.

## Build

```
python3 -m mavstudio build                     # pruned standalone dialect XML
python3 -m mavstudio build --lang C            # and run mavgen
```

The build emits a **standalone** dialect containing exactly the enabled
messages, the enums they transitively reference, and the enabled MAV_CMD
entries. Standalone rather than `<include>`-based because pruning cannot reach
into an included file.

Build refuses to run with validation errors unless you pass `--skip-validate`.

Build filenames are forced to `[a-z0-9_]` because mavgen turns the filename
into a preprocessor macro — `my_uav_swan-h200_flight.xml` would produce the
invalid `MAVLINK_MY_UAV_SWAN-H200_FLIGHT_XML_HASH`.

## Upstream hygiene

```
$ python3 -m mavstudio upstream
PROJECT    added   2 messages, 1 commands, 1 enums
           enabled 130, disabled 269
           modified standard files: 0   (good)
           id conflicts: 0
```

`modified standard files` must stay at 0 — that is the whole point of the
overlay. `validate` reports any local edit to an upstream XML as an error.

## The three front-ends

All three drive the same library, so they cannot drift:

| | command | needs |
| --- | --- | --- |
| Desktop | `python3 -m mavstudio qt` | PySide6 |
| Browser | `python3 -m mavstudio web` | nothing extra |
| Terminal | `python3 -m mavstudio <cmd>` | nothing extra |

On a headless Linux box PySide6 also needs system libraries:
`libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4
libxcb-keysyms1 libxcb-shape0 libdbus-1-3`.

The web server binds to loopback and edits files in your project — do not
expose it to a network you do not control.

## Files

```
uav/project.yaml                    dialect settings, id range, vehicles
uav/capabilities.yaml               optional capability overrides
uav/message_meta.yaml               interface + requirement traceability
uav/profiles/<vehicle>.<name>.yaml  what is on, at what rate, in what direction
uav/interfaces/<name>.yaml          MOSA interface contracts
uav/modules/<name>.yaml             MOSA module manifests
message_definitions/v1.0/my_uav.xml your dialect (real MAVLink XML, in git)
build/mavstudio/                    generated dialect, headers, ICD (gitignored)
```

## Tests

```
PYTHONPATH=tools python3 -m unittest discover -s tools/tests -v
```
