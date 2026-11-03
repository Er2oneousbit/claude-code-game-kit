// ---------------------------------------------------------------------------
// MusicDirector.hpp
// Purpose : The adaptive-music rules of data/music.json: the sample grid, loop points, where playback is, the next
//           beat / bar / phrase / loop end, which transition rule applies, and the plan for a change of track
//           (when, fade, stinger, entry point). Pure logic, no SDL; a mixer plays what it plans.
// Usage   : core::MusicDirector music(music_json);
//           const core::MusicPlan p = music.plan("explore", since, entry, "combat", now);   // all in samples
//           p.switch_at, p.from_stop_at, p.to_start_at, p.to_offset, p.stinger, p.stinger_at
// Notes   : A port of tools/audio/wavesmith/music.py (the reference); data/golden/music.json must come out exactly
//           (integers, tolerance 0). Beat k starts at floor(k * 60 * rate / bpm + 0.5), computed in the same
//           order as the reference so every port lands on the same sample; std::round is not the rule.
//
// Pseudocode:
//   position: p = now - since + entry; past the loop end -> wrap into [loop start, loop end)
//   plan: rule (exact pair, from *, to *, default) -> next boundary of its quantize at or after p
//         -> switch_at = now + (boundary - p); stinger -> the target enters after the stinger's bars
//         -> sync (same bpm and meter) -> enter at the same place in the bar
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace core {

struct MusicTrack {
    double bpm = 120;
    int beats_per_bar = 4;
    int bars = 1;
    int loop_start_bar = 0;
};

struct MusicRule {
    std::string from, to;
    std::string quantize = "bar";  // immediate | beat | bar | phrase | loop_end
    double fade_ms = 0;
    bool sync = false;
    std::optional<std::string> stinger;
    int phrase_bars = 4;
};

struct MusicPlan {
    std::int64_t switch_at = 0, from_stop_at = 0, fade = 0, to_offset = 0, to_start_at = 0;
    std::optional<std::string> stinger;
    std::optional<std::int64_t> stinger_at;
};

inline std::int64_t beat_sample(double k, double bpm, double rate) {
    return static_cast<std::int64_t>(std::floor(k * 60 * rate / bpm + 0.5));
}

class MusicDirector {
public:
    explicit MusicDirector(const nlohmann::json& m) : rate_(m.at("sample_rate").get<double>()) {
        for (const auto& [name, t] : m.at("tracks").items()) {
            MusicTrack tr;
            tr.bpm = t.at("bpm").get<double>();
            tr.beats_per_bar = t.value("beats_per_bar", 4);
            tr.bars = t.at("bars").get<int>();
            tr.loop_start_bar = t.value("loop_start_bar", 0);
            tracks_.emplace(name, tr);
        }
        if (m.contains("stingers")) {
            for (const auto& [name, s] : m.at("stingers").items()) stinger_bars_[name] = s.at("bars").get<double>();
        }
        if (m.contains("default_transition")) default_ = read_rule(m.at("default_transition"), MusicRule{});
        if (m.contains("transitions")) {
            for (const auto& r : m.at("transitions")) {
                MusicRule rule = read_rule(r, default_);
                rule.from = r.value("from", std::string());
                rule.to = r.value("to", std::string());
                rules_.push_back(rule);
            }
        }
    }

    std::int64_t bar_sample(int b, const MusicTrack& t) const { return beat_sample(double(b) * t.beats_per_bar, t.bpm, rate_); }

    // The bar that contains `sample`, exact on the rounded grid
    int bar_index_at(std::int64_t sample, const MusicTrack& t) const {
        int b = static_cast<int>(std::floor(double(sample) * t.bpm / (60 * rate_ * t.beats_per_bar)));
        while (bar_sample(b + 1, t) <= sample) ++b;
        while (b > 0 && bar_sample(b, t) > sample) --b;
        return b;
    }

    std::pair<std::int64_t, std::int64_t> loop_points(const MusicTrack& t) const {
        return {bar_sample(t.loop_start_bar, t), bar_sample(t.bars, t)};
    }

    std::int64_t position(const MusicTrack& t, std::int64_t since, std::int64_t now, std::int64_t entry = 0) const {
        std::int64_t p = now - since + entry;
        const auto [start, end] = loop_points(t);
        if (p >= end) p = start + (p - start) % (end - start);
        return p;
    }

    std::int64_t next_boundary(const MusicTrack& t, std::int64_t p, const std::string& quantize, int phrase_bars) const {
        if (quantize == "immediate") return p;
        const auto [start, end] = loop_points(t);
        if (quantize == "loop_end") return end;
        int step = 0;
        if (quantize == "beat") step = 1;
        else if (quantize == "bar") step = t.beats_per_bar;
        else if (quantize == "phrase") step = t.beats_per_bar * phrase_bars;
        else throw std::runtime_error("unknown quantize " + quantize);  // a typo must not mean "phrase"
        auto k = static_cast<std::int64_t>(std::floor(double(p) * t.bpm / (60 * rate_)));
        while (beat_sample(double(k), t.bpm, rate_) < p) ++k;
        while (k % step) ++k;
        return std::min(beat_sample(double(k), t.bpm, rate_), end);
    }

    // Exact pair, then from "*", then to "*", then default_transition, then the built-in default
    MusicRule rule_for(const std::string& from, const std::string& to) const {
        for (const auto& want : {std::make_pair(from, to), std::make_pair(std::string("*"), to),
                                 std::make_pair(from, std::string("*"))}) {
            for (const auto& r : rules_) {
                if (r.from == want.first && r.to == want.second) return r;
            }
        }
        return default_;
    }

    MusicPlan plan(const std::string& from, std::int64_t since, std::int64_t entry, const std::string& to,
                   std::int64_t now) const {
        const MusicTrack& a = track(from);
        const MusicTrack& b = track(to);
        const MusicRule rule = rule_for(from, to);
        const std::int64_t p = position(a, since, now, entry);
        const std::int64_t boundary = next_boundary(a, p, rule.quantize, rule.phrase_bars);
        MusicPlan out;
        out.switch_at = now + (boundary - p);
        out.fade = static_cast<std::int64_t>(std::floor(rule.fade_ms * rate_ / 1000 + 0.5));
        out.from_stop_at = out.switch_at + out.fade;
        out.to_start_at = out.switch_at;
        out.stinger = rule.stinger;
        if (rule.stinger && !rule.stinger->empty()) {  // "stinger": "" means none, as in the reference
            const auto s = stinger_bars_.find(*rule.stinger);
            if (s == stinger_bars_.end()) throw std::runtime_error("unknown stinger " + *rule.stinger);
            out.stinger_at = out.switch_at;
            out.to_start_at = out.switch_at + beat_sample(s->second * b.beats_per_bar, b.bpm, rate_);
        } else if (rule.sync && a.bpm == b.bpm && a.beats_per_bar == b.beats_per_bar) {
            out.to_offset = boundary - bar_sample(bar_index_at(boundary, a), a);
        }
        return out;
    }

    const MusicTrack& track(const std::string& name) const {
        const auto it = tracks_.find(name);
        if (it == tracks_.end()) throw std::runtime_error("unknown music track " + name);
        return it->second;
    }

private:
    // A rule's fields over a base (the file's default_transition, itself over the built-in default)
    static MusicRule read_rule(const nlohmann::json& r, MusicRule base) {
        base.quantize = r.value("quantize", base.quantize);
        base.fade_ms = r.value("fade_ms", base.fade_ms);
        base.sync = r.value("sync", base.sync);
        base.phrase_bars = r.value("phrase_bars", base.phrase_bars);
        if (r.contains("stinger")) {
            base.stinger = r.at("stinger").is_null() ? std::nullopt
                                                    : std::optional<std::string>(r.at("stinger").get<std::string>());
        }
        return base;
    }

    double rate_;
    std::map<std::string, MusicTrack> tracks_;
    std::map<std::string, double> stinger_bars_;
    std::vector<MusicRule> rules_;
    MusicRule default_;
};

}  // namespace core

// {{FOOTER}}
