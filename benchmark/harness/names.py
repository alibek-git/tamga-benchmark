"""Name-structure analysis for corpus construction and phenomenon tagging.

This is **not** engine code. It exists so the benchmark can (a) tag what each pair
actually tests and (b) build hard negatives that are structurally adversarial —
`Иванов Пётр` vs `Иванов Павел` — rather than merely string-similar by accident.

Deliberately kept crude. Anything clever here would leak the engine's own assumptions
into the benchmark that is supposed to judge it (`benchmark/README.md`, on the synthetic
cap). Where structure is ambiguous the functions return `None` and the caller must
degrade gracefully rather than guess.
"""

from __future__ import annotations

import unicodedata

CYRILLIC_RANGES = ((0x0400, 0x04FF), (0x0500, 0x052F), (0x2DE0, 0x2DFF), (0xA640, 0xA69F))

# Slavic patronymic endings, masculine then feminine, across the East Slavic languages:
# Russian `-ович/-овна`, Ukrainian `-ович/-івна`, Belarusian `-авіч/-аўна`. Belarusian and
# Ukrainian feminine forms are included because omitting them made
# `Валянцінаўна` unrecognisable as a patronymic and mis-tagged a dropped patronymic as a
# dropped ordinary token.
RU_PATRONYMIC_SUFFIXES = (
    "ович", "евич", "ьевич", "иевич", "овна", "евна", "ьевна", "ична", "инична",
    "авіч", "евіч", "овіч", "іч", "аўна", "еўна", "оўна",
    "івна", "ївна", "йович", "ович",
)
RU_PATRONYMIC_SUFFIXES_LAT = (
    "ovich", "evich", "yevich", "ievich", "ovna", "evna", "yevna", "ichna", "inichna",
    "ovic", "evic", "avich", "ovych", "yovych", "ivna", "yivna", "auna", "euna",
    "avic", "ovna",
)

# Turkic patronymic particles (`docs/domain-notes.md` §3).
TURKIC_PARTICLES_CYR = ("ұлы", "улы", "қызы", "кызы", "кизи", "угли", "оглы", "ұлі")
TURKIC_PARTICLES_LAT = ("uly", "ulı", "ұly", "kyzy", "qyzy", "kizi", "ugli", "oglu",
                        "ogly", "uulu")

# Gendered surname endings: (feminine, masculine).
GENDERED_SUFFIX_PAIRS_CYR = (
    ("ова", "ов"), ("ева", "ев"), ("ёва", "ёв"), ("ина", "ин"), ("ына", "ын"),
    ("ская", "ский"), ("цкая", "цкий"), ("ая", "ый"),
)
GENDERED_SUFFIX_PAIRS_LAT = (
    ("ova", "ov"), ("eva", "ev"), ("ova", "off"), ("ina", "in"), ("yna", "yn"),
    ("skaya", "sky"), ("skaia", "skii"), ("skaya", "skiy"), ("tskaya", "tsky"),
)

# Legal-form tokens (`docs/domain-notes.md` §6). Groups of mutually form-equivalent
# markers; membership in one group is what a matcher must not treat as a name difference.
LEGAL_FORM_GROUPS = (
    ("ооо", "ooo", "llc", "ltd", "limited liability company", "о.о.о."),
    ("оао", "oao", "ао", "ao", "jsc", "joint stock company"),
    ("зао", "zao", "cjsc"),
    ("пао", "pao", "pjsc"),
    ("тоо", "too", "llp"),
    ("ип", "ip", "sole proprietor"),
    ("нк", "nk", "national company"),
)


def detect_script(text: str) -> str:
    """ISO 15924 code for the dominant script: `Cyrl`, `Latn`, `Mixed`, or `Zyyy`."""
    cyr = lat = 0
    for ch in text:
        if not ch.isalpha():
            continue
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in CYRILLIC_RANGES):
            cyr += 1
        else:
            try:
                if "LATIN" in unicodedata.name(ch):
                    lat += 1
            except ValueError:
                pass
    if cyr and lat:
        return "Mixed"
    if cyr:
        return "Cyrl"
    if lat:
        return "Latn"
    return "Zyyy"


# Orthography-specific Cyrillic letters, used to infer which language a Cyrillic string
# is written in when no metadata says so (OFAC records the script, not the language).
#
# This is evidence from the letter inventory, which is more direct than a nationality
# field: `Рыгоравiч` is Belarusian orthography whatever passport its bearer holds. It is
# still a heuristic and it fails on names that happen to use no distinctive letter, which
# fall through to `ru`. Corpus records carry `language_basis` so this inference is never
# mistaken for ground truth.
# Letters exclusive to Kazakh among the Turkic Cyrillic orthographies here. Kazakh and
# Kyrgyz **share** `ң ө ү`, so those alone cannot separate them — checking the shared set
# first collapsed every Kyrgyz name into `kk` and emptied the `ky` slice entirely.
_KK_EXCLUSIVE = set("әұіқғһ")
_KK_KY_SHARED = set("ңөү")


def guess_language_from_orthography(text: str, hint: str | None = None
                                    ) -> tuple[str, str]:
    """Infer language from distinctive Cyrillic letters. Returns `(lang, basis)`.

    `basis` names the evidence so a reader can audit the inference: `orthography:<letters>`,
    `orthography+hint:...` where the letters were ambiguous and the source label language
    broke the tie, or `default:ru` when nothing distinctive is present.

    `hint` is the language code of the label the name came from. It is consulted **only**
    for the genuine Kazakh/Kyrgyz ambiguity, never to override positive orthographic
    evidence — the whole reason this function exists is that the label language is
    frequently wrong about the name (`Ольга Александровна Булавкина` filed under `kk`).

    Latin homoglyphs are folded to Cyrillic first, so a corrupted Belarusian name is not
    misread as Russian because its `і` was stored as a Latin `i`.
    """
    low = set(fold_homoglyphs_to_cyrillic(text).lower())

    # Ukrainian-only letters.
    if low & set("їєґ"):
        return "uk", f"orthography:{''.join(sorted(low & set('їєґ')))}"
    # Tajik-only descenders and macrons.
    if low & set("ҷӣӯ"):
        return "tg", f"orthography:{''.join(sorted(low & set('ҷӣӯ')))}"
    # `ў` is Belarusian; Uzbek Cyrillic also uses it, distinguished by `қ ғ ҳ`.
    if "ў" in low:
        if low & set("қғҳ"):
            return "uz", "orthography:ў+қғҳ"
        return "be", "orthography:ў"
    if low & set("әұ"):
        return "kk", f"orthography:{''.join(sorted(low & set('әұ')))}"
    # Ukrainian and Belarusian both use `і`; Ukrainian orthography has no `ы`, `э` or `ъ`.
    if "і" in low and not (low & _KK_EXCLUSIVE - {"і"}):
        if low & set("ыэъ"):
            return "be", "orthography:і+ыэъ"
        return "uk", "orthography:і"
    if low & _KK_EXCLUSIVE:
        return "kk", f"orthography:{''.join(sorted(low & _KK_EXCLUSIVE))}"
    if low & _KK_KY_SHARED:
        letters = "".join(sorted(low & _KK_KY_SHARED))
        if hint in ("kk", "ky"):
            return hint, f"orthography+hint:{letters}|label={hint}"
        return "kk", f"orthography:{letters}"
    return "ru", "default:ru"


def normalise_ws(text: str) -> str:
    return " ".join(text.replace(" ", " ").split())


def strip_wikidata_disambiguator(label: str) -> str:
    """Wikidata labels carry parenthetical qualifiers: `Ivanov (footballer)`."""
    if "(" in label:
        label = label.split("(")[0]
    return normalise_ws(label)


def uninvert(label: str) -> tuple[str, bool]:
    """Wikidata `ru` labels are often inverted: `Мухамеджанов, Бауржан Алимович`.

    Returns `(natural_order_name, was_inverted)`. Only a single comma is handled;
    anything stranger is left alone, because guessing would corrupt a label.
    """
    if label.count(",") != 1:
        return normalise_ws(label), False
    surname, rest = (p.strip() for p in label.split(","))
    if not surname or not rest:
        return normalise_ws(label), False
    return normalise_ws(f"{rest} {surname}"), True


def tokens(name: str) -> list[str]:
    return [t for t in normalise_ws(name).replace("-", " ").split() if t]


def _endswith_any(token: str, suffixes) -> str | None:
    low = token.lower().rstrip(".")
    for suf in sorted(suffixes, key=len, reverse=True):
        if low.endswith(suf) and len(low) > len(suf):
            return suf
    return None


def patronymic_kind(token: str) -> str | None:
    """`russified`, `turkic`, `abbreviated`, or None."""
    low = token.lower().rstrip(".")
    if len(low) <= 2 and token.endswith("."):
        return "abbreviated"
    if _endswith_any(token, RU_PATRONYMIC_SUFFIXES) or _endswith_any(
        token, RU_PATRONYMIC_SUFFIXES_LAT
    ):
        return "russified"
    if low in TURKIC_PARTICLES_CYR or low in TURKIC_PARTICLES_LAT:
        return "turkic"
    if _endswith_any(token, TURKIC_PARTICLES_CYR) or _endswith_any(
        token, TURKIC_PARTICLES_LAT
    ):
        return "turkic"
    return None


def find_patronymic(name: str) -> tuple[int, str] | None:
    """Index and kind of the first token that looks like a patronymic."""
    for i, tok in enumerate(tokens(name)):
        kind = patronymic_kind(tok)
        if kind:
            return i, kind
    return None


def split_name_parts(name: str, inverted_label: bool = False) -> dict:
    """Locate the surname in a CIS personal name. Returns parts plus the evidence used.

    Naively taking the last token is wrong often enough to corrupt a corpus: CIS labels
    appear as `Given Patronymic Surname`, as `Surname, Given Patronymic` (comma), **and
    as `Surname Given Patronymic` with no comma at all** — `Кічук Ярослав Валерійович`.
    Taking the last token there yields the patronymic, which silently grouped unrelated
    people together when building same-surname and patronymic-collision negatives.

    The patronymic's *position* disambiguates: it sits second in given-first order and
    last in surname-first order.
    """
    toks = tokens(name)
    result = {"given": None, "patronymic": None, "surname": None, "basis": "unknown",
              "order": "unknown"}
    if not toks:
        return result

    if inverted_label and "," in name:
        surname = normalise_ws(name.split(",")[0])
        rest = tokens(normalise_ws(name.split(",", 1)[1]))
        result.update(surname=surname, given=rest[0] if rest else None,
                      patronymic=rest[1] if len(rest) > 1 else None,
                      basis="comma", order="surname-first")
        return result

    pat = find_patronymic(name)
    if pat and len(toks) >= 3:
        idx = pat[0]
        if idx == len(toks) - 1:
            # `Surname Given Patronymic` — patronymic in final position.
            result.update(surname=toks[0], given=toks[1], patronymic=toks[idx],
                          basis="patronymic-final", order="surname-first")
            return result
        if idx == 1:
            # `Given Patronymic Surname` — the common natural order.
            result.update(given=toks[0], patronymic=toks[1], surname=toks[-1],
                          basis="patronymic-second", order="given-first")
            return result

    if pat and len(toks) == 2:
        idx = pat[0]
        other = toks[1 - idx]
        result.update(patronymic=toks[idx], surname=other, basis="two-token-patronymic",
                      order="unknown")
        return result

    # No patronymic to anchor on. Default to given-first, the dominant convention in
    # Wikidata labels once the comma-inverted ones are handled above.
    result.update(given=toks[0], surname=toks[-1], basis="default-given-first",
                  order="given-first")
    return result


# Latin letters that are visually identical to a Cyrillic letter. Real watchlist data
# contains these (236 OFAC SDN Cyrillic-declared variants, list of 2026-07-24), and they
# defeat both script detection and language inference unless folded first.
_HOMOGLYPH_LATIN_TO_CYRILLIC = {
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "y": "у", "x": "х", "i": "і",
    "A": "А", "B": "В", "E": "Е", "K": "К", "M": "М", "H": "Н", "O": "О", "P": "Р",
    "C": "С", "T": "Т", "X": "Х", "I": "І",
}


def fold_homoglyphs_to_cyrillic(text: str) -> str:
    """Map Latin homoglyphs onto Cyrillic. For *analysis only* — never for stored names.

    Used so that `Аляксандр Васiльевiч` (Latin `i`) is still recognised as Belarusian
    orthography rather than defaulting to Russian.
    """
    if detect_script(text) != "Mixed":
        return text
    return "".join(_HOMOGLYPH_LATIN_TO_CYRILLIC.get(c, c) for c in text)


def feminine_of(surname: str) -> str | None:
    """Masculine surname → feminine form, or None if not a gendered pattern."""
    low = surname.lower()
    for fem, masc in GENDERED_SUFFIX_PAIRS_CYR + GENDERED_SUFFIX_PAIRS_LAT:
        if low.endswith(masc) and len(low) > len(masc):
            stem = surname[: len(surname) - len(masc)]
            return stem + (fem.upper() if surname.isupper() else fem)
    return None


def masculine_of(surname: str) -> str | None:
    """Feminine surname → masculine form, or None."""
    low = surname.lower()
    for fem, masc in GENDERED_SUFFIX_PAIRS_CYR + GENDERED_SUFFIX_PAIRS_LAT:
        if low.endswith(fem) and len(low) > len(fem):
            stem = surname[: len(surname) - len(fem)]
            return stem + (masc.upper() if surname.isupper() else masc)
    return None


def is_gendered_pair(a: str, b: str) -> bool:
    """Are these the masculine and feminine forms of one surname?"""
    return masculine_of(a) == b or masculine_of(b) == a or feminine_of(a) == b or \
        feminine_of(b) == a


def legal_form_group(name: str) -> int | None:
    """Index of the legal-form group a name's tokens fall in, if any."""
    low = " " + normalise_ws(name).lower().replace('"', " ").replace("«", " ") + " "
    for idx, group in enumerate(LEGAL_FORM_GROUPS):
        for marker in group:
            if f" {marker} " in low:
                return idx
    return None


def strip_legal_form(name: str) -> str:
    low = normalise_ws(name)
    for group in LEGAL_FORM_GROUPS:
        for marker in sorted(group, key=len, reverse=True):
            for variant in (marker, marker.upper(), marker.title()):
                low = low.replace(variant, " ")
    return normalise_ws(low.replace('"', " ").replace("«", " ").replace("»", " "))


def looks_like_person_name(name: str) -> bool:
    """Cheap sanity filter: 2–5 alphabetic tokens, no digits, no org markers."""
    toks = tokens(name)
    if not 2 <= len(toks) <= 5:
        return False
    if any(ch.isdigit() for ch in name):
        return False
    if legal_form_group(name) is not None:
        return False
    return all(any(c.isalpha() for c in t) for t in toks)
