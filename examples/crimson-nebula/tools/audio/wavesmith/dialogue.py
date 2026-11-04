#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# dialogue.py
# Purpose : Turns the dialogue you write (data/dialogue.json: speakers, lines, scripted sequences) and the voice files
#           made for it (local_tts.py speech, babble.py gibberish) into what the game reads: dialogue.built.json
#           (format v0: per-character reveal times for a typewriter, subtitle cues, SFX captions, timed sequences),
#           plus SRT / WebVTT subtitle files, and lints it against subtitle reading guidelines.
# Usage   : python tools/audio/wavesmith/wavesmith.py dialogue build data/dialogue.json --root . --events data/audio_events.json \
#               --out data/dialogue/en.built.json                     # --audience children: 17 characters a second
#           python tools/audio/wavesmith/wavesmith.py dialogue lint data/dialogue.json --root .        # --strict: warnings fail
#           python tools/audio/wavesmith/wavesmith.py dialogue lint data/dialogue.json --root . --pseudo    # will translations fit?
#           python tools/audio/wavesmith/wavesmith.py dialogue export data/dialogue/en.built.json --sequence intro --format vtt --out intro.vtt
#           python tools/audio/wavesmith/wavesmith.py dialogue vectors --check     # data/golden/dialogue.json current? (exit 1)
# Needs   : Python 3.8+ only (wavfile.py and flacfile.py read voice durations)
# Exit    : 0 ok, 1 errors found (or warnings with --strict) or stale vectors, 2 usage or unreadable files
# Notes   : Reveal times: exact from a babble .timeline.json; estimated for other voice files (characters spread over
#           the voiced part, with pauses at punctuation: right for a typewriter, not for lip sync); characters at the
#           speaker's cps when there is no audio. One reveal entry per character (code point), as the engines expect.
#           Subtitle style defaults: at most 40 characters a line (Xbox Accessibility Guideline 104 calls longer
#           lines long; Netflix allows 42), 2 lines, 20 characters a second (Netflix, adults; 17 for children),
#           5/6 s minimum and 7 s maximum per cue (Netflix). Exports name the speaker whenever it changes (XAG 104);
#           SRT's inline "NAME: " is laid out within the line width, and lint warns when a cue has no room for it.
#           SFX captions come from audio_events.json events with a "caption" (and "directional": true for sounds
#           whose side of the screen matters; XAG 104 asks for an arrow). The format only ever adds optional fields.
#           reveal_count() is the reference typewriter: a line's reveal list counts only when it has one entry per
#           character of the shown text; otherwise the text types at DEFAULT_CPS, faster when that would not finish
#           within duration_s. Every engine with a dialogue module follows data/golden/dialogue.json.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   build: load dialogue.json -> per line: duration (voice file | babble timeline | text at cps)
#          -> reveal (timeline | estimate over the voiced span | cps) -> cues (break into <= 40-character lines,
#          <= 2 lines a cue, timed from the reveal, stretched to 5/6 s, split past 7 s) -> captions -> sequences
#   lint:  build, then report reading speed, short or long cues, unbreakable words, unknown speakers, missing files
#          --pseudo: each line through the pseudo-locale (40 % longer) over the same timing -> the same cue checks
#   export: a sequence's cues at absolute times -> SRT or WebVTT, speaker named when it changes
#   reveal_count(line, t): reveal list as long as the shown text? entries at or before t
#          else duration 0? everything; else floor(t * max(DEFAULT_CPS, length / duration) + eps), capped
#   vectors: scripted reveal counts through reveal_count -> data/golden/dialogue.json (--write / --check)
import argparse
import hashlib
import json
import math
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audioio  # noqa: E402
import flacfile  # noqa: E402
from wavfile import read_wav_channels  # noqa: E402

VERSION = 1
STYLE = {"max_chars_per_line": 40, "max_lines": 2, "min_cue_s": 0.833, "max_cue_s": 7.0, "max_cps": 20}
CHILDREN_CPS = 17
DEFAULT_CPS = 30                 # typewriter speed without audio (matches the engines' DEFAULT_CPS)
REVEAL_EPS = 1e-9                # t * cps lands on a whole character count despite rounding
GOLDEN = Path(__file__).resolve().parents[3] / "data" / "golden" / "dialogue.json"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
KINDS = ("line", "bark")
INTERRUPTS = ("never", "lower", "always")
PAUSE_WEIGHT = {",": 3, ";": 4, ":": 4, ".": 6, "!": 6, "?": 6, "\n": 6}   # reveal-estimate weight vs 1 for others
VOICED_DB = -40.0                # below the clip's peak: silence before and after the voice
SPEAKER_REPEAT_S = 60.0          # XAG 104: name the speaker again after a pause of 1-2 minutes
DEBUG = False


class ToolError(Exception):
    """Exit 2: usage or a file that cannot be read."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


# ---- Voice files --------------------------------------------------------------------
def read_mono(path):
    """(the loudest channel's level per sample, rate) from WAV, FLAC, OGG Vorbis, or anything ffmpeg reads."""
    try:
        chans, rate = audioio.read_audio(path)
    except audioio.AudioIOError as exc:
        raise ToolError(str(exc))
    return [max(abs(s) for s in frame) for frame in zip(*chans)], rate


def voiced_span(levels, rate):
    """(start s, end s, total s): where the voice is, between the silence before and after it."""
    peak = max(levels, default=0.0)
    total = len(levels) / rate if rate else 0.0
    if peak <= 0:
        return 0.0, total, total
    floor = peak * 10 ** (VOICED_DB / 20)
    loud = [i for i, v in enumerate(levels) if v > floor]
    return loud[0] / rate, (loud[-1] + 1) / rate, total


# ---- Reveal and cues ----------------------------------------------------------------
def estimate_reveal(text, start, end):
    """Character times spread over [start, end] by weight (pauses at punctuation)."""
    chars = list(text)
    weights = [PAUSE_WEIGHT.get(c, 1) for c in chars]
    total = sum(weights) or 1
    out, acc = [], 0.0
    for i, w in enumerate(weights):
        out.append({"i": i, "t": round(start + (end - start) * acc / total, 4)})
        acc += w
    return out


def cps_reveal(text, cps):
    return [{"i": i, "t": round(i / cps, 4)} for i in range(len(list(text)))]


# ---- The typewriter (reference for every engine) -----------------------------------------------------------------
def reveal_count(line, t, length=None):
    """Characters (code points) of the shown text visible t seconds into a built line. `length` is the shown
    text's length when it differs from line["text"] (a translation, the pseudo locale). The reveal list counts only
    when it has one entry per shown character: built for another take or text, it would stop short and the line
    would never finish. Otherwise the text types at DEFAULT_CPS, faster when that would not finish by duration_s."""
    n = len(line.get("text", "")) if length is None else length
    reveal = line.get("reveal") or []
    if len(reveal) == n:
        return sum(1 for r in reveal if r["t"] <= t)
    duration = line.get("duration_s", n / DEFAULT_CPS)
    if duration <= 0:
        return n
    cps = max(DEFAULT_CPS, n / duration)                  # all of it by duration_s, never slower than DEFAULT_CPS
    return min(n, max(0, math.floor(t * cps + REVEAL_EPS)))


def vector_cases():
    """Scripted typewriter questions every engine's dialogue module must answer exactly (whole characters)."""
    hello = "Hello there"                                 # 11 characters
    fits = [{"i": i, "t": round(i * 0.05, 4)} for i in range(len(hello))]
    long_text = "The bakery opens at dawn, and the baker wants every loaf on the shelf before the first cart rolls in. " \
                "Bring flour, bring salt, and bring the key."
    lines = [
        ("a reveal list with one entry per character is followed",
         {"text": hello, "duration_s": 1.0, "reveal": fits}, (0.0, 0.12, 0.25, 0.5, 2.0)),
        ("a reveal list shorter than the text is ignored: 30 per second, the line finishes",
         {"text": hello, "duration_s": 2.0, "reveal": fits[:5]}, (0.0, 0.1, 0.2, 0.3, 2.0)),
        ("a reveal list longer than the text is ignored too",
         {"text": "Hi", "duration_s": 1.0, "reveal": fits[:5]}, (0.0, 0.04, 1.0)),
        ("no reveal list: a long line types faster to finish by its duration",
         {"text": long_text, "duration_s": 2.0}, (0.0, 0.5, 1.0, 1.99, 2.0, 3.0)),
        ("no reveal list and no duration: 30 per second",
         {"text": "Forty-five characters of plain text, no data."}, (0.0, 1.0, 1.5, 2.0)),
        ("a duration of 0 shows the whole line at once",
         {"text": hello, "duration_s": 0}, (0.0,)),
        ("characters are code points, not bytes",
         {"text": "\u00c7a va, Zo\u00eb? \u00a1S\u00ed!", "duration_s": 0.2}, (0.0, 0.1, 0.2)),
    ]
    steps = [{"line": line, "t": t, "expect": reveal_count(line, t)} for _, line, ts in lines for t in ts]
    names = [name for name, _, ts in lines for _ in ts]
    for step, name in zip(steps, names):
        step["about"] = name
    return [{"type": "reveal_count", "name": "typewriter reveal counts", "steps": steps}]


def render_vectors():
    return json.dumps({"version": 1, "tolerance": 0, "about": "tools/audio/wavesmith/dialogue.py vectors --write",
                       "cases": vector_cases()}, indent=1, ensure_ascii=False) + "\n"


def _end_bonus(word):
    """How good a line or cue ending after this word is: sentence end, clause end, or anywhere."""
    return 3 if word[-1:] in ".!?" else 2 if word[-1:] in ",;:" else 0


def split_two(words, width):
    """Best one- or two-line layout of words (None if they cannot fit in two lines of `width`). Netflix and XAG 104:
    break at sensible points (after punctuation), keep a bottom-heavy shape (top line not longer than the bottom)."""
    text = " ".join(words)
    if len(text) <= width:
        return [text]
    best, best_score = None, None
    for k in range(1, len(words)):
        top, bottom = " ".join(words[:k]), " ".join(words[k:])
        if len(top) > width or len(bottom) > width:
            continue
        score = abs(len(top) - len(bottom)) + max(0, len(top) - len(bottom)) - 12 * _end_bonus(words[k - 1])
        if best_score is None or score < best_score:
            best, best_score = [top, bottom], score
    return best


CUE_COST = 20                    # each cue costs this: fewer, fuller cues read better
END_COST = {3: 0, 2: 15, 0: 80}  # a cue ending mid-clause costs more than an extra cue (sentence 3, clause 2)
FILL_COST = 40                   # times (1 - fill)^2: a half-empty cue flashes by


def segment(text, width, max_lines=2):
    """[(first word index, lines)] for the text. Dynamic programming over word positions picks the cheapest set of
    cues: each cue costs CUE_COST, plus END_COST unless it is the last, plus FILL_COST * (1 - fill)^2. So cues end
    at sentences or clauses when they can, and no scrap ("listen.") is left alone at the end. A word longer than
    `width` gets a cue of its own (lint reports it)."""
    words = text.split()
    n = len(words)
    best = [math.inf] * (n + 1)          # best[i]: cheapest cost of laying out words[i:]
    choice = [None] * (n + 1)
    best[n] = 0.0
    for i in range(n - 1, -1, -1):
        for j in range(i + 1, n + 1):
            joined = " ".join(words[i:j])
            if max_lines >= 2:
                layout = split_two(words[i:j], width)
            else:
                layout = [joined] if len(joined) <= width else None
            if layout is None:
                if j == i + 1:                       # an unbreakable word: alone on its line
                    layout = [words[i]]
                else:
                    break
            fill = min(1.0, len(joined) / (width * max_lines))
            cost = CUE_COST + FILL_COST * (1 - fill) ** 2 + (0 if j == n else END_COST[_end_bonus(words[j - 1])])
            if cost + best[j] < best[i]:
                best[i], choice[i] = cost + best[j], (j, layout)
    cues, i = [], 0
    while i < n:
        j, layout = choice[i]
        cues.append((i, layout))
        i = j
    return cues


def make_cues(text, reveal, duration, style):
    """Cues of at most max_lines lines; each starts when its first character is revealed, ends when the next begins
    (the last at the line's end); stretched to the minimum length, split when longer than the maximum."""
    segments = segment(text, style["max_chars_per_line"], style["max_lines"])
    groups = [lines for _, lines in segments]
    # each cue starts when its first word's first character is revealed (word positions, never a text search:
    # "the" also appears earlier in "before the kingdom")
    word_starts = [m.start() for m in re.finditer(r"\S+", text)]
    times = [reveal[word_starts[w]]["t"] if word_starts[w] < len(reveal) else 0.0 for w, _ in segments]
    cues = []
    for k, g in enumerate(groups):
        start = times[k]
        end = times[k + 1] if k + 1 < len(groups) else max(duration, start)
        if end - start < style["min_cue_s"]:
            end = start + style["min_cue_s"]                    # readers need it; the next cue starts later
        cues.append({"start": round(start, 3), "end": round(end, 3), "lines": g})
    for k in range(1, len(cues)):                               # no overlap after stretching
        if cues[k]["start"] < cues[k - 1]["end"]:
            cues[k]["start"] = cues[k - 1]["end"]
            cues[k]["end"] = round(max(cues[k]["end"], cues[k]["start"] + style["min_cue_s"]), 3)
    out = []
    for c in cues:                                              # split anything past the maximum evenly
        n = max(1, math.ceil((c["end"] - c["start"]) / style["max_cue_s"] - 1e-9))
        if n == 1 or len(c["lines"]) == 1:
            out.append(c)
            continue
        step = (c["end"] - c["start"]) / len(c["lines"])
        for j, ln in enumerate(c["lines"]):
            out.append({"start": round(c["start"] + j * step, 3), "end": round(c["start"] + (j + 1) * step, 3),
                        "lines": [ln]})
    return out


def cue_warnings(where, cues, style):
    """Reading speed, cue length and unbreakable words, as warnings."""
    out = []
    for c in cues:
        chars = sum(len(x) for x in c["lines"])
        span = c["end"] - c["start"]
        if span > 0 and chars / span > style["max_cps"] + 1e-9:
            out.append(f"{where}: \"{' '.join(c['lines'])[:40]}\" needs {chars / span:.1f} characters a second "
                       f"(guideline {style['max_cps']}): shorten the text or slow the line")
        if span > style["max_cue_s"] + 1e-9:
            out.append(f"{where}: \"{' '.join(c['lines'])[:40]}\" stays {span:.1f} s (guideline at most "
                       f"{style['max_cue_s']:.0f} s): split the line or trim the silence in its audio")
        for x in c["lines"]:
            if len(x) > style["max_chars_per_line"]:
                out.append(f"{where}: \"{x[:30]}...\" is {len(x)} characters with no place to break")
    return out


def pseudo_warnings(built):
    """What happens to each line when it is translated and the voice stays: the text through the kit's pseudo-locale
    (tools/golden_vectors.py pseudo(): accented, 40 % longer, bracketed), revealed over the same voice timing (each
    pseudo character at the time of the original character it stretches over), cut into cues with the same style.
    Captions are one line each: they must still fit the line width."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # tools/: golden_vectors.py
    from golden_vectors import pseudo
    style, out = built["style"], []
    for lid, ln in built["lines"].items():
        ptext = pseudo(ln["text"])
        n, m = len(ln["reveal"]), len(ptext)
        reveal = [{"i": k, "t": ln["reveal"][min(n - 1, k * n // m)]["t"]} for k in range(m)]
        cues = make_cues(ptext, reveal, ln["duration_s"], style)
        out += [w.replace(f"line {lid}: ", f"line {lid} (pseudo, +40 %): ", 1)
                for w in cue_warnings(f"line {lid}", cues, style)]
    for cid, c in built["captions"].items():
        ptext = pseudo(c["text"])
        if len(ptext) > style["max_chars_per_line"]:
            out.append(f"caption {cid} (pseudo, +40 %): {len(ptext)} characters on one line (at most "
                       f"{style['max_chars_per_line']}): keep captions short, \"[door]\" not \"[the old door creaks]\"")
    return out


# ---- Build --------------------------------------------------------------------------
def load_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(f"cannot read {what} {path}: {exc}")


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def build(src_path, root=".", events_path=None, audience="adults"):
    """(built dict, errors list, warnings list). A dialogue file that is not a JSON object is a ToolError; a value of
    the wrong type anywhere inside is a named error, never a traceback (built is None then)."""
    raw_bytes = Path(src_path).read_bytes()
    src = load_json(src_path, "dialogue")
    if not isinstance(src, dict):
        raise ToolError(f"{src_path} must hold one JSON object (version, speakers, lines, sequences), "
                        f"not a {type(src).__name__}")
    try:
        return _build(src, raw_bytes, root, events_path, audience)
    except (TypeError, AttributeError, KeyError) as exc:   # a value of a type no check foresaw: named, not a crash
        return None, [f"a value has the wrong type ({type(exc).__name__}: {exc}); compare the file with the format "
                      f"in docs/resources/audio.md"], []


def _build(src, raw_bytes, root, events_path, audience):
    errors, warnings = [], []
    style = dict(STYLE, max_cps=CHILDREN_CPS if audience == "children" else STYLE["max_cps"])
    if src.get("version") != VERSION:
        errors.append("version must be 1")
    speakers = src.get("speakers")
    speakers = {} if speakers is None else speakers
    if not isinstance(speakers, dict):
        errors.append("speakers must be an object (speaker id to name, cps, color)")
        speakers = {}
    broken = set()                    # speakers already reported: their lines are skipped without a second error
    for spk, sp in speakers.items():
        if not isinstance(sp, dict):
            errors.append(f"speaker {spk}: must be an object (name, cps, color)")
            broken.add(spk)
        elif "cps" in sp and not (is_number(sp["cps"]) and sp["cps"] > 0):
            errors.append(f"speaker {spk}: cps must be a number above 0 (characters a second; leave it out for "
                          f"{DEFAULT_CPS})")
            broken.add(spk)
    lines_in = src.get("lines") or []
    if not isinstance(lines_in, list):
        errors.append("lines must be a list (in the order they are written)")
        lines_in = []
    root = Path(root)
    built_lines, seen = {}, set()
    for n, ln in enumerate(lines_in):
        if not isinstance(ln, dict):
            errors.append(f"line #{n}: must be an object (id, speaker, text), not {json.dumps(ln)[:40]}")
            continue
        lid = ln.get("id", f"#{n}")
        if not isinstance(lid, str):
            errors.append(f"line #{n}: id must be a string, not {json.dumps(lid)[:40]}")
            continue
        where = f"line {lid}"
        if not ID_RE.match(lid):
            errors.append(f"{where}: id must be lowercase ASCII letters, digits, _ . - (it is the localization key)")
        if lid in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(lid)
        spk = ln.get("speaker")
        if not isinstance(spk, str) or spk not in speakers:
            errors.append(f"{where}: speaker {spk!r} is not in speakers")
            continue
        if spk in broken:
            continue
        sp = speakers[spk]
        if not sp.get("name"):
            warnings.append(f"speaker {spk}: no name; subtitles must name the speaker when it changes (XAG 104)")
        text = ln.get("text", "")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{where}: text is empty")
            continue
        kind = ln.get("kind", "line")
        if kind not in KINDS:
            errors.append(f"{where}: kind must be line or bark")
        if ln.get("interrupt", "lower") not in INTERRUPTS:
            errors.append(f"{where}: interrupt must be never, lower or always")
        if kind == "bark" and not ln.get("cooldown_s"):
            warnings.append(f"{where}: a bark without cooldown_s can repeat back to back")
        count = len(list(text))
        audio, timeline = ln.get("audio"), ln.get("timeline")
        if not all(v is None or isinstance(v, str) for v in (audio, timeline)):
            errors.append(f"{where}: audio and timeline must be paths (strings) relative to the root")
            continue
        reveal, source, duration = None, "text", count / sp.get("cps", DEFAULT_CPS)
        if audio:
            if not (root / audio).is_file():
                errors.append(f"{where}: audio {audio} not found under the root")
            else:
                levels, rate = read_mono(root / audio)
                start, end, duration = voiced_span(levels, rate)
                reveal, source = estimate_reveal(text, start, end), "estimated"
        if timeline:
            if not (root / timeline).is_file():
                errors.append(f"{where}: timeline {timeline} not found under the root")
            else:
                tl = load_json(root / timeline, "timeline")
                rv = tl.get("reveal") or []
                if tl.get("text") not in (None, text) or len(rv) != count:
                    errors.append(f"{where}: {timeline} was made for another text (re-render it with babble.py)")
                else:
                    reveal, source = [{"i": r["i"], "t": r["t"]} for r in rv], "babble"
                    if not audio:
                        duration = tl.get("seconds", duration)
        if reveal is None:
            reveal = cps_reveal(text, sp.get("cps", DEFAULT_CPS))
        cues = make_cues(text, reveal, duration, style)
        warnings += cue_warnings(where, cues, style)
        name = sp.get("name", spk)
        if cues and named_lines(name, cues[0]["lines"], style) is None:
            warnings.append(f"{where}: SRT puts \"{srt_prefix(name)}\" in front when the speaker changes, and the first "
                            f"cue no longer fits {style['max_lines']} lines of {style['max_chars_per_line']} "
                            f"characters: shorten the speaker's name or the line's opening")
        entry = {"speaker": spk, "name": sp.get("name", spk), "color": sp.get("color", "#FFFFFF"), "text": text,
                 "kind": kind, "priority": ln.get("priority", 50), "interrupt": ln.get("interrupt", "lower"),
                 "cooldown_s": ln.get("cooldown_s", 0), "duration_s": round(duration, 3), "reveal_source": source,
                 "reveal": reveal, "cues": cues}
        if audio:
            entry["audio"] = audio
        built_lines[lid] = entry
    captions = {}
    if events_path:
        ev = load_json(events_path, "audio events")
        for name, e in sorted((ev.get("events") or {}).items()):
            if e.get("caption"):
                captions[name] = {"text": e["caption"], "priority": e.get("caption_priority", 30),
                                  "min_s": e.get("caption_min_s", 1.0), "directional": bool(e.get("directional", False))}
    sequences = {}
    seq_in = src.get("sequences")
    seq_in = {} if seq_in is None else seq_in
    if not isinstance(seq_in, dict):
        errors.append("sequences must be an object (sequence name to a list of steps)")
        seq_in = {}
    for sname, steps in sorted(seq_in.items()):
        if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
            errors.append(f"sequence {sname}: must be a list of steps, each an object with a line")
            continue
        out, ends = [], {}
        for k, step in enumerate(steps):
            lid = step.get("line")
            if not isinstance(lid, str) or lid not in built_lines:
                errors.append(f"sequence {sname} step {k}: unknown line {lid!r}")
                continue
            if "after" in step:
                if not isinstance(step["after"], str) or step["after"] not in ends:
                    errors.append(f"sequence {sname} step {k}: 'after' must name an earlier step's line")
                    continue
                start = ends[step["after"]] + step.get("gap_s", 0.0)
            else:
                start = step.get("at", 0.0)
            end = start + built_lines[lid]["duration_s"]
            ends[lid] = end
            out.append({"line": lid, "start": round(start, 3), "end": round(end, 3)})
        sequences[sname] = out
    built = {"version": VERSION, "locale": src.get("locale", "en"), "built_by": "tools/audio/wavesmith/dialogue.py",
             "source_sha256": hashlib.sha256(raw_bytes).hexdigest(), "style": style, "lines": built_lines,
             "captions": captions, "sequences": sequences}
    return built, errors, warnings


# ---- Export -------------------------------------------------------------------------
def fmt_time(t, sep):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def sequence_cues(built, name):
    if name not in built.get("sequences", {}):
        raise ToolError(f"no sequence {name!r} (have: {', '.join(built.get('sequences', {})) or 'none'})")
    out, last_speaker, last_end = [], None, -1e9
    for step in built["sequences"][name]:
        line = built["lines"][step["line"]]
        for c in line["cues"]:
            start, end = step["start"] + c["start"], step["start"] + c["end"]
            named = line["speaker"] != last_speaker or start - last_end > SPEAKER_REPEAT_S
            out.append({"start": start, "end": end, "lines": list(c["lines"]), "name": line["name"] if named else None})
            last_speaker, last_end = line["speaker"], end
    return out


def srt_prefix(name):
    return f"{name.upper()}: "


def named_lines(name, lines, style):
    """A cue's lines with "NAME: " in front (SRT has no voice tag, so players show the name inline), laid out again
    when the first line would pass the line width. None when the cue no longer fits its lines."""
    first = srt_prefix(name) + (lines[0] if lines else "")
    width = style["max_chars_per_line"]
    if len(first) <= width:
        return [first] + list(lines[1:])
    words = [srt_prefix(name).strip()] + [w for x in lines for w in x.split()]   # the name stays one piece
    if style["max_lines"] >= 2:
        return split_two(words, width)
    return [" ".join(words)] if len(" ".join(words)) <= width else None


def to_srt(cues, style=STYLE, warnings=None):
    """SRT text; the speaker's name goes in front of the cue that names it, within the line width when it fits
    (otherwise in front anyway, with a note in warnings when a list is given)."""
    blocks = []
    for n, c in enumerate(cues, 1):
        lines = list(c["lines"])
        if c["name"]:
            laid = named_lines(c["name"], lines, style)
            if laid is None:
                laid = [srt_prefix(c["name"]) + (lines[0] if lines else "")] + lines[1:]
                if warnings is not None:
                    warnings.append(f"cue {n}: \"{laid[0][:40]}\" is {len(laid[0])} characters with the speaker's name "
                                    f"in front (at most {style['max_chars_per_line']}): shorten the name or the line")
            lines = laid
        blocks.append(f"{n}\r\n{fmt_time(c['start'], ',')} --> {fmt_time(c['end'], ',')}\r\n" + "\r\n".join(lines))
    return "\r\n\r\n".join(blocks) + "\r\n"


def vtt_escape(text):
    """WebVTT cue text is markup: & < > must be written as entities, or "<b>" turns bold and "-->" ends the cue."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_vtt(cues):
    blocks, speaker = ["WEBVTT"], None
    for c in cues:
        speaker = c["name"] or speaker
        # a blank line would end the cue early, so empty lines are left out
        body = "\n".join(vtt_escape(line) for line in c["lines"] if line.strip())
        voice = f"<v {vtt_escape(speaker)}>" if speaker else ""
        blocks.append(f"{fmt_time(c['start'], '.')} --> {fmt_time(c['end'], '.')}\n{voice}{body}")
    return "\n\n".join(blocks) + "\n"


# ---- Commands -----------------------------------------------------------------------
def report(errors, warnings):
    for e in errors:
        print(f"[FAIL] {e}")
    for w in warnings:
        print(f"[warn] {w}")


def cmd_build(args):
    built, errors, warnings = build(args.dialogue, args.root, args.events, args.audience)
    report(errors, warnings)
    if errors:
        print(f"[FAIL] {len(errors)} error(s): nothing written")
        return 1
    out = Path(args.out)
    if out.exists() and not args.overwrite:
        raise ToolError(f"{out} exists (use --overwrite)")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(built, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"[ OK ] {out.as_posix()}: {len(built['lines'])} lines, {len(built['captions'])} captions, "
          f"{len(built['sequences'])} sequences, {len(warnings)} warning(s)")
    return 0


def cmd_lint(args):
    built, errors, warnings = build(args.dialogue, args.root, args.events, args.audience)
    if args.pseudo and not errors:
        warnings += pseudo_warnings(built)
    report(errors, warnings)
    print(f"[{'FAIL' if errors else ' OK '}] {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors or (warnings and args.strict) else 0


def cmd_export(args):
    built = load_json(args.built, "built dialogue")
    cues = sequence_cues(built, args.sequence)
    notes = []
    text = to_srt(cues, built.get("style", STYLE), notes) if args.format == "srt" else to_vtt(cues)
    for x in notes:
        print(f"[warn] {x}")
    out = Path(args.out)
    if out.exists() and not args.overwrite:
        raise ToolError(f"{out} exists (use --overwrite)")
    out.write_bytes(text.encode("utf-8"))
    print(f"[ OK ] {out.as_posix()}: {len(cues)} cues ({args.format})")
    return 0


def cmd_vectors(args):
    text = render_vectors()
    if args.write:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes(text.encode("utf-8"))
        print(f"[ OK ] wrote {GOLDEN}")
        return 0
    current = GOLDEN.read_bytes().decode("utf-8") if GOLDEN.exists() else None
    if current != text:
        print(f"[FAIL] {GOLDEN} is stale or missing: run dialogue.py vectors --write")
        return 1
    print(f"[ OK ] {GOLDEN} is current")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description="Dialogue for games: built file (typewriter reveal, subtitle cues, SFX "
                                             "captions), SRT / WebVTT export, and subtitle linting.",
                                 epilog="Exit codes: 0 ok, 1 errors (or warnings with --strict) or stale vectors, "
                                        "2 usage.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="tracebacks")
    src = argparse.ArgumentParser(add_help=False)
    src.add_argument("dialogue", help="the dialogue.json you write")
    src.add_argument("--root", default=".", help="folder the audio and timeline paths are relative to")
    src.add_argument("--events", help="audio_events.json: events with a caption become SFX captions")
    src.add_argument("--audience", choices=("adults", "children"), default="adults",
                     help="reading speed guideline: 20 characters a second, or 17 for children")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build", parents=[common, src], help="write dialogue.built.json")
    b.add_argument("--out", required=True)
    b.add_argument("--overwrite", action="store_true")
    li = sub.add_parser("lint", parents=[common, src], help="errors and subtitle guideline warnings")
    li.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    li.add_argument("--pseudo", action="store_true",
                    help="also check every line 40 %% longer (the pseudo-locale) over the same voice timing: will a "
                         "translation still be readable?")
    ex = sub.add_parser("export", parents=[common], help="a sequence as SRT or WebVTT")
    ex.add_argument("built", help="a dialogue.built.json")
    ex.add_argument("--sequence", required=True)
    ex.add_argument("--format", choices=("srt", "vtt"), default="srt")
    ex.add_argument("--out", required=True)
    ex.add_argument("--overwrite", action="store_true")
    ve = sub.add_parser("vectors", parents=[common], help="the typewriter golden vectors (data/golden/dialogue.json)")
    mode = ve.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="rewrite the file from the reference")
    mode.add_argument("--check", action="store_true", help="exit 1 when the file is stale or missing")
    return ap


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = build_parser()
    args = ap.parse_args(argv)
    DEBUG = getattr(args, "debug", False)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        return {"build": cmd_build, "lint": cmd_lint, "export": cmd_export, "vectors": cmd_vectors}[args.cmd](args)
    except ToolError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
