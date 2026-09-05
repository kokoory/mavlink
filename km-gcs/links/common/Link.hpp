// Transport abstraction.
//
// A link moves bytes. It does not know what a MAVLink frame is, which is what
// lets the same UdpLink carry DDS or a custom protocol later without change.

#pragma once

#include <cstdint>
#include <functional>
#include <span>
#include <string>
#include <vector>

#include "core/domain/Time.hpp"

namespace kmgcs::links {

using LinkId = std::uint32_t;

/// Where a datagram came from, so a reply can go back to the same place.
/// Opaque to everything above the link: the protocol layer passes it around
/// but never interprets it.
struct Endpoint {
    std::string host;
    std::uint16_t port{0};

    friend bool operator==(const Endpoint& a, const Endpoint& b) {
        return a.port == b.port && a.host == b.host;
    }
    [[nodiscard]] std::string toString() const;
};

enum class LinkState { Down, Connecting, Up, Failed };

struct LinkStats {
    std::uint64_t bytesReceived{0};
    std::uint64_t bytesSent{0};
    std::uint64_t datagramsReceived{0};
    std::uint64_t sendErrors{0};
    std::uint64_t receiveErrors{0};
};

/// Called on the link's own thread with whatever arrived. Handlers must not
/// touch domain state; they publish, and the core thread consumes.
using BytesHandler = std::function<void(LinkId, std::span<const std::byte>,
                                        const Endpoint&, domain::TimePoint)>;
using StateHandler = std::function<void(LinkId, LinkState, const std::string&)>;

class ILink {
public:
    virtual ~ILink() = default;

    [[nodiscard]] virtual LinkId id() const = 0;
    [[nodiscard]] virtual std::string description() const = 0;
    [[nodiscard]] virtual LinkState state() const = 0;
    [[nodiscard]] virtual LinkStats stats() const = 0;

    virtual bool start(std::string& error) = 0;
    virtual void stop() = 0;

    /// Send to the default peer, or to @p to when given.
    virtual bool send(std::span<const std::byte> bytes) = 0;
    virtual bool sendTo(std::span<const std::byte> bytes, const Endpoint& to) = 0;

    /// Pump the link once, delivering at most @p budget datagrams.
    ///
    /// An explicit pump rather than an internal thread keeps the first version
    /// single-threaded and deterministic in tests; a worker thread can call it
    /// in a loop later without the interface changing.
    virtual std::size_t poll(domain::Duration timeout, std::size_t budget) = 0;

    void onBytes(BytesHandler handler) { bytesHandler_ = std::move(handler); }
    void onStateChanged(StateHandler handler) { stateHandler_ = std::move(handler); }

protected:
    BytesHandler bytesHandler_;
    StateHandler stateHandler_;
};

[[nodiscard]] const char* toString(LinkState state);

}  // namespace kmgcs::links
