"""Assemble the benchmark corpus from the committed source snapshots.

Builds the full ≥5,000-pair corpus specified in `benchmark/README.md`. The pilot that
preceded it (`pilot-v0.1`, 460 pairs) stays committed for provenance; this version
supersedes it for all reported results.

The negative count matters as much as the total. Recall at 0.1% FPR — which `PLAN.md`
requires — is only expressible when the corpus has enough negatives to resolve it, since
the finest achievable FPR step is `1/n_negatives`. The pilot's 230 negatives could not
represent any rate below 0.43%, so that metric was reported as unresolvable rather than
interpolated. This corpus carries 2,500.

## Determinism

Byte-identical output from the same snapshots, forever (`CLAUDE.md` §4). Achieved by:
seeding one `random.Random` with a fixed constant, sorting every collection before
sampling from it, and never iterating a set or dict whose order depends on insertion.
There is no wall-clock or hostname input to the corpus itself.

## What is deliberately excluded, and why

**Negatives whose two names are identical after normalisation.** Two different people
genuinely do share a full name, and different dates of birth prove they are different
entities — so these pairs are correctly labelled. They are still excluded, because no
name matcher can resolve them from names alone. Including them would add a fixed error
floor to every baseline that tells us nothing about the *transliteration* gap this
benchmark exists to measure. The count of exclusions is reported in the manifest so the
choice is visible rather than buried.

**Wikidata items lacking a date of birth, on the negative side.** Distinct QIDs are not
quite a guarantee of distinct entities — Wikidata contains duplicate items — and two
items for one person almost always share a DOB. Requiring both DOBs present and
different removes that risk at the cost of some sample size.
"""

from __future__ import annotations

import argparse
import collections
import difflib
import hashlib
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from harness import names as N          # noqa: E402
from harness import phenomena as P      # noqa: E402
from harness import translit as T       # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SOURCES = ROOT / "benchmark" / "sources"
PAIRS = ROOT / "benchmark" / "pairs"

SEED = 20260726
DATASET_VERSION = "v1.0"

# Composition targets for the full corpus (`benchmark/README.md`: ≥5,000 pairs).
#
# The negative count is set at 2,500 for a specific reason: **recall at 0.1% FPR is only
# measurable when the corpus has enough negatives to resolve it.** With `n` negatives the
# finest achievable FPR step is `1/n`, so the pilot's 230 negatives could not express any
# rate below 0.43% and the metric was reported as unresolvable. At 2,500 negatives, 0.1%
# FPR corresponds to 2 permitted false positives, and the hard-negatives-only slice
# (1,900) resolves it at 1 — so the number `PLAN.md` asks for becomes real rather than
# interpolated.
TARGETS = {
    "positive": {
        "ofac-cross-script": 700,
        "ofac-cross-romanisation": 550,
        "wikidata-cross-script": 500,
        "synthetic": 750,
    },
    "negative": {
        "same-surname": 650,
        "similar-string": 700,
        "gender-pair": 380,
        "romanisation-collision": 380,
        "patronymic-collision": 200,
        "easy": 700,
    },
}

# Per-entity caps, so no single heavily-aliased SDN entry or surname group can dominate a
# slice. Raised from the pilot's flat 2 because the full corpus needs an order of magnitude
# more pairs from the same source pools; entity diversity is preserved by capping per
# *group* as well as per entity.
MAX_PAIRS_PER_ENTITY = 3
MAX_NEGATIVES_PER_GROUP = 3

REQUIRED_LANGUAGES = ("ru", "kk", "uk", "uz", "ky")


# --------------------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------------------

def newest(pattern: str) -> Path:
    found = sorted(SOURCES.glob(pattern))
    if not found:
        raise SystemExit(f"no source snapshot matching {pattern} in {SOURCES}")
    return found[-1]


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def clean_wikidata(rows: list[dict]) -> list[dict]:
    """Normalise labels and drop rows unusable as name pairs.

    `language` is taken from the name's **orthography**, not from the Wikidata label
    language code that produced the row. The codes are not interchangeable: the `kk`
    label of a Kazakhstani citizen is frequently a Russian name in Russian orthography
    (`Ольга Александровна Булавкина`), and filing that under `kk` would make the
    per-language breakdown say something false about Kazakh. `label_language` keeps the
    original code so the substitution is auditable.
    """
    out: list[dict] = []
    for r in rows:
        native_raw = N.strip_wikidata_disambiguator(r["native"])
        en = N.strip_wikidata_disambiguator(r["en"])
        native, inverted = N.uninvert(native_raw)
        if not native or not en:
            continue
        if r["entity_type"] == "person":
            if not (N.looks_like_person_name(native) and N.looks_like_person_name(en)):
                continue
        native_script = N.detect_script(native)
        if native_script in ("Cyrl", "Mixed"):
            language, basis = N.guess_language_from_orthography(native, hint=r["native_lang"])
        else:
            language, basis = r["native_lang"], "label-language:non-cyrillic"
        parts = N.split_name_parts(native_raw if inverted else native, inverted)
        out.append({
            **r,
            "native": native,
            "native_raw": native_raw,
            "inverted": inverted,
            "en": en,
            "native_script": native_script,
            "en_script": N.detect_script(en),
            "dob_year": (r.get("dob") or "")[:4].lstrip("-") or None,
            "label_language": r["native_lang"],
            "language": language,
            "language_basis": basis,
            "parts": parts,
        })
    return sorted(out, key=lambda r: r["qid"])


# --------------------------------------------------------------------------------------
# record construction
# --------------------------------------------------------------------------------------

def make_record(
    pair_id: str,
    name_a: str,
    name_b: str,
    language: str,
    entity_type: str,
    same_entity: bool,
    source: str,
    tags: list[str],
    notes: str,
    hard_negative: bool = False,
    extra_tags: tuple[str, ...] = (),
) -> dict:
    tag_set = sorted(set(tags) | set(extra_tags))
    return {
        "id": pair_id,
        "name_a": name_a,
        "name_b": name_b,
        "script_a": N.detect_script(name_a),
        "script_b": N.detect_script(name_b),
        "language": language,
        "entity_type": entity_type,
        "same_entity": same_entity,
        "phenomena": tag_set,
        "difficulty": P.difficulty(same_entity, tag_set, hard_negative),
        "source": source,
        "notes": notes,
    }


def evidence_note(align: dict) -> str:
    """Human-readable alignment evidence, so any tag can be audited from the record."""
    bits = []
    for p in align["pairs"]:
        systems = ("=" + "|".join(p["systems"])) if p["systems"] else ""
        bits.append(f"{p['cyr']}→{p['lat']}[{p['tier']}{systems}]")
    if align["cyr_unmatched"]:
        bits.append("cyr-unmatched:" + ",".join(align["cyr_unmatched"]))
    if align["lat_unmatched"]:
        bits.append("lat-unmatched:" + ",".join(align["lat_unmatched"]))
    return "; ".join(bits)


# --------------------------------------------------------------------------------------
# positives — OFAC
# --------------------------------------------------------------------------------------

def ofac_positives(rows: list[dict], rng: random.Random) -> tuple[list[dict], list[dict]]:
    """Cross-script and cross-romanisation positives from SDN alias sets."""
    cross_script: list[dict] = []
    cross_roman: list[dict] = []

    for rec in rows:
        cyr = [v for v in rec["variants"] if v["script"] == "Cyrl"]
        lat = [v for v in rec["variants"] if v["script"] == "Latn"]
        if not cyr or not lat:
            continue
        ref = rec["ofac_fixed_ref"]
        lang = rec["language"]
        etype = rec["entity_type"]

        # Cross-script: each Cyrillic form against a Latin form.
        made = 0
        for c in cyr:
            for l in lat:
                if made >= MAX_PAIRS_PER_ENTITY:
                    break
                tags, align = P.tag_cross_script(c["text"], l["text"], lang)
                cross_script.append(make_record(
                    pair_id="", name_a=c["text"], name_b=l["text"], language=lang,
                    entity_type=etype, same_entity=True,
                    source=f"ofac-sdn:{ref}#identity{rec['identity_id']}",
                    tags=tags,
                    notes=f"OFAC alias set; language inferred {rec['language_basis']}; "
                          f"alignment: {evidence_note(align)}",
                ))
                made += 1
            if made >= MAX_PAIRS_PER_ENTITY:
                break

        # Cross-romanisation: two Latin forms of one entity, produced by different systems.
        if len(lat) >= 2:
            uniq = sorted({v["text"] for v in lat})
            made = 0
            for i in range(len(uniq)):
                for j in range(i + 1, len(uniq)):
                    if made >= MAX_PAIRS_PER_ENTITY:
                        break
                    a, b = uniq[i], uniq[j]
                    if a.lower() == b.lower():
                        continue
                    cross_roman.append(make_record(
                        pair_id="", name_a=a, name_b=b, language=lang,
                        entity_type=etype, same_entity=True,
                        source=f"ofac-sdn:{ref}#identity{rec['identity_id']}",
                        tags=P.tag_same_script(a, b, lang),
                        notes="OFAC alias set; two Latin forms of one entity, "
                              "romanisation systems not recoverable without the "
                              "Cyrillic original",
                    ))
                    made += 1
                if made >= MAX_PAIRS_PER_ENTITY:
                    break

    rng.shuffle(cross_script)
    rng.shuffle(cross_roman)
    return cross_script, cross_roman


# --------------------------------------------------------------------------------------
# positives — Wikidata
# --------------------------------------------------------------------------------------

def wikidata_positives(rows: list[dict], rng: random.Random) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        if r["native_script"] != "Cyrl" or r["en_script"] != "Latn":
            continue
        lang = r["language"]

        # Roughly half of the inverted labels are kept inverted, so `order:swapped` is
        # tested with *real* surname-first data rather than a synthesised swap. The split
        # is by a hash of the QID, so it is stable across rebuilds.
        keep_inverted = r["inverted"] and int(
            hashlib.sha256(r["qid"].encode()).hexdigest(), 16
        ) % 2 == 0
        name_a = r["native_raw"] if keep_inverted else r["native"]

        tags, align = P.tag_cross_script(name_a, r["en"], lang)
        extra = ("order:swapped",) if keep_inverted else ()
        out.append(make_record(
            pair_id="", name_a=name_a, name_b=r["en"], language=lang,
            entity_type=r["entity_type"], same_entity=True,
            source=f"wikidata:{r['qid']}", tags=tags, extra_tags=extra,
            notes=("label stored surname-first; kept as stored" if keep_inverted
                   else "label normalised to given-name-first")
                  + f"; language from {r['language_basis']}"
                  + f"; alignment: {evidence_note(align)}",
        ))

    # Stratify by language before returning. An unstratified shuffle reflects the source
    # distribution, which is overwhelmingly Russian orthography, and left `ky` with six
    # pairs — too few for the per-phenomenon breakdown that is this benchmark's main
    # output to say anything about Kyrgyz. Round-robin over languages instead, so the
    # minority orthographies are represented in proportion to what the corpus needs
    # rather than to what Wikidata happens to hold.
    rng.shuffle(out)
    by_lang: dict[str, list[dict]] = collections.defaultdict(list)
    for rec in out:
        by_lang[rec["language"]].append(rec)

    stratified: list[dict] = []
    langs = sorted(by_lang)
    cursor = {lang: 0 for lang in langs}
    while any(cursor[lang] < len(by_lang[lang]) for lang in langs):
        for lang in langs:
            if cursor[lang] < len(by_lang[lang]):
                stratified.append(by_lang[lang][cursor[lang]])
                cursor[lang] += 1
    return stratified


# --------------------------------------------------------------------------------------
# positives — synthetic
# --------------------------------------------------------------------------------------

# (system, the phenomenon tag it demonstrates, languages it applies to)
# (system, phenomenon tag it demonstrates, languages, pairs to draw)
# Kazakh and Kyrgyz are sampled harder than their share of the source data: the Kazakh
# multi-alphabet problem is the flagship case for this thesis (`docs/domain-notes.md` §3),
# and a taxonomy with seven Kazakh pairs in it cannot support or refute a claim about it.
SYNTHETIC_PLAN = (
    ("iso9", "romanisation:iso9", ("ru", "uk", "be"), 24),
    ("gost-b", "romanisation:gost-b", ("ru",), 24),
    ("icao", "romanisation:icao", ("ru", "uk"), 24),
    ("ala-lc", "romanisation:ala-lc", ("ru",), 24),
    ("scholarly", "romanisation:scholarly", ("ru",), 24),
    ("bgn", "romanisation:bgn", ("ru",), 24),
    ("uk-kmu55", "romanisation:uk-kmu55", ("uk",), 32),
    ("uk-bgn", "romanisation:bgn", ("uk",), 24),
    ("kk-latin2021", "kazakh:cyrillic-latin", ("kk",), 60),
    ("kk-ru-mediated", "kazakh:cyrillic-latin", ("kk",), 60),
    ("ky-bgn", "romanisation:bgn", ("ky",), 45),
    ("ky-ru-mediated", "romanisation:ru-mediated", ("ky",), 45),
    ("tg-bgn", "romanisation:bgn", ("tg",), 40),
    ("be-bgn", "romanisation:be-bgn", ("be",), 24),
    ("be-latin-ascii", "romanisation:be-latin-ascii", ("be",), 24),
)

# Draws for the structural transformations, per language. Kazakh, Kyrgyz and Uzbek are
# drawn harder than their share of the source pool: the Turkic patronymic and
# multi-alphabet cases are the ones this thesis is about, and Wikidata simply holds fewer
# of those entities (`ky` tops out near 489 rows however high the query limit goes).
STRUCTURAL_DRAWS = {"ru": 40, "uk": 36, "kk": 60, "ky": 30, "be": 24, "tg": 20}
UZ_MODIFIER_DRAWS = 40
UZ_PLAIN_DRAWS = 70
TURKIC_PATRONYMIC_DRAWS = 90


def synthetic_positives(rows: list[dict], rng: random.Random, want: int) -> list[dict]:
    """Rule-generated positives with a known ground-truth transformation.

    Capped at ≤30% of positives (`benchmark/README.md`): synthetic pairs only test
    transformations already modelled, so a corpus dominated by them measures our own
    assumptions back at us. They are here for the coverage nothing else provides —
    the rare-letter romanisations, and Uzbek Cyrillic, which Wikidata does not carry.
    """
    # Grouped by *orthography-derived* language, so a Kazakh synthetic pair is built from
    # a name actually written in Kazakh orthography rather than from a Russian name that
    # happened to sit in the `kk` label field.
    by_lang: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        if r["native_script"] == "Cyrl" and r["entity_type"] == "person":
            by_lang[r["language"]].append(r)

    out: list[dict] = []

    # 1. Romanisation-standard coverage.
    for system, tag, langs, draw in SYNTHETIC_PLAN:
        for lang in langs:
            pool = sorted(by_lang.get(lang, []), key=lambda r: r["qid"])
            if not pool:
                continue
            for r in rng.sample(pool, min(draw, len(pool))):
                latin = T.romanise(r["native"], system)
                if latin == r["native"]:
                    continue
                out.append(make_record(
                    pair_id="", name_a=r["native"], name_b=latin, language=lang,
                    entity_type="person", same_entity=True,
                    source=f"synthetic:{system}+wikidata:{r['qid']}",
                    tags=[tag], extra_tags=("synthetic",),
                    notes=f"rule-generated: {system} applied to the Wikidata "
                          f"{lang} label; ground-truth transformation known",
                ))

    # 2. Uzbek Cyrillic, which has to be generated — see module docstring.
    uz_latin = sorted(
        (r for r in rows if r["native_lang"] == "uz" and r["native_script"] == "Latn"
         and r["entity_type"] == "person"),
        key=lambda r: r["qid"],
    )
    # The apostrophe-variant phenomenon only exists for names that actually contain the
    # modifier letter, so those are taken first and each is emitted in all three
    # codepoint forms; names without it contribute plain Cyrillic↔Latin coverage.
    uz_with_modifier = [r for r in uz_latin
                        if any(c in r["native"] for c in ("ʻ", "‘", "'"))]
    uz_plain = [r for r in uz_latin if r not in uz_with_modifier]

    for r in uz_with_modifier[:UZ_MODIFIER_DRAWS]:
        cyr = T.uzbek_latin_to_cyrillic(r["native"])
        for variant, vtag in zip(T.uzbek_apostrophe_variants(r["native"]),
                                 ("U+02BB", "U+2018", "ASCII-apostrophe")):
            out.append(make_record(
                pair_id="", name_a=cyr, name_b=variant, language="uz",
                entity_type="person", same_entity=True,
                source=f"synthetic:uz-cyrillic-inverse+wikidata:{r['qid']}",
                tags=["uzbek:apostrophe", "romanisation:uz-latin1995"],
                extra_tags=("synthetic",),
                notes=f"Uzbek Cyrillic generated by inverting the 1995 Latin mapping; "
                      f"Latin side writes the modifier letter as {vtag}",
            ))

    for r in rng.sample(uz_plain, min(UZ_PLAIN_DRAWS, len(uz_plain))):
        cyr = T.uzbek_latin_to_cyrillic(r["native"])
        if cyr == r["native"]:
            continue
        out.append(make_record(
            pair_id="", name_a=cyr, name_b=r["native"], language="uz",
            entity_type="person", same_entity=True,
            source=f"synthetic:uz-cyrillic-inverse+wikidata:{r['qid']}",
            tags=["romanisation:uz-latin1995"], extra_tags=("synthetic",),
            notes="Uzbek Cyrillic generated by inverting the 1995 Latin mapping",
        ))

    # 3. Structural transformations on real Cyrillic names.
    for lang, draw in STRUCTURAL_DRAWS.items():
        pool = sorted(by_lang.get(lang, []), key=lambda r: r["qid"])
        pool = [r for r in pool if len(N.tokens(r["native"])) >= 3]
        if not pool:
            continue
        for r in rng.sample(pool, min(draw, len(pool))):
            toks = N.tokens(r["native"])
            base_system = {"ru": "bgn", "uk": "uk-kmu55", "kk": "kk-ru-mediated",
                           "ky": "ky-bgn", "be": "be-bgn", "tg": "tg-bgn"}[lang]
            latin_toks = [T.romanise(t, base_system) for t in toks]

            # patronymic abbreviated to an initial
            pat = N.find_patronymic(r["native"])
            if pat:
                idx = pat[0]
                abbrev = list(latin_toks)
                abbrev[idx] = abbrev[idx][0] + "."
                out.append(make_record(
                    pair_id="", name_a=r["native"], name_b=" ".join(abbrev),
                    language=lang, entity_type="person", same_entity=True,
                    source=f"synthetic:patronymic-abbreviated+wikidata:{r['qid']}",
                    tags=["patronymic:abbreviated", f"patronymic:{pat[1]}"],
                    extra_tags=("synthetic",),
                    notes=f"{base_system} romanisation with the patronymic reduced "
                          f"to an initial",
                ))

            # diacritics stripped from a diacritic-bearing standard
            marked = T.romanise(r["native"],
                                "kk-latin2021" if lang == "kk" else "iso9")
            stripped = T.strip_diacritics(marked)
            if stripped != marked:
                out.append(make_record(
                    pair_id="", name_a=r["native"], name_b=stripped, language=lang,
                    entity_type="person", same_entity=True,
                    source=f"synthetic:diacritics-stripped+wikidata:{r['qid']}",
                    tags=["romanisation:diacritics-stripped"],
                    extra_tags=("synthetic",),
                    notes="diacritic-bearing standard degraded to ASCII, as a system "
                          "that cannot store combining marks would record it",
                ))

    # 4. Turkic patronymic particle against the Russified suffix. `docs/domain-notes.md`
    #    §3: the same Kazakh person appears as `Aidar Serikuly Nazarbayev` and
    #    `Aidar Serikovich Nazarbayev`. Only the suffix substitution is generated — the
    #    de-Russification of surnames (`Назарбаев`→`Назарбай`) is *not*, because the
    #    Russian suffix absorbs the stem's final consonant and reconstructing it is
    #    guesswork. `kazakh:derussified` therefore stays untested in this pilot rather
    #    than being tested with invented morphology.
    turkic_made = 0
    for lang in ("kk", "ky", "tg"):
        pool = sorted(by_lang.get(lang, []), key=lambda r: r["qid"])
        for r in pool:
            if turkic_made >= TURKIC_PATRONYMIC_DRAWS:
                break
            pat = N.find_patronymic(r["native"])
            if not pat or pat[1] != "russified":
                continue
            toks = N.tokens(r["native"])
            token = toks[pat[0]]
            stem = None
            for suffix, particle in (("ович", "ұлы"), ("евич", "ұлы"), ("ұлы", None),
                                     ("овна", "қызы"), ("евна", "қызы")):
                if particle and token.lower().endswith(suffix):
                    stem = token[: len(token) - len(suffix)]
                    replacement = stem + particle
                    break
            else:
                continue
            if not stem:
                continue
            turkic = " ".join(
                replacement if i == pat[0] else t for i, t in enumerate(toks)
            )
            latin = T.romanise(turkic, "kk-ru-mediated")
            out.append(make_record(
                pair_id="", name_a=r["native"], name_b=latin, language=lang,
                entity_type="person", same_entity=True,
                source=f"synthetic:turkic-patronymic+wikidata:{r['qid']}",
                tags=["patronymic:form-substituted", "patronymic:turkic",
                      "patronymic:russified", "romanisation:ru-mediated"],
                extra_tags=("synthetic",),
                notes=f"Russified patronymic '{token}' replaced with the Turkic particle "
                      f"form '{replacement}', then romanised; both forms circulate for "
                      f"one person (docs/domain-notes.md §3)",
            ))
            turkic_made += 1

    # Validation gate. A rule-generated Latin form containing Cyrillic is a table defect,
    # not a hard pair — it means some letter had no row and passed through. Such pairs are
    # dropped and counted rather than shipped, because a corpus that contains corrupt
    # synthetic data would make every baseline look worse for the wrong reason.
    clean: list[dict] = []
    rejected = 0
    for rec in out:
        if N.detect_script(rec["name_b"]) != "Latn":
            rejected += 1
            continue
        clean.append(rec)
    if rejected:
        print(f"  synthetic pairs rejected for non-Latin output: {rejected}",
              file=sys.stderr)

    rng.shuffle(clean)
    synthetic_rejects["count"] = rejected
    return clean[:want]


# Populated by `synthetic_positives`, reported in the manifest.
synthetic_rejects: dict[str, int] = {"count": 0}


# --------------------------------------------------------------------------------------
# negatives
# --------------------------------------------------------------------------------------

def surname_of(row: dict) -> str:
    """The surname, located by `names.split_name_parts` rather than by position.

    Taking the last token here was a real defect: labels stored `Surname Given
    Patronymic` without a comma returned the patronymic, which grouped unrelated people
    into the same-surname and patronymic-collision slices.
    """
    return row["parts"]["surname"] or ""


def distinct_entities(a: dict, b: dict) -> bool:
    """Are these certainly two different entities?

    Requires different QIDs *and* both dates of birth present and different, because
    Wikidata does contain duplicate items for one person and those share a DOB.
    """
    if a["qid"] == b["qid"]:
        return False
    if not a["dob_year"] or not b["dob_year"]:
        return False
    return a["dob_year"] != b["dob_year"]


def _neg(a: dict, b: dict, kind: str, tags: list[str], note: str,
         hard: bool = True) -> dict:
    return make_record(
        pair_id="", name_a=a["native"], name_b=b["en"],
        language=a["language"], entity_type=a["entity_type"], same_entity=False,
        source=f"wikidata:{a['qid']}|wikidata:{b['qid']}",
        tags=tags, extra_tags=(f"negative:{kind}",), hard_negative=hard,
        notes=f"{note}; distinct QIDs, DOB {a['dob_year']} vs {b['dob_year']}; "
              f"language from {a['language_basis']}",
    )


def latin_surname_matches(row: dict) -> bool:
    """Is the English label's surname actually a romanisation of the Cyrillic surname?

    Needed for the gendered-pair slice. The gendered relationship is established on the
    *Cyrillic* surnames, but the pair presented to a matcher uses the other entity's
    *English* label — and if that label uses an unrelated surname form
    (`Байрамова` recorded in English as `Bayramli`) the pair is still a valid negative
    but no longer demonstrates the gendered-pair phenomenon it is filed under.
    """
    cyr_surname = row["parts"]["surname"]
    if not cyr_surname:
        return False
    en_toks = N.tokens(row["en"])
    if not en_toks:
        return False
    candidates = {T.strip_diacritics(T.romanise(cyr_surname, s)).lower()
                  for s in T.SYSTEM_NAMES}
    return any(
        max(difflib.SequenceMatcher(None, c, T.strip_diacritics(t).lower()).ratio()
            for c in candidates) >= 0.80
        for t in en_toks
    )


def build_negatives(rows: list[dict], rng: random.Random) -> tuple[dict, int]:
    """All negative slices. Returns `(slices, n_identical_excluded)`."""
    people = [r for r in rows
              if r["entity_type"] == "person" and r["native_script"] == "Cyrl"
              and r["en_script"] == "Latn" and r["dob_year"]]
    people.sort(key=lambda r: r["qid"])

    identical_excluded = 0

    def usable(a: dict, b: dict) -> bool:
        nonlocal identical_excluded
        if not distinct_entities(a, b):
            return False
        if N.normalise_ws(a["en"]).lower() == N.normalise_ws(b["en"]).lower():
            identical_excluded += 1
            return False
        return True

    slices: dict[str, list[dict]] = {}

    # --- same surname, different given name -------------------------------------------
    by_surname: dict[str, list[dict]] = collections.defaultdict(list)
    for r in people:
        s = surname_of(r)
        if len(s) >= 4:
            by_surname[s].append(r)

    same_surname: list[dict] = []
    for surname in sorted(by_surname):
        group = sorted(by_surname[surname], key=lambda r: r["qid"])
        if len(group) < 2:
            continue
        made = 0
        for i in range(len(group) - 1):
            if made >= MAX_NEGATIVES_PER_GROUP:
                break
            a, b = group[i], group[i + 1]
            if not usable(a, b):
                continue
            if N.tokens(a["native"])[0].lower() == N.tokens(b["native"])[0].lower():
                continue
            same_surname.append(_neg(
                a, b, "same-surname", ["negative:similar-string"],
                f"same surname {surname}, different given name",
            ))
            made += 1
    rng.shuffle(same_surname)
    slices["same-surname"] = same_surname

    # --- gendered pair of unrelated people --------------------------------------------
    surname_index = {s: sorted(g, key=lambda r: r["qid"]) for s, g in by_surname.items()}
    gender_pairs: list[dict] = []
    for surname in sorted(surname_index):
        alt = N.feminine_of(surname) or N.masculine_of(surname)
        if not alt or alt not in surname_index:
            continue
        made = 0
        used_partners: set[str] = set()
        for a in surname_index[surname]:
            if made >= MAX_NEGATIVES_PER_GROUP:
                break
            partner = next((b for b in surname_index[alt]
                            if b["qid"] not in used_partners
                            and usable(a, b) and latin_surname_matches(b)), None)
            if partner is None:
                continue
            used_partners.add(partner["qid"])
            gender_pairs.append(_neg(
                a, partner, "gender-pair", ["gender:feminine-form"],
                f"gendered surname pair {surname}/{alt}, unrelated people",
            ))
            made += 1
    rng.shuffle(gender_pairs)
    slices["gender-pair"] = gender_pairs

    # --- romanisation collision -------------------------------------------------------
    # Built at the **surname** level, not the full name. Two reasons:
    #
    # 1. Full-name collisions are vanishingly rare — 4 in a pool of 8,334.
    # 2. Where they do occur they are the *least* trustworthy labels in the corpus:
    #    `Айгуль Жапарова` and `Айгүл Жапарова` under two QIDs are as likely to be one
    #    person with a duplicate Wikidata item as two people, and
    #    `benchmark/README.md` says to exclude a pair rather than guess its label.
    #
    # Surname collisions are plentiful (`Әбиев`/`Абиев` both romanise to `abiev`) and the
    # label is safe whenever the given names differ. The pair then tests exactly the
    # failure this product is about: an identical romanised surname on two different
    # people, where the Cyrillic distinguishes them by a Kazakh letter that a
    # Russian-mediated romanisation destroys.
    surname_collapse: dict[str, dict[str, list[dict]]] = collections.defaultdict(
        lambda: collections.defaultdict(list))
    for r in people:
        s = surname_of(r)
        if len(s) >= 4:
            surname_collapse[T.collapse(s)][s].append(r)

    collisions: list[dict] = []
    for key in sorted(surname_collapse):
        spellings = sorted(surname_collapse[key])
        if len(spellings) < 2:
            continue
        made = 0
        for i in range(len(spellings)):
            if made >= MAX_NEGATIVES_PER_GROUP:
                break
            for j in range(i + 1, len(spellings)):
                if made >= MAX_NEGATIVES_PER_GROUP:
                    break
                group_a = sorted(surname_collapse[key][spellings[i]],
                                 key=lambda r: r["qid"])
                group_b = sorted(surname_collapse[key][spellings[j]],
                                 key=lambda r: r["qid"])
                for a in group_a:
                    if made >= MAX_NEGATIVES_PER_GROUP:
                        break
                    for b in group_b:
                        if not usable(a, b):
                            continue
                        ga = N.tokens(a["native"])[0].lower()
                        gb = N.tokens(b["native"])[0].lower()
                        if ga == gb or T.collapse(ga) == T.collapse(gb):
                            continue  # same given name too: distinctness less certain
                        collisions.append(_neg(
                            a, b, "romanisation-collision", ["negative:similar-string"],
                            f"surnames {spellings[i]} and {spellings[j]} both romanise "
                            f"to '{key}' under Russian-mediated romanisation; different "
                            f"given names",
                        ))
                        made += 1
                        break
    rng.shuffle(collisions)
    slices["romanisation-collision"] = collisions

    # --- shared surname and patronymic ------------------------------------------------
    # Keyed on the surname located structurally plus the patronymic token. Both must be
    # present and shared, and the given names must differ — otherwise the pair is not a
    # collision, it is two unrelated people who happen to share a patronymic suffix.
    by_sur_pat: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for r in people:
        surname = r["parts"]["surname"]
        patronymic = r["parts"]["patronymic"]
        given = r["parts"]["given"]
        if not (surname and patronymic and given):
            continue
        by_sur_pat[(surname.lower(), patronymic.lower())].append(r)

    pat_collisions: list[dict] = []
    for key in sorted(by_sur_pat):
        group = sorted(by_sur_pat[key], key=lambda r: r["qid"])
        if len(group) < 2:
            continue
        made = 0
        for i in range(len(group)):
            if made >= MAX_NEGATIVES_PER_GROUP:
                break
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if not usable(a, b):
                    continue
                if (a["parts"]["given"] or "").lower() == \
                        (b["parts"]["given"] or "").lower():
                    continue
                if not latin_surname_matches(b):
                    continue
                pat_collisions.append(_neg(
                    a, b, "patronymic-collision", ["patronymic:russified"],
                    f"shared surname '{key[0]}' and patronymic '{key[1]}', "
                    f"different given name",
                ))
                made += 1
                break
    rng.shuffle(pat_collisions)
    slices["patronymic-collision"] = pat_collisions

    # --- string-similar, unrelated ----------------------------------------------------
    # Compare the *romanised* Cyrillic against the other entity's English label, since
    # that is the comparison a screening system actually performs.
    #
    # Blocking is by sorted neighbourhood rather than a shared prefix: sorting brings
    # similar strings adjacent, and a second pass over the reversed strings catches names
    # that differ at the start and agree at the end (`Абдулов`/`Габдулов`). A shared
    # 3-character prefix, tried first, found only 8 candidates in the whole pool.
    romanised = {r["qid"]: T.strip_diacritics(
        T.romanise(r["native"], "bgn")).lower() for r in people}

    # Window and per-anchor cap are sized for yield: at window 12 taking one pair per
    # anchor this produced 279 candidates against a 14,088-entity pool, which was a
    # generator limit rather than a data limit.
    SIMILAR_WINDOW = 25
    SIMILAR_PER_ANCHOR = 2

    similar: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    for reverse in (False, True):
        ordered = sorted(
            people,
            key=lambda r: (romanised[r["qid"]][::-1] if reverse else romanised[r["qid"]]),
        )
        for i in range(len(ordered)):
            made = 0
            for j in range(i + 1, min(i + SIMILAR_WINDOW, len(ordered))):
                if made >= SIMILAR_PER_ANCHOR:
                    break
                a, b = ordered[i], ordered[j]
                key = tuple(sorted((a["qid"], b["qid"])))
                if key in seen_pairs or not usable(a, b):
                    continue
                ratio = difflib.SequenceMatcher(
                    None, romanised[a["qid"]], N.normalise_ws(b["en"]).lower()
                ).ratio()
                if 0.82 <= ratio < 0.99:
                    seen_pairs.add(key)
                    similar.append(_neg(
                        a, b, "similar-string", ["negative:similar-string"],
                        f"unrelated entities, romanised similarity {ratio:.3f}",
                    ))
                    made += 1
    rng.shuffle(similar)
    slices["similar-string"] = similar

    # --- easy negatives ---------------------------------------------------------------
    easy: list[dict] = []
    pool = list(people)
    rng.shuffle(pool)
    for i in range(0, len(pool) - 1, 2):
        a, b = pool[i], pool[i + 1]
        if not usable(a, b):
            continue
        ratio = difflib.SequenceMatcher(
            None, romanised[a["qid"]], N.normalise_ws(b["en"]).lower()
        ).ratio()
        if ratio >= 0.6:
            continue
        easy.append(_neg(a, b, "easy", [], f"unrelated, romanised similarity "
                                           f"{ratio:.3f}", hard=False))
    slices["easy"] = easy

    return slices, identical_excluded


# --------------------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------------------

def take(pool: list[dict], want: int, label: str, shortfalls: dict) -> list[dict]:
    if len(pool) < want:
        shortfalls[label] = {"wanted": want, "available": len(pool)}
    return pool[:want]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(PAIRS / f"{DATASET_VERSION}.jsonl"))
    args = ap.parse_args()

    rng = random.Random(SEED)

    wd_path = newest("wikidata-snapshot-*.jsonl")
    ofac_path = newest("ofac-sdn-extract-*.jsonl")
    wd_rows = clean_wikidata(load_jsonl(wd_path))
    ofac_rows = load_jsonl(ofac_path)

    print(f"  wikidata usable rows: {len(wd_rows)}", file=sys.stderr)
    print(f"  ofac identities:      {len(ofac_rows)}", file=sys.stderr)

    shortfalls: dict = {}
    selected: list[dict] = []

    of_cross, of_roman = ofac_positives(ofac_rows, rng)
    selected += take(of_cross, TARGETS["positive"]["ofac-cross-script"],
                     "ofac-cross-script", shortfalls)
    selected += take(of_roman, TARGETS["positive"]["ofac-cross-romanisation"],
                     "ofac-cross-romanisation", shortfalls)

    wd_pos = wikidata_positives(wd_rows, rng)
    selected += take(wd_pos, TARGETS["positive"]["wikidata-cross-script"],
                     "wikidata-cross-script", shortfalls)

    syn = synthetic_positives(wd_rows, rng, TARGETS["positive"]["synthetic"])
    selected += take(syn, TARGETS["positive"]["synthetic"], "synthetic", shortfalls)

    neg_slices, identical_excluded = build_negatives(wd_rows, rng)
    for kind, want in TARGETS["negative"].items():
        selected += take(neg_slices.get(kind, []), want, f"negative-{kind}", shortfalls)

    # Stable ids: sort by a content hash so ordering does not depend on build sequence.
    selected.sort(key=lambda r: hashlib.sha256(
        f"{r['name_a']}|{r['name_b']}|{r['source']}".encode()
    ).hexdigest())

    # De-duplicate on the name pair itself. Two generators can legitimately produce the
    # same strings — a rule-generated romanisation that happens to reproduce the real
    # Wikidata label exactly, or one negative found by both the same-surname and
    # similar-string passes. Keeping both would silently double-weight those pairs in every
    # metric and split them across two source slices in the breakdown.
    #
    # Sorted order above makes the survivor deterministic. Labels were checked for
    # contradiction before this was added: of 25 duplicated keys, zero disagreed on
    # `same_entity`, so this removes redundancy and not a labelling conflict.
    seen_pairs: dict[tuple[str, str], dict] = {}
    duplicates: list[dict] = []
    for rec in selected:
        key = (rec["name_a"], rec["name_b"])
        if key in seen_pairs:
            duplicates.append({"name_a": rec["name_a"], "name_b": rec["name_b"],
                               "dropped_source": rec["source"],
                               "kept_source": seen_pairs[key]["source"],
                               "same_entity": rec["same_entity"],
                               "label_agreed": rec["same_entity"]
                               == seen_pairs[key]["same_entity"]})
            continue
        seen_pairs[key] = rec
    selected = list(seen_pairs.values())
    for i, rec in enumerate(selected, start=1):
        prefix = "pos" if rec["same_entity"] else "neg"
        rec["id"] = f"{DATASET_VERSION}-{prefix}-{i:04d}"

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in selected:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

    # ---------------------------------------------------------------------------------
    # manifest — composition measured from the written corpus, never asserted
    # ---------------------------------------------------------------------------------
    positives = [r for r in selected if r["same_entity"]]
    negatives = [r for r in selected if not r["same_entity"]]
    n_synth = sum(1 for r in positives if "synthetic" in r["phenomena"])
    n_hard_neg = sum(1 for r in negatives if r["difficulty"] == "hard")

    phen = collections.Counter(t for r in selected for t in r["phenomena"])
    manifest = {
        "dataset_version": DATASET_VERSION,
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": SEED,
        "scope": "PILOT — 300-500 pairs for a same-day P0 signal, not the >=5,000 "
                 "corpus in benchmark/README.md",
        "sources": {
            "wikidata": wd_path.name,
            "ofac": ofac_path.name,
        },
        "counts": {
            "total": len(selected),
            "positive": len(positives),
            "negative": len(negatives),
            "hard_negative": n_hard_neg,
            "easy_negative": len(negatives) - n_hard_neg,
            "synthetic_positive": n_synth,
        },
        "composition_targets": {
            "synthetic_share_of_positives": {
                "target": "<= 0.30",
                "actual": round(n_synth / len(positives), 4) if positives else None,
                "met": (n_synth / len(positives) <= 0.30) if positives else None,
            },
            "hard_share_of_negatives": {
                "target": ">= 0.60",
                "actual": round(n_hard_neg / len(negatives), 4) if negatives else None,
                "met": (n_hard_neg / len(negatives) >= 0.60) if negatives else None,
            },
        },
        "by_language": dict(sorted(collections.Counter(
            r["language"] for r in selected).items())),
        "by_entity_type": dict(sorted(collections.Counter(
            r["entity_type"] for r in selected).items())),
        "by_difficulty": dict(sorted(collections.Counter(
            r["difficulty"] for r in selected).items())),
        "by_script_pair": dict(sorted(collections.Counter(
            f"{r['script_a']}->{r['script_b']}" for r in selected).items())),
        "by_source_prefix": dict(sorted(collections.Counter(
            r["source"].split(":")[0] for r in selected).items())),
        "phenomena_counts": dict(sorted(phen.items())),
        "required_languages_present": {
            lang: lang in {r["language"] for r in selected} for lang in REQUIRED_LANGUAGES
        },
        "shortfalls_against_target": shortfalls,
        "excluded": {
            "duplicate_name_pairs_removed": len(duplicates),
            "duplicate_labels_that_disagreed": sum(
                1 for d in duplicates if not d["label_agreed"]),
            "duplicate_examples": duplicates[:5],
            "synthetic_pairs_with_non_latin_output": synthetic_rejects["count"],
            "negatives_with_identical_normalised_names": identical_excluded,
            "reason": "correctly labelled as different entities (differing DOB) but "
                      "unresolvable from names alone; including them would add a fixed "
                      "error floor to every baseline that says nothing about the "
                      "transliteration gap",
        },
        "sha256_of_corpus": hashlib.sha256(out_path.read_bytes()).hexdigest(),
    }
    (out_path.parent / f"{DATASET_VERSION}.manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"wrote {out_path} ({len(selected)} pairs: {len(positives)}+/{len(negatives)}-)",
          file=sys.stderr)
    if shortfalls:
        print(f"  SHORTFALLS: {json.dumps(shortfalls)}", file=sys.stderr)


if __name__ == "__main__":
    main()
