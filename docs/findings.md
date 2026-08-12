# Frontier language models close a cross-script name-matching gap that purpose-built matchers do not

**An open benchmark for Cyrillic and Central Asian names in sanctions screening, and what
measuring it settled.**

Corpus `v1.0` · 5,102 labelled pairs · 19 baselines ·
measured 2026-08-10 · corpus sha256 `bdbc4e8522b3a525…`

---

## Summary

Sanctions and denied-party watchlists are published predominantly in Latin script. A large
share of the counterparty records screened against them — Russian, Kazakh, Ukrainian,
Uzbek, Kyrgyz — are written in Cyrillic, and there is no single romanisation standard
mapping between the two. One Cyrillic surname has many legitimate Latin spellings, several
of them produced by mutually incompatible published standards.

This benchmark measures how well available methods handle that. The result:

1. **Purpose-built matchers leave a large, systematically-shaped gap.** The strongest
   freely-available specialist matcher recovers
   58.5% of true matches at a 1% false-positive rate
   on hard negatives. Its failures are not random — they concentrate in nameable
   linguistic phenomena, above all patronymic handling.
2. **A general-purpose language model closes that gap almost entirely.** Prompted with two
   sentences and given no transliteration tables, romanisation standards or name-structure
   parser, `claude-opus-5` recovers
   97.8% at the same operating point —
   **39 percentage points of recall** — and does so without a precision
   penalty.
3. **The gap was never a knowledge gap.** Every phenomenon the specialist matchers fail on
   is handled by the general model, including Turkic patronymic particles
   (`0.153` → `0.992`)
   and Ukrainian official romanisation
   (`0.460` → `1.000`).

This benchmark was built to test a commercial hypothesis: that cross-script name matching
needs Slavic and Turkic linguistic expertise that vendors lack, and that supplying it is a
defensible product. **The measurement refuted that hypothesis**, and the project it was
built for was stopped. The corpus, harness and every per-pair score are published so the
result can be checked and disputed.

## 1. Why this needed measuring

Fuzzy string matching assumes edit distance correlates with the probability of two names
denoting different entities. Across scripts it does not:

| Pair | Edit distance | Truth |
|---|---|---|
| `Shcherbakov` / `Scherbakov` | 1 | same person, two romanisation systems |
| `Ivanov` / `Ivanova` | 1 | usually different people — gendered forms of one surname |
| `Aleksandr` / `Oleksandr` | 1 | Russian and Ukrainian forms; records do not say which |

Legitimate spelling variance and genuine identity difference occupy the same edit
distance, so no threshold separates them. Layered on top: Kazakh exists simultaneously in
Cyrillic, in competing Latin orthographies and in a Russian-mediated romanisation that
collapses `ә ұ ө ғ қ ң` onto their nearest Russian letters; patronymics appear, vanish and
abbreviate; Turkic particles `-ұлы`/`-қызы` coexist with Russified `-ович`/`-овна`;
surnames are gendered, and a stripped feminine ending means *same person* while a gendered
pair usually means *two people*.

Despite being an operational problem for every institution screening CIS counterparties,
we found no public benchmark quantifying it.

## 2. The corpus

5,102 labelled pairs, each `(name_a, name_b, same_entity, language, phenomena,
difficulty, source)`.

| Property | Value |
|---|---|
| Total pairs | 5,102 |
| Positive / negative | 2,491 / 2,611 |
| Hard negatives | 1,911 (73% of negatives) |
| Synthetic positives | 745 (30% of positives, capped at 30%) |
| Persons / organisations | 4,404 / 698 |
| Cross-script / same-script | 4,500 / 550 |
| Languages | `ru` 2,926 · `uk` 694 · `be` 520 · `kk` 497 · `ky` 198 · `tg` 145 · `uz` 122 |

**Positives** come from three sources. OFAC SDN alias sets supply cross-script and
cross-romanisation variants curated by government analysts — the gold standard, since they
record how one entity's name is actually written across systems. Wikidata supplies
cross-script pairs that are aligned by construction (the `ru`/`kk`/`uk` and `en` labels of
one item denote one entity) under CC0. Published transliteration tables supply synthetic
pairs with a known ground-truth transformation, capped at 30% of positives because
rule-generated pairs only test transformations already modelled.

**Hard negatives are 73% of negatives**, and
they carry most of the benchmark's value: a corpus of easy negatives makes every matcher
look excellent. They are constructed as same-surname-different-given-name, gendered pairs
of unrelated people, shared surname *and* patronymic, high string similarity after
romanisation, and — sharpest — **romanisation collisions**, where two different Cyrillic
surnames collapse to one identical Latin form (`Әбиев` and `Абиев` both give `abiev`).

Three construction decisions shape the numbers and are stated so results can be read
correctly:

- **Entity distinctness is proven, not assumed.** Negatives require both dates of birth
  present and different. Distinct identifiers alone are insufficient because Wikidata
  contains duplicate items for one person, which share a date of birth.
- **Unresolvable negatives are excluded** — 127
  pairs whose two names are identical after normalisation. They are correctly labelled
  (differing DOB proves different entities) but no name matcher can resolve them from names
  alone, so they would add a fixed error floor telling us nothing about cross-script
  matching.
- **Romanisation attribution is conservative.** A standard is named only when it reproduces
  every token exactly; otherwise the pair is `ad-hoc`. Under-attribution is the safe
  direction of error for a benchmark whose taxonomy is its main output.

**An incidental finding about the reference data.** 236 of the
OFAC SDN list's own Cyrillic-declared name variants contain Latin homoglyphs — a Latin `i`
inside the Belarusian patronymic `Рыгоравiч`, a Latin `O` in `OOO`, a Latin `P` in
`ТPиБУн`. Visually identical, different codepoints, and enough to defeat script detection
silently. Measured on the list published 2026-07-24; these pairs are tagged
`corruption:mixed-script-homoglyph` rather than cleaned away.

## 3. Method

Every baseline is open source, a published algorithm, or a commercially available API — all
reproducibly runnable by a third party. **No commercial screening product was evaluated**
(see §9).

Metrics, all reported together because none is sufficient alone:

- **Recall at a fixed false-positive rate** (1% and 0.1%). The figure a compliance buyer
  cares about: FPR is their analyst labour cost, recall is their regulatory exposure.
- **FPR required to reach 95% recall** — the inverse question, and the one that tests
  whether a matcher can be operated at the recall a regulator expects.
- **max-F1**, oracle-tuned over a full threshold sweep. Deliberately the most flattering
  reading of every baseline.
- **ROC-AUC**, threshold-free, so ranking quality is visible independent of operating point.

Results are given on two slices: **hard-negatives-only** (easy negatives removed; a lower
bound on matcher quality) and **full**. Neither is a production false-positive estimate —
this corpus is roughly half positives and no real screening queue is.

**Read max-F1 against 0.7228, not zero.** On a near-balanced
corpus, calling every pair a match scores 0.7228 on the hard
slice. F1 is a weak discriminator here, which is why it is reported alongside ROC-AUC and
fixed-recall figures rather than alone.

## 4. Results

Hard-negatives-only slice, 2,491 positives against
1,911 hard negatives.

| Baseline | Family | max-F1 | Recall @ 1% FPR | Recall @ 0.1% FPR | ROC-AUC | FPR for 95% recall | Deterministic |
|---|---|---|---|---|---|---|---|
| `llm-judge/claude-opus-5` | frontier LLM | 0.9859 | 0.9775 | 0.8414 | 0.9960 | 0.004 | no |
| `llm-judge/claude-sonnet-5` | frontier LLM | 0.9820 | 0.9627 | 0.5680 | 0.9918 | 0.007 | no |
| `nomenklatura/logic-v2` | purpose-built matcher | 0.8523 | 0.5853 | 0.3549 | 0.8711 | 0.918 | yes |
| `nomenklatura/name-based` | purpose-built matcher | 0.8044 | 0.4111 | 0.1437 | 0.8332 | 0.828 | yes |
| `nomenklatura/logic-v1` | purpose-built matcher | 0.7228 | 0.4496 | 0.0000 | 0.7233 | 1.000 | yes |
| `nomenklatura/ofac` | purpose-built matcher | 0.7228 | 0.2268 | 0.2268 | 0.6134 | 1.000 | yes |
| `embedding/LaBSE` | multilingual embedding | 0.7864 | 0.4460 | 0.2489 | 0.8171 | 0.916 | no |
| `embedding/multilingual-e5-base` | multilingual embedding | 0.7719 | 0.2625 | 0.1317 | 0.8038 | 0.793 | no |
| `icu-any-latin-ascii+levenshtein` | ICU transliteration + fuzzy | 0.7681 | 0.3770 | 0.1835 | 0.7825 | 0.864 | yes |
| `icu-any-latin-ascii+jaro-winkler` | ICU transliteration + fuzzy | 0.7633 | 0.3902 | 0.1694 | 0.7582 | 0.957 | yes |
| `icu+soundex` | English phonetic | 0.7333 | 0.3035 | 0.0000 | 0.7311 | 1.000 | yes |
| `icu+double-metaphone` | English phonetic | 0.7293 | 0.2910 | 0.0000 | 0.7004 | 1.000 | yes |
| `jaro-winkler-raw` | raw fuzzy | 0.7228 | 0.2489 | 0.2489 | 0.6244 | 1.000 | yes |
| `exact-match-nfkc` | floor | 0.7228 | 0.0000 | 0.0000 | 0.5000 | 1.000 | yes |

The separation is not marginal. The two frontier models occupy a different regime from
everything else: ROC-AUC 0.9960 and
0.9918 against
0.8711 for the best specialist matcher.

**The operational figure is the last column.** To hold 95% recall — a level a supervisor
might reasonably expect of a screening control — the frontier model needs a false-positive
rate of 0.0042. The best specialist
matcher needs 0.9178: it must flag
almost every hard negative to get there. That is the difference between a control that can
be operated at high recall and one that cannot.

## 5. The error taxonomy

Every pair is tagged with the phenomenon it tests, which converts a score into a diagnosis.
Recall per phenomenon at the 1% FPR operating point, ordered by how badly the specialist
matcher performs:

| Phenomenon | n | `logic-v2` | `sonnet-5` | `opus-5` | Δ |
|---|---|---|---|---|---|
| `patronymic:abbreviated` | 139 | 0.137 | 0.978 | **0.993** | +0.856 |
| `patronymic:turkic` | 131 | 0.153 | 0.977 | **0.992** | +0.840 |
| `patronymic:dropped` | 353 | 0.210 | 0.943 | **0.983** | +0.773 |
| `romanisation:be-bgn` | 29 | 0.414 | 1.000 | **1.000** | +0.586 |
| `token:dropped` | 633 | 0.419 | 0.919 | **0.946** | +0.528 |
| `patronymic:form-substituted` | 105 | 0.438 | 0.981 | **0.990** | +0.552 |
| `romanisation:uk-kmu55` | 63 | 0.460 | 1.000 | **1.000** | +0.540 |
| `romanisation:ad-hoc` | 582 | 0.490 | 0.976 | **0.988** | +0.498 |
| `patronymic:russified` | 846 | 0.506 | 0.966 | **0.981** | +0.475 |
| `legal-form` | 530 | 0.534 | 0.932 | **0.958** | +0.425 |
| `corruption:mixed-script-homoglyph` | 52 | 0.558 | 0.981 | **0.981** | +0.423 |
| `uzbek:apostrophe` | 83 | 0.566 | 1.000 | **1.000** | +0.434 |
| `kazakh:cyrillic-latin` | 157 | 0.592 | 0.981 | **0.994** | +0.401 |
| `romanisation:uz-latin1995` | 121 | 0.636 | 1.000 | **1.000** | +0.364 |
| `romanisation:bgn` | 366 | 0.757 | 0.978 | **0.989** | +0.232 |
| `romanisation:icao` | 128 | 0.773 | 0.992 | **0.984** | +0.211 |
| `romanisation:diacritics-stripped` | 150 | 0.840 | 0.967 | **0.987** | +0.147 |
| `romanisation:iso9` | 51 | 0.961 | 0.980 | **1.000** | +0.039 |
| `romanisation:scholarly` | 19 | 1.000 | 1.000 | **1.000** | +0.000 |

Two things stand out.

**The specialist matcher's failures are structural, not orthographic.** It handles Russian
romanisation standards well — ISO 9 0.961, BGN/PCGN
0.757, ICAO 0.773. What
defeats it is name *structure* — abbreviated patronymics
0.137, Turkic patronymics
0.153, dropped patronymics
0.210 — and the non-Russian East Slavic romanisations
that change *consonants* rather than vowel digraphs: Belarusian
0.414, Ukrainian
0.460. Ukrainian official romanisation maps `г`→`h`,
so `Гончаров` becomes `Honcharov`, not `Goncharov`; a Russian-tuned matcher mispredicts the
first character, which is what prefix-weighted similarity and blocking punish hardest.

**The general model has no such profile.** It exceeds
0.946 on every phenomenon in the table. There is no
residual segment where a specialist retains an advantage.

### Precision is not the trade

A method can buy recall with false positives. This one does not — but the detail is worth
reporting honestly. False positives by hard-negative construction, at each matcher's own
1% FPR threshold:

| Hard-negative slice | n | `logic-v2` FPs | `opus-5` FPs |
|---|---|---|---|
| `negative:similar-string` | 1365 | 17 (0.0125) | 18 (0.0132) |
| `negative:same-surname` | 650 | 1 (0.0015) | 6 (0.0092) |
| `negative:romanisation-collision` | 341 | 0 (0.0000) | 8 (0.0235) |
| `negative:gender-pair` | 380 | 0 (0.0000) | 0 (0.0000) |
| `negative:patronymic-collision` | 166 | 0 (0.0000) | 0 (0.0000) |

At its max-F1 operating point the frontier model reaches precision
0.9903 at recall 0.9815
(24 false positives,
46 misses out of 2,491 positives).

**The one place the specialist matcher wins** is romanisation collisions: it produces
0 false positives there against
8 for the frontier model. That is
partly an artefact of operating at 58.5% recall
rather than 97.8% — a less sensitive matcher makes
fewer errors of every kind. But it is also the expected place for a semantically-driven
method to err: two names that collapse to one Latin form under Russian-mediated
romanisation are genuinely ambiguous, and the frontier model spends its small error budget
there rather than randomly.

## 6. Threats to validity

**Memorisation.** The corpus is built from public figures — Wikidata notables and OFAC
designees — so a language model might be recalling known aliases rather than reasoning
about transliteration. This was tested. If memorisation were the mechanism, rule-generated
Latin forms that appear in no real record anywhere should score markedly worse than real
alias data. They score **better**:

| Provenance | Recall @ 1% FPR | n |
|---|---|---|
| synthetic (rule-generated; in no real record) | 0.9987 | 745 |
| Wikidata labels (real, notable people) | 0.9899 | 496 |
| OFAC SDN alias sets (real, designated people) | 0.9600 | 1,250 |

Memorisation would have been the more comfortable explanation for the authors of this
benchmark. It is not supported.

**Single vendor.** Only two frontier models were tested, both from Anthropic. Whether this
result generalises to other frontier models is **untested**, and it is the largest gap in
this work. The harness accepts any scorer; contributions are welcome.

**Corpus difficulty is a choice.** The negatives were constructed by the author, so the
headline recall figures are partly a property of that construction. Treat the hard slice as
a lower bound on matcher quality, not as anyone's production false-positive rate.

**Coverage is uneven.** `ru` 2,926 · `uk` 694 · `be` 520 · `kk` 497 · `ky` 198 · `tg` 145 · `uz` 122. Kyrgyz is capped by Wikidata itself — roughly 489
entities carry both a `ky` and an `en` label — and Uzbek Cyrillic barely exists there (46
`uz-cyrl` labels), so Uzbek Cyrillic pairs are generated by inverting the 1995 Latin
mapping and are marked synthetic. **Per-language claims for `ky`, `tg` and `uz` are not
supportable** from this corpus. Armenian, Georgian, Azerbaijani Cyrillic and Turkmen are
absent entirely.

**Three negative slices are short of target**, reported rather than silently truncated:
`similar-string` 375/700, `romanisation-collision` 344/380, `patronymic-collision` 178/200.
These are data limits on entities with differing dates of birth.

**A benchmarking trap worth passing on.** Extended thinking is enabled by default on the
models tested and is billed as output tokens. With a small `max_tokens` the entire budget
is consumed by the thinking block, the response carries no text at all, and the answer is
unrecoverable. That failure **correlates with difficulty** — harder pairs think longer — so
a tight token budget silently scores the hardest true pairs as non-matches and understates
the baseline in whichever direction the experimenter happens to be hoping for. Our budget
had to be raised to 1,024 tokens before parse failures reached zero. Separately, an API
credit exhaustion mid-run left 54 pairs cached as errors and scored 0.0; the harness now
refuses to publish any run containing errored responses.

## 7. Cost, latency and determinism

Accuracy is not the only axis, and the frontier models lose badly on the others.

| | `logic-v2` | `claude-sonnet-5` | `claude-opus-5` |
|---|---|---|---|
| Wall clock, ~5,100 pairs | 2.8s (local) | 972s | 1342s |
| Concurrency used | 1 | 16 | 16 |
| Input tokens / comparison | 0 | 122 | 122 |
| Output tokens / comparison | 0 | 15 | 52 |
| Deterministic | yes | no | no |
| Replayable for an auditor | yes | no | no |

Token totals are quoted per comparison rather than in aggregate because the corpus was
rebuilt between passes; per-comparison rates are stable, aggregates are not comparable.
Absolute cost is deliberately not quoted — it depends on per-token pricing that changes and
that readers should check for themselves.

**Determinism is the load-bearing row.** Regulated screening is replayed: an examiner may
ask why a historical alert was or was not raised, and the answer must be reproducible from
the same inputs and a pinned version. The frontier models cannot provide that. They cannot
even be pinned to greedy decoding — the model family tested **rejects a `temperature`
parameter outright** as deprecated. Combined with model deprecation cycles, that makes an
unmediated LLM unsuitable as the scorer of record in an audited pipeline, whatever its
accuracy.

That is a statement about *admissibility*, not about the accuracy gap, and it should not be
read as diminishing the measured result.

## 8. What this settles, and what it does not

**Settled.** The linguistic knowledge required for cross-script CIS name matching is not
scarce. It is present in general-purpose frontier models and reachable with a two-sentence
prompt. Any product thesis premised on that knowledge being rare and hard to acquire is
not supported by this measurement. The benchmark was built to test exactly that thesis and
it returned a verdict against it; the project was stopped rather than continued.

**Not settled, and genuinely open:**

- Whether the result holds for frontier models from other vendors, and for open-weight
  models that could be run on-premises — which matters enormously, because on-premises
  deployment is a hard requirement for many regulated buyers.
- Whether LLM-quality matching can be made **deterministic, auditable and cheap** —
  by distillation, caching, or reproducible generation with a retained decision trail.
  That is where the remaining unmet need appears to be, and this benchmark does not test
  it at all.
- How any of this behaves on **non-notable names**, which are the overwhelming majority of
  real screening traffic and which no public corpus of this kind can easily represent.

**A note on fairness to the specialist matchers.** `nomenklatura` is optimised for
constraints the frontier models ignore: it is deterministic, explainable, auditable, free,
and runs in 2.8 seconds locally on this corpus without a network call.
Comparing it to a frontier model on accuracy alone is not the whole picture, and none of
this should be read as a criticism of its engineering. The honest framing is that
**cross-script name matching turns out to be much harder than the tooling built for it
assumed, and much easier than anyone expected for a general model** — not that any project
did poor work.

## 9. Scope, licensing and reproduction

**Defensive use only.** This work exists to help regulated parties *find* sanctioned
counterparties. It is not a tool for testing whether a name variant evades screening, and
the corpus must not be used to build alias generators positioned around evasion or scoring
surfaces that rank variants by likelihood of not being flagged. Any matcher informed by
this benchmark is a screening *aid*; responsibility for compliance and for the disposition
of every alert remains with the screener.

**No commercial screening product was benchmarked.** Only open-source matchers, published
algorithms, standard libraries and commercially available general-purpose APIs were
evaluated — everything a third party can re-run. Vendors are invited to submit their own
results.

**Data provenance.** Wikidata labels are CC0. OFAC SDN data is a United States Government
work published for public compliance use; `[VERIFY]` current terms at
<https://ofac.treasury.gov> before redistributing the extract. Only public figures —
watchlist entries and Wikidata notables — and synthetic constructions appear in the corpus;
no customer data and no compiled dataset of private individuals.

**Reproduction.** Source snapshots are committed, so the corpus rebuilds offline and
byte-identically; CI asserts that on every change, alongside accuracy gates that fail if
any deterministic baseline regresses. Environment: Python 3.12.1,
`nomenklatura` 4.12.4, real ICU via PyICU,
`sentence-transformers` 5.6.1.

```bash
pip install -r requirements-dev.txt
python3 benchmark/harness/build/build_pairs.py     # rebuild corpus from snapshots
python3 benchmark/harness/run.py --version v1.0      # score every baseline
python3 -m pytest tests/                            # unit, integrity, accuracy gates
```

Per-pair scores for every baseline are published in
`benchmark/results/v1.0/scores.jsonl`, so any figure above can be recomputed and
any disagreement located precisely.

---

*Corpus `v1.0`, sha256 `bdbc4e8522b3a525…`, measured 2026-08-10
against the OFAC SDN list published 2026-07-24. Sanctions data decays weekly; treat every
figure as of those dates. Corrections are welcome and will be published.*
