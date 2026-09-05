// Typed, plugin-extensible event bus.
//
// The architecture document defines DomainEvent as a closed std::variant. That
// contradicts its own plugin principle (P7): a plugin cannot add an alternative
// to a variant that was sealed when the core was compiled. It also means every
// new core event recompiles every translation unit that touches the bus.
//
// So events are type-erased behind a stable per-type id, and subscription stays
// type-safe through a small template front end. A plugin can define its own
// event struct and publish it without the core knowing the type exists.
//
// Threading: publish() may be called from any thread. Delivery happens on
// whichever thread calls drain(), which is how the core keeps a single owner
// for domain state without every producer needing to know that.
//
// See docs/architecture/adr/0005-event-bus.md

#pragma once

#include <atomic>
#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <typeindex>
#include <unordered_map>
#include <vector>

namespace kmgcs::event {

/// Stable identity for an event type. Derived from the C++ type, so two
/// translation units agree without a central registry to keep in sync.
class EventType {
public:
    template <typename T>
    static EventType of() {
        return EventType{std::type_index(typeid(T))};
    }

    [[nodiscard]] std::string name() const { return index_.name(); }

    friend bool operator==(const EventType& a, const EventType& b) {
        return a.index_ == b.index_;
    }
    [[nodiscard]] std::size_t hash() const { return index_.hash_code(); }

private:
    explicit EventType(std::type_index index) : index_(index) {}
    std::type_index index_;
    friend struct EventTypeHash;
};

struct EventTypeHash {
    std::size_t operator()(const EventType& type) const { return type.hash(); }
};

/// Opaque handle used to unsubscribe.
using SubscriptionId = std::uint64_t;

/// What to do when a subscriber is slower than the producer.
///
/// The document's backpressure table is right that policy has to differ per
/// event kind; putting it on the subscription is what makes that enforceable
/// rather than aspirational.
enum class DeliveryPolicy {
    Lossless,    ///< queue everything; commands, acks, faults
    LatestValue, ///< keep only the newest; attitude, position, battery
    Bounded,     ///< queue up to a limit, then drop oldest; raw log feeds
};

struct SubscriptionOptions {
    DeliveryPolicy policy{DeliveryPolicy::Lossless};
    std::size_t bound{1024};  ///< used by Bounded
};

/// Counters a health view can read without reaching into the bus internals.
struct BusStats {
    std::uint64_t published{0};
    std::uint64_t delivered{0};
    std::uint64_t coalesced{0};  ///< superseded by LatestValue
    std::uint64_t dropped{0};    ///< discarded by Bounded
    std::size_t queueDepth{0};
};

class EventBus {
public:
    EventBus() = default;
    EventBus(const EventBus&) = delete;
    EventBus& operator=(const EventBus&) = delete;

    /// Publish from any thread. Returns immediately; nothing is delivered until
    /// a consumer calls drain().
    template <typename T>
    void publish(T event) {
        publishErased(EventType::of<T>(),
                      std::make_shared<T>(std::move(event)));
    }

    /// Subscribe to one event type. The handler runs on the drain() thread.
    template <typename T>
    SubscriptionId subscribe(std::function<void(const T&)> handler,
                             SubscriptionOptions options = {}) {
        return subscribeErased(
            EventType::of<T>(),
            [handler = std::move(handler)](const std::shared_ptr<const void>& payload) {
                handler(*static_cast<const T*>(payload.get()));
            },
            options);
    }

    void unsubscribe(SubscriptionId id);

    /// Deliver queued events on the calling thread.
    ///
    /// @param maxEvents stop after this many, so a burst cannot monopolise the
    ///                  loop. 0 means drain everything currently queued.
    /// @return number of events delivered.
    std::size_t drain(std::size_t maxEvents = 0);

    [[nodiscard]] BusStats stats() const;
    [[nodiscard]] std::size_t subscriberCount() const;

private:
    using ErasedHandler = std::function<void(const std::shared_ptr<const void>&)>;

    struct Subscription {
        SubscriptionId id{0};
        EventType type;
        ErasedHandler handler;
        SubscriptionOptions options;
    };

    struct QueuedEvent {
        EventType type;
        std::shared_ptr<const void> payload;
        std::uint64_t sequence{0};
    };

    void publishErased(EventType type, std::shared_ptr<const void> payload);
    SubscriptionId subscribeErased(EventType type, ErasedHandler handler,
                                   SubscriptionOptions options);

    mutable std::mutex mutex_;
    std::deque<QueuedEvent> queue_;
    std::vector<Subscription> subscriptions_;
    std::atomic<SubscriptionId> nextSubscriptionId_{1};
    std::uint64_t nextSequence_{1};
    BusStats stats_;
    /// Highest LatestValue policy in force for a type, so a coalescible event
    /// can be superseded in the queue instead of piling up.
    std::unordered_map<EventType, bool, EventTypeHash> coalescible_;
};

}  // namespace kmgcs::event
