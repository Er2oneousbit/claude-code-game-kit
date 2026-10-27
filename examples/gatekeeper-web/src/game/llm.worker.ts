// ---------------------------------------------------------------------------
// llm.worker.ts
// Purpose : Runs the WebLLM engine in a Web Worker so model loading and text
//           generation never freeze the game (WebLLM README: worker usage).
// Usage   : new Worker(new URL("./llm.worker.ts", import.meta.url), { type: "module" })
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { WebWorkerMLCEngineHandler } from "@mlc-ai/web-llm";

const handler = new WebWorkerMLCEngineHandler();
self.onmessage = (msg: MessageEvent) => handler.onmessage(msg);
