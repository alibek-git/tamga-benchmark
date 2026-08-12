"""Layer 1 — unit tests for the romanisation tables.

Every case here is either documented in `docs/domain-notes.md` §2-§3 or was the specific
input that exposed a defect during the pilot build. The regression cases are labelled as
such: they are the reason the test exists, not decoration.
"""

from __future__ import annotations

import pytest

from harness import names as N
from harness import translit as T

# (cyrillic, system, expected) — the table in docs/domain-notes.md §2, and the Kazakh,
# Ukrainian, Uzbek and Belarusian cases from §3 and §5.
DOCUMENTED = [
    ("Александр Щербаков", "bgn", "Aleksandr Shcherbakov"),
    ("Александр Щербаков", "icao", "Aleksandr Shcherbakov"),
    ("Александр Щербаков", "gost-b", "Aleksandr Shherbakov"),
    ("Александр Щербаков", "iso9", "Aleksandr Ŝerbakov"),
    ("Александр Щербаков", "scholarly", "Aleksandr Ščerbakov"),
    ("Александр Щербаков", "ad-hoc", "Aleksandr Scherbakov"),
    # `я`/`ю` are where ICAO diverges from BGN, which is the reason ICAO matters:
    # it is the passport MRZ standard, so it is what KYC records copied from ID
    # documents contain.
    ("Юрий", "bgn", "Yuriy"),
    ("Юрий", "icao", "Iurii"),
    # Ukrainian KMU 55:2010 — `г`→h is the diagnostic letter against Russian `г`→g.
    ("Гончаров", "uk-kmu55", "Honcharov"),
    ("Гончаров", "bgn", "Goncharov"),
    # Kazakh: the Russian-mediated form collapses letters the 2021 Latin form keeps.
    ("Нұрсұлтан", "kk-ru-mediated", "Nursultan"),
    ("Нұрсұлтан", "kk-latin2021", "Nūrsūltan"),
    ("Шымкент", "kk-ru-mediated", "Shymkent"),
    ("Шымкент", "kk-latin2021", "Şymkent"),
    # Uzbek 1995 official, with U+02BB as the canonical modifier letter.
    ("Ўзбекистон", "uz-latin1995", "Oʻzbekiston"),
    # Belarusian: `е` is `ye` only word-initially / after a vowel, so `Алег`→`Aleh`.
    ("Алег", "be-bgn", "Aleh"),
]


@pytest.mark.parametrize("cyrillic,system,expected", DOCUMENTED)
def test_documented_romanisations(cyrillic: str, system: str, expected: str) -> None:
    assert T.romanise(cyrillic, system) == expected


LEAK_SAMPLES = [
    "Зубков Олег Олексійович",       # Ukrainian і — regression, see below
    "Лявонці Ульянавіч Зданевіч",   # Belarusian і
    "Сәтімжан Қамзеұлы Санбаев",    # Kazakh ә ұ і
    "Ҳабиба Каримова",              # Uzbek/Tajik ҳ
    "Мікіта Крыўцоў",               # Belarusian ў
    "Рустами Эмомалӣ",              # Tajik ӣ
    "Чыңгыз Айтматов",              # Kyrgyz ң
    "Щербаков Ёлкин Цыганов",       # Russian щ ё ц
]


@pytest.mark.parametrize("system", T.SYSTEM_NAMES)
@pytest.mark.parametrize("text", LEAK_SAMPLES)
def test_no_cyrillic_survives_any_system(system: str, text: str) -> None:
    """**Regression.** Applying the Russian ISO 9 table to Ukrainian text left `і`
    untransliterated and emitted mixed-script output (`Олексійович`→`Oleksіjovic`) — corrupt
    data masquerading as a hard pair. No system, on any language, may leak Cyrillic.
    """
    out = T.romanise(text, system)
    assert N.detect_script(out) == "Latn", f"{system} leaked Cyrillic: {out!r}"


def test_bgn_ye_rule_is_positional() -> None:
    """BGN/PCGN writes `е` as `ye` word-initially and after a vowel, `e` elsewhere."""
    assert T.romanise("Ельцин", "bgn").startswith("Yel")
    assert "ye" not in T.romanise("Пётр", "bgn").lower().replace("yo", "")
    assert T.romanise("Ёлкин", "bgn") == "Yëlkin"


def test_strip_diacritics_preserves_case() -> None:
    """**Regression.** An earlier version lowercased uppercase letters while stripping,
    turning `Şymkent` into ` symkent`."""
    assert T.strip_diacritics("Şymkent") == "Symkent"
    assert T.strip_diacritics("Nūrsūltan Ŝerbakov") == "Nursultan Serbakov"
    assert T.strip_diacritics("ʹʺ") == ""


def test_uzbek_apostrophe_variants_are_three_distinct_codepoints() -> None:
    variants = T.uzbek_apostrophe_variants("Gʻulomov Oʻtkir")
    assert len(set(variants)) == 3
    assert "ʻ" in variants[0] and "‘" in variants[1] and "'" in variants[2]


def test_uzbek_latin_to_cyrillic_roundtrips_the_modifier_letters() -> None:
    assert T.uzbek_latin_to_cyrillic("Oʻzbekiston") == "Ўзбекистон"
    assert T.uzbek_latin_to_cyrillic("Gʻulomov") == "Ғуломов"


def test_collapse_folds_only_what_russian_mediation_destroys() -> None:
    """Two different Kazakh surnames collapsing to one Latin form is the sharpest hard
    negative the corpus contains, so this fold defines that slice."""
    assert T.collapse("Әбиев") == T.collapse("Абиев")
    assert T.collapse("Ақан") == T.collapse("Акан")
    assert T.collapse("Иванов") != T.collapse("Смирнов")


def test_attribution_reports_ties_rather_than_guessing() -> None:
    system, exact, matching = T.attribute("Александр Щербаков", "Aleksandr Shcherbakov",
                                          "ru")
    assert exact and system in matching and len(matching) >= 2, matching


def test_attribution_falls_back_to_ad_hoc_not_nearest() -> None:
    system, exact, matching = T.attribute("Александр Щербаков", "Alexander Scherbakov",
                                          "ru")
    assert (system, exact, matching) == ("ad-hoc", False, [])


def test_romanise_is_deterministic() -> None:
    for system in T.SYSTEM_NAMES:
        first = T.romanise("Щербаков Александр Иванович", system)
        for _ in range(3):
            assert T.romanise("Щербаков Александр Иванович", system) == first
