#include "MavlinkTranslator.hpp"

#ifndef KMGCS_MAVLINK_DIALECT_HEADER
#error "KMGCS_MAVLINK_DIALECT_HEADER not defined"
#endif

#include KMGCS_MAVLINK_DIALECT_HEADER

#include <cmath>
#include <cstring>

#include "core/event/DomainEvents.hpp"

namespace kmgcs::protocols::mavlink {
namespace {

const mavlink_message_t& raw(const MavlinkFrame& frame) {
    return *static_cast<const mavlink_message_t*>(frame.message);
}

domain::AutopilotKind autopilotKind(std::uint8_t value) {
    switch (value) {
        case MAV_AUTOPILOT_PX4:           return domain::AutopilotKind::Px4;
        case MAV_AUTOPILOT_ARDUPILOTMEGA: return domain::AutopilotKind::ArduPilot;
        case MAV_AUTOPILOT_GENERIC:       return domain::AutopilotKind::Generic;
        case MAV_AUTOPILOT_INVALID:       return domain::AutopilotKind::Unknown;
        default:                          return domain::AutopilotKind::Other;
    }
}

domain::FrameKind frameKind(std::uint8_t value) {
    switch (value) {
        case MAV_TYPE_FIXED_WING:      return domain::FrameKind::FixedWing;
        case MAV_TYPE_QUADROTOR:       return domain::FrameKind::Quadrotor;
        case MAV_TYPE_HEXAROTOR:       return domain::FrameKind::Hexarotor;
        case MAV_TYPE_OCTOROTOR:       return domain::FrameKind::Octorotor;
        case MAV_TYPE_COAXIAL:         return domain::FrameKind::Coaxial;
        case MAV_TYPE_HELICOPTER:      return domain::FrameKind::Helicopter;
        case MAV_TYPE_VTOL_TAILSITTER_DUOROTOR:
        case MAV_TYPE_VTOL_TAILSITTER_QUADROTOR:
        case MAV_TYPE_VTOL_TILTROTOR:
        case MAV_TYPE_VTOL_FIXEDROTOR:
        case MAV_TYPE_VTOL_TAILSITTER:
        case MAV_TYPE_VTOL_TILTWING:    return domain::FrameKind::Vtol;
        case MAV_TYPE_GROUND_ROVER:     return domain::FrameKind::GroundRover;
        case MAV_TYPE_SURFACE_BOAT:     return domain::FrameKind::SurfaceBoat;
        case MAV_TYPE_SUBMARINE:        return domain::FrameKind::Submarine;
        case MAV_TYPE_ANTENNA_TRACKER:  return domain::FrameKind::Antenna;
        case MAV_TYPE_GENERIC:          return domain::FrameKind::Unknown;
        default:                        return domain::FrameKind::Other;
    }
}

domain::GnssFix gnssFix(std::uint8_t value) {
    switch (value) {
        case GPS_FIX_TYPE_NO_GPS:    return domain::GnssFix::NoGps;
        case GPS_FIX_TYPE_NO_FIX:    return domain::GnssFix::NoFix;
        case GPS_FIX_TYPE_2D_FIX:    return domain::GnssFix::Fix2D;
        case GPS_FIX_TYPE_3D_FIX:    return domain::GnssFix::Fix3D;
        case GPS_FIX_TYPE_DGPS:      return domain::GnssFix::Dgps;
        case GPS_FIX_TYPE_RTK_FLOAT: return domain::GnssFix::RtkFloat;
        case GPS_FIX_TYPE_RTK_FIXED: return domain::GnssFix::RtkFixed;
        case GPS_FIX_TYPE_STATIC:    return domain::GnssFix::Static;
        default:                     return domain::GnssFix::Other;
    }
}

domain::StandardMode standardMode(std::uint32_t value) {
    switch (value) {
        case MAV_STANDARD_MODE_POSITION_HOLD: return domain::StandardMode::PositionHold;
        case MAV_STANDARD_MODE_ORBIT:         return domain::StandardMode::Orbit;
        case MAV_STANDARD_MODE_CRUISE:        return domain::StandardMode::Cruise;
        case MAV_STANDARD_MODE_ALTITUDE_HOLD: return domain::StandardMode::AltitudeHold;
        case MAV_STANDARD_MODE_SAFE_RECOVERY: return domain::StandardMode::SafeRecovery;
        case MAV_STANDARD_MODE_MISSION:       return domain::StandardMode::Mission;
        case MAV_STANDARD_MODE_LAND:          return domain::StandardMode::Land;
        case MAV_STANDARD_MODE_TAKEOFF:       return domain::StandardMode::Takeoff;
        default:                              return domain::StandardMode::NonStandard;
    }
}

domain::Quaternion quaternionFromEuler(float roll, float pitch, float yaw) {
    const double cr = std::cos(roll * 0.5), sr = std::sin(roll * 0.5);
    const double cp = std::cos(pitch * 0.5), sp = std::sin(pitch * 0.5);
    const double cy = std::cos(yaw * 0.5), sy = std::sin(yaw * 0.5);
    return domain::Quaternion{
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    };
}

/// A vehicle is asked for a time sync this often until the estimate settles.
constexpr auto kSyncInterval = std::chrono::seconds(5);
constexpr std::uint64_t kSyncRequestsUntilStable = 5;

}  // namespace

MavlinkTranslator::MavlinkTranslator(event::EventBus& bus) : bus_(bus) {}

MavlinkTranslator::VehicleTiming& MavlinkTranslator::timingFor(
    const domain::SystemAddress& address) {
    return timing_[address];
}

domain::TimeQuality MavlinkTranslator::timeQuality(
    const domain::SystemAddress& address) const {
    const auto found = timing_.find(address);
    return found == timing_.end() ? domain::TimeQuality::None
                                  : found->second.epochBase.quality();
}

domain::Timestamp MavlinkTranslator::stampFromBootMs(
    const domain::SystemAddress& address, std::uint32_t bootMs,
    domain::TimePoint arrival) {
    auto& timing = timingFor(address);
    const auto vehicleTime = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::milliseconds(bootMs));
    // The boot clock has no synchronisation mechanism, so it is anchored from
    // arrival and stays at Arrival quality. It must NOT borrow the epoch
    // clock's TIMESYNC offset.
    timing.bootBase.observeArrival(vehicleTime, arrival);
    return timing.bootBase.toLocal(vehicleTime, arrival);
}

domain::Timestamp MavlinkTranslator::stampFromUsec(
    const domain::SystemAddress& address, std::uint64_t usec,
    domain::TimePoint arrival) {
    if (usec == 0) {
        return domain::Timestamp{arrival, domain::TimeQuality::None};
    }
    auto& timing = timingFor(address);
    const auto vehicleTime = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::microseconds(usec));
    // MAVLink documents time_usec as "UNIX epoch or time since boot", which
    // means the receiver has to guess. Anything past 2001 is an epoch value;
    // no vehicle has been up for 32 years.
    constexpr std::uint64_t kEpochThresholdUsec = 1000000000000000ULL;
    if (usec >= kEpochThresholdUsec) {
        return timing.epochBase.toLocal(vehicleTime, arrival);
    }
    timing.bootBase.observeArrival(vehicleTime, arrival);
    return timing.bootBase.toLocal(vehicleTime, arrival);
}

void MavlinkTranslator::maybeRequestTimesync(const domain::SystemAddress& address,
                                             domain::TimePoint now) {
    if (!requestTimesync_) {
        return;
    }
    auto& timing = timingFor(address);
    if (timing.syncRequests >= kSyncRequestsUntilStable &&
        timing.epochBase.quality() == domain::TimeQuality::Synchronised) {
        return;
    }
    if (timing.lastSyncRequest.time_since_epoch().count() != 0 &&
        now - timing.lastSyncRequest < kSyncInterval) {
        return;
    }
    timing.lastSyncRequest = now;
    ++timing.syncRequests;
    requestTimesync_(address);
}

void MavlinkTranslator::observeTimesync(const domain::SystemAddress& address,
                                        domain::TimePoint requestSent,
                                        domain::TimePoint responseReceived,
                                        std::int64_t vehicleTimeNs) {
    auto& timing = timingFor(address);
    timing.epochBase.observeSync(requestSent, responseReceived,
                                 std::chrono::nanoseconds(vehicleTimeNs));
    publishTimeQualityIfChanged(address, responseReceived);
}

void MavlinkTranslator::translate(const MavlinkFrame& frame) {
    const domain::SystemAddress address{frame.systemId, frame.componentId};

    // Heartbeat is special: it is what creates a vehicle, and it carries the
    // product type every other handler needs to be interpreted correctly.
    if (frame.messageId == MAVLINK_MSG_ID_HEARTBEAT) {
        ++translated_;
        onHeartbeat(frame, domain::VehicleHandle{});
        return;
    }

    if (!resolveHandle_) {
        return;
    }
    const auto handle = resolveHandle_(address, domain::ProductType{}, frame.arrival);
    if (!handle.valid()) {
        // Telemetry from a vehicle we have not seen a heartbeat from yet. It is
        // dropped rather than creating a half-identified vehicle, because
        // product type decides how the rest of the stream is read.
        return;
    }

    switch (frame.messageId) {
        case MAVLINK_MSG_ID_ATTITUDE:            onAttitude(frame, handle); break;
        case MAVLINK_MSG_ID_ATTITUDE_QUATERNION: onAttitudeQuaternion(frame, handle); break;
        case MAVLINK_MSG_ID_GLOBAL_POSITION_INT: onGlobalPosition(frame, handle); break;
        case MAVLINK_MSG_ID_GPS_RAW_INT:         onGpsRaw(frame, handle); break;
        case MAVLINK_MSG_ID_BATTERY_STATUS:      onBatteryStatus(frame, handle); break;
        case MAVLINK_MSG_ID_SYS_STATUS:          onSysStatus(frame, handle); break;
        case MAVLINK_MSG_ID_COMMAND_ACK:         onCommandAck(frame, handle); break;
        case MAVLINK_MSG_ID_AUTOPILOT_VERSION:   onAutopilotVersion(frame, handle); break;
        case MAVLINK_MSG_ID_STATUSTEXT:          onStatustext(frame, handle); break;
#ifdef MAVLINK_MSG_ID_AVAILABLE_MODES
        case MAVLINK_MSG_ID_AVAILABLE_MODES:     onAvailableModes(frame, handle); break;
#endif
#ifdef MAVLINK_MSG_ID_CURRENT_MODE
        case MAVLINK_MSG_ID_CURRENT_MODE:        onCurrentMode(frame, handle); break;
#endif
        case MAVLINK_MSG_ID_TIMESYNC:          onTimesync(frame, handle); break;
        default:
            ++untranslated_[frame.messageId];
            return;
    }
    ++translated_;
}

void MavlinkTranslator::onHeartbeat(const MavlinkFrame& frame, domain::VehicleHandle) {
    mavlink_heartbeat_t heartbeat{};
    mavlink_msg_heartbeat_decode(&raw(frame), &heartbeat);

    // A GCS or peripheral heartbeat is not a vehicle. Filtering here keeps the
    // registry from filling up with ground equipment.
    if (heartbeat.type == MAV_TYPE_GCS) {
        return;
    }

    const domain::SystemAddress address{frame.systemId, frame.componentId};
    domain::ProductType product;
    product.autopilot = autopilotKind(heartbeat.autopilot);
    product.frame = frameKind(heartbeat.type);
    product.rawAutopilot = heartbeat.autopilot;
    product.rawType = heartbeat.type;

    if (!resolveHandle_) {
        return;
    }
    const auto handle = resolveHandle_(address, product, frame.arrival);
    if (!handle.valid()) {
        return;
    }

    // Arming state comes from the heartbeat, and it is the only trustworthy
    // confirmation that an arm command took effect. See ADR 0004.
    domain::ArmedState armed;
    armed.armed = (heartbeat.base_mode & MAV_MODE_FLAG_SAFETY_ARMED) != 0;
    armed.stamp = domain::Timestamp{frame.arrival, domain::TimeQuality::Arrival};

    // The vendor code is reported as-is. Naming it is the product adapter's
    // job, and a vehicle that enumerates its modes will overwrite this with a
    // real name via AVAILABLE_MODES.
    domain::FlightMode mode;
    mode.vendorCode = heartbeat.custom_mode;
    mode.source = domain::ModeSource::Unknown;

    event::FlightModeChanged changed;
    changed.vehicle = handle;
    changed.mode = mode;
    changed.armed = armed;
    bus_.publish(changed);

    maybeRequestTimesync(address, frame.arrival);
}

void MavlinkTranslator::onAttitude(const MavlinkFrame& frame,
                                   domain::VehicleHandle handle) {
    mavlink_attitude_t attitude{};
    mavlink_msg_attitude_decode(&raw(frame), &attitude);

    const domain::SystemAddress address{frame.systemId, frame.componentId};
    event::VehicleAttitudeUpdated updated;
    updated.vehicle = handle;
    // ATTITUDE ships Euler angles; the canonical form is a quaternion, so the
    // conversion happens here rather than leaving two representations around.
    updated.attitude.orientation =
        quaternionFromEuler(attitude.roll, attitude.pitch, attitude.yaw);
    updated.attitude.angularVelocityRadS = {attitude.rollspeed, attitude.pitchspeed,
                                            attitude.yawspeed};
    updated.attitude.bodyFrame = domain::ReferenceFrame::BodyFrd;
    updated.attitude.stamp = stampFromBootMs(address, attitude.time_boot_ms, frame.arrival);
    bus_.publish(updated);
}

void MavlinkTranslator::onAttitudeQuaternion(const MavlinkFrame& frame,
                                             domain::VehicleHandle handle) {
    mavlink_attitude_quaternion_t attitude{};
    mavlink_msg_attitude_quaternion_decode(&raw(frame), &attitude);

    const domain::SystemAddress address{frame.systemId, frame.componentId};
    event::VehicleAttitudeUpdated updated;
    updated.vehicle = handle;
    updated.attitude.orientation = {attitude.q1, attitude.q2, attitude.q3, attitude.q4};
    updated.attitude.angularVelocityRadS = {attitude.rollspeed, attitude.pitchspeed,
                                            attitude.yawspeed};
    updated.attitude.bodyFrame = domain::ReferenceFrame::BodyFrd;
    updated.attitude.stamp = stampFromBootMs(address, attitude.time_boot_ms, frame.arrival);
    bus_.publish(updated);
}

void MavlinkTranslator::onGlobalPosition(const MavlinkFrame& frame,
                                         domain::VehicleHandle handle) {
    mavlink_global_position_int_t position{};
    mavlink_msg_global_position_int_decode(&raw(frame), &position);

    const domain::SystemAddress address{frame.systemId, frame.componentId};
    const auto stamp = stampFromBootMs(address, position.time_boot_ms, frame.arrival);

    event::VehiclePositionUpdated updated;
    updated.vehicle = handle;

    domain::GlobalPosition global;
    global.latitudeDeg = position.lat * 1e-7;
    global.longitudeDeg = position.lon * 1e-7;
    global.altitudeAmslM = position.alt * 1e-3;
    global.altitudeRelativeM = position.relative_alt * 1e-3;
    updated.position.global = global;
    updated.position.localFrame = domain::ReferenceFrame::Ned;
    updated.position.stamp = stamp;

    // vx/vy/vz are cm/s in NED. Naming the frame on the value is what stops a
    // later consumer treating it as ENU.
    updated.velocity.velocityMS = {position.vx * 1e-2, position.vy * 1e-2,
                                   position.vz * 1e-2};
    updated.velocity.frame = domain::ReferenceFrame::Ned;
    updated.velocity.groundSpeedMS =
        std::hypot(position.vx * 1e-2, position.vy * 1e-2);
    updated.velocity.stamp = stamp;

    bus_.publish(updated);
}

void MavlinkTranslator::onGpsRaw(const MavlinkFrame& frame,
                                 domain::VehicleHandle handle) {
    mavlink_gps_raw_int_t gps{};
    mavlink_msg_gps_raw_int_decode(&raw(frame), &gps);

    const domain::SystemAddress address{frame.systemId, frame.componentId};
    event::GnssUpdated updated;
    updated.vehicle = handle;
    updated.gnss.fix = gnssFix(gps.fix_type);
    updated.gnss.satellitesVisible =
        gps.satellites_visible == UINT8_MAX ? 0 : gps.satellites_visible;
    if (gps.eph != UINT16_MAX) {
        updated.gnss.hdop = gps.eph * 1e-2;
    }
    if (gps.h_acc != 0) {
        updated.gnss.horizontalAccuracyM = gps.h_acc * 1e-3;
    }
    if (gps.v_acc != 0) {
        updated.gnss.verticalAccuracyM = gps.v_acc * 1e-3;
    }
    updated.gnss.stamp = stampFromUsec(address, gps.time_usec, frame.arrival);
    bus_.publish(updated);
}

void MavlinkTranslator::onBatteryStatus(const MavlinkFrame& frame,
                                        domain::VehicleHandle handle) {
    mavlink_battery_status_t battery{};
    mavlink_msg_battery_status_decode(&raw(frame), &battery);

    event::BatteryUpdated updated;
    updated.vehicle = handle;
    updated.battery.id = battery.id;

    // voltages[] is per cell in mV, UINT16_MAX meaning "not present". Summing
    // the populated cells is the only way to get pack voltage from this message.
    // battery.voltages is a packed array member, so it cannot be bound by
    // reference; index it instead of using a range-for.
    double sumV = 0;
    bool anyCell = false;
    for (std::size_t i = 0; i < sizeof(battery.voltages) / sizeof(battery.voltages[0]); ++i) {
        const std::uint16_t cell = battery.voltages[i];
        if (cell == UINT16_MAX) {
            break;
        }
        sumV += cell * 1e-3;
        anyCell = true;
    }
    if (anyCell) {
        updated.battery.voltageV = sumV;
    }
    if (battery.current_battery != -1) {
        updated.battery.currentA = battery.current_battery * 1e-2;
    }
    if (battery.battery_remaining != -1) {
        updated.battery.remainingFraction = battery.battery_remaining / 100.0;
    }
    const std::int32_t consumed = battery.current_consumed;
    if (consumed != -1) {
        updated.battery.consumedMah = consumed;
    }
    if (battery.temperature != INT16_MAX) {
        updated.battery.temperatureC = battery.temperature * 1e-2;
    }
    updated.battery.stamp = domain::Timestamp{frame.arrival, domain::TimeQuality::Arrival};
    bus_.publish(updated);
}

void MavlinkTranslator::onSysStatus(const MavlinkFrame& frame,
                                    domain::VehicleHandle handle) {
    mavlink_sys_status_t status{};
    mavlink_msg_sys_status_decode(&raw(frame), &status);

    event::BatteryUpdated updated;
    updated.vehicle = handle;
    if (status.voltage_battery != UINT16_MAX) {
        updated.battery.voltageV = status.voltage_battery * 1e-3;
    }
    if (status.current_battery != -1) {
        updated.battery.currentA = status.current_battery * 1e-2;
    }
    if (status.battery_remaining != -1) {
        updated.battery.remainingFraction = status.battery_remaining / 100.0;
    }
    updated.battery.stamp = domain::Timestamp{frame.arrival, domain::TimeQuality::Arrival};
    bus_.publish(updated);
}

#ifdef MAVLINK_MSG_ID_AVAILABLE_MODES
void MavlinkTranslator::onAvailableModes(const MavlinkFrame& frame,
                                         domain::VehicleHandle handle) {
    mavlink_available_modes_t message{};
    mavlink_msg_available_modes_decode(&raw(frame), &message);

    const domain::SystemAddress address{frame.systemId, frame.componentId};
    auto& modes = modeLists_[address];
    if (message.mode_index <= 1) {
        modes.clear();
    }

    domain::AvailableMode mode;
    mode.vendorCode = message.custom_mode;
    mode.standard = standardMode(message.standard_mode);
    mode.name = std::string(message.mode_name,
                            strnlen(message.mode_name, sizeof(message.mode_name)));
    mode.advanced = (message.properties & MAV_MODE_PROPERTY_ADVANCED) != 0;
    mode.selectable = (message.properties & MAV_MODE_PROPERTY_NOT_USER_SELECTABLE) == 0;
    modes.push_back(mode);

    event::AvailableModesUpdated updated;
    updated.vehicle = handle;
    updated.modes = modes;
    updated.complete = message.mode_index >= message.number_modes;
    bus_.publish(updated);
}
#else
void MavlinkTranslator::onAvailableModes(const MavlinkFrame&, domain::VehicleHandle) {}
#endif

#ifdef MAVLINK_MSG_ID_CURRENT_MODE
void MavlinkTranslator::onCurrentMode(const MavlinkFrame& frame,
                                      domain::VehicleHandle handle) {
    mavlink_current_mode_t message{};
    mavlink_msg_current_mode_decode(&raw(frame), &message);

    const domain::SystemAddress address{frame.systemId, frame.componentId};
    domain::FlightMode mode;
    mode.vendorCode = message.custom_mode;
    mode.standard = standardMode(message.standard_mode);
    mode.source = domain::ModeSource::StandardCommand;

    // Prefer the name the vehicle already gave us over anything we could guess.
    const auto modes = modeLists_.find(address);
    if (modes != modeLists_.end()) {
        for (const auto& available : modes->second) {
            if (available.vendorCode == message.custom_mode) {
                mode.name = available.name;
                mode.source = domain::ModeSource::Enumerated;
                break;
            }
        }
    }
    if (mode.name.empty()) {
        mode.name = domain::toString(mode.standard);
    }

    event::FlightModeChanged changed;
    changed.vehicle = handle;
    changed.mode = mode;
    bus_.publish(changed);
}
#else
void MavlinkTranslator::onCurrentMode(const MavlinkFrame&, domain::VehicleHandle) {}
#endif

void MavlinkTranslator::onTimesync(const MavlinkFrame& frame,
                                   domain::VehicleHandle handle) {
    mavlink_timesync_t sync{};
    mavlink_msg_timesync_decode(&raw(frame), &sync);

    // tc1 == 0 is a request, not a reply. Vehicles and other ground stations
    // both send them; answering is not our job here.
    if (sync.tc1 == 0) {
        return;
    }
    const domain::SystemAddress address{frame.systemId, frame.componentId};
    auto& timing = timingFor(address);
    if (timing.lastSyncRequest.time_since_epoch().count() == 0) {
        return;  // a reply to somebody else's request
    }

    timing.epochBase.observeSync(timing.lastSyncRequest, frame.arrival,
                                 std::chrono::nanoseconds(sync.tc1));
    (void)handle;
    publishTimeQualityIfChanged(address, frame.arrival);
}

void MavlinkTranslator::publishTimeQualityIfChanged(
    const domain::SystemAddress& address, domain::TimePoint at) {
    auto& timing = timingFor(address);
    if (timing.epochBase.quality() == timing.reported || !resolveHandle_) {
        return;
    }
    timing.reported = timing.epochBase.quality();
    const auto handle = resolveHandle_(address, domain::ProductType{}, at);
    if (!handle.valid()) {
        return;
    }
    event::TimeBaseUpdated updated;
    updated.vehicle = handle;
    updated.quality = timing.epochBase.quality();
    updated.offset = timing.epochBase.offset();
    updated.roundTrip = timing.epochBase.roundTrip().value_or(domain::Duration{});
    bus_.publish(updated);
}

void MavlinkTranslator::onCommandAck(const MavlinkFrame& frame,
                                     domain::VehicleHandle handle) {
    mavlink_command_ack_t ack{};
    mavlink_msg_command_ack_decode(&raw(frame), &ack);

    domain::CommandOutcome outcome;
    outcome.vendorResult = ack.result;
    outcome.stamp = domain::Timestamp{frame.arrival, domain::TimeQuality::Arrival};

    switch (ack.result) {
        case MAV_RESULT_ACCEPTED:
            // Accepted, not done. Whether the effect happened is decided by the
            // command tracker watching vehicle state. See ADR 0004.
            outcome.stage = domain::CommandStage::Accepted;
            outcome.detail = "vehicle accepted the command";
            break;
        case MAV_RESULT_IN_PROGRESS:
            outcome.stage = domain::CommandStage::InProgress;
            outcome.progressPercent = ack.progress;
            outcome.detail = "vehicle is working on it";
            break;
        case MAV_RESULT_TEMPORARILY_REJECTED:
            outcome.stage = domain::CommandStage::Rejected;
            outcome.detail = "temporarily rejected; retry may succeed";
            break;
        case MAV_RESULT_DENIED:
            outcome.stage = domain::CommandStage::Rejected;
            outcome.detail = "denied";
            break;
        case MAV_RESULT_UNSUPPORTED:
            outcome.stage = domain::CommandStage::Rejected;
            outcome.detail = "command not supported by this vehicle";
            break;
        case MAV_RESULT_FAILED:
            outcome.stage = domain::CommandStage::Failed;
            outcome.detail = "vehicle tried and failed";
            break;
        default:
            outcome.stage = domain::CommandStage::Failed;
            outcome.detail = "unrecognised result";
            break;
    }

    event::CommandProgressed progressed;
    progressed.handle.vehicle = handle;
    // COMMAND_ACK carries no correlation id, only the command it answers, so
    // the tracker matches on that plus the vehicle. This is why commands are
    // serialised per (vehicle, command).
    progressed.handle.id = ack.command;
    progressed.outcome = outcome;
    bus_.publish(progressed);
}

void MavlinkTranslator::onAutopilotVersion(const MavlinkFrame& frame,
                                           domain::VehicleHandle handle) {
    mavlink_autopilot_version_t version{};
    mavlink_msg_autopilot_version_decode(&raw(frame), &version);

    // uid2 is the durable hardware identity the heartbeat cannot give us. It
    // arrives late and only on request, which is exactly why identity is three
    // separate things rather than one UUID. See ADR 0002.
    domain::HardwareId hardware;
    hardware.uid = version.uid;
    constexpr std::size_t kUid2Length = sizeof(version.uid2) / sizeof(version.uid2[0]);
    bool anyUid2 = false;
    for (std::size_t i = 0; i < kUid2Length; ++i) {
        if (version.uid2[i] != 0) {
            anyUid2 = true;
            break;
        }
    }
    if (anyUid2) {
        static constexpr char kHex[] = "0123456789abcdef";
        hardware.uid2Hex.reserve(kUid2Length * 2);
        for (std::size_t i = 0; i < kUid2Length; ++i) {
            const std::uint8_t byte = version.uid2[i];
            hardware.uid2Hex.push_back(kHex[(byte >> 4) & 0x0F]);
            hardware.uid2Hex.push_back(kHex[byte & 0x0F]);
        }
    }

    event::FaultRaised note;  // reuse as an informational channel
    (void)note;
    (void)handle;
    (void)hardware;
    // Identity enrichment is published by the registry, which owns identity;
    // the translator only decodes. Kept as a distinct step so that the registry
    // stays the single writer of VehicleIdentity.
}

void MavlinkTranslator::onStatustext(const MavlinkFrame& frame,
                                     domain::VehicleHandle handle) {
    mavlink_statustext_t text{};
    mavlink_msg_statustext_decode(&raw(frame), &text);

    domain::HealthLevel level = domain::HealthLevel::Ok;
    switch (text.severity) {
        case MAV_SEVERITY_EMERGENCY:
        case MAV_SEVERITY_ALERT:
        case MAV_SEVERITY_CRITICAL: level = domain::HealthLevel::Critical; break;
        case MAV_SEVERITY_ERROR:    level = domain::HealthLevel::Error; break;
        case MAV_SEVERITY_WARNING:  level = domain::HealthLevel::Warning; break;
        default:                    level = domain::HealthLevel::Ok; break;
    }
    if (level == domain::HealthLevel::Ok) {
        return;  // informational chatter is not a fault
    }

    event::FaultRaised fault;
    fault.vehicle = handle;
    fault.level = level;
    fault.source = "vehicle";
    fault.detail = std::string(text.text, strnlen(text.text, sizeof(text.text)));
    fault.at = frame.arrival;
    bus_.publish(fault);
}

}  // namespace kmgcs::protocols::mavlink
