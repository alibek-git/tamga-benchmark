"""Metrics for the P0 benchmark. All three, never one alone (`benchmark/README.md`).

## Recall at a fixed false-positive rate

The number a compliance buyer cares about, because FPR *is* their labour cost and recall
is their regulatory risk. Computed by sweeping every distinct score as a threshold and
taking the highest recall achievable while FPR stays at or below the target.

**At pilot size, 0.1% FPR is not measurable, and this module refuses to pretend it is.**
With `n` negatives the smallest non-zero FPR is `1/n`; with 230 negatives that is 0.43%,
so no threshold exists whose FPR falls between 0 and 0.43%. Asking for recall at 0.1% FPR
returns `null` together with the reason, rather than the recall at zero false positives
relabelled — those are different operating points and conflating them would overstate what
the pilot measured. `recall_at_zero_fp` is reported separately as the strictest operating
point that *is* resolvable, with a Clopper-Pearson upper bound on the FPR it corresponds
to.

## F1

Maximum F1 over the same threshold sweep — **oracle-tuned**, i.e. the threshold is chosen
with knowledge of the labels. That flatters every baseline, which is the right direction of
bias for a test whose purpose is to kill our own thesis: if a baseline cannot clear the
gate even when handed its best possible threshold, the failure is real.

## Error taxonomy

Per-phenomenon recall at the corpus-level operating point, so failures can be attributed
to nameable linguistic causes instead of an aggregate score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Curve:
    """A threshold sweep over one baseline's scores."""
    thresholds: list[float] = field(default_factory=list)
    tp: list[int] = field(default_factory=list)
    fp: list[int] = field(default_factory=list)
    fn: list[int] = field(default_factory=list)
    tn: list[int] = field(default_factory=list)


def clopper_pearson_upper(successes: int, trials: int, confidence: float = 0.95) -> float:
    """Upper bound of a binomial proportion. Used to state what an observed zero false
    positives actually licenses: with 230 negatives and 0 observed, the true FPR could
    still be as high as ~1.3%, and saying "0% FPR" would be a claim the data cannot carry.
    """
    if trials == 0:
        return 1.0
    if successes >= trials:
        return 1.0
    # Invert the beta distribution via bisection: P(X <= successes | p) = 1 - confidence.
    alpha = 1.0 - confidence
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        cdf = sum(
            math.comb(trials, k) * mid**k * (1 - mid)**(trials - k)
            for k in range(successes + 1)
        )
        if cdf > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def build_curve(scores: list[float], labels: list[bool]) -> Curve:
    """Sweep every distinct score as a `>=` threshold."""
    curve = Curve()
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    candidates = sorted({*scores, 0.0, 1.0 + 1e-9}, reverse=True)
    for threshold in candidates:
        tp = fp = 0
        for score, label in zip(scores, labels):
            if score >= threshold:
                if label:
                    tp += 1
                else:
                    fp += 1
        curve.thresholds.append(threshold)
        curve.tp.append(tp)
        curve.fp.append(fp)
        curve.fn.append(n_pos - tp)
        curve.tn.append(n_neg - fp)
    return curve


def recall_at_fpr(curve: Curve, target_fpr: float, n_neg: int) -> dict:
    """Highest recall achievable with FPR <= target.

    Returns `resolvable: False` when the corpus is too small for the target to correspond
    to any achievable threshold, rather than silently returning the nearest one.
    """
    n_pos = curve.tp[0] + curve.fn[0]
    min_nonzero_fpr = 1.0 / n_neg if n_neg else 1.0

    if target_fpr < min_nonzero_fpr and target_fpr > 0:
        allowed_fp = int(math.floor(target_fpr * n_neg))
        if allowed_fp == 0:
            return {
                "resolvable": False,
                "reason": f"target FPR {target_fpr:.4f} is below the corpus resolution: "
                          f"with {n_neg} negatives the smallest non-zero FPR is "
                          f"{min_nonzero_fpr:.4f} ({1}/{n_neg}). No threshold has an FPR "
                          f"strictly between 0 and {min_nonzero_fpr:.4f}.",
                "negatives_required_for_resolution": math.ceil(1.0 / target_fpr),
                "recall": None,
            }

    allowed_fp = int(math.floor(target_fpr * n_neg))
    best = None
    for i in range(len(curve.thresholds)):
        if curve.fp[i] <= allowed_fp:
            recall = curve.tp[i] / n_pos if n_pos else 0.0
            if best is None or recall > best["recall"]:
                best = {
                    "resolvable": True,
                    "recall": recall,
                    "threshold": curve.thresholds[i],
                    "false_positives": curve.fp[i],
                    "true_positives": curve.tp[i],
                    "achieved_fpr": curve.fp[i] / n_neg if n_neg else 0.0,
                    "allowed_false_positives": allowed_fp,
                }
    if best is None:
        return {"resolvable": True, "recall": 0.0, "threshold": None,
                "false_positives": 0, "true_positives": 0, "achieved_fpr": 0.0,
                "allowed_false_positives": allowed_fp}
    return best


def recall_at_zero_fp(curve: Curve, n_neg: int) -> dict:
    """Recall at the strictest operating point the corpus can actually resolve."""
    n_pos = curve.tp[0] + curve.fn[0]
    best = {"recall": 0.0, "threshold": None, "true_positives": 0}
    for i in range(len(curve.thresholds)):
        if curve.fp[i] == 0:
            recall = curve.tp[i] / n_pos if n_pos else 0.0
            if recall > best["recall"]:
                best = {"recall": recall, "threshold": curve.thresholds[i],
                        "true_positives": curve.tp[i]}
    best["observed_fpr"] = 0.0
    best["fpr_95pct_upper_bound"] = clopper_pearson_upper(0, n_neg)
    best["note"] = ("zero observed false positives does not mean zero FPR; the upper "
                    "bound is what this corpus size licenses")
    return best


def fpr_at_recall(curve: Curve, target_recall: float, n_neg: int) -> dict:
    """Lowest FPR at which recall reaches the target — the mirror of `recall_at_fpr`.

    This is the metric that actually tests the commercial thesis. The claim in
    `README.md` is that vendors absorb transliteration variance *by loosening their fuzzy
    threshold*, and thereby flood compliance teams with false positives. Recall at a fixed
    FPR cannot test that claim: it pins FPR low and so reports good precision by
    construction. Asking the question the other way round — to catch 95% of true hits,
    how many false positives must be accepted? — measures the trade the thesis alleges.

    `alerts_per_true_hit` is the same figure in the buyer's units: how many alerts an
    analyst dispositions for each real one, at the stated recall. `CLAUDE.md` §4 requires
    precision to be quoted at a stated recall level, never alone.
    """
    n_pos = curve.tp[0] + curve.fn[0]
    if n_pos == 0:
        return {"reachable": False, "reason": "no positives in slice"}

    best = None
    for i in range(len(curve.thresholds)):
        recall = curve.tp[i] / n_pos
        if recall < target_recall:
            continue
        fpr = curve.fp[i] / n_neg if n_neg else 0.0
        if best is None or fpr < best["false_positive_rate"]:
            tp, fp = curve.tp[i], curve.fp[i]
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            best = {
                "reachable": True,
                "target_recall": target_recall,
                "achieved_recall": recall,
                "false_positive_rate": fpr,
                "false_positives": fp,
                "precision": precision,
                "alerts_per_true_hit": (tp + fp) / tp if tp else None,
                "threshold": curve.thresholds[i],
            }
    if best is None:
        return {"reachable": False, "target_recall": target_recall,
                "reason": f"recall {target_recall} is not attainable at any threshold; "
                          f"maximum recall is "
                          f"{max(curve.tp) / n_pos:.4f}"}
    return best


def max_f1(curve: Curve) -> dict:
    """Maximum F1 over the sweep. Oracle-tuned — see module docstring."""
    n_pos = curve.tp[0] + curve.fn[0]
    best = {"f1": 0.0, "threshold": None, "precision": 0.0, "recall": 0.0}
    for i in range(len(curve.thresholds)):
        tp, fp, fn = curve.tp[i], curve.fp[i], curve.fn[i]
        if tp == 0:
            continue
        precision = tp / (tp + fp)
        recall = tp / n_pos if n_pos else 0.0
        if precision + recall == 0:
            continue
        f1 = 2 * precision * recall / (precision + recall)
        if f1 > best["f1"]:
            best = {"f1": f1, "threshold": curve.thresholds[i],
                    "precision": precision, "recall": recall,
                    "true_positives": tp, "false_positives": fp, "false_negatives": fn}
    return best


def roc_auc(scores: list[float], labels: list[bool]) -> float:
    """Threshold-free ranking quality, via the Mann-Whitney statistic with tie handling."""
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return float("nan")
    ranked = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(ranked):
        j = i
        while j + 1 < len(ranked) and scores[ranked[j + 1]] == scores[ranked[i]]:
            j += 1
        average = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[ranked[k]] = average
        i = j + 1
    rank_sum = sum(r for r, y in zip(ranks, labels) if y)
    n_pos, n_neg = len(pos), len(neg)
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def evaluate(scores: list[float], labels: list[bool], n_neg: int | None = None) -> dict:
    """Full metric set for one baseline on one slice."""
    n_pos = sum(labels)
    n_neg = n_neg if n_neg is not None else len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return {"n_positive": n_pos, "n_negative": n_neg,
                "note": "slice lacks both classes; metrics undefined"}
    curve = build_curve(scores, labels)

    # The F1 floor of a near-balanced corpus. Calling every pair a match scores
    # 2P/(P+1) with P = n_pos/(n_pos+n_neg), which is 0.667 at 50/50 — so max-F1 is not
    # zero-based and a gate expressed in raw F1 has far less headroom than it appears to.
    trivial_precision = n_pos / (n_pos + n_neg)
    trivial_f1 = 2 * trivial_precision / (trivial_precision + 1.0)

    return {
        "n_positive": n_pos,
        "n_negative": n_neg,
        "recall_at_1pct_fpr": recall_at_fpr(curve, 0.01, n_neg),
        "recall_at_0_1pct_fpr": recall_at_fpr(curve, 0.001, n_neg),
        "recall_at_zero_fp": recall_at_zero_fp(curve, n_neg),
        "fpr_at_95pct_recall": fpr_at_recall(curve, 0.95, n_neg),
        "fpr_at_99pct_recall": fpr_at_recall(curve, 0.99, n_neg),
        "fpr_at_90pct_recall": fpr_at_recall(curve, 0.90, n_neg),
        "max_f1": max_f1(curve),
        "trivial_all_positive_f1": trivial_f1,
        "max_f1_above_trivial": max_f1(curve)["f1"] - trivial_f1,
        "roc_auc": roc_auc(scores, labels),
    }


def per_phenomenon_recall(records: list[dict], scores: list[float],
                          threshold: float) -> dict:
    """Recall per phenomenon tag at a fixed threshold, over positives only.

    The diagnostic output. A phenomenon is only reported when it has at least
    `MIN_PHENOMENON_SUPPORT` positives, because recall over three pairs is noise being
    presented as a finding.
    """
    from collections import defaultdict
    hits: dict[str, int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)
    for record, score in zip(records, scores):
        if not record["same_entity"]:
            continue
        for tag in record["phenomena"]:
            totals[tag] += 1
            if score >= threshold:
                hits[tag] += 1
    return {
        tag: {
            "recall": hits[tag] / totals[tag],
            "n": totals[tag],
            "missed": totals[tag] - hits[tag],
            "low_support": totals[tag] < MIN_PHENOMENON_SUPPORT,
        }
        for tag in sorted(totals)
    }


def per_phenomenon_false_positive_rate(records: list[dict], scores: list[float],
                                       threshold: float) -> dict:
    """FPR per phenomenon tag at a fixed threshold, over negatives only.

    The other half of the taxonomy: which hard-negative constructions actually generate
    the false positives a compliance team would have to clear by hand.
    """
    from collections import defaultdict
    hits: dict[str, int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)
    for record, score in zip(records, scores):
        if record["same_entity"]:
            continue
        for tag in record["phenomena"]:
            totals[tag] += 1
            if score >= threshold:
                hits[tag] += 1
    return {
        tag: {
            "false_positive_rate": hits[tag] / totals[tag],
            "n": totals[tag],
            "false_positives": hits[tag],
            "low_support": totals[tag] < MIN_PHENOMENON_SUPPORT,
        }
        for tag in sorted(totals)
    }


MIN_PHENOMENON_SUPPORT = 8
