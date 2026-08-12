# tamga-benchmark

**An open benchmark for cross-script name matching on Cyrillic and Central Asian names,
as used in sanctions and denied-party screening.**

5,102 labelled name pairs · 19 baselines · every per-pair score published ·
measured 2026-08-10 · corpus `v1.0`, sha256 `bdbc4e8522b3a525…`

A *tamga* is the seal Turkic and Mongol peoples stamped to mark identity and lineage — the
oldest answer to "is this the same party?".

---

## The problem

Sanctions and denied-party watchlists are published predominantly in Latin script. A large
share of the counterparty records screened against them — Russian, Kazakh, Ukrainian,
Belarusian, Uzbek, Kyrgyz — are written in Cyrillic, and **there is no single romanisation
standard** mapping between the two. One Cyrillic surname has many legitimate Latin
spellings, several produced by mutually incompatible published standards.

Fuzzy matching assumes edit distance correlates with the probability that two names denote
different entities. Across scripts it does not:

| Pair | Edit distance | Truth |
|---|---|---|
| `Shcherbakov` / `Scherbakov` | 1 | same person, two romanisation systems |
| `Ivanov` / `Ivanova` | 1 | usually different people — gendered forms |
| `Aleksandr` / `Oleksandr` | 1 | Russian and Ukrainian forms; records don't say which |

Legitimate spelling variance and genuine identity difference occupy the same edit distance,
so no threshold separates them. Despite being an operational problem for every institution
screening CIS counterparties, we found no public benchmark quantifying it. This is one.

## The headline result

Hard-negatives-only slice — 2,491 positives against 1,911 hard negatives:

| Baseline | Family | max-F1 | Recall @ 1% FPR | ROC-AUC | FPR for 95% recall | Deterministic |
|---|---|---|---|---|---|---|
| `llm-judge/claude-opus-5` | frontier LLM | **0.9859** | **0.9775** | **0.9960** | **0.004** | no |
| `llm-judge/claude-sonnet-5` | frontier LLM | 0.9820 | 0.9627 | 0.9918 | 0.007 | no |
| `nomenklatura/logic-v2` | purpose-built matcher | 0.8523 | 0.5853 | 0.8711 | 0.918 | yes |
| `embedding/LaBSE` | multilingual embedding | 0.7864 | 0.4460 | 0.8171 | 0.916 | no |
| `icu-any-latin-ascii+levenshtein` | ICU translit + fuzzy | 0.7681 | 0.3770 | 0.7825 | 0.864 | yes |
| `icu+soundex` | English phonetic | 0.7333 | 0.3035 | 0.7311 | 1.000 | yes |
| `exact-match-nfkc` | floor | 0.7228 | 0.0000 | 0.5000 | 1.000 | yes |

Full table of all 19 baselines: [`docs/findings.md`](docs/findings.md) §4.

Three things this measured:

1. **Purpose-built matchers leave a large, systematically-shaped gap.** The strongest
   freely-available specialist matcher recovers 58.5% of true matches at a 1%
   false-positive rate. Its failures concentrate in nameable linguistic phenomena — above
   all name *structure*, not orthography.
2. **A general-purpose language model closes it almost entirely.** Given a two-sentence
   prompt and no transliteration tables, romanisation standards or name parser,
   `claude-opus-5` recovers 97.8% at the same operating point — **39 percentage points of
   recall** — without a precision penalty.
3. **The gap was never a knowledge gap.** Turkic patronymics go `0.153` → `0.992`;
   Ukrainian official romanisation `0.460` → `1.000`.

**The operational figure is the last column.** To hold 95% recall, the frontier model needs
a 0.4% false-positive rate. The best specialist matcher needs 91.8% — it must flag almost
every hard negative to get there. That is the difference between a control that can be
operated at high recall and one that cannot.

**But determinism cuts the other way.** Regulated screening is replayed: an examiner may
ask why a historical alert was or was not raised, and the answer must be reproducible from
the same inputs and a pinned version. `logic-v2` scores the corpus in 2.8 seconds locally,
deterministically, offline, for free. The frontier models take ~20 minutes, cost money, and
cannot be pinned — the model family tested rejects a `temperature` parameter outright.
That is a statement about *admissibility*, not about the accuracy gap. See
[`docs/findings.md`](docs/findings.md) §7.

## Why this exists

It was built to test a commercial hypothesis: that cross-script name matching needs Slavic
and Turkic linguistic expertise vendors lack, and that supplying it is a defensible
product. **The measurement refuted that hypothesis and the product was abandoned.** The
kill criteria were numeric and fixed before any work, precisely so a bad result could not
be argued away afterwards.

What survives is the benchmark, published as a public good. The corpus, the harness and
every per-pair score are here so the result can be checked and disputed.

## An incidental finding, if you screen names for a living

**236 of the OFAC SDN list's own Cyrillic-declared name variants contain Latin
homoglyphs** — a Latin `i` inside the Belarusian patronymic `Рыгоравiч`, a Latin `O` in
`OOO`, a Latin `P` in `ТPиБУн`. Visually identical, different codepoints, and enough to
defeat script detection silently. Measured on the list published 2026-07-24; these pairs
are tagged `corruption:mixed-script-homoglyph` rather than cleaned away.

## What's in the box

```
tamga-benchmark/
├── docs/
│   ├── findings.md        # THE WRITE-UP — start here
│   ├── domain-notes.md    # the linguistics: why this is hard, in detail
│   ├── data-sources.md    # provenance and licence of every input
│   └── legal-and-ethics.md# defensive-use scope, personal data, publishing rules
├── benchmark/
│   ├── pairs/             # the labelled corpus (v1.0 + the pilot, for provenance)
│   ├── sources/           # committed source snapshots — the corpus rebuilds offline
│   ├── harness/           # baselines, metrics, corpus builder
│   └── results/           # metrics, per-phenomenon breakdown, per-pair scores
├── tests/                 # unit, corpus integrity, and accuracy gates
└── CLAUDE.md              # the working agreement — verification discipline
```

## Reproducing it

Source snapshots are committed, so the corpus rebuilds offline and byte-identically; CI
asserts that on every change, alongside accuracy gates that fail if any deterministic
baseline regresses.

```bash
pip install -r requirements-dev.txt
```

```bash
python3 benchmark/harness/build/build_pairs.py
```

```bash
python3 benchmark/harness/run.py --version v1.0
```

```bash
python3 -m pytest tests/
```

Environment: Python 3.12.1, `nomenklatura` 4.12.4, real ICU via PyICU,
`sentence-transformers` 5.6.1. The LLM baselines need `ANTHROPIC_API_KEY`; every other
baseline runs offline. Per-pair scores for every baseline are in
[`benchmark/results/v1.0/scores.jsonl`](benchmark/results/v1.0/scores.jsonl), so any figure
above can be recomputed and any disagreement located precisely.

## Contributing, and the open questions

The harness accepts any scorer. The gaps most worth closing, in order:

- **Other vendors' frontier models, and open-weight models.** Only two models were tested,
  both from Anthropic. Whether the result generalises is **untested** and it is the largest
  gap in this work. Open-weight matters most — on-premises deployment is a hard requirement
  for many regulated buyers.
- **Deterministic, auditable, cheap LLM-quality matching** — by distillation, caching, or
  reproducible generation with a retained decision trail. That is where the remaining unmet
  need appears to be, and this benchmark does not test it at all.
- **Languages this corpus underserves.** Per-language claims for `ky`, `tg` and `uz` are
  **not supportable** from this corpus. Armenian, Georgian, Azerbaijani Cyrillic and
  Turkmen are absent entirely.
- **Non-notable names**, which are the overwhelming majority of real screening traffic and
  which no public corpus of this kind can easily represent.

Vendors of commercial screening products are invited to submit their own results. **No
commercial product was benchmarked here** — only open-source matchers, published
algorithms, standard libraries and generally available APIs, all re-runnable by a third
party. Corrections are welcome and will be published.

## Scope — defensive use only

This corpus exists to help regulated parties **find** sanctioned counterparties. It is not
a tool for testing whether a name variant *evades* screening, and it must not be used to
build alias generators positioned around evasion, or scoring surfaces that rank variants by
likelihood of not being flagged. See [`docs/legal-and-ethics.md`](docs/legal-and-ethics.md).

Any matcher informed by this benchmark is a screening *aid*. Responsibility for compliance
and for the disposition of every alert remains with the screener.

## Licence

- **Code** (`benchmark/harness/`, `tests/`) — MIT. See [`LICENSE`](LICENSE).
- **Corpus and results** (`benchmark/pairs/`, `benchmark/results/`, `benchmark/sources/`) —
  CC BY 4.0. See [`LICENSE-DATA`](LICENSE-DATA).

Wikidata labels are CC0. OFAC SDN data is a United States Government work published for
public compliance use. Only public figures — watchlist entries and Wikidata notables — and
synthetic constructions appear in the corpus; no customer data and no compiled dataset of
private individuals. Provenance per source: [`docs/data-sources.md`](docs/data-sources.md).

---

*Corpus `v1.0`, measured 2026-08-10 against the OFAC SDN list published 2026-07-24.
Sanctions data decays weekly; treat every figure as of those dates.*
