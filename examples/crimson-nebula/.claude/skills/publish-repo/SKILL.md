---
name: publish-repo
description: Put the project on GitHub properly - license, secret and personal-data scan, private repo first, lock-down settings, then public. Use when the user wants to publish, open-source, share the code, "put it on GitHub", or make a repo public.
---

# Publish repo

Follow `docs/sop/SOP-13-publish-to-github.md`. Every step that creates, pushes, or changes visibility is outward-facing:
show the exact command and get a yes first. Never flip a repo to public without an explicit request in this session.

1. **License:** if `LICENSE` is missing, ask what reuse the user wants (SOP-13 step 1 table), then write the license
   file and a README "License" line that says what it covers (code, assets, or both).
2. **Redistribution:** walk `docs/ASSET_LOG.md`. List every asset whose license does not allow public redistribution
   (store packs, commercial fonts, unclear AI or music terms) and every `PLACEHOLDER` row. Propose: remove, gitignore,
   or keep the repo private.
3. **Scan:** run `python tools/publish_check.py`. Report FAIL and WARN items as a table with the fix for each.
   Check whether a history scanner is installed (`gitleaks version`); if so run it, if not say history is unscanned.
   A real key found anywhere: tell the user to rotate it at the provider first. Do not print the key.
4. **Email:** show the emails in `git log --format=%ae | sort -u`. If any is personal, explain the noreply setup (step 3).
5. **Create private:** check `gh auth status`, then propose the `gh repo create ... --private` command.
6. **Lock down:** give the step 6 settings as a checklist with where to click. Offer `gh` commands where they exist,
   and say which settings need the web UI or a paid plan on private repos.
7. **Public:** only when asked. Re-run `publish_check.py`, then give the visibility steps.

Output: what was done, what the user still has to click, and anything left at FAIL or UNKNOWN.
