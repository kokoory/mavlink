#include <sstream>

#include "Check.hpp"
#include "core/domain/Command.hpp"
#include "core/domain/Time.hpp"
#include "core/domain/VehicleState.hpp"

using namespace kmgcs::domain;

KM_TEST(euler_round_trips_through_quaternion) {
    // Attitude is stored as a quaternion and shown as Euler angles; a round
    // trip has to come back to where it started or the HUD lies.
    const double roll = 0.3, pitch = -0.2, yaw = 1.1;
    const double cr = std::cos(roll / 2), sr = std::sin(roll / 2);
    const double cp = std::cos(pitch / 2), sp = std::sin(pitch / 2);
    const double cy = std::cos(yaw / 2), sy = std::sin(yaw / 2);
    const Quaternion q{cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy,
                       cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy};
    const auto e = toEuler(q);
    KM_CHECK_NEAR(e.rollRad, roll, 1e-9);
    KM_CHECK_NEAR(e.pitchRad, pitch, 1e-9);
    KM_CHECK_NEAR(e.yawRad, yaw, 1e-9);
}

KM_TEST(euler_clamps_at_gimbal_lock) {
    // Straight up must read +90 degrees, not NaN.
    const double half = std::sqrt(0.5);
    const Quaternion q{half, 0, half, 0};
    const auto e = toEuler(q);
    KM_CHECK(!std::isnan(e.pitchRad));
    KM_CHECK_NEAR(e.pitchRad, M_PI / 2, 1e-9);
}

KM_TEST(identity_keeps_handle_stable_when_address_changes) {
    // The whole reason identity is three things: renumbering a vehicle must not
    // invalidate references to it.
    VehicleIdentity identity;
    identity.handle = VehicleHandle{7};
    identity.address = SystemAddress{1, 1};
    const auto before = identity.handle;
    identity.address = SystemAddress{42, 1};
    KM_CHECK(identity.handle == before);
    KM_CHECK(identity.address != (SystemAddress{1, 1}));
}

KM_TEST(hardware_id_is_optional) {
    HardwareId empty;
    KM_CHECK(!empty.known());
    HardwareId legacy;
    legacy.uid = 12345;
    KM_CHECK(legacy.known());
}

KM_TEST(time_base_reports_no_estimate_before_any_sync) {
    TimeBase base;
    KM_CHECK(base.quality() == TimeQuality::None);
    const auto arrival = now();
    const auto stamp = base.toLocal(std::chrono::nanoseconds(500), arrival);
    // With no estimate the only honest answer is arrival time, flagged as such.
    KM_CHECK(stamp.quality == TimeQuality::None);
    KM_CHECK(stamp.value == arrival);
}

KM_TEST(time_base_becomes_synchronised_after_several_round_trips) {
    TimeBase base;
    const auto start = now();
    for (int i = 0; i < 4; ++i) {
        const auto sent = start + std::chrono::milliseconds(100 * i);
        const auto received = sent + std::chrono::milliseconds(20);
        const auto vehicleTime = (sent + std::chrono::milliseconds(10))
                                     .time_since_epoch() +
                                 std::chrono::seconds(1000);
        base.observeSync(sent, received, vehicleTime);
    }
    KM_CHECK(base.quality() == TimeQuality::Synchronised);
    KM_CHECK(base.roundTrip().has_value());
    // Offset should land near the 1000 s the synthetic vehicle clock is ahead.
    const auto offsetSeconds =
        std::chrono::duration_cast<std::chrono::seconds>(base.offset()).count();
    KM_CHECK_EQ(offsetSeconds, 1000);
}

KM_TEST(a_synced_epoch_clock_must_not_convert_boot_relative_stamps) {
    // Found by running the headless station against a vehicle that answers
    // TIMESYNC: the vehicle's absolute clock and its time_boot_ms are different
    // clocks, and converting one with the other's offset put timestamps decades
    // out. Each clock needs its own TimeBase.
    TimeBase epochBase;
    TimeBase bootBase;

    const auto sent = now();
    const auto received = sent + std::chrono::milliseconds(20);
    // Vehicle absolute clock, far from our steady_clock epoch.
    const auto vehicleAbsolute = std::chrono::nanoseconds(
        std::chrono::seconds(1700000000));
    epochBase.observeSync(sent, received, vehicleAbsolute);
    KM_CHECK(epochBase.quality() == TimeQuality::Coarse);

    // A boot-relative stamp: 12.345 s since the vehicle powered up.
    const auto boot = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::milliseconds(12345));
    const auto arrival = received + std::chrono::milliseconds(5);

    // Converting the boot stamp with the epoch offset is nonsense...
    const auto wrong = epochBase.toLocal(boot, arrival);
    const auto wrongError = wrong.value > arrival ? wrong.value - arrival
                                                  : arrival - wrong.value;
    KM_CHECK(wrongError > std::chrono::hours(24 * 365));

    // ...while its own base keeps it near arrival, where it belongs.
    bootBase.observeArrival(boot, arrival);
    const auto right = bootBase.toLocal(boot, arrival);
    const auto rightError = right.value > arrival ? right.value - arrival
                                                  : arrival - right.value;
    KM_CHECK(rightError < std::chrono::seconds(1));
}

KM_TEST(arm_is_only_confirmed_by_armed_state) {
    // ADR 0004: an ACCEPTED ack is not proof the vehicle armed.
    VehicleCommand arm;
    arm.kind = CommandKind::Arm;
    const auto policy = defaultPolicyFor(arm);
    KM_CHECK(policy.confirmed != nullptr);

    VehicleSnapshot disarmed;
    disarmed.armed.armed = false;
    KM_CHECK(!policy.confirmed(disarmed));

    VehicleSnapshot armed;
    armed.armed.armed = true;
    KM_CHECK(policy.confirmed(armed));
}

KM_TEST(land_has_no_state_confirmation) {
    // Nothing observable proves a landing started, and waiting for touchdown
    // would block for minutes, so Accepted is the honest terminal state.
    VehicleCommand land;
    land.kind = CommandKind::Land;
    KM_CHECK(defaultPolicyFor(land).confirmed == nullptr);
}

KM_TEST(command_outcome_terminality) {
    CommandOutcome accepted;
    accepted.stage = CommandStage::Accepted;
    // Accepted is acknowledged but NOT terminal: the tracker keeps watching
    // until the effect shows up or the confirm timeout expires.
    KM_CHECK(accepted.acknowledged());
    KM_CHECK(!accepted.terminal());

    CommandOutcome confirmed;
    confirmed.stage = CommandStage::Confirmed;
    KM_CHECK(confirmed.acknowledged());
    KM_CHECK(confirmed.terminal());

    CommandOutcome inProgress;
    inProgress.stage = CommandStage::InProgress;
    KM_CHECK(!inProgress.acknowledged());
    KM_CHECK(!inProgress.terminal());
}

KM_TEST(set_mode_confirms_against_the_requested_mode) {
    VehicleCommand setMode;
    setMode.kind = CommandKind::SetFlightMode;
    FlightMode wanted;
    wanted.vendorCode = 5;
    wanted.name = "Loiter";
    setMode.mode = wanted;

    const auto policy = defaultPolicyFor(setMode);
    VehicleSnapshot other;
    other.mode.vendorCode = 3;
    KM_CHECK(!policy.confirmed(other));
    VehicleSnapshot matching;
    matching.mode.vendorCode = 5;
    KM_CHECK(policy.confirmed(matching));
}

KM_MAIN("domain")
