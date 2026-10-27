// ---------------------------------------------------------------------------
// log.ts
// Purpose : Tiny channel-based logger so console output is greppable and toggleable.
// Usage   : Log.info("physics", "landed"); Log.warn(...); Log.error(...); Log.debug(...)
//           Debug lines print when the page URL has ?debug (or Log.debugEnabled = true)
//           and the channel is on: Log.enableChannel("ai").
// Notes   : `dev.py smoke` fails on any console error, and Log.error uses console.error.
//           That is intentional: an error at boot is a failed build.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

const channels = new Set<string>(["core"]);

function debugFromUrl(): boolean {
  return typeof location !== "undefined" && new URLSearchParams(location.search).has("debug");
}

export const Log = {
  debugEnabled: debugFromUrl(),

  enableChannel(channel: string): void {
    channels.add(channel);
  },

  debug(channel: string, msg: string): void {
    if (Log.debugEnabled && channels.has(channel)) console.debug(`[DEBUG][${channel}] ${msg}`);
  },

  info(channel: string, msg: string): void {
    console.log(`[INFO][${channel}] ${msg}`);
  },

  warn(channel: string, msg: string): void {
    console.warn(`[WARN][${channel}] ${msg}`);
  },

  error(channel: string, msg: string): void {
    console.error(`[ERROR][${channel}] ${msg}`);
  },
};

// {{FOOTER}}
