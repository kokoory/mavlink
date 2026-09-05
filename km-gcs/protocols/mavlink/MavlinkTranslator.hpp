// MAVLink to canonical translation.
//
// This is the boundary the whole architecture rests on. Above it, nothing knows
// that MAVLink exists; below it, nothing knows what a VehicleSnapshot is. Every
// unit and frame conversion happens here, explicitly, once.

#pragma once

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <vector>

#include "core/domain/Identity.hpp"
#include "core/domain/Time.hpp"
#include "core/domain/VehicleState.hpp"
#include "core/event/EventBus.hpp"
#include "protocols/mavlink/MavlinkProtocolAdapter.hpp"

namespace kmgcs::protocols::mavlink {

/// Resolves a wire address to the handle the rest of the system uses.
/// Supplied by the registry so the translator never invents identity.
using HandleResolver =
    std::function<domain::VehicleHandle(const domain::SystemAddress&,
                                        const domain::ProductType&,
                                        domain::TimePoint)>;

/// Asks for a TIMESYNC to be sent. The translator decides when a sync is due;
/// the composition root decides how bytes reach the vehicle.
using TimesyncRequester = std::function<void(const domain::SystemAddress&)>;

class MavlinkTranslator {
public:
    explicit MavlinkTranslator(event::EventBus& bus);

    void setHandleResolver(HandleResolver resolver) {
        resolveHandle_ = std::move(resolver);
    }
    void setTimesyncRequester(TimesyncRequester requester) {
        requestTimesync_ = std::move(requester);
    }

    /// Translate one decoded frame into zero or more domain events.
    void translate(const MavlinkFrame& frame);

    /// Feed a completed TIMESYNC round trip measured by the composition root.
    void observeTimesync(const domain::SystemAddress& address,
                         domain::TimePoint requestSent,
                         domain::TimePoint responseReceived,
                         std::int64_t vehicleTimeNs);

    [[nodiscard]] domain::TimeQuality timeQuality(
        const domain::SystemAddress& address) const;

    /// Messages seen but not translated, for coverage reporting. A profile can
    /// require a message the translator silently ignores; this is how that gets
    /// noticed rather than shipped.
    [[nodiscard]] std::map<std::uint32_t, std::uint64_t> untranslated() const {
        return untranslated_;
    }
    [[nodiscard]] std::uint64_t translatedCount() const { return translated_; }

private:
    struct VehicleTiming {
        /// time_boot_ms lives here. Only ever anchored from arrival times:
        /// no MAVLink mechanism synchronises the boot clock directly.
        domain::TimeBase bootBase;
        /// The vehicle's absolute clock, synchronised by TIMESYNC.
        domain::TimeBase epochBase;
        domain::TimePoint lastSyncRequest{};
        std::uint64_t syncRequests{0};
        /// Last quality reported upward, so a change is published once rather
        /// than on every frame.
        domain::TimeQuality reported{domain::TimeQuality::None};
    };

    VehicleTiming& timingFor(const domain::SystemAddress& address);
    domain::Timestamp stampFromBootMs(const domain::SystemAddress& address,
                                      std::uint32_t bootMs,
                                      domain::TimePoint arrival);
    domain::Timestamp stampFromUsec(const domain::SystemAddress& address,
                                    std::uint64_t usec, domain::TimePoint arrival);
    void maybeRequestTimesync(const domain::SystemAddress& address,
                              domain::TimePoint now);
    /// Publish TimeBaseUpdated when a vehicle's time quality actually changes.
    void publishTimeQualityIfChanged(const domain::SystemAddress& address,
                                     domain::TimePoint at);

    // One handler per message, so adding a message means adding a function
    // rather than growing a switch nobody wants to read.
    void onHeartbeat(const MavlinkFrame&, domain::VehicleHandle);
    void onAttitude(const MavlinkFrame&, domain::VehicleHandle);
    void onAttitudeQuaternion(const MavlinkFrame&, domain::VehicleHandle);
    void onGlobalPosition(const MavlinkFrame&, domain::VehicleHandle);
    void onGpsRaw(const MavlinkFrame&, domain::VehicleHandle);
    void onBatteryStatus(const MavlinkFrame&, domain::VehicleHandle);
    void onSysStatus(const MavlinkFrame&, domain::VehicleHandle);
    void onAvailableModes(const MavlinkFrame&, domain::VehicleHandle);
    void onCurrentMode(const MavlinkFrame&, domain::VehicleHandle);
    void onCommandAck(const MavlinkFrame&, domain::VehicleHandle);
    void onTimesync(const MavlinkFrame&, domain::VehicleHandle);
    void onAutopilotVersion(const MavlinkFrame&, domain::VehicleHandle);
    void onStatustext(const MavlinkFrame&, domain::VehicleHandle);

    event::EventBus& bus_;
    HandleResolver resolveHandle_;
    TimesyncRequester requestTimesync_;
    std::map<domain::SystemAddress, VehicleTiming> timing_;
    /// Modes accumulate across several AVAILABLE_MODES messages before the list
    /// is complete, so they are held per vehicle until the last one arrives.
    std::map<domain::SystemAddress, std::vector<domain::AvailableMode>> modeLists_;
    std::map<std::uint32_t, std::uint64_t> untranslated_;
    std::uint64_t translated_{0};
};

}  // namespace kmgcs::protocols::mavlink
