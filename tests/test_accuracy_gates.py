"""Layer 3 — accuracy gates. The layer `tests/README.md` calls the one that matters.

`CLAUDE.md` §6: "Regression tests must include benchmark accuracy gates, so a refactor
that quietly costs 2 points of recall fails CI."

These tests **recompute** baseline scores from the committed corpus and compare them
against floors in `accuracy_gates.json`. They do not read the stored `metrics.json`, since
that would only prove a JSON file is internally consistent — it would not catch a change
to `translit.py` or `phenomena.py` that quietly degraded matching.

Only deterministic, dependency-light baselines are gated; see `make_gates.py` for why the
embedding and LLM baselines are measured but not used as floors.
"""

from __future__ import annotations

import pytest

from harness import baselines as B
from harness import metrics as M


@pytest.fixture(scope="module")
def scored(corpus):
    """Recompute every gateable baseline over the corpus. ~5s for 5k pairs."""
    core = {b.name: b for b in B.CORE_BASELINES}
    noms, diag = B.nomenklatura_baselines()
    if diag.get("available"):
        core.update({b.name: b for b in noms})
    out = {}
    for name, baseline in core.items():
        out[name] = [baseline.score(r["name_a"], r["name_b"], r) for r in corpus]
    return out


def slice_indices(corpus, slice_name: str) -> list[int]:
    if slice_name == "full":
        return list(range(len(corpus)))
    return [i for i, r in enumerate(corpus)
            if r["same_entity"] or r["difficulty"] == "hard"]


def evaluate(corpus, scores: list[float], slice_name: str) -> dict:
    indices = slice_indices(corpus, slice_name)
    labels = [corpus[i]["same_entity"] for i in indices]
    return M.evaluate([scores[i] for i in indices], labels,
                      n_neg=sum(1 for y in labels if not y))


def gate_cases(gates: dict) -> list[tuple[str, str, str, float]]:
    cases = []
    for slice_name, per_baseline in gates["slices"].items():
        for baseline, entries in per_baseline.items():
            for metric, bounds in entries.items():
                cases.append((slice_name, baseline, metric, bounds["floor"]))
    return cases


def test_gates_file_matches_the_committed_corpus(gates, manifest) -> None:
    """A floor measured against a different corpus is not a floor. If the corpus is
    rebuilt, the gates must be regenerated deliberately."""
    assert gates["dataset_sha256"] == manifest["sha256_of_corpus"], (
        "accuracy_gates.json was measured against a different corpus; regenerate with "
        "benchmark/harness/make_gates.py"
    )


def test_gate_covers_the_serious_open_source_incumbent(gates) -> None:
    """`nomenklatura/logic-v2` is the strongest baseline measured and the one any engine
    claim will be judged against, so it must never silently drop out of the gate."""
    for slice_name, per_baseline in gates["slices"].items():
        assert "nomenklatura/logic-v2" in per_baseline, slice_name


def test_no_regression_against_recorded_floors(corpus, gates, scored) -> None:
    """The gate itself. Reports every breach at once rather than failing on the first."""
    failures: list[str] = []
    checked = 0

    cache: dict[tuple[str, str], dict] = {}
    for slice_name, baseline, metric, floor in gate_cases(gates):
        if baseline not in scored:
            failures.append(f"{baseline}: gated but not runnable in this environment")
            continue
        key = (baseline, slice_name)
        if key not in cache:
            cache[key] = evaluate(corpus, scored[baseline], slice_name)
        data = cache[key]

        if metric == "recall_at_1pct_fpr":
            value = data["recall_at_1pct_fpr"].get("recall") or 0.0
        elif metric == "max_f1":
            value = data["max_f1"]["f1"]
        elif metric == "roc_auc":
            value = data["roc_auc"]
        else:
            continue

        checked += 1
        if value < floor:
            failures.append(
                f"{slice_name}/{baseline}/{metric}: {value:.4f} < floor {floor:.4f} "
                f"(regression of {floor - value:.4f})"
            )

    assert checked > 0, "no gates were evaluated"
    assert not failures, "accuracy regression:\n  " + "\n  ".join(failures)


def test_deterministic_gate_verdict_is_unchanged(corpus, gates, scored) -> None:
    """The gate verdict restricted to auditable baselines — the part CI can recompute.

    The *overall* P0 verdict now rests on an LLM judge, which is non-deterministic and
    credential-gated, so it cannot be recomputed here; `test_overall_gate_verdict_matches
    _the_measurement` checks that one against the committed run instead.
    """
    hard = [(name, evaluate(corpus, s, "hard-negatives-only"))
            for name, s in scored.items()]
    best_f1 = max(d["max_f1"]["f1"] for _, d in hard)
    best_recall = max((d["recall_at_1pct_fpr"].get("recall") or 0.0) for _, d in hard)

    kill = best_f1 >= 0.93 and best_recall >= 0.95
    verdict = "KILL" if kill else ("GO" if best_f1 <= 0.85 else "IN-BETWEEN")
    expected = gates["gate_verdict_deterministic_only"]["verdict"]
    assert verdict == expected, (
        f"deterministic gate verdict moved to {verdict} (best max-F1 {best_f1:.4f}, "
        f"best recall @1% FPR {best_recall:.4f}). Update PLAN.md and regenerate."
    )


def test_overall_gate_verdict_matches_the_measurement(gates, metrics) -> None:
    """The decision variable for the whole project, asserted against the committed run.

    It is KILL because a frontier LLM judge clears both criteria. That verdict is not
    reproducible in CI by construction — which is itself part of why an LLM cannot be the
    scorer in an audited pipeline (`CLAUDE.md` §4) — so it is pinned to the measurement.
    """
    recorded = metrics["slices"]["hard-negatives-only"]["_gate_verdict"]["verdict"]
    assert recorded == gates["gate_verdict"]["verdict"], (
        f"metrics.json says {recorded}, accuracy_gates.json says "
        f"{gates['gate_verdict']['verdict']}; regenerate the gates deliberately"
    )


def test_english_phonetics_still_fail(corpus, scored) -> None:
    """A published finding, pinned as a test: Soundex has no usable high-precision
    operating point on this data (`docs/domain-notes.md` §7). If a change ever makes it
    work, that is a discovery about the corpus, not a fix.
    """
    data = evaluate(corpus, scored["icu+soundex"], "hard-negatives-only")
    assert data["roc_auc"] < 0.80, data["roc_auc"]


def test_exact_match_floor_does_not_discriminate(corpus, scored) -> None:
    """Exact matching after Unicode normalisation should never fire on a cross-script
    pair, so its ROC-AUC must sit at chance. If it rises, the corpus has acquired
    trivially-matching pairs."""
    data = evaluate(corpus, scored["exact-match-nfkc"], "full")
    assert data["roc_auc"] == pytest.approx(0.5, abs=0.02), data["roc_auc"]
