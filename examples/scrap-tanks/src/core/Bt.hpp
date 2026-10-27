// ---------------------------------------------------------------------------
// Bt.hpp
// Purpose : A small behavior tree (ADR 0002): Selector, Sequence, Condition, Action, with
//           Success / Failure / Running. Engine-free and generic over a context type.
// Usage   : using namespace core::bt;
//           auto tree = selector<Ctx>("root", children<Ctx>(
//               sequence<Ctx>("retreat", children<Ctx>(condition<Ctx>("hurt", is_hurt), action<Ctx>("RETREAT", retreat))),
//               action<Ctx>("FLANK", flank)));
//           std::string active; tree->tick(ctx, active);   // active = name of the action that ran
// Notes   : Reactive: every tick starts at the root, so a higher-priority branch takes over the
//           moment its conditions hold. No node memory; actions keep their state in the context.
//           `active` is what the game shows over each raider (pillar 2: read the raiders).
//
// Pseudocode:
//   selector: for child in order: s = child.tick; if s != Failure: return s ; return Failure
//   sequence: for child in order: s = child.tick; if s != Success: return s ; return Success
//   condition: fn(ctx) ? Success : Failure
//   action: s = fn(ctx); if s != Failure: active = name; return s
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <functional>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace core::bt {

enum class Status { Success, Failure, Running };

template <class Ctx>
class Node {
public:
    explicit Node(std::string name) : name_(std::move(name)) {}
    virtual ~Node() = default;
    virtual Status tick(Ctx& ctx, std::string& active) = 0;
    const std::string& name() const { return name_; }

private:
    std::string name_;
};

template <class Ctx>
using NodePtr = std::unique_ptr<Node<Ctx>>;

template <class Ctx>
class Composite : public Node<Ctx> {
public:
    Composite(std::string name, std::vector<NodePtr<Ctx>> children, bool is_selector)
        : Node<Ctx>(std::move(name)), children_(std::move(children)), selector_(is_selector) {}

    Status tick(Ctx& ctx, std::string& active) override {
        // A selector stops at the first child that does not fail, a sequence at the first that does not succeed.
        const Status keep_going = selector_ ? Status::Failure : Status::Success;
        for (auto& child : children_) {
            const Status s = child->tick(ctx, active);
            if (s != keep_going) return s;
        }
        return keep_going;
    }

private:
    std::vector<NodePtr<Ctx>> children_;
    bool selector_;
};

template <class Ctx>
class Condition : public Node<Ctx> {
public:
    Condition(std::string name, std::function<bool(Ctx&)> fn) : Node<Ctx>(std::move(name)), fn_(std::move(fn)) {}
    Status tick(Ctx& ctx, std::string&) override { return fn_(ctx) ? Status::Success : Status::Failure; }

private:
    std::function<bool(Ctx&)> fn_;
};

template <class Ctx>
class Action : public Node<Ctx> {
public:
    Action(std::string name, std::function<Status(Ctx&)> fn) : Node<Ctx>(std::move(name)), fn_(std::move(fn)) {}
    Status tick(Ctx& ctx, std::string& active) override {
        const Status s = fn_(ctx);
        if (s != Status::Failure) active = this->name();
        return s;
    }

private:
    std::function<Status(Ctx&)> fn_;
};

// ---- builders: read like the tree they make ----
// children<Ctx>(a, b, c): unique_ptrs cannot go through an initializer list, so this collects them.
template <class Ctx, class... Nodes>
std::vector<NodePtr<Ctx>> children(Nodes&&... nodes) {
    std::vector<NodePtr<Ctx>> v;
    (v.push_back(std::forward<Nodes>(nodes)), ...);
    return v;
}

template <class Ctx>
NodePtr<Ctx> selector(std::string name, std::vector<NodePtr<Ctx>> kids) {
    return std::make_unique<Composite<Ctx>>(std::move(name), std::move(kids), true);
}

template <class Ctx>
NodePtr<Ctx> sequence(std::string name, std::vector<NodePtr<Ctx>> kids) {
    return std::make_unique<Composite<Ctx>>(std::move(name), std::move(kids), false);
}

template <class Ctx>
NodePtr<Ctx> condition(std::string name, std::function<bool(Ctx&)> fn) {
    return std::make_unique<Condition<Ctx>>(std::move(name), std::move(fn));
}

template <class Ctx>
NodePtr<Ctx> action(std::string name, std::function<Status(Ctx&)> fn) {
    return std::make_unique<Action<Ctx>>(std::move(name), std::move(fn));
}

}  // namespace core::bt
