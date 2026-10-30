---
name: make-a-game
description: Guided start for someone who downloaded the Claude Code Game Kit and wants a game. Use when the user, working in the kit folder, types just "Start" (the README's instruction), or says anything like "make me a game", "I want to make a game", "how do I use this", "where do I start", "help me get started", or seems new. Greets them, gives the project a random codename (scripts/codename.py), interviews them into a game plan in the shape of the kit's GDD template, and only then picks the engine, checks installs, creates the game folder with scripts/new_game.py, writes the plan into it and tells them exactly how to continue there.
---

# Make a game (start here)

The person in front of you probably downloaded this kit and has never set up a game project. Your job: get them from
"now what?" to "Claude is working inside my new game folder, and it knows what game we are making" in one sitting,
with no jargon. Interview first, build second: a game folder made from a one-line guess gets Claude's game, not theirs.

Ground rules:
- **Plain words.** Say "game folder", not "scaffold"; "the tool that runs the game", not "engine overlay". Explain a
  word the first time you must use it (one short clause). No SOP or evidence IDs.
- **Ask, then act.** One question at a time, each with suggested answers they can pick or a default they accept with "ok".
- **You run the commands.** They should never have to type a kit command. Before each one, say in a sentence what it
  does and that Claude Code may ask permission ("press Enter for Yes").
- **Never build the game in the kit folder,** never edit kit files here, never install software without a yes.
- **Never ask for or handle passwords, API keys or payment details.**

## 1. Greet them (first message)
Two or three short sentences, in your own words, covering:
- What this is: the kit kick-starts the two of you making a game together. It sets up a game folder where Claude
  already knows how to build, test and run the game, with safety rules and step-by-step procedures built in.
- What happens next: a short interview about their game, a one-page game plan you write from their answers, and only
  then the game folder. They can answer briefly, say "you decide" to any question, or "skip the interview" (then ask
  only the questions marked * below and fill the rest with labeled guesses).
Every new game starts with a random codename. Before the greeting, run `python scripts/codename.py` (`python3` on
macOS/Linux; it prints a name like `Project_Cobalt_Wyvern`, re-rolled if a folder of that name already sits next to the
kit). Say it in the greeting: "Your project is **Project_Cobalt_Wyvern** for now; we can rename it any time." Do not
ask for a name. If the command fails (no Python yet), invent one in the same pattern and note that Python needs
installing (step 5). Then ask the first interview batch.

## 2. Interview them into a game plan
The plan has the shape of the game's `docs/GDD.md` template (read `core/docs/GDD.md` here for the headings). Ask in
the order below, **one question at a time**. If your tools include a multiple-choice question prompt
(AskUserQuestion in Claude Code), use it: 3 or 4 short options fitted to what they said so far (each a label plus a
one-line description; a "You decide" option where it helps; mark one "(Recommended)" when you have a reason), and say
"Q4 of 13" in the question (14 when question 8b applies). The prompt always offers a free-text "Other", so they can answer in their own words.
Without the prompt, ask one question per message with two or three examples. Reflect back in one line after every
three or so answers ("So: a top-down stealth game about a lighthouse keeper.").
"You decide" means: pick something that fits, say what you picked, and mark it *(Claude's pick)* in the plan.
A. **The idea**
   1.* What is the game, in one sentence? ("a cat that dodges cucumbers"; "surprise me" is fine: offer three tiny
      ideas and let them pick)
   2. Which 2 or 3 games is it like, and what do you want from each? ("Celeste's jumping, Hades' runs")
   3. What makes it different from those? (a new setting on a known formula is enough)
B. **The play**
   4.* What does the player do most of the time, minute to minute?
   5. What makes them keep playing: beating levels, getting stronger, a story, a high score?
   6. How do you win, and how do you lose? What happens when you lose?
C. **Look and feel**
   7.* 2D or 3D, and seen from where (side, top-down, angled, first or third person)? (Default: 2D.)
   8. What should it look and sound like? (pixel art, cartoon, low-poly, dark, cozy, retro chiptune...)
   8b. *Only for a 2D game* (ask right after 8; it adds one to the question count): where should the finished art
       come from? Say first that the first build always uses simple art drawn in code, so this is about later. Options:
       - **Drawn in code plus free packs** *(Recommended for a first game)*: no cost, no setup; Claude draws simple
         sprites in code, and free packs (Kenney and others) fill in, each license checked.
       - **My own art**: they draw it (Aseprite, Pixelorama, Krita...) or already have sprites; Claude wires it in.
       - **A paid AI service**: for example PixelLab for pixel art. Their account and API token, a cost per image;
         Claude runs it only with their go-ahead per job.
       - **Dotwork, AI on this computer**: free per image, but needs an NVIDIA graphics card (8 GB of video memory for
         sprites, 16 GB for animation), 15 to 78 GB of downloads and an hour of setup. Makes ready-to-use assets for
         Godot; other engines get image files.
       Several at once is fine ("Dotwork for characters, packs for tiles"). Record the answer as the plan's Art source.
   9. Who is it for, and how should the player feel? ("me and my kids; clever", "horror fans; tense")
D. **Size and setup**
   10.* Where should it run: in a web browser (easy to share a link) or as a downloadable program? Any engine
       already installed (Godot, Unity, Unreal, RPG Maker MZ)? Windows, Mac or Linux?
   11. What is the smallest version that would already be fun to play for two minutes? (that is the first goal)
   12. What should stay out for now, even if it is cool? (online play, a story mode, a level editor...)
   13. What name should I use as the author? It goes in the game's docs and file credits. Offer their Git name
       (`git config user.name`, if set) as the default, plus "the user" for no name at all; a handle is fine.
Keyboard, gamepad or touch comes from their answers; ask only if it is unclear.

## 3. Write the plan and get a yes
From the answers, draft and show the plan in the chat, one short screen, under the GDD's headings: Working title,
One-line pitch, Genre, Perspective, Reference games, The twist, **three Pillars** (you propose them from the answers:
each a short phrase plus what it rules out), Core loop (`action -> feedback -> reward -> new decision`), Player fantasy
and audience, Art and audio direction (with the Art source from 8b), Controls, Toy scope (question 11), Out of scope (question 12), two or three
**Assumptions to test** with how you will know, and the Author (question 13). Mark every *(Claude's pick)*.
Right under the plan, before asking for the yes, show this warning in a box of its own (your words, same points):
> ⚠️ **The first version will look crude, on purpose.** Simple placeholder characters made in code (2D: pixel-art figures with a walk and an action; 3D: figures
> built from a few shapes, a kart with wheels and a driver; never dots or bare boxes) on plain backgrounds, maybe no sound. The first
> goal is to find out whether the game is *fun*, and that only takes the mechanics. Art, animation and music come once
> the fun is proven: polishing art for a game that turns out not to work wastes time, usage and money. Judge the
> first build by how it plays, not how it looks.
Ask (as a prompt when you can: "Looks good, build it" / "Change something" / "Rename it first"): "Anything to
change before I set up the game?" Apply changes, and move on only after a clear yes ("looks good",
"build it"). Keep the plan in the chat for now: it goes into the game folder in step 8.

## 4. Pick the engine for them
Pick one, **name it in plain words** ("a browser game made with Phaser, a free game library") and say why in one
sentence. Point to `CHOOSING_AN_ENGINE.md` only if they want to compare.
| They said | Pick | Why it suits a first game |
|---|---|---|
| Nothing special, or "browser", 2D | `web` | Only Node.js to install; the game opens in the browser; the kit installs everything else |
| Same, but 3D | `web-3d` | Same, with Three.js for 3D |
| "A real engine with an editor", or desktop builds | `godot` | Free and small, but needs a download, an environment variable and a test add-on (you do those for them) |
| Unity or Unreal already installed, and they want it | `unity` / `unreal` | Heavy installs; the engine must create the project first (README "Already have a project?") |
| Wants to write Rust, or code-only with no editor | `bevy` | Needs Rust (rustup) and, on Windows, Visual Studio Build Tools; the first build takes 5 to 15 minutes, later ones seconds |
| Wants to learn C++ | `cpp-sdl2` | Needs Visual Studio Build Tools or a compiler, CMake and vcpkg; the slowest start |
| Art source is Dotwork, and no engine named | `godot` | Dotwork writes Godot-ready art (animations, tile sets, scenes); other engines get only image files to wire in by hand |
| A classic RPG and they own RPG Maker MZ | `rpgmaker-mz` | They build maps and events in the editor; you write and test the plugins. Tell them this overlay is an untested proof of concept: never run against MZ itself |

## 5. Check the installs (you run the checks)
Run these and report in plain words what is there and what is missing:
- `python --version` (macOS/Linux: `python3 --version`). Needs 3.8 or newer. On Windows, if it opens the Microsoft
  Store or says "not found": install from https://www.python.org/downloads/ and tick **"Add python.exe to PATH"**.
- `git --version`. Recommended (saves history, lets them undo). https://git-scm.com/downloads (defaults are fine).
- Web, web-3d or RPG Maker MZ: `node --version`, needs 22.12 or newer. https://nodejs.org (the LTS button).
- Godot: Godot 4.3 or newer (tested on 4.7.2), standard (not .NET) build, from https://godotengine.org/download . It is a zip, not an
  installer: suggest unzipping to a simple folder (for example `C:\Godot` or `~/Applications`). Later, inside the game
  folder, set `GODOT_BIN` to that exe for them (ask first) and install GUT per `docs/ENGINE_FLOW.md`.
- Bevy: `cargo --version` (Rust 1.97.1 or newer). Missing: https://rustup.rs (Windows: `rustup-init.exe`, defaults are
  fine; it should offer the Visual Studio Build Tools if they are missing (verify)). Warn them the first `check` compiles Bevy for
  5 to 15 minutes, once.
- Art source Dotwork: check the graphics card only, install nothing for it now (Dotwork waits until the toy is fun).
  Windows and Linux: `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader`. Report the card and its memory
  in plain words; no NVIDIA card or under 8 GB means Dotwork will not run there, so offer to switch the art source.
  Also say how much free disk the models will need (15 GB for sprites, about 78 GB for everything).
- Unity, Unreal, C++: follow that engine's `engines/<id>/ENGINE.md` "Version and setup"; walk them through it step by step.
Missing pieces: give the link and the one setting that matters, offer to install with the system package manager
(`winget`, `brew`) if they prefer, and wait. After an install, terminals opened before it do not see it: tell them to
restart Claude Code (or the Desktop app) and say "I installed it", then check again.

## 6. Place the game folder
- Name: the codename from step 1 (`--name "Project_Cobalt_Wyvern"`), or a name they chose since.
- Folder: next to the kit, not inside it: `../<game-slug>`. Show the full path you will use, for example
  `C:\Games\cucumber-panic`, so they can find it in their file browser.
- If the kit sits in a OneDrive or iCloud folder, or the path is long (over about 60 characters), suggest a short
  unsynced place instead (`C:\Games\<slug>`, `~/Games/<slug>`): sync fights the many small files, and C++ and Unreal
  builds break on long Windows paths.
- Placed somewhere other than next to the kit? If a folder of that name already exists there, roll a new codename
  for that place (`python scripts/codename.py --check-dir "<that parent folder>"`) and tell them the new name.

## 7. Create it
From the kit folder:
```
python scripts/new_game.py --name "<Name>" --engine <id> --dest "<full path>" --author "<author>" --git-init
```
(Leave out `--git-init` if git is missing. Unity and Unreal: the engine creates the project first, then add `--adopt`.
RPG Maker MZ: after creating it, they make a new project in the MZ editor, anywhere, and you run
`python tools/dev.py setup --from "<that folder>"`, which copies MZ's own files into the game's `game/` folder.)
Run each command on its own (no `;` or `&&` chains), with the full path to the game's `tools/dev.py` (it works from
any folder), so every permission prompt shows one clear action. Then, for the new folder: web and web-3d run `python tools/dev.py setup` (a few minutes, downloads the packages), every
engine runs `python tools/dev.py doctor`. Fix what doctor reports, one item at a time, asking before any download or
environment variable. For web, finish with `python tools/dev.py smoke` so they know it works.

## 8. Point the game at the plan
In the new folder, fill `docs/GDD.md` with the approved plan from step 3 (its headings match; leave sections the
interview did not cover as the template has them, and keep the *(Claude's pick)* marks so the game's Claude knows what
to confirm). Set "Current tier" to Toy, and copy the toy scope into the Toy row. Then set `docs/HANDOFF.md` "Next step"
to: "Fast lane in docs/FIRST_HOUR.md: make the toy in docs/GDD.md playable (<the toy, one line>)." The game's own
Claude reads both on its first session. The Art source line tells it which route to take once the toy is fun:
`/dotwork` for Dotwork, `/gen-brief` for a paid service, `/asset-intake` for packs and their own art.

## 9. Hand over (the part people miss)
Explain in two sentences: Claude Code works in one folder at a time, and the game folder has its own Claude setup
(instructions, slash commands, safety rules). So the next step is a **new session in the game folder**. Mention that
Claude Code may ask whether they trust the folder (yes, it is theirs), and that the folder name shown should be the
game's, not the kit's.
Give the exact steps for how they are running Claude now:
- **Desktop app:** start a new session in the Code tab, keep it on **Local**, folder control under the prompt box,
  **Open folder...**, pick `<full path>`.
- **Terminal:** close this session (type `exit`), then:
  ```
  cd "<full path>"
  claude
  ```
- **VS Code:** **File > Open Folder...** > `<full path>` (VS Code reopens in it), then the Claude Code spark icon in
  the left-hand bar, new session.
Then tell them what to type there, one at a time: `/start-session` (Claude replies with a short plan for their
game: that confirms they are in the right place), then:
```
Let's do the fast lane: make my idea playable as a tiny toy.
```
Tell them what comes after: once the toy runs, Claude there asks them to play it, note what they like and what they
don't, and paste the notes back; that loop is how the game gets good.
End with: `START_HERE.md` in the kit has these steps and example things to say, if they lose this window.

## If they only want to look first
Point them at `examples/` (most have a GIF, each has a `HOW_IT_WAS_MADE.md`; `lockpick-mz` is an untested proof of concept) and offer to start a game whenever they are ready.
