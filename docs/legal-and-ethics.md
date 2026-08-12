# Legal and ethical posture

Not boilerplate. A sanctions-adjacent corpus published from a jurisdiction under
enforcement scrutiny has to be scrupulous, and several of these choices constrained the
work.

**None of this is legal advice.** Anyone relying on this corpus commercially should get
review from a qualified lawyer in the relevant jurisdictions.

> Section numbering is preserved from the original private repository, because the harness
> and tests reference these sections by number. §5 covered the commercial entity structure
> of the abandoned product and is out of scope here.

---

## 1. Defensive use only — the hard line

This work helps regulated parties **find** sanctioned counterparties.

The same matching capability could, in principle, answer the inverse question — "which
spelling of my name gets past screening?" That is out of scope permanently. Concretely, do
not use this corpus to build:

- Alias or variant generators positioned around evading detection.
- "Will this name clear OFAC?" style checkers sold to screened parties.
- Any scoring surface that ranks name variants by likelihood of *not* being flagged.
- Consulting on structuring names, entities or documentation to avoid designation.

The distinguishing factor is customer and surface, not algorithm. Build for the screener,
never for the screened. This is written into [`../CLAUDE.md`](../CLAUDE.md) §5 so it
survives into every future working session on this repository.

## 2. Disclaimers

- Anything built on this benchmark is a **screening aid**. The user remains solely
  responsible for their sanctions compliance obligations and for the disposition of every
  alert.
- Position such a matcher as a **precision layer over** existing screening, never a
  replacement for it. This is both honest and the correct risk posture.
- No guarantee of completeness. Lists change continuously; matching is probabilistic.

The temptation, when promoting a result like this one, is to imply it catches what others
miss. Resist it. Someone who drops a control on the strength of a benchmark figure and then
misses a designated party has had a company-ending event, and the benchmark contributed to
it.

## 3. Publishing benchmark results responsibly

Publishing measurements of other people's matchers is the largest exposure in this work.
The rules followed here:

- **Publish results only for baselines that are legally and reproducibly runnable** —
  open-source matchers, published algorithms, standard libraries, generally available APIs.
  Full method, code and data released so anyone can re-run them.
- **Do not publish benchmark numbers for commercial screening products** obtained by
  evaluating them, particularly where terms of service prohibit benchmarking. Invite
  vendors to submit their own results instead. **No commercial screening product was
  evaluated for this benchmark.**
- Frame the work as *the problem is hard and under-measured*, not *vendor X is bad*. This
  is more accurate, more credible and harder to attack. `nomenklatura` is optimised for
  constraints the frontier models ignore — deterministic, explainable, auditable, free,
  offline — and none of the results here should be read as a criticism of its engineering.
- Correct errors publicly and promptly. The benchmark's value is entirely its credibility.

## 4. Personal data

Names, dates of birth and addresses are personal data.

- **The corpus uses public figures only** — watchlist entries and Wikidata notables — plus
  synthetic constructions. It must never become a compiled dataset of ordinary people's
  identifiers. See [`data-sources.md`](data-sources.md) §4.
- **GDPR applies** to EU data subjects. Anyone processing screening payloads with a matcher
  informed by this work needs to establish their own lawful basis — likely legitimate
  interest or legal obligation, since screening is legally mandated — and their own
  processor agreements. Same question for Kazakhstan's data-protection law; `[VERIFY]`
  current requirements including any data-localisation rule.
- **Process-and-discard by default** for any real screening payload. Retention should be
  opt-in, purpose-limited and time-bounded.
- Never train on customer data without specific written consent.

## 6. Honesty about accuracy

The accuracy claim is the whole of this artifact. Specifically:

- Never state an accuracy figure that isn't measured on the published corpus, at a stated
  recall level, with the baseline version named.
- Never quote precision without recall, or either without the operating point.
- If real data performs worse than the benchmark, say so.

[`../CLAUDE.md`](../CLAUDE.md) §3 forbids fabricated numbers anywhere in this repository for
this reason: an invented placeholder migrates into a deck, and an unsupportable accuracy
claim is both a commercial and a regulatory problem for whoever relied on it. Every figure
in [`findings.md`](findings.md) is generated from `benchmark/results/`, and a test asserts
that it cannot drift from the measurement.
