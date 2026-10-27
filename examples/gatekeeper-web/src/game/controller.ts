// ---------------------------------------------------------------------------
// controller.ts
// Purpose : Glue between the page (start panel, chat log, input), the brain (model or
//           scripted), the rules (core/gatekeeper.ts) and the picture (GateScene).
// Usage   : new Controller(scene).start() from main.ts once the scene is ready.
//           URL flags: ?autoplay (types a winning script with the scripted guard),
//           ?autoplay=rude (a losing script), ?llm=1 (load the model at once, with ?autoplay too),
//           ?debug (show intent, trust change and where each reply came from).
// Notes   : Logs markers for smoke and scenario runs: INTENT, GATE_OPEN, TURNED_AWAY.
//           The model is optional at every step: no WebGPU, a failed download, a slow or
//           broken reply all land on the scripted guard, and the game says so. A fatal reply (the
//           engine itself failed) swaps in the scripted guard for the rest of the session.
//           "Start over" bumps a run counter: a reply still on its way belongs to the old game and is dropped.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): stale replies after "Start over" dropped,
//           fatal replies switch to the scripted guard, typed text kept while busy, one intro per
//           start, one restart per click burst, player text cut to MAX_INPUT
// ---------------------------------------------------------------------------
import { applyIntent, mood, newState, type State } from "../core/gatekeeper";
import { MAX_INPUT } from "../core/intent";
import { outcomeLine } from "../core/lines";
import { Log } from "../core/log";
import { Rng } from "../core/rng";
import { FallbackBrain, type NpcBrain, webGpuAvailable } from "./brain";
import type { GateScene } from "./GateScene";
import type { Turn } from "./prompt";
import { MAX_SLOW_REPLIES, MODEL_DOWNLOAD_MB, RULES, SEED } from "./tuning";

const WIN_SCRIPT = ["Good evening, guard.", "That armor looks well kept.", "Captain Wren asked me to come tonight."];
const RUDE_SCRIPT = ["Open the gate.", "Open it or I will break your nose.", "Last chance before I hurt you."];

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

export class Controller {
  private state: State = newState(RULES);
  private history: Turn[] = [];
  private brain: NpcBrain;
  private busy = false;
  private run = 0;              // bumped by reset(); say() drops a reply that comes back in a later run
  private slowInARow = 0;       // model timeouts in a row; MAX_SLOW_REPLIES of them count as a lost model
  private restarting = false;   // "Start over" clicked, the scene has not been recreated yet
  private begun = false;        // begin() ran once, so start() must not run the intro again
  private readonly rng = new Rng(SEED);
  private readonly pick = (n: number) => this.rng.int(0, n - 1);
  private readonly params = new URLSearchParams(location.search);
  private readonly debug = this.params.has("debug");

  constructor(private readonly scene: GateScene) {
    this.brain = new FallbackBrain(this.pick);
  }

  async start(): Promise<void> {
    $("useScript").onclick = () => this.begin(new FallbackBrain(this.pick));
    $("useModel").onclick = () => this.loadModel();
    $("say").onsubmit = (e) => {
      e.preventDefault();
      const input = $<HTMLInputElement>("line");
      const text = input.value.trim();
      if (!text || !this.canSay()) return;   // keep the text: Enter again once Bram has answered
      input.value = "";
      void this.say(text);
    };
    $("again").onclick = () => this.reset();
    const gpu = await webGpuAvailable();
    if (!gpu) {
      $<HTMLButtonElement>("useModel").disabled = true;
      this.status("No WebGPU in this browser, so the AI guard is unavailable. The scripted guard works everywhere.");
    } else {
      this.status(`The AI guard downloads about ${MODEL_DOWNLOAD_MB} MB the first time; after that the browser keeps it.`);
    }
    const auto = this.params.get("autoplay");
    if (this.params.has("llm") && gpu) await this.loadModel();
    if (auto !== null) {
      if (!this.begun) this.begin(new FallbackBrain(this.pick));   // a failed model load already began
      for (const line of auto === "rude" ? RUDE_SCRIPT : WIN_SCRIPT) {
        if (this.state.outcome !== "talking") break;
        await this.say(line);
      }
    }
  }

  private status(text: string): void {
    $("status").textContent = text;
  }

  private async loadModel(): Promise<void> {
    $<HTMLButtonElement>("useModel").disabled = true;
    $<HTMLButtonElement>("useScript").disabled = true;
    $("progress").style.display = "block";
    try {
      const { WebLlmBrain } = await import("./webllmBrain");   // the WebLLM library loads only now
      const brain = await WebLlmBrain.load((f, text) => {
        ($("progress").firstElementChild as HTMLElement).style.width = `${Math.round(f * 100)}%`;
        this.status(text);
      }, this.pick);
      Log.info("ai", "MODEL_READY");
      this.begin(brain);
    } catch (err) {
      Log.warn("ai", `model failed to load: ${String(err)}`);
      this.status("The model could not load, so the scripted guard takes over.");
      this.begin(new FallbackBrain(this.pick));
    }
  }

  private begin(brain: NpcBrain): void {
    this.brain = brain;
    this.begun = true;
    $("start").style.display = "none";
    $("chat").style.display = "block";
    this.add("sys", brain.kind === "model"
      ? "You are talking to an AI guard running on your computer. He will improvise; the rules do not."
      : "You are talking to the scripted guard.");
    this.add("guard", "Halt. The gate is closed.");
    this.scene.show(this.state, false);
    $<HTMLInputElement>("line").focus();
  }

  private reset(): void {
    if (this.restarting) return;   // a double click would queue two restarts and two intros
    this.restarting = true;
    this.run += 1;
    this.busy = false;             // a reply still on its way is dropped by say(), so nothing else clears this
    this.state = newState(RULES);
    this.history = [];
    $("log").innerHTML = "";
    this.scene.scene.restart();
    this.scene.events.once("create", () => {
      this.restarting = false;
      this.begin(this.brain);
    });
  }

  /** Whether say() would take a line now (the submit handler keeps the text when it would not). */
  private canSay(): boolean {
    return !this.busy && !this.restarting && this.state.outcome === "talking";
  }

  private add(kind: "you" | "guard" | "sys", text: string): void {
    const p = document.createElement("div");
    p.className = kind;
    if (kind === "guard") p.innerHTML = "<b>Bram:</b> ";
    p.append(kind === "you" ? `You: ${text}` : text);
    $("log").append(p);
    $("log").scrollTop = $("log").scrollHeight;
  }

  async say(line: string): Promise<void> {
    if (!this.canSay()) return;
    const text = line.slice(0, MAX_INPUT);   // the history and the log hold what the model was sent
    const run = this.run;
    this.busy = true;
    this.add("you", text);
    const r = await this.brain.reply(this.history, text, mood(this.state, RULES));
    if (run !== this.run) return;   // "Start over" while Bram was thinking: this reply belongs to the old game
    const step = applyIntent(this.state, r.intent, RULES);
    this.state = step.state;
    this.history.push({ player: text, intent: r.intent, line: r.line });
    this.add("guard", r.line);
    if (this.debug || r.why) this.add("sys", `[${r.intent}, trust ${step.delta >= 0 ? "+" : ""}${step.delta}, ${r.source}${r.ms ? ` ${r.ms} ms` : ""}${r.why ? `, ${r.why}` : ""}]`);
    Log.info("game", `INTENT ${r.intent} (${r.source}) trust=${this.state.trust}`);
    if (r.why) Log.warn("ai", `FALLBACK: ${r.why}`);
    if (r.source === "model") Log.info("ai", `MODEL_REPLY ${r.ms} ms: ${r.line}`);
    this.slowInARow = r.why === "model too slow" ? this.slowInARow + 1 : 0;
    if ((r.fatal || this.slowInARow >= MAX_SLOW_REPLIES) && this.brain.kind === "model") {
      // A broken engine would cost REPLY_TIMEOUT_MS or an error on every line from here on
      this.brain = new FallbackBrain(this.pick);
      this.add("sys", "The AI guard stopped working; the scripted guard takes over.");
      Log.warn("ai", "MODEL_LOST: switched to the scripted guard");
    }
    this.scene.show(this.state);
    if (this.state.outcome !== "talking") {
      this.add("guard", outcomeLine(this.state.outcome, this.pick));
      this.scene.finish(this.state.outcome);
      Log.info("game", this.state.outcome === "open" ? "GATE_OPEN" : "TURNED_AWAY");
    }
    this.busy = false;
  }
}
