// ---------------------------------------------------------------------------
// musicPlayer.ts
// Purpose : Plays data/music.json through Web Audio: each track's stems loop together on the bar grid, and a change
//           of track happens on the sample the music director plans (next beat, bar, phrase or loop end), with an
//           optional fade and stinger.
// Usage   : const music = new MusicPlayer(ctx, musicJson, buffers, player.bus("music"))  // buffers by file path
//           music.start("explore")                     // now; or music.start("explore", atSample)
//           music.request("combat")                    // returns the plan (samples on the context clock)
//           music.setStemGain("explore", "drums", 0)   // layers: fade a stem in or out (linear 0..1)
// Notes   : Works with AudioContext and OfflineAudioContext (the kit's Chromium check renders offline and finds every
//           switch on its planned sample). Times are samples on the context clock (ctx.currentTime * ctx.sampleRate);
//           music.json's sample_rate must equal the context's rate, or bar points would fall between samples (the
//           constructor refuses). A fade is a straight line in gain from switch_at to from_stop_at. Stems loop with
//           loopStart / loopEnd on the bar grid, so an intro plays once. Decisions live in src/core/musicDirector.ts.
//
// Pseudocode:
//   start(track, at): one looping source per stem -> stem gain -> track gain -> out; remember since / entry
//   request(to, now): plan = planTransition(...) -> old track: gain ramp to 0 by from_stop_at, stop there
//                     -> stinger source at stinger_at -> new track's stems start at to_start_at from to_offset
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { loopPoints, planTransition, type MusicFile, type MusicPlan } from "../core/musicDirector";

type Playing = { name: string; since: number; entry: number; gain: GainNode; sources: AudioBufferSourceNode[]; stems: Record<string, GainNode> };

export class MusicPlayer {
  private current: Playing | null = null;
  private readonly ctx: BaseAudioContext;
  private readonly data: MusicFile;
  private readonly buffers: Record<string, AudioBuffer>;
  private readonly out: AudioNode;
  private readonly rate: number;

  // plain fields, not parameter properties, so the file also runs type-stripped
  constructor(ctx: BaseAudioContext, data: MusicFile, buffers: Record<string, AudioBuffer>, out: AudioNode = ctx.destination) {
    if (data.sample_rate !== ctx.sampleRate) {
      throw new Error(`music.json says ${data.sample_rate} Hz but the audio context runs at ${ctx.sampleRate} Hz`);
    }
    this.ctx = ctx;
    this.data = data;
    this.buffers = buffers;
    this.out = out;
    this.rate = ctx.sampleRate;
  }

  /** The context clock in whole samples. */
  nowSample(): number {
    return Math.round(this.ctx.currentTime * this.rate);
  }

  get track(): string | null {
    return this.current?.name ?? null;
  }

  private buffer(file: string): AudioBuffer {
    const b = this.buffers[file];
    if (!b) throw new Error(`music file ${file} is not loaded`);
    return b;
  }

  private launch(name: string, at: number, entry: number): Playing {
    const t = this.data.tracks[name];
    if (!t) throw new Error(`unknown track ${name}`);
    const [ls, le] = loopPoints(t, this.rate);
    const gain = this.ctx.createGain();
    gain.connect(this.out);
    const sources: AudioBufferSourceNode[] = [];
    const stems: Record<string, GainNode> = {};
    for (const [stem, file] of Object.entries(t.stems)) {
      const src = this.ctx.createBufferSource();
      src.buffer = this.buffer(file);
      src.loop = true;
      src.loopStart = ls / this.rate;
      src.loopEnd = le / this.rate;
      const g = this.ctx.createGain();
      src.connect(g).connect(gain);
      src.start(at / this.rate, entry / this.rate);
      sources.push(src);
      stems[stem] = g;
    }
    return { name, since: at, entry, gain, sources, stems };
  }

  /** Starts a track (stopping nothing: call it once, then use request). */
  start(name: string, atSample = this.nowSample()): void {
    this.current = this.launch(name, atSample, 0);
  }

  /** Plans and schedules a change to `to`; returns the plan. Nothing happens when `to` is already playing. */
  request(to: string, nowSample = this.nowSample()): MusicPlan | null {
    const cur = this.current;
    if (!cur) {
      this.start(to, nowSample);
      return null;
    }
    if (cur.name === to) return null;
    const p = planTransition(this.data, cur.name, cur.since, cur.entry, to, nowSample);
    const g = cur.gain.gain;
    g.setValueAtTime(1, p.switch_at / this.rate);
    if (p.fade > 0) g.linearRampToValueAtTime(0, p.from_stop_at / this.rate);
    for (const s of cur.sources) s.stop(p.from_stop_at / this.rate);
    if (p.stinger && p.stinger_at !== null) {
      const st = this.ctx.createBufferSource();
      st.buffer = this.buffer(this.data.stingers![p.stinger].file);
      st.connect(this.out);
      st.start(p.stinger_at / this.rate);
    }
    this.current = this.launch(to, p.to_start_at, p.to_offset);
    return p;
  }

  /** A stem's level (linear 0..1), from `atSample` on (layers: add drums when the action starts). */
  setStemGain(track: string, stem: string, value: number, atSample = this.nowSample()): void {
    if (this.current?.name !== track) return;
    const g = this.current.stems[stem];
    if (!g) throw new Error(`track ${track} has no stem ${stem}`);
    g.gain.setValueAtTime(Math.min(1, Math.max(0, value)), atSample / this.rate);
  }
}
