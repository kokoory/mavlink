// End-to-end: real MAVLink bytes over a real UDP socket, through the parser and
// translator, into canonical vehicle state.
//
// The bytes are produced by the same generated MAVLink library the GCS parses
// with, so this exercises the actual wire format rather than a mock of it.

#include <sstream>
#include <thread>

#include "Check.hpp"
#include "core/app/Composition.hpp"

using namespace kmgcs;

namespace {

/// A synthetic vehicle: its own socket, sending real frames to the station.
class FakeVehicle {
public:
    FakeVehicle(std::uint16_t targetPort, std::uint8_t systemId)
        : link_(99, makeConfig(targetPort)), systemId_(systemId) {
        std::string error;
        started_ = link_.start(error);
        protocol_.setLocalAddress(systemId_, 1);
    }

    [[nodiscard]] bool ready() const { return started_; }

    void sendHeartbeat(std::uint8_t autopilot, std::uint8_t type,
                       std::uint32_t customMode, bool armed) {
        // Built through the protocol adapter's own encoder path where possible;
        // heartbeat has no encode() helper, so it is packed the same way the
        // generated library would pack it on a vehicle.
        send(packHeartbeat(autopilot, type, customMode, armed));
    }

    void sendAttitude(std::uint32_t bootMs, float roll, float pitch, float yaw);
    void sendGlobalPosition(std::uint32_t bootMs, double lat, double lon, double altM);
    void sendGpsRaw(std::uint8_t fixType, std::uint8_t satellites);
    void sendSysStatus(double voltageV, int remainingPercent);

private:
    static links::UdpLinkConfig makeConfig(std::uint16_t targetPort) {
        links::UdpLinkConfig config;
        config.listenPort = 0;  // ephemeral
        config.peer = links::Endpoint{"127.0.0.1", targetPort};
        return config;
    }

    std::vector<std::byte> packHeartbeat(std::uint8_t autopilot, std::uint8_t type,
                                         std::uint32_t customMode, bool armed);
    /// The link already knows the station's address from its config.
    void send(const std::vector<std::byte>& bytes) { link_.send(bytes); }

    links::UdpLink link_;
    protocols::mavlink::MavlinkProtocolAdapter protocol_;
    std::uint8_t systemId_;
    bool started_{false};
};

}  // namespace

// The packing helpers need the generated headers, which only this translation
// unit in the test tree is allowed to see.
#include KMGCS_MAVLINK_DIALECT_HEADER

namespace {

std::vector<std::byte> toBytes(const mavlink_message_t& message) {
    std::vector<std::byte> buffer(MAVLINK_MAX_PACKET_LEN);
    const auto length =
        mavlink_msg_to_send_buffer(reinterpret_cast<uint8_t*>(buffer.data()), &message);
    buffer.resize(length);
    return buffer;
}

}  // namespace

std::vector<std::byte> FakeVehicle::packHeartbeat(std::uint8_t autopilot,
                                                  std::uint8_t type,
                                                  std::uint32_t customMode, bool armed) {
    mavlink_message_t message{};
    mavlink_msg_heartbeat_pack(systemId_, 1, &message, type, autopilot,
                               armed ? MAV_MODE_FLAG_SAFETY_ARMED : 0,
                               customMode, MAV_STATE_STANDBY);
    return toBytes(message);
}

void FakeVehicle::sendAttitude(std::uint32_t bootMs, float roll, float pitch, float yaw) {
    mavlink_message_t message{};
    mavlink_msg_attitude_pack(systemId_, 1, &message, bootMs, roll, pitch, yaw,
                              0.0F, 0.0F, 0.0F);
    send(toBytes(message));
}

void FakeVehicle::sendGlobalPosition(std::uint32_t bootMs, double lat, double lon,
                                     double altM) {
    mavlink_message_t message{};
    mavlink_msg_global_position_int_pack(
        systemId_, 1, &message, bootMs, static_cast<int32_t>(lat * 1e7),
        static_cast<int32_t>(lon * 1e7), static_cast<int32_t>(altM * 1e3),
        static_cast<int32_t>(altM * 1e3), 100, 200, -50, UINT16_MAX);
    send(toBytes(message));
}

void FakeVehicle::sendGpsRaw(std::uint8_t fixType, std::uint8_t satellites) {
    mavlink_message_t message{};
    mavlink_msg_gps_raw_int_pack(systemId_, 1, &message, 0, fixType, 0, 0, 0,
                                 UINT16_MAX, UINT16_MAX, UINT16_MAX, UINT16_MAX,
                                 satellites, 0, 0, 0, 0, 0, 0);
    send(toBytes(message));
}

void FakeVehicle::sendSysStatus(double voltageV, int remainingPercent) {
    mavlink_message_t message{};
    mavlink_msg_sys_status_pack(
        systemId_, 1, &message,
        /*sensors present/enabled/health*/ 0, 0, 0,
        /*load*/ 0,
        static_cast<uint16_t>(voltageV * 1000),
        /*current_battery*/ -1,
        static_cast<int8_t>(remainingPercent),
        /*drop_rate_comm*/ 0, /*errors_comm*/ 0,
        /*errors_count1..4*/ 0, 0, 0, 0,
        /*extended sensors*/ 0, 0, 0);
    send(toBytes(message));
}

namespace {

/// Pump the station until @p predicate holds or the budget runs out.
template <typename Predicate>
bool pumpUntil(app::Station& station, Predicate predicate, int maxIterations = 200) {
    for (int i = 0; i < maxIterations; ++i) {
        station.poll(std::chrono::milliseconds(5));
        if (predicate()) {
            return true;
        }
    }
    return false;
}

app::StationConfig ephemeralConfig() {
    app::StationConfig config;
    config.udp.listenPort = 0;
    config.registry.heartbeatTimeout = std::chrono::seconds(30);
    return config;
}

}  // namespace

KM_TEST(a_heartbeat_over_udp_discovers_a_vehicle) {
    app::Station station(ephemeralConfig());
    std::string error;
    KM_CHECK(station.start(error));

    FakeVehicle vehicle(station.link().boundPort(), 1);
    KM_CHECK(vehicle.ready());

    vehicle.sendHeartbeat(MAV_AUTOPILOT_PX4, MAV_TYPE_QUADROTOR, 0, false);
    const bool found = pumpUntil(station, [&] {
        return station.core().store().size() == 1;
    });
    KM_CHECK(found);

    const auto snapshots = station.core().store().snapshots();
    KM_CHECK_EQ(snapshots.size(), std::size_t{1});
    KM_CHECK(snapshots.front().identity.product.autopilot == domain::AutopilotKind::Px4);
    KM_CHECK(snapshots.front().identity.product.frame == domain::FrameKind::Quadrotor);
    KM_CHECK_EQ(snapshots.front().identity.address.system, std::uint8_t{1});
}

KM_TEST(attitude_reaches_the_state_store_in_canonical_form) {
    app::Station station(ephemeralConfig());
    std::string error;
    KM_CHECK(station.start(error));
    FakeVehicle vehicle(station.link().boundPort(), 1);

    vehicle.sendHeartbeat(MAV_AUTOPILOT_PX4, MAV_TYPE_QUADROTOR, 0, false);
    pumpUntil(station, [&] { return station.core().store().size() == 1; });

    vehicle.sendAttitude(1000, 0.25F, -0.1F, 1.5F);
    const bool arrived = pumpUntil(station, [&] {
        const auto all = station.core().store().snapshots();
        return !all.empty() &&
               all.front().attitude.stamp.value.time_since_epoch().count() != 0;
    });
    KM_CHECK(arrived);

    const auto snapshot = station.core().store().snapshots().front();
    // Stored as a quaternion, displayed as Euler: the wire's Euler angles must
    // survive the conversion.
    const auto euler = domain::toEuler(snapshot.attitude.orientation);
    KM_CHECK_NEAR(euler.rollRad, 0.25, 1e-5);
    KM_CHECK_NEAR(euler.pitchRad, -0.1, 1e-5);
    KM_CHECK_NEAR(euler.yawRad, 1.5, 1e-5);
    KM_CHECK(snapshot.attitude.bodyFrame == domain::ReferenceFrame::BodyFrd);
}

KM_TEST(position_units_are_converted_not_forwarded) {
    app::Station station(ephemeralConfig());
    std::string error;
    KM_CHECK(station.start(error));
    FakeVehicle vehicle(station.link().boundPort(), 1);

    vehicle.sendHeartbeat(MAV_AUTOPILOT_PX4, MAV_TYPE_QUADROTOR, 0, false);
    pumpUntil(station, [&] { return station.core().store().size() == 1; });

    vehicle.sendGlobalPosition(2000, 37.5665, 126.9780, 120.5);
    const bool arrived = pumpUntil(station, [&] {
        const auto all = station.core().store().snapshots();
        return !all.empty() && all.front().position.global.has_value();
    });
    KM_CHECK(arrived);

    const auto snapshot = station.core().store().snapshots().front();
    // 1e7-scaled integers on the wire, degrees in the domain.
    KM_CHECK_NEAR(snapshot.position.global->latitudeDeg, 37.5665, 1e-6);
    KM_CHECK_NEAR(snapshot.position.global->longitudeDeg, 126.9780, 1e-6);
    KM_CHECK_NEAR(snapshot.position.global->altitudeAmslM, 120.5, 1e-3);
    // cm/s on the wire, m/s in the domain, with the frame named.
    KM_CHECK_NEAR(snapshot.velocity.velocityMS.x, 1.0, 1e-6);
    KM_CHECK_NEAR(snapshot.velocity.velocityMS.y, 2.0, 1e-6);
    KM_CHECK_NEAR(snapshot.velocity.velocityMS.z, -0.5, 1e-6);
    KM_CHECK(snapshot.velocity.frame == domain::ReferenceFrame::Ned);
}

KM_TEST(gps_and_battery_reach_the_store) {
    app::Station station(ephemeralConfig());
    std::string error;
    KM_CHECK(station.start(error));
    FakeVehicle vehicle(station.link().boundPort(), 1);

    vehicle.sendHeartbeat(MAV_AUTOPILOT_ARDUPILOTMEGA, MAV_TYPE_FIXED_WING, 0, false);
    pumpUntil(station, [&] { return station.core().store().size() == 1; });

    vehicle.sendGpsRaw(GPS_FIX_TYPE_3D_FIX, 14);
    vehicle.sendSysStatus(22.2, 78);
    const bool arrived = pumpUntil(station, [&] {
        const auto all = station.core().store().snapshots();
        return !all.empty() && all.front().battery.voltageV.has_value() &&
               all.front().gnss.satellitesVisible > 0;
    });
    KM_CHECK(arrived);

    const auto snapshot = station.core().store().snapshots().front();
    KM_CHECK(snapshot.gnss.fix == domain::GnssFix::Fix3D);
    KM_CHECK_EQ(snapshot.gnss.satellitesVisible, 14);
    KM_CHECK_NEAR(*snapshot.battery.voltageV, 22.2, 1e-3);
    KM_CHECK_NEAR(*snapshot.battery.remainingFraction, 0.78, 1e-6);
}

KM_TEST(the_armed_flag_comes_from_the_heartbeat) {
    // ADR 0004: this is the only trustworthy confirmation that arming worked.
    app::Station station(ephemeralConfig());
    std::string error;
    KM_CHECK(station.start(error));
    FakeVehicle vehicle(station.link().boundPort(), 1);

    vehicle.sendHeartbeat(MAV_AUTOPILOT_PX4, MAV_TYPE_QUADROTOR, 0, false);
    pumpUntil(station, [&] { return station.core().store().size() == 1; });
    KM_CHECK(!station.core().store().snapshots().front().armed.armed);

    vehicle.sendHeartbeat(MAV_AUTOPILOT_PX4, MAV_TYPE_QUADROTOR, 0, true);
    const bool armed = pumpUntil(station, [&] {
        const auto all = station.core().store().snapshots();
        return !all.empty() && all.front().armed.armed;
    });
    KM_CHECK(armed);
}

KM_TEST(px4_mode_names_come_from_the_product_adapter) {
    app::Station station(ephemeralConfig());
    std::string error;
    KM_CHECK(station.start(error));
    FakeVehicle vehicle(station.link().boundPort(), 1);

    // PX4 auto/mission: main mode 4 in byte 2, sub mode 4 in byte 3.
    const std::uint32_t missionMode = (4u << 16) | (4u << 24);
    vehicle.sendHeartbeat(MAV_AUTOPILOT_PX4, MAV_TYPE_QUADROTOR, missionMode, false);
    const bool named = pumpUntil(station, [&] {
        const auto all = station.core().store().snapshots();
        return !all.empty() && all.front().mode.known();
    });
    KM_CHECK(named);
    KM_CHECK_EQ(station.core().store().snapshots().front().mode.name,
                std::string("Mission"));
}

KM_TEST(two_vehicles_on_one_link_stay_separate) {
    app::Station station(ephemeralConfig());
    std::string error;
    KM_CHECK(station.start(error));

    FakeVehicle px4(station.link().boundPort(), 1);
    FakeVehicle ardupilot(station.link().boundPort(), 2);

    px4.sendHeartbeat(MAV_AUTOPILOT_PX4, MAV_TYPE_QUADROTOR, 0, false);
    ardupilot.sendHeartbeat(MAV_AUTOPILOT_ARDUPILOTMEGA, MAV_TYPE_FIXED_WING, 0, false);
    const bool both = pumpUntil(station, [&] {
        return station.core().store().size() == 2;
    });
    KM_CHECK(both);

    const auto snapshots = station.core().store().snapshots();
    KM_CHECK_EQ(snapshots.size(), std::size_t{2});
    bool sawPx4 = false, sawArduPilot = false;
    for (const auto& snapshot : snapshots) {
        if (snapshot.identity.product.autopilot == domain::AutopilotKind::Px4) sawPx4 = true;
        if (snapshot.identity.product.autopilot == domain::AutopilotKind::ArduPilot)
            sawArduPilot = true;
    }
    KM_CHECK(sawPx4);
    KM_CHECK(sawArduPilot);
}

KM_TEST(a_ground_station_heartbeat_is_not_a_vehicle) {
    app::Station station(ephemeralConfig());
    std::string error;
    KM_CHECK(station.start(error));
    FakeVehicle other(station.link().boundPort(), 250);

    other.sendHeartbeat(MAV_AUTOPILOT_INVALID, MAV_TYPE_GCS, 0, false);
    for (int i = 0; i < 40; ++i) {
        station.poll(std::chrono::milliseconds(5));
    }
    KM_CHECK_EQ(station.core().store().size(), std::size_t{0});
}

KM_TEST(the_parser_survives_garbage) {
    app::Station station(ephemeralConfig());
    std::string error;
    KM_CHECK(station.start(error));
    FakeVehicle vehicle(station.link().boundPort(), 1);

    // Random bytes, then a valid heartbeat. The frame after the garbage must
    // still be found: a link does not get to poison the parser permanently.
    links::UdpLinkConfig noise;
    noise.listenPort = 0;
    noise.peer = links::Endpoint{"127.0.0.1", station.link().boundPort()};
    links::UdpLink noiseLink(98, noise);
    std::string noiseError;
    KM_CHECK(noiseLink.start(noiseError));
    std::vector<std::byte> garbage(64, std::byte{0xAB});
    noiseLink.send(garbage);

    vehicle.sendHeartbeat(MAV_AUTOPILOT_PX4, MAV_TYPE_QUADROTOR, 0, false);
    const bool found = pumpUntil(station, [&] {
        return station.core().store().size() == 1;
    });
    KM_CHECK(found);
}

KM_MAIN("pipeline")
