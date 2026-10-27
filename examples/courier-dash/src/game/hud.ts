// ---------------------------------------------------------------------------
// hud.ts
// Purpose : The HTML overlay: clock, parcels, stamina bar, version, the start and end messages,
//           and the debug line.
// Usage   : const hud = new Hud(host, version); each frame hud.update(sim, best, debugText)
// Notes   : Plain DOM over the canvas (styles in index.html): crisp text at any size and no
//           font atlas. Text only changes when the value does, so it is cheap per frame.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import type { Sim } from "../core/sim";

const HELP =
  "Deliver all 5 parcels to the flag before the clock runs out.<br>" +
  "<b>WASD</b> or <b>arrows</b> to move, <b>Shift</b> to sprint. One parcel at a time.<br>" +
  "Do not let the robot touch you. <span class='c'>Cyan</span>: patrolling. <span class='a'>Amber !</span>: it saw something. <span class='r'>Red</span>: chasing.<br>" +
  "The clock starts when you move.";

type Field = "time" | "parcels" | "fill" | "msg" | "debug" | "best";

export class Hud {
  private readonly el: Record<Field, HTMLElement>;
  private last: Record<string, string> = {};

  constructor(host: HTMLElement, version: string) {
    const root = document.createElement("div");
    root.id = "hud";
    root.innerHTML = `
      <div class="panel stats"><div class="time"></div><div class="parcels"></div><div class="bar"><div class="fill"></div></div><div class="best"></div></div>
      <div class="version">v${version}</div>
      <div class="panel msg"></div>
      <div class="debug"></div>`;
    host.appendChild(root);
    const q = (s: string) => root.querySelector<HTMLElement>(s)!;
    this.el = { time: q(".time"), parcels: q(".parcels"), fill: q(".fill"), msg: q(".msg"), debug: q(".debug"), best: q(".best") };
  }

  update(sim: Sim, best: number | null, debug: string): void {
    this.set("time", sim.timeLeft.toFixed(1));
    this.el.time.classList.toggle("low", sim.started && sim.timeLeft <= sim.t.run.lowTimeSeconds);
    this.set("parcels", `Parcels ${sim.delivered} / ${sim.parcels.length}${sim.carrying !== null ? " (carrying one)" : ""}`);
    this.el.fill.style.width = `${(100 * sim.courier.stamina) / sim.t.courier.staminaMax}%`;
    this.el.fill.classList.toggle("tired", sim.courier.exhausted);
    this.set("best", best === null ? "" : `Best: ${best.toFixed(1)} s to spare`);
    this.set("debug", debug);

    let msg = "";
    if (sim.outcome === "caught") msg = `<b>Caught!</b> ${sim.delivered} of ${sim.parcels.length} delivered.<br>Press <b>R</b> to try again.`;
    else if (sim.outcome === "timeup") msg = `<b>Out of time.</b> ${sim.delivered} of ${sim.parcels.length} delivered.<br>Press <b>R</b> to try again.`;
    else if (sim.outcome === "won") msg = `<b>All delivered</b> with ${sim.timeLeft.toFixed(1)} s to spare!<br>Press <b>R</b> to go again.`;
    else if (!sim.started) msg = HELP;
    this.set("msg", msg);
    this.el.msg.style.display = msg ? "block" : "none";
  }

  private set(key: Field, html: string): void {
    if (this.last[key] === html) return;
    this.last[key] = html;
    this.el[key].innerHTML = html;
  }
}
