// ---------------------------------------------------------------------------
// test_golden_audio.cpp
// Purpose : Checks the C++ audio logic (src/core: AudioDirector, MusicDirector, AudioAccess) against the kit's
//           golden vectors data/golden/audio.json, music.json and access.json, case by case.
// Usage   : python tools/dev.py test     (ctest lists "golden audio: audio.json", "... music.json", "... access.json")
// Notes   : The vectors are written by tools/audio/wavesmith (audio_events.py, music.py, access.py), the references
//           every engine port is held to. Expected values are read from the files at test time, never copied here.
//           A case type this file does not know fails, so a new vector type cannot be skipped silently. Music plans
//           are integers (tolerance 0); "stinger" and "stinger_at" are null when there is none.
//
// Pseudocode:
//   load the file -> for each case: find the runner for its type (or fail) -> run its steps -> compare
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <cmath>
#include <fstream>
#include <string>

#include <nlohmann/json.hpp>

#include "core/AudioAccess.hpp"
#include "core/AudioDirector.hpp"
#include "core/MusicDirector.hpp"

#ifndef GOLDEN_DIR
#error "GOLDEN_DIR must name the folder with the golden vector files (CMakeLists.txt sets it)"
#endif

namespace {

using nlohmann::json;

json load(const char* name) {
    std::ifstream in(std::string(GOLDEN_DIR) + "/" + name, std::ios::binary);
    REQUIRE_MESSAGE(in.good(), "cannot open " << name);
    return json::parse(in);
}

bool near(double a, double b, double tol) { return std::fabs(a - b) <= tol; }

// One played or rejected decision against its expected object
int check_play(const core::PlayDecision& d, const json& want, double tol, const std::string& at) {
    const std::string result = d.result == core::PlayResult::Played    ? "played"
                               : d.result == core::PlayResult::Cooldown ? "cooldown"
                                                                        : "capped";
    CHECK_MESSAGE(result == want.at("result").get<std::string>(), at << ": result " << result);
    if (result != "played") return 1;
    CHECK_MESSAGE(d.variant == want.at("variant").get<int>(), at << ": variant " << d.variant);
    CHECK_MESSAGE(d.voice == want.at("voice").get<int>(), at << ": voice " << d.voice);
    CHECK_MESSAGE(near(d.pitch_semitones, want.at("pitch_semitones").get<double>(), tol), at << ": pitch_semitones");
    CHECK_MESSAGE(near(d.pitch_ratio, want.at("pitch_ratio").get<double>(), tol), at << ": pitch_ratio");
    CHECK_MESSAGE(near(d.gain_db, want.at("gain_db").get<double>(), tol), at << ": gain_db");
    CHECK_MESSAGE(near(d.ends_ms, want.at("ends_ms").get<double>(), tol), at << ": ends_ms");
    if (want.at("stolen").is_null()) {
        CHECK_MESSAGE(!d.stolen.has_value(), at << ": stole a voice it should not have");
    } else {
        CHECK_MESSAGE((d.stolen && *d.stolen == want.at("stolen").get<int>()), at << ": stolen");
    }
    return 8;
}

int run_audio_case(const json& c, double tol) {
    core::AudioDirector dir(c.at("params"));
    int checked = 0, i = 0;
    for (const auto& step : c.at("steps")) {
        const std::string at = c.at("name").get<std::string>() + " step " + std::to_string(i++);
        const std::string call = step.at("call").get<std::string>();
        if (call == "play") {
            checked += check_play(dir.play(step.at("event").get<std::string>(), step.at("t_ms").get<double>()),
                                  step.at("expect"), tol, at);
        } else if (call == "duck") {
            const auto got = dir.duck(step.at("t_ms").get<double>());
            CHECK_MESSAGE(got.size() == step.at("expect").size(), at << ": duck bus count");
            for (const auto& [bus, db] : step.at("expect").items()) {
                const auto g = got.find(bus);
                CHECK_MESSAGE((g != got.end() && near(g->second, db.get<double>(), tol)), at << ": duck " << bus);
                ++checked;
            }
        } else {
            FAIL_CHECK(at << ": unknown step call " << call);
        }
    }
    return checked;
}

int run_music_case(const json& c) {
    int checked = 0, i = 0;
    if (c.at("type") == "music_grid") {
        for (const auto& s : c.at("steps")) {
            CHECK_MESSAGE(core::beat_sample(s.at("k").get<double>(), s.at("bpm").get<double>(), s.at("rate").get<double>()) ==
                              s.at("sample").get<std::int64_t>(),
                          "beat samples step " << i);
            ++i;
            ++checked;
        }
        return checked;
    }
    const core::MusicDirector music(c.at("params"));
    for (const auto& s : c.at("steps")) {
        const std::string at = "plan step " + std::to_string(i++);
        const core::MusicPlan p = music.plan(s.at("from").get<std::string>(), s.at("since").get<std::int64_t>(),
                                             s.at("entry").get<std::int64_t>(), s.at("to").get<std::string>(),
                                             s.at("now").get<std::int64_t>());
        const json& w = s.at("expect");
        CHECK_MESSAGE(w.size() == 7, at << ": the expected plan has " << w.size() << " fields, this test knows 7");
        CHECK_MESSAGE(p.switch_at == w.at("switch_at").get<std::int64_t>(), at << ": switch_at " << p.switch_at);
        CHECK_MESSAGE(p.from_stop_at == w.at("from_stop_at").get<std::int64_t>(), at << ": from_stop_at");
        CHECK_MESSAGE(p.fade == w.at("fade").get<std::int64_t>(), at << ": fade");
        CHECK_MESSAGE(p.to_offset == w.at("to_offset").get<std::int64_t>(), at << ": to_offset " << p.to_offset);
        CHECK_MESSAGE(p.to_start_at == w.at("to_start_at").get<std::int64_t>(), at << ": to_start_at");
        if (w.at("stinger").is_null()) {
            CHECK_MESSAGE((!p.stinger && !p.stinger_at), at << ": no stinger expected");
        } else {
            CHECK_MESSAGE((p.stinger && *p.stinger == w.at("stinger").get<std::string>()), at << ": stinger");
            CHECK_MESSAGE((p.stinger_at && *p.stinger_at == w.at("stinger_at").get<std::int64_t>()), at << ": stinger_at");
        }
        checked += 7;
    }
    return checked;
}

int run_access_case(const json& c, double tol) {
    int checked = 0, i = 0;
    for (const auto& s : c.at("steps")) {
        const std::string at = c.at("type").get<std::string>() + " step " + std::to_string(i++);
        if (c.at("type") == "access_gains") {
            const auto got = core::user_bus_gains(s.at("buses"), s.at("sliders"));
            CHECK_MESSAGE(got.size() == s.at("expect").size(), at << ": bus count");
            for (const auto& [bus, want] : s.at("expect").items()) {
                const auto g = got.find(bus);
                CHECK_MESSAGE((g != got.end() && near(g->second, want.get<double>(), tol)), at << ": " << bus);
                ++checked;
            }
        } else {
            const double dx = s.at("dx"), dy = s.at("dy"), hw = s.at("half_w"), hh = s.at("half_h");
            CHECK_MESSAGE(core::caption_direction(dx, dy, hw, hh) == s.at("dir").get<int>(), at << ": dir");
            CHECK_MESSAGE(core::caption_arrow(dx, dy, hw, hh) == s.at("arrow").get<std::string>(), at << ": arrow");
            checked += 2;
        }
    }
    return checked;
}

}  // namespace

TEST_CASE("golden audio: audio.json") {
    const json file = load("audio.json");
    const double tol = file.at("tolerance").get<double>();
    int cases = 0, values = 0;
    for (const auto& c : file.at("cases")) {
        const std::string type = c.value("type", "?");
        if (type == "audio_director") {
            values += run_audio_case(c, tol);
        } else {
            FAIL_CHECK("unknown case type '" << type << "' in audio.json: add a runner for it");
        }
        ++cases;
    }
    MESSAGE("audio.json: " << cases << " case(s), " << values << " value(s) checked");
    CHECK(cases > 0);
}

TEST_CASE("golden audio: music.json") {
    const json file = load("music.json");
    int cases = 0, values = 0;
    for (const auto& c : file.at("cases")) {
        const std::string type = c.value("type", "?");
        if (type == "music_grid" || type == "music_plan") {
            values += run_music_case(c);
        } else {
            FAIL_CHECK("unknown case type '" << type << "' in music.json: add a runner for it");
        }
        ++cases;
    }
    MESSAGE("music.json: " << cases << " case(s), " << values << " value(s) checked");
    CHECK(cases > 0);
}

TEST_CASE("golden audio: access.json") {
    const json file = load("access.json");
    const double tol = file.at("tolerance").get<double>();
    REQUIRE(file.at("arrows").size() == core::kCaptionArrows.size());
    for (std::size_t k = 0; k < core::kCaptionArrows.size(); ++k) {
        CHECK_MESSAGE(file.at("arrows")[k].get<std::string>() == core::kCaptionArrows[k], "arrow " << k);
    }
    int cases = 0, values = 0;
    for (const auto& c : file.at("cases")) {
        const std::string type = c.value("type", "?");
        if (type == "access_gains" || type == "access_arrow") {
            values += run_access_case(c, tol);
        } else {
            FAIL_CHECK("unknown case type '" << type << "' in access.json: add a runner for it");
        }
        ++cases;
    }
    MESSAGE("access.json: " << cases << " case(s), " << values << " value(s) checked");
    CHECK(cases > 0);
}
