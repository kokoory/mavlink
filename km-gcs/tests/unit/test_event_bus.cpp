#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "Check.hpp"
#include "core/event/EventBus.hpp"

using namespace kmgcs::event;

namespace {
struct Tick { int value{0}; };
struct Tock { std::string text; };
/// Stands in for an event type a plugin defines after the core was compiled.
struct PluginDefinedEvent { double payload{0}; };
}  // namespace

KM_TEST(delivers_to_the_matching_subscriber_only) {
    EventBus bus;
    int ticks = 0, tocks = 0;
    bus.subscribe<Tick>([&](const Tick&) { ++ticks; });
    bus.subscribe<Tock>([&](const Tock&) { ++tocks; });

    bus.publish(Tick{1});
    bus.publish(Tick{2});
    bus.publish(Tock{"x"});
    KM_CHECK_EQ(bus.drain(), std::size_t{3});
    KM_CHECK_EQ(ticks, 2);
    KM_CHECK_EQ(tocks, 1);
}

KM_TEST(nothing_is_delivered_until_drain) {
    EventBus bus;
    int seen = 0;
    bus.subscribe<Tick>([&](const Tick&) { ++seen; });
    bus.publish(Tick{1});
    KM_CHECK_EQ(seen, 0);
    bus.drain();
    KM_CHECK_EQ(seen, 1);
}

KM_TEST(plugin_defined_events_need_no_core_change) {
    // The reason the bus is type-erased rather than a closed variant: a type
    // the core never heard of has to work.
    EventBus bus;
    double received = 0;
    bus.subscribe<PluginDefinedEvent>([&](const PluginDefinedEvent& e) {
        received = e.payload;
    });
    bus.publish(PluginDefinedEvent{42.5});
    bus.drain();
    KM_CHECK_NEAR(received, 42.5, 1e-9);
}

KM_TEST(latest_value_coalesces_a_fast_stream) {
    // A 200 Hz attitude stream must not build a queue a 20 Hz consumer can
    // never drain.
    EventBus bus;
    std::vector<int> seen;
    bus.subscribe<Tick>([&](const Tick& t) { seen.push_back(t.value); },
                        SubscriptionOptions{DeliveryPolicy::LatestValue, 0});
    for (int i = 1; i <= 100; ++i) {
        bus.publish(Tick{i});
    }
    bus.drain();
    KM_CHECK_EQ(seen.size(), std::size_t{1});
    KM_CHECK_EQ(seen.front(), 100);
    KM_CHECK(bus.stats().coalesced == 99);
}

KM_TEST(one_lossless_subscriber_defeats_coalescing) {
    // A recorder that needs every sample has to win over a UI that does not.
    EventBus bus;
    int latest = 0, lossless = 0;
    bus.subscribe<Tick>([&](const Tick&) { ++latest; },
                        SubscriptionOptions{DeliveryPolicy::LatestValue, 0});
    bus.subscribe<Tick>([&](const Tick&) { ++lossless; },
                        SubscriptionOptions{DeliveryPolicy::Lossless, 0});
    for (int i = 0; i < 10; ++i) {
        bus.publish(Tick{i});
    }
    bus.drain();
    KM_CHECK_EQ(lossless, 10);
    KM_CHECK_EQ(latest, 10);
    KM_CHECK_EQ(bus.stats().coalesced, std::uint64_t{0});
}

KM_TEST(drain_budget_bounds_a_burst) {
    EventBus bus;
    int seen = 0;
    bus.subscribe<Tick>([&](const Tick&) { ++seen; });
    for (int i = 0; i < 50; ++i) {
        bus.publish(Tick{i});
    }
    KM_CHECK_EQ(bus.drain(10), std::size_t{10});
    KM_CHECK_EQ(seen, 10);
    KM_CHECK_EQ(bus.stats().queueDepth, std::size_t{40});
}

KM_TEST(unsubscribe_stops_delivery) {
    EventBus bus;
    int seen = 0;
    const auto id = bus.subscribe<Tick>([&](const Tick&) { ++seen; });
    bus.publish(Tick{1});
    bus.drain();
    KM_CHECK_EQ(seen, 1);
    bus.unsubscribe(id);
    bus.publish(Tick{2});
    bus.drain();
    KM_CHECK_EQ(seen, 1);
}

KM_TEST(a_handler_may_publish_without_deadlocking) {
    // Handlers run outside the lock precisely so this works; a translator that
    // reacts to one event by publishing another is normal.
    EventBus bus;
    int tocks = 0;
    bus.subscribe<Tick>([&](const Tick& t) { bus.publish(Tock{std::to_string(t.value)}); });
    bus.subscribe<Tock>([&](const Tock&) { ++tocks; });
    bus.publish(Tick{7});
    bus.drain();
    KM_CHECK_EQ(tocks, 1);
}

KM_TEST(publishing_is_safe_from_several_threads) {
    EventBus bus;
    int seen = 0;
    bus.subscribe<Tick>([&](const Tick&) { ++seen; });
    std::vector<std::thread> producers;
    producers.reserve(4);
    for (int t = 0; t < 4; ++t) {
        producers.emplace_back([&bus] {
            for (int i = 0; i < 250; ++i) {
                bus.publish(Tick{i});
            }
        });
    }
    for (auto& producer : producers) {
        producer.join();
    }
    bus.drain();
    KM_CHECK_EQ(seen, 1000);
}

KM_MAIN("event bus")
