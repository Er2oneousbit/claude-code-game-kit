// ---------------------------------------------------------------------------
// GamePlatform.js
// Purpose : The kit's platform layer (#84, docs/PLATFORM.md) for RPG Maker MZ: achievements, stats, rich presence,
//           the overlay's pause hook and cloud saves, kept here and sent to a backend. Every game runs the null
//           backend (it records every call). The rules are plain JavaScript with no RPG Maker objects, so Node tests
//           them (tests/gamePlatform.test.js) against data/golden/platform.json; the MZ glue at the end runs only
//           inside MZ.
// Usage   : in another plugin or a Script event command:
//               GamePlatform.service.unlock("first_win") ; GamePlatform.service.addStat("enemies_defeated", 1)
//               GamePlatform.service.setPresence("status", "In the crypt")
//           GamePlatform.onOverlay(active) when a store overlay opens or closes (over the map it opens the menu)
//           in a test: const GamePlatform = require("../game/js/plugins/GamePlatform.js");
// Notes   : The same rules as the web overlay's src/core/platform.ts (compiled from it, then hand-checked). MZ
//           glue: the achievements come from game/data/achievements.json (none: every call is "unknown" and
//           nothing is written, so the game runs exactly as before); the local state is platform_state.json in
//           MZ's save folder (desktop) or localStorage (browser), written only when it changed; MZ's menu is the
//           pause menu: opening it flushes, and so do a save and quitting; DataManager.saveGame calls saved() for
//           save/file<N>.rmmzsave once MZ's write resolved. The overlay over Scene_Map asks the map for its menu
//           (menuCalling, so MZ opens it when the menu is allowed); over a battle, an event or a menu it does
//           nothing. A browser build has no Steam and keeps the null backend.
//           The last lines make the same file a global (GamePlatform) in MZ and a CommonJS module in Node.
//
// Pseudocode:
//   rules op -> update local state -> online: send calls to the backend one at a time, in order
//   flush: set_stat per pending stat (definition order), set_achievement per pending unlock, store_stats;
//          a false store_stats keeps everything and goes offline; then cloud_write per pending cloud file
//   service: defs <- achievements.json ; state <- platform_state.json ; backend available ->
//          connect(backend.remote()) ; after every op: write the state file when it changed
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/*:
 * @target MZ
 * @plugindesc {{GAME_NAME}}: platform services (achievements, stats, presence, cloud hooks; null backend).
 * @author {{AUTHOR}}
 * @orderAfter GameShell
 *
 * @help GamePlatform.js
 *
 * The kit's platform layer for {{GAME_NAME}}: achievements and stats from
 * data/achievements.json, rich presence, cloud-save hooks and the store
 * overlay's pause. Every game runs the null backend, which records what a
 * store would have been sent; docs/PLATFORM.md explains the Steam side.
 * Without data/achievements.json it does nothing.
 * No plugin commands and no parameters: call GamePlatform.service from a
 * Script command or your own plugin.
 */

(() => {
    "use strict";

    const isObject = (v) => typeof v === "object" && v !== null && !Array.isArray(v);
    const Log = { warn: (channel, msg) => console.warn(`[${channel}] ${msg}`) };
    // the kit's atomic write (tmp, read back, rename) on a { read, write, rename } store
    function atomicWrite(store, name, text) {
        const tmp = name + ".tmp";
        store.write(tmp, text);
        if (store.read(tmp) !== text) throw new Error(`atomic write: ${tmp} did not read back complete`);
        store.rename(tmp, name);
    }

    // ---- Tunables (the same in every engine: data/golden/platform.json "names and limits") ------
    const PLATFORM_FORMAT = "platform_state";
    const PLATFORM_STATE_VERSION = 1;
    const PLATFORM_STATE_FILE = "platform_state.json";
    const PLATFORM_ID_MAX = 64;
    const STAT_TYPES = ["int", "float"];
    const PRESENCE_MAX_KEYS = 30; // Steam's rich presence limits (verify)
    const PRESENCE_MAX_VALUE_BYTES = 255;
    const CLOUD_MODES = ["auto", "api"];
    const CLOUD_LOCAL_NAMES = ["settings.json", PLATFORM_STATE_FILE, "telemetry.csv", "log_tail.txt"];
    const CLOUD_LOCAL_SUFFIXES = [".tmp", ".log"];
    const CLOUD_LOCAL_DIRS = ["logs", "crashes", "captures"];
    const OVERLAY_PAUSE_SCREENS = ["play"];
    /** The game's cloud mode: "auto" (Steam Auto-Cloud, no code, preferred) or "api" (the adapter writes files). */
    const CLOUD_MODE = "auto";
    const LETTERS = /^[A-Za-z][A-Za-z0-9_]*$/;
    /** An achievement, stat or presence key name: 1 to 64 ASCII characters, a letter first. */
    function platformIdOk(v) {
        return typeof v === "string" && v.length > 0 && v.length <= PLATFORM_ID_MAX && LETTERS.test(v);
    }
    /** A finite number (JSON true is never 1 here). */
    const numOk = (v) => typeof v === "number" && Number.isFinite(v);
    /** Whole by value, never by type: 5 and 5.0 are the same number. */
    const whole = (v) => numOk(v) && Math.floor(v) === v;
    const utf8Len = (s) => new TextEncoder().encode(s).length;
    const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
    /** o[k] when the key is there (null included), else the default: Python's dict.get(k, default). */
    const get = (o, k, dflt) => (has(o, k) ? o[k] : dflt);
    function clampStat(s, v) {
        const lo = Math.max(v, s.min);
        return s.max === null ? lo : Math.min(lo, s.max);
    }
    /** A stat's value before anything happened: 0 clamped into [min, max]. */
    function statInitial(s) {
        return clampStat(s, 0);
    }
    const emptyDefs = () => ({ version: PLATFORM_STATE_VERSION, stats: [], achievements: [] });
    /** data/achievements.json text (null or "" = no file) -> the definitions and the number of problems. */
    function achievementsLoad(text) {
        if (!text)
            return { defs: emptyDefs(), problems: 0 };
        let raw;
        try {
            raw = JSON.parse(text);
        }
        catch {
            return { defs: emptyDefs(), problems: 1 };
        }
        if (!isObject(raw))
            return { defs: emptyDefs(), problems: 1 };
        let problems = 0;
        const stats = [];
        const achievements = [];
        let rawStats = get(raw, "stats", []);
        if (!Array.isArray(rawStats)) {
            rawStats = [];
            problems++;
        }
        for (const s of rawStats) {
            let ok = isObject(s) && platformIdOk(s.id) && stats.every((t) => t.id !== s.id);
            let kind, lo, hi, inc;
            if (ok && isObject(s)) {
                kind = get(s, "type", "int");
                lo = get(s, "min", 0);
                hi = get(s, "max", null);
                inc = get(s, "increment_only", false);
                const w = kind === "int" ? whole : numOk;
                ok = STAT_TYPES.includes(kind) && w(lo) && (hi === null || (w(hi) && hi >= lo)) && typeof inc === "boolean";
            }
            if (!ok || !isObject(s)) {
                problems++;
                continue;
            }
            stats.push({ id: s.id, type: kind, min: lo, max: hi, increment_only: inc });
        }
        const byId = new Map(stats.map((s) => [s.id, s]));
        let rawAch = get(raw, "achievements", []);
        if (!Array.isArray(rawAch)) {
            rawAch = [];
            problems++;
        }
        for (const a of rawAch) {
            let ok = isObject(a) &&
                platformIdOk(a.id) &&
                achievements.every((b) => b.id !== a.id) &&
                typeof a.name === "string" &&
                a.name !== "" &&
                typeof get(a, "description", "") === "string";
            let stat = null, threshold = null, every = null;
            if (ok && isObject(a)) {
                stat = get(a, "stat", null);
                threshold = get(a, "threshold", null);
                every = get(a, "progress_every", null);
                if (stat !== null) {
                    const sdef = typeof stat === "string" ? byId.get(stat) : undefined;
                    const w = sdef && sdef.type === "int" ? whole : numOk;
                    ok =
                        sdef !== undefined &&
                            w(threshold) &&
                            threshold > statInitial(sdef) &&
                            (sdef.max === null || threshold <= sdef.max) &&
                            (every === null || (w(every) && every > 0 && every < threshold));
                }
                else {
                    ok = threshold === null && every === null; // a threshold without a stat is a mistake
                }
            }
            if (!ok || !isObject(a)) {
                problems++;
                continue;
            }
            achievements.push({
                id: a.id,
                name: a.name,
                description: get(a, "description", ""),
                stat: stat,
                threshold: stat === null ? null : threshold,
                progress_every: every === null ? null : every,
            });
        }
        return { defs: { version: PLATFORM_STATE_VERSION, stats, achievements }, problems };
    }
    /** Which user-data file syncs: "cloud" or "local". ASCII-only folding (never a locale's lowercase). */
    function cloudPartition(path) {
        const folded = path.replace(/[A-Z]/g, (c) => String.fromCharCode(c.charCodeAt(0) + 32));
        const parts = folded.replace(/\\/g, "/").split("/").filter((p) => p !== "" && p !== ".");
        if (parts.length === 0)
            return "local";
        const name = parts[parts.length - 1];
        if ((parts.length > 1 && CLOUD_LOCAL_DIRS.includes(parts[0])) || CLOUD_LOCAL_NAMES.includes(name) || CLOUD_LOCAL_SUFFIXES.some((s) => name.endsWith(s))) {
            return "local";
        }
        return "cloud";
    }
    /** The store overlay opened (active) or closed over `screen`: "pause" opens the pause menu; closing never resumes. */
    function overlayAction(active, screen) {
        return active && OVERLAY_PAUSE_SCREENS.includes(screen) ? "pause" : "none";
    }
    /** The backend every game runs by default: records every call and keeps what a store would hold. */
    class NullBackend {
        name = "null";
        calls = [];
        unlocked = [];
        stats = {};
        presence = {};
        cloud = [];
        /** Test hook: the next N store_stats fail (a failed store lands nothing). */
        failStores = 0;
        stagedUnlocks = [];
        stagedStats = {};
        available() {
            return true;
        }
        remote() {
            return { unlocked: [...this.unlocked], stats: { ...this.stats } };
        }
        send(call) {
            this.calls.push([...call]);
            const [name, a, b] = call;
            if (name === "set_achievement") {
                if (!this.stagedUnlocks.includes(a))
                    this.stagedUnlocks.push(a);
            }
            else if (name === "set_stat") {
                this.stagedStats[a] = b;
            }
            else if (name === "store_stats") {
                if (this.failStores > 0) {
                    this.failStores--;
                    return false;
                }
                for (const u of this.stagedUnlocks)
                    if (!this.unlocked.includes(u))
                        this.unlocked.push(u);
                Object.assign(this.stats, this.stagedStats);
                this.stagedUnlocks = [];
                this.stagedStats = {};
            }
            else if (name === "reset_all_stats") {
                this.unlocked = [];
                this.stats = {};
                this.stagedUnlocks = [];
                this.stagedStats = {};
            }
            else if (name === "set_presence") {
                if (b === "")
                    delete this.presence[a];
                else
                    this.presence[a] = b;
            }
            else if (name === "clear_presence") {
                this.presence = {};
            }
            else if (name === "cloud_write" && !this.cloud.includes(a)) {
                this.cloud.push(a);
            }
            return true;
        }
    }
    /** The rules (PLATFORM.md section 3). Every operation returns its status word and the calls it sent, in order. */
    class Platform {
        defs;
        backend;
        online;
        cloud;
        statDefs;
        achDefs;
        unlocked = [];
        stats = {};
        pendingStats = [];
        pendingUnlocks = [];
        pendingCloud = [];
        presence = {};
        sent = [];
        constructor(defs, backend = new NullBackend(), online = false, cloud = "auto") {
            this.defs = defs;
            this.backend = backend;
            this.online = online;
            this.cloud = cloud;
            this.statDefs = new Map(defs.stats.map((s) => [s.id, s]));
            this.achDefs = new Map(defs.achievements.map((a) => [a.id, a]));
            this.resetLocal();
        }
        resetLocal() {
            this.unlocked = [];
            this.stats = {};
            for (const s of this.defs.stats)
                this.stats[s.id] = statInitial(s);
            this.pendingStats = [];
            this.pendingUnlocks = [];
            this.pendingCloud = [];
        }
        /** What the state file holds (and what the golden steps compare). */
        state() {
            return {
                format: PLATFORM_FORMAT,
                version: PLATFORM_STATE_VERSION,
                unlocked: [...this.unlocked],
                stats: { ...this.stats },
                pending: {
                    stats: this.defs.stats.filter((s) => this.pendingStats.includes(s.id)).map((s) => s.id),
                    unlocks: [...this.pendingUnlocks],
                    cloud: [...this.pendingCloud],
                },
            };
        }
        /** Takes over a loaded state (platformStateLoad's), e.g. at start. */
        restore(st) {
            this.unlocked = [...st.unlocked];
            this.stats = { ...st.stats };
            this.pendingStats = [...st.pending.stats];
            this.pendingUnlocks = [...st.pending.unlocks];
            this.pendingCloud = [...st.pending.cloud];
        }
        /** The presence map, keys sorted (ordinal). */
        presenceList() {
            return Object.keys(this.presence).sort().map((k) => [k, this.presence[k]]);
        }
        send(call) {
            this.sent.push(call);
            return this.backend.send(call);
        }
        done(out) {
            const calls = this.sent;
            this.sent = [];
            return { out, calls };
        }
        unlockLocal(id) {
            this.unlocked.push(id);
            this.pendingUnlocks.push(id);
        }
        unlock(id) {
            if (!this.achDefs.has(id))
                return this.done("unknown");
            if (this.unlocked.includes(id))
                return this.done("already");
            this.unlockLocal(id);
            if (this.online)
                this.flushInner();
            return this.done("unlocked");
        }
        check(sid, old, now, notify) {
            let unlocked = false;
            for (const a of this.defs.achievements) {
                if (a.stat !== sid || this.unlocked.includes(a.id))
                    continue;
                if (now >= a.threshold) {
                    this.unlockLocal(a.id);
                    unlocked = true;
                }
                else if (notify && this.online && a.progress_every !== null && Math.floor(now / a.progress_every) > Math.floor(old / a.progress_every)) {
                    this.send(["indicate_progress", a.id, now, a.threshold]);
                }
            }
            return unlocked;
        }
        /** v may be anything a caller (or a JSON file) passes: a non-number is refused, never coerced. */
        setStat(id, v) {
            const s = this.statDefs.get(id);
            if (!s)
                return this.done("unknown");
            if (!numOk(v) || (s.type === "int" && !whole(v)))
                return this.done("refused");
            const c = clampStat(s, v);
            const old = this.stats[id];
            if (s.increment_only && c < old)
                return this.done("refused");
            if (c === old)
                return this.done("same");
            this.stats[id] = c;
            if (!this.pendingStats.includes(id))
                this.pendingStats.push(id);
            if (this.check(id, old, c, true) && this.online)
                this.flushInner();
            return this.done(c !== v ? "clamped" : "ok");
        }
        addStat(id, d) {
            const s = this.statDefs.get(id);
            if (!s)
                return this.done("unknown");
            if (!numOk(d) || (s.type === "int" && !whole(d)))
                return this.done("refused");
            return this.setStat(id, this.stats[id] + d);
        }
        flushInner() {
            if (!this.online)
                return "offline";
            if (this.pendingStats.length === 0 && this.pendingUnlocks.length === 0 && this.pendingCloud.length === 0)
                return "nothing";
            if (this.pendingStats.length > 0 || this.pendingUnlocks.length > 0) {
                for (const s of this.defs.stats)
                    if (this.pendingStats.includes(s.id))
                        this.send(["set_stat", s.id, this.stats[s.id]]);
                for (const id of this.pendingUnlocks)
                    this.send(["set_achievement", id]);
                if (!this.send(["store_stats"])) {
                    this.online = false; // the store said no: keep everything, wait for connect()
                    return "failed";
                }
                this.pendingStats = [];
                this.pendingUnlocks = [];
            }
            for (const p of this.pendingCloud)
                this.send(["cloud_write", p]);
            this.pendingCloud = [];
            return "sent";
        }
        flush() {
            return this.done(this.flushInner());
        }
        setPresence(key, value) {
            if (!platformIdOk(key) || typeof value !== "string" || utf8Len(value) > PRESENCE_MAX_VALUE_BYTES)
                return this.done("refused");
            const known = Object.prototype.hasOwnProperty.call(this.presence, key);
            if (value === "") {
                if (!known)
                    return this.done("same");
                delete this.presence[key];
            }
            else {
                if (known && this.presence[key] === value)
                    return this.done("same");
                if (!known && Object.keys(this.presence).length >= PRESENCE_MAX_KEYS)
                    return this.done("refused");
                this.presence[key] = value;
            }
            if (this.online)
                this.send(["set_presence", key, value]);
            return this.done("ok");
        }
        clearPresence() {
            if (Object.keys(this.presence).length === 0)
                return this.done("same");
            this.presence = {};
            if (this.online)
                this.send(["clear_presence"]);
            return this.done("ok");
        }
        /** The save code calls this after its atomic write succeeded; path is relative to the user-data folder. */
        saved(path) {
            const part = cloudPartition(path);
            if (part === "cloud" && this.cloud === "api") {
                if (this.online)
                    this.send(["cloud_write", path]);
                else if (!this.pendingCloud.includes(path))
                    this.pendingCloud.push(path);
            }
            return this.done(part);
        }
        connect(remote) {
            this.online = true;
            const ru = Array.isArray(remote.unlocked) ? remote.unlocked : [];
            for (const id of ru) {
                if (typeof id !== "string")
                    continue;
                if (this.achDefs.has(id) && !this.unlocked.includes(id))
                    this.unlocked.push(id);
                const i = this.pendingUnlocks.indexOf(id);
                if (i >= 0)
                    this.pendingUnlocks.splice(i, 1);
            }
            const rs = isObject(remote.stats) ? remote.stats : {};
            for (const s of this.defs.stats) {
                const r0 = has(rs, s.id) ? rs[s.id] : undefined;
                if (!numOk(r0) || (s.type === "int" && !whole(r0)))
                    continue;
                const r = clampStat(s, r0);
                const old = this.stats[s.id];
                const pend = this.pendingStats.includes(s.id);
                let now;
                if (s.increment_only) {
                    if (r >= old && pend)
                        this.pendingStats.splice(this.pendingStats.indexOf(s.id), 1);
                    now = Math.max(old, r);
                }
                else {
                    now = pend ? old : r;
                }
                this.stats[s.id] = now;
                this.check(s.id, old, now, false);
            }
            this.flushInner();
            if (this.online)
                for (const [k, v] of this.presenceList())
                    this.send(["set_presence", k, v]);
            return this.done(this.online ? "online" : "failed");
        }
        disconnect() {
            this.online = false;
            return this.done("offline");
        }
        /** Testing only: refused offline (a reset is never queued). */
        resetAll() {
            if (!this.online)
                return this.done("offline");
            this.resetLocal();
            this.send(["reset_all_stats", true]);
            return this.done("reset");
        }
    }
    /** platform_state.json text (null or "" = no file) -> the state and the number of problems. */
    function platformStateLoad(defs, text) {
        const p = new Platform(defs);
        if (!text)
            return { state: p.state(), problems: 0 };
        let raw;
        try {
            raw = JSON.parse(text);
        }
        catch {
            return { state: p.state(), problems: 1 };
        }
        if (!isObject(raw) || raw.format !== PLATFORM_FORMAT || raw.version !== PLATFORM_STATE_VERSION)
            return { state: p.state(), problems: 1 };
        let problems = 0;
        const list = (v) => {
            if (Array.isArray(v))
                return v;
            if (v !== undefined && v !== null)
                problems++;
            return [];
        };
        const dict = (v) => {
            if (isObject(v))
                return v;
            if (v !== undefined && v !== null)
                problems++;
            return {};
        };
        for (const id of list(raw.unlocked)) {
            if (typeof id === "string" && p.achDefs.has(id) && !p.unlocked.includes(id))
                p.unlocked.push(id);
            else
                problems++;
        }
        const st = dict(raw.stats);
        for (const sid of Object.keys(st)) {
            const s = p.statDefs.get(sid);
            const v = st[sid];
            if (!s || !numOk(v) || (s.type === "int" && !whole(v))) {
                problems++;
                continue;
            }
            p.stats[sid] = clampStat(s, v);
        }
        const pending = dict(raw.pending);
        for (const sid of list(pending.stats)) {
            if (typeof sid === "string" && p.statDefs.has(sid) && !p.pendingStats.includes(sid))
                p.pendingStats.push(sid);
            else
                problems++;
        }
        for (const id of list(pending.unlocks)) {
            if (typeof id === "string" && p.unlocked.includes(id) && !p.pendingUnlocks.includes(id))
                p.pendingUnlocks.push(id);
            else
                problems++;
        }
        for (const path of list(pending.cloud)) {
            if (typeof path === "string" && cloudPartition(path) === "cloud" && !p.pendingCloud.includes(path))
                p.pendingCloud.push(path);
            else
                problems++;
        }
        return { state: p.state(), problems };
    }
    /** The game-facing service the shell owns: the rules, the backend, and the cached local state file. */
    class PlatformService {
        store;
        backend;
        platform;
        /** False without data/achievements.json (or with an empty one): nothing is ever written. */
        active;
        lastWritten;
        constructor(store, achievementsText, backend = new NullBackend(), cloud = CLOUD_MODE) {
            this.store = store;
            this.backend = backend;
            const { defs, problems } = achievementsLoad(achievementsText);
            if (problems > 0)
                Log.warn("platform", `data/achievements.json: ${problems} problem(s), those entries were dropped`);
            this.active = defs.stats.length > 0 || defs.achievements.length > 0;
            this.platform = new Platform(defs, backend, false, cloud);
            let stored = null;
            if (this.active) {
                try {
                    stored = store.read(PLATFORM_STATE_FILE);
                }
                catch {
                    stored = null;
                }
                const loaded = platformStateLoad(defs, stored);
                if (loaded.problems > 0)
                    Log.warn("platform", `${PLATFORM_STATE_FILE}: ${loaded.problems} problem(s), the store's copy wins`);
                this.platform.restore(loaded.state);
            }
            this.lastWritten = stored ?? "";
            if (backend.available())
                this.platform.connect(backend.remote());
            this.persist();
        }
        /** Writes the state file when it changed (never throws: a full store must not stop the game). */
        persist() {
            if (!this.active)
                return;
            const text = JSON.stringify(this.platform.state(), null, 1) + "\n";
            if (text === this.lastWritten)
                return;
            try {
                atomicWrite(this.store, PLATFORM_STATE_FILE, text, { backup: false });
                this.lastWritten = text;
            }
            catch (err) {
                Log.warn("platform", `${PLATFORM_STATE_FILE} not written: ${String(err)}`);
            }
        }
        after(r) {
            this.persist();
            return r.out;
        }
        unlock(id) {
            return this.after(this.platform.unlock(id));
        }
        setStat(id, v) {
            return this.after(this.platform.setStat(id, v));
        }
        addStat(id, d) {
            return this.after(this.platform.addStat(id, d));
        }
        /** At checkpoints: level end, pause, quit. */
        flush() {
            return this.after(this.platform.flush());
        }
        setPresence(key, value) {
            return this.after(this.platform.setPresence(key, value));
        }
        clearPresence() {
            return this.after(this.platform.clearPresence());
        }
        /** After an atomic save: its cloud partition (and, in api mode, the cloud write or its queue). */
        saved(path) {
            return this.after(this.platform.saved(path));
        }
        /** The store overlay opened or closed over `screen`: "pause" means open the pause menu. */
        overlay(active, screen) {
            return overlayAction(active, screen);
        }
        /** Each frame (the null backend does nothing). */
        update() {
            this.backend.update?.();
        }
    }

    // ---- stores for the state file ---------------------------------------------------
    /** In memory (tests, and a browser that blocks storage). */
    class MemoryStore {
        files = new Map();
        read(name) { return this.files.has(name) ? this.files.get(name) : null; }
        write(name, text) { this.files.set(name, text); }
        rename(from, to) { this.files.set(to, this.files.get(from)); this.files.delete(from); }
    }

    /** MZ's save folder on desktop (NW.js: Node's fs), localStorage in a browser. */
    function mzStore() {
        const local = typeof StorageManager !== "undefined" && StorageManager.isLocalMode && StorageManager.isLocalMode();
        if (local && typeof require === "function") {
            const fs = require("fs");
            const dir = StorageManager.fileDirectoryPath();
            const full = (name) => dir + name;
            return {
                read: (name) => (fs.existsSync(full(name)) ? fs.readFileSync(full(name), "utf8") : null),
                write: (name, text) => { if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true }); fs.writeFileSync(full(name), text, "utf8"); },
                rename: (from, to) => fs.renameSync(full(from), full(to)),
            };
        }
        try {
            const ls = globalThis.localStorage;
            const key = (name) => `kit ${name}`;
            return {
                read: (name) => ls.getItem(key(name)),
                write: (name, text) => ls.setItem(key(name), text),
                rename: (from, to) => { ls.setItem(key(to), ls.getItem(key(from))); ls.removeItem(key(from)); },
            };
        } catch {
            return new MemoryStore();
        }
    }

    /** The screen word overlayAction needs for MZ's current scene: the map is "play", anything else is not. */
    function sceneScreen(scene) {
        if (typeof Scene_Map !== "undefined" && scene instanceof Scene_Map) return "play";
        return scene && scene.constructor ? scene.constructor.name : "none";
    }

    const GamePlatform = {
        PLATFORM_FORMAT, PLATFORM_STATE_VERSION, PLATFORM_STATE_FILE, PLATFORM_ID_MAX, STAT_TYPES, PRESENCE_MAX_KEYS,
        PRESENCE_MAX_VALUE_BYTES, CLOUD_MODES, CLOUD_LOCAL_NAMES, CLOUD_LOCAL_SUFFIXES, CLOUD_LOCAL_DIRS,
        OVERLAY_PAUSE_SCREENS, CLOUD_MODE, ACHIEVEMENTS_URL: "data/achievements.json",
        platformIdOk, statInitial, achievementsLoad, cloudPartition, overlayAction, NullBackend, Platform,
        platformStateLoad, PlatformService, MemoryStore, sceneScreen,
        /** The live service (MZ): a service with no achievements until data/achievements.json has loaded. */
        service: null,
        /** A store overlay opened (true) or closed: over the map it asks for MZ's menu; closing never resumes. */
        onOverlay(active) {
            const scene = typeof SceneManager !== "undefined" ? SceneManager._scene : null;
            if (GamePlatform.service.overlay(active, sceneScreen(scene)) === "pause") scene.menuCalling = true;
        },
    };

    // ---- the MZ glue (only inside RPG Maker MZ) ------------------------------------------
    if (typeof SceneManager !== "undefined" && typeof DataManager !== "undefined" && typeof Scene_Menu !== "undefined") {
        const store = mzStore();
        GamePlatform.service = new PlatformService(store, null);
        // data/achievements.json is optional: a missing file keeps the service that does nothing
        const xhr = new XMLHttpRequest();
        xhr.open("GET", GamePlatform.ACHIEVEMENTS_URL);
        xhr.overrideMimeType("application/json");
        xhr.onload = () => {
            if (xhr.status < 400 && xhr.responseText) GamePlatform.service = new PlatformService(store, xhr.responseText);
        };
        xhr.onerror = () => {};
        xhr.send();

        const updateMain = SceneManager.updateMain;
        SceneManager.updateMain = function () {
            updateMain.call(this);
            GamePlatform.service.update();
        };
        const menuStart = Scene_Menu.prototype.start;
        Scene_Menu.prototype.start = function () {
            menuStart.call(this);
            GamePlatform.service.flush(); // MZ's menu is the pause menu: a checkpoint (docs/PLATFORM.md)
        };
        const terminate = SceneManager.terminate;
        SceneManager.terminate = function () {
            GamePlatform.service.flush();
            terminate.call(this);
        };
        const saveGame = DataManager.saveGame;
        DataManager.saveGame = function (savefileId) {
            const name = `save/${this.makeSavename(savefileId)}.rmmzsave`;
            return saveGame.call(this, savefileId).then((r) => {
                GamePlatform.service.saved(name);
                GamePlatform.service.flush();
                return r;
            });
        };
    } else {
        GamePlatform.service = new PlatformService(new MemoryStore(), null);
    }

    // Both, not either: MZ's desktop test play (NW.js) may define `module` too, and the plugins need the global
    globalThis.GamePlatform = GamePlatform;                                                       // RPG Maker MZ
    if (typeof module === "object" && module && module.exports) module.exports = GamePlatform;    // Node (tests)
})();

// {{FOOTER}}
