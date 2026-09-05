// MAVLink framing.
//
// Parsing, CRC, signing metadata, sysid/compid routing. Everything here is
// about the wire format; nothing here knows that PX4 exists.

#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <unordered_map>

#include "protocols/common/ProtocolAdapter.hpp"

namespace kmgcs::protocols::mavlink {

/// One decoded frame, handed to the translator.
///
/// The raw message is deliberately opaque above this file: the pointer type is
/// only meaningful inside the MAVLink layer, which is why it is void here and
/// cast back in the translator. Keeping the concrete type out of the header is
/// what stops mavlink_message_t from spreading through the include graph.
struct MavlinkFrame {
    links::LinkId link{0};
    links::Endpoint from;
    domain::TimePoint arrival{};
    std::uint8_t systemId{0};
    std::uint8_t componentId{0};
    std::uint32_t messageId{0};
    bool isSigned{false};
    const void* message{nullptr};  ///< mavlink_message_t*, valid for the call only
};

using FrameHandler = std::function<void(const MavlinkFrame&)>;

class MavlinkProtocolAdapter final : public IProtocolAdapter {
public:
    MavlinkProtocolAdapter();
    ~MavlinkProtocolAdapter() override;

    MavlinkProtocolAdapter(const MavlinkProtocolAdapter&) = delete;
    MavlinkProtocolAdapter& operator=(const MavlinkProtocolAdapter&) = delete;

    [[nodiscard]] std::string name() const override { return "mavlink2"; }
    [[nodiscard]] ProtocolStats stats() const override { return stats_; }

    void consume(links::LinkId link, std::span<const std::byte> bytes,
                 const links::Endpoint& from, domain::TimePoint arrival) override;

    std::vector<std::byte> encode(const ProtocolCommand& command) override;

    void onFrame(FrameHandler handler) { frameHandler_ = std::move(handler); }

    /// Identity this ground station presents on the wire.
    void setLocalAddress(std::uint8_t system, std::uint8_t component);
    [[nodiscard]] std::uint8_t localSystem() const { return localSystem_; }
    [[nodiscard]] std::uint8_t localComponent() const { return localComponent_; }

    /// Encode a TIMESYNC request. Time synchronisation is part of the baseline
    /// rather than a later addition, because without it every telemetry
    /// timestamp is arrival time and the timing conformance axis has nothing
    /// to measure. See ADR 0003.
    std::vector<std::byte> encodeTimesyncRequest(std::uint8_t targetSystem,
                                                 std::uint8_t targetComponent,
                                                 std::int64_t localTimeNs);

private:
    struct Channel;
    /// One parser per link: MAVLink parse state is per byte stream, and sharing
    /// it across links corrupts frames whenever two links carry traffic at once.
    Channel& channelFor(links::LinkId link);

    std::unordered_map<links::LinkId, std::unique_ptr<Channel>> channels_;
    FrameHandler frameHandler_;
    ProtocolStats stats_;
    std::uint8_t localSystem_{255};    ///< 255 is the conventional GCS system id
    std::uint8_t localComponent_{190}; ///< MAV_COMP_ID_MISSIONPLANNER
    std::uint8_t nextChannel_{0};
};

}  // namespace kmgcs::protocols::mavlink
