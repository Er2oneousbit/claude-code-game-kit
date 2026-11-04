// ---------------------------------------------------------------------------
// musicDirector.ts
// Purpose : The adaptive-music rules of data/music.json, with no Web Audio in them (Vitest runs them against
//           data/golden/music.json): the sample grid, loop points, where playback is, the next beat / bar / phrase /
//           loop end, which transition rule applies, and the plan for a change (when, fade, stinger, entry point).
// Usage   : const p = planTransition(music, "explore", sinceSample, entrySample, "combat", nowSample)
//           p.switch_at, p.from_stop_at, p.to_start_at, p.to_offset, p.stinger_at  (all in samples)
// Notes   : A port of tools/audio/wavesmith/music.py (the reference): every value is a whole number of samples and must match
//           the golden file exactly. Beat k starts at floor(k * 60 * rate / bpm + 0.5): Math.round is not used, it
//           rounds -0.5 differently from Python and is not the rule. Plain functions only (type-stripping safe).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export type Quantize = "immediate" | "beat" | "bar" | "phrase" | "loop_end";
export interface MusicTrack { bpm: number; beats_per_bar?: number; bars: number; loop_start_bar?: number; stems: Record<string, string> }
export interface MusicRule { from?: string; to?: string; quantize?: Quantize; fade_ms?: number; sync?: boolean; stinger?: string | null; phrase_bars?: number }
export interface MusicFile {
  version: number; sample_rate: number; start?: string;
  tracks: Record<string, MusicTrack>;
  stingers?: Record<string, { file: string; bars: number }>;
  transitions?: MusicRule[];
  default_transition?: MusicRule;
}
export interface MusicPlan {
  switch_at: number; from_stop_at: number; fade: number; to_offset: number; to_start_at: number;
  stinger: string | null; stinger_at: number | null;
}

const DEFAULT_RULE: MusicRule = { quantize: "bar", fade_ms: 0, sync: false };
const bpbOf = (t: { beats_per_bar?: number }): number => t.beats_per_bar ?? 4;

export function beatSample(k: number, bpm: number, rate: number): number {
  return Math.floor((k * 60 * rate) / bpm + 0.5);
}

export function barSample(b: number, t: MusicTrack, rate: number): number {
  return beatSample(b * bpbOf(t), t.bpm, rate);
}

export function barIndexAt(sample: number, t: MusicTrack, rate: number): number {
  let b = Math.floor((sample * t.bpm) / (60 * rate * bpbOf(t)));
  while (barSample(b + 1, t, rate) <= sample) b++;
  while (b > 0 && barSample(b, t, rate) > sample) b--;
  return b;
}

/** [loop start, loop end) in samples; bars before loop_start_bar are an intro that plays once. */
export function loopPoints(t: MusicTrack, rate: number): [number, number] {
  return [barSample(t.loop_start_bar ?? 0, t, rate), barSample(t.bars, t, rate)];
}

export function position(t: MusicTrack, rate: number, since: number, now: number, entry = 0): number {
  let p = now - since + entry;
  const [start, end] = loopPoints(t, rate);
  if (p >= end) p = start + ((p - start) % (end - start));
  return p;
}

export function nextBoundary(t: MusicTrack, rate: number, p: number, quantize: Quantize, phraseBars = 4): number {
  if (quantize === "immediate") return p;
  const [, end] = loopPoints(t, rate);
  if (quantize === "loop_end") return end;
  const bpb = bpbOf(t);
  // a typo in music.json must not mean "phrase" (the type does not reach the data a game loads)
  const step = quantize === "beat" ? 1 : quantize === "bar" ? bpb : quantize === "phrase" ? bpb * phraseBars : 0;
  if (step === 0) throw new Error(`unknown quantize ${quantize}`);
  let k = Math.floor((p * t.bpm) / (60 * rate));
  while (beatSample(k, t.bpm, rate) < p) k++;
  while (k % step) k++;
  return Math.min(beatSample(k, t.bpm, rate), end);
}

/** Exact pair, then from "*", then to "*", then the file's default_transition, then the built-in default. */
export function ruleFor(m: MusicFile, from: string, to: string): MusicRule {
  const rules = m.transitions ?? [];
  for (const [f, t] of [[from, to], ["*", to], [from, "*"]]) {
    const r = rules.find((x) => x.from === f && x.to === t);
    if (r) return { ...DEFAULT_RULE, ...(m.default_transition ?? {}), ...r };
  }
  return { ...DEFAULT_RULE, ...(m.default_transition ?? {}) };
}

export function planTransition(m: MusicFile, from: string, since: number, entry: number, to: string, now: number): MusicPlan {
  const rate = m.sample_rate;
  const a = m.tracks[from], b = m.tracks[to];
  if (!a || !b) throw new Error(`unknown track ${!a ? from : to}`);
  const rule = ruleFor(m, from, to);
  const p = position(a, rate, since, now, entry);
  const boundary = nextBoundary(a, rate, p, rule.quantize ?? "bar", rule.phrase_bars ?? 4);
  const switchAt = now + (boundary - p);
  const fade = Math.floor(((rule.fade_ms ?? 0) * rate) / 1000 + 0.5);
  const out: MusicPlan = { switch_at: switchAt, from_stop_at: switchAt + fade, fade, to_offset: 0, to_start_at: switchAt,
                           stinger: rule.stinger ?? null, stinger_at: null };
  if (rule.stinger) {
    const st = m.stingers?.[rule.stinger];
    if (!st) throw new Error(`unknown stinger ${rule.stinger}`);
    out.stinger_at = switchAt;
    out.to_start_at = switchAt + beatSample(st.bars * bpbOf(b), b.bpm, rate);
  } else if (rule.sync && a.bpm === b.bpm && bpbOf(a) === bpbOf(b)) {
    out.to_offset = boundary - barSample(barIndexAt(boundary, a, rate), a, rate);
  }
  return out;
}
