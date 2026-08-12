# Working agreement for this repo

Read this before doing anything else here. It is referenced by section number from the
harness and the tests, because these rules are the reason the numbers in
[`docs/findings.md`](docs/findings.md) can be trusted.

---

## 1. What this repository is

An open benchmark for cross-script name matching on Cyrillic and Central Asian names, as
used in sanctions and denied-party screening: a labelled corpus, a harness that scores any
matcher against it, and the measured results for 19 baselines.

It was built to test a commercial hypothesis — that this matching problem needs Slavic and
Turkic linguistic expertise vendors lack, and that supplying it is a defensible product.
The measurement refuted that hypothesis and the product was abandoned. The benchmark was
published instead. [`docs/findings.md`](docs/findings.md) is the write-up.

## 2. The prime directive: measure before building

The order of work was fixed before any of it started:

1. Build the labelled benchmark.
2. Run commodity baselines against it.
3. **Only if the baselines fail** in systematic, nameable ways, build an engine.

They did fail that way — and then a frontier LLM judge closed the gap, which ended the
project at step 2. No engine exists in this repository, deliberately. The harness
implements only third-party or textbook methods, so that nothing here is grading its own
homework.

If you extend this benchmark, keep that separation: a scorer you are promoting does not
get to be the scorer that defines the corpus.

## 3. Verification discipline — non-negotiable

This benchmark measures a **compliance** control. A wrong fact in the foundation becomes a
wrong claim downstream in somebody's risk assessment. Treat unverified assertions as
defects.

**The `[VERIFY]` convention.** Any factual claim about the outside world — a regulation, a
sanctions programme, a matcher's capability, a licence term — must either:

- carry an inline source (URL, list name + date, statute/EO number), **or**
- be marked `[VERIFY]` with a note on what evidence would settle it.

Never quietly upgrade a `[VERIFY]` to a stated fact. Remove the marker only in the same
edit that adds the source.

**Sanctions facts decay.** Programmes, designations, general licences and thresholds change
weekly. Any claim about the current state of a sanctions regime needs a date stamp and
re-checking before it is relied on.

**Never fabricate a benchmark number.** Not as an illustration, not as a placeholder, not
as "roughly what we'd expect". If a number isn't measured, write `TBD`. Every figure in
`docs/findings.md` is generated from `benchmark/results/` by
`benchmark/harness/make_findings.py` for exactly this reason, and a test asserts it.

## 4. Non-negotiables of a compliance product

These are requirements, not preferences — and they are why the accuracy table is not the
whole story. A method that wins on accuracy and loses here may still be inadmissible.

- **Deterministic.** Same input + same engine version ⇒ byte-identical output, forever.
  Auditors and regulators replay historical decisions.
- **Versioned.** Every release gets a version; scores are attributable to it. No silent
  model swaps. Ship a delta report showing what changed and which historical decisions
  would flip.
- **Explainable.** Every match should emit a human-readable reason chain
  ("BGN/PCGN romanisation of `щ`→`shch`; patronymic dropped; gendered surname
  `Иванова`→`Иванов`"). A compliance officer must be able to defend the decision to an
  examiner. A bare similarity score is not enough.
- **Calibrated and tunable.** Output a calibrated probability plus a published
  precision/recall curve, so the user sets their own risk appetite defensibly.
- **Recall is sacred.** Precision improvements that cost recall are not improvements. A
  missed true hit is a regulatory event; a false positive is a labour cost. Optimise
  precision *at fixed recall*, and state the recall level in every result.
- **Minimal retention.** Screening payloads contain personal data. Process-and-discard by
  default.

This is why the non-deterministic baselines — embeddings and LLM judges — are measured and
reported like everything else but are **never used as regression floors**. They cannot be
version-frozen for replay.

## 5. Scope guardrail — defensive use only

This work helps regulated parties **find** sanctioned counterparties.

Do not build, and do not help design, features whose purpose is to test whether a name
variant *evades* screening — alias generators marketed for evasion, "will this pass OFAC?"
checkers, or anything that scores names by likelihood of slipping through.

The same corpus can technically inform both questions; the difference is product surface,
positioning and customer. Keep the surface defensive. If a request drifts this way, flag it
rather than quietly complying. Full posture: [`docs/legal-and-ethics.md`](docs/legal-and-ethics.md).

## 6. Repo conventions

- **Python**, with boring, inspectable dependencies over heavy frameworks — this code has
  to be auditable by a stranger.
- **Results are committed as data, not pasted into prose.** The docs reference
  `benchmark/results/`; they do not restate it by hand.
- **Test the accuracy, not just the code.** Regression tests include benchmark accuracy
  gates, so a refactor that quietly costs 2 points of recall fails CI. Lowering a floor to
  make CI pass defeats the entire purpose of the gate.
- **Commit messages** state what changed and why — imperative, specific, no filler.
- Branch for anything non-trivial; PR into `main`.

## 7. Domain quick reference

Enough to not say something naive. Full detail in [`docs/domain-notes.md`](docs/domain-notes.md).

- **Screening** = matching a counterparty against watchlists (OFAC SDN, EU consolidated,
  UK OFSI, UN, BIS Entity List, and others).
- **The operational pain is false positives.** Screening alert volumes are overwhelmingly
  false hits, each requiring human disposition. `[VERIFY]` any specific rate before quoting
  one.
- **Why Cyrillic breaks matchers:** no single romanisation standard (ISO 9, GOST 7.79,
  BGN/PCGN, ALA-LC, ICAO 9303, ad-hoc); Kazakh is mid-transition between Cyrillic and
  several competing Latin alphabets; patronymics appear, vanish, or abbreviate; surnames
  are gendered (`Иванов`/`Иванова`); Turkic patronymic particles (`-ұлы`/`-uly`,
  `-қызы`/`-kyzy`) coexist with Russified `-ович`/`-овна`.
- **Watchlists are mostly Latin-script**, so the common case is matching a Cyrillic source
  record against a Latin list entry — a cross-script problem, not a fuzzy-string problem.
- **Phonetic algorithms are English-tuned.** Soundex and Metaphone are close to useless
  here; treat any library defaulting to them as a red flag. This is measured, not asserted:
  `icu+soundex` reaches 0.3035 recall at 1% FPR.

## 8. Working style

- Prefer the smallest change that answers the open question.
- When a decision has real trade-offs, state the recommendation and the reason, then
  proceed — don't produce an options menu.
- Flag it plainly when the evidence points against the thesis. This benchmark exists
  because it was able to kill a project cheaply; anyone who rationalises past a bad result
  has destroyed the only safeguard.
