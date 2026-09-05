"""Layer 3 -- capabilities.

A capability is a protocol-level feature ("MAVLink FTP", "Gimbal Protocol")
that owns a set of messages and commands. Turning a capability off in a profile
disables everything it owns, which is far easier to reason about than ticking
83 individual checkboxes.

Patterns are shell globs matched against message / command names. The built-in
set below is a starting point; a project can extend or override it with
``uav/capabilities.yaml``.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field as dc_field

from .catalog import Catalog


@dataclass
class Capability:
    key: str
    title: str
    group: str
    category: str
    description: str = ""
    #: Globs matched against message names.
    messages: list[str] = dc_field(default_factory=list)
    #: Globs matched against MAV_CMD entry names.
    commands: list[str] = dc_field(default_factory=list)
    #: Required capabilities cannot be switched off -- MAVLink stops working.
    required: bool = False
    #: Default enabled state for a fresh profile.
    default: bool = True


def _cap(key, title, group, category, messages, commands=(), **kwargs):
    return Capability(
        key=key,
        title=title,
        group=group,
        category=category,
        messages=list(messages),
        commands=list(commands),
        **kwargs,
    )


# --------------------------------------------------------------------------
# Built-in capability set
# --------------------------------------------------------------------------

BUILTIN_CAPABILITIES: list[Capability] = [
    # ---- CORE ------------------------------------------------------------
    _cap(
        "heartbeat", "Heartbeat", "CORE", "Core",
        ["HEARTBEAT", "SYS_STATUS", "SYSTEM_TIME", "PROTOCOL_VERSION",
         "AUTOPILOT_VERSION", "EXTENDED_SYS_STATE", "STATUSTEXT"],
        ["MAV_CMD_REQUEST_PROTOCOL_VERSION", "MAV_CMD_REQUEST_AUTOPILOT_CAPABILITIES"],
        required=True,
    ),
    _cap(
        "command_protocol", "Command Protocol", "CORE", "Core",
        ["COMMAND_LONG", "COMMAND_INT", "COMMAND_ACK", "COMMAND_CANCEL",
         "MESSAGE_INTERVAL", "SET_MODE", "CURRENT_MODE", "AVAILABLE_MODES",
         "AVAILABLE_MODES_MONITOR"],
        ["MAV_CMD_SET_MESSAGE_INTERVAL", "MAV_CMD_REQUEST_MESSAGE",
         "MAV_CMD_DO_SET_MODE"],
        required=True,
    ),
    _cap(
        "parameter_protocol", "Parameter Protocol", "CORE", "Core",
        ["PARAM_REQUEST_READ", "PARAM_REQUEST_LIST", "PARAM_VALUE", "PARAM_SET",
         "PARAM_MAP_RC", "PARAM_ERROR"],
        ["MAV_CMD_DO_SET_PARAMETER"],
    ),
    _cap(
        "mission_protocol", "Mission Protocol", "CORE", "Mission",
        ["MISSION_*"],
        ["MAV_CMD_NAV_WAYPOINT", "MAV_CMD_NAV_LOITER_*", "MAV_CMD_NAV_RETURN_*",
         "MAV_CMD_NAV_LAND", "MAV_CMD_NAV_TAKEOFF*", "MAV_CMD_DO_JUMP*",
         "MAV_CMD_MISSION_START", "MAV_CMD_DO_SET_MISSION_CURRENT"],
    ),
    _cap(
        "time_sync", "Time Synchronization", "CORE", "Core",
        ["TIMESYNC", "PING"],
    ),

    # ---- TELEMETRY -------------------------------------------------------
    _cap(
        "telemetry_attitude", "Attitude", "TELEMETRY", "Navigation",
        ["ATTITUDE", "ATTITUDE_QUATERNION", "ATTITUDE_QUATERNION_COV",
         "ATTITUDE_TARGET", "SET_ATTITUDE_TARGET", "MOUNT_ORIENTATION",
         "AHRS*"],
    ),
    _cap(
        "telemetry_position", "Position", "TELEMETRY", "Navigation",
        ["GLOBAL_POSITION_INT", "GLOBAL_POSITION_INT_COV", "GLOBAL_POSITION_SENSOR",
         "LOCAL_POSITION_NED", "LOCAL_POSITION_NED_COV",
         "LOCAL_POSITION_NED_SYSTEM_GLOBAL_OFFSET", "ALTITUDE", "VFR_HUD",
         "NAV_CONTROLLER_OUTPUT", "HOME_POSITION", "SET_HOME_POSITION",
         "GPS_GLOBAL_ORIGIN", "SET_GPS_GLOBAL_ORIGIN", "POSITION_TARGET_*",
         "SET_POSITION_TARGET_*", "ESTIMATOR_STATUS", "CONTROL_SYSTEM_STATE"],
    ),
    _cap(
        "telemetry_imu", "IMU / Vibration", "TELEMETRY", "Sensor",
        ["HIGHRES_IMU", "SCALED_IMU", "SCALED_IMU2", "SCALED_IMU3", "VIBRATION",
         "SCALED_PRESSURE*", "AIRSPEED", "WIND_COV", "HYGROMETER_SENSOR"],
        default=False,
    ),
    _cap(
        "telemetry_raw_sensors", "Raw Sensors", "TELEMETRY", "Sensor",
        ["RAW_IMU", "RAW_PRESSURE", "RAW_RPM", "GPS_STATUS"],
        default=False,
    ),
    _cap(
        "telemetry_battery", "Battery / Power", "TELEMETRY", "Health",
        ["BATTERY_STATUS", "BATTERY_INFO", "SMART_BATTERY_INFO", "POWER_STATUS",
         "FUEL_STATUS", "GENERATOR_STATUS", "EFI_STATUS", "ESC_INFO", "ESC_STATUS"],
    ),
    _cap(
        "telemetry_gps", "GPS / RTK", "TELEMETRY", "Sensor",
        ["GPS_RAW_INT", "GPS2_RAW", "GPS_RTK", "GPS2_RTK", "GPS_INPUT",
         "GPS_INJECT_DATA", "GPS_RTCM_DATA"],
    ),
    _cap(
        "telemetry_rc", "RC / Servo", "TELEMETRY", "Control",
        ["RC_CHANNELS", "RC_CHANNELS_RAW", "RC_CHANNELS_SCALED",
         "RC_CHANNELS_OVERRIDE", "SERVO_OUTPUT_RAW", "ACTUATOR_OUTPUT_STATUS",
         "ACTUATOR_CONTROL_TARGET", "SET_ACTUATOR_CONTROL_TARGET",
         "MANUAL_CONTROL", "MANUAL_SETPOINT", "BUTTON_CHANGE",
         "CHANGE_OPERATOR_CONTROL*"],
    ),
    _cap(
        "telemetry_optical_flow", "Optical Flow / Vision", "TELEMETRY", "Sensor",
        ["OPTICAL_FLOW", "OPTICAL_FLOW_RAD", "VISION_*", "GLOBAL_VISION_*",
         "VICON_POSITION_ESTIMATE", "ATT_POS_MOCAP", "ODOMETRY", "LANDING_TARGET"],
        default=False,
    ),
    _cap(
        "telemetry_distance", "Distance / Obstacle", "TELEMETRY", "Sensor",
        ["DISTANCE_SENSOR", "OBSTACLE_DISTANCE", "TRAJECTORY_REPRESENTATION_*",
         "WHEEL_DISTANCE", "TERRAIN_REPORT"],
        default=False,
    ),
    _cap(
        "high_latency", "High Latency Telemetry", "TELEMETRY", "Service",
        ["HIGH_LATENCY", "HIGH_LATENCY2", "ISBD_LINK_STATUS"],
        ["MAV_CMD_CONTROL_HIGH_LATENCY"],
        default=False,
    ),

    # ---- SERVICES --------------------------------------------------------
    _cap(
        "ftp", "MAVLink FTP", "SERVICES", "Service",
        ["FILE_TRANSFER_PROTOCOL"],
        default=False,
    ),
    _cap(
        "log_download", "Log Download", "SERVICES", "Service",
        ["LOG_*", "LOGGING_*", "REMOTE_LOG_*"],
        ["MAV_CMD_LOGGING_START", "MAV_CMD_LOGGING_STOP"],
        default=False,
    ),
    _cap(
        "param_ext", "Parameter EXT", "SERVICES", "Service",
        ["PARAM_EXT_*"],
        default=False,
    ),
    _cap(
        "events", "Events Interface", "SERVICES", "Service",
        ["EVENT", "CURRENT_EVENT_SEQUENCE", "REQUEST_EVENT",
         "RESPONSE_EVENT_ERROR"],
        ["MAV_CMD_REQUEST_EVENTS"],
        default=False,
    ),
    _cap(
        "component_information", "Component Information", "SERVICES", "Service",
        ["COMPONENT_INFORMATION", "COMPONENT_INFORMATION_BASIC",
         "COMPONENT_METADATA", "RESOURCE_REQUEST", "FLIGHT_INFORMATION",
         "STORAGE_INFORMATION"],
        default=False,
    ),
    _cap(
        "camera_protocol", "Camera Protocol", "SERVICES", "Payload",
        ["CAMERA_*", "VIDEO_STREAM_*", "IMAGE_*", "SET_VIDEO_STREAM_SETTINGS",
         "ILLUMINATOR_STATUS"],
        ["MAV_CMD_IMAGE_*", "MAV_CMD_VIDEO_*", "MAV_CMD_DO_DIGICAM_*",
         "MAV_CMD_SET_CAMERA_*", "MAV_CMD_REQUEST_CAMERA*", "MAV_CMD_CAMERA_*",
         "MAV_CMD_DO_TRIGGER_CONTROL", "MAV_CMD_DO_SET_CAM_TRIGG_*"],
        default=False,
    ),
    _cap(
        "gimbal_protocol", "Gimbal Protocol", "SERVICES", "Payload",
        ["GIMBAL_*", "MOUNT_*", "AUTOPILOT_STATE_FOR_GIMBAL_DEVICE"],
        ["MAV_CMD_DO_MOUNT_*", "MAV_CMD_DO_GIMBAL_*", "MAV_CMD_REQUEST_GIMBAL*",
         "MAV_CMD_SET_STORAGE_USAGE"],
        default=False,
    ),
    _cap(
        "mission_geofence", "Geofence / Rally", "SERVICES", "Mission",
        ["FENCE_*", "RALLY_*", "SAFETY_ALLOWED_AREA", "SAFETY_SET_ALLOWED_AREA"],
        ["MAV_CMD_NAV_FENCE_*", "MAV_CMD_NAV_RALLY_POINT", "MAV_CMD_DO_FENCE_ENABLE"],
        default=False,
    ),
    _cap(
        "terrain", "Terrain Service", "SERVICES", "Service",
        ["TERRAIN_*"],
        default=False,
    ),
    _cap(
        "calibration", "Calibration", "SERVICES", "Service",
        ["MAG_CAL_*", "SENSOR_OFFSETS", "SET_MAG_OFFSETS"],
        ["MAV_CMD_PREFLIGHT_CALIBRATION", "MAV_CMD_DO_ACCEPT_MAG_CAL",
         "MAV_CMD_DO_CANCEL_MAG_CAL", "MAV_CMD_DO_START_MAG_CAL"],
        default=False,
    ),
    _cap(
        "tune", "Tune / Buzzer", "SERVICES", "Service",
        ["PLAY_TUNE", "PLAY_TUNE_V2", "SUPPORTED_TUNES"],
        default=False,
    ),
    _cap(
        "winch_gripper", "Winch / Gripper", "SERVICES", "Payload",
        ["WINCH_STATUS"],
        ["MAV_CMD_DO_WINCH", "MAV_CMD_DO_GRIPPER"],
        default=False,
    ),

    # ---- NETWORK ---------------------------------------------------------
    _cap(
        "link_status", "Link Status / Routing", "NETWORK", "Network",
        ["RADIO_STATUS", "LINK_NODE_STATUS", "ONBOARD_COMPUTER_STATUS"],
    ),
    _cap(
        "tunnel", "TUNNEL / Encapsulation", "NETWORK", "Network",
        ["TUNNEL", "V2_EXTENSION", "DATA_TRANSMISSION_HANDSHAKE",
         "ENCAPSULATED_DATA", "SERIAL_CONTROL"],
        default=False,
    ),
    _cap(
        "can_bus", "CAN / UAVCAN", "NETWORK", "Network",
        ["CAN_FRAME", "CANFD_FRAME", "CAN_FILTER_MODIFY", "UAVCAN_NODE_*"],
        ["MAV_CMD_UAVCAN_GET_NODE_INFO"],
        default=False,
    ),
    _cap(
        "cellular_wifi", "Cellular / WiFi", "NETWORK", "Network",
        ["CELLULAR_*", "WIFI_CONFIG_AP"],
        default=False,
    ),
    _cap(
        "data_stream_legacy", "Legacy Data Streams", "NETWORK", "Deprecated",
        ["DATA_STREAM", "REQUEST_DATA_STREAM"],
        default=False,
    ),

    # ---- SECURITY --------------------------------------------------------
    _cap(
        "signing", "Packet Signing", "SECURITY", "Security",
        ["SETUP_SIGNING", "AUTH_KEY"],
        ["MAV_CMD_SECURE_COMMAND", "MAV_CMD_SECURE_COMMAND_REPLY"],
    ),
    _cap(
        "debug_messages", "Debug Messages", "SECURITY", "Debug",
        ["DEBUG", "DEBUG_VECT", "DEBUG_FLOAT_ARRAY", "NAMED_VALUE_FLOAT",
         "NAMED_VALUE_INT", "MEMORY_VECT"],
        default=False,
    ),

    # ---- PAYLOAD ---------------------------------------------------------
    _cap(
        "adsb", "ADS-B / Traffic", "PAYLOAD", "Payload",
        ["ADSB_VEHICLE", "COLLISION", "UTM_GLOBAL_POSITION", "AIS_VESSEL"],
        ["MAV_CMD_DO_ADSB_OUT_IDENT"],
        default=False,
    ),
    _cap(
        "open_drone_id", "OpenDroneID (Remote ID)", "PAYLOAD", "Payload",
        ["OPEN_DRONE_ID_*"],
        ["MAV_CMD_ODID_*"],
        default=False,
    ),
    _cap(
        "follow_orbit", "Follow / Orbit / Figure-8", "PAYLOAD", "Navigation",
        ["FOLLOW_TARGET", "ORBIT_EXECUTION_STATUS",
         "FIGURE_EIGHT_EXECUTION_STATUS", "TIME_ESTIMATE_TO_TARGET"],
        ["MAV_CMD_DO_ORBIT", "MAV_CMD_DO_FOLLOW*", "MAV_CMD_DO_FIGURE_EIGHT"],
        default=False,
    ),
    _cap(
        "relay_servo", "Relay / Aux Servo", "PAYLOAD", "Payload",
        ["RELAY_STATUS"],
        ["MAV_CMD_DO_SET_RELAY", "MAV_CMD_DO_REPEAT_RELAY",
         "MAV_CMD_DO_SET_SERVO", "MAV_CMD_DO_REPEAT_SERVO"],
        default=False,
    ),

    # ---- SIMULATION ------------------------------------------------------
    _cap(
        "hil_simulation", "HIL / SITL", "SIMULATION", "Simulation",
        ["HIL_*", "SIM_STATE"],
        default=False,
    ),
]


class CapabilitySet:
    """Resolves capability globs against a catalog."""

    def __init__(self, capabilities: list[Capability] | None = None):
        self.capabilities = list(capabilities or BUILTIN_CAPABILITIES)
        self._by_key = {c.key: c for c in self.capabilities}

    def get(self, key: str) -> Capability | None:
        return self._by_key.get(key)

    def keys(self) -> list[str]:
        return [c.key for c in self.capabilities]

    def groups(self) -> dict[str, list[Capability]]:
        result: dict[str, list[Capability]] = {}
        for capability in self.capabilities:
            result.setdefault(capability.group, []).append(capability)
        return result

    def messages_for(self, key: str, catalog: Catalog) -> set[str]:
        capability = self._by_key.get(key)
        if capability is None:
            return set()
        return {
            name
            for name in catalog.messages
            if any(fnmatch.fnmatchcase(name, p) for p in capability.messages)
        }

    def commands_for(self, key: str, catalog: Catalog) -> set[str]:
        capability = self._by_key.get(key)
        if capability is None:
            return set()
        return {
            name
            for name in catalog.commands
            if any(fnmatch.fnmatchcase(name, p) for p in capability.commands)
        }

    def owner_of_message(self, name: str) -> Capability | None:
        """First capability whose globs claim ``name`` (used for the category column)."""
        for capability in self.capabilities:
            if any(fnmatch.fnmatchcase(name, p) for p in capability.messages):
                return capability
        return None

    def owners_of_message(self, name: str) -> list[Capability]:
        return [
            c
            for c in self.capabilities
            if any(fnmatch.fnmatchcase(name, p) for p in c.messages)
        ]

    def category_of(self, name: str) -> str:
        capability = self.owner_of_message(name)
        return capability.category if capability else "Uncategorised"

    def coverage(self, catalog: Catalog) -> tuple[set[str], set[str]]:
        """(claimed, unclaimed) message names -- unclaimed ones need a home."""
        claimed: set[str] = set()
        for capability in self.capabilities:
            claimed |= self.messages_for(capability.key, catalog)
        return claimed, set(catalog.messages) - claimed
