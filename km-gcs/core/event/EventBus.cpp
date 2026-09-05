#include "EventBus.hpp"

#include <algorithm>

namespace kmgcs::event {

void EventBus::publishErased(EventType type, std::shared_ptr<const void> payload) {
    std::lock_guard<std::mutex> lock(mutex_);
    ++stats_.published;

    const auto coalescible = coalescible_.find(type);
    if (coalescible != coalescible_.end() && coalescible->second) {
        // LatestValue: replace any queued event of the same type rather than
        // letting a 200 Hz attitude stream build a queue the consumer will
        // never catch up with.
        const auto existing = std::find_if(
            queue_.begin(), queue_.end(),
            [&type](const QueuedEvent& queued) { return queued.type == type; });
        if (existing != queue_.end()) {
            existing->payload = std::move(payload);
            existing->sequence = nextSequence_++;
            ++stats_.coalesced;
            stats_.queueDepth = queue_.size();
            return;
        }
    }

    queue_.push_back(QueuedEvent{type, std::move(payload), nextSequence_++});
    stats_.queueDepth = queue_.size();
}

SubscriptionId EventBus::subscribeErased(EventType type, ErasedHandler handler,
                                         SubscriptionOptions options) {
    std::lock_guard<std::mutex> lock(mutex_);
    const SubscriptionId id = nextSubscriptionId_++;
    subscriptions_.push_back(Subscription{id, type, std::move(handler), options});

    // A type is coalescible only while every subscriber to it agrees. One
    // lossless subscriber (a recorder, say) is enough to keep every sample.
    bool allLatest = true;
    for (const auto& subscription : subscriptions_) {
        if (subscription.type == type &&
            subscription.options.policy != DeliveryPolicy::LatestValue) {
            allLatest = false;
            break;
        }
    }
    coalescible_[type] = allLatest;
    return id;
}

void EventBus::unsubscribe(SubscriptionId id) {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto removed = std::remove_if(
        subscriptions_.begin(), subscriptions_.end(),
        [id](const Subscription& subscription) { return subscription.id == id; });
    if (removed == subscriptions_.end()) {
        return;
    }
    subscriptions_.erase(removed, subscriptions_.end());

    // Recompute coalescibility: dropping the one lossless subscriber may make
    // a type coalescible again.
    coalescible_.clear();
    for (const auto& subscription : subscriptions_) {
        auto& allLatest = coalescible_[subscription.type];
        allLatest = true;
    }
    for (const auto& subscription : subscriptions_) {
        if (subscription.options.policy != DeliveryPolicy::LatestValue) {
            coalescible_[subscription.type] = false;
        }
    }
}

std::size_t EventBus::drain(std::size_t maxEvents) {
    std::size_t delivered = 0;
    while (maxEvents == 0 || delivered < maxEvents) {
        std::shared_ptr<const void> payload;
        std::vector<ErasedHandler> handlers;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (queue_.empty()) {
                break;
            }
            // EventType has no default constructor on purpose -- an event
            // without a type is not a thing -- so the entry is consumed here
            // rather than copied into a blank local.
            const QueuedEvent& front = queue_.front();
            payload = front.payload;
            for (const auto& subscription : subscriptions_) {
                if (subscription.type == front.type) {
                    handlers.push_back(subscription.handler);
                }
            }
            queue_.pop_front();
            stats_.queueDepth = queue_.size();
        }
        // Handlers run outside the lock: a handler is allowed to publish, and
        // holding the mutex across user code would deadlock the moment one does.
        for (const auto& handler : handlers) {
            handler(payload);
        }
        {
            std::lock_guard<std::mutex> lock(mutex_);
            ++stats_.delivered;
        }
        ++delivered;
    }
    return delivered;
}

BusStats EventBus::stats() const {
    std::lock_guard<std::mutex> lock(mutex_);
    BusStats copy = stats_;
    copy.queueDepth = queue_.size();
    return copy;
}

std::size_t EventBus::subscriberCount() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return subscriptions_.size();
}

}  // namespace kmgcs::event
