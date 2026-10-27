// ---------------------------------------------------------------------------
// sound.ts
// Purpose : The four sound effects (pickup, delivered, caught, last-seconds tick) and the town's ambience loop.
// Usage   : const sfx = new Sfx(); sfx.play("pickup"); sfx.ambience()   // on every key press: starts it once
// Notes   : Plain HTMLAudioElement: enough for four one-shots and one loop. Browsers block sound until the
//           player presses a key; a blocked play() is ignored on purpose, never an error
//           (the headless smoke browser and autoplay runs hit that path). ElevenLabs sounds (A-0007 to A-0011).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

const SOUNDS = {
  pickup: "assets/audio/parcel-pickup.mp3",
  delivered: "assets/audio/parcel-delivered.mp3",
  caught: "assets/audio/robot-caught.mp3",
  tick: "assets/audio/clock-tick.mp3",
} as const;
const AMBIENCE = "assets/audio/town-ambience.wav";
const VOLUME = 0.6;
const AMBIENCE_VOLUME = 0.3;   // under the one-shots

export type SoundName = keyof typeof SOUNDS;

export class Sfx {
  private clips = new Map<SoundName, HTMLAudioElement>();
  private loop: HTMLAudioElement | null = null;
  muted = false;

  constructor() {
    for (const [name, url] of Object.entries(SOUNDS) as [SoundName, string][]) {
      const a = new Audio(url);
      a.preload = "auto";
      a.volume = VOLUME;
      this.clips.set(name, a);
    }
  }

  play(name: SoundName): void {
    if (this.muted) return;
    const clip = this.clips.get(name)!.cloneNode(true) as HTMLAudioElement;
    clip.volume = VOLUME;
    clip.play().catch(() => {}); // blocked until the first key press: fine
  }

  // The town hums under the night; called on key presses, so the first one the browser allows starts it
  ambience(): void {
    if (this.muted) {
      this.loop?.pause();
      return;
    }
    if (!this.loop) {
      this.loop = new Audio(AMBIENCE);
      this.loop.loop = true;
      this.loop.volume = AMBIENCE_VOLUME;
    }
    if (this.loop.paused) this.loop.play().catch(() => {}); // still locked: the next key press tries again
  }
}
