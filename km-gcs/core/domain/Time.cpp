#include "Time.hpp"

#include <algorithm>

namespace kmgcs::domain {

void TimeBase::observeSync(TimePoint requestSent, TimePoint responseReceived,
                           std::chrono::nanoseconds vehicleTime) {
    const auto rtt = responseReceived - requestSent;
    // Assume a symmetric path: the vehicle stamped tc1 roughly half an RTT
    // after we sent ts1. This is the same assumption NTP makes, and the RTT is
    // reported alongside so a caller can judge how much it is worth.
    const auto midpoint = requestSent + rtt / 2;
    const auto sample = vehicleTime - midpoint.time_since_epoch();

    if (samples_ == 0) {
        offset_ = sample;
    } else {
        // Exponential smoothing. Enough to damp jitter without a filter that
        // needs tuning before the first flight.
        constexpr int kSmoothingNumerator = 1;
        constexpr int kSmoothingDenominator = 4;
        const auto delta = sample - offset_;
        offset_ += delta * kSmoothingNumerator / kSmoothingDenominator;
    }

    roundTrip_ = std::chrono::duration_cast<Duration>(rtt);
    ++samples_;
    quality_ = samples_ >= 3 ? TimeQuality::Synchronised : TimeQuality::Coarse;
}

void TimeBase::observeArrival(std::chrono::nanoseconds vehicleTime, TimePoint arrival) {
    if (quality_ == TimeQuality::Coarse || quality_ == TimeQuality::Synchronised) {
        return;  // a real sync beats an arrival-time guess
    }
    // One-way latency is unknown, so this only anchors the timeline. It is
    // deliberately marked Arrival so nothing downstream mistakes it for a
    // synchronised estimate.
    offset_ = vehicleTime - arrival.time_since_epoch();
    quality_ = TimeQuality::Arrival;
}

Timestamp TimeBase::toLocal(std::chrono::nanoseconds vehicleTime, TimePoint arrival) const {
    if (quality_ == TimeQuality::None) {
        return Timestamp{arrival, TimeQuality::None};
    }
    return Timestamp{TimePoint{vehicleTime - offset_}, quality_};
}

}  // namespace kmgcs::domain
