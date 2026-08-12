# Domain notes — why Cyrillic name matching is hard

The technical case for the company. If this document is wrong, the company is wrong.

Linguistic facts here are stable and checkable. Regulatory facts decay — those carry
`[VERIFY]` and a date. See `CLAUDE.md` §3.

---

## 1. The core insight

Fuzzy string matching assumes **edit distance correlates with the probability of being a
different entity**. For cross-script names, it does not.

- `Shcherbakov` vs `Scherbakov` — edit distance 1, **same person**, two romanisation
  systems.
- `Ivanov` vs `Ivanova` — edit distance 1, usually **different people** (gendered forms
  of a surname shared by millions).
- `Aleksandr` vs `Oleksandr` — edit distance 1, Russian vs Ukrainian form of the same
  given name; could be the same person or not, and post-2022 the distinction is
  politically loaded and appears inconsistently in records.

A matcher tuned on English names learns a distance threshold. On Cyrillic-derived names
that threshold is meaningless, because legitimate transliteration variance and genuine
identity difference live at the same edit distance. **You cannot fix this by tuning the
threshold. You have to model the transformation.**

That is the whole product.

> **Measured twice, and the paragraph above does not survive it.**
>
> The 460-pair pilot (2026-07-26) found the *romanisation* half already commoditised, and
> located the gap in name structure instead. The full 5,102-pair corpus (2026-08-10)
> refined that — Russian romanisation is handled, Ukrainian (0.460) and Belarusian (0.414)
> are not — and then closed the question entirely: **a frontier LLM judge solves all of it**,
> structure included, scoring 0.9859 max-F1 and 0.9775 recall @ 1% FPR against 0.8523 /
> 0.5853 for the best dedicated open-source matcher. `patronymic:turkic` goes from 0.153 to
> 0.992; Ukrainian romanisation from 0.460 to 1.000.
>
> So "you have to model the transformation" is **false as a business claim**. You have to
> *know* the transformation, and a general-purpose model already does — with a two-sentence
> prompt and no transliteration tables. The linguistics in this document remain correct and
> useful; what they no longer support is a defensible product built on possessing them.
> This is why the pre-registered gate returned KILL
> ([`../benchmark/README.md`](../benchmark/README.md#the-pre-registered-gate)).

## 2. Romanisation: there is no standard, there are eight

Watchlists (OFAC SDN, EU consolidated, UK OFSI) are published predominantly in Latin
script. Source records — a KZ customer file, a Russian bill of lading, a Cyrillic invoice
— are not. So the common operation is **cross-script**, and the Latin side was produced
by one of several mutually incompatible systems.

Russian, principal divergences:

| Cyrillic | ISO 9 | GOST 7.79-B | BGN/PCGN | ICAO 9303 | Scholarly | Ad-hoc |
|---|---|---|---|---|---|---|
| `щ` | ŝ | shh | shch | shch | šč | sch / sh |
| `я` | â | ya | ya | ia | ja | ya |
| `ю` | û | yu | yu | iu | ju | yu |
| `ж` | ž | zh | zh | zh | ž | j / zh |
| `х` | h | x | kh | kh | ch | h / kh |
| `ц` | c | cz / c | ts | ts | c | ts / c |
| `ё` | ë | yo | ë | e | ë | e / yo |
| `ы` | y | y' | y | y | y | i / y |
| `й` | j | j | y | i | j | y / i |
| `ъ` `ь` | ʺ ʹ | \`\` \` | ʺ ʹ | ie / — | ʺ ʹ | omitted |

**ICAO 9303 matters disproportionately.** It is the passport machine-readable-zone
standard, so it is what appears in KYC records copied from identity documents — and it
diverges from BGN/PCGN precisely on the high-frequency letters `я` and `ю`.

`Александр Щербаков` legitimately appears as *Aleksandr Shcherbakov*, *Alexander
Scherbakov*, *Aleksandr Shherbakov*, *Aleksandr Ščerbakov*, *Alexandr Shcherbakoff* — all
the same person, none of them wrong.

**Ukrainian uses a different official system** (Cabinet of Ministers Resolution No. 55,
2010): `г`→h (not g), `и`→y, `й`→i, `я`→ia. So Russian `Гончаров` → *Goncharov* but
Ukrainian `Гончаров` → *Honcharov*. Same letters, different first character in Latin.

## 3. Kazakh: three alphabets at once

Kazakh Cyrillic has 42 letters, including `ә ғ қ ң ө ұ ү һ і` — which have no clean
Russian-Cyrillic or Latin equivalent, so they get mangled differently by every system.

Kazakhstan has been transitioning to a Latin alphabet, with several officially approved
versions superseding one another — a 2017 digraph/apostrophe version, a 2018
acute-accent version, and a 2021 revision using diacritics. Rollout has been repeatedly
postponed. `[VERIFY as of 2026-07]` — confirm the current official alphabet and rollout
status before any customer-facing claim.

The practical consequence is what matters and is not in dispute: **a Kazakh name can
exist in Cyrillic, in two or three competing Latin orthographies, and in a
Russian-mediated romanisation, simultaneously, in live records.**

- `Нұрсұлтан` → *Nursultan* / *Nūrsultan* / *Nursūltan* / *Nursultan*
- `Шымкент` → *Shymkent* / *Şymkent* / *Chimkent* (Russian-mediated, Soviet-era records)

**Kazakh patronymics** add a second axis. Turkic particles `-ұлы` / `-uly` ("son of") and
`-қызы` / `-kyzy` ("daughter of") coexist with Russified `-ович` / `-овна`. The same
person appears as:

- *Aidar Serikuly Nazarbayev*
- *Aidar Serikovich Nazarbayev*
- *Nazarbayev Aidar Serikuly* (surname-first, official KZ document order)
- *Nazarbayev A.S.*

And there is an active de-Russification practice: `Назарбаев` → `Назарбай`, dropping the
Russian `-ов`. Both forms circulate.

## 4. Patronymics, gender, and name order

- **Patronymics appear, vanish, and abbreviate.** Russian and Kazakh official records
  carry three parts; Western records usually drop the patronymic entirely; internal
  systems often abbreviate to an initial. A matcher that treats a missing patronymic as
  evidence of difference will miss true hits; one that ignores it entirely throws away
  the strongest available discriminator between two people with the same name.
- **Surnames are gendered.** `Иванов`/`Иванова`, `Петровский`/`Петровская`,
  `Ким` (indeclinable, no gender marking). The gendered pair is *not* a spelling variant
  — it is usually two different people from the same family. But a woman's name recorded
  in a system that stripped the feminine ending is the same person. Both cases are common
  and they pull in opposite directions.
- **Name order is unstable.** Official CIS document order is surname-first; Western
  systems assume given-first. Cross-border records mix them with no marker.

## 5. The rest of the corridor

| Language | Script situation | The specific trap |
|---|---|---|
| Uzbek | Latin since the 1990s, Cyrillic still in wide use | Latin uses `oʻ` and `gʻ` — and the modifier letter is written variously as U+02BB, U+2018, or a plain ASCII apostrophe. Three byte sequences, one letter. |
| Kyrgyz | Cyrillic | Additional letters `ң ө ү`; heavy Russian-mediated romanisation |
| Tajik | Cyrillic, but a Persian language | Persian names in Cyrillic, then romanised — two lossy hops |
| Azerbaijani | Latin since 1991, Cyrillic legacy, Arabic script in Iran | Three-script identity space; `ə` frequently degraded to `a` or `e` |
| Armenian | Own script | Eastern vs Western Armenian romanisation differ substantially (`Յ` and consonant voicing) |
| Georgian | Own script | National vs ISO 9984 romanisation; aspirated consonant marking |
| Belarusian | Cyrillic + Łacinka | Russian vs Belarusian forms of the same name |
| Turkmen | Latin since the 1990s | Unusual letter set (`ä ň ö ş ü ý ž`) routinely stripped to ASCII |

## 6. Non-person entities

Screening is not only people.

- **Companies.** Legal-form abbreviations are a matching problem in themselves:
  `ООО` / `OOO` / `LLC` / `Ltd`, `АО` / `AO` / `JSC`, `ЗАО` / `CJSC`, `ПАО` / `PJSC`,
  and Kazakhstan-specific `ТОО` / `TOO` / `LLP`. A matcher must know these are
  form-equivalent, and must not let the form token dominate the similarity score.
- **Vessels.** Sanctions work leans heavily on shipping. IMO number is the stable key;
  names change and flags hop. Name matching alone is insufficient and mildly dangerous
  as a signal.
- **Addresses.** Cyrillic addresses carry abbreviations (`ул.`/`улица`, `д.`/`дом`,
  `кв.`), reversed element order relative to Western convention, and Soviet-era vs
  current place names for the same location (`Целиноград`/`Акмола`/`Астана`/`Нур-Султан`/
  `Астана` — one city, five official names across its history). `[VERIFY]` the current
  name before use in any example; it has changed twice recently.

## 7. Why off-the-shelf tooling fails, specifically

- **Soundex and Metaphone encode English phonology.** They collapse distinctions that
  matter in Slavic and Turkic names and preserve ones that don't. Any library defaulting
  to them for this data is mis-applied, not merely suboptimal.
- **Single-pass ICU transliteration picks one system** and thereby guarantees a mismatch
  against records produced with a different one.
- **Multilingual embeddings** are trained on semantic similarity of text, not identity of
  names. They cluster names by language and morphology rather than by referent — and they
  are not deterministic across model versions, which disqualifies them as the sole scorer
  in an audited pipeline (see `CLAUDE.md` §4).
- **LLM-as-judge** does not merely work "surprisingly well" — measured against corpus
  `v1.0`, it **beats every other method by roughly 40 points of recall at 1% FPR and closes
  the entire error taxonomy in this document**. `claude-opus-5` scores 0.9859 max-F1 and
  0.9775 recall @ 1% FPR against 0.8523 / 0.5853 for the best open-source matcher. This is
  the finding that returned KILL on the pre-registered gate
  ([`../benchmark/README.md`](../benchmark/README.md#the-pre-registered-gate)). It remains
  non-deterministic, unexplainable in the audit sense, expensive at screening volumes, and
  impossible to version-freeze for replay — but those are reasons it cannot be the *scorer
  of record*, not reasons the accuracy gap is smaller than measured.

  > **Measured 2026-08-10, and the replay objection is now concrete rather than
  > theoretical.** Two things surfaced while running this baseline against corpus `v1.0`:
  >
  > 1. **The current frontier models reject the `temperature` parameter outright** — it is
  >   deprecated for the Claude 5 family and returns HTTP 400. So the judge cannot be
  >   pinned to greedy decoding *even in principle*, let alone replayed. For a control an
  >   examiner may ask you to re-run on historical data, that is disqualifying on its own,
  >   independently of accuracy (`CLAUDE.md` §4).
  > 2. **Extended thinking is on by default and is billed as output.** A small
  >   `max_tokens` is consumed entirely by the thinking block, the response carries no
  >   text at all, and the answer is unrecoverable. That failure is **correlated with
  >   difficulty** — harder pairs think longer — so a tight token budget silently scores
  >   the hardest true pairs as non-matches and understates the baseline in whichever
  >   direction the experimenter happens to be hoping for. Ours had to be raised to 1,024
  >   before parse failures went to zero.
  >
  > The second point is a warning about benchmarking LLMs generally, not about this model:
  > a plausible-looking configuration produced a systematically biased result that looked
  > like a finding.

Each of these is a P0 benchmark baseline for exactly this reason: the claim "existing
tools fail on this data" must be *measured*, not asserted.

## 8. Why now — the demand side

`[VERIFY — all of §8, as of 2026-07. Sanctions facts decay weekly.]`

The structural driver is that since 2022, Kazakhstan and its neighbours became the
principal re-export and parallel-import corridor into Russia, and Western enforcement
pushed liability *onto institutions in those countries*. The mechanism that matters most:
secondary-sanctions authority allowing designation of **foreign financial institutions**
that facilitate Russia's military-industrial base (E.O. 14114, December 2023) — which
converts a diffuse policy concern into personal, existential risk for a Kazakh bank's
board, and makes them buy screening.

Related pressure worth confirming and dating before use: BIS Common High Priority List of
HS codes; EU "no re-export to Russia" contractual clause requirements; Kazakhstan's own
export/cargo tracking measures.

**What to verify before this appears in any deck:** current status of E.O. 14114 and
successor authorities; whether the enforcement posture toward Central Asian institutions
has intensified or relaxed; current EU package number and its re-export provisions.

The thesis does not depend on any single instrument staying in force. It depends on the
durable fact that a large volume of trade runs through Cyrillic-script jurisdictions
under compliance scrutiny — which outlives any particular sanctions programme.
