"""Commodity baselines for the P0 kill test.

Every baseline listed in `PLAN.md` (P0), including the ones expected to fail. "Soundex
fails on Cyrillic" is a finding worth publishing, so the weak entries are run and reported
exactly like the strong ones.

**This module contains no Tamga engine.** P0 exists to decide whether an engine is worth
building (`CLAUDE.md` §2), so the harness deliberately implements only third-party or
textbook methods. The multi-system transliteration lattice is P1 work and is not here.

Each baseline returns a score in `[0, 1]`; higher means more likely to be the same entity.
Scores are only ever compared *within* a baseline, via a threshold sweep, so different
baselines' scales need not be commensurable.

## Two implementation notes that materially affect the numbers

**Phonetic baselines are given a transliteration first.** Soundex and Double Metaphone
accept ASCII letters only; handed Cyrillic they would return an empty or garbage code and
score zero on everything, which measures nothing but an encoding mismatch. So they are run
as *ICU transliteration → phonetic key*, which is the strongest honest form of the method
and the only one a real implementation would ship. They are labelled accordingly.

**nomenklatura requires a distinct entity `id` per comparison.** Its name analysis is
cached per entity id, so reusing ids returns the first pair's verdict for every subsequent
pair. Left uncorrected this made `logic-v2` — the serious open-source incumbent, and the
most important single baseline here — emit one constant score for the entire corpus.
Every proxy below gets a fresh id from a counter.
"""

from __future__ import annotations

import itertools
import unicodedata
from typing import Callable

import icu
import jellyfish
import rapidfuzz.distance.JaroWinkler as _jw
import rapidfuzz.distance.Levenshtein as _lev
from metaphone import doublemetaphone

# --------------------------------------------------------------------------------------
# normalisation helpers
# --------------------------------------------------------------------------------------

_TRANSLIT_BASIC = icu.Transliterator.createInstance("Cyrillic-Latin")
_TRANSLIT_ASCII = icu.Transliterator.createFromRules(
    "tamga-bench-ascii",
    ":: Any-Latin; :: NFD; :: [:Nonspacing Mark:] Remove; :: NFC; :: Lower;",
    icu.UTransDirection.FORWARD,
)


def nfkc_fold(text: str) -> str:
    """Unicode normalisation + case fold + whitespace collapse. The floor baseline's
    entire preprocessing, and the shared preprocessing for everything else."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def icu_basic(text: str) -> str:
    """Single-pass ICU `Cyrillic-Latin`. What a naive ICU integration produces — and it
    keeps the diacritics ICU emits (`Щ`→`Ŝ`), which is why it is reported separately."""
    return " ".join(_TRANSLIT_BASIC.transliterate(text).casefold().split())


def icu_ascii(text: str) -> str:
    """ICU `Any-Latin` then combining-mark removal and case fold. What a *competent* ICU
    integration produces, and the fairest commodity cross-script normalisation."""
    return " ".join(_TRANSLIT_ASCII.transliterate(text).split())


def _tokens(text: str) -> list[str]:
    return [t for t in text.replace("-", " ").split() if t]


def _ascii_letters_only(token: str) -> str:
    return "".join(c for c in token if c.isascii() and c.isalpha())


# --------------------------------------------------------------------------------------
# string similarity
# --------------------------------------------------------------------------------------

def _jaro_winkler(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return float(_jw.similarity(a, b))


def _levenshtein_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return float(_lev.normalized_similarity(a, b))


def _token_set_similarity(a: str, b: str, fn: Callable[[str, str], float]) -> float:
    """Order-insensitive similarity: greedily pair the most similar tokens.

    Needed because name order is unstable across CIS records
    (`docs/domain-notes.md` §4), and a raw whole-string comparison would score a
    surname-first record against a given-first record as a mismatch for a reason that has
    nothing to do with transliteration.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    if len(ta) > len(tb):
        ta, tb = tb, ta
    used: set[int] = set()
    total = 0.0
    for x in ta:
        best, best_j = 0.0, None
        for j, y in enumerate(tb):
            if j in used:
                continue
            s = fn(x, y)
            if s > best:
                best, best_j = s, j
        if best_j is not None:
            used.add(best_j)
        total += best
    # Penalise unmatched tokens on the longer side, so a one-token query does not score
    # 1.0 against a three-token list entry that happens to contain it.
    return total / len(tb)


# --------------------------------------------------------------------------------------
# phonetic keys
# --------------------------------------------------------------------------------------

def _soundex_codes(text: str) -> set[str]:
    codes = set()
    for token in _tokens(text):
        ascii_token = _ascii_letters_only(token)
        if not ascii_token:
            continue
        try:
            codes.add(jellyfish.soundex(ascii_token))
        except Exception:  # noqa: BLE001 - a token the encoder rejects contributes nothing
            continue
    return codes


def _metaphone_codes(text: str) -> set[str]:
    codes = set()
    for token in _tokens(text):
        ascii_token = _ascii_letters_only(token)
        if not ascii_token:
            continue
        primary, secondary = doublemetaphone(ascii_token)
        if primary:
            codes.add(primary)
        if secondary:
            codes.add(secondary)
    return codes


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------------------
# baseline registry
# --------------------------------------------------------------------------------------

class Baseline:
    def __init__(self, name: str, family: str, fn: Callable[[str, str, dict], float],
                 deterministic: bool = True, notes: str = "",
                 prepare: Callable[[list[dict]], dict] | None = None) -> None:
        self.name = name
        self.family = family
        self.fn = fn
        self.deterministic = deterministic
        self.notes = notes
        # Optional batch hook. Baselines that call a network API implement this to fetch
        # all verdicts concurrently before per-pair scoring; local baselines leave it None.
        self.prepare = prepare

    def score(self, a: str, b: str, record: dict) -> float:
        value = self.fn(a, b, record)
        return max(0.0, min(1.0, float(value)))


def _exact(a: str, b: str, _: dict) -> float:
    return 1.0 if nfkc_fold(a) == nfkc_fold(b) else 0.0


def _raw_jw(a: str, b: str, _: dict) -> float:
    return _token_set_similarity(nfkc_fold(a), nfkc_fold(b), _jaro_winkler)


def _raw_lev(a: str, b: str, _: dict) -> float:
    return _token_set_similarity(nfkc_fold(a), nfkc_fold(b), _levenshtein_ratio)


def _icu_basic_jw(a: str, b: str, _: dict) -> float:
    return _token_set_similarity(icu_basic(a), icu_basic(b), _jaro_winkler)


def _icu_ascii_jw(a: str, b: str, _: dict) -> float:
    return _token_set_similarity(icu_ascii(a), icu_ascii(b), _jaro_winkler)


def _icu_ascii_lev(a: str, b: str, _: dict) -> float:
    return _token_set_similarity(icu_ascii(a), icu_ascii(b), _levenshtein_ratio)


def _icu_soundex(a: str, b: str, _: dict) -> float:
    return _jaccard(_soundex_codes(icu_ascii(a)), _soundex_codes(icu_ascii(b)))


def _icu_metaphone(a: str, b: str, _: dict) -> float:
    return _jaccard(_metaphone_codes(icu_ascii(a)), _metaphone_codes(icu_ascii(b)))


CORE_BASELINES = [
    Baseline("exact-match-nfkc", "floor", _exact,
             notes="NFKC + casefold + whitespace collapse, then equality. The floor."),
    Baseline("jaro-winkler-raw", "naive-fuzzy", _raw_jw,
             notes="Jaro-Winkler on raw strings, token-set aligned. What a naive "
                   "implementation does; across scripts it has almost nothing to work "
                   "with."),
    Baseline("levenshtein-raw", "naive-fuzzy", _raw_lev,
             notes="Normalised Levenshtein on raw strings, token-set aligned."),
    Baseline("icu-cyrl-latn+jaro-winkler", "icu-translit", _icu_basic_jw,
             notes="Single-pass ICU Cyrillic-Latin, diacritics retained (Щ->Ŝ), then "
                   "Jaro-Winkler. A naive ICU integration."),
    Baseline("icu-any-latin-ascii+jaro-winkler", "icu-translit", _icu_ascii_jw,
             notes="ICU Any-Latin + combining-mark removal + casefold, then "
                   "Jaro-Winkler. What a competent ICU integration does, and the "
                   "commodity method the thesis has to beat."),
    Baseline("icu-any-latin-ascii+levenshtein", "icu-translit", _icu_ascii_lev,
             notes="As above with normalised Levenshtein."),
    Baseline("icu+soundex", "english-phonetic", _icu_soundex,
             notes="ICU transliteration then Soundex, Jaccard over token code sets. "
                   "Transliterated first because Soundex takes ASCII only; this is the "
                   "strongest honest form of the method."),
    Baseline("icu+double-metaphone", "english-phonetic", _icu_metaphone,
             notes="ICU transliteration then Double Metaphone (both codes), Jaccard over "
                   "token code sets."),
]


# --------------------------------------------------------------------------------------
# nomenklatura (OpenSanctions)
# --------------------------------------------------------------------------------------

def nomenklatura_baselines() -> tuple[list[Baseline], dict]:
    """The OpenSanctions matchers. Returns `(baselines, diagnostics)`."""
    try:
        from followthemoney import model
        from nomenklatura.matching import ALGORITHMS
        import importlib.metadata as md
        version = md.version("nomenklatura")
    except Exception as exc:  # noqa: BLE001
        return [], {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    counter = itertools.count()

    def make(algo):
        config = algo.default_config()

        def score(a: str, b: str, record: dict) -> float:
            schema = "Organization" if record.get("entity_type") == "organisation" \
                else "Person"
            # A fresh id per proxy: nomenklatura caches name analysis per entity id, and
            # reusing ids makes every pair return the first pair's score.
            qa = model.get_proxy({"id": f"q{next(counter)}", "schema": schema,
                                  "properties": {"name": [a]}})
            qb = model.get_proxy({"id": f"r{next(counter)}", "schema": schema,
                                  "properties": {"name": [b]}})
            try:
                return float(algo.compare(qa, qb, config).score)
            except Exception:  # noqa: BLE001
                return 0.0

        return score

    out: list[Baseline] = []
    for algo in ALGORITHMS:
        out.append(Baseline(
            f"nomenklatura/{algo.NAME}", "opensanctions", make(algo),
            deterministic=algo.NAME != "er-unstable",
            notes=(algo.__doc__ or "").strip().split("\n")[0][:200],
        ))
    return out, {"available": True, "version": version,
                 "algorithms": [a.NAME for a in ALGORITHMS]}


# --------------------------------------------------------------------------------------
# multilingual embeddings
# --------------------------------------------------------------------------------------

# Pinned so a later model release cannot silently change published scores
# (`CLAUDE.md` §4 — no silent model swaps).
EMBEDDING_MODELS = (
    ("LaBSE", "sentence-transformers/LaBSE", ""),
    ("multilingual-e5-base", "intfloat/multilingual-e5-base", "query: "),
)


def embedding_baselines(cache_dir: str | None = None) -> tuple[list[Baseline], dict]:
    """Cosine similarity between sentence-embedding vectors of the two names.

    Included because "just use a multilingual embedding model" is a real answer a buyer
    will raise. Note the recorded caveat rather than the score alone: these models are
    trained for semantic similarity of text, not identity of referents, and they are not
    version-stable, which disqualifies them as a sole scorer in an audited pipeline
    (`docs/domain-notes.md` §7, `CLAUDE.md` §4).
    """
    diagnostics: dict = {"available": False, "models": {}}
    try:
        import importlib.metadata as md
        import torch
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # noqa: BLE001
        diagnostics["reason"] = f"{type(exc).__name__}: {exc}"
        return [], diagnostics

    torch.manual_seed(0)
    out: list[Baseline] = []

    for label, model_id, prefix in EMBEDDING_MODELS:
        try:
            model = SentenceTransformer(model_id, cache_folder=cache_dir,
                                        device="cpu")
            model.eval()
        except Exception as exc:  # noqa: BLE001
            diagnostics["models"][label] = {"loaded": False,
                                           "reason": f"{type(exc).__name__}: {exc}"}
            continue

        cache: dict[str, object] = {}

        def score(a: str, b: str, _: dict, _model=model, _prefix=prefix,
                  _cache=cache) -> float:
            import torch as _torch
            keys = [f"{_prefix}{a}", f"{_prefix}{b}"]
            missing = [k for k in keys if k not in _cache]
            if missing:
                with _torch.no_grad():
                    vectors = _model.encode(missing, convert_to_tensor=True,
                                            normalize_embeddings=True,
                                            show_progress_bar=False)
                for k, v in zip(missing, vectors):
                    _cache[k] = v
            va, vb = _cache[keys[0]], _cache[keys[1]]
            cosine = float(_torch.dot(va, vb).item())
            # Map [-1, 1] onto [0, 1]; monotonic, so it cannot change the ROC.
            return (cosine + 1.0) / 2.0

        out.append(Baseline(
            f"embedding/{label}", "embedding", score, deterministic=False,
            notes=f"cosine similarity of {model_id} embeddings"
                  + (f", '{prefix.strip()}' prefix per the model's convention"
                     if prefix else "")
                  + "; trained for semantic similarity, not entity identity",
        ))
        diagnostics["models"][label] = {"loaded": True, "model_id": model_id}

    diagnostics["available"] = bool(out)
    try:
        diagnostics["sentence_transformers_version"] = md.version(
            "sentence-transformers")
        diagnostics["torch_version"] = md.version("torch")
    except Exception:  # noqa: BLE001
        pass
    return out, diagnostics


# --------------------------------------------------------------------------------------
# LLM as judge
# --------------------------------------------------------------------------------------

LLM_JUDGE_SPEC = {
    "baseline": "llm-judge",
    "why_in_the_list": "'Just use an LLM' is the answer a buyer will raise, and it is "
                       "the honest baseline to beat as well as the cost ceiling "
                       "(PLAN.md P0, docs/domain-notes.md §7).",
    "requirement": "An Anthropic API credential in the environment "
                   "(ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN).",
}

# Two frontier models, because "just use a *bigger* LLM" is a separate claim from "just
# use an LLM" and only measurement separates them. If the larger model closes the gap the
# smaller one leaves, that is a genuine threat to this project's premise.
LLM_JUDGE_MODELS = ("claude-sonnet-5", "claude-opus-5")

LLM_JUDGE_PROMPT = (
    "You are screening a counterparty name against a sanctions watchlist entry.\n"
    "Do these two names refer to the SAME real-world entity?\n\n"
    "Name A: {a}\nName B: {b}\n\n"
    "Answer with a probability between 0.00 and 1.00 that they are the same entity. "
    "Reply with the number only."
)

LLM_MAX_WORKERS = 16
LLM_ATTEMPTS = 4

# The Claude 5 models emit a `thinking` block before any text, and it is on by default.
# With a small budget the whole allowance is consumed by thinking, the response carries no
# text block at all, and the answer is unrecoverable — at `max_tokens=8` that happened on
# 2 of 12 pairs. Crucially the failures were **correlated with difficulty**: harder pairs
# think longer, so a tight budget silently scored the hardest true pairs 0.0 and would have
# understated this baseline in precisely the direction that flatters this project's thesis.
#
# Thinking is therefore left enabled — the model's default configuration, and the strongest
# honest form of "just use an LLM" — with a budget large enough to finish. Output-token
# usage is recorded so the cost ceiling in `PLAN.md` is a measured number rather than a
# guess. Disabling thinking answers these pairs about as well for ~20× fewer output tokens,
# which is worth knowing but is not the default a buyer would hit.
LLM_MAX_TOKENS = 1024
LLM_MAX_TOKENS_RETRY = 4096


def _extract_text(resp) -> str:
    """First text block of a response.

    Not `resp.content[0].text`: a response may lead with a non-text block, and indexing
    blindly raised `AttributeError: 'NoneType' object has no attribute 'strip'` on a real
    call during development.
    """
    for block in getattr(resp, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            return text
    return ""


def llm_judge_baselines(cache_dir=None) -> tuple[list[Baseline], dict]:
    """Frontier-LLM judges. Returns no baselines when no credential is available.

    Reports unavailability rather than substituting an estimate (`CLAUDE.md` §3 — never
    write a number that wasn't produced by a run).

    ## Why these scores are not reproducible, and why that is the finding

    `docs/domain-notes.md` §7 argues an LLM judge "cannot be version-frozen for replay".
    That is now concrete rather than theoretical: the Claude 5 models **reject the
    `temperature` parameter outright** — it is deprecated for that family — so this
    baseline cannot even be pinned to greedy decoding, let alone replayed. Raw responses
    are therefore cached to disk so a *published figure* stays auditable, but the run
    itself is not repeatable. That disqualifies the method as a sole scorer in an audited
    pipeline (`CLAUDE.md` §4), independently of how accurate it is.
    """
    import json
    import os
    import pathlib
    import time
    from concurrent.futures import ThreadPoolExecutor

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return [], {**LLM_JUDGE_SPEC, "available": False,
                    "reason": "no API credential in the environment",
                    "result": "NOT RUN — reported as TBD, not estimated"}
    try:
        import anthropic
    except Exception as exc:  # noqa: BLE001
        return [], {**LLM_JUDGE_SPEC, "available": False,
                    "reason": f"{type(exc).__name__}: {exc}"}

    client = anthropic.Anthropic()
    usage: dict = {}
    out: list[Baseline] = []

    for model_id in LLM_JUDGE_MODELS:
        store = pathlib.Path(cache_dir or ".") / f"llm-judge-{model_id}.jsonl"
        cache: dict[str, float] = {}
        raw: dict[str, str] = {}
        if store.exists():
            for line in store.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                cache[rec["key"]] = rec["score"]
                raw[rec["key"]] = rec.get("raw", "")

        counters = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "errors": 0,
                    "unparseable": 0, "truncated_retried": 0, "cached": 0}

        def key_of(a: str, b: str) -> str:
            return f"{a}\x1f{b}"

        def ask(pair: tuple[str, str], _model=model_id, _cache=cache, _raw=raw,
                _c=counters) -> None:
            a, b = pair
            k = key_of(a, b)
            if k in _cache:
                _c["cached"] += 1
                return
            last = None
            budget = LLM_MAX_TOKENS
            for attempt in range(LLM_ATTEMPTS):
                try:
                    # No `temperature`: deprecated for the Claude 5 family and rejected
                    # with a 400. See the docstring — this is why the run is not replayable.
                    resp = client.messages.create(
                        model=_model, max_tokens=budget,
                        messages=[{"role": "user",
                                   "content": LLM_JUDGE_PROMPT.format(a=a, b=b)}],
                    )
                    text = _extract_text(resp).strip()
                    _c["calls"] += 1
                    _c["input_tokens"] += resp.usage.input_tokens
                    _c["output_tokens"] += resp.usage.output_tokens

                    # Truncated mid-thinking: raise the budget and ask again rather than
                    # recording a 0.0. Scoring a truncation as "not a match" would bias
                    # this baseline downward on the hardest pairs, which are the ones that
                    # think longest.
                    if not text and resp.stop_reason == "max_tokens":
                        _c["truncated_retried"] += 1
                        budget = LLM_MAX_TOKENS_RETRY
                        continue

                    try:
                        value = float(text.split()[0].rstrip("."))
                    except Exception:  # noqa: BLE001
                        # A refusal or an unparseable answer is recorded as such and
                        # scored 0.0. It is a real failure mode of the method, not an
                        # error to hide — and never silently treated as a confident match.
                        _c["unparseable"] += 1
                        value = 0.0
                    _cache[k] = max(0.0, min(1.0, value))
                    _raw[k] = text
                    return
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    time.sleep(2 * (attempt + 1))
            _c["errors"] += 1
            _cache[k] = 0.0
            _raw[k] = f"ERROR: {type(last).__name__}"

        # `_ask=ask` is bound as a default deliberately. Without it `prepare` resolves
        # `ask` from the enclosing scope at *call* time, and since this loop rebinds `ask`
        # once per model, every model's prepare would invoke the last model's `ask` —
        # filling one cache twice and leaving the other empty, so one baseline scored 0.0
        # on every pair. Same reason the other closures below take default arguments.
        def prepare(records: list[dict], _model=model_id, _store=store, _cache=cache,
                    _raw=raw, _c=counters, _ask=ask) -> dict:
            pairs = [(r["name_a"], r["name_b"]) for r in records]
            todo = [p for p in pairs if key_of(*p) not in _cache]
            if todo:
                with ThreadPoolExecutor(max_workers=LLM_MAX_WORKERS) as pool:
                    list(pool.map(_ask, todo))
                _store.parent.mkdir(parents=True, exist_ok=True)
                with _store.open("w", encoding="utf-8") as fh:
                    for k in sorted(_cache):
                        fh.write(json.dumps({"key": k, "score": _cache[k],
                                             "raw": _raw.get(k, "")},
                                            ensure_ascii=False) + "\n")
            # Count errored entries still sitting in the cache from *any* run, not just
            # this one. A failed call is recorded as 0.0, which reads as "confidently not a
            # match" — so an outage silently biases this baseline downward on whichever
            # pairs happened to be in flight. This happened for real: an API credit
            # exhaustion mid-run left 54 pairs scored 0.0 on one model and 0 on the other.
            # `run.py` refuses to publish a run with a non-zero count here.
            stale = sum(1 for v in _raw.values() if str(v).startswith("ERROR"))
            usage[_model] = dict(_c)
            usage[_model]["errored_entries_in_cache"] = stale
            usage[_model]["distinct_scores"] = len(set(_cache.values()))
            usage[_model]["response_cache"] = str(_store.name)
            return usage[_model]

        def score(a: str, b: str, _: dict, _cache=cache) -> float:
            return _cache.get(key_of(a, b), 0.0)

        out.append(Baseline(
            f"llm-judge/{model_id}", "llm", score, deterministic=False, prepare=prepare,
            notes=f"{model_id} asked for P(same entity); no temperature parameter "
                  f"(deprecated for this model family), so not replayable and unusable "
                  f"as a version-frozen scorer",
        ))

    return out, {**LLM_JUDGE_SPEC, "available": True, "models": list(LLM_JUDGE_MODELS),
                 "temperature": "not set — deprecated for the Claude 5 family and "
                                "rejected with HTTP 400",
                 "usage": usage}
