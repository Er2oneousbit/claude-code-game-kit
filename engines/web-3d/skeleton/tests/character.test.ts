// ---------------------------------------------------------------------------
// character.test.ts
// Purpose : src/game/character.ts against the golden rigged character (data/golden/character/character.glb: Mixamo
//           bone names, looping idle and walk clips, #290): GLTFLoader finds the clips at their lengths, walk plays on
//           a loop at 1x (the clock and the loop's period) and turns the moving bone as far as the clip swings it, no
//           more, and three's bone names drop the ':'.
// Usage   : python tools/dev.py test
// Notes   : Runs in Node: the fixture has no textures, so GLTFLoader needs no DOM. Numbers come from
//           data/golden/character/expected.json (tools/blender/golden_character.py), never from this file.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the swing's ceiling, the loop's period and clock
//           (0.15.0 review)
// ---------------------------------------------------------------------------
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";
import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { boneName, parseCharacter } from "../src/game/character";
import { GOLDEN_DIR } from "./helpers/golden";

const DIR = join(GOLDEN_DIR, "character");
const expected = JSON.parse(readFileSync(join(DIR, "expected.json"), "utf-8"));
const STEPS = 30; // frames of walk to play
const MIN_SHARE = 0.8; // the bone must turn at least this share of the clip's swing (frames sample it)
const MAX_SHARE = 1.1; // ... and no more: more would mean two clips applied at once, or the wrong bone
const PERIOD_TOL_DEG = 1.0; // a pose a whole clip length later is the same pose (the loop's period is the length)
const CLOCK_TOL_S = 0.002; // the action's clock advances by the time given (timeScale 1)

async function load() {
  const buf = readFileSync(join(DIR, expected.file));
  return parseCharacter(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer);
}

describe("rigged character (data/golden/character)", () => {
  it("has the clips at their lengths", async () => {
    const ch = await load();
    for (const [name, want] of Object.entries(expected.clips) as [string, { seconds: number }][]) {
      expect(ch.clips.has(name), name).toBe(true);
      expect(ch.clips.get(name)!.duration).toBeCloseTo(want.seconds, 2);
    }
  });

  it("names bones without the colon, all of them in one skeleton", async () => {
    const ch = await load();
    const skinned: THREE.SkinnedMesh[] = [];
    ch.root.traverse((o) => { if ((o as THREE.SkinnedMesh).isSkinnedMesh) skinned.push(o as THREE.SkinnedMesh); });
    expect(skinned.length).toBeGreaterThan(0);
    const names = skinned[0].skeleton.bones.map((b) => b.name).sort();
    expect(names).toEqual((expected.bones as string[]).map(boneName).sort());
    expect(boneName("mixamorig:Hips")).toBe("mixamorigHips");
  });

  it("plays walk on a loop and swings the moving bone", async () => {
    const ch = await load();
    const action = ch.play("walk", { fade: 0 });
    const bone = ch.root.getObjectByName(boneName(expected.moving_bone))!;
    expect(bone).toBeTruthy();
    const poses: THREE.Quaternion[] = [];
    for (let i = 0; i <= STEPS; i++) {
      poses.push(bone.quaternion.clone());
      ch.update(1 / 30);
    }
    let most = 0;
    for (const a of poses) for (const b of poses) most = Math.max(most, THREE.MathUtils.radToDeg(a.angleTo(b)));
    expect(most).toBeGreaterThan(MIN_SHARE * expected.moving_bone_swing_deg);
    expect(most).toBeLessThan(MAX_SHARE * expected.moving_bone_swing_deg); // not two clips at once
    ch.update(expected.clips.walk.seconds * 1.5);
    expect(action.isRunning()).toBe(true); // a looping clip is still running after its length
  });

  it("loops with the clip's length as its period, at 1x", async () => {
    const ch = await load();
    const length: number = expected.clips.walk.seconds;
    const action = ch.play("walk", { fade: 0 });
    const bone = ch.root.getObjectByName(boneName(expected.moving_bone))!;
    ch.update(length * 0.25);
    expect(Math.abs(action.time - length * 0.25)).toBeLessThan(CLOCK_TOL_S); // the clock runs at 1x
    const quarter = bone.quaternion.clone();
    ch.update(length);
    expect(THREE.MathUtils.radToDeg(quarter.angleTo(bone.quaternion))).toBeLessThan(PERIOD_TOL_DEG);
    expect(Math.abs(action.time - length * 0.25)).toBeLessThan(CLOCK_TOL_S); // wrapped once, not clamped
  });

  it("plays a clip once and holds it, and refuses an unknown clip", async () => {
    const ch = await load();
    const idle = ch.play("idle", { loop: false });
    ch.update(expected.clips.idle.seconds + 0.5);
    expect(idle.isRunning()).toBe(false);
    expect(idle.clampWhenFinished).toBe(true);
    expect(() => ch.play("no_such_clip")).toThrow(/no clip/);
  });

  it("stands the expected height on the ground", async () => {
    const ch = await load();
    ch.root.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(ch.root, true);
    expect(box.max.y - box.min.y).toBeCloseTo(expected.height_m, 1);
    expect(Math.abs(box.min.y)).toBeLessThan(0.02);
  });
});

// {{FOOTER}}
