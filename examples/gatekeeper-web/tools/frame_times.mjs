// ---------------------------------------------------------------------------
// frame_times.mjs
// Purpose : Frame-time sampling for tools/smoke.mjs (#90): the page records the time between its animation frames
//           (requestAnimationFrame) while smoke runs, and smoke prints one summary line that tools/dev.py reads:
//             FRAME_TIMES frames=N mean=MS p95=MS p99=MS worst=MS mode=software|render
// Usage   : import { startFrameSampler, stopFrameSampler, frameLine } from "./frame_times.mjs";
//           await startFrameSampler(page)  ->  ... the run ...  ->  times = await stopFrameSampler(page)
//           console.log(frameLine(times, headed ? "render" : "software"))
// Notes   : The numbers are what a player would see: the time from one drawn frame to the next, capped by the
//           browser's frame rate (60 Hz: about 16.7 ms when nothing is slow). Headless Chromium draws WebGL on the
//           CPU (SwiftShader), so a headless run is "software": slower than a GPU, not a GPU budget. Percentiles are
//           nearest-rank (the same rule as every engine's FRAME_TIMES line). Every page call is raced against a
//           timeout: a frozen page gives no numbers, never a hang.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

const CALL_TIMEOUT_MS = 2000; // a page that does not answer within this gives no frame times
const later = (ms, value) => new Promise((res) => setTimeout(() => res(value), ms));

/** Starts recording frame-to-frame times in the page (window.__kitFrames). Never throws. */
export async function startFrameSampler(page) {
  const start = page
    .evaluate(() => {
      const s = (window.__kitFrames = { times: [], last: 0, on: true });
      const tick = (now) => {
        if (!s.on) return;
        if (s.last) s.times.push(now - s.last);
        s.last = now;
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    })
    .catch(() => {});
  await Promise.race([start, later(CALL_TIMEOUT_MS)]);
}

/** Stops the sampler and returns its frame times in ms, or null (never started, page gone or frozen). */
export async function stopFrameSampler(page) {
  const read = page
    .evaluate(() => {
      const s = window.__kitFrames;
      if (!s) return null;
      s.on = false;
      return s.times;
    })
    .catch(() => null);
  const times = await Promise.race([read, later(CALL_TIMEOUT_MS, null)]);
  return Array.isArray(times) ? times.filter((t) => Number.isFinite(t) && t >= 0) : null;
}

/** The FRAME_TIMES line for these times ("" when there are none). */
export function frameLine(times, mode) {
  if (!times || !times.length) return "";
  const s = [...times].sort((a, b) => a - b);
  const pick = (q) => s[Math.max(0, Math.ceil(q * s.length) - 1)];
  const mean = s.reduce((a, b) => a + b, 0) / s.length;
  const ms = (v) => v.toFixed(2);
  return `FRAME_TIMES frames=${s.length} mean=${ms(mean)} p95=${ms(pick(0.95))} p99=${ms(pick(0.99))} worst=${ms(s[s.length - 1])} mode=${mode}`;
}
