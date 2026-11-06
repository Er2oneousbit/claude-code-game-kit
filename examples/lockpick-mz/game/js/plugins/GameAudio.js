// ---------------------------------------------------------------------------
// GameAudio.js
// Purpose : The kit's audio rules, engine-free: the audio director (which file of a sound event, pitch and volume
//           draws, cooldowns, voice caps, ducking), the music director (beat grid, loop points, when a transition
//           may happen and how) and the audio accessibility rules (slider gains per bus, caption arrows). Plain
//           JavaScript with no RPG Maker objects, so Node tests it (tests/gameAudio.test.js) against the kit's golden
//           vectors (data/golden/audio.json, music.json, access.json) and MZ loads it as an ordinary plugin.
// Usage   : in another plugin:  const dir = new GameAudio.AudioDirector(events);   // { seed?, events, ducking? }
//                               const d = dir.play("step_stone", nowMs);          // d.result: "played" | ...
//                               const p = GameAudio.planTransition(music, "explore", since, entry, "combat", now);
//                               GameAudio.userBusGains(buses, sliders); GameAudio.captionArrow(dx, dy, halfW, halfH);
//           in a test:          const GameAudio = require("../game/js/plugins/GameAudio.js");
// Notes   : Ports of tools/audio/wavesmith/audio_events.py, music.py and access.py (the specs; the web overlay's
//           audioDirector.ts, musicDirector.ts and audioAccess.ts are the same rules in TypeScript). Park-Miller
//           runs in plain JS numbers: every product stays below 2^53, so no bit operations and no BigInt. Rounding
//           is always floor(x + 0.5), never Math.round (it rounds -0.5 differently from Python).
//           This file only decides; playing is MZ's job. A glue plugin would turn a decision into
//           AudioManager.playSe({ name, volume, pitch, pan }), where volume is 0..100 linear and pitch is the
//           playback rate in percent (pitch_ratio * 100), and the slider gains into ConfigManager.bgmVolume,
//           bgsVolume, meVolume and seVolume (0..100). None of that is wired yet (verify in RPG Maker MZ).
//           Keep it free of $game*, Scene_*, Window_*, AudioManager: anything MZ goes in GameMain.js.
//           The last lines make the same file a global (GameAudio) in MZ and a CommonJS module in Node.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/*:
 * @target MZ
 * @plugindesc Lockpick MZ: audio rules (engine-free: sound events, music transitions, audio accessibility).
 * @author the user
 *
 * @help GameAudio.js
 *
 * The kit's audio rules for Lockpick MZ, kept free of RPG Maker objects so
 * they can be tested outside the editor (python tools/dev.py test) against
 * the kit's golden vectors. It decides which file, pitch and volume a sound
 * gets, when a music change may happen, and how loud each bus plays for the
 * player's sliders. It plays nothing itself: a glue plugin passes those
 * decisions to AudioManager (verify in RPG Maker MZ).
 * No plugin commands and no parameters.
 */

(() => {
    "use strict";

    // ---- Tunables -------------------------------------------------------------
    const DEFAULT_MAX_VOICES = 8;          // voices per event when the event does not say
    const DEFAULT_BEATS_PER_BAR = 4;
    const DEFAULT_PHRASE_BARS = 4;
    const PM_M = 2147483647;               // Park-Miller modulus (2^31 - 1)
    const PM_A = 16807;                    // Park-Miller multiplier: s * PM_A < 2^46, exact in a double
    const DEFAULT_RULE = { quantize: "bar", fade_ms: 0, sync: false };   // music.py DEFAULT_RULE

    // Bus name -> settings slider (access.py SLIDER_FOR_BUS). Pass your own map to userBusGains when your
    // audio_events.json uses other bus names (MZ's own channels are bgm, bgs, me, se: verify in RPG Maker MZ).
    const SLIDER_FOR_BUS = {
        master: "master", music: "music", sfx: "sfx", ambience: "sfx", ui: "ui", dialogue: "voice", voice: "voice",
    };
    const ARROWS = ["→", "↘", "↓", "↙", "←", "↖", "↑", "↗"];   // k = 0..7, clockwise from the right (y down)

    // ---- Small helpers --------------------------------------------------------
    // Own keys only: an event or bus named "constructor" must not find Object.prototype's
    const has = (obj, key) => obj !== null && typeof obj === "object" && Object.prototype.hasOwnProperty.call(obj, key);
    // Python's dict.get(key, default) for JSON data: a missing or null field takes the default
    const orDefault = (v, d) => (v === undefined || v === null ? d : v);
    // Modulo that is never negative, like Python's (JS % keeps the sign of the dividend)
    const mod = (a, m) => ((a % m) + m) % m;
    const beatsPerBar = (track) => orDefault(track.beats_per_bar, DEFAULT_BEATS_PER_BAR);

    // =============================================================================
    // Audio director (audio_events.py)
    // =============================================================================

    // Park-Miller minimal standard generator: exact in doubles, so Python, JS and every other port agree
    class ParkMiller {
        constructor(seed) {
            this.s = mod(seed, PM_M) || 1;
        }

        next() {                           // a number in [0, 1)
            this.s = (this.s * PM_A) % PM_M;
            return (this.s - 1) / (PM_M - 1);
        }
    }

    // One random stream per event, so adding an event never changes the draws of another
    function eventSeed(eventId, globalSeed) {
        let h = 0;
        for (let i = 0; i < eventId.length; i++) h = (h * 31 + eventId.charCodeAt(i)) % PM_M;   // ids are ASCII
        return (h + mod(globalSeed, PM_M) * 7919) % PM_M || 1;
    }

    // Duck gain in dB after dt ms: a straight line towards depth while the trigger bus plays, back to 0 when not
    function ramp(gain, active, rule, dt) {
        const depth = rule.depth_db;
        const attack = orDefault(rule.attack_ms, 0);
        const release = orDefault(rule.release_ms, 0);
        if (active) return attack <= 0 ? depth : Math.max(depth, gain + (depth / attack) * dt);
        return release <= 0 ? 0 : Math.min(0, gain - (depth / release) * dt);
    }

    class AudioDirector {
        // params: { seed?, events: { id: { bus, files, lengths_ms, pick?, pitch_semitones?, ... } }, ducking? }
        constructor(params) {
            if (!params || !has(params, "events")) throw new TypeError("AudioDirector needs { events: {...} }");
            this.events = params.events;
            this.ducking = orDefault(params.ducking, []);
            const seed = orDefault(params.seed, 1);
            this.rng = {};
            for (const name of Object.keys(this.events)) this.rng[name] = new ParkMiller(eventSeed(name, seed));
            this.voices = [];              // { id, event, bus, start, end }; end moves to the steal time when stolen
            this.history = [];             // trigger-bus voices the ducking envelopes may still need
            this.triggers = new Set(this.ducking.map((r) => r.trigger));
            this.nextId = 1;
            this.lastPlay = {};
            this.lastVariant = {};
            this.bags = {};
            this.duckState = this.ducking.map(() => ({ gain: 0, t: 0 }));
            this.now = 0;
        }

        _clock(t) {
            if (t < this.now) throw new RangeError(`calls must come in time order (${t} ms after ${this.now} ms)`);
            this.now = t;
        }

        // Which file of the event; draws from rng only when the rule needs it (the draw order is part of the spec)
        _pick(name, ev, rng) {
            const n = ev.files.length;
            const last = has(this.lastVariant, name) ? this.lastVariant[name] : -1;
            const rule = orDefault(ev.pick, "random_no_repeat");
            if (n === 1) return 0;
            if (rule === "sequence") return (last + 1) % n;
            if (rule === "random") return Math.min(Math.floor(rng.next() * n), n - 1);
            if (rule === "random_no_repeat") {
                if (last < 0) return Math.min(Math.floor(rng.next() * n), n - 1);
                const k = Math.min(Math.floor(rng.next() * (n - 1)), n - 2);   // one of the other n - 1 files
                return k >= last ? k + 1 : k;
            }
            if (rule !== "shuffle") throw new RangeError(`event ${name}: unknown pick rule ${rule}`);
            let bag = has(this.bags, name) ? this.bags[name] : [];
            if (bag.length === 0) {        // refill with Fisher-Yates
                bag = Array.from({ length: n }, (_, i) => i);
                for (let i = n - 1; i > 0; i--) {
                    const j = Math.min(Math.floor(rng.next() * (i + 1)), i);
                    [bag[i], bag[j]] = [bag[j], bag[i]];
                }
                if (bag[0] === last) [bag[0], bag[1]] = [bag[1], bag[0]];   // never the same file twice across a refill
            }
            const idx = bag.shift();
            this.bags[name] = bag;
            return idx;
        }

        // Decide one play of event `name` at t ms: { result: "played", variant, ... } | "cooldown" | "capped"
        play(name, t) {
            this._clock(t);
            if (!has(this.events, name)) throw new RangeError(`unknown audio event ${name}`);
            const ev = this.events[name];
            this.voices = this.voices.filter((v) => v.end > t);
            const cooldown = orDefault(ev.cooldown_ms, 0);
            if (cooldown && has(this.lastPlay, name) && t - this.lastPlay[name] < cooldown) {
                return { result: "cooldown" };                                    // rejected: no draws
            }
            const mine = this.voices.filter((v) => v.event === name);
            let stolen = null;
            if (mine.length >= orDefault(ev.max_voices, DEFAULT_MAX_VOICES)) {
                if (orDefault(ev.steal, "oldest") === "none") return { result: "capped" };   // rejected: no draws
                const victim = mine.reduce((a, b) =>
                    (b.start < a.start || (b.start === a.start && b.id < a.id) ? b : a));   // oldest, then lowest id
                victim.end = t;            // it stops now (the ducking envelope sees that)
                this.voices = this.voices.filter((v) => v !== victim);
                stolen = victim.id;
            }
            const rng = this.rng[name];
            const idx = this._pick(name, ev, rng);
            const [lo, hi] = orDefault(ev.pitch_semitones, [0, 0]);
            const semis = lo === hi ? lo : lo + (hi - lo) * rng.next();
            const [vlo, vhi] = orDefault(ev.volume_db, [0, 0]);
            const gain = vlo === vhi ? vlo : vlo + (vhi - vlo) * rng.next();
            const ratio = Math.pow(2, semis / 12);
            // a resampled voice plays faster when pitched up, so it ends sooner
            // (MZ's pitch is a playback rate too: verify in RPG Maker MZ)
            const end = t + ev.lengths_ms[idx] / ratio;
            const voice = { id: this.nextId++, event: name, bus: ev.bus, start: t, end };
            this.voices.push(voice);
            if (this.triggers.has(voice.bus)) this.history.push(voice);
            this.lastPlay[name] = t;
            this.lastVariant[name] = idx;
            return { result: "played", variant: idx, pitch_semitones: semis, pitch_ratio: ratio, gain_db: gain,
                     voice: voice.id, stolen, ends_ms: voice.end };
        }

        // Duck gain in dB per target bus at t ms (every rule advanced to t); the lowest rule wins on a shared bus
        duck(t) {
            this._clock(t);
            const out = {};
            this.ducking.forEach((rule, i) => {
                const st = this.duckState[i];
                const mine = this.history.filter((v) => v.bus === rule.trigger);
                // walk every voice start and end since the last call, so a call every few seconds gives the same curve
                const edges = [...new Set(mine.flatMap((v) => [v.start, v.end]).filter((e) => st.t < e && e < t))]
                    .sort((a, b) => a - b);
                let gain = st.gain;
                let at = st.t;
                for (const edge of [...edges, t]) {
                    const active = mine.some((v) => v.start <= at && at < v.end);
                    gain = ramp(gain, active, rule, edge - at);
                    at = edge;
                }
                st.gain = gain;
                st.t = t;
                for (const bus of rule.targets) out[bus] = Math.min(has(out, bus) ? out[bus] : 0, gain);
            });
            // every rule now stands at t: voices that ended by then add no later edge, so they can go
            // (results unchanged; keeps duck() cheap in a long session)
            this.history = this.history.filter((v) => v.end > t);
            return out;
        }
    }

    // =============================================================================
    // Music director (music.py): every value is a whole number of samples
    // =============================================================================

    // First sample of beat k: floor(k * 60 * rate / bpm + 0.5), the same sample in every engine
    function beatSample(k, bpm, rate) {
        return Math.floor((k * 60 * rate) / bpm + 0.5);
    }

    function barSample(b, track, rate) {
        return beatSample(b * beatsPerBar(track), track.bpm, rate);
    }

    // The bar that holds `sample`, exact on the rounded grid (the float estimate is only a starting point)
    function barIndexAt(sample, track, rate) {
        let b = Math.floor((sample * track.bpm) / (60 * rate * beatsPerBar(track)));
        while (barSample(b + 1, track, rate) <= sample) b++;
        while (b > 0 && barSample(b, track, rate) > sample) b--;
        return b;
    }

    // [loop start, loop end) in samples; bars before loop_start_bar are an intro that plays once
    function loopPoints(track, rate) {
        return [barSample(orDefault(track.loop_start_bar, 0), track, rate), barSample(track.bars, track, rate)];
    }

    // Where playback is (samples from the track's start) at `now`, started at `since` from offset `entry`
    function position(track, rate, since, now, entry = 0) {
        let p = now - since + entry;
        const [start, end] = loopPoints(track, rate);
        if (p >= end) p = start + mod(p - start, end - start);
        return p;
    }

    // The first boundary of the kind at or after track position p (beats counted from the track's first beat)
    function nextBoundary(track, rate, p, quantize, phraseBars = DEFAULT_PHRASE_BARS) {
        if (quantize === "immediate") return p;
        const end = loopPoints(track, rate)[1];
        if (quantize === "loop_end") return end;
        const bpb = beatsPerBar(track);
        const step = quantize === "beat" ? 1 : quantize === "bar" ? bpb : quantize === "phrase" ? bpb * phraseBars : 0;
        if (!(step > 0)) throw new RangeError(`unknown quantize ${quantize} (or phrase_bars ${phraseBars})`);
        let k = Math.floor((p * track.bpm) / (60 * rate));
        while (beatSample(k, track.bpm, rate) < p) k++;
        while (k % step) k++;
        return Math.min(beatSample(k, track.bpm, rate), end);
    }

    // The rule for a change: exact pair, then from "*", then to "*", then the file's default, then the built-in one
    function ruleFor(music, from, to) {
        const rules = orDefault(music.transitions, []);
        const base = Object.assign({}, DEFAULT_RULE, orDefault(music.default_transition, {}));
        for (const [f, t] of [[from, to], ["*", to], [from, "*"]]) {
            const r = rules.find((x) => x.from === f && x.to === t);
            if (r) return Object.assign({}, base, r);
        }
        return base;
    }

    // When and how to change from track `from` (playing since sample `since` from offset `entry`) to `to`, asked
    // at sample `now`: { switch_at, from_stop_at, fade, to_offset, to_start_at, stinger, stinger_at }
    function planTransition(music, from, since, entry, to, now) {
        const rate = music.sample_rate;
        const tracks = orDefault(music.tracks, {});
        if (!has(tracks, from)) throw new RangeError(`unknown track ${from}`);
        if (!has(tracks, to)) throw new RangeError(`unknown track ${to}`);
        const a = tracks[from];
        const b = tracks[to];
        const rule = ruleFor(music, from, to);
        const p = position(a, rate, since, now, entry);
        const boundary = nextBoundary(a, rate, p, rule.quantize, orDefault(rule.phrase_bars, DEFAULT_PHRASE_BARS));
        const switchAt = now + (boundary - p);
        const fade = Math.floor((orDefault(rule.fade_ms, 0) * rate) / 1000 + 0.5);
        const out = { switch_at: switchAt, from_stop_at: switchAt + fade, fade, to_offset: 0, to_start_at: switchAt,
                      stinger: orDefault(rule.stinger, null), stinger_at: null };
        if (rule.stinger) {
            const stingers = orDefault(music.stingers, {});
            if (!has(stingers, rule.stinger)) throw new RangeError(`unknown stinger ${rule.stinger}`);
            out.stinger_at = switchAt;
            out.to_start_at = switchAt + beatSample(stingers[rule.stinger].bars * beatsPerBar(b), b.bpm, rate);
        } else if (rule.sync && a.bpm === b.bpm && beatsPerBar(a) === beatsPerBar(b)) {
            // keep the beat: enter the target at the same place in its bar (bar boundaries are where they line up)
            out.to_offset = boundary - barSample(barIndexAt(boundary, a, rate), a, rate);
        }
        return out;
    }

    // =============================================================================
    // Audio accessibility (access.py)
    // =============================================================================

    // A slider value as a gain: 0..1; missing, non-numeric or not finite counts as 1 (never mute by accident)
    function clamp01(v) {
        return typeof v === "number" && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 1;
    }

    // { bus: linear gain } from the player's sliders. A slider never applies twice down one branch: a bus whose
    // parent already follows the same slider gets 1 (ambience under sfx). Parents default to "master".
    function userBusGains(buses, sliders, mapping = SLIDER_FOR_BUS) {
        const names = Object.keys(buses);
        const sliderOf = (bus) => (has(mapping, bus) ? mapping[bus] : undefined);
        const parentOf = (bus) => {
            const p = has(buses, bus) && buses[bus] ? buses[bus].parent : undefined;
            return p !== undefined && p !== null ? p : bus === "master" ? undefined : "master";
        };
        const out = {};
        for (const name of names) {
            const slider = sliderOf(name);
            let inherited = false;
            // walk up the parents, at most one step per bus, so a cycle (a -> b -> a) cannot hang
            let p = parentOf(name);
            for (let n = 0; p !== undefined && n < names.length; n++, p = parentOf(p)) {
                if (slider !== undefined && sliderOf(p) === slider) inherited = true;
            }
            const value = has(sliders, slider) ? sliders[slider] : undefined;
            out[name] = slider === undefined || inherited ? 1 : clamp01(value);
        }
        return out;
    }

    // -1 while a sound at (dx, dy) from the view's centre is inside the view (edges included), else the direction
    // 0..7 clockwise from the right (screen y grows downwards, as in MZ's Graphics: verify in RPG Maker MZ)
    function captionDirection(dx, dy, halfW, halfH) {
        if (!Number.isFinite(dx) || !Number.isFinite(dy)) return -1;
        if (Math.abs(dx) <= halfW && Math.abs(dy) <= halfH) return -1;
        return mod(Math.floor(Math.atan2(dy, dx) / (Math.PI / 4) + 0.5), 8);
    }

    // The arrow for a caption of an off-screen sound, or "" while it is on screen
    function captionArrow(dx, dy, halfW, halfH) {
        const k = captionDirection(dx, dy, halfW, halfH);
        return k < 0 ? "" : ARROWS[k];
    }

    const GameAudio = {
        // audio director
        AudioDirector, ParkMiller, eventSeed, DEFAULT_MAX_VOICES,
        // music director
        beatSample, barSample, barIndexAt, loopPoints, position, nextBoundary, ruleFor, planTransition,
        // accessibility
        userBusGains, captionDirection, captionArrow, clamp01, SLIDER_FOR_BUS, ARROWS,
    };

    // Both, not either: MZ's desktop test play (NW.js) may define `module` too, and the plugins need the global
    globalThis.GameAudio = GameAudio;                                                       // RPG Maker MZ
    if (typeof module === "object" && module && module.exports) module.exports = GameAudio; // Node (tests)
})();
