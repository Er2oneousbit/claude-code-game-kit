# SOP-07: Claude Code Hygiene

## Goal
Keep the AI sharp, cheap, and on-task. Most "Claude got dumb" moments are context problems.

## Session shape
1. `/start-session`: loads HANDOFF, ROADMAP Now, git status. Claude proposes the first task.
2. One task per conversation. When the task is done and committed, run `/end-session`, then `/clear` for the next task.
3. `/end-session` rewrites HANDOFF so the next session (or a fresh Claude) starts warm.

## Context rules
- `CLAUDE.md` stays lean. Details belong in `docs/` and get pulled in only when needed.
- Delegate wide searches and reviews to subagents. They return a summary, not 40 file dumps.
- Ask for pseudocode and a plan before big edits. Cheaper to fix a plan than a diff.
- Use plan mode for architecture-level changes.
- If Claude repeats itself, contradicts earlier decisions, or loses track: write HANDOFF, `/clear`, restart.
- Paste exact error text. Paraphrased errors lose the clue.

## Prompting patterns that work for game dev
- "Here is the behavior I see, here is what I expect, here is the log. Propose 3 hypotheses ranked by likelihood. Do not change code yet."
- "Pseudocode first, then wait."
- "Prototype this in the ugliest way that proves it works. Mark with PROTOTYPE:."
- "Make the smallest change that could possibly work, run `check`, report."
- "Review this diff against docs/STYLE.md and docs/ENGINE.md gotchas." (`code-reviewer`)
- "Which numbers in this system should be tunables? Move them to data."

## Verification rule
Claude must label engine API claims as **verified** (checked against installed version or docs this session) or
**unverified** (from memory). Unverified claims get tested before they go into the codebase.

## MCP and plugins
- Add an MCP server or editor plugin only with an ADR entry (what, why, how to disable).
- Document how to start it in `docs/ENGINE.md`, so a tester is not stuck.

## Permissions
- `.claude/settings.json` is the shared baseline. Personal overrides go in `.claude/settings.local.json` (git-ignored).
- Never grant broad `Bash(*)`. Allow specific commands as you trust them.
- **Unattended runs** (`/goal`, overnight jobs): use auto mode with the deny rules intact, on a branch, after a commit. `SOP-12` has the recipe.
- **Bypass-permissions mode** (F18, a kit policy; seen in a grade-C video, E27): the agent never stops to ask. It can also delete, overwrite or run anything your
  user can. Only on a disposable branch in a VM or container, and check the deny rules still apply in that mode.

## Done when
- HANDOFF reflects reality and the next session can start without asking you for context.

## Common mistakes
- One giant conversation for a week.
- Burying rules in chat instead of in docs. If you said it twice, put it in `CLAUDE.md` or a SOP.
