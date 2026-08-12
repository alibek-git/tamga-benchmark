# The benchmark

It does two jobs at once:

1. **Kill test** — decides whether the gap a product thesis was premised on actually
   exists (see *The pre-registered gate* below).
2. **Permanent eval harness** — any matcher can be scored against it, in CI.

Status: **complete, and it did its job — the gate returned KILL.**
`pairs/v1.0.jsonl` holds **5,102 pairs** with results in `results/v1.0/`; the 460-pair pilot
(`pairs/pilot-v0.1.jsonl`) stays committed for provenance and is superseded for all reported
figures. Accuracy gates run in CI.

A frontier LLM judge clears both kill criteria (0.9859 max-F1, 0.9775 recall @ 1% FPR) and
closes every phenomenon the dedicated matchers fail on. The publication write-up is
[`../docs/findings.md`](../docs/findings.md). This corpus remains useful — as the published
measurement of *why* the older methods break, and as the eval harness for anything built
next.

---

## The pre-registered gate

The kill criteria were numeric and fixed **before any work**, precisely so a bad result
could not be argued away afterwards:

| Condition | Verdict |
|---|---|
| A commodity baseline reaches **max-F1 ≥ 0.93 and recall ≥ 0.95 at 1% FPR** | **KILL** — the gap does not exist |
| The best commodity baseline stays at **max-F1 ≤ 0.85** | GO — build the engine |
| Between the two | Narrow the claim to the phenomena where the gap survives |

They are hard-coded in [`harness/run.py`](harness/run.py) (`GATE_KILL_F1`,
`GATE_KILL_RECALL_AT_1PCT`, `GATE_GO_F1`) so the verdict is computed against the criterion
decided in advance rather than one chosen after seeing the numbers. `claude-opus-5` cleared
the kill threshold on both metrics.

> **A note on references to `PLAN.md`.** Comments in the harness and strings inside the
> committed results cite `PLAN.md` — the private planning document where these thresholds
> and the baseline list were fixed. It is not part of this repository, which carries the
> benchmark rather than the commercial plan it was built to test. Those strings are left
> exactly as they were when the measurement ran: the results files are the record of what
> was actually executed, and editing them after the fact to tidy a reference would corrupt
> that record for a cosmetic gain.

## Dataset schema

One JSONL record per labelled pair.

```json
{
  "id": "wd-0001742",
  "name_a": "Щербаков Александр Иванович",
  "name_b": "Alexander Scherbakov",
  "script_a": "Cyrl",
  "script_b": "Latn",
  "language": "ru",
  "entity_type": "person",
  "same_entity": true,
  "phenomena": ["romanisation:ad-hoc", "patronymic:dropped", "order:swapped"],
  "difficulty": "hard",
  "source": "wikidata:Q123456",
  "notes": "щ→sch is non-standard but common in older records"
}
```

Field notes:

- **`phenomena`** — the whole point. Tagging *what each pair tests* is what converts a
  score into an error taxonomy, and the taxonomy is what tells us whether a real engine
  has anything to add over a commodity baseline. A benchmark without this is a number
  with no diagnostic value.
- **`difficulty`** — `easy` / `hard`. Report metrics broken out by this. Aggregate scores
  over an easy-heavy set are the standard way benchmarks lie.
- **`source`** — provenance for every pair, so any label can be re-checked or disputed.
- **`same_entity`** — where the truth is genuinely uncertain, exclude the pair rather than
  guessing. A mislabelled benchmark is worse than a small one.

## Phenomenon vocabulary

Extend as the corpus grows; keep it controlled, not free text.

| Tag | Tests |
|---|---|
| `romanisation:iso9` / `:gost-b` / `:bgn` / `:icao` / `:ala-lc` / `:scholarly` / `:ad-hoc` | Which system produced the Latin form |
| `patronymic:dropped` / `:abbreviated` / `:turkic` / `:russified` | Patronymic handling |
| `gender:feminine-form` / `:stripped` | Gendered surname forms |
| `kazakh:cyrillic-latin` / `:derussified` | Kazakh multi-alphabet and `-ов` dropping |
| `order:swapped` | Surname-first vs given-first |
| `language:ru-uk-variant` | Russian vs Ukrainian form of one name |
| `uzbek:apostrophe` | `oʻ`/`gʻ` codepoint variance |
| `legal-form` | `ТОО` / `TOO` / `LLP`, `ООО` / `LLC` etc. |
| `corruption:ocr` / `:typo` | Degraded records |
| `negative:same-surname` / `:gender-pair` / `:similar-string` | Hard-negative construction |

### Vocabulary added by the pilot build

Each of these was needed to describe something the corpus actually contains. Definitions
live in `harness/phenomena.py::EXTENDED_VOCABULARY`, which is the authoritative list.

| Tag | Tests |
|---|---|
| `given:exonym` / `:diminutive` | `Александр`→`Alexander` is a conventional English form, not a romanisation — no rule table produces it |
| `patronymic:form-substituted` | Both sides carry a patronymic but in different conventions (`-ұлы` against `-ович`) — a substitution, not a drop |
| `romanisation:diacritics-stripped` | Explained only after combining marks are removed. Reported as the degradation rather than named as a system, because several standards collapse to the same ASCII |
| `romanisation:unattributed-variant` | Two Latin forms of one Cyrillic original whose systems cannot be identified without that original |
| `corruption:mixed-script-homoglyph` | Latin letters inside a Cyrillic string. **Measured in OFAC SDN itself, not synthesised** — 236 of its Cyrillic-declared name variants contain Latin homoglyphs (list of 2026-07-24) |
| `negative:romanisation-collision` | Two different Cyrillic names that collapse to one Latin form — the sharpest hard negative available |
| `negative:patronymic-collision` | Different entities sharing surname and patronymic |
| `token:dropped` / `:unaligned` / `:abbreviated` | Token-level residue, kept visible rather than absorbed |
| `script:same` | Latn↔Latn cross-romanisation, or Cyrl↔Cyrl language variant |

`kazakh:derussified` remains **untested**: the Russian suffix in `Назарбаев` absorbs the
stem's final consonant, so reconstructing `Назарбай` is guesswork, and inventing morphology
to fill a slice would be worse than leaving it empty.

## Construction decisions that shape the numbers

Recorded here because each one changes how results must be read.

- **`language` comes from orthography, not from the source label's language code.** The
  `kk` label of a Kazakhstani citizen is frequently a Russian name in Russian orthography;
  filing it under `kk` would make the per-language breakdown say something false. Each
  record's `notes` carries the evidence used. Kazakh and Kyrgyz share `ң ө ү`, so those
  letters alone cannot separate them and the source label language breaks that tie only.
- **Negatives require both dates of birth present and different.** Distinct QIDs are not
  quite a guarantee of distinct entities, and two Wikidata items for one person almost
  always share a DOB.
- **Negatives whose two names are identical after normalisation are excluded.** They are
  correctly labelled — differing DOB proves different entities — but no name matcher can
  resolve them from names alone, so they would add a fixed error floor that says nothing
  about the transliteration gap. The count is in the manifest.
- **Romanisation attribution is conservative.** A system is named only when it reproduces
  *every* aligned token exactly; otherwise the pair is `ad-hoc` or
  `diacritics-stripped`. Under-attribution is the safe direction of error for a benchmark
  whose taxonomy is its main output.

## Composition targets

| Property | Target |
|---|---|
| Total pairs | ≥ 5,000 — **met: 5,102** |
| Languages | `ru`, `kk`, `uk`, `uz`, `ky` minimum |
| Positive : negative | roughly balanced |
| Hard negatives, as share of negatives | ≥ 60% |
| Synthetic (rule-generated) pairs, as share of positives | ≤ 30% — see below |
| Entity types | person-dominant, with organisation coverage |

**On the synthetic cap.** Rule-generated pairs only test transformations we already
modelled, so a corpus dominated by them measures our own assumptions back at us. They're
necessary for coverage of rare letters; they must stay a minority.

Sources and licensing: [`../docs/data-sources.md`](../docs/data-sources.md).

## Metrics — report all three, never one alone

1. **Recall at fixed false-positive rate** (1% and 0.1%). The number a compliance buyer
   cares about, because FPR *is* their labour cost and recall is their regulatory risk.
2. **F1** on the balanced set, for comparability with published work.
3. **Error taxonomy** — per-phenomenon breakdown for every baseline. The diagnostic output.

Always state the operating point. A precision figure without its recall level is
meaningless here and, in marketing, dishonest (`../docs/legal-and-ethics.md` §6).

Also measure **blocking recall separately** if a baseline uses candidate generation — a
true hit dropped before scoring is invisible in pairwise metrics and is the most common
place real systems silently lose recall.

## Baselines

The full list is [`harness/baselines.py`](harness/baselines.py). Run every one; the weak
ones matter as much as the strong ones, because "Soundex fails here" is a finding worth
publishing.

## Harness requirements

- Deterministic and re-runnable by a stranger from a clean checkout.
- Every result carries the dataset version and baseline version.
- Results committed as data, not pasted into prose — the docs reference them.
- **Never write a number here that wasn't produced by a run** (`../CLAUDE.md` §3).

## The LLM-as-judge baseline

Run against corpus `v1.0` with two frontier models (`claude-sonnet-5`, `claude-opus-5`),
because "just use a *bigger* LLM" is a different claim from "just use an LLM" and only
measurement separates them.

Configuration, and why it is what it is:

| Choice | Reason |
|---|---|
| No `temperature` | Deprecated for the Claude 5 family; the API rejects it with HTTP 400. The judge cannot be pinned to greedy decoding even in principle. |
| Extended thinking left **enabled** (the default) | The strongest honest form of the method. A buyer evaluating "just use an LLM" hits the default configuration. |
| `max_tokens` 1,024, retried at 4,096 | Thinking is billed as output and consumed the whole budget at smaller values, leaving responses with **no text block at all**. |
| Raw responses cached to `benchmark/.cache/` | So a published figure stays auditable even though the run is not repeatable. Gitignored — it is derived data, and large. |

**The token budget was a real trap.** At `max_tokens=8`, 2 of 12 sampled pairs returned
nothing parseable and were scored 0.0. Truncation correlates with pair *difficulty* —
harder pairs think longer — so a tight budget systematically scores the hardest true pairs
as non-matches. That biases a competitor baseline downward in whichever direction the
experimenter happens to be hoping for. It is pinned by tests in `../tests/`.

Neither LLM baseline is used as a regression floor: non-deterministic scorers cannot be
version-frozen for replay, which `../CLAUDE.md` §4 disqualifies from an audited pipeline.
They are measured and reported like everything else.

## Regression gates

`../tests/` implements the three layers in `../tests/README.md`, and layer 3 is the one
that matters: `test_accuracy_gates.py` **recomputes** every deterministic baseline from the
committed corpus and fails if any drops below a floor in `../tests/accuracy_gates.json`.
It deliberately does not read `metrics.json`, which would only prove a JSON file is
self-consistent rather than catching a change to `translit.py` that degraded matching.

Floors are `measured − 0.01`, so a two-point regression fails while library noise does not.
Embedding and LLM baselines are measured but never used as floors — they are not
version-stable, which `../CLAUDE.md` §4 disqualifies from an audited pipeline.

Regenerate floors only when a change is understood and intended:

```bash
python3 benchmark/harness/make_gates.py --version v1.0
```

Lowering a floor to make CI pass defeats the entire purpose of the gate.
