// ---------------------------------------------------------------------------
// musicPlayer.test.ts
// Purpose : The music player's scheduling (src/shell/musicPlayer.ts): a change asked back before its switch is
//           undone, as Godot's player does (the new track never sounds, a stinger that has not started goes with it,
//           the old track keeps its gain and plays on: nothing restarts); a change asked for after the switch began
//           is planned as a second change, from where the new track enters.
// Usage   : python tools/dev.py test
// Notes   : A stand-in audio context records what the player schedules (starts, stops, gain automation), so no
//           audio device or browser is needed. The last stop() call is the one that counts, as in Web Audio. The
//           kit also rendered these cases in headless Chromium (OfflineAudioContext): each matched, on every sample,
//           a render in which the asked-back change was never asked for.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import type { MusicFile } from "../src/core/musicDirector";
import { MusicPlayer } from "../src/shell/musicPlayer";

const RATE = 48000; // 120 BPM in 4/4: a bar is 96000 samples

class FakeParam {
  events: { type: string; value: number; time: number }[] = [];
  setValueAtTime(value: number, time: number) { this.events.push({ type: "set", value, time }); return this; }
  linearRampToValueAtTime(value: number, time: number) { this.events.push({ type: "ramp", value, time }); return this; }
  cancelScheduledValues(time: number) { this.events = this.events.filter((e) => e.time < time); return this; }
}

class FakeNode {
  connected = true;
  connect<T>(n: T): T { return n; }
  disconnect() { this.connected = false; }
}

class FakeGain extends FakeNode { gain = new FakeParam(); }

class FakeSource extends FakeNode {
  buffer: unknown = null;
  loop = false;
  loopStart = 0;
  loopEnd = 0;
  startAt: number | null = null;
  stopAt: number | null = null;
  start(when = 0) { this.startAt = when; }
  stop(when = 0) { this.stopAt = when; }                 // the last call wins, as in Web Audio
  /** Sounds at some point: started, connected, and not stopped before (or at) its start. */
  get heard(): boolean { return this.startAt !== null && this.connected && (this.stopAt === null || this.stopAt > this.startAt); }
}

class FakeContext {
  sampleRate = RATE;
  currentTime = 0;
  destination = new FakeNode();
  sources: FakeSource[] = [];
  createGain() { return new FakeGain(); }
  createBufferSource() { const s = new FakeSource(); this.sources.push(s); return s; }
}

const MUSIC = {
  version: 1, sample_rate: RATE,
  tracks: { explore: { bpm: 120, bars: 2, loop_start_bar: 1, stems: { pads: "pads", drums: "drums" } },
            combat: { bpm: 120, bars: 1, stems: { full: "combat" } } },
  stingers: { alarm: { file: "alarm", bars: 1 } },
  transitions: [{ from: "explore", to: "combat", quantize: "bar", fade_ms: 500 },
                { from: "combat", to: "explore", quantize: "beat", fade_ms: 0, stinger: "alarm" }],
} as unknown as MusicFile;

function setup() {
  const ctx = new FakeContext();
  const buffers = { pads: {}, drums: {}, combat: {}, alarm: {} } as unknown as Record<string, AudioBuffer>;
  const player = new MusicPlayer(ctx as unknown as BaseAudioContext, MUSIC, buffers);
  player.start("explore", 0);
  return { ctx, player, explore: [...ctx.sources] };
}

describe("MusicPlayer: a change asked back before its switch", () => {
  it("is undone: the old track plays on with its gain, the new one never sounds", () => {
    const { ctx, player, explore } = setup();
    const p = player.request("combat", 250000);
    expect(p?.switch_at).toBe(288000);
    const combat = ctx.sources.slice(explore.length);
    expect(combat.every((s) => s.heard)).toBe(true);                 // scheduled for the bar
    expect(player.request("explore", 260000)).toBeNull();          // explore is current again: nothing to plan
    expect(player.track).toBe("explore");
    expect(combat.some((s) => s.heard)).toBe(false);               // stopped before it ever started
    for (const s of explore) expect(s.stopAt).toBeGreaterThan(1e9); // its stop at the bar is undone
    expect(player.request("combat", 300000)?.switch_at).toBe(384000);   // and a later change plans as usual
  });

  it("drops the fade it planned and keeps a stinger that has not started from sounding", () => {
    const { ctx, player, explore } = setup();
    player.request("combat", 100000);                               // combat from the bar at 192000 (with a fade)
    const before = ctx.sources.length;
    const p = player.request("explore", 250000);                    // back with a stinger on the beat
    expect(p?.stinger_at).toBe(264000);
    const added = ctx.sources.slice(before);                       // the stinger and explore's stems
    expect(player.request("combat", 251000)).toBeNull();
    expect(player.track).toBe("combat");
    expect(added.some((s) => s.heard)).toBe(false);
    expect(explore.every((s) => s.stopAt === 192000 / RATE + 500 / 1000)).toBe(true);   // the first change stands
  });

  it("is a second change when the switch has begun, planned from where the new track enters", () => {
    const { player } = setup();
    player.request("combat", 100000);                               // switch at 192000
    const p = player.request("explore", 200000);                    // too late to undo
    expect(p).not.toBeNull();
    expect(p!.switch_at).toBeGreaterThanOrEqual(200000);
    expect(player.track).toBe("explore");
  });
});
