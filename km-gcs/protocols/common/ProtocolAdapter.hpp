// Protocol abstraction.
//
// A protocol adapter turns bytes into something the translator can read, and
// turns a protocol-neutral command into bytes. It does not decide what a PX4
// flight mode means: that is the product adapter's job, one layer up.

#pragma once

#include <cstdint>
#include <span>
#include <string>

#include "core/domain/Time.hpp"
#include "links/common/Link.hpp"

namespace kmgcs::protocols {

struct ProtocolStats {
    std::uint64_t framesParsed{0};
    std::uint64_t parseErrors{0};
    std::uint64_t bytesConsumed{0};
    std::uint64_t framesEncoded{0};
    std::uint64_t signedFrames{0};
};

/// A command expressed in terms the protocol understands, produced by a product
/// adapter and consumed by a protocol adapter. Deliberately generic: the fields
/// map onto MAVLink's COMMAND_LONG shape because that is what we speak today,
/// but nothing above this layer constructs one directly.
struct ProtocolCommand {
    std::uint16_t command{0};
    std::uint8_t targetSystem{0};
    std::uint8_t targetComponent{0};
    float params[7]{};
    bool confirmation{false};
};

class IProtocolAdapter {
public:
    virtual ~IProtocolAdapter() = default;

    [[nodiscard]] virtual std::string name() const = 0;
    [[nodiscard]] virtual ProtocolStats stats() const = 0;

    /// Feed bytes that arrived on a link. Frames may span datagrams, so the
    /// adapter keeps whatever parser state it needs.
    virtual void consume(links::LinkId link, std::span<const std::byte> bytes,
                         const links::Endpoint& from, domain::TimePoint arrival) = 0;

    virtual std::vector<std::byte> encode(const ProtocolCommand& command) = 0;
};

}  // namespace kmgcs::protocols
