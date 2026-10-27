---
name: start-session
description: Begin a work session on this game. Use at the start of a conversation, after /clear, or when the user says "let's get going", "where were we", or "what's next". Loads HANDOFF and ROADMAP, checks git state, runs a quick health check, and proposes the first task.
---

# Start session

Goal: get oriented in under a minute without reading the whole repo.

1. Read `docs/HANDOFF.md` (already imported by CLAUDE.md, do not re-read if it is in context) and the **Now** section of `docs/ROADMAP.md`.
2. If Git is installed and the folder is a repository (a `.git` folder exists): run `git status --short` and
   `git log --oneline -5`; note the branch and any uncommitted work. Otherwise say "no Git history yet" and go on.
3. Run `python tools/dev.py check`. If it fails, report the failure first, before any new work.
4. Report back in this shape, tight:
   - **State:** one or two sentences (what works, what is in flight)
   - **Health:** check result, uncommitted files
   - **Proposed first task:** from HANDOFF "Next step" or ROADMAP Now, with a one-line "done when"
   - **Questions:** only if something is genuinely ambiguous or missing
5. Wait for a go-ahead or a different direction. Do not start editing yet.

Rules:
- Do not summarize the whole GDD. The user knows their game.
- If HANDOFF is stale (older than the last commits) say so and ask whether to trust it.
- No lectures. Be brief.
