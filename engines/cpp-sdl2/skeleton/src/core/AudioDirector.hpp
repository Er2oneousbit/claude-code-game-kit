// ---------------------------------------------------------------------------
// AudioDirector.hpp
// Purpose : Decides how each game sound plays: which file of the event (no back-to-back repeats), its pitch and
//           volume within the event's ranges, voice limits (steal the oldest or refuse), cooldowns, and how far
//           dialogue ducks the music and ambience buses. Data comes from data/audio_events.json. Pure logic, no SDL.
// Usage   : core::AudioDirector dir(events_json);              // {"seed", "events": {...}, "ducking": [...]}
//           const auto d = dir.play("step_stone", now_ms);       // d.result: Played, Cooldown or Capped
//           if (d.result == core::PlayResult::Played) start(files[d.variant], d.pitch_ratio, d.gain_db, d.voice)
//           each frame: for (const auto& [bus, db] : dir.duck(now_ms)) set_bus_duck(bus, db);
// Notes   : A port of tools/audio/wavesmith/audio_events.py (the reference); every step of data/golden/audio.json
//           must come out the same. The random source is Park-Miller in 64-bit integers (exact, no bit operations),
//           drawn in a fixed order (variant, pitch, volume) and never by a rejected play. Each event needs
//           "files" (their count is the number of variants) and "lengths_ms" (one per file, from the loaded
//           sounds): fewer lengths than files throws when the director is made. Calls must come in time order.
//           Where the reference raises (an unknown event, an earlier time, max_voices below 1 with steal
//           "oldest"), play throws std::runtime_error.
//
// Pseudocode:
//   play(e, t) -> drop finished voices -> cooldown? Cooldown -> at max_voices: steal oldest or Capped
//              -> variant by pick rule -> pitch -> volume -> new voice (ends at t + length / pitch ratio)
//   duck(t)    -> per ducking rule: walk the trigger bus's voice edges since the last call, ramp in dB
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace core {

// ---- Tunables ----
constexpr int kDefaultMaxVoices = 8;
constexpr std::int64_t kParkMillerM = 2147483647;  // 2^31 - 1
constexpr std::int64_t kParkMillerA = 16807;

// Park-Miller minimal standard generator: exact in 64-bit integers, so every language agrees
class ParkMiller {
public:
    explicit ParkMiller(std::int64_t seed) {
        s_ = ((seed % kParkMillerM) + kParkMillerM) % kParkMillerM;
        if (s_ == 0) s_ = 1;
    }
    double next() {
        s_ = (s_ * kParkMillerA) % kParkMillerM;
        return static_cast<double>(s_ - 1) / static_cast<double>(kParkMillerM - 1);
    }

private:
    std::int64_t s_;
};

// Per-event seed: a polynomial hash of the ASCII event id mixed with the file's seed (never 0)
inline std::int64_t event_seed(const std::string& event_id, std::int64_t global_seed) {
    std::int64_t h = 0;
    for (unsigned char c : event_id) h = (h * 31 + c) % kParkMillerM;
    const std::int64_t g = ((global_seed % kParkMillerM) + kParkMillerM) % kParkMillerM;
    const std::int64_t s = (h + g * 7919) % kParkMillerM;
    return s == 0 ? 1 : s;
}

struct AudioEvent {
    std::string bus;
    std::vector<std::string> files;  // the variants (PlayDecision::variant indexes them)
    std::vector<double> lengths_ms;
    std::string pick = "random_no_repeat";  // sequence | random | random_no_repeat | shuffle
    double pitch_lo = 0, pitch_hi = 0;      // semitones
    double vol_lo = 0, vol_hi = 0;          // dB
    int max_voices = kDefaultMaxVoices;
    std::string steal = "oldest";           // oldest | none
    double cooldown_ms = 0;
};

struct DuckRule {
    std::string trigger;
    std::vector<std::string> targets;
    double depth_db = 0, attack_ms = 0, release_ms = 0;
};

enum class PlayResult { Played, Cooldown, Capped };

struct PlayDecision {
    PlayResult result = PlayResult::Played;
    int variant = 0;
    double pitch_semitones = 0, pitch_ratio = 1, gain_db = 0;
    int voice = 0;
    std::optional<int> stolen;  // the voice that was stopped to make room, if any
    double ends_ms = 0;
};

class AudioDirector {
public:
    explicit AudioDirector(const nlohmann::json& params) {
        const std::int64_t seed = params.contains("seed") ? params.at("seed").get<std::int64_t>() : 1;
        for (const auto& [name, e] : params.at("events").items()) {
            AudioEvent ev;
            ev.bus = e.at("bus").get<std::string>();
            ev.files = e.at("files").get<std::vector<std::string>>();
            ev.lengths_ms = e.at("lengths_ms").get<std::vector<double>>();
            if (ev.files.empty() || ev.lengths_ms.size() < ev.files.size())
                throw std::runtime_error("audio event " + name + ": files and lengths_ms need one entry per file");
            ev.pick = e.value("pick", std::string("random_no_repeat"));
            if (e.contains("pitch_semitones")) {
                ev.pitch_lo = e["pitch_semitones"][0].get<double>();
                ev.pitch_hi = e["pitch_semitones"][1].get<double>();
            }
            if (e.contains("volume_db")) {
                ev.vol_lo = e["volume_db"][0].get<double>();
                ev.vol_hi = e["volume_db"][1].get<double>();
            }
            ev.max_voices = e.value("max_voices", kDefaultMaxVoices);
            ev.steal = e.value("steal", std::string("oldest"));
            ev.cooldown_ms = e.value("cooldown_ms", 0.0);
            events_.emplace(name, ev);
            rng_.emplace(name, ParkMiller(event_seed(name, seed)));
        }
        if (params.contains("ducking")) {
            for (const auto& r : params.at("ducking")) {
                DuckRule rule;
                rule.trigger = r.at("trigger").get<std::string>();
                rule.targets = r.at("targets").get<std::vector<std::string>>();
                rule.depth_db = r.at("depth_db").get<double>();
                rule.attack_ms = r.value("attack_ms", 0.0);
                rule.release_ms = r.value("release_ms", 0.0);
                triggers_.insert(rule.trigger);
                ducking_.push_back(rule);
                duck_state_.push_back({0.0, 0.0});
            }
        }
    }

    PlayDecision play(const std::string& name, double t) {
        clock(t);
        const auto it = events_.find(name);
        if (it == events_.end()) throw std::runtime_error("unknown audio event " + name);
        const AudioEvent& ev = it->second;
        voices_.erase(std::remove_if(voices_.begin(), voices_.end(), [t](const Voice& v) { return v.end <= t; }),
                      voices_.end());
        PlayDecision d;
        const auto lp = last_play_.find(name);
        if (ev.cooldown_ms != 0 && lp != last_play_.end() && t - lp->second < ev.cooldown_ms) {
            d.result = PlayResult::Cooldown;
            return d;
        }
        int mine = 0;
        for (const auto& v : voices_) mine += v.event == name;
        if (mine >= ev.max_voices) {
            if (ev.steal == "none") {
                d.result = PlayResult::Capped;
                return d;
            }
            // the oldest copy: earliest start, then lowest id
            auto victim = voices_.end();
            for (auto v = voices_.begin(); v != voices_.end(); ++v) {
                if (v->event != name) continue;
                if (victim == voices_.end() || v->start < victim->start ||
                    (v->start == victim->start && v->id < victim->id))
                    victim = v;
            }
            if (victim == voices_.end())  // max_voices below 1: the reference fails here too (min of nothing)
                throw std::runtime_error("audio event " + name + ": max_voices must be 1 or more");
            d.stolen = victim->id;
            for (auto& h : history_) {
                if (h.id == victim->id) h.end = t;  // it stops now: the ducking envelope sees that edge
            }
            voices_.erase(victim);
        }
        ParkMiller& rng = rng_.at(name);
        const int idx = pick(name, ev, rng);
        const double semis = ev.pitch_lo == ev.pitch_hi ? ev.pitch_lo : ev.pitch_lo + (ev.pitch_hi - ev.pitch_lo) * rng.next();
        const double gain = ev.vol_lo == ev.vol_hi ? ev.vol_lo : ev.vol_lo + (ev.vol_hi - ev.vol_lo) * rng.next();
        const double ratio = std::pow(2.0, semis / 12.0);
        Voice voice{next_id_++, name, ev.bus, t, t + ev.lengths_ms.at(static_cast<std::size_t>(idx)) / ratio};
        voices_.push_back(voice);
        if (triggers_.count(voice.bus)) history_.push_back(voice);
        last_play_[name] = t;
        last_variant_[name] = idx;
        d.variant = idx;
        d.pitch_semitones = semis;
        d.pitch_ratio = ratio;
        d.gain_db = gain;
        d.voice = voice.id;
        d.ends_ms = voice.end;
        return d;
    }

    // Duck gain in dB per target bus at time t (every rule advanced to t)
    std::map<std::string, double> duck(double t) {
        clock(t);
        std::map<std::string, double> out;
        for (std::size_t i = 0; i < ducking_.size(); ++i) {
            const DuckRule& rule = ducking_[i];
            auto& st = duck_state_[i];
            std::vector<const Voice*> mine;
            std::set<double> edges;
            for (const auto& v : history_) {
                if (v.bus != rule.trigger) continue;
                mine.push_back(&v);
                for (double e : {v.start, v.end}) {
                    if (st.second < e && e < t) edges.insert(e);
                }
            }
            double gain = st.first, at = st.second;
            std::vector<double> stops(edges.begin(), edges.end());
            stops.push_back(t);
            for (double edge : stops) {
                bool active = false;
                for (const Voice* v : mine) active = active || (v->start <= at && at < v->end);
                gain = ramp(gain, active, rule, edge - at);
                at = edge;
            }
            st = {gain, t};
            for (const auto& bus : rule.targets) {
                const auto o = out.find(bus);
                out[bus] = o == out.end() ? std::min(0.0, gain) : std::min(o->second, gain);
            }
        }
        // every rule now stands at t: voices that ended by then add no later edge (results unchanged)
        history_.erase(std::remove_if(history_.begin(), history_.end(), [t](const Voice& v) { return v.end <= t; }),
                       history_.end());
        return out;
    }

private:
    struct Voice {
        int id;
        std::string event, bus;
        double start, end;
    };

    void clock(double t) {
        if (t < now_) throw std::runtime_error("audio director calls must come in time order");
        now_ = t;
    }

    int pick(const std::string& name, const AudioEvent& ev, ParkMiller& rng) {
        const int n = static_cast<int>(ev.files.size());  // the reference counts files, not lengths
        const auto lv = last_variant_.find(name);
        const int last = lv == last_variant_.end() ? -1 : lv->second;
        if (n == 1) return 0;
        if (ev.pick == "sequence") return (last + 1) % n;
        if (ev.pick == "random") return std::min(static_cast<int>(std::floor(rng.next() * n)), n - 1);
        if (ev.pick == "random_no_repeat") {
            if (last < 0) return std::min(static_cast<int>(std::floor(rng.next() * n)), n - 1);
            const int k = std::min(static_cast<int>(std::floor(rng.next() * (n - 1))), n - 2);
            return k >= last ? k + 1 : k;
        }
        std::vector<int>& bag = bags_[name];  // shuffle: every file once per round
        if (bag.empty()) {
            for (int i = 0; i < n; ++i) bag.push_back(i);
            for (int i = n - 1; i > 0; --i) {
                const int j = std::min(static_cast<int>(std::floor(rng.next() * (i + 1))), i);
                std::swap(bag[static_cast<std::size_t>(i)], bag[static_cast<std::size_t>(j)]);
            }
            if (bag[0] == last) std::swap(bag[0], bag[1]);  // never the same file twice across a refill
        }
        const int idx = bag.front();
        bag.erase(bag.begin());
        return idx;
    }

    static double ramp(double gain, bool active, const DuckRule& rule, double dt) {
        const double depth = rule.depth_db;
        if (active) {
            if (rule.attack_ms <= 0) return depth;
            return std::max(depth, gain + depth / rule.attack_ms * dt);
        }
        if (rule.release_ms <= 0) return 0.0;
        return std::min(0.0, gain - depth / rule.release_ms * dt);
    }

    std::map<std::string, AudioEvent> events_;
    std::map<std::string, ParkMiller> rng_;
    std::vector<DuckRule> ducking_;
    std::vector<std::pair<double, double>> duck_state_;  // per rule: gain dB, time of the last update
    std::set<std::string> triggers_;
    std::vector<Voice> voices_, history_;
    std::map<std::string, double> last_play_;
    std::map<std::string, int> last_variant_;
    std::map<std::string, std::vector<int>> bags_;
    int next_id_ = 1;
    double now_ = 0;
};

}  // namespace core

// {{FOOTER}}
