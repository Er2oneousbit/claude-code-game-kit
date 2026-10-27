# Start here: make a game with Claude

New to all of this? Good, this page is for you. You do not need to know how to code, set up projects, or use a
terminal much. Claude does the setup; you bring the idea and say what feels fun.

**What this kit is:** a starter set that turns an empty folder into a game project Claude knows how to work on: how to
run the game, test it, keep notes between sessions, and not break things. Without it, Claude guesses. With it, Claude
follows a plan. It is free and open source (MIT license): you can read every file.

> Reading this on your computer and it looks messy (stars, pipes, links you cannot click)? Open it on the kit's GitHub
> page instead, where it is formatted.

## What you need
- **A paid Claude plan.** Claude Code comes with the Pro, Max, Team and Enterprise plans (or a pay-as-you-go
  Anthropic API account). The free plan does not include it. Plans: https://claude.com/pricing
- **A computer** running Windows 10 or newer. The kit was tested on Windows. macOS and Linux should work for the
  browser engines (the scaffolder ran on Linux in an earlier version) but were not tested for this release, so expect
  to ask Claude for help if something differs.
- **Some time for installs.** Setup time depends on your downloads and the engine; a browser game needs the fewest.

## Step 1: Install Claude Code
Pick one:
- **Easiest: the Claude desktop app.** No terminal needed. Download it (Windows: https://claude.com/download, Mac and
  Linux (beta): https://code.claude.com/docs/en/desktop-quickstart), sign in, and click the **Code** tab at the top of the
  sidebar.
- **VS Code.** Already use VS Code (version 1.94 or newer)? Press `Ctrl+Shift+X` (Mac: `Cmd+Shift+X`), search for
  **Claude Code**, click **Install**, and sign in when it first opens.
- **The terminal version.** Follow https://code.claude.com/docs/en/terminal-guide : it shows how to open a terminal and
  paste the one install line.

## Step 2: Install Python
The kit's helper scripts need Python 3.8 or newer.
- **Windows and Mac:** https://www.python.org/downloads/ . If the installer shows a box saying
  **"Add python.exe to PATH"**, tick it.
- **Linux:** usually installed already.

Not sure it worked? Skip ahead: Claude checks in step 4 and helps you fix it.

Also recommended: **Git** (https://git-scm.com/downloads, click Next on every screen). It lets Claude save your
progress so you can undo mistakes. You do not need to learn it.

Do not worry about the game engine yet. Claude picks one with you in step 4. **First game? When Claude asks, say you
want it in the browser:** that needs the fewest installs. Big engines like Unity and Unreal are huge downloads.

## Step 3: Get the kit
1. On the kit's GitHub page: green **Code** button, then **Download ZIP**.
2. **Unzip it properly.** Windows: right-click the ZIP, **Extract All...**. Mac: double-click the ZIP. (Opening the ZIP
   in Windows Explorer without extracting looks like a folder, but Claude cannot work in it.)
3. **Move it somewhere short and simple,** like `C:\Games\` on Windows or a `Games` folder in your home folder on a
   Mac. Avoid folders synced to OneDrive or iCloud: game projects have thousands of small files that fight the sync.
4. Check: you have a folder with this `START_HERE.md` file in it. That is the kit folder. (If you see a folder inside a
   folder with the same name, the inner one is the kit folder.)

## Step 4: Ask Claude to set up your game
Open Claude Code **in the kit folder**:
- **Desktop app:** in the Code tab, look at the row under the message box. Make sure it runs on your computer
  (**Local**, not Cloud), then click the folder control next to it, **Open folder...**, and pick the kit folder.
- **VS Code:** **File > Open Folder...**, pick the kit folder, then click the Claude Code icon (a small spark) in the
  left-hand bar and start a new session.
- **Terminal:** type `cd ` (with a space), drag the kit folder onto the terminal window, press Enter, then type
  `claude` and press Enter.

Claude Code may first ask whether you **trust this folder**. For the kit (and later your own game folder) the answer
is yes.

Then type:
```
Start
```
(Or say it in your own words: "I want to make a game" works too.) Claude gives your project a random codename (like
`Project_Cobalt_Wyvern`; rename it whenever you like) and interviews you about your game, one question at a time (mostly click-to-pick):
what it is, how it plays, how it looks, how big the first version is. Say "you decide" to anything you do not care
about. From your answers it writes a one-page game plan with you. Once you say it looks good, Claude picks the right
tools, checks your installs, and creates a **new folder for your game** next to the kit, with the plan inside.

**About the permission questions.** Before Claude runs a command or changes a file, Claude Code may ask you first.
Claude says what each step does. If it sounds right, choose **Yes**. If you are not sure, choose **No** and ask
"what does that do, and is it safe?". Saying No never breaks anything; Claude just explains or finds another way.

## Step 5: Open your game folder and start building
Claude finishes by telling you exactly where your game folder is. Now **start a new session in that folder** (this
matters: the game folder has its own Claude setup):
- **Desktop app:** start a new session and pick the game folder, the same way as in step 4.
- **VS Code:** **File > Open Folder...**, pick the game folder (VS Code reopens in it), then a new Claude Code session.
- **Terminal:** type `exit`, then `cd` into the game folder and type `claude`, as in step 4.

Check that the folder name shown is your game's name, not the kit. Then type `/start-session` and press Enter. Claude
replies with a short plan for your game (that is how you know you are in the right place). Then type:
```
Let's do the fast lane: make my idea playable as a tiny toy.
```
> ⚠️ **Your first build will look crude, on purpose.** Simple placeholder pixel-art characters drawn in code (a little hero with a walk and a punch, not dots or boxes) on plain backgrounds. The first job is to find out
> whether your game is *fun*, and that only takes the mechanics. Nice art, animation and music come after the fun is
> proven: polishing a game that turns out not to work wastes time, usage and money.

In your first session you have something you can play. Say **"run the game"**: a browser game opens in your browser,
Godot and C++ open a game window, and Unity and Unreal open their editor (press Play there). Then you play it, say what feels wrong, and Claude fixes it. That loop is the whole job.

## Things to say to Claude
- "Run the game."
- "The jump feels floaty. Make it snappier."
- "Add an enemy that walks back and forth."
- "Something broke: <paste the error>." (Claude follows a step-by-step bug hunt.)
- "Find me free music for a spooky level." (Claude checks licenses before anything goes in.)
- "What should we do next?"
- `/end-session` before you stop, so next time Claude remembers where you were. `/start-session` when you come back.
- `/stuck` when you and Claude are going in circles.

## When something goes wrong
- **During setup** (Python not found, an install failed, an error you do not understand): copy the exact message
  into Claude and say "help me fix this step by step".
- **"Usage limit reached":** nothing is lost. Your plan's limits reset after a while, and Claude Code shows when.
  Come back then, open your game folder, and type `/start-session`.
- **The game broke after a change:** say "that broke it, undo the last change". Claude can usually undo its own
  recent edits. Even safer: whenever something works, say **"commit this"**, and you can always go back to that point
  (this is what Git is for).

## Words you will see
| Word | Means |
|---|---|
| Engine | The program that runs your game: Godot, Unity, a web browser (Phaser, Three.js) |
| GDD | Game design doc: one page saying what your game is. Claude fills it in with you |
| Vertical slice | One small, finished-feeling piece of the game, before making more of it |
| Playtest | Someone plays it while you watch (or they tell you what they felt) |
| Commit | A saved snapshot of the project you can go back to |
| `dev.py` | The kit's helper that runs, tests and builds your game, the same way for every engine |

## Good to know
- **Fun first, shapes first.** If your game is not fun with plain boxes and circles, nice art will not save it. Get it
  fun, then add one new thing at a time, play until it is fun again, then the next. Fancy graphics come last.
- **Small first.** One screen, one action, then grow. "Make me an open-world RPG" in one go never works.
- **Fresh sessions stay sharp.** Long sessions use more of your limit; `/end-session` and a fresh start keep it lean.
- **Free assets.** The kit lists free music, sounds and art with their licenses (`docs/RESOURCES.md` in your game).
- **Want to see finished examples first?** The `examples/` folder has nine small games (one an untested RPG Maker
  MZ proof of concept), most with a GIF, each with a step-by-step story of how it was made.
- **Prefer to do the setup yourself?** The main `README.md` has the manual commands.
