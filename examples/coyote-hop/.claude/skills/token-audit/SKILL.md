---
name: token-audit
description: Read-only audit of what uses up tokens and usage in Claude Code for this project (memory files, MCP tools and deferral, model and effort, hooks, subagent models, scheduled work, the prompt cache). Use when the user says "token audit", "why am I running out of tokens", "why am I running out of usage", "I keep hitting my usage limit", "save tokens", or asks what a session costs. Reports only, changes nothing.
---

# Token audit

**Rules:** report only: change no file and no setting, not even an obvious fix (the user decides). Measure, do not
estimate. Where a number cannot be read, write UNKNOWN, never a guess. Evidence is a number or a path, never an
adjective.

1. **Measure:** `python tools/token_audit.py` (`--json` for the raw report, `--log <file>.jsonl` when it finds no
   session log). It sizes the memory files and their @imports (estimates at 4 characters per token), reads the
   settings (model, effort, hooks, proxy variable names, `.mcp.json`), the subagent models, the skills, and sums the
   newest session log's usage once per API response. It lists what it cannot see.
2. **Ask** the user to run `/context` and `/usage` and paste both: you cannot run slash commands yourself. `/context`
   numbers replace the tool's estimates. Skipped: those rows stay UNKNOWN.
3. **MCP:** from your own tool list, name each connected MCP server, how many tools it gives you, and whether they are
   deferred (names only until a tool search loads them) or loaded in full.
4. **Scheduled work:** the scheduled tasks, loops and background jobs you started or can see, with their intervals.
   Flag an interval longer than the cache lifetime (the tool's "cache writes by lifetime": 5 minutes or 1 hour): each
   run then rebuilds the cache. None you can see: UNKNOWN.
5. **Report:** one table sorted by cost, RED first, built from the tool's FINDINGS plus steps 2 to 4:

   | FINDING | SEVERITY (RED/AMBER/GREEN) | EVIDENCE | WHAT IT IS COSTING ME |
   |---|---|---|---|

   Then one line: the single highest-leverage change. Stop there; make the change only if the user asks.

**Tips, not rules** (cite them as tips): the 5,000-token file and 10,000-token total memory thresholds, the warning
that `ANTHROPIC_BASE_URL` or `ANTHROPIC_AUTH_TOKEN` silently turns tool deferral off, and "each model switch rebuilds
the cache" come from one video's description (E154 in `docs/EVIDENCE.md`, grade D: check with `/context`). The
effort row rests on E62 (grade C). Context habits that cut usage: `docs/sop/SOP-07-claude-code-hygiene.md`.
