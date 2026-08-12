"""Romanisation tables for Cyrillic-script languages.

Two jobs, both P0-only:

1. Generate *synthetic* positive pairs with a known ground-truth transformation
   (`benchmark/README.md`, composition targets — capped at 30% of positives).
2. **Attribute** an observed Latin form to the standard that produced it, so a pair
   harvested from Wikidata or OFAC can be tagged `romanisation:bgn` rather than guessed at.

Attribution is deliberately conservative: a tag is emitted only when a standard
*exactly* reproduces the observed Latin form. Table imperfections therefore cause
under-attribution (`romanisation:ad-hoc`) rather than a wrong tag. That is the safe
direction of error for a benchmark whose taxonomy is its main output.

## Table provenance and known limits

These are **letter-level** tables with positional rules added only where the source
standard documents one and it is high-frequency. They are not full implementations.

- **ISO 9:1995** — strict 1:1 diacritic system. Table per the standard's Russian rows.
  `[VERIFY]` against ISO 9:1995 itself; transcribed from secondary sources and the table
  in `docs/domain-notes.md` §2.
- **GOST 7.79-2000 System B** — ASCII-only. Implements the documented `ц`→`c` before
  `i/e/y/j`, `cz` elsewhere rule. The standard states that rule over the *output*
  letters, so it is applied here to the Cyrillic letters that produce them
  (`и е ы й`) as well as to literal Latin `i e y j`. `[VERIFY]` against
  GOST 7.79-2000 — the reading affects `ц`+`ы` forms such as `Цыганов`.
- **BGN/PCGN 1947 (Russian)** — implements the `е`→`ye` / `ё`→`yë` rule word-initially
  and after a vowel, `й`, `ъ`, `ь`. Does **not** implement the optional middle-dot
  digraph separator (`т·с` vs `ц`), which is rare in name data. `[VERIFY]`.
- **ICAO Doc 9303** — passport MRZ transliteration; the reason it matters is that KYC
  records copied from identity documents use it (`docs/domain-notes.md` §2).
  `[VERIFY]` against Doc 9303 Part 3.
- **ALA-LC** — rendered *without* the combining ligature ties (`t͡s`→`ts`, `i͡u`→`iu`),
  which is how it appears in practice once records pass through systems that strip
  combining marks. `[VERIFY]`.
- **Scholarly / scientific transliteration** — the Slavist convention. `х`→`ch` per
  `docs/domain-notes.md` §2.
- **Ukrainian KMU 55:2010** — Cabinet of Ministers of Ukraine Resolution No. 55 of
  27 Jan 2010, the official Ukrainian romanisation. Implements the word-initial
  `є/ї/й/ю/я` forms and the `зг`→`zgh` rule. `[VERIFY]`.
- **Kazakh Latin 2021** — `[VERIFY, as of 2026-07]`. Kazakhstan's Latin-alphabet
  transition has produced several officially approved versions superseding one another
  and rollout has been repeatedly postponed (`docs/domain-notes.md` §3). This table
  encodes the diacritic-based 2021 revision as commonly reported. It is used here only
  to generate synthetic Kazakh Latin variants and to attempt attribution; **no
  customer-facing claim may rest on it** until the current official alphabet is
  confirmed against a primary Kazakh government source.
- **Russian-mediated Kazakh/Kyrgyz** — not a published standard. It is the observed
  practice of routing a Turkic name through Russian Cyrillic conventions, which
  *collapses* letters that Kazakh distinguishes (`ә ұ ү ө ғ қ ң і` → `a u u o g k n i`).
  Encoded here because that collapse is a primary source of real screening failure.
- **Uzbek Latin (1995 official)** — includes `oʻ`/`gʻ` with U+02BB MODIFIER LETTER
  TURNED COMMA, the canonical codepoint. Variance across U+02BB / U+2018 / U+0027 is
  applied separately by `uzbek_apostrophe_variants()`.

Everything here is pure, deterministic and dependency-free (`CLAUDE.md` §4).
"""

from __future__ import annotations

import unicodedata

# --------------------------------------------------------------------------------------
# Russian
# --------------------------------------------------------------------------------------

RU_ISO9 = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "ë", "ж": "ž",
    "з": "z", "и": "i", "й": "j", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "č", "ш": "š", "щ": "ŝ", "ъ": "ʺ", "ы": "y", "ь": "ʹ", "э": "è", "ю": "û",
    "я": "â",
}

RU_GOST779B = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh",
    "з": "z", "и": "i", "й": "j", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "cz",
    "ч": "ch", "ш": "sh", "щ": "shh", "ъ": "``", "ы": "y'", "ь": "`", "э": "e'",
    "ю": "yu", "я": "ya",
}

RU_BGN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "ë", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "ʺ", "ы": "y", "ь": "ʹ", "э": "e",
    "ю": "yu", "я": "ya",
}

RU_ICAO = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "ie", "ы": "y", "ь": "", "э": "e",
    "ю": "iu", "я": "ia",
}

RU_ALALC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "ë", "ж": "zh",
    "з": "z", "и": "i", "й": "ĭ", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "ʺ", "ы": "y", "ь": "ʹ", "э": "ė",
    "ю": "iu", "я": "ia",
}

RU_SCHOLARLY = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "ë", "ж": "ž",
    "з": "z", "и": "i", "й": "j", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "ch", "ц": "c",
    "ч": "č", "ш": "š", "щ": "šč", "ъ": "ʺ", "ы": "y", "ь": "ʹ", "э": "è", "ю": "ju",
    "я": "ja",
}

# Not a standard. The high-frequency ad-hoc substitutions seen in real records —
# the German-influenced щ→sch, the English-influenced х→h, ц→c, final -ов→-off.
# Used to generate a synthetic `romanisation:ad-hoc` slice.
RU_ADHOC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}

RU_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯіїєўұүөәӣӯ")

# ISO 9 and the Slavist conventions are pan-Cyrillic: they define rows for the Ukrainian,
# Belarusian and Turkic letters, not only the Russian ones. Omitting those rows let a
# Ukrainian name transliterated under `iso9` keep its `і` as raw Cyrillic and emit
# mixed-script output (`Олексійович`→`Oleksіjovic`), which is corrupt data, not a hard
# pair. Every Russian-base table below is extended so no Cyrillic letter can pass
# through untransliterated.
#
# `[VERIFY]` the ISO 9 rows for these letters against ISO 9:1995.
_EAST_SLAVIC_ISO9 = {"і": "ì", "ї": "ï", "є": "ê", "ґ": "g", "ў": "ŭ", "ѐ": "è"}
_EAST_SLAVIC_PLAIN = {"і": "i", "ї": "yi", "є": "ye", "ґ": "g", "ў": "u", "ѐ": "e"}
_TURKIC_PLAIN = {"ә": "a", "ғ": "g", "қ": "k", "ң": "n", "ө": "o", "ұ": "u", "ү": "u",
                 "һ": "h", "ӣ": "i", "ӯ": "u", "ҳ": "h", "ҷ": "j"}

for _table, _slavic in (
    (RU_ISO9, _EAST_SLAVIC_ISO9),
    (RU_SCHOLARLY, {"і": "i", "ї": "ji", "є": "je", "ґ": "g", "ў": "ŭ", "ѐ": "è"}),
    (RU_ALALC, {"і": "ī", "ї": "ï", "є": "ie", "ґ": "g", "ў": "ŭ", "ѐ": "e"}),
    (RU_GOST779B, {"і": "i'", "ї": "yi", "є": "ye", "ґ": "g'", "ў": "u'", "ѐ": "e"}),
    (RU_BGN, _EAST_SLAVIC_PLAIN),
    (RU_ICAO, _EAST_SLAVIC_PLAIN),
    (RU_ADHOC, _EAST_SLAVIC_PLAIN),
):
    for _letter, _value in _slavic.items():
        _table.setdefault(_letter, _value)
    for _letter, _value in _TURKIC_PLAIN.items():
        _table.setdefault(_letter, _value)

# --------------------------------------------------------------------------------------
# Ukrainian — KMU Resolution No. 55 (2010)
# --------------------------------------------------------------------------------------

UK_KMU55 = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie",
    "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ь": "",
    "ю": "iu", "я": "ia", "'": "",
}
# Word-initial forms, per the same resolution.
UK_KMU55_INITIAL = {"є": "ye", "ї": "yi", "й": "y", "ю": "yu", "я": "ya"}

UK_BGN = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ye",
    "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "yi", "й": "y", "к": "k", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ь": "ʹ",
    "ю": "yu", "я": "ya", "'": "",
}

# --------------------------------------------------------------------------------------
# Kazakh
# --------------------------------------------------------------------------------------

KK_LATIN2021 = {
    "а": "a", "ә": "ä", "б": "b", "в": "v", "г": "g", "ғ": "ğ", "д": "d", "е": "e",
    "ё": "e", "ж": "j", "з": "z", "и": "i", "й": "i", "к": "k", "қ": "q", "л": "l",
    "м": "m", "н": "n", "ң": "ñ", "о": "o", "ө": "ö", "п": "p", "р": "r", "с": "s",
    "т": "t", "у": "u", "ұ": "ū", "ү": "ü", "ф": "f", "х": "h", "һ": "h", "ц": "ts",
    "ч": "ch", "ш": "ş", "щ": "şş", "ъ": "", "ы": "y", "і": "i", "ь": "", "э": "e",
    "ю": "iu", "я": "ia",
}

# Kazakh routed through Russian conventions — the collapse that breaks matchers.
KK_RU_MEDIATED = {
    "а": "a", "ә": "a", "б": "b", "в": "v", "г": "g", "ғ": "g", "д": "d", "е": "e",
    "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "қ": "k", "л": "l",
    "м": "m", "н": "n", "ң": "n", "о": "o", "ө": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "у": "u", "ұ": "u", "ү": "u", "ф": "f", "х": "kh", "һ": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "і": "i", "ь": "", "э": "e",
    "ю": "yu", "я": "ya",
}

# --------------------------------------------------------------------------------------
# Belarusian, Tajik
# --------------------------------------------------------------------------------------

# BGN/PCGN Belarusian. The diagnostic letter is `г`→`h` (Russian gives `g`), which is why
# `Рыгоравiч` romanises as `Ryhoravich` and not `Rygoravich`. `[VERIFY]` against the
# BGN/PCGN Belarusian table; transcribed from secondary sources.
BE_BGN = {
    "а": "a", "б": "b", "в": "v", "г": "h", "д": "d", "е": "e", "ё": "ë", "ж": "zh",
    "з": "z", "і": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ў": "w", "ф": "f", "х": "kh",
    "ц": "ts", "ч": "ch", "ш": "sh", "ы": "y", "ь": "ʹ", "э": "e", "ю": "yu", "я": "ya",
    "'": "",
}

# **Not a published standard.** BGN/PCGN Belarusian with its modifier letters degraded to
# ASCII — `ў`→`u` rather than `w`, `ʹ` dropped. Added because it is the practice actually
# observed in OFAC SDN Belarusian entries (`Сліжэўскі`→`Slizheuski`), and a table that
# cannot reproduce real list data would push those pairs into `ad-hoc` and hide a
# nameable convention. Labelled as observed practice so it is never cited as a standard.
BE_LATIN_ASCII = dict(BE_BGN, **{"ў": "u", "ь": "", "ё": "yo"})

# Tajik is a Persian language written in Cyrillic, then romanised — two lossy hops
# (`docs/domain-notes.md` §5). `[VERIFY]`.
TG_BGN = dict(RU_BGN, **{
    "ғ": "gh", "ӣ": "i", "қ": "q", "ӯ": "u", "ҳ": "h", "ҷ": "j", "и": "i", "е": "e",
})

# --------------------------------------------------------------------------------------
# Kyrgyz, Uzbek
# --------------------------------------------------------------------------------------

KY_BGN = dict(RU_BGN, **{"ң": "ng", "ө": "ö", "ү": "ü"})
KY_RU_MEDIATED = dict(RU_BGN, **{"ң": "n", "ө": "o", "ү": "u"})

UZ_LATIN1995 = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ғ": "gʻ", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "қ": "q", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ў": "oʻ",
    "ф": "f", "х": "x", "ҳ": "h", "ц": "ts", "ч": "ch", "ш": "sh", "ъ": "ʼ", "ы": "i",
    "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
UZ_RU_MEDIATED = dict(
    RU_BGN, **{"ғ": "g", "қ": "k", "ҳ": "kh", "ў": "u", "х": "kh", "ж": "zh"}
)

# --------------------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------------------

_SYSTEMS: dict[str, dict] = {
    "iso9": {"table": RU_ISO9, "lang": "ru"},
    "gost-b": {"table": RU_GOST779B, "lang": "ru", "ts_rule": True},
    "bgn": {"table": RU_BGN, "lang": "ru", "ye_rule": True},
    "icao": {"table": RU_ICAO, "lang": "ru"},
    "ala-lc": {"table": RU_ALALC, "lang": "ru"},
    "scholarly": {"table": RU_SCHOLARLY, "lang": "ru"},
    "ad-hoc": {"table": RU_ADHOC, "lang": "ru"},
    "uk-kmu55": {"table": UK_KMU55, "lang": "uk", "initial": UK_KMU55_INITIAL,
                 "zgh_rule": True},
    "uk-bgn": {"table": UK_BGN, "lang": "uk"},
    "kk-latin2021": {"table": KK_LATIN2021, "lang": "kk"},
    "kk-ru-mediated": {"table": KK_RU_MEDIATED, "lang": "kk"},
    "ky-bgn": {"table": KY_BGN, "lang": "ky"},
    "ky-ru-mediated": {"table": KY_RU_MEDIATED, "lang": "ky"},
    "uz-latin1995": {"table": UZ_LATIN1995, "lang": "uz"},
    "uz-ru-mediated": {"table": UZ_RU_MEDIATED, "lang": "uz"},
    "be-bgn": {"table": BE_BGN, "lang": "be", "ye_rule": True},
    "be-latin-ascii": {"table": BE_LATIN_ASCII, "lang": "be", "ye_rule": True},
    "tg-bgn": {"table": TG_BGN, "lang": "tg"},
}

SYSTEM_NAMES = tuple(_SYSTEMS)

# Backstop: every table gets a plain fallback for every Cyrillic letter any other table
# knows about, so no system applied to any language can emit raw Cyrillic. Each table's
# own rows always win — `setdefault` never overwrites a documented mapping. This is a
# guard against corrupt output, not a linguistic claim: applying the Ukrainian table to a
# Kazakh name is a build error, and the guard only ensures such an error produces
# recognisably wrong Latin rather than silently mixed-script data.
_UNIVERSAL_FALLBACK = {
    **{k: v for k, v in RU_BGN.items() if isinstance(v, str)},
    **_EAST_SLAVIC_PLAIN,
    **_TURKIC_PLAIN,
    "ы": "y", "э": "e", "ъ": "", "ь": "", "ё": "e", "й": "y", "щ": "shch",
}
for _spec in _SYSTEMS.values():
    for _letter, _value in _UNIVERSAL_FALLBACK.items():
        _spec["table"].setdefault(_letter, _value)

# Which systems it is meaningful to *attribute* an observed Latin form to, per language.
ATTRIBUTION_ORDER = {
    "ru": ("bgn", "icao", "gost-b", "iso9", "ala-lc", "scholarly", "ad-hoc"),
    "uk": ("uk-kmu55", "uk-bgn", "bgn", "icao", "iso9", "ad-hoc"),
    "kk": ("kk-ru-mediated", "kk-latin2021", "bgn", "icao", "ad-hoc"),
    "ky": ("ky-ru-mediated", "ky-bgn", "bgn", "icao", "ad-hoc"),
    "uz": ("uz-latin1995", "uz-ru-mediated", "bgn", "icao", "ad-hoc"),
    "be": ("be-bgn", "be-latin-ascii", "bgn", "icao", "iso9", "ad-hoc"),
    "tg": ("tg-bgn", "bgn", "icao", "iso9", "ad-hoc"),
}

# Systems whose output carries diacritics or modifier letters. Needed to keep a
# diacritic-insensitive match from being credited as a positive identification of the
# system: `Мария`→`Maria` is *not* evidence of ISO 9 merely because ISO 9's `Mariâ`
# collapses to `maria` when combining marks are stripped. See `phenomena.align_tokens`.
# Note this includes the BGN family: BGN/PCGN emits the modifier letters `ʹ` and `ʺ` for
# `ь` and `ъ`, which real systems routinely drop, so `Григорьевич`→`Grigoryevich` is BGN
# with marks stripped rather than an unattributable form.
DIACRITIC_SYSTEMS = frozenset({
    "iso9", "scholarly", "ala-lc", "kk-latin2021", "gost-b", "uz-latin1995",
    "bgn", "uk-bgn", "ky-bgn", "be-bgn", "tg-bgn",
})


def _apply(text: str, system: str) -> str:
    spec = _SYSTEMS[system]
    table = spec["table"]
    ye_rule = spec.get("ye_rule", False)
    ts_rule = spec.get("ts_rule", False)
    initial = spec.get("initial")
    zgh_rule = spec.get("zgh_rule", False)

    out: list[str] = []
    n = len(text)
    for i, ch in enumerate(text):
        low = ch.lower()
        upper = ch != low

        prev = text[i - 1] if i > 0 else ""
        # word-initial = start of string or preceded by a non-letter
        at_word_start = i == 0 or not prev.isalpha()

        rep: str | None = None

        if zgh_rule and low == "г" and prev.lower() == "з":
            rep = "gh"
        elif initial and at_word_start and low in initial:
            rep = initial[low]
        elif ye_rule and low in ("е", "ё"):
            after_trigger = at_word_start or prev in RU_VOWELS or prev.lower() in ("й", "ъ", "ь")
            if low == "е":
                rep = "ye" if after_trigger else "e"
            else:
                rep = "yë" if after_trigger else "ë"
        elif ts_rule and low == "ц":
            nxt = text[i + 1].lower() if i + 1 < n else ""
            rep = "c" if nxt in ("i", "e", "y", "j", "и", "е", "ы", "й") else "cz"
        elif low in table:
            rep = table[low]

        if rep is None:
            out.append(ch)
            continue
        if upper and rep:
            rep = rep[0].upper() + rep[1:]
        out.append(rep)

    return "".join(out)


def romanise(text: str, system: str) -> str:
    """Apply a named romanisation system. Deterministic and total."""
    if system not in _SYSTEMS:
        raise KeyError(f"unknown romanisation system: {system}")
    return _apply(text, system)


def strip_diacritics(text: str) -> str:
    """Degrade to ASCII the way a system that cannot store combining marks does.

    Handles the letters whose NFD decomposition does not strip (`ø`-class), which for
    our tables means the Kazakh/Turkish-derived set and the Slavist modifier letters.
    """
    manual = {
        "ʺ": "", "ʹ": "", "ʻ": "", "ʼ": "", "‘": "", "’": "", "`": "",
        "ū": "u", "ğ": "g", "ñ": "n", "ş": "s", "ä": "a", "ö": "o", "ü": "u",
        "ı": "i", "ə": "a", "ý": "y", "ň": "n",
    }
    out: list[str] = []
    for ch in text:
        if ch in manual:
            out.append(manual[ch])
        elif ch.lower() in manual:
            rep = manual[ch.lower()]
            out.append(rep.upper() if rep else rep)
        else:
            out.append(ch)
    decomposed = unicodedata.normalize("NFD", "".join(out))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def uzbek_apostrophe_variants(text: str) -> list[str]:
    """The three byte sequences for one Uzbek letter (`docs/domain-notes.md` §5).

    U+02BB MODIFIER LETTER TURNED COMMA (canonical), U+2018 LEFT SINGLE QUOTATION MARK
    (what word processors autocorrect it to), and U+0027 APOSTROPHE (what ASCII systems
    keep).
    """
    canonical = text.replace("‘", "ʻ").replace("'", "ʻ")
    return [
        canonical,
        canonical.replace("ʻ", "‘"),
        canonical.replace("ʻ", "'"),
    ]


# Inverse of UZ_LATIN1995, longest-sequence-first. Uzbek is the one target language whose
# Wikidata labels are already Latin (it switched script in the 1990s), so Uzbek *Cyrillic*
# forms have to be generated rather than harvested. The 1995 mapping is close to bijective
# on the sequences below, which is what makes the inverse safe to use as ground truth for
# a synthetic pair.
_UZ_LATIN_TO_CYRILLIC = (
    ("oʻ", "ў"), ("o‘", "ў"), ("o'", "ў"), ("gʻ", "ғ"), ("g‘", "ғ"), ("g'", "ғ"),
    ("sh", "ш"), ("ch", "ч"), ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("ts", "ц"),
    ("a", "а"), ("b", "б"), ("d", "д"), ("e", "е"), ("f", "ф"), ("g", "г"), ("h", "ҳ"),
    ("i", "и"), ("j", "ж"), ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"),
    ("p", "п"), ("q", "қ"), ("r", "р"), ("s", "с"), ("t", "т"), ("u", "у"), ("v", "в"),
    ("x", "х"), ("y", "й"), ("z", "з"),
)


def uzbek_latin_to_cyrillic(text: str) -> str:
    """Uzbek Latin (1995 official) → Uzbek Cyrillic. Deterministic, longest-match-first."""
    out: list[str] = []
    i = 0
    lowered = text.lower()
    while i < len(text):
        for seq, cyr in _UZ_LATIN_TO_CYRILLIC:
            if lowered.startswith(seq, i):
                out.append(cyr.upper() if text[i].isupper() else cyr)
                i += len(seq)
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


# Letters that a Russian-mediated romanisation collapses onto one Latin form. Two
# *different* Cyrillic names that agree after this collapse produce an identical Latin
# string — the sharpest hard negative the corpus can contain, because every matcher that
# romanises once will call them equal (`docs/domain-notes.md` §3).
COLLAPSE_MAP = {
    "ә": "а", "ғ": "г", "қ": "к", "ң": "н", "ө": "о", "ұ": "у", "ү": "у", "һ": "х",
    "і": "и", "ѐ": "е", "ё": "е", "й": "и", "ў": "у", "ӣ": "и", "ӯ": "у", "ҳ": "х",
    "ҷ": "ж", "э": "е", "ъ": "", "ь": "",
}


def collapse(text: str) -> str:
    """Fold the letters a Russian-mediated romanisation cannot distinguish."""
    return "".join(COLLAPSE_MAP.get(c, COLLAPSE_MAP.get(c.lower(), c)) if
                   c.lower() in COLLAPSE_MAP else c for c in text.lower())


def attribute(cyrillic: str, latin: str, language: str) -> tuple[str, bool, list[str]]:
    """Which standard produced `latin` from `cyrillic`?

    Returns `(system_tag, exact, all_matching)`.

    `exact` is True only when some system reproduces the observed Latin form
    character-for-character after case folding; a diacritic-insensitive second pass
    runs if the strict pass fails. When neither pass matches, the result is
    `("ad-hoc", False, [])` — conservative by design, see module docstring.

    **Ties are common and are reported, not hidden.** Several standards agree on many
    names (BGN and ALA-LC both give `Щербаков`→`Shcherbakov`), so `all_matching` holds
    every system consistent with the observation and `system_tag` is merely the first
    in `ATTRIBUTION_ORDER`. A single-system tag on a tied pair would be a fabricated
    level of certainty.
    """
    target = latin.lower().strip()
    target_ascii = strip_diacritics(target)
    order = ATTRIBUTION_ORDER.get(language, ATTRIBUTION_ORDER["ru"])

    strict = [s for s in order if romanise(cyrillic, s).lower().strip() == target]
    if strict:
        return strict[0], True, strict

    loose = [
        s for s in order
        if strip_diacritics(romanise(cyrillic, s).lower().strip()) == target_ascii
    ]
    if loose:
        return loose[0], True, loose

    return "ad-hoc", False, []
