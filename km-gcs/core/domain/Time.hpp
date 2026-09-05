// Time and time-base estimation.
//
// The architecture document gives every domain value a sourceTime and a
// receiveTime but never says how sourceTime is obtained. That gap matters more
// than it looks: MAVLink timestamps are mostly time_boot_ms, measured from the
// vehicle's own boot, so two vehicles' "sourceTime" values are not comparable,
// a recording cannot be aligned against wall clock, and the Timing conformance
// axis has nothing to measure against.
//
// A TimeBase closes the gap. It estimates offset and rate between a vehicle's
// clock and ours, either from TIMESYNC exchanges or, failing that, from arrival
// times. Every estimate carries its own quality so downstream code can tell a
// synchronised timestamp from a guess.
//
// See docs/architecture/adr/0003-time-base.md

#pragma once

#include <chrono>
#include <cstdint>
#include <optional>

namespace kmgcs::domain {

using Clock = std::chrono::steady_clock;
using TimePoint = std::chrono::time_point<Clock, std::chrono::nanoseconds>;
using Duration = std::chrono::nanoseconds;

/// Wall-clock time, for logs and for correlating with other systems.
using WallClock = std::chrono::system_clock;
using WallTime = std::chrono::time_point<WallClock, std::chrono::nanoseconds>;

[[nodiscard]] inline TimePoint now() {
    return std::chrono::time_point_cast<std::chrono::nanoseconds>(Clock::now());
}

/// How much to trust a converted timestamp.
enum class TimeQuality {
    None,        ///< no estimate yet; the timestamp is arrival time
    Arrival,     ///< derived from arrival time only, one-way latency unknown
    Coarse,      ///< a single TIMESYNC round trip
    Synchronised ///< several round trips, offset stable
};

struct Timestamp {
    TimePoint value{};
    TimeQuality quality{TimeQuality::None};

    [[nodiscard]] bool usableForRateMeasurement() const {
        return quality != TimeQuality::None;
    }
};

/// Offset/quality estimate between ONE of a vehicle's clocks and ours.
///
/// A vehicle has more than one clock and MAVLink exposes them separately:
///
///   time_boot_ms   milliseconds since the vehicle booted
///   tc1 / time_usec  the vehicle's absolute clock, in nanoseconds/microseconds
///
/// TIMESYNC synchronises the absolute clock only. Using a TIMESYNC offset to
/// convert time_boot_ms produces timestamps wrong by however long the vehicle
/// has been powered, which is why a vehicle needs one TimeBase per clock rather
/// than one overall. Found by running the thing, not by reading the spec.
///
/// TIMESYNC carries tc1 and ts1 in nanoseconds. A GCS sends tc1 = 0 with ts1 set
/// to its own time; the vehicle answers with tc1 filled in. Offset then follows
/// from the usual NTP-style arithmetic, and the round-trip time bounds the error.
class TimeBase {
public:
    /// Feed one completed TIMESYNC round trip.
    ///
    /// @param requestSent      our time when we sent ts1
    /// @param responseReceived our time when the reply arrived
    /// @param vehicleTime      tc1 from the reply, in the vehicle's timeline
    void observeSync(TimePoint requestSent, TimePoint responseReceived,
                     std::chrono::nanoseconds vehicleTime);

    /// Feed the arrival of a message that carried a vehicle-relative timestamp.
    /// Used only until a real sync lands, so that early telemetry is not
    /// timestamped with a silent zero.
    void observeArrival(std::chrono::nanoseconds vehicleTime, TimePoint arrival);

    /// Convert a vehicle-relative timestamp into our timeline.
    [[nodiscard]] Timestamp toLocal(std::chrono::nanoseconds vehicleTime,
                                    TimePoint arrival) const;

    [[nodiscard]] TimeQuality quality() const { return quality_; }
    [[nodiscard]] std::chrono::nanoseconds offset() const { return offset_; }
    [[nodiscard]] std::optional<Duration> roundTrip() const { return roundTrip_; }
    [[nodiscard]] int sampleCount() const { return samples_; }

private:
    std::chrono::nanoseconds offset_{0};
    std::optional<Duration> roundTrip_;
    TimeQuality quality_{TimeQuality::None};
    int samples_{0};
};

}  // namespace kmgcs::domain
