// ---------------------------------------------------------------------------
// platform.golden.test.ts
// Purpose : Runs every case of data/golden/platform.json through src/core/platform.ts (achievements and stats,
//           rich presence, the overlay's pause hook, cloud saves, the state file, the null backend), then checks
//           the PlatformService the shell owns: the cached state file, the save hook, no file without
//           achievements.
// Usage   : python tools/dev.py test
// Notes   : One test per case. A case type this file does not know fails, so a new vector type added to
//           tools/golden_vectors.py cannot be skipped silently. Expected values come only from the JSON. A step's
//           calls are what the Platform sent to its backend during that step; "fail_store" is the null backend's
//           hook (its next store_stats fails).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import {
  CLOUD_LOCAL_DIRS,
  CLOUD_LOCAL_NAMES,
  CLOUD_LOCAL_SUFFIXES,
  CLOUD_MODES,
  NullBackend,
  OVERLAY_PAUSE_SCREENS,
  Platform,
  PlatformService,
  PLATFORM_FORMAT,
  PLATFORM_ID_MAX,
  PLATFORM_STATE_FILE,
  PLATFORM_STATE_VERSION,
  PRESENCE_MAX_KEYS,
  PRESENCE_MAX_VALUE_BYTES,
  STAT_TYPES,
  achievementsLoad,
  cloudPartition,
  overlayAction,
  platformStateLoad,
  type Call,
  type Out,
} from "../src/core/platform";
import { MemoryStore } from "../src/core/textStore";
import { SaveStore } from "../src/core/saveStore";
import { expectClose, loadGolden, type GoldenCase } from "./helpers/golden";

const golden = loadGolden("platform.json");
const TOL = golden.tolerance;

function runStep(p: Platform, nb: NullBackend, op: any[]): Out | { out: null; calls: Call[] } {
  const [kind, ...args] = op;
  switch (kind) {
    case "fail_store":
      nb.failStores += 1;
      return { out: null, calls: [] };
    case "overlay":
      return { out: overlayAction(args[0], args[1]), calls: [] };
    case "unlock":
      return p.unlock(args[0]);
    case "set_stat":
      return p.setStat(args[0], args[1]);
    case "add_stat":
      return p.addStat(args[0], args[1]);
    case "flush":
      return p.flush();
    case "set_presence":
      return p.setPresence(args[0], args[1]);
    case "clear_presence":
      return p.clearPresence();
    case "saved":
      return p.saved(args[0]);
    case "connect":
      return p.connect(args[0]);
    case "disconnect":
      return p.disconnect();
    case "reset_all":
      return p.resetAll();
    default:
      throw new Error(`unknown step ${kind}`);
  }
}

const RUNNERS: Record<string, (c: GoldenCase) => void> = {
  platform_format: (c) => {
    expectClose(
      {
        state_format: PLATFORM_FORMAT,
        state_file: PLATFORM_STATE_FILE,
        state_version: PLATFORM_STATE_VERSION,
        id_max: PLATFORM_ID_MAX,
        stat_types: STAT_TYPES,
        presence_max_keys: PRESENCE_MAX_KEYS,
        presence_max_value_bytes: PRESENCE_MAX_VALUE_BYTES,
        cloud_modes: CLOUD_MODES,
        cloud_local_names: CLOUD_LOCAL_NAMES,
        cloud_local_suffixes: CLOUD_LOCAL_SUFFIXES,
        cloud_local_dirs: CLOUD_LOCAL_DIRS,
        overlay_pause_screens: OVERLAY_PAUSE_SCREENS,
      },
      Object.fromEntries(Object.entries(c).filter(([k]) => k !== "type" && k !== "name")),
      TOL,
      "format",
    );
  },
  achievements_load: (c) => {
    c.points.forEach(([name, text, defs, problems]: [string, string | null, unknown, number]) => {
      const r = achievementsLoad(text);
      expectClose(r.defs, defs, TOL, `${name}: defs`);
      expectClose(r.problems, problems, TOL, `${name}: problems`);
    });
  },
  cloud_partition: (c) => {
    c.points.forEach(([path, want]: [string, string]) => expectClose(cloudPartition(path), want, TOL, `"${path}"`));
  },
  overlay: (c) => {
    c.points.forEach(([active, screen, want]: [boolean, string, string]) => expectClose(overlayAction(active, screen), want, TOL, `${active} ${screen}`));
  },
  platform_script: (c) => {
    const nb = new NullBackend();
    const p = new Platform(c.defs, nb, c.online, c.cloud);
    c.steps.forEach((s: any, i: number) => {
      const r = runStep(p, nb, s.op);
      const where = `step ${i} ${JSON.stringify(s.op)}`;
      expectClose(r.out, s.out, TOL, `${where}: out`);
      expectClose(r.calls, s.calls, TOL, `${where}: calls`);
      expectClose(p.state(), s.state, TOL, `${where}: state`);
      expectClose(p.presenceList(), s.presence, TOL, `${where}: presence`);
      expectClose(p.online, s.online, TOL, `${where}: online`);
    });
  },
  platform_state_load: (c) => {
    c.points.forEach(([name, text, state, problems]: [string, string | null, unknown, number]) => {
      const r = platformStateLoad(c.defs, text);
      expectClose(r.state, state, TOL, `${name}: state`);
      expectClose(r.problems, problems, TOL, `${name}: problems`);
    });
  },
  null_backend: (c) => {
    const nb = new NullBackend();
    c.sends.forEach(([call, ok, remote, presence, cloud]: [Call, boolean | null, unknown, unknown, unknown], i: number) => {
      let got: boolean | null = null;
      if (call.length === 1 && call[0] === "fail_next_store") nb.failStores += 1;
      else got = nb.send(call);
      const where = `send ${i} ${JSON.stringify(call)}`;
      expectClose(got, ok, TOL, `${where}: ok`);
      expectClose(nb.remote(), remote, TOL, `${where}: remote`);
      expectClose(Object.keys(nb.presence).sort().map((k) => [k, nb.presence[k]]), presence, TOL, `${where}: presence`);
      expectClose(nb.cloud, cloud, TOL, `${where}: cloud`);
    });
    expectClose(nb.calls, c.calls, TOL, "calls");
  },
};

describe("platform.json golden vectors", () => {
  for (const c of golden.cases) {
    it(`${c.type}: ${c.name}`, () => {
      const run = RUNNERS[c.type];
      if (!run) throw new Error(`no runner for case type "${c.type}": add one to this file`);
      run(c);
    });
  }
});

const SAMPLE = JSON.stringify({
  stats: [{ id: "kills", type: "int", max: 100, increment_only: true }],
  achievements: [{ id: "first", name: "First" }, { id: "kills_10", name: "Ten", stat: "kills", threshold: 10 }],
});

describe("PlatformService (the shell's half)", () => {
  it("writes nothing and answers unknown without data/achievements.json", () => {
    const store = new MemoryStore();
    const ps = new PlatformService(store, null);
    expect(ps.active).toBe(false);
    expect(ps.unlock("first")).toBe("unknown");
    expect(ps.flush()).toBe("nothing");
    expect(ps.saved("save_1.json")).toBe("cloud");
    expect([...store.files.keys()]).toEqual([]);
  });

  it("caches the local state and reloads it on the next start", () => {
    const store = new MemoryStore();
    const nb = new NullBackend();
    const ps = new PlatformService(store, SAMPLE, nb);
    expect(ps.addStat("kills", 12)).toBe("ok");
    expect(ps.unlock("first")).toBe("unlocked");
    const saved = JSON.parse(store.read(PLATFORM_STATE_FILE) ?? "{}");
    expect(saved.unlocked).toEqual(["kills_10", "first"]);
    expect(saved.stats.kills).toBe(12);
    const again = new PlatformService(store, SAMPLE, new NullBackend());
    expect(again.platform.unlocked).toEqual(["kills_10", "first"]);
    expect(again.unlock("first")).toBe("already");
    expect(store.read(PLATFORM_STATE_FILE + ".tmp")).toBeNull();
  });

  it("the save store calls saved() after its atomic write", () => {
    const store = new MemoryStore();
    const ps = new PlatformService(store, SAMPLE, new NullBackend(), "api");
    const seen: string[] = [];
    const saves = new SaveStore(store, (p) => {
      seen.push(p);
      ps.saved(p);
    });
    saves.save(1, { level: 1 });
    expect(seen).toEqual(["save_1.json"]);
    expect((ps.backend as NullBackend).cloud).toEqual(["save_1.json"]);
  });

  it("an available backend is used without data/achievements.json (presence needs no achievements)", () => {
    const nb = new NullBackend();
    const ps = new PlatformService(new MemoryStore(), null, nb);
    expect(ps.setPresence("status", "Menu")).toBe("ok");
    expect(nb.calls).toEqual([["set_presence", "status", "Menu"]]);
  });

  it("a store that fails after it was accepted goes back on the queue, offline", () => {
    const nb = new NullBackend();
    const late: Call[][] = [];
    const backend = Object.assign(nb, { takeStoreFailure: () => late.shift() ?? null });
    const ps = new PlatformService(new MemoryStore(), SAMPLE, backend);
    expect(ps.addStat("kills", 12)).toBe("ok"); // kills_10 unlocks and flushes
    late.push([["set_stat", "kills", 12], ["set_achievement", "kills_10"]]);
    ps.update();
    expect(ps.platform.online).toBe(false);
    expect(ps.platform.state().pending).toEqual({ stats: ["kills"], unlocks: ["kills_10"], cloud: [] });
  });

  it("the overlay pauses only over gameplay", () => {
    const ps = new PlatformService(new MemoryStore(), null);
    expect(ps.overlay(true, "play")).toBe("pause");
    expect(ps.overlay(true, "juice")).toBe("none");
    expect(ps.overlay(false, "pause")).toBe("none");
  });
});
