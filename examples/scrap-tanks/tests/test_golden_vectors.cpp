// ---------------------------------------------------------------------------
// test_golden_vectors.cpp
// Purpose : Checks the C++ juice and shell logic (src/core) against the kit's golden vectors,
//           data/golden/juice.json and data/golden/shell.json, case by case; and data/golden/credits.json through
//           the credits screen's text (core::strip_html_comments, #279).
// Usage   : python tools/dev.py test     (ctest lists "golden vectors: juice.json" and "... shell.json";
//           build/debug/bin/Debug/unit_tests.exe -tc="golden*" prints how many cases each file had)
// Notes   : The vectors are written by tools/golden_vectors.py, the reference implementation every engine
//           port is held to. Expected values are read from the files at test time, never copied here.
//           CMakeLists.txt passes the folder as GOLDEN_DIR. A case type this file does not know fails the
//           test, so a new vector type cannot be skipped silently. Numbers compare within the file's
//           tolerance (an int 0 equals a float 0.0), arrays in order, objects as key sets.
//
// Pseudocode:
//   load the file -> check its format version -> for each case: find the checker for its type (or fail)
//   -> run the case's steps or points through src/core -> compare every result with the expected value
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <cmath>
#include <cstdint>
#include <exception>
#include <map>
#include <optional>
#include <string>
#include <utility>

#include <nlohmann/json.hpp>

#include "core/AtomicFile.hpp"
#include "core/Bindings.hpp"
#include "core/CoyoteTimer.hpp"
#include "core/Ease.hpp"
#include "core/FlashLimiter.hpp"
#include "core/FollowCamera.hpp"
#include "core/Hitstop.hpp"
#include "core/I18n.hpp"
#include "core/InputBuffer.hpp"
#include "core/SaveStore.hpp"
#include "core/Settings.hpp"
#include "core/Shake.hpp"
#include "core/ShellLogic.hpp"
#include "core/Spring.hpp"

#ifndef GOLDEN_DIR
#error "GOLDEN_DIR must name the folder with juice.json and shell.json (CMakeLists.txt sets it)"
#endif

namespace {

using nlohmann::json;

// ---- Constants ----
constexpr int kVectorFormat = 1;  // the golden file "version" this test understands
// The plural case lists [locale, n, category, text] but not its key; the reference builds it with this one
constexpr const char* kPluralKey = "apples";

double g_tol = 1e-6;  // replaced by each file's "tolerance" before its cases run

json load_vectors(const char* name) {
    const auto path = core::path_from_utf8(GOLDEN_DIR) / name;
    std::string error;
    const auto text = core::read_file(path, &error);
    REQUIRE_MESSAGE(text.has_value(), "cannot read " << core::path_to_utf8(path) << " " << error);
    json j = json::parse(*text, nullptr, false);
    REQUIRE_MESSAGE(!j.is_discarded(), core::path_to_utf8(path) << " is not valid JSON");
    return j;
}

// "" when got matches want, else where and how they differ.
std::string diff(const json& got, const json& want, const std::string& at = "$") {
    if (want.is_number() && got.is_number()) {
        const double g = got.get<double>();
        const double w = want.get<double>();
        return std::fabs(g - w) <= g_tol ? "" : at + ": got " + got.dump() + ", want " + want.dump();
    }
    if (got.type() != want.type()) {
        return at + ": got " + got.dump() + ", want " + want.dump();
    }
    if (want.is_array()) {
        if (got.size() != want.size()) {
            return at + ": " + std::to_string(got.size()) + " items, want " + std::to_string(want.size());
        }
        for (std::size_t i = 0; i < want.size(); ++i) {
            const std::string d = diff(got[i], want[i], at + "[" + std::to_string(i) + "]");
            if (!d.empty()) {
                return d;
            }
        }
        return "";
    }
    if (want.is_object()) {
        for (const auto& [key, value] : got.items()) {
            if (!want.contains(key)) {
                return at + "." + key + ": not expected";
            }
        }
        for (const auto& [key, value] : want.items()) {
            if (!got.contains(key)) {
                return at + "." + key + ": missing";
            }
            const std::string d = diff(got.at(key), value, at + "." + key);
            if (!d.empty()) {
                return d;
            }
        }
        return "";
    }
    return got == want ? "" : at + ": got " + got.dump() + ", want " + want.dump();
}

void expect_same(const json& got, const json& want, const std::string& what) {
    const std::string d = diff(got, want);
    CHECK_MESSAGE(d.empty(), what << " " << d);
}

std::string text(const json& j) {
    return j.get<std::string>();  // throws on a non-string: the case data is wrong
}

std::optional<std::string> optional_text(const json& j) {
    return j.is_string() ? std::optional<std::string>(j.get<std::string>()) : std::nullopt;
}

void unknown_call(const json& step) {
    FAIL_CHECK("unknown step call " << step.at("call").dump());
}

// ---- juice.json -------------------------------------------------------------------------

void check_noise(const json& c) {
    for (const json& p : c.at("points")) {
        expect_same(core::noise(p[0].get<std::int64_t>(), p[1].get<double>(), p[2].get<std::int64_t>()), p[3],
                    "noise" + p.dump());
    }
}

void check_shake(const json& c) {
    const json& k = c.at("params");
    core::Shake s(k.at("max_offset"), k.at("max_angle"), k.at("decay"), k.at("frequency"),
                  k.at("seed").get<std::int64_t>());
    for (const json& step : c.at("steps")) {
        const std::string call = step.at("call");
        if (call == "add_trauma") {
            s.add_trauma(step.at("a"));
        } else if (call == "update") {
            const core::ShakeOffset o = s.update(step.at("dt"), step.at("intensity"));
            expect_same({{"x", o.x}, {"y", o.y}, {"angle", o.angle}, {"trauma", s.trauma()}}, step.at("expect"),
                        "update" + step.dump());
        } else {
            unknown_call(step);
        }
    }
}

void check_hitstop(const json& c) {
    core::Hitstop h(c.at("params").at("max_s"));
    for (const json& step : c.at("steps")) {
        const std::string call = step.at("call");
        if (call == "hit") {
            h.hit(step.at("duration"));
        } else if (call == "scaled_dt") {
            const double dt = h.scaled_dt(step.at("dt"));
            expect_same({{"dt", dt}, {"remaining", h.remaining()}}, step.at("expect"), "scaled_dt" + step.dump());
        } else {
            unknown_call(step);
        }
    }
}

void check_ease(const json& c) {
    for (const json& p : c.at("points")) {
        const auto kind = core::ease_from_name(p[0].get<std::string>());
        CHECK_MESSAGE(kind.has_value(), "no easing named " << p[0]);
        if (kind) {
            expect_same(core::ease(*kind, p[1].get<double>()), p[2], "ease" + p.dump());
        }
    }
}

void check_follow(const json& c) {
    const json& k = c.at("params");
    core::FollowCamera cam(k.at("deadzone_w"), k.at("deadzone_h"), k.at("lookahead"), k.at("smoothing"), k.at("x"),
                           k.at("y"));
    for (const json& step : c.at("steps")) {
        if (step.at("call") != "update") {
            unknown_call(step);
            continue;
        }
        const core::CameraPos p =
            cam.update(step.at("dt"), step.at("tx"), step.at("ty"), step.at("vx"), step.at("vy"));
        expect_same({{"x", p.x}, {"y", p.y}}, step.at("expect"), "update" + step.dump());
    }
}

void check_input_buffer(const json& c) {
    core::InputBuffer b(c.at("params").at("window_s"));
    for (const json& step : c.at("steps")) {
        const std::string call = step.at("call");
        if (call == "press") {
            b.press(text(step.at("action")));
        } else if (call == "update") {
            b.update(step.at("dt"));
        } else if (call == "consume") {
            expect_same({{"result", b.consume(text(step.at("action")))}}, step.at("expect"), "consume" + step.dump());
        } else {
            unknown_call(step);
        }
    }
}

void check_coyote(const json& c) {
    core::CoyoteTimer t(c.at("params").at("window_s"));
    for (const json& step : c.at("steps")) {
        const std::string call = step.at("call");
        if (call == "update") {
            t.update(step.at("dt"), step.at("on_floor").get<bool>());
        } else if (call == "consume") {
            t.consume();
        } else if (call == "can_jump") {
            expect_same({{"result", t.can_jump()}}, step.at("expect"), "can_jump" + step.dump());
        } else {
            unknown_call(step);
        }
    }
}

void check_spring(const json& c) {
    const json& k = c.at("params");
    core::Spring s(k.at("frequency"), k.at("damping"));
    s.x = k.at("x");
    s.v = k.at("v");
    s.target = k.at("target");
    for (const json& step : c.at("steps")) {
        if (step.at("call") != "update") {
            unknown_call(step);
            continue;
        }
        const double x = s.update(step.at("dt"));
        expect_same({{"x", x}, {"v", s.v}}, step.at("expect"), "update" + step.dump());
    }
}

void check_squash(const json& c) {
    for (const json& p : c.at("points")) {
        const core::SquashScale s = core::squash(p[0].get<double>());
        expect_same(json::array({p[0], s.sx, s.sy}), p, "squash" + p.dump());
    }
}

void check_flash_limiter(const json& c) {
    const json& k = c.at("params");
    core::FlashLimiter f(k.at("max_flashes").get<int>(), k.at("window_s"));
    for (const json& step : c.at("steps")) {
        if (step.at("call") != "request") {
            unknown_call(step);
            continue;
        }
        expect_same({{"result", f.request(step.at("now"))}}, step.at("expect"), "request" + step.dump());
    }
}

// ---- shell.json -------------------------------------------------------------------------

void check_defaults(const json& c) {
    expect_same(core::default_settings(), c.at("expect"), "default_settings()");
}

void check_settings_load(const json& c) {
    const core::SettingsLoad r = core::settings_load(optional_text(c.at("input")));
    expect_same(r.settings, c.at("expect"), "settings");
    std::string listed;
    for (const auto& p : r.problems) {
        listed += " " + p;
    }
    CHECK_MESSAGE(r.problems.size() == c.at("problems").get<std::size_t>(), "problems:" << listed);
    expect_same(core::effective_shake(r.settings), c.at("effective_shake"), "effective_shake");
    expect_same(core::telemetry_allowed(r.settings), c.at("telemetry_allowed"), "telemetry_allowed");
}

void check_rebind(const json& c) {
    const auto r = core::rebind(core::bindings_from_json(c.at("bindings")), text(c.at("action")),
                                c.at("slot").get<std::size_t>(), text(c.at("binding")));
    REQUIRE_MESSAGE(r.has_value(), "rebind refused the slot");
    json conflicts = json::array();
    for (const auto& [action, slot] : r->conflicts) {
        conflicts.push_back(json::array({action, slot}));
    }
    expect_same({{"bindings", core::bindings_to_json(r->bindings)}, {"conflicts", conflicts}}, c.at("expect"),
                "rebind");
}

void check_glyph_set(const json& c) {
    for (const json& p : c.at("points")) {
        expect_same(core::glyph_set(text(p[0]), text(p[1])), p[2], "glyph_set" + p.dump());
    }
}

void check_glyph_name(const json& c) {
    for (const json& p : c.at("points")) {
        expect_same(core::glyph_name(text(p[0]), text(p[1])), p[2], "glyph_name" + p.dump());
    }
}

void check_prompt_binding(const json& c) {
    const core::Bindings b = core::bindings_from_json(c.at("bindings"));
    for (const json& p : c.at("points")) {
        expect_same(core::prompt_binding(b, text(p[0]), text(p[1])), p[2], "prompt_binding" + p.dump());
    }
}

void check_save_load(const json& c) {
    CHECK(c.at("current_version").get<int>() == core::kSaveVersion);
    const core::SaveLoad r = core::save_load(optional_text(c.at("primary")), optional_text(c.at("backup")));
    expect_same({{"envelope", r.envelope}, {"source", r.source}, {"problems", r.problems.size()}}, c.at("expect"),
                "save_load");
}

core::TrArgs args_from(const json& j) {
    core::TrArgs args;
    for (const auto& [name, value] : j.items()) {
        args[name] = value.is_string() ? value.get<std::string>() : value.dump();
    }
    return args;
}

void check_tr(const json& c) {
    const core::StringTables tables = core::string_tables_from_json(c.at("tables"));
    for (const json& p : c.at("points")) {
        expect_same(core::tr(tables, text(p[0]), text(p[1]), args_from(p[2])), p[3], "tr" + p.dump());
    }
}

void check_plural(const json& c) {
    const core::StringTables tables = core::string_tables_from_json(c.at("tables"));
    for (const json& p : c.at("points")) {
        const auto n = p[1].get<long long>();
        expect_same(core::plural(text(p[0]), n), p[2], "plural" + p.dump());
        expect_same(core::tr_plural(tables, text(p[0]), kPluralKey, n), p[3], "tr_plural" + p.dump());
    }
}

void check_narration(const json& c) {
    for (const json& p : c.at("points")) {
        expect_same(core::narration_line(text(p[0]), text(p[1]), text(p[2])), p[3], "narration" + p.dump());
    }
}

void check_pseudo(const json& c) {
    for (const json& p : c.at("points")) {
        expect_same(core::pseudo(text(p[0])), p[1], "pseudo" + p.dump());
    }
}

void check_strip_comments(const json& c) {
    for (const json& p : c.at("points")) {
        expect_same(core::strip_html_comments(text(p[1])), p[2], "strip_comments " + text(p[0]));
    }
}

using Checker = void (*)(const json& c);

// Runs every case of one vector file through its checker; unknown types fail. Returns the cases checked.
int run_file(const char* file, const std::map<std::string, Checker>& checkers) {
    const std::string name = file;  // doctest prints a raw const char* as a pointer, a std::string as text
    const json vectors = load_vectors(file);
    CHECK_MESSAGE(vectors.at("version") == kVectorFormat, name << " has a vector format this test does not know");
    g_tol = vectors.at("tolerance").get<double>();
    int checked = 0;
    std::map<std::string, int> per_type;  // cases run per type: every type with a checker must have one
    for (const json& c : vectors.at("cases")) {
        const std::string type = c.value("type", "?");
        const std::string label = type + " | " + c.value("name", "?");
        INFO("case: " << label);
        const auto it = checkers.find(type);
        if (it == checkers.end()) {
            FAIL_CHECK("unknown case type '" << type << "': add a checker for it");
            continue;
        }
        try {
            it->second(c);
            ++checked;
            ++per_type[type];
        } catch (const std::exception& e) {  // a missing field or a wrong type in the case data
            FAIL_CHECK("case threw: " << e.what());
        }
    }
    CHECK(checked > 0);
    for (const auto& [type, checker] : checkers) {
        CHECK_MESSAGE(per_type[type] > 0, name << " has no '" << type << "' case (a truncated file must not pass)");
    }
    MESSAGE(name << ": " << checked << " cases checked");
    return checked;
}

}  // namespace

TEST_CASE("golden vectors: juice.json") {
    run_file("juice.json", {
        {"noise", check_noise}, {"shake", check_shake}, {"hitstop", check_hitstop}, {"ease", check_ease},
        {"follow", check_follow}, {"input_buffer", check_input_buffer}, {"coyote", check_coyote},
        {"spring", check_spring}, {"squash", check_squash}, {"flash_limiter", check_flash_limiter},
    });
}

TEST_CASE("golden vectors: shell.json") {
    const json vectors = load_vectors("shell.json");
    CHECK(vectors.at("save_version").get<int>() == core::kSaveVersion);
    run_file("shell.json", {
        {"defaults", check_defaults}, {"settings_load", check_settings_load}, {"rebind", check_rebind},
        {"glyph_set", check_glyph_set}, {"glyph_name", check_glyph_name}, {"prompt_binding", check_prompt_binding},
        {"save_load", check_save_load}, {"tr", check_tr}, {"plural", check_plural}, {"pseudo", check_pseudo},
        {"narration", check_narration},
    });
}

TEST_CASE("golden vectors: credits.json") {
    run_file("credits.json", {{"strip_comments", check_strip_comments}});
}

// ---- What the vectors cannot express: the error paths ----

TEST_CASE("an unknown easing name is an error, not a silent linear") {
    CHECK_FALSE(core::ease_from_name("out_wobble").has_value());
    CHECK(core::ease_from_name("out_bounce") == core::Ease::OutBounce);
}

TEST_CASE("rebind refuses a slot past the end and appends at the end") {
    const core::Bindings b = core::default_bindings();
    CHECK_FALSE(core::rebind(b, "jump", 3, "key:k").has_value());  // jump has slots 0 and 1
    const auto r = core::rebind(b, "jump", 2, "key:k");
    REQUIRE(r.has_value());
    CHECK(r->bindings.at("jump").size() == 3);
}
