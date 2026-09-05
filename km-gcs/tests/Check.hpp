// Minimal test harness.
//
// Enough to express the assertions the first slice needs, and no dependency to
// install before the architecture is proven. Swappable for a real framework the
// moment one earns its place.

#pragma once

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace kmgcs::testing {

inline int g_failures = 0;
inline std::string g_currentCase;

struct Case {
    const char* name;
    void (*run)();
};

inline std::vector<Case>& cases() {
    static std::vector<Case> registry;
    return registry;
}

struct Register {
    Register(const char* name, void (*run)()) { cases().push_back({name, run}); }
};

inline void fail(const char* file, int line, const std::string& detail) {
    ++g_failures;
    std::cerr << "  FAIL " << g_currentCase << "\n    " << file << ":" << line
              << "\n    " << detail << "\n";
}

inline int runAll(const char* suite) {
    std::cout << suite << "\n";
    for (const auto& test : cases()) {
        g_currentCase = test.name;
        const int before = g_failures;
        test.run();
        if (g_failures == before) {
            std::cout << "  ok   " << test.name << "\n";
        }
    }
    if (g_failures > 0) {
        std::cout << g_failures << " failure(s)\n";
        return 1;
    }
    std::cout << cases().size() << " passed\n";
    return 0;
}

}  // namespace kmgcs::testing

#define KM_TEST(name)                                                        \
    static void name();                                                      \
    static ::kmgcs::testing::Register register_##name(#name, &name);         \
    static void name()

#define KM_CHECK(condition)                                                  \
    do {                                                                     \
        if (!(condition)) {                                                  \
            ::kmgcs::testing::fail(__FILE__, __LINE__,                       \
                                   "expected: " #condition);                 \
        }                                                                    \
    } while (false)

#define KM_CHECK_EQ(actual, expected)                                        \
    do {                                                                     \
        const auto kmActual = (actual);                                      \
        const auto kmExpected = (expected);                                  \
        if (!(kmActual == kmExpected)) {                                     \
            std::ostringstream kmMessage;                                    \
            kmMessage << #actual " == " #expected "\n      actual:   "       \
                      << kmActual << "\n      expected: " << kmExpected;     \
            ::kmgcs::testing::fail(__FILE__, __LINE__, kmMessage.str());     \
        }                                                                    \
    } while (false)

#define KM_CHECK_NEAR(actual, expected, tolerance)                           \
    do {                                                                     \
        const double kmActual = static_cast<double>(actual);                 \
        const double kmExpected = static_cast<double>(expected);             \
        if (std::abs(kmActual - kmExpected) > (tolerance)) {                 \
            std::ostringstream kmMessage;                                    \
            kmMessage << #actual " ~= " #expected "\n      actual:   "       \
                      << kmActual << "\n      expected: " << kmExpected      \
                      << " +- " << (tolerance);                              \
            ::kmgcs::testing::fail(__FILE__, __LINE__, kmMessage.str());     \
        }                                                                    \
    } while (false)

#define KM_MAIN(suite)                                                       \
    int main() { return ::kmgcs::testing::runAll(suite); }
