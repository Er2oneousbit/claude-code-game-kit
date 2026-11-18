#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# l10n.py
# Purpose : The localization round trip: the game's strings (data/i18n/<locale>.json, every engine) out to a
#           translator's file with context and length budgets, machine drafts from a model on this machine, a review
#           status per line, the reviewed lines back into the game's table with validation, and a check of every
#           table, the pseudo-locale and the game's fonts (SOP-19 section 5).
# Usage   : python tools/i18n/l10n.py export ru                      # l10n/ru.xlf (XLIFF 1.2; --format csv)
#           python tools/i18n/l10n.py draft ru --backend lmstudio      # machine drafts, marked for review
#           python tools/i18n/l10n.py review ru                        # accept / fix / reject each draft
#           python tools/i18n/l10n.py import ru                        # reviewed lines into data/i18n/ru.json
#           python tools/i18n/l10n.py check                            # tables, plurals, lengths, pseudo, fonts
#           python tools/i18n/l10n.py <command> -h                     # every option of a command
# Exit    : 0 ok, 1 a check failed or a line was refused (each one is listed), 2 usage or environment problem (no
#           en.json, a broken file, no model server answering)
# Notes   : Files: l10n/<locale>.xlf or .csv (the translator's file, commit it), l10n/context.json (optional, yours:
#           {"menu.play": {"note": "main menu button", "max": 12}} or {"key": "a note"}), l10n/.gdignore (so Godot
#           does not import the CSV as a translation). Never put these in data/i18n/: every engine loads each JSON
#           there as a language. Length: "max" counts the characters a player sees (placeholders count 0); without
#           a max, a line longer than the pseudo-locale's 40 % growth is a warning (the pseudo smoke run proved only
#           that much fits). Drafts are never imported until a person accepts them (review, or a translation tool
#           that marks them translated). Kit tools: standard library only; check_i18n.py next door does the
#           completeness check before a language ships.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   export : en + existing table + context -> units (plus plural categories the language needs that English lacks)
#            -> merge pending drafts from an older file with the same English -> write file
#   draft  : each empty unit -> backend -> reject a reply that changes placeholders -> store as a draft + flags
#   review : each draft -> accept (re-validated) / edit / reject; or --accept/--set/--reject from the command line
#   import : refuse a file that lost units; per unit: English key? same English as now? placeholders? length?
#            reviewed? -> plural groups complete? -> write the table in en.json's layout
#   check  : every table: placeholders, plural categories, lengths; pseudo of English: lengths; every font:
#            every character of every table and of the pseudo-locale
import argparse
import difflib
import json
import os
import sys
import traceback
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import l10n_drafts as drafts  # noqa: E402
import l10n_exchange as ex  # noqa: E402
import l10n_fonts as fonts  # noqa: E402
import l10n_rules as rules  # noqa: E402
import l10n_tables as tables  # noqa: E402  (puts tools/ on the path)
import check_i18n  # noqa: E402

# ---- constants -------------------------------------------------------------------------------------------------
PROJECT = HERE.parents[1]               # tools/i18n/l10n.py -> the game's root
I18N_DIR = "data/i18n"
WORK_DIR = "l10n"
CONTEXT_FILE = "context.json"
BASE = "en"
SKIP_LOCALES = {"pseudo"}
FORMATS = {"xliff": ".xlf", "csv": ".csv"}
BACK_MIN = 0.5                          # back-translation similarity below this flags a draft (never passes one)
LONG_TAG = "longer than the pseudo-locale tested:"   # the length warning, summed up unless --lengths
SHOW = 40                               # lines listed per problem kind before "(+N more)"
DEBUG = False


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


class UsageError(Exception):
    pass


def read_file(path):
    """A text file exactly as stored (no newline translation: a CRLF table stays CRLF). Python 3.8's Path has no
    write_text(newline=), so both directions go through open()."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_file(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ---- the project's files ---------------------------------------------------------------------------------------
class Project(object):
    def __init__(self, root, i18n_dir=None, work_dir=None):
        self.root = Path(root)
        self.i18n = Path(i18n_dir) if i18n_dir else self.root / I18N_DIR
        self.work = Path(work_dir) if work_dir else self.root / WORK_DIR
        self.en_path = self.i18n / f"{BASE}.json"
        if not self.en_path.is_file():
            raise UsageError(f"no {self.en_path} (the English table every other language is checked against)")
        try:
            self.en_text = read_file(self.en_path)
            self.en = tables.load(self.en_path)
        except (ValueError, OSError, UnicodeDecodeError) as e:
            raise UsageError(str(e))
        self.context = self._context()

    def _context(self):
        path = self.work / CONTEXT_FILE
        if not path.is_file():
            return {}
        try:
            raw = json.loads(read_file(path))
        except (ValueError, OSError, UnicodeDecodeError) as e:
            raise UsageError(f"{path}: not readable JSON ({e})")
        out = {}
        for key, v in (raw.items() if isinstance(raw, dict) else []):
            if key.startswith("_"):
                continue
            if isinstance(v, str):
                v = {"note": v}
            if not isinstance(v, dict) or not isinstance(v.get("max", 0), int):
                raise UsageError(f"{path}: {key!r} must be a note string or {{\"note\": ..., \"max\": <int>}}")
            out[key] = v
        return out

    def table_path(self, locale):
        return self.i18n / f"{locale}.json"

    def table(self, locale):
        p = self.table_path(locale)
        if not p.is_file():
            return {}, None
        try:
            return tables.load(p), read_file(p)
        except (ValueError, OSError, UnicodeDecodeError) as e:
            raise UsageError(str(e))

    def locales(self):
        return sorted(p.stem for p in self.i18n.glob("*.json") if p.stem != BASE and p.stem not in SKIP_LOCALES)

    def exchange_path(self, locale, explicit=None, fmt=None):
        if explicit:
            return Path(explicit)
        if fmt:
            return self.work / f"{locale}{FORMATS[fmt]}"
        for ext in FORMATS.values():
            if (self.work / f"{locale}{ext}").is_file():
                return self.work / f"{locale}{ext}"
        raise UsageError(f"no {self.work / (locale + '.xlf')} or .csv: run `l10n.py export {locale}` first")


def check_locale(locale):
    if locale in (BASE,) or locale in SKIP_LOCALES or not locale.replace("_", "").replace("-", "").isalnum():
        raise UsageError(f"{locale!r} is not a language to translate into (en is the source, pseudo is generated)")


# ---- units: what one language needs -----------------------------------------------------------------------------
def plural_extras(en, locale):
    """{key: source key} for plural categories the language needs that English lacks (ru: demo.hits.few -> .other)."""
    cats = rules.categories(locale) or ("one", "other")
    out = {}
    for base, have in rules.plural_groups(en).items():
        for cat in cats:
            if cat not in have:
                out[f"{base}.{cat}"] = f"{base}.other"
    return out


def expected_source(en, extras, key):
    """The English a unit must carry: its own, or the .other line for an added plural category."""
    if key in en:
        return en[key]
    if key in extras:
        return en[extras[key]]
    return None


def build_units(proj, locale):
    table, _ = proj.table(locale)
    extras = plural_extras(proj.en, locale)
    cats = rules.categories(locale)
    units = []
    keys = list(proj.en)
    # an added plural category goes right after its group's last English line
    for extra, src in extras.items():
        base = src.rsplit(".", 1)[0]
        last = max(i for i, k in enumerate(keys) if rules.split_plural(k)[0] == base)
        keys.insert(last + 1, extra)
    for key in keys:
        source = expected_source(proj.en, extras, key)
        ctx = proj.context.get(key, {})
        notes = [ctx.get("note", "")] if ctx.get("note") else []
        base, cat = rules.split_plural(key)
        if cat and base in rules.plural_groups(proj.en):
            used = ", ".join(cats) if cats else "unknown to l10n.py (verify in CLDR)"
            hint = f"plural form '{rules.CATEGORY_HINT[cat]}'; {rules.language_name(locale)} uses: {used}"
            if key in extras:
                hint += "; the English shown is the 'other' form"
            elif cats and cat not in cats:
                hint += f"; {locale} never picks '{cat}': copy your 'other' form"
            notes.append(hint)
        u = ex.Unit(key, source, note=" | ".join(notes), max_len=ctx.get("max"))
        if key in table:
            done = table[key] != source or not needs_translation(source)
            u.target, u.state = (table[key], "translated") if done else ("", ex.STATE_EMPTY)
        elif nothing_to_translate(source):      # "{name}", "{w} x {h}": only placeholders and punctuation
            u.target, u.state = source, "translated"
        units.append(u)
    return units


def needs_translation(text):
    """check_i18n's rule: False for placeholders and punctuation only, or a listed name or unit."""
    return check_i18n.needs_translation(text)


def nothing_to_translate(text):
    """Only placeholders and punctuation: the same in every language (a listed name such as "English" is not:
    as language.name it is the language's own name)."""
    return bool(check_i18n.NOTHING_TO_TRANSLATE.match(rules.PLACEHOLDER.sub("", text)))


def merge_pending(units, old_units):
    """Keep drafts and review work from an older file for lines still untranslated in the table and unchanged."""
    old = {u.key: u for u in old_units}
    kept = 0
    for u in units:
        o = old.get(u.key)
        if o and not u.target and o.source == u.source and o.target:
            u.target, u.state, u.qualifier = o.target, o.state, o.qualifier
            u.tool_notes, u.other_notes = o.tool_notes, o.other_notes
            kept += 1
        elif o:
            u.other_notes = o.other_notes
    return kept


# ---- validating one line ---------------------------------------------------------------------------------------
def line_problems(source, target, max_len):
    """(errors, warnings) for a translation of source."""
    errors, warnings = [], []
    if target.strip() == "" and source.strip() != "":
        errors.append("empty")
        return errors, warnings
    p = rules.placeholder_problem(source, target)
    if p:
        errors.append(p)
    n = rules.visible_len(target)
    if max_len and n > max_len:
        errors.append(f"{n} characters, the budget is {max_len}")
    elif not max_len and n > rules.pseudo_budget(source) and rules.visible_len(source) > 0:
        warnings.append(f"{n} characters, {LONG_TAG} {rules.pseudo_budget(source)}")
    return errors, warnings


# ---- export ----------------------------------------------------------------------------------------------------
def cmd_export(proj, a):
    check_locale(a.locale)
    path = proj.exchange_path(a.locale, a.out, a.format or "xliff")
    units = build_units(proj, a.locale)
    kept = 0
    if path.is_file():
        try:
            old_units, _ = ex.read(path)
        except ValueError as e:
            raise UsageError(f"{e} (move it away to export afresh)")
        kept = merge_pending(units, old_units)
    path.parent.mkdir(parents=True, exist_ok=True)
    gd = path.parent / ".gdignore"
    if not gd.exists():
        write_file(gd, "")
    meta = {"source": BASE, "target": a.locale, "original": f"{I18N_DIR}/{BASE}.json"}
    ex.write(path, units, meta)
    todo = sum(1 for u in units if not u.target)
    print(f"[ OK ] {path}: {len(units)} lines, {len(units) - todo} translated, {todo} to do"
          + (f", {kept} drafts or reviews kept from the old file" if kept else ""))
    gap = rules.helper_gap(a.locale)
    if gap:
        print(f"[warn] {gap}")
    if rules.categories(a.locale) is None:
        print(f"[warn] l10n.py does not know {a.locale}'s plural categories: the file asks for one/other (verify "
              "in CLDR)")
    return 0


# ---- draft -----------------------------------------------------------------------------------------------------
def cmd_draft(proj, a):
    check_locale(a.locale)
    path = proj.exchange_path(a.locale, a.file)
    units, meta = read_exchange(path)
    try:
        be = drafts.make_backend(a.backend, url=a.url, model=a.model, command=a.command, allow_remote=a.allow_remote,
                                 timeout=a.timeout)
        model = be.pick_model()
    except drafts.DraftError as e:
        raise UsageError(str(e))
    todo = [u for u in units if not u.target and u.state == ex.STATE_EMPTY and (not a.key or u.key in a.key)]
    if a.limit:
        todo = todo[:a.limit]
    made = rejected = flagged = 0
    print(f"drafting {len(todo)} lines into {rules.language_name(a.locale)} with {model}")
    try:
        for u in todo:
            req = {"key": u.key, "text": u.source, "note": u.note, "max": u.max_len, "source": BASE,
                   "target": a.locale, "source_name": "English", "target_name": rules.language_name(a.locale)}
            text = be.translate(req)
            errors, warnings = line_problems(u.source, text, u.max_len)
            errors += draft_problems(u, text)
            if any(e.startswith(("placeholders", "empty", "the draft")) for e in errors):
                u.tool_notes = [n for n in u.tool_notes if not n.startswith("draft rejected")]
                u.tool_notes.append(f"draft rejected ({model}): {'; '.join(errors)}: {text!r}")
                rejected += 1
                print(f"  [rejected] {u.key}: {'; '.join(errors)}: {text!r}")
                continue
            if text == u.source and needs_translation(u.source):
                warnings.append("the draft is the English text")
            if a.back_check:
                back = be.translate(dict(req, text=text, source=a.locale, target=BASE,
                                         source_name=rules.language_name(a.locale), target_name="English",
                                         note="", max=None))
                score = difflib.SequenceMatcher(None, back.lower(), u.source.lower()).ratio()
                if score < BACK_MIN:
                    warnings.append(f"back-translation differs (similarity {score:.2f}): {back!r}")
            u.target, u.state, u.qualifier = text, ex.STATE_DRAFT, ex.DRAFT_QUALIFIER
            u.tool_notes = [f"machine draft ({model}): a person reviews it before it ships"]
            u.tool_notes += [f"flag: {w}" for w in errors + warnings]
            made += 1
            flagged += bool(errors or warnings)
            print(f"  [draft] {u.key}: {text!r}" + (f"  flags: {'; '.join(errors + warnings)}" if errors or warnings
                                                     else ""))
    except drafts.DraftError as e:
        ex.write(path, units, meta)
        print(f"[error] {e} ({made} drafts saved in {path})")
        return 2
    ex.write(path, units, meta)
    print(f"[ OK ] {path}: {made} drafts ({flagged} flagged), {rejected} rejected; next: l10n.py review {a.locale}")
    return 1 if rejected else 0


def read_exchange(path):
    try:
        return ex.read(path)
    except ValueError as e:
        raise UsageError(str(e))


def draft_problems(u, text):
    """What a model gets wrong that a translator would not: the string id in the text, a reply that is a JSON
    object or a code block, line breaks the English does not have."""
    out = []
    if u.key in text:
        out.append("the draft contains the string id")
    if text.lstrip().startswith(("{\"", "```")) or "```" in text:
        out.append("the draft is markup, not a translation")
    if "\n" in text and "\n" not in u.source:
        out.append("the draft has line breaks the English does not have")
    return out


# ---- review ----------------------------------------------------------------------------------------------------
def accept(u, text=None):
    """Mark a line as reviewed (optionally with new text). Returns the errors that stopped it, [] when accepted."""
    text = u.target if text is None else text
    errors, warnings = line_problems(u.source, text, u.max_len)
    if errors:
        return errors
    u.target, u.state, u.qualifier = text, "translated", ""
    u.tool_notes = [n for n in u.tool_notes if not n.startswith(("machine draft", "flag:", "draft rejected"))]
    u.tool_notes += [f"reviewed; flag: {w}" for w in warnings]
    return []


def reject(u):
    u.target, u.state, u.qualifier = "", ex.STATE_EMPTY, ""
    u.tool_notes = ["draft rejected in review"]


def cmd_review(proj, a):
    check_locale(a.locale)
    path = proj.exchange_path(a.locale, a.file)
    units, meta = read_exchange(path)
    by_key = {u.key: u for u in units}
    changed, bad = 0, 0
    for spec in a.set:
        if "=" not in spec:
            raise UsageError(f"--set needs KEY=TEXT, got {spec!r}")
        key, text = spec.split("=", 1)
        bad += _apply(by_key, key, lambda u, t=text: accept(u, t))
        changed += 1
    for key in a.accept:
        bad += _apply(by_key, key, lambda u: accept(u) if u.target else ["no draft to accept"])
        changed += 1
    for key in a.reject:
        bad += _apply(by_key, key, lambda u: reject(u) or [])
        changed += 1
    pending = [u for u in units if u.is_draft()]
    if not changed and not a.list and sys.stdin.isatty():
        changed += interactive(pending)
    elif not changed:
        list_pending(pending)
    if changed:
        ex.write(path, units, meta)
        left = sum(1 for u in units if u.is_draft())
        print(f"[ OK ] {path}: saved; {left} drafts still to review")
    return 1 if bad else 0


def _apply(by_key, key, fn):
    u = by_key.get(key)
    if u is None:
        print(f"[FAIL] {key}: no such line in the file")
        return 1
    errors = fn(u)
    if errors:
        print(f"[FAIL] {key}: {'; '.join(errors)}")
        return 1
    print(f"[ OK ] {key}: {u.state}")
    return 0


def show(u):
    print(f"\n{u.key}" + (f"   (max {u.max_len})" if u.max_len else ""))
    if u.note:
        print(f"  context : {u.note}")
    print(f"  English : {u.source}")
    print(f"  draft   : {u.target}")
    for n in u.tool_notes:
        if n.startswith("flag:"):
            print(f"  {n}")


def list_pending(pending):
    if not pending:
        print("[ OK ] no drafts waiting for review")
        return
    for u in pending[:SHOW]:
        show(u)
    if len(pending) > SHOW:
        print(f"\n(+{len(pending) - SHOW} more)")
    print(f"\n{len(pending)} drafts to review: --accept KEY, --set KEY=TEXT, --reject KEY (or run in a terminal)")


def interactive(pending):
    done = 0
    for u in pending:
        show(u)
        while True:
            try:
                ans = input("  [a]ccept  [e]dit  [r]eject  [s]kip  [q]uit > ").strip().lower()
            except EOFError:
                return done
            if ans == "a":
                errors = accept(u)
                if errors:
                    print(f"  cannot accept: {'; '.join(errors)} (edit it)")
                    continue
            elif ans == "e":
                try:
                    errors = accept(u, input("  new text > "))
                except EOFError:
                    return done
                if errors:
                    print(f"  not accepted: {'; '.join(errors)}")
                    continue
            elif ans == "r":
                reject(u)
            elif ans == "q":
                return done
            elif ans != "s":
                continue
            done += ans in "aer"
            break
    return done


# ---- import ----------------------------------------------------------------------------------------------------
def cmd_import(proj, a):
    check_locale(a.locale)
    path = proj.exchange_path(a.locale, a.file)
    units, meta = read_exchange(path)
    if meta.get("target") and meta["target"] != a.locale:
        raise UsageError(f"{path} is a {meta['target']} file, not {a.locale}")
    extras = plural_extras(proj.en, a.locale)
    # 1. a file that lost (or gained) lines since export
    record = meta.get("record")
    if record is None:
        print(f"[warn] {path}: no export record, so lost lines cannot be detected (was it exported by l10n.py?)")
    elif ex.key_record([u.key for u in units]) != f"keys={record[0]} sha256={record[1]}":
        print(f"[FAIL] {path}: the file holds {len(units)} lines, export wrote {record[0]} (lines lost or added "
              "by a tool): nothing imported. Re-export and copy the translations over, or fix the file.")
        missing = [k for k in list(proj.en) + list(extras) if k not in {u.key for u in units}]
        for k in missing[:SHOW]:
            print(f"  lost: {k}")
        return 1
    table, old_text = proj.table(a.locale)
    new = dict(table)
    refused, pending, warnings, taken = [], [], [], []
    for u in units:
        want = expected_source(proj.en, extras, u.key)
        if want is None:
            refused.append(f"{u.key}: not a key of en.json (removed since export?)")
            continue
        if u.source != want:
            refused.append(f"{u.key}: the English changed since export ({u.source!r} -> {want!r}): re-export and "
                           "translate it again")
            continue
        if not u.imported():
            if u.target or u.is_draft():
                pending.append(u.key)
            continue
        errors, warns = line_problems(want, u.target, u.max_len or proj.context.get(u.key, {}).get("max"))
        if errors:
            refused.append(f"{u.key}: {'; '.join(errors)}: {u.target!r}")
            continue
        warnings += [f"{u.key}: {w}" for w in warns]
        if new.get(u.key) != u.target:
            taken.append(u.key)
        new[u.key] = u.target
    # 2. plural groups: every category the language needs, or none of the group from this file
    for base, keys in plural_problems(proj.en, new, a.locale, extras).items():
        refused.append(f"{base}: plural forms {', '.join(keys)} missing (needed by {a.locale}); the group's lines "
                       "from this file were not imported")
        for k in list(new):
            if rules.split_plural(k)[0] == base and k in taken:
                if k in table:
                    new[k] = table[k]
                else:
                    del new[k]
                taken.remove(k)
    gap = rules.helper_gap(a.locale)
    if gap and any(rules.split_plural(k)[1] for k in taken):
        warnings.append(gap)
    report("refused", refused, "[FAIL]")
    report_warnings(warnings, a.lengths)
    if pending:
        print(f"[info] {len(pending)} lines not reviewed yet, left out (l10n.py review {a.locale}): "
              f"{', '.join(pending[:8])}{' ...' if len(pending) > 8 else ''}")
    target_path = proj.table_path(a.locale)
    if old_text is None and all(nothing_to_translate(proj.en.get(k, "x")) for k in taken):
        # only names and placeholders so far: a new table would list the language in the game with nothing in it
        taken = []
    if taken and not a.dry_run:
        try:
            text = tables.render(proj.en_text, new, old_text)
        except ValueError as e:
            raise UsageError(str(e))
        write_file(target_path, text)
    verb = "would import" if a.dry_run else "imported"
    print(f"[{'FAIL' if refused else ' OK '}] {target_path}: {verb} {len(taken)} lines, {len(refused)} refused")
    return 1 if refused else 0


def plural_problems(en, table, locale, extras):
    """{base: [missing keys]} for plural groups the table has started but not finished for this language."""
    cats = rules.categories(locale) or ("one", "other")
    out = {}
    for base, have in rules.plural_groups(en).items():
        want = [f"{base}.{c}" for c in cats]
        present = [k for k in want if k in table]
        if present and len(present) < len(want):
            out[base] = [k for k in want if k not in table]
    return out


def report(title, lines, tag):
    if not lines:
        return
    print(f"{tag} {len(lines)} {title}:")
    for ln in lines[:SHOW]:
        print(f"  {ln}")
    if len(lines) > SHOW:
        print(f"  (+{len(lines) - SHOW} more)")


def report_warnings(warnings, show_long):
    """Warnings; the pseudo-length ones as one count line unless show_long (short labels often run long)."""
    long_ones = [w for w in warnings if LONG_TAG in w]
    report("warnings", [w for w in warnings if LONG_TAG not in w] + (long_ones if show_long else []), "[warn]")
    if long_ones and not show_long:
        print(f"[info] {len(long_ones)} lines are longer than the pseudo-locale's 40 % and have no max: look at them "
              "on screen, or give them a max in l10n/context.json (--lengths lists them)")


# ---- check -----------------------------------------------------------------------------------------------------
def cmd_check(proj, a):
    locales = a.locale or proj.locales()
    for loc in locales:
        check_locale(loc)
    font_paths = [Path(f) if Path(f).is_file() else proj.root / f for f in a.font]
    for f in font_paths:
        if not f.is_file():
            raise UsageError(f"font {f} not found")
    if not a.font and not a.no_fonts:
        font_paths = [f for f in fonts.discover(proj.root) if f.name not in a.skip_font]
    have = {}
    for f in font_paths:
        try:
            have[f] = fonts.font_chars(f)
        except fonts.FontError as e:
            raise UsageError(str(e))
    errors, warnings = [], []
    texts = {BASE: proj.en}
    for loc in locales:
        table, _ = proj.table(loc)
        if not table:
            raise UsageError(f"no {proj.table_path(loc)}")
        texts[loc] = table
        extras = plural_extras(proj.en, loc)
        for key, text in table.items():
            want = expected_source(proj.en, extras, key)
            if want is None:
                continue
            ctx_max = proj.context.get(key, {}).get("max")
            e, w = line_problems(want, text, ctx_max)
            errors += [f"{loc} {key}: {x}" for x in e if x != "empty"]
            warnings += [f"{loc} {key}: {x}" for x in w]
        for base, keys in plural_problems(proj.en, table, loc, extras).items():
            errors.append(f"{loc} {base}: plural forms {', '.join(keys)} missing")
        gap = rules.helper_gap(loc)
        if gap:
            warnings.append(f"{loc}: {gap}")
    # the pseudo-locale: what the smoke run will show, against the length budgets and the fonts
    texts["pseudo"] = {k: rules.pseudo(v) for k, v in proj.en.items()}
    for key, text in proj.en.items():
        m = proj.context.get(key, {}).get("max")
        if m and rules.visible_len(text) > m:
            errors.append(f"en {key}: {rules.visible_len(text)} characters, the budget is {m}")
        elif m and rules.pseudo_budget(text) > m:
            warnings.append(f"pseudo {key}: the budget {m} is below the pseudo-locale's {rules.pseudo_budget(text)}"
                            " (the pseudo smoke run will clip it)")
    for f, chars in have.items():
        rel = os.path.relpath(f, proj.root)
        for loc, table in texts.items():
            miss = {}
            for key, text in table.items():
                for ch in fonts.missing(chars, text):
                    miss.setdefault(ch, []).append(key)
            if miss:
                errors.append(f"{rel}: {loc} needs {len(miss)} characters the font lacks: " + "; ".join(
                    f"{fonts.describe(ch)} ({', '.join(ks[:3])}{' ...' if len(ks) > 3 else ''})"
                    for ch, ks in list(miss.items())[:12]) + (" ..." if len(miss) > 12 else ""))
    report("problems", errors, "[FAIL]")
    report_warnings(warnings, a.lengths)
    fonts_line = (f"{len(have)} fonts" if have else "no fonts found (--font PATH)" if not a.no_fonts else "fonts off")
    print(f"[{'FAIL' if errors else ' OK '}] checked en, pseudo and {len(locales)} tables "
          f"({', '.join(locales) or 'none'}) with {fonts_line}")
    return 1 if errors else 0


# ---- command line ----------------------------------------------------------------------------------------------
def common_options(suppress):
    """The global options, accepted before or after the command. The command's copy has no defaults of its own
    (argparse would otherwise reset a value given before the command)."""
    c = argparse.ArgumentParser(add_help=False)
    d = (lambda v: argparse.SUPPRESS) if suppress else (lambda v: v)
    c.add_argument("--project", default=d(None), help="the game's root (default: two folders above this script)")
    c.add_argument("--dir", default=d(None), help=f"the string tables (default: <project>/{I18N_DIR})")
    c.add_argument("--work", default=d(None), help=f"the translators' files (default: <project>/{WORK_DIR})")
    c.add_argument("--debug", action="store_true", default=d(False), help="tracebacks and more detail")
    return c


def parser():
    top = common_options(False)
    common = common_options(True)
    ap = argparse.ArgumentParser(
        prog="l10n.py", parents=[top],
        description="The localization round trip: export the game's strings, draft with a local model, review, "
                    "import with validation, check tables, the pseudo-locale and fonts.",
        epilog="Exit 0 ok, 1 a check failed or a line was refused, 2 usage or environment problem. Files live in "
               "l10n/ (commit them); never in data/i18n/. SOP-19 section 5.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")
    p = sub.add_parser("export", parents=[common], help="write l10n/<locale>.xlf (or .csv) for a translator")
    p.add_argument("locale", help="the language code, as the table's file name (ru for data/i18n/ru.json)")
    p.add_argument("--format", choices=sorted(FORMATS), default=None, help="xliff (default) or csv")
    p.add_argument("--out", default=None, help="the file to write (default: l10n/<locale>.xlf)")
    p = sub.add_parser("draft", parents=[common], help="machine drafts for the empty lines, from a local model")
    p.add_argument("locale")
    p.add_argument("--file", default=None, help="the translator's file (default: l10n/<locale>.xlf or .csv)")
    p.add_argument("--backend", choices=drafts.BACKENDS, default="lmstudio",
                   help="lmstudio, ollama, llamacpp (OpenAI-compatible servers on this machine), openai (--url), "
                        "or command (--command)")
    p.add_argument("--url", default=None, help="an OpenAI-compatible base URL, e.g. http://127.0.0.1:1234/v1")
    p.add_argument("--model", default=None, help="the model id (default: the first the server lists)")
    p.add_argument("--command", nargs="+", default=None,
                   help="a program that reads the JSON request on stdin and prints the draft (or {\"text\": ...})")
    p.add_argument("--key", action="append", default=[], help="draft only this line (repeatable)")
    p.add_argument("--limit", type=int, default=0, help="draft at most N lines")
    p.add_argument("--back-check", action="store_true",
                   help="translate each draft back to English and flag ones that drift (never passes a line)")
    p.add_argument("--allow-remote", action="store_true", help="allow a URL that is not this machine")
    p.add_argument("--timeout", type=int, default=drafts.TIMEOUT_S, help="seconds per request")
    p = sub.add_parser("review", parents=[common], help="accept, fix or reject the drafts")
    p.add_argument("locale")
    p.add_argument("--file", default=None)
    p.add_argument("--list", action="store_true", help="only list the drafts waiting for review")
    p.add_argument("--accept", action="append", default=[], metavar="KEY", help="accept this draft (repeatable)")
    p.add_argument("--reject", action="append", default=[], metavar="KEY", help="reject this draft (repeatable)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=TEXT",
                   help="your own translation of a line, accepted (repeatable)")
    p = sub.add_parser("import", parents=[common], help="the reviewed lines into data/i18n/<locale>.json")
    p.add_argument("locale")
    p.add_argument("--file", default=None)
    p.add_argument("--dry-run", action="store_true", help="validate and report, write nothing")
    p.add_argument("--lengths", action="store_true", help="list every line longer than the pseudo-locale's 40 %%")
    p = sub.add_parser("check", parents=[common],
                       help="every table: placeholders, plurals, lengths; the pseudo-locale; the fonts' glyphs")
    p.add_argument("--locale", action="append", default=[], help="only this table (repeatable)")
    p.add_argument("--font", action="append", default=[],
                   help="a font to check (.ttf .otf .ttc .fnt or a Dotwork glyph file; default: every font the "
                        "game has)")
    p.add_argument("--skip-font", action="append", default=[], metavar="NAME",
                   help="leave out a found font by file name (a symbol or debug font)")
    p.add_argument("--no-fonts", action="store_true", help="skip the font check")
    p.add_argument("--lengths", action="store_true", help="list every line longer than the pseudo-locale's 40 %%")
    return ap


def main(argv=None):
    global DEBUG
    ap = parser()
    a = ap.parse_args(argv)
    DEBUG = a.debug
    if not a.cmd:
        ap.print_help()
        return 2
    root = Path(a.project) if a.project else PROJECT
    if a.cmd == "check" and not a.dir and not (root / I18N_DIR).is_dir():
        print(f"[ OK ] no string tables ({I18N_DIR}/ does not exist), nothing to check")
        return 0
    try:
        proj = Project(root, a.dir, a.work)
        return {"export": cmd_export, "draft": cmd_draft, "review": cmd_review, "import": cmd_import,
                "check": cmd_check}[a.cmd](proj, a)
    except UsageError as e:
        print(f"[error] {e}")
        return 2
    except KeyboardInterrupt:
        print("[error] interrupted")
        return 2
    except Exception as e:                      # a bug here, not in the game's files
        print(f"[error] {type(e).__name__}: {e} (run with --debug for the traceback)")
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
