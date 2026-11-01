// ---------------------------------------------------------------------------
// audioPlayer.ts
// Purpose : Plays what the AudioDirector decides through Web Audio: one gain node per bus (from
//           data/audio_events.json), a buffer source per voice at the chosen pitch and volume, stolen voices
//           stopped, and the ducking envelope applied to the target buses.
// Usage   : const player = new AudioPlayer(ctx, eventsJson, buffers)   // buffers: { "step_0.wav": AudioBuffer, ... }
//           player.play("step_stone")              // now (ctx.currentTime), or player.play(name, atMs) to schedule
//           each frame: player.update()            // ducking; or player.update(atMs) when scheduling ahead
//           settings: player.applySettings(shell.settings.audio)   // the volume sliders (audioAccess.ts)
//           player.setBusVolume("music", -6)      // a bus's own level in dB (normally from the events file)
// Notes   : Works with AudioContext and OfflineAudioContext (the kit's Chromium check renders offline and measures
//           the duck envelope, pitches and voice cap from the output). Bus routing: each bus connects to its
//           parent, master to ctx.destination (or to `out`, a node the caller passes). Decisions, randomness and
//           timing rules live in src/core/audioDirector.ts; this file only turns them into nodes.
//
// Pseudocode:
//   constructor: director + bus gain nodes wired child -> parent -> master -> out; lengths from the buffers
//   play(name, atMs): d = director.play -> stolen? stop its source at atMs -> source(buffer, playbackRate)
//                     -> voice gain -> bus; remember source by voice id
//   update(atMs): for each bus: gain = volume_db + duck_db, times the player's slider -> setValueAtTime at atMs
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { userBusGains, type AudioSliders } from "../core/audioAccess";
import { AudioDirector, type AudioEvent, type DuckRule, type PlayResult } from "../core/audioDirector";

export interface BusDef {
  parent?: string;
  volume_db?: number;
}

export interface EventsFile {
  version: number;
  seed?: number;
  buses: Record<string, BusDef>;
  ducking?: DuckRule[];
  events: Record<string, Omit<AudioEvent, "lengths_ms">>;
}

export const dbToGain = (db: number): number => Math.pow(10, db / 20);

export class AudioPlayer {
  readonly director: AudioDirector;
  private readonly buses: Record<string, GainNode> = {};
  private readonly volumes: Record<string, number> = {};
  private user: Record<string, number> = {};
  private readonly sources = new Map<number, AudioBufferSourceNode>();
  private readonly files: Record<string, string[]> = {};
  private readonly ctx: BaseAudioContext;
  private readonly data: EventsFile;
  private readonly buffers: Record<string, AudioBuffer>;

  // busOut: tests route chosen buses to their own output channel instead of the parent (plain fields, not
  // parameter properties, so the file also runs type-stripped)
  constructor(ctx: BaseAudioContext, data: EventsFile, buffers: Record<string, AudioBuffer>,
              out: AudioNode = ctx.destination, busOut?: Record<string, AudioNode>) {
    this.ctx = ctx;
    this.data = data;
    this.buffers = buffers;
    for (const name of Object.keys(data.buses)) {
      this.buses[name] = ctx.createGain();
      this.volumes[name] = data.buses[name].volume_db ?? 0;
    }
    for (const [name, def] of Object.entries(data.buses)) {
      const dest = busOut?.[name] ?? (name === "master" ? out : this.buses[def.parent ?? "master"]);
      this.buses[name].connect(dest);
    }
    const events: Record<string, AudioEvent> = {};
    for (const [name, ev] of Object.entries(data.events)) {
      this.files[name] = ev.files;
      events[name] = { ...ev, lengths_ms: ev.files.map((f) => this.buffer(f).duration * 1000) };
    }
    this.director = new AudioDirector({ seed: data.seed, events, ducking: data.ducking });
    this.update(0);
  }

  private buffer(file: string): AudioBuffer {
    const b = this.buffers[file];
    if (!b) throw new Error(`audio file ${file} is not loaded`);
    return b;
  }

  private nowMs(): number {
    return this.ctx.currentTime * 1000;
  }

  /** Plays an event now, or at atMs on the context clock. Returns the director's decision. */
  play(name: string, atMs = this.nowMs()): PlayResult {
    const d = this.director.play(name, atMs);
    if (d.result !== "played") return d;
    if (d.stolen !== null) {
      this.sources.get(d.stolen)?.stop(atMs / 1000);
      this.sources.delete(d.stolen);
    }
    const src = this.ctx.createBufferSource();
    src.buffer = this.buffer(this.files[name][d.variant]);
    src.playbackRate.value = d.pitch_ratio;
    const gain = this.ctx.createGain();
    gain.gain.value = dbToGain(d.gain_db);
    src.connect(gain).connect(this.buses[this.data.events[name].bus]);
    src.start(atMs / 1000);
    src.onended = () => this.sources.delete(d.voice);
    this.sources.set(d.voice, src);
    return d;
  }

  /** Applies bus volumes and ducking at atMs (call every frame, or at a fine step when scheduling ahead). */
  update(atMs = this.nowMs()): void {
    const duck = this.director.duck(atMs);
    for (const [bus, node] of Object.entries(this.buses)) {
      node.gain.setValueAtTime(dbToGain(this.volumes[bus] + (duck[bus] ?? 0)) * (this.user[bus] ?? 1), atMs / 1000);
    }
  }

  /** The settings screen's volume sliders (linear 0..1); takes effect at the next update(). */
  applySettings(sliders: AudioSliders): void {
    this.user = userBusGains(this.data.buses, sliders);
  }

  setBusVolume(bus: string, db: number): void {
    if (!(bus in this.volumes)) throw new Error(`unknown bus ${bus}`);
    this.volumes[bus] = db;
  }
}

// {{FOOTER}}
