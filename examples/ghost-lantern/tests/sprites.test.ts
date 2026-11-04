// ---------------------------------------------------------------------------
// sprites.test.ts
// Purpose : The art wiring: every frame the loader asks for is a real PNG of its size in public/,
//           every ghost action has a clip inside its frames, and the keeper's facing rule.
// Notes   : A missing frame only shows in the browser as a green "missing texture" box, so this
//           catches a renamed or deleted file before smoke does.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { facingFor, frameFiles, GHOST_ART, GHOST_FRAMES } from "../src/game/sprites";

const PNG_SIG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

describe("sprites", () => {
  it("loads only real PNG frames of the stated size, each key once", () => {
    const files = frameFiles();
    expect(files.length).toBe(3 * (6 + 4) + 3 * 9); // keeper: 3 drawn directions x (walk + idle); ghost: 3 x 9
    expect(new Set(files.map((f) => f.key)).size, "texture keys are unique").toBe(files.length);
    for (const f of files) {
      const data = readFileSync(join("public", f.file));
      expect([...data.subarray(0, 8)], f.file).toEqual(PNG_SIG);
      expect([data.readUInt32BE(16), data.readUInt32BE(20)], f.file).toEqual([f.px, f.px]);
    }
  });

  it("gives every ghost action a clip inside its frames", () => {
    for (const [action, art] of Object.entries(GHOST_ART)) {
      expect(art.from, action).toBeGreaterThanOrEqual(0);
      expect(art.to, action).toBeLessThan(GHOST_FRAMES);
      expect(art.to - art.from + 1, `${action} has at least 4 frames`).toBeGreaterThanOrEqual(4);
    }
  });

  it("faces the larger axis of the move and keeps the facing when standing still", () => {
    expect(facingFor({ x: 1, y: 0 }, "south")).toBe("east");
    expect(facingFor({ x: -1, y: 0.5 }, "south")).toBe("west");
    expect(facingFor({ x: 0.2, y: -1 }, "east")).toBe("north");
    expect(facingFor({ x: 0, y: 1 }, "north")).toBe("south");
    expect(facingFor({ x: 1, y: 1 }, "north"), "a diagonal reads as a side view").toBe("east");
    expect(facingFor({ x: 0, y: 0 }, "west")).toBe("west");
  });
});
