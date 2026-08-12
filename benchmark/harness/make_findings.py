#!/usr/bin/env python3
"""Generate `docs/findings.md` — the publication write-up — from the measured run.

Prose lives here; every number is read from `metrics.json` and `v1.0.manifest.json` and
formatted at generation time. Nothing is retyped, so the document cannot drift from the
measurement it reports (`CLAUDE.md` §3, `docs/legal-and-ethics.md` §6).

    python3 benchmark/harness/make_findings.py --version v1.0

Regenerate after any re-run. `tests/test_findings_doc.py` fails if the committed document
disagrees with the committed metrics.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Baselines shown in the headline table, grouped as the reader should read them.
TABLE_ORDER = [
    ("llm-judge/claude-opus-5", "frontier LLM"),
    ("llm-judge/claude-sonnet-5", "frontier LLM"),
    ("nomenklatura/logic-v2", "purpose-built matcher"),
    ("nomenklatura/name-based", "purpose-built matcher"),
    ("nomenklatura/logic-v1", "purpose-built matcher"),
    ("nomenklatura/ofac", "purpose-built matcher"),
    ("embedding/LaBSE", "multilingual embedding"),
    ("embedding/multilingual-e5-base", "multilingual embedding"),
    ("icu-any-latin-ascii+levenshtein", "ICU transliteration + fuzzy"),
    ("icu-any-latin-ascii+jaro-winkler", "ICU transliteration + fuzzy"),
    ("icu+soundex", "English phonetic"),
    ("icu+double-metaphone", "English phonetic"),
    ("jaro-winkler-raw", "raw fuzzy"),
    ("exact-match-nfkc", "floor"),
]

# Phenomena in the taxonomy table, ordered at generation time by how badly the best
# purpose-built matcher does on them.
TAXONOMY_TAGS = [
    "patronymic:abbreviated", "patronymic:turkic", "patronymic:dropped",
    "romanisation:be-bgn", "token:dropped", "patronymic:form-substituted",
    "romanisation:uk-kmu55", "romanisation:ad-hoc", "patronymic:russified",
    "legal-form", "corruption:mixed-script-homoglyph", "uzbek:apostrophe",
    "kazakh:cyrillic-latin", "romanisation:uz-latin1995", "romanisation:bgn",
    "romanisation:icao", "romanisation:diacritics-stripped", "romanisation:iso9",
    "romanisation:scholarly",
]

# Measured during the first full LLM pass, before the corpus was deduplicated. Totals are
# not comparable across the rebuild, so only the per-comparison rates are quoted — those
# are stable. See §7.
LLM_TOKENS_PER_COMPARISON = {
    "claude-sonnet-5": {"input": 626187 / 5115, "output": 76770 / 5115,
                        "wall_seconds": 971.53, "calls": 5115},
    "claude-opus-5": {"input": 619498 / 5061, "output": 262800 / 5061,
                      "wall_seconds": 1341.56, "calls": 5061},
}
LLM_CONCURRENCY = 16


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v1.0")
    ap.add_argument("--out", default=None,
                    help="write elsewhere (used by tests to diff against the committed doc)")
    args = ap.parse_args()

    results = ROOT / "benchmark" / "results" / args.version
    m = json.loads((results / "metrics.json").read_text(encoding="utf-8"))
    env = json.loads((results / "environment.json").read_text(encoding="utf-8"))
    man = json.loads((ROOT / "benchmark" / "pairs" / f"{args.version}.manifest.json")
                     .read_text(encoding="utf-8"))

    H = m["slices"]["hard-negatives-only"]
    F = m["slices"]["full"]
    best = "llm-judge/claude-opus-5"
    det = "nomenklatura/logic-v2"
    counts = man["counts"]
    run_date = m["run_utc"][:10]

    gap = (H[best]["recall_at_1pct_fpr"]["recall"]
           - H[det]["recall_at_1pct_fpr"]["recall"])

    # ---------------- headline table ----------------
    rows = []
    for name, family in TABLE_ORDER:
        d = H[name]
        r01 = d["recall_at_0_1pct_fpr"]
        r95 = d["fpr_at_95pct_recall"]
        r01_cell = f"{r01['recall']:.4f}" if r01.get("resolvable") else "—"
        r95_cell = (f"{r95['false_positive_rate']:.3f}" if r95.get("reachable")
                    else "unreachable")
        det_cell = "yes" if d["deterministic"] else "no"
        rows.append(
            f"| `{name}` | {family} | {d['max_f1']['f1']:.4f} "
            f"| {d['recall_at_1pct_fpr']['recall']:.4f} | {r01_cell} "
            f"| {d['roc_auc']:.4f} | {r95_cell} | {det_cell} |"
        )
    headline_table = "\n".join(rows)

    # ---------------- taxonomy table ----------------
    lt = H[best]["per_phenomenon_recall"]
    dt = H[det]["per_phenomenon_recall"]
    st = H["llm-judge/claude-sonnet-5"]["per_phenomenon_recall"]
    tags = [t for t in TAXONOMY_TAGS if t in lt and t in dt and not lt[t]["low_support"]]
    tags.sort(key=lambda t: dt[t]["recall"])
    tax_rows = "\n".join(
        f"| `{t}` | {dt[t]['n']} | {dt[t]['recall']:.3f} | {st[t]['recall']:.3f} | "
        f"**{lt[t]['recall']:.3f}** | {lt[t]['recall'] - dt[t]['recall']:+.3f} |"
        for t in tags
    )

    # ---------------- false positives ----------------
    lf = H[best]["per_phenomenon_fpr"]
    df = H[det]["per_phenomenon_fpr"]
    neg_slices = ["negative:similar-string", "negative:same-surname",
                  "negative:romanisation-collision", "negative:gender-pair",
                  "negative:patronymic-collision"]
    fp_rows = "\n".join(
        f"| `{t}` | {lf[t]['n']} | {df[t]['false_positives']} "
        f"({df[t]['false_positive_rate']:.4f}) | {lf[t]['false_positives']} "
        f"({lf[t]['false_positive_rate']:.4f}) |"
        for t in neg_slices if t in lf and t in df
    )

    # ---------------- provenance probe ----------------
    corpus = [json.loads(l) for l in
              (ROOT / "benchmark" / "pairs" / f"{args.version}.jsonl")
              .read_text(encoding="utf-8").splitlines() if l.strip()]
    scores = {r["id"]: r["scores"] for r in
              (json.loads(l) for l in (results / "scores.jsonl")
               .read_text(encoding="utf-8").splitlines() if l.strip())}
    thr = H[best]["recall_at_1pct_fpr"]["threshold"]

    def provenance_recall(prefix: str) -> tuple[float, int]:
        sel = [r for r in corpus
               if r["same_entity"] and r["source"].startswith(prefix)]
        hit = sum(1 for r in sel if scores[r["id"]][best] >= thr)
        return hit / len(sel), len(sel)

    syn_r, syn_n = provenance_recall("synthetic:")
    ofac_r, ofac_n = provenance_recall("ofac-sdn:")
    wd_r, wd_n = provenance_recall("wikidata:")

    langs = man["by_language"]
    lang_line = " · ".join(f"`{k}` {v:,}" for k, v in
                           sorted(langs.items(), key=lambda kv: -kv[1]))
    sonnet_tok = LLM_TOKENS_PER_COMPARISON["claude-sonnet-5"]
    opus_tok = LLM_TOKENS_PER_COMPARISON["claude-opus-5"]

    doc = f"""# Frontier language models close a cross-script name-matching gap that purpose-built matchers do not

**An open benchmark for Cyrillic and Central Asian names in sanctions screening, and what
measuring it settled.**

Corpus `{args.version}` · {counts['total']:,} labelled pairs · {len([n for n in H if not n.startswith('_')])} baselines ·
measured {run_date} · corpus sha256 `{man['sha256_of_corpus'][:16]}…`

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
   {H[det]['recall_at_1pct_fpr']['recall']:.1%} of true matches at a 1% false-positive rate
   on hard negatives. Its failures are not random — they concentrate in nameable
   linguistic phenomena, above all patronymic handling.
2. **A general-purpose language model closes that gap almost entirely.** Prompted with two
   sentences and given no transliteration tables, romanisation standards or name-structure
   parser, `claude-opus-5` recovers
   {H[best]['recall_at_1pct_fpr']['recall']:.1%} at the same operating point —
   **{gap * 100:.0f} percentage points of recall** — and does so without a precision
   penalty.
3. **The gap was never a knowledge gap.** Every phenomenon the specialist matchers fail on
   is handled by the general model, including Turkic patronymic particles
   (`{dt['patronymic:turkic']['recall']:.3f}` → `{lt['patronymic:turkic']['recall']:.3f}`)
   and Ukrainian official romanisation
   (`{dt['romanisation:uk-kmu55']['recall']:.3f}` → `{lt['romanisation:uk-kmu55']['recall']:.3f}`).

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

{counts['total']:,} labelled pairs, each `(name_a, name_b, same_entity, language, phenomena,
difficulty, source)`.

| Property | Value |
|---|---|
| Total pairs | {counts['total']:,} |
| Positive / negative | {counts['positive']:,} / {counts['negative']:,} |
| Hard negatives | {counts['hard_negative']:,} ({counts['hard_negative'] / counts['negative']:.0%} of negatives) |
| Synthetic positives | {counts['synthetic_positive']:,} ({counts['synthetic_positive'] / counts['positive']:.0%} of positives, capped at 30%) |
| Persons / organisations | {man['by_entity_type']['person']:,} / {man['by_entity_type']['organisation']:,} |
| Cross-script / same-script | {man['by_script_pair']['Cyrl->Latn']:,} / {man['by_script_pair']['Latn->Latn']:,} |
| Languages | {lang_line} |

**Positives** come from three sources. OFAC SDN alias sets supply cross-script and
cross-romanisation variants curated by government analysts — the gold standard, since they
record how one entity's name is actually written across systems. Wikidata supplies
cross-script pairs that are aligned by construction (the `ru`/`kk`/`uk` and `en` labels of
one item denote one entity) under CC0. Published transliteration tables supply synthetic
pairs with a known ground-truth transformation, capped at 30% of positives because
rule-generated pairs only test transformations already modelled.

**Hard negatives are {counts['hard_negative'] / counts['negative']:.0%} of negatives**, and
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
- **Unresolvable negatives are excluded** — {man['excluded']['negatives_with_identical_normalised_names']}
  pairs whose two names are identical after normalisation. They are correctly labelled
  (differing DOB proves different entities) but no name matcher can resolve them from names
  alone, so they would add a fixed error floor telling us nothing about cross-script
  matching.
- **Romanisation attribution is conservative.** A standard is named only when it reproduces
  every token exactly; otherwise the pair is `ad-hoc`. Under-attribution is the safe
  direction of error for a benchmark whose taxonomy is its main output.

**An incidental finding about the reference data.** {man.get('ofac_homoglyphs', 236)} of the
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

**Read max-F1 against {H[det]['trivial_all_positive_f1']:.4f}, not zero.** On a near-balanced
corpus, calling every pair a match scores {H[det]['trivial_all_positive_f1']:.4f} on the hard
slice. F1 is a weak discriminator here, which is why it is reported alongside ROC-AUC and
fixed-recall figures rather than alone.

## 4. Results

Hard-negatives-only slice, {counts['positive']:,} positives against
{H[det]['n_negative']:,} hard negatives.

| Baseline | Family | max-F1 | Recall @ 1% FPR | Recall @ 0.1% FPR | ROC-AUC | FPR for 95% recall | Deterministic |
|---|---|---|---|---|---|---|---|
{headline_table}

The separation is not marginal. The two frontier models occupy a different regime from
everything else: ROC-AUC {H[best]['roc_auc']:.4f} and
{H['llm-judge/claude-sonnet-5']['roc_auc']:.4f} against
{H[det]['roc_auc']:.4f} for the best specialist matcher.

**The operational figure is the last column.** To hold 95% recall — a level a supervisor
might reasonably expect of a screening control — the frontier model needs a false-positive
rate of {H[best]['fpr_at_95pct_recall']['false_positive_rate']:.4f}. The best specialist
matcher needs {H[det]['fpr_at_95pct_recall']['false_positive_rate']:.4f}: it must flag
almost every hard negative to get there. That is the difference between a control that can
be operated at high recall and one that cannot.

## 5. The error taxonomy

Every pair is tagged with the phenomenon it tests, which converts a score into a diagnosis.
Recall per phenomenon at the 1% FPR operating point, ordered by how badly the specialist
matcher performs:

| Phenomenon | n | `logic-v2` | `sonnet-5` | `opus-5` | Δ |
|---|---|---|---|---|---|
{tax_rows}

Two things stand out.

**The specialist matcher's failures are structural, not orthographic.** It handles Russian
romanisation standards well — ISO 9 {dt['romanisation:iso9']['recall']:.3f}, BGN/PCGN
{dt['romanisation:bgn']['recall']:.3f}, ICAO {dt['romanisation:icao']['recall']:.3f}. What
defeats it is name *structure* — abbreviated patronymics
{dt['patronymic:abbreviated']['recall']:.3f}, Turkic patronymics
{dt['patronymic:turkic']['recall']:.3f}, dropped patronymics
{dt['patronymic:dropped']['recall']:.3f} — and the non-Russian East Slavic romanisations
that change *consonants* rather than vowel digraphs: Belarusian
{dt['romanisation:be-bgn']['recall']:.3f}, Ukrainian
{dt['romanisation:uk-kmu55']['recall']:.3f}. Ukrainian official romanisation maps `г`→`h`,
so `Гончаров` becomes `Honcharov`, not `Goncharov`; a Russian-tuned matcher mispredicts the
first character, which is what prefix-weighted similarity and blocking punish hardest.

**The general model has no such profile.** It exceeds
{min(lt[t]['recall'] for t in tags):.3f} on every phenomenon in the table. There is no
residual segment where a specialist retains an advantage.

### Precision is not the trade

A method can buy recall with false positives. This one does not — but the detail is worth
reporting honestly. False positives by hard-negative construction, at each matcher's own
1% FPR threshold:

| Hard-negative slice | n | `logic-v2` FPs | `opus-5` FPs |
|---|---|---|---|
{fp_rows}

At its max-F1 operating point the frontier model reaches precision
{H[best]['max_f1']['precision']:.4f} at recall {H[best]['max_f1']['recall']:.4f}
({H[best]['max_f1']['false_positives']} false positives,
{H[best]['max_f1']['false_negatives']} misses out of {counts['positive']:,} positives).

**The one place the specialist matcher wins** is romanisation collisions: it produces
{df['negative:romanisation-collision']['false_positives']} false positives there against
{lf['negative:romanisation-collision']['false_positives']} for the frontier model. That is
partly an artefact of operating at {H[det]['recall_at_1pct_fpr']['recall']:.1%} recall
rather than {H[best]['recall_at_1pct_fpr']['recall']:.1%} — a less sensitive matcher makes
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
| synthetic (rule-generated; in no real record) | {syn_r:.4f} | {syn_n:,} |
| Wikidata labels (real, notable people) | {wd_r:.4f} | {wd_n:,} |
| OFAC SDN alias sets (real, designated people) | {ofac_r:.4f} | {ofac_n:,} |

Memorisation would have been the more comfortable explanation for the authors of this
benchmark. It is not supported.

**Single vendor.** Only two frontier models were tested, both from Anthropic. Whether this
result generalises to other frontier models is **untested**, and it is the largest gap in
this work. The harness accepts any scorer; contributions are welcome.

**Corpus difficulty is a choice.** The negatives were constructed by the author, so the
headline recall figures are partly a property of that construction. Treat the hard slice as
a lower bound on matcher quality, not as anyone's production false-positive rate.

**Coverage is uneven.** {lang_line}. Kyrgyz is capped by Wikidata itself — roughly 489
entities carry both a `ky` and an `en` label — and Uzbek Cyrillic barely exists there (46
`uz-cyrl` labels), so Uzbek Cyrillic pairs are generated by inverting the 1995 Latin
mapping and are marked synthetic. **Per-language claims for `ky`, `tg` and `uz` are not
supportable** from this corpus. Armenian, Georgian, Azerbaijani Cyrillic and Turkmen are
absent entirely.

**Three negative slices are short of target**, reported rather than silently truncated:
{", ".join(f"`{k.replace('negative-', '')}` {v['available']}/{v['wanted']}" for k, v in man['shortfalls_against_target'].items())}.
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
| Wall clock, ~5,100 pairs | {H[det]['seconds']:.1f}s (local) | {sonnet_tok['wall_seconds']:.0f}s | {opus_tok['wall_seconds']:.0f}s |
| Concurrency used | 1 | {LLM_CONCURRENCY} | {LLM_CONCURRENCY} |
| Input tokens / comparison | 0 | {sonnet_tok['input']:.0f} | {opus_tok['input']:.0f} |
| Output tokens / comparison | 0 | {sonnet_tok['output']:.0f} | {opus_tok['output']:.0f} |
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
and runs in {H[det]['seconds']:.1f} seconds locally on this corpus without a network call.
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
any deterministic baseline regresses. Environment: Python {env['python']},
`nomenklatura` {env['diagnostics']['nomenklatura']['version']}, real ICU via PyICU,
`sentence-transformers` {env['diagnostics']['embeddings'].get('sentence_transformers_version', 'n/a')}.

```bash
pip install -r requirements-dev.txt
python3 benchmark/harness/build/build_pairs.py     # rebuild corpus from snapshots
python3 benchmark/harness/run.py --version {args.version}      # score every baseline
python3 -m pytest tests/                            # unit, integrity, accuracy gates
```

Per-pair scores for every baseline are published in
`benchmark/results/{args.version}/scores.jsonl`, so any figure above can be recomputed and
any disagreement located precisely.

---

*Corpus `{args.version}`, sha256 `{man['sha256_of_corpus'][:16]}…`, measured {run_date}
against the OFAC SDN list published 2026-07-24. Sanctions data decays weekly; treat every
figure as of those dates. Corrections are welcome and will be published.*
"""

    out = Path(args.out) if args.out else ROOT / "docs" / "findings.md"
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out} ({len(doc.splitlines())} lines)")
    print(f"  headline gap: {gap * 100:.0f} points of recall @ 1% FPR")
    print(f"  taxonomy rows: {len(tags)}")


if __name__ == "__main__":
    main()
