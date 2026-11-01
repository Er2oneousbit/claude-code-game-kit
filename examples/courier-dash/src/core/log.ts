// ---------------------------------------------------------------------------
// log.ts
// Purpose : Tiny channel-based logger so console output is greppable and toggleable.
// Usage   : Log.info("physics", "landed"); Log.warn(...); Log.error(...); Log.debug(...)
//           Debug lines print when the page URL has ?debug (or Log.debugEnabled = true)
//           and the channel is on: Log.enableChannel("ai").
//           Log.addSink((line) => ...) also receives every printed line (the game log file uses it).
// Notes   : `dev.py smoke` fails on any console error, and Log.error uses console.error.
//           That is intentional: an error at boot is a failed build.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export type LogSink = (line: string) => void;

const channels = new Set<string>(["core"]);
const sinks: LogSink[] = [];

function debugFromUrl(): boolean {
  return typeof location !== "undefined" && new URLSearchParams(location.search).has("debug");
}

function emit(line: string): void {
  for (const sink of sinks) {
    try {
      sink(line);
    } catch {
      /* a broken sink must never break logging */
    }
  }
}

export const Log = {
  debugEnabled: debugFromUrl(),

  enableChannel(channel: string): void {
    channels.add(channel);
  },

  addSink(sink: LogSink): void {
    sinks.push(sink);
  },

  debug(channel: string, msg: string): void {
    if (!(Log.debugEnabled && channels.has(channel))) return;
    const line = `[DEBUG][${channel}] ${msg}`;
    console.debug(line);
    emit(line);
  },

  info(channel: string, msg: string): void {
    const line = `[INFO][${channel}] ${msg}`;
    console.log(line);
    emit(line);
  },

  warn(channel: string, msg: string): void {
    const line = `[WARN][${channel}] ${msg}`;
    console.warn(line);
    emit(line);
  },

  error(channel: string, msg: string): void {
    const line = `[ERROR][${channel}] ${msg}`;
    console.error(line);
    emit(line);
  },
};
