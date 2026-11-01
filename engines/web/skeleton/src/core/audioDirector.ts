// ---------------------------------------------------------------------------
// audioDirector.ts
// Purpose : Decides how each game sound plays: which file of the event (no back-to-back repeats), its pitch and
//           volume within the event's ranges, voice limits (steal the oldest or refuse), cooldowns, and how far
//           dialogue ducks the music and ambience buses. Data comes from data/audio_events.json.
// Usage   : const dir = new AudioDirector(eventsJson);           // { seed?, events, ducking? }
//           const d = dir.play("step_stone", nowMs);              // d.result: "played" | "cooldown" | "capped"
//           if (d.result === "played") player.start(event.files[d.variant], d.pitchRatio, d.gainDb, d.voice, d.stolen)
//           each frame: for (const [bus, db] of Object.entries(dir.duck(nowMs))) busGain(bus, db)
// Notes   : No Phaser or Web Audio import: this file only decides (Vitest runs it), audioPlayer.ts plays.
//           The spec is tools/audio/audio_events.py; every step of data/golden/audio.json must come out the same
//           (Park-Miller random source, no bit operations, fixed draw order: variant, pitch, volume; a rejected
//           play draws nothing). Calls must come in time order. lengths_ms per file: from the loaded buffers.
//
// Pseudocode:
//   play(e, t) -> drop finished voices -> cooldown? "cooldown" -> at max_voices: steal oldest or "capped"
//              -> variant by pick rule -> pitch -> volume -> new voice (ends at t + length / pitch ratio)
//   duck(t)    -> per ducking rule: walk the trigger bus's voice edges since the last call, ramp in dB
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
export const DEFAULT_MAX_VOICES = 8;
const PM_M = 2147483647; // Park-Miller modulus (2^31 - 1)
const PM_A = 16807;

export type Pick = "sequence" | "random" | "random_no_repeat" | "shuffle";

export interface AudioEvent {
  bus: string;
  files: string[];
  lengths_ms: number[];
  pick?: Pick;
  pitch_semitones?: [number, number];
  volume_db?: [number, number];
  max_voices?: number;
  steal?: "oldest" | "none";
  cooldown_ms?: number;
  caption?: string;
}

export interface DuckRule {
  trigger: string;
  targets: string[];
  depth_db: number;
  attack_ms?: number;
  release_ms?: number;
}

export interface DirectorParams {
  seed?: number;
  events: Record<string, AudioEvent>;
  ducking?: DuckRule[];
}

export type PlayResult =
  | { result: "cooldown" }
  | { result: "capped" }
  | {
      result: "played";
      variant: number;
      pitch_semitones: number;
      pitch_ratio: number;
      gain_db: number;
      voice: number;
      stolen: number | null;
      ends_ms: number;
    };

interface Voice {
  id: number;
  event: string;
  bus: string;
  start: number;
  end: number;
}

/** Park-Miller minimal standard generator: exact in doubles, so every language agrees. */
export class ParkMiller {
  s: number;
  constructor(seed: number) {
    this.s = mod(seed, PM_M) || 1;
  }
  next(): number {
    this.s = (this.s * PM_A) % PM_M;
    return (this.s - 1) / (PM_M - 1);
  }
}

/** Modulo that is never negative, like Python's and Lua's (JS % keeps the sign of the dividend). */
function mod(a: number, m: number): number {
  return ((a % m) + m) % m;
}

export function eventSeed(eventId: string, globalSeed: number): number {
  let h = 0;
  for (let i = 0; i < eventId.length; i++) h = (h * 31 + eventId.charCodeAt(i)) % PM_M; // ids are ASCII
  return (h + mod(globalSeed, PM_M) * 7919) % PM_M || 1;
}

export class AudioDirector {
  private readonly events: Record<string, AudioEvent>;
  private readonly ducking: DuckRule[];
  private readonly rng: Record<string, ParkMiller> = {};
  private voices: Voice[] = [];
  private history: Voice[] = []; // trigger-bus voices the ducking envelopes may still need
  private readonly triggers: Set<string>;
  private nextId = 1;
  private readonly lastPlay: Record<string, number> = {};
  private readonly lastVariant: Record<string, number> = {};
  private readonly bags: Record<string, number[]> = {};
  private readonly duckState: { gain: number; t: number }[];
  private now = 0;

  constructor(params: DirectorParams) {
    this.events = params.events;
    this.ducking = params.ducking ?? [];
    const seed = params.seed ?? 1;
    for (const name of Object.keys(this.events)) this.rng[name] = new ParkMiller(eventSeed(name, seed));
    this.duckState = this.ducking.map(() => ({ gain: 0, t: 0 }));
    this.triggers = new Set(this.ducking.map((r) => r.trigger));
  }

  private clock(t: number): void {
    if (t < this.now) throw new Error(`calls must come in time order (${t} ms after ${this.now} ms)`);
    this.now = t;
  }

  private pick(name: string, ev: AudioEvent, rng: ParkMiller): number {
    const n = ev.files.length;
    const last = this.lastVariant[name] ?? -1;
    const rule = ev.pick ?? "random_no_repeat";
    if (n === 1) return 0;
    if (rule === "sequence") return (last + 1) % n;
    if (rule === "random") return Math.min(Math.floor(rng.next() * n), n - 1);
    if (rule === "random_no_repeat") {
      if (last < 0) return Math.min(Math.floor(rng.next() * n), n - 1);
      const k = Math.min(Math.floor(rng.next() * (n - 1)), n - 2);
      return k >= last ? k + 1 : k;
    }
    let bag = this.bags[name] ?? [];
    if (bag.length === 0) {
      bag = Array.from({ length: n }, (_, i) => i);
      for (let i = n - 1; i > 0; i--) {
        const j = Math.min(Math.floor(rng.next() * (i + 1)), i);
        [bag[i], bag[j]] = [bag[j], bag[i]];
      }
      if (bag[0] === last) [bag[0], bag[1]] = [bag[1], bag[0]]; // never the same file twice across a refill
    }
    const idx = bag.shift() as number;
    this.bags[name] = bag;
    return idx;
  }

  play(name: string, t: number): PlayResult {
    this.clock(t);
    const ev = this.events[name];
    if (!ev) throw new Error(`unknown audio event ${name}`);
    this.voices = this.voices.filter((v) => v.end > t);
    const cooldown = ev.cooldown_ms ?? 0;
    if (cooldown && name in this.lastPlay && t - this.lastPlay[name] < cooldown) return { result: "cooldown" };
    const mine = this.voices.filter((v) => v.event === name);
    let stolen: number | null = null;
    if (mine.length >= (ev.max_voices ?? DEFAULT_MAX_VOICES)) {
      if ((ev.steal ?? "oldest") === "none") return { result: "capped" };
      const victim = mine.reduce((a, b) => (b.start < a.start || (b.start === a.start && b.id < a.id) ? b : a));
      victim.end = t; // it stops now (the ducking envelope sees that)
      this.voices = this.voices.filter((v) => v !== victim);
      stolen = victim.id;
    }
    const rng = this.rng[name];
    const idx = this.pick(name, ev, rng);
    const [lo, hi] = ev.pitch_semitones ?? [0, 0];
    const semis = lo === hi ? lo : lo + (hi - lo) * rng.next();
    const [vlo, vhi] = ev.volume_db ?? [0, 0];
    const gain = vlo === vhi ? vlo : vlo + (vhi - vlo) * rng.next();
    const ratio = Math.pow(2, semis / 12);
    const voice: Voice = { id: this.nextId++, event: name, bus: ev.bus, start: t, end: t + ev.lengths_ms[idx] / ratio };
    this.voices.push(voice);
    if (this.triggers.has(voice.bus)) this.history.push(voice);
    this.lastPlay[name] = t;
    this.lastVariant[name] = idx;
    return { result: "played", variant: idx, pitch_semitones: semis, pitch_ratio: ratio, gain_db: gain,
             voice: voice.id, stolen, ends_ms: voice.end };
  }

  /** Duck gain in dB per target bus at time t (every rule advanced to t). */
  duck(t: number): Record<string, number> {
    this.clock(t);
    const out: Record<string, number> = {};
    this.ducking.forEach((rule, i) => {
      const st = this.duckState[i];
      const mine = this.history.filter((v) => v.bus === rule.trigger);
      const edges = [...new Set(mine.flatMap((v) => [v.start, v.end]).filter((e) => st.t < e && e < t))].sort((a, b) => a - b);
      let gain = st.gain;
      let at = st.t;
      for (const edge of [...edges, t]) {
        const active = mine.some((v) => v.start <= at && at < v.end);
        gain = ramp(gain, active, rule, edge - at);
        at = edge;
      }
      st.gain = gain;
      st.t = t;
      for (const bus of rule.targets) out[bus] = Math.min(out[bus] ?? 0, gain);
    });
    // every rule now stands at t: voices that ended by then add no later edge, so they can go (results unchanged)
    this.history = this.history.filter((v) => v.end > t);
    return out;
  }
}

function ramp(gain: number, active: boolean, rule: DuckRule, dt: number): number {
  const depth = rule.depth_db;
  if (active) {
    if ((rule.attack_ms ?? 0) <= 0) return depth;
    return Math.max(depth, gain + (depth / (rule.attack_ms as number)) * dt);
  }
  if ((rule.release_ms ?? 0) <= 0) return 0;
  return Math.min(0, gain - (depth / (rule.release_ms as number)) * dt);
}

// {{FOOTER}}
