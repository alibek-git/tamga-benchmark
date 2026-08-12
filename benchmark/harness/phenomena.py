"""Derive the `phenomena` tags for a name pair.

`benchmark/README.md`: "**`phenomena`** — the whole point. Tagging *what each pair tests*
is what converts a score into an error taxonomy." This module is therefore the part of
the corpus build that most needs to be conservative, because a wrong tag produces a
confidently wrong diagnosis, which is worse than no diagnosis.

## Method

Token alignment, not whole-string guessing. For a Cyrillic/Latin pair:

1. Romanise every Cyrillic token under every candidate system for the language.
2. Match each Latin token to the Cyrillic token it could have come from.
3. Whatever aligns tells us the romanisation system; whatever fails to align tells us
   the structural phenomenon (dropped patronymic, gender change, exonym, corruption).

Attribution reports **every** system consistent with the observation, never one picked
arbitrarily out of a tie (`translit.attribute`).

## Where this refuses to guess

- A romanisation that no table reproduces is tagged `romanisation:ad-hoc`, not assigned
  to the nearest system.
- A Latin token that matches no Cyrillic token and is not explicable as an exonym or a
  gender form is tagged `token:unaligned` rather than being explained away.

Tags added to the `benchmark/README.md` vocabulary by this module are listed in
`EXTENDED_VOCABULARY` below, so the controlled list stays auditable.
"""

from __future__ import annotations

import difflib
import unicodedata

from . import names as N
from . import translit as T

# Additions to the phenomenon vocabulary in `benchmark/README.md`, with the reason each
# was needed. Kept here so the controlled vocabulary cannot drift silently.
EXTENDED_VOCABULARY = {
    "given:exonym": "English conventional form replaces transliteration "
                    "(Александр→Alexander, Пётр→Peter). Distinct from a romanisation "
                    "variant: no rule table produces it.",
    "given:diminutive": "Short/familiar form of a given name (Александр→Sasha).",
    "corruption:mixed-script-homoglyph": "Latin letters inside a Cyrillic string "
                                         "(Рыгоравiч with U+0069). Measured in OFAC SDN "
                                         "itself, not synthesised.",
    "token:dropped": "A token present on one side and absent on the other, not "
                     "identifiable as a patronymic.",
    "token:unaligned": "A token this module could not explain. Present so unexplained "
                       "residue is visible rather than silently absorbed.",
    "token:abbreviated": "A non-patronymic token reduced to an initial.",
    "patronymic:form-substituted": "Both sides carry a patronymic but in different "
                                   "conventions (Turkic `-ұлы` against Russified "
                                   "`-ович`) — a substitution, not a drop.",
    "romanisation:diacritics-stripped": "Explained only after combining marks are "
                                        "removed. Which standard produced it is not "
                                        "recoverable, so the degradation is reported "
                                        "instead of naming a system.",
    "romanisation:unattributed-variant": "Two Latin forms of one Cyrillic original whose "
                                         "systems cannot be identified without that "
                                         "original.",
    "negative:romanisation-collision": "Two different Cyrillic names that collapse to "
                                       "the same Latin form under some standard — the "
                                       "sharpest hard negative available.",
    "negative:patronymic-collision": "Different entities sharing surname and patronymic.",
    "script:same": "Both sides in the same script (Latn↔Latn cross-romanisation, or "
                   "Cyrl↔Cyrl language variant).",
}

# Conventional English forms that are not transliterations of the Cyrillic. Restricted to
# high-frequency CIS given names. Each entry is a claim that the two forms denote the same
# given name conventionally — checkable, and deliberately short.
EXONYMS = {
    "александр": {"alexander", "alex"},
    "алексей": {"alexis"},
    "андрей": {"andrew"},
    "владимир": {"vladimir", "wladimir"},
    "дмитрий": {"dimitri", "demetrius"},
    "евгений": {"eugene", "eugen"},
    "екатерина": {"catherine", "katherine", "ekaterina"},
    "елена": {"helen", "helena", "elena"},
    "иван": {"john", "ivan"},
    "михаил": {"michael"},
    "николай": {"nicholas", "nikolas"},
    "павел": {"paul"},
    "пётр": {"peter"},
    "петр": {"peter"},
    "сергей": {"serge", "sergius"},
    "юрий": {"george", "yuri", "yury"},
    "мария": {"maria", "mary"},
    "наталья": {"natalie", "natalia"},
    "татьяна": {"tatiana", "tatyana"},
    "олег": {"oleg"},
    "георгий": {"george"},
    "яков": {"jacob", "james"},
    "василий": {"basil"},
    "фёдор": {"theodore"},
    "федор": {"theodore"},
}

DIMINUTIVES = {
    "александр": {"sasha", "shura"},
    "дмитрий": {"dima"},
    "михаил": {"misha"},
    "николай": {"kolya"},
    "владимир": {"volodya", "vova"},
    "сергей": {"seryozha"},
    "екатерина": {"katya"},
    "мария": {"masha"},
    "татьяна": {"tanya"},
    "елена": {"lena"},
}


def _fold(text: str) -> str:
    """Case-fold and strip diacritics for tolerant token comparison."""
    return T.strip_diacritics(text.lower()).replace("'", "").replace("`", "").strip(".")


def has_mixed_script(text: str) -> bool:
    return N.detect_script(text) == "Mixed"


def homoglyph_report(text: str) -> list[str]:
    """The specific out-of-script letters in a mixed-script string, as `U+XXXX` codes."""
    cyr: list[str] = []
    lat: list[str] = []
    for ch in text:
        if not ch.isalpha():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        (cyr if "CYRILLIC" in name else lat).append(ch)
    minority = lat if len(cyr) >= len(lat) else cyr
    return sorted({f"{ch}=U+{ord(ch):04X}" for ch in minority})


FUZZY_THRESHOLD = 0.72


def _casefold_only(text: str) -> str:
    return text.lower().strip(".").strip()


def _romanisations(token: str, language: str) -> dict[str, str]:
    """Every candidate system's output for one token, case-folded but diacritics intact."""
    systems = T.ATTRIBUTION_ORDER.get(language, T.ATTRIBUTION_ORDER["ru"])
    return {s: _casefold_only(T.romanise(token, s)) for s in systems}


def _best_ratio(romans: dict[str, str], target: str) -> float:
    return max(
        (difflib.SequenceMatcher(None, _fold(r), _fold(target)).ratio()
         for r in romans.values()),
        default=0.0,
    )


def align_tokens(cyrillic: str, latin: str, language: str) -> dict:
    """Align Latin tokens to Cyrillic tokens via an explicit match cascade.

    Each aligned token records **how** it matched, so a tag is never stronger than its
    evidence:

    | tier | meaning |
    |---|---|
    | `exact`      | a system's output equals the observed form, diacritics included |
    | `stripped`   | equal only after combining marks are removed, *and* the system emits diacritics — so the observation is that system degraded, not that system identified |
    | `gender`     | matched after normalising a gendered surname ending |
    | `patronymic` | both sides patronymic-shaped but in different systems (`-ұлы` vs `-ович`) |
    | `exonym` / `diminutive` | conventional English form or familiar form |
    | `initial`    | abbreviated to a single letter |
    | `fuzzy`      | none of the above; similar enough to be the same token, so the pair is ad-hoc rather than a dropped token |

    The `fuzzy` tier exists to stop a romanisation this module cannot model from being
    misreported as a *missing* token — the failure mode that produced spurious
    `token:dropped` tags in the first draft of this file.
    """
    cyr_tokens = N.tokens(cyrillic)
    lat_tokens = N.tokens(latin)

    used_lat: set[int] = set()
    pairs: list[dict] = []
    cyr_unmatched: list[str] = []

    def free() -> list[tuple[int, str]]:
        return [(j, t) for j, t in enumerate(lat_tokens) if j not in used_lat]

    for ctok in cyr_tokens:
        romans = _romanisations(ctok, language)
        matched = False

        # tier 1 — exact, diacritics included
        for j, ltok in free():
            lf = _casefold_only(ltok)
            systems = sorted(s for s, r in romans.items() if r == lf)
            if systems:
                used_lat.add(j)
                pairs.append({"cyr": ctok, "lat": ltok, "tier": "exact",
                              "systems": systems})
                matched = True
                break
        if matched:
            continue

        # tier 2 — equal after diacritic stripping. Only credited for systems that
        # actually emit diacritics; otherwise this tier would silently re-run tier 1.
        for j, ltok in free():
            lf = _fold(ltok)
            systems = sorted(
                s for s, r in romans.items()
                if _fold(r) == lf and s in T.DIACRITIC_SYSTEMS and _fold(r) != r
            )
            if systems:
                used_lat.add(j)
                pairs.append({"cyr": ctok, "lat": ltok, "tier": "stripped",
                              "systems": systems})
                matched = True
                break
        if matched:
            continue

        # tier 3 — gendered surname normalisation
        for alt, direction in ((N.masculine_of(ctok), "fem->masc"),
                               (N.feminine_of(ctok), "masc->fem")):
            if not alt:
                continue
            alt_romans = _romanisations(alt, language)
            for j, ltok in free():
                lf = _casefold_only(ltok)
                systems = sorted(s for s, r in alt_romans.items()
                                 if r == lf or _fold(r) == _fold(ltok))
                if systems:
                    used_lat.add(j)
                    pairs.append({"cyr": ctok, "lat": ltok, "tier": "gender",
                                  "systems": systems, "direction": direction})
                    matched = True
                    break
            if matched:
                break
        if matched:
            continue

        # tier 4 — exonym / diminutive
        low = ctok.lower()
        for j, ltok in free():
            lf = _fold(ltok)
            if lf in EXONYMS.get(low, set()):
                used_lat.add(j)
                pairs.append({"cyr": ctok, "lat": ltok, "tier": "exonym",
                              "systems": []})
                matched = True
                break
            if lf in DIMINUTIVES.get(low, set()):
                used_lat.add(j)
                pairs.append({"cyr": ctok, "lat": ltok, "tier": "diminutive",
                              "systems": []})
                matched = True
                break
        if matched:
            continue

        # tier 5 — abbreviated to an initial
        for j, ltok in free():
            lf = _fold(ltok)
            if len(lf) == 1 and any(_fold(r).startswith(lf) for r in romans.values()):
                used_lat.add(j)
                pairs.append({"cyr": ctok, "lat": ltok, "tier": "initial",
                              "systems": []})
                matched = True
                break
        if matched:
            continue

        # tier 6 — patronymic in a different system on each side
        if N.patronymic_kind(ctok):
            for j, ltok in free():
                if N.patronymic_kind(ltok):
                    used_lat.add(j)
                    pairs.append({
                        "cyr": ctok, "lat": ltok, "tier": "patronymic", "systems": [],
                        "kinds": [N.patronymic_kind(ctok), N.patronymic_kind(ltok)],
                    })
                    matched = True
                    break
        if matched:
            continue

        # tier 7 — fuzzy: same token, romanisation not modelled here
        best: tuple[float, int, str] | None = None
        for j, ltok in free():
            ratio = _best_ratio(romans, ltok)
            if ratio >= FUZZY_THRESHOLD and (best is None or ratio > best[0]):
                best = (ratio, j, ltok)
        if best is not None:
            _, j, ltok = best
            used_lat.add(j)
            pairs.append({"cyr": ctok, "lat": ltok, "tier": "fuzzy", "systems": [],
                          "ratio": round(best[0], 3)})
            continue

        cyr_unmatched.append(ctok)

    lat_unmatched = [t for j, t in enumerate(lat_tokens) if j not in used_lat]
    return {
        "pairs": pairs,
        "cyr_unmatched": cyr_unmatched,
        "lat_unmatched": lat_unmatched,
    }


def tag_cross_script(cyrillic: str, latin: str, language: str) -> tuple[list[str], dict]:
    """Phenomenon tags for a Cyrillic↔Latin pair, plus the alignment evidence."""
    tags: set[str] = set()
    align = align_tokens(cyrillic, latin, language)

    # --- romanisation attribution -----------------------------------------------------
    # A system is named only when it explains **every** aligned token at the `exact`
    # tier. Anything less and the pair is described by what actually happened —
    # `diacritics-stripped` or `ad-hoc` — never assigned to the nearest system.
    #
    # This rule exists because of a specific bug it prevents: `Мария Иванова` /
    # `Maria Ivanova` has one token BGN explains and one it does not (BGN gives
    # `Mariya`), and intersecting only over the tokens that *did* match exactly
    # produced a confident, wrong `romanisation:bgn`.
    pairs = align["pairs"]
    exact = [p for p in pairs if p["tier"] == "exact"]
    stripped = [p for p in pairs if p["tier"] == "stripped"]

    explaining: set[str] | None = None
    if pairs and len(exact) == len(pairs):
        for p in exact:
            explaining = set(p["systems"]) if explaining is None else \
                explaining & set(p["systems"])

    if explaining:
        order = T.ATTRIBUTION_ORDER.get(language, T.ATTRIBUTION_ORDER["ru"])
        primary = next(s for s in order if s in explaining)
        tags.add(f"romanisation:{_system_tag(primary)}")
    elif pairs and all(p["tier"] in ("exact", "stripped") for p in pairs) and stripped:
        # Explained only once combining marks are removed. Which standard produced it is
        # not recoverable — several collapse to the same ASCII — so the degradation is
        # reported instead of naming a system.
        tags.add("romanisation:diacritics-stripped")
    elif pairs:
        tags.add("romanisation:ad-hoc")

    # --- structure from the alignment tiers -------------------------------------------
    for p in align["pairs"]:
        tier = p["tier"]
        if tier == "initial":
            tags.add("patronymic:abbreviated" if N.patronymic_kind(p["cyr"])
                     else "token:abbreviated")
        elif tier == "exonym":
            tags.add("given:exonym")
        elif tier == "diminutive":
            tags.add("given:diminutive")
        elif tier == "gender":
            tags.add("gender:stripped" if p.get("direction") == "fem->masc"
                     else "gender:feminine-form")
        elif tier == "patronymic":
            tags.add("patronymic:form-substituted")
            for kind in p.get("kinds", []):
                if kind:
                    tags.add(f"patronymic:{kind}")
        elif tier == "fuzzy":
            tags.add("romanisation:ad-hoc")

    for ctok in align["cyr_unmatched"]:
        kind = N.patronymic_kind(ctok)
        if kind:
            tags.add("patronymic:dropped")
            tags.add(f"patronymic:{kind}")
        else:
            tags.add("token:dropped")

    for _ in align["lat_unmatched"]:
        tags.add("token:unaligned")

    # A patronymic present and aligned on both sides — records which convention is in use.
    found = N.find_patronymic(cyrillic)
    if found and "patronymic:dropped" not in tags:
        tags.add(f"patronymic:{found[1]}")

    # --- script and corruption --------------------------------------------------------
    if has_mixed_script(cyrillic) or has_mixed_script(latin):
        tags.add("corruption:mixed-script-homoglyph")

    if language == "kk":
        kk_specific = set("әғқңөұүһі")
        if set(cyrillic.lower()) & kk_specific:
            tags.add("kazakh:cyrillic-latin")
    if language == "uz" and ("ʻ" in latin or "‘" in latin or "'" in latin):
        tags.add("uzbek:apostrophe")

    if N.legal_form_group(cyrillic) is not None or N.legal_form_group(latin) is not None:
        tags.add("legal-form")

    # `order:swapped` is deliberately *not* inferred here. Token alignment is
    # order-insensitive by construction, so this module cannot observe order; the corpus
    # builder asserts the tag when it knows the pair was built from an inverted label.
    return sorted(tags), align


def _system_tag(system: str) -> str:
    """Map an internal system id to the vocabulary tag in `benchmark/README.md`."""
    return {
        "gost-b": "gost-b",
        "ala-lc": "ala-lc",
        "uk-kmu55": "uk-kmu55",
        "uk-bgn": "bgn",
        "kk-latin2021": "kk-latin2021",
        "kk-ru-mediated": "ru-mediated",
        "ky-bgn": "bgn",
        "ky-ru-mediated": "ru-mediated",
        "uz-latin1995": "uz-latin1995",
        "uz-ru-mediated": "ru-mediated",
    }.get(system, system)


def tag_same_script(a: str, b: str, language: str) -> list[str]:
    """Phenomenon tags for a Latin↔Latin (or Cyrl↔Cyrl) pair.

    Used for OFAC cross-romanisation variants, where both sides are Latin forms of one
    Cyrillic original produced by different systems. There is no Cyrillic side to align
    against, so tagging is limited to what is observable from the two Latin strings.
    """
    tags = {"script:same"}
    ta, tb = N.tokens(a), N.tokens(b)

    if len(ta) != len(tb):
        shorter, longer = (ta, tb) if len(ta) < len(tb) else (tb, ta)
        extra = [t for t in longer if _fold(t) not in {_fold(x) for x in shorter}]
        if any(N.patronymic_kind(t) for t in extra):
            tags.add("patronymic:dropped")
        else:
            tags.add("token:dropped")

    for t in ta + tb:
        kind = N.patronymic_kind(t)
        if kind and kind != "abbreviated":
            tags.add(f"patronymic:{kind}")
        elif kind == "abbreviated":
            tags.add("patronymic:abbreviated")

    if ta and tb and N.is_gendered_pair(ta[-1], tb[-1]):
        tags.add("gender:feminine-form")

    if N.legal_form_group(a) is not None or N.legal_form_group(b) is not None:
        tags.add("legal-form")

    if has_mixed_script(a) or has_mixed_script(b):
        tags.add("corruption:mixed-script-homoglyph")

    if language == "uz" and any("ʻ" in x or "‘" in x or "'" in x for x in (a, b)):
        tags.add("uzbek:apostrophe")

    # Differing romanisation is the reason these pairs exist, but which systems produced
    # them is not recoverable without the Cyrillic original.
    if _fold(a) != _fold(b):
        tags.add("romanisation:unattributed-variant")

    return sorted(tags)


def difficulty(same_entity: bool, tags: list[str], hard_negative: bool) -> str:
    """Structural difficulty. Never derived from a matcher's score — that would be
    circular, and `benchmark/README.md` requires difficulty to be a property of the pair.

    A positive is `easy` only when it differs by script alone: one attributable
    romanisation standard, same token count, no structural change. Everything else is
    `hard`.
    """
    if not same_entity:
        return "hard" if hard_negative else "easy"

    structural = {
        "patronymic:dropped", "patronymic:abbreviated", "order:swapped",
        "gender:feminine-form", "gender:stripped", "token:dropped", "token:unaligned",
        "given:exonym", "given:diminutive", "corruption:ocr", "corruption:typo",
        "corruption:mixed-script-homoglyph", "kazakh:derussified",
    }
    if any(t in structural for t in tags):
        return "hard"
    if "romanisation:ad-hoc" in tags or "romanisation:unattributed-variant" in tags:
        return "hard"
    return "easy"
