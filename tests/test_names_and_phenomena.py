"""Layer 1 — name-structure parsing and phenomenon tagging.

The tagger produces the error taxonomy, which `benchmark/README.md` calls the whole point
of the corpus. A wrong tag yields a confidently wrong diagnosis, so the tests below are
weighted toward the two failure modes that actually occurred during the pilot build:
mis-locating the surname, and over-claiming a romanisation standard.
"""

from __future__ import annotations

import pytest

from harness import names as N
from harness import phenomena as P


# --------------------------------------------------------------------------------------
# name structure
# --------------------------------------------------------------------------------------

# (name, inverted_label, expected surname)
SURNAMES = [
    # `Given Patronymic Surname` — the common natural order.
    ("Геннадий Геннадьевич Головкин", False, "Головкин"),
    ("Зоя Валянцінаўна Белахвосцік", False, "Белахвосцік"),
    ("Сәтімжан Қамзеұлы Санбаев", False, "Санбаев"),
    # `Surname Given Patronymic` with **no comma** — the case that broke the pilot.
    ("Кічук Ярослав Валерійович", False, "Кічук"),
    ("Кім Віталій Олександрович", False, "Кім"),
    ("Федорейко Валерій Степанович", False, "Федорейко"),
    # Comma-inverted, as Wikidata stores many labels.
    ("Осьминский, Василий Михайлович", True, "Осьминский"),
    # Two tokens, no patronymic to anchor on.
    ("Данила Рублев", False, "Рублев"),
]


@pytest.mark.parametrize("name,inverted,expected", SURNAMES)
def test_surname_is_located_structurally(name: str, inverted: bool,
                                         expected: str) -> None:
    """**Regression.** Taking the last token as the surname returned the *patronymic* for
    surname-first labels without a comma, which silently grouped unrelated people into the
    same-surname and patronymic-collision negative slices.
    """
    assert N.split_name_parts(name, inverted)["surname"] == expected


def test_patronymic_kinds_across_east_slavic_and_turkic() -> None:
    assert N.patronymic_kind("Григорьевич") == "russified"
    assert N.patronymic_kind("Петровна") == "russified"
    # Belarusian and Ukrainian feminine forms — regression: these were unrecognised, so a
    # dropped patronymic was mis-tagged as a dropped ordinary token.
    assert N.patronymic_kind("Валянцінаўна") == "russified"
    assert N.patronymic_kind("Леонідівна") == "russified"
    assert N.patronymic_kind("Қамзеұлы") == "turkic"
    assert N.patronymic_kind("Серікқызы") == "turkic"
    assert N.patronymic_kind("И.") == "abbreviated"
    assert N.patronymic_kind("Головкин") is None


def test_gendered_surname_pairs() -> None:
    assert N.feminine_of("Иванов") == "Иванова"
    assert N.masculine_of("Иванова") == "Иванов"
    assert N.is_gendered_pair("Петровский", "Петровская")
    assert not N.is_gendered_pair("Ким", "Ли")


def test_script_detection_and_homoglyph_folding() -> None:
    assert N.detect_script("Щербаков") == "Cyrl"
    assert N.detect_script("Shcherbakov") == "Latn"
    # A Latin `i` inside a Cyrillic name — present 236 times in the OFAC SDN list itself.
    assert N.detect_script("Рыгоравiч") == "Mixed"
    assert N.detect_script(N.fold_homoglyphs_to_cyrillic("Рыгоравiч")) == "Cyrl"


def test_language_inference_prefers_orthography_over_label_language() -> None:
    """A Russian name sitting in the `kk` label field is Russian, whatever the field says."""
    lang, basis = N.guess_language_from_orthography("Ольга Александровна Булавкина",
                                                    hint="kk")
    assert lang == "ru" and basis == "default:ru"
    assert N.guess_language_from_orthography("Сәтімжан Қамзеұлы", hint="kk")[0] == "kk"
    assert N.guess_language_from_orthography("Кічук Ярослав", hint="uk")[0] == "uk"
    assert N.guess_language_from_orthography("Мікіта Крыўцоў", hint="be")[0] == "be"


def test_kazakh_and_kyrgyz_are_separable() -> None:
    """**Regression.** Kazakh and Kyrgyz share `ң ө ү`. Checking the shared set first
    collapsed every Kyrgyz name into `kk` and emptied the `ky` slice entirely.
    """
    assert N.guess_language_from_orthography("Кубанычбек Өмүралиев", hint="ky")[0] == "ky"
    assert N.guess_language_from_orthography("Сәтімжан Санбаев", hint="ky")[0] == "kk", \
        "Kazakh-exclusive letters must win over the hint"


def test_legal_form_grouping() -> None:
    assert N.legal_form_group("ООО Волга Груп") == N.legal_form_group("OOO Volga Group")
    assert N.legal_form_group("ТОО Астана") == N.legal_form_group("Astana LLP")
    assert N.legal_form_group("Волга Груп") is None


# --------------------------------------------------------------------------------------
# phenomenon tagging
# --------------------------------------------------------------------------------------

def tags_for(cyrillic: str, latin: str, language: str) -> list[str]:
    return P.tag_cross_script(cyrillic, latin, language)[0]


def test_clean_romanisation_names_one_system() -> None:
    tags = tags_for("Юрий Ёлкин", "Iurii Elkin", "ru")
    assert "romanisation:icao" in tags


def test_never_names_a_system_that_does_not_explain_every_token() -> None:
    """**Regression.** `Мария Иванова`/`Maria Ivanova` was tagged `romanisation:bgn`, but
    BGN gives `Mariya`. The tag came from intersecting only the tokens that *did* match,
    which manufactured confidence. A system may be named only if it explains all of them.
    """
    tags = tags_for("Мария Иванова", "Maria Ivanova", "ru")
    assert "romanisation:bgn" not in tags
    assert "romanisation:diacritics-stripped" in tags


def test_unmodellable_romanisation_is_ad_hoc_not_nearest_system() -> None:
    tags = tags_for("Щербаков Александр", "Scherbakov Alexander", "ru")
    assert "romanisation:ad-hoc" in tags
    assert not any(t.startswith("romanisation:") and t != "romanisation:ad-hoc"
                   for t in tags)


def test_dropped_patronymic_is_not_reported_as_a_dropped_token() -> None:
    tags = tags_for("Мухтар Капашевич Алтынбаев", "Mukhtar Altynbayev", "kk")
    assert "patronymic:dropped" in tags and "token:dropped" not in tags


def test_present_token_is_never_reported_as_missing() -> None:
    """**Regression.** A romanisation the tables cannot model made a token that is present
    on both sides look absent, producing spurious `token:dropped` / `token:unaligned`.
    """
    tags = tags_for("Алег Леанідавіч Сліжэўскі", "Aleh Leanidavich Slizheuski", "be")
    assert "token:dropped" not in tags and "token:unaligned" not in tags


def test_gender_stripping_detected_regardless_of_token_order() -> None:
    tags = tags_for("Иванова Мария Петровна", "Maria Ivanov", "ru")
    assert "gender:stripped" in tags


def test_turkic_and_russified_patronymics_are_a_substitution() -> None:
    tags = tags_for("Нұрсұлтан Әбішұлы Назарбаев", "Nursultan Abishevich Nazarbayev",
                    "kk")
    assert "patronymic:form-substituted" in tags
    assert "patronymic:turkic" in tags and "patronymic:russified" in tags


def test_abbreviated_patronymic() -> None:
    assert "patronymic:abbreviated" in tags_for("Олег Леонидович Слижевский",
                                                "Oleg L. Slizhevskiy", "ru")


def test_exonym_is_distinguished_from_romanisation() -> None:
    tags = tags_for("Александр Григорьевич Лукашенко",
                    "Alexander Grigoryevich Lukashenko", "ru")
    assert "given:exonym" in tags


def test_mixed_script_corruption_is_tagged_not_cleaned() -> None:
    tags = tags_for("Аляксандр Рыгоравiч Лукашэнка", "Alyaksandr Ryhorovich Lukashenka",
                    "be")
    assert "corruption:mixed-script-homoglyph" in tags


def test_difficulty_is_structural_not_score_derived() -> None:
    assert P.difficulty(True, ["romanisation:icao"], False) == "easy"
    assert P.difficulty(True, ["romanisation:icao", "patronymic:dropped"], False) == "hard"
    assert P.difficulty(True, ["romanisation:ad-hoc"], False) == "hard"
    assert P.difficulty(False, [], hard_negative=True) == "hard"
    assert P.difficulty(False, [], hard_negative=False) == "easy"


def test_every_extended_tag_is_documented() -> None:
    """The vocabulary is controlled, not free text (`benchmark/README.md`)."""
    for tag, why in P.EXTENDED_VOCABULARY.items():
        assert why.strip(), f"{tag} has no documented meaning"


# --------------------------------------------------------------------------------------
# LLM-judge response handling
#
# These are unit tests for the *parsing*, not the model. They exist because the first
# implementation scored a truncated response as 0.0, and truncation correlates with pair
# difficulty — so the bug quietly biased a competitor baseline downward on exactly the
# hard cases. That is the kind of error that flatters our own thesis, so it is pinned.
# --------------------------------------------------------------------------------------

class _Block:
    def __init__(self, type_: str, text: str | None = None) -> None:
        self.type = type_
        self.text = text


class _Resp:
    def __init__(self, *blocks: _Block) -> None:
        self.content = list(blocks)


def test_extract_text_skips_leading_non_text_blocks() -> None:
    """Claude 5 emits a `thinking` block first, so `content[0].text` is None and indexing
    blindly raised AttributeError on a real call."""
    from harness import baselines as B
    resp = _Resp(_Block("thinking", None), _Block("text", "0.97"))
    assert B._extract_text(resp) == "0.97"


def test_extract_text_returns_empty_when_only_thinking_present() -> None:
    """A response truncated mid-thinking has no text at all. It must report empty so the
    caller retries with a larger budget rather than recording a confident 0.0."""
    from harness import baselines as B
    assert B._extract_text(_Resp(_Block("thinking", None))) == ""
    assert B._extract_text(_Resp()) == ""


def test_llm_token_budget_leaves_room_for_an_answer_after_thinking() -> None:
    """Regression guard on the constant itself: at max_tokens=8 the entire budget went to
    thinking and 2 of 12 sampled pairs became unparseable."""
    from harness import baselines as B
    assert B.LLM_MAX_TOKENS >= 512
    assert B.LLM_MAX_TOKENS_RETRY > B.LLM_MAX_TOKENS
