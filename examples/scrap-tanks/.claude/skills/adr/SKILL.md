---
name: adr
description: Record an architecture or technology decision (engine choice, plugin, library, save format, networking approach, config format, MCP server). Use when choosing between technical options or when a significant decision was just made in conversation.
---

# ADR (architecture decision record)

1. List `docs/adr/` and pick the next number (`NNNN`, four digits). Copy `docs/adr/0000-template.md` to `docs/adr/NNNN-short-title.md`.
2. Fill it in from the conversation. Do not invent context. Ask for what is missing.
3. Options: at least two real alternatives plus "do nothing". Pros and cons in plain terms.
4. Decision and the single most important reason. Consequences: good, bad, and what would make us revisit.
5. Mark every factual claim about tools or engines **verified** or **unverified** in Notes.
6. If it supersedes an earlier ADR, update that ADR's status line.
7. Reference the ADR number in `docs/ARCHITECTURE.md`: in the Key systems row it affects, or else in the section it changes (e.g. "State and save data: JSON, see ADR-0003").

Keep ADRs short. One page. They exist so future-you does not re-litigate settled choices.
