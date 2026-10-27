// ---------------------------------------------------------------------------
// test_bt.cpp
// Purpose : The behavior-tree library (ADR 0002): selector and sequence semantics, Running, the
//           active action name, and reactive priority (a higher branch takes over at once).
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <string>

#include "core/Bt.hpp"

namespace {

struct Blackboard {
    bool danger = false;
    bool target = false;
    int ran_attack = 0;
};

using namespace core::bt;

NodePtr<Blackboard> make_tree() {
    return selector<Blackboard>("root", children<Blackboard>(
        sequence<Blackboard>("flee", children<Blackboard>(
            condition<Blackboard>("danger", [](Blackboard& b) { return b.danger; }),
            action<Blackboard>("FLEE", [](Blackboard&) { return Status::Running; }))),
        sequence<Blackboard>("attack", children<Blackboard>(
            condition<Blackboard>("target", [](Blackboard& b) { return b.target; }),
            action<Blackboard>("ATTACK", [](Blackboard& b) { ++b.ran_attack; return Status::Success; }))),
        action<Blackboard>("IDLE", [](Blackboard&) { return Status::Running; })));
}

}  // namespace

TEST_CASE("the first branch whose conditions hold runs; its action is reported") {
    auto tree = make_tree();
    Blackboard b;
    std::string active;
    CHECK(tree->tick(b, active) == Status::Running);
    CHECK(active == "IDLE");

    b.target = true;
    active.clear();
    CHECK(tree->tick(b, active) == Status::Success);
    CHECK(active == "ATTACK");
    CHECK(b.ran_attack == 1);
}

TEST_CASE("a higher-priority branch takes over on the next tick (reactive)") {
    auto tree = make_tree();
    Blackboard b;
    b.target = true;
    std::string active;
    tree->tick(b, active);
    b.danger = true;
    tree->tick(b, active);
    CHECK(active == "FLEE");
    CHECK(b.ran_attack == 1);  // attack did not run while fleeing
}

TEST_CASE("a sequence stops at the first failing condition; a failing action is not reported") {
    Blackboard b;
    auto seq = sequence<Blackboard>("s", children<Blackboard>(
        condition<Blackboard>("no", [](Blackboard&) { return false; }),
        action<Blackboard>("NEVER", [](Blackboard& bb) { ++bb.ran_attack; return Status::Success; })));
    std::string active;
    CHECK(seq->tick(b, active) == Status::Failure);
    CHECK(b.ran_attack == 0);
    auto failing = action<Blackboard>("FAILS", [](Blackboard&) { return Status::Failure; });
    CHECK(failing->tick(b, active) == Status::Failure);
    CHECK(active.empty());
}
