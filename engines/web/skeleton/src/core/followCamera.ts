// ---------------------------------------------------------------------------
// followCamera.ts
// Purpose : 2D camera follow with a deadzone box, look-ahead along the target's velocity and frame-rate
//           independent exponential smoothing. Same numbers in every engine (data/golden/juice.json "follow").
// Usage   : const cam = new FollowCamera({ deadzoneW: 64, deadzoneH: 48 })
//           each frame: const { x, y } = cam.update(dt, player.x, player.y, body.vx, body.vy)
//           then center the engine camera on (x, y)
// Notes   : No Phaser import (Vitest runs it). smoothing 0 snaps; higher values catch up faster
//           (k = 1 - e^(-smoothing * dt), so 30 fps and 144 fps settle the same way).
//
// Pseudocode (per axis):
//   desired = cam, or target -/+ half the deadzone when the target left the box ; desired += v * lookahead
//   cam += (desired - cam) * k
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
export const FOLLOW_DEFAULTS = {
  deadzoneW: 64.0, // pixels the target may move left/right before the camera follows
  deadzoneH: 48.0,
  lookahead: 0.25, // seconds of velocity to look ahead
  smoothing: 8.0, // 1/s; 0 = snap
  x: 0.0, // start position
  y: 0.0,
};

export type FollowParams = typeof FOLLOW_DEFAULTS;

function axis(cam: number, target: number, half: number): number {
  if (target > cam + half) return target - half;
  if (target < cam - half) return target + half;
  return cam;
}

export class FollowCamera {
  deadzoneW: number;
  deadzoneH: number;
  lookahead: number;
  smoothing: number;
  x: number;
  y: number;

  constructor(params: Partial<FollowParams> = {}) {
    const p = { ...FOLLOW_DEFAULTS, ...params };
    this.deadzoneW = p.deadzoneW;
    this.deadzoneH = p.deadzoneH;
    this.lookahead = p.lookahead;
    this.smoothing = p.smoothing;
    this.x = p.x;
    this.y = p.y;
  }

  update(dt: number, tx: number, ty: number, vx = 0, vy = 0): { x: number; y: number } {
    const dx = axis(this.x, tx, this.deadzoneW / 2.0) + vx * this.lookahead;
    const dy = axis(this.y, ty, this.deadzoneH / 2.0) + vy * this.lookahead;
    const k = this.smoothing > 0.0 ? 1.0 - Math.exp(-this.smoothing * dt) : 1.0;
    this.x += (dx - this.x) * k;
    this.y += (dy - this.y) * k;
    return { x: this.x, y: this.y };
  }
}

// {{FOOTER}}
