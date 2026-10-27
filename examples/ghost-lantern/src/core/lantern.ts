// ---------------------------------------------------------------------------
// lantern.ts
// Purpose : The lantern: oil that drains (faster when bright), a light radius,
//           and how much light reaches a point. Shield and timer in one (GDD twist).
// Usage   : const l = new Lantern(cfg); l.update(dt, wantBright); l.radius(); l.lightAt(distance)
// Notes   : Engine-free and unit tested. Units: oil 0..cfg.maxOil, distances in tiles.
//           Empty lantern still glows a little (cfg.emptyRadius) so the player can see,
//           but it scares nothing (lightAt returns 0 when empty).
//
// Pseudocode:
//   bright = wantBright and oil > 0
//   oil -= (bright ? brightBurn : dimBurn) * dt, clamped at 0
//   radius = empty ? emptyRadius : (bright ? brightRadius : dimRadius)
//   lightAt(d) = empty ? 0 : power * clamp(1 - d / radius, 0, 1)   power: dimPower or brightPower
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export type LanternConfig = {
  maxOil: number;
  dimBurn: number; // oil per second
  brightBurn: number;
  dimRadius: number; // tiles
  brightRadius: number;
  emptyRadius: number;
  dimPower: number; // 0..1: how much a dim lantern scares (seeing, not shielding)
  brightPower: number;
};

export class Lantern {
  oil: number;
  bright = false;

  constructor(private readonly cfg: LanternConfig) {
    this.oil = cfg.maxOil;
  }

  get empty(): boolean {
    return this.oil <= 0;
  }

  update(dt: number, wantBright: boolean): void {
    const burning = wantBright && !this.empty ? this.cfg.brightBurn : this.cfg.dimBurn;
    this.oil = Math.max(0, this.oil - burning * dt);
    this.bright = wantBright && !this.empty; // after draining: an empty lantern is never bright, not even for a frame
  }

  refill(amount: number): void {
    this.oil = Math.min(this.cfg.maxOil, this.oil + amount);
  }

  radius(): number {
    if (this.empty) return this.cfg.emptyRadius;
    return this.bright ? this.cfg.brightRadius : this.cfg.dimRadius;
  }

  /** 0..1 light at `distance` tiles from the lantern (what ghosts fear). */
  lightAt(distance: number): number {
    if (this.empty) return 0;
    const power = this.bright ? this.cfg.brightPower : this.cfg.dimPower;
    return power * Math.min(1, Math.max(0, 1 - distance / this.radius()));
  }

  fraction(): number {
    return this.oil / this.cfg.maxOil;
  }
}
