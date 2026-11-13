// ---------------------------------------------------------------------------
// DisplayStaging.hpp
// Purpose : The settings screen's Display tab with an Apply button (#308): Display changes wait for Apply, every
//           other tab applies at once. Pure logic, no SDL, no clock: it never touches the window, it returns the
//           (field, value) calls the shell makes through its own set path.
// Usage   : core::DisplayStaging st(settings["display"]);
//           st.stage("resolution", json::array({1280, 720}));   // the row shows st.value("resolution")
//           for (auto& [field, v] : st.apply()) settings["display"][field] = v;   // then apply the window, save
//           each frame: st.tick(real_dt)  (REAL seconds: not game time, not paused)   -> the revert's calls
//           st.keep() / st.revert() / st.back()
// Notes   : tools/golden_vectors.py DisplayStaging is the spec, data/golden/shell.json's display_staging cases
//           the test (tests/test_golden_vectors.cpp). Values compare as JSON (1 equals 1.0, [w, h] by value).
//           Rules:
//           - stage(field, v): a pending change; staging the applied value drops it. "busy" while the confirm is
//             open (the shell disables the controls then).
//           - apply(): the pending fields that differ, in kDisplayApplyOrder (mode before resolution); remembers
//             the values they replace; a change to mode or resolution opens the confirm (kDisplayConfirmS).
//           - tick(dt): the countdown; reaching 0 reverts. seconds() is ceil(left) for "Reverting in N s".
//           - keep(): closes the confirm. revert(): puts back exactly what the last apply replaced.
//           - back(): during the confirm it reverts (a screen the player cannot see must never stick); with
//             pending changes the first back warns, the second discards them; else it leaves.
//
// Pseudocode:
//   apply  : changed = pending fields != applied; replaced = their applied values; pending = {}; set(changed);
//            changed has mode or resolution -> left = kDisplayConfirmS
//   set(v) : for field in order: if in v -> applied[field] = v[field], call (field, v[field])
//   tick   : left -= dt; left <= 0 -> revert()
//   back   : confirm open -> ("revert", revert()) ; pending and not warned -> warned, ("warn") ; else discard, ("leave")
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <array>
#include <cmath>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace core {

// ---- Tunables ----
// The Display fields in the order Apply sets them: mode before resolution (a window size set before leaving
// fullscreen is lost on some platforms).
constexpr std::array<const char*, 5> kDisplayApplyOrder = {"mode", "resolution", "vsync", "frame_cap", "ui_scale"};
constexpr std::array<const char*, 2> kDisplayConfirmFields = {"mode", "resolution"};   // can black out the screen
constexpr double kDisplayConfirmS = 15.0;   // real seconds before an unanswered confirm reverts

class DisplayStaging {
public:
    using Calls = std::vector<std::pair<std::string, nlohmann::json>>;   // (field, value) in the apply order

    // applied: the Display section as it is now (settings["display"]).
    explicit DisplayStaging(nlohmann::json applied = nlohmann::json::object()) : applied_(std::move(applied)) {}

    // What a Display row shows: the pending value, else the applied one (null for a field the section lacks).
    nlohmann::json value(const std::string& field) const {
        if (pending_.contains(field)) {
            return pending_.at(field);
        }
        return applied_.contains(field) ? applied_.at(field) : nlohmann::json();
    }

    // "staged", or "busy" while the confirm is open.
    std::string stage(const std::string& field, const nlohmann::json& v) {
        if (left_) {
            return "busy";
        }
        if (applied_.contains(field) && applied_.at(field) == v) {
            pending_.erase(field);
        } else {
            pending_[field] = v;
        }
        warned_ = false;
        return "staged";
    }

    Calls apply() {
        nlohmann::json changed = nlohmann::json::object();
        for (const auto& [field, v] : pending_.items()) {
            if (!applied_.contains(field) || applied_.at(field) != v) {
                changed[field] = v;
            }
        }
        replaced_ = nlohmann::json::object();
        for (const auto& [field, v] : changed.items()) {
            replaced_[field] = applied_.contains(field) ? applied_.at(field) : nlohmann::json();
        }
        pending_ = nlohmann::json::object();
        warned_ = false;
        Calls calls = set(changed);
        for (const char* f : kDisplayConfirmFields) {
            if (changed.contains(f)) {
                left_ = kDisplayConfirmS;
            }
        }
        return calls;
    }

    // ceil(seconds left) while the confirm is open.
    std::optional<int> seconds() const {
        if (!left_) {
            return std::nullopt;
        }
        return static_cast<int>(std::ceil(*left_));
    }

    // dt in REAL seconds. Returns the revert's calls on the frame the countdown runs out.
    Calls tick(double dt) {
        if (!left_) {
            return {};
        }
        *left_ -= dt;
        return *left_ <= 0.0 ? revert() : Calls{};
    }

    void keep() {
        left_.reset();
        replaced_ = nlohmann::json::object();
    }

    Calls revert() {
        Calls calls = set(replaced_);
        left_.reset();
        replaced_ = nlohmann::json::object();
        return calls;
    }

    // ("revert", calls) during the confirm, ("warn", {}) the first time with pending changes, else ("leave", {}).
    std::pair<std::string, Calls> back() {
        if (left_) {
            return {"revert", revert()};
        }
        if (!pending_.empty() && !warned_) {
            warned_ = true;
            return {"warn", {}};
        }
        pending_ = nlohmann::json::object();
        warned_ = false;
        return {"leave", {}};
    }

    bool confirming() const { return left_.has_value(); }
    bool has_pending() const { return !pending_.empty(); }
    const nlohmann::json& pending() const { return pending_; }
    const nlohmann::json& applied() const { return applied_; }

private:
    nlohmann::json applied_;
    nlohmann::json pending_ = nlohmann::json::object();
    nlohmann::json replaced_ = nlohmann::json::object();   // field -> the value the last apply replaced
    std::optional<double> left_;                            // the confirm's countdown, nullopt when closed
    bool warned_ = false;

    Calls set(const nlohmann::json& values) {
        Calls calls;
        for (const char* f : kDisplayApplyOrder) {
            if (values.contains(f)) {
                applied_[f] = values.at(f);
                calls.emplace_back(f, values.at(f));
            }
        }
        return calls;
    }
};

}  // namespace core

// {{FOOTER}}
