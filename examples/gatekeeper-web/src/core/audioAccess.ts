// ---------------------------------------------------------------------------
// audioAccess.ts
// Purpose : Audio accessibility rules with no Web Audio or DOM in them (Vitest runs them): which settings slider
//           turns which bus of data/audio_events.json up or down, and which arrow a directional caption gets when
//           the sound comes from off screen.
// Usage   : player.applySettings(settings.audio)                       // AudioPlayer calls userBusGains
//           userBusGains(events.buses, settings.audio)                  // { music: 0.8, sfx: 1, dialogue: 1, ... }
//           captionArrow(src.x - cam.midX, src.y - cam.midY, cam.width / 2, cam.height / 2)   // "" | "←" | "↗" ...
// Notes   : Sliders are linear 0..1 (settings.audio), as the settings screen shows them; a slider multiplies its
//           bus on top of the bus's volume_db and the ducking. A bus follows the slider named in SLIDER_FOR_BUS;
//           when one of its parent buses already follows the same slider it gets 1, so a slider never counts twice
//           (ambience under sfx). Buses without a slider (master's own children you invent) get 1 unless a parent has
//           one. The mono switch is not here: Web Audio downmixes at the destination (0.5 * (L + R), see app.ts).
//           Arrows: screen coordinates (y grows downwards), eight directions, nothing while the source is on screen
//           (Xbox Accessibility Guideline 104: indicate where an important off-screen sound comes from).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export type AudioSliders = { master: number; music: number; sfx: number; ui: number; voice: number };

// Bus name -> settings slider. Edit it when your audio_events.json uses other bus names.
export const SLIDER_FOR_BUS: Record<string, keyof AudioSliders> = {
  master: "master", music: "music", sfx: "sfx", ambience: "sfx", ui: "ui", dialogue: "voice", voice: "voice",
};

const clamp01 = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 1);

/** Linear gain per bus from the player's sliders (1 where no slider applies or a parent already applies it). */
export function userBusGains(buses: Record<string, { parent?: string }>, sliders: AudioSliders): Record<string, number> {
  const out: Record<string, number> = {};
  const names = Object.keys(buses);
  const parentOf = (b: string): string | undefined => buses[b]?.parent ?? (b === "master" ? undefined : "master");
  for (const name of names) {
    const slider = SLIDER_FOR_BUS[name];
    let inherited = false;
    // walk up the parents (at most one step per bus, so a cycle cannot hang)
    let p = parentOf(name);
    for (let n = 0; p !== undefined && n < names.length; n++, p = parentOf(p)) {
      if (slider !== undefined && SLIDER_FOR_BUS[p] === slider) inherited = true;
    }
    out[name] = slider === undefined || inherited ? 1 : clamp01(sliders[slider]);
  }
  return out;
}

const ARROWS = ["→", "↘", "↓", "↙", "←", "↖", "↑", "↗"]; // every 45 degrees, clockwise from the right (y down)

/** -1 while a sound at (dx, dy) from the view's centre is inside the view (edges included), else the direction
 *  0..7 clockwise from the right (screen y grows downwards). floor(x + 0.5) is the rule in every engine
 *  (tools/audio/wavesmith/access.py; data/golden/access.json). */
export function captionDirection(dx: number, dy: number, halfW: number, halfH: number): number {
  if (!Number.isFinite(dx) || !Number.isFinite(dy)) return -1;
  if (Math.abs(dx) <= halfW && Math.abs(dy) <= halfH) return -1;
  const k = Math.floor(Math.atan2(dy, dx) / (Math.PI / 4) + 0.5);
  return ((k % 8) + 8) % 8;
}

/** The arrow for a sound at (dx, dy) from the view's centre, or "" while it is inside the view. */
export function captionArrow(dx: number, dy: number, halfW: number, halfH: number): string {
  const k = captionDirection(dx, dy, halfW, halfH);
  return k < 0 ? "" : ARROWS[k];
}
