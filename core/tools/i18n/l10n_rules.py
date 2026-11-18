#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# l10n_rules.py
# Purpose : The rules the localization round trip (l10n.py) checks a translated line against: placeholders, plural
#           categories per language (CLDR), the length budget and the pseudo-locale. No file access here.
# Usage   : import l10n_rules as rules
#           rules.placeholders("Hi {name}, %d new")      # ['%d', '{name}']
#           rules.plural_groups(en_table)                # {'demo.hits': ['one', 'other']}
#           rules.categories("ru")                       # ('one', 'few', 'many', 'other')
#           rules.pseudo("Play")                         # '[Pláý~~]' (the engines' pseudo-locale, same algorithm)
# Notes   : Placeholders are {name} and the printf codes %s %d %i %f %% (the pseudo-locale keeps the same ones), so
#           a translation must keep the same multiset of them. Lengths count the visible characters: placeholders
#           count 0, because what they turn into is not known here. Plural categories are CLDR's cardinal ones for
#           whole numbers; the "many" CLDR gives French, Spanish, Italian, Portuguese and Catalan for compact
#           millions is left out (the kit's plural helper never picks it). Standard library only.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   placeholders(text) = sorted list of {name} and %x tokens; same(a, b) = equal lists
#   plural_groups(en)  = bases whose keys end in .<category> and include .other
#   categories(lang)   = CLDR table lookup on the base language, None when the language is not in the table
#   visible_len(text)  = len(text with every placeholder removed)
#   pseudo(text)       = accents + 40 % "~" padding + brackets (matches data/golden/shell.json)
import math
import re

# ---- constants -------------------------------------------------------------------------------------------------
# any {word} counts, not only ASCII names: a model that translated {name} into {имя} must be caught
PLACEHOLDER = re.compile(r"\{\{?[^{}\s]+\}?\}|%[sdif%]")
CATEGORY_NAMES = ("zero", "one", "two", "few", "many", "other")
# CLDR cardinal plural categories for whole numbers, as CLDR's plural rules chart lists them (written from CLDR 44,
# not live-checked here: verify against unicode.org/cldr/charts/latest/supplemental/language_plural_rules.html
# before shipping a language). A language not listed here gets a warning and the English-like pair.
CLDR = {
    ("other",): "ja zh ko vi th id ms lo my km yo ig jv su",
    ("one", "other"): "en de nl sv da nb nn no fi et it es pt ca gl el hu tr bg eu af sq ka kk ky mn az uz ur hi bn "
                      "fa ta te ml kn mr gu sw fil is fr hy",
    ("one", "few", "other"): "hr sr bs ro mo",
    ("one", "few", "many", "other"): "ru uk be pl cs sk lt",
    ("zero", "one", "other"): "lv",
    ("one", "two", "other"): "he",
    ("one", "two", "few", "other"): "sl",
    ("one", "two", "few", "many", "other"): "ga",
    ("zero", "one", "two", "few", "many", "other"): "ar cy",
}
CATEGORIES = {lang: cats for cats, langs in CLDR.items() for lang in langs.split()}
# Which languages the kit's plural helper (every engine's i18n code) has a rule for. Anything else runs on its
# English-like default (one for exactly 1), so a language that needs other categories also needs a rule added.
HELPER_RULES = {"fr", "ja", "zh", "ko"}
# What a category means, for translators (an English note next to each plural line).
CATEGORY_HINT = {
    "zero": "zero (0 in some languages)", "one": "one (1, and in some languages 21, 31 ...)",
    "two": "two (2)", "few": "few (in Russian 2-4, 22-24 ...)", "many": "many (in Russian 0, 5-20, 25-30 ...)",
    "other": "other (every other number)",
}
PSEUDO_GROWTH = 0.40          # translated English runs about 40 % longer (SOP-19, the engines' pseudo-locale)
PSEUDO_MAP = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú", "c": "ç", "n": "ñ", "y": "ý",
              "A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú", "C": "Ç", "N": "Ñ", "Y": "Ý"}
LANGUAGE_NAMES = {
    "ar": "Arabic", "bg": "Bulgarian", "ca": "Catalan", "cs": "Czech", "da": "Danish", "de": "German",
    "el": "Greek", "en": "English", "es": "Spanish", "et": "Estonian", "fi": "Finnish", "fr": "French",
    "he": "Hebrew", "hi": "Hindi", "hr": "Croatian", "hu": "Hungarian", "id": "Indonesian", "it": "Italian",
    "ja": "Japanese", "ko": "Korean", "lt": "Lithuanian", "lv": "Latvian", "nb": "Norwegian Bokmal",
    "nl": "Dutch", "pl": "Polish", "pt": "Portuguese", "pt_BR": "Brazilian Portuguese", "ro": "Romanian",
    "ru": "Russian", "sk": "Slovak", "sl": "Slovenian", "sr": "Serbian", "sv": "Swedish", "th": "Thai",
    "tr": "Turkish", "uk": "Ukrainian", "vi": "Vietnamese", "zh": "Chinese (Simplified)",
    "zh_Hant": "Chinese (Traditional)",
}


def base_language(locale):
    """'pt-BR' / 'pt_BR' -> 'pt'."""
    return re.split(r"[-_]", locale, maxsplit=1)[0].lower()


def language_name(locale):
    """An English name for a prompt or a note: 'fr' -> 'French'; unknown codes come back as they are."""
    norm = locale.replace("-", "_")
    return LANGUAGE_NAMES.get(norm) or LANGUAGE_NAMES.get(base_language(locale)) or locale


# ---- placeholders ----------------------------------------------------------------------------------------------
def placeholders(text):
    return sorted(PLACEHOLDER.findall(text))


def placeholder_problem(source, target):
    """None when target keeps exactly the source's placeholders, else a short reason naming the difference."""
    want, got = placeholders(source), placeholders(target)
    if want == got:
        return None
    lost = [p for p in want if want.count(p) > got.count(p)]
    added = [p for p in got if got.count(p) > want.count(p)]
    parts = []
    if lost:
        parts.append("lost " + " ".join(sorted(set(lost))))
    if added:
        parts.append("added " + " ".join(sorted(set(added))))
    return "placeholders: " + ", ".join(parts)


def visible_len(text):
    """Characters a player sees around the placeholders (each placeholder counts 0)."""
    return len(PLACEHOLDER.sub("", text))


# ---- plurals ---------------------------------------------------------------------------------------------------
def split_plural(key):
    """'demo.hits.one' -> ('demo.hits', 'one'); a key without a category suffix -> (key, None)."""
    base, _, last = key.rpartition(".")
    if base and last in CATEGORY_NAMES:
        return base, last
    return key, None


def plural_groups(table):
    """{base: [categories in table order]} for every base that has an .other key and at least one more category."""
    groups = {}
    for key in table:
        base, cat = split_plural(key)
        if cat:
            groups.setdefault(base, []).append(cat)
    return {b: cats for b, cats in groups.items() if "other" in cats and len(cats) > 1}


def categories(locale):
    """CLDR's categories for the locale's language, or None when the table does not know the language."""
    return CATEGORIES.get(base_language(locale))


def helper_gap(locale):
    """A warning when the language needs categories the kit's plural helper cannot pick, else None."""
    cats = categories(locale)
    lang = base_language(locale)
    if cats and set(cats) - {"one", "other"} and lang not in HELPER_RULES:
        return (f"{lang} needs plural categories {', '.join(cats)}, but the game's plural helper has no {lang} rule "
                f"(it picks only one/other): add the rule from CLDR before shipping (SOP-19 5.2)")
    return None


# ---- the pseudo-locale -----------------------------------------------------------------------------------------
def pseudo(text):
    """The engines' pseudo-locale (i18n.gd / i18n.ts / ...): accents, ~ padding of 40 % of the visible characters
    rounded up, brackets. {name} and %s %d %i %f %% pass through and do not count."""
    out, visible, i = [], 0, 0
    while i < len(text):
        c = text[i]
        if c == "{":
            j = text.find("}", i)
            if j > i:
                out.append(text[i:j + 1])
                i = j + 1
                continue
        if c == "%" and i + 1 < len(text) and text[i + 1] in "sdif%":
            out.append(text[i:i + 2])
            i += 2
            continue
        out.append(PSEUDO_MAP.get(c, c))
        visible += 1
        i += 1
    return "[" + "".join(out) + "~" * math.ceil(visible * PSEUDO_GROWTH) + "]"


def pseudo_budget(source):
    """The visible length the pseudo-locale smoke run proved fits on screen: the English plus 40 %, rounded up."""
    n = visible_len(source)
    return n + math.ceil(n * PSEUDO_GROWTH)
