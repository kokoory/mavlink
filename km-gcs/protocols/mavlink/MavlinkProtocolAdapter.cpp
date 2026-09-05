#include "MavlinkProtocolAdapter.hpp"

// The generated dialect header is chosen by the build from the mavstudio
// profile, so the message set this file compiles against is the one the profile
// selected. See cmake/KmGcsMavlink.cmake.
#ifndef KMGCS_MAVLINK_DIALECT_HEADER
#error "KMGCS_MAVLINK_DIALECT_HEADER not defined; configure through km-gcs/CMakeLists.txt"
#endif

#include KMGCS_MAVLINK_DIALECT_HEADER

#include <stdexcept>

namespace kmgcs::protocols::mavlink {

struct MavlinkProtocolAdapter::Channel {
    std::uint8_t index{0};
    mavlink_message_t message{};
    mavlink_status_t status{};
};

MavlinkProtocolAdapter::MavlinkProtocolAdapter() = default;
MavlinkProtocolAdapter::~MavlinkProtocolAdapter() = default;

void MavlinkProtocolAdapter::setLocalAddress(std::uint8_t system, std::uint8_t component) {
    localSystem_ = system;
    localComponent_ = component;
}

MavlinkProtocolAdapter::Channel& MavlinkProtocolAdapter::channelFor(links::LinkId link) {
    const auto found = channels_.find(link);
    if (found != channels_.end()) {
        return *found->second;
    }
    if (nextChannel_ >= MAVLINK_COMM_NUM_BUFFERS) {
        // Reuse the last channel rather than corrupting memory. Frames may be
        // lost when two links share a parser, so this is reported, not silent.
        --nextChannel_;
    }
    auto channel = std::make_unique<Channel>();
    channel->index = nextChannel_++;
    auto& reference = *channel;
    channels_.emplace(link, std::move(channel));
    return reference;
}

void MavlinkProtocolAdapter::consume(links::LinkId link, std::span<const std::byte> bytes,
                                     const links::Endpoint& from,
                                     domain::TimePoint arrival) {
    Channel& channel = channelFor(link);
    stats_.bytesConsumed += bytes.size();

    for (const std::byte raw : bytes) {
        const auto value = static_cast<std::uint8_t>(raw);
        const uint8_t parsed = mavlink_parse_char(channel.index, value,
                                                  &channel.message, &channel.status);
        if (parsed == 0) {
            continue;
        }

        ++stats_.framesParsed;
        const bool isSigned = (channel.message.incompat_flags &
                               MAVLINK_IFLAG_SIGNED) != 0;
        if (isSigned) {
            ++stats_.signedFrames;
        }

        if (frameHandler_) {
            MavlinkFrame frame;
            frame.link = link;
            frame.from = from;
            frame.arrival = arrival;
            frame.systemId = channel.message.sysid;
            frame.componentId = channel.message.compid;
            frame.messageId = channel.message.msgid;
            frame.isSigned = isSigned;
            frame.message = &channel.message;
            frameHandler_(frame);
        }
    }

    // parse_error accumulates across the whole stream, so report the delta.
    const auto errors = static_cast<std::uint64_t>(channel.status.parse_error);
    if (errors > stats_.parseErrors) {
        stats_.parseErrors = errors;
    }
}

std::vector<std::byte> MavlinkProtocolAdapter::encode(const ProtocolCommand& command) {
    mavlink_message_t message{};
    mavlink_msg_command_long_pack(
        localSystem_, localComponent_, &message,
        command.targetSystem, command.targetComponent, command.command,
        command.confirmation ? 1 : 0,
        command.params[0], command.params[1], command.params[2],
        command.params[3], command.params[4], command.params[5], command.params[6]);

    std::vector<std::byte> buffer(MAVLINK_MAX_PACKET_LEN);
    const auto length = mavlink_msg_to_send_buffer(
        reinterpret_cast<uint8_t*>(buffer.data()), &message);
    buffer.resize(length);
    ++stats_.framesEncoded;
    return buffer;
}

std::vector<std::byte> MavlinkProtocolAdapter::encodeTimesyncRequest(
    std::uint8_t targetSystem, std::uint8_t targetComponent, std::int64_t localTimeNs) {
    mavlink_message_t message{};
    // tc1 = 0 marks this as a request; the responder fills it with its own
    // clock and echoes ts1 so the round trip can be measured.
    mavlink_msg_timesync_pack(localSystem_, localComponent_, &message,
                              0, localTimeNs, targetSystem, targetComponent);

    std::vector<std::byte> buffer(MAVLINK_MAX_PACKET_LEN);
    const auto length = mavlink_msg_to_send_buffer(
        reinterpret_cast<uint8_t*>(buffer.data()), &message);
    buffer.resize(length);
    ++stats_.framesEncoded;
    return buffer;
}

}  // namespace kmgcs::protocols::mavlink
