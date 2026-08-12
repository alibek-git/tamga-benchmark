"""Generate `tests/accuracy_gates.json` from a measured run.

`CLAUDE.md` §6: "Regression tests must include benchmark accuracy gates, so a refactor
that quietly costs 2 points of recall fails CI." That requires a committed floor to
compare against, and this script produces it from `metrics.json` rather than by hand.

Floors are set at `measured - TOLERANCE`. The tolerance is deliberately smaller than the
regression CLAUDE.md names: at 0.01 a two-point drop fails, while genuine noise from a
library patch release does not.

Only baselines that are **deterministic and cheap** are gated. Embedding baselines are
excluded because they are not version-stable and would require ~2 GB of model weights in
CI; `er-unstable` is excluded because its own name declares it unstable; `llm-judge` is
excluded because it is non-deterministic and credential-gated. Those still get measured,
they just cannot serve as a regression floor.

    python3 benchmark/harness/make_gates.py --version v1.0
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TOLERANCE = 0.01

# From PLAN.md's P0 gate, fixed before the work.
GATE_KILL_RECALL = 0.95

EXCLUDED_PREFIXES = ("embedding/", "llm-judge")
EXCLUDED_EXACT = ("nomenklatura/er-unstable",)

# Metrics gated per baseline. Recall at 1% FPR is the number a compliance buyer cares
# about; ROC-AUC is threshold-free so it catches ranking regressions that a single
# operating point can hide.
GATED = (
    ("recall_at_1pct_fpr", lambda d: d["recall_at_1pct_fpr"].get("recall")),
    ("max_f1", lambda d: d["max_f1"]["f1"]),
    ("roc_auc", lambda d: d["roc_auc"]),
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v1.0")
    args = ap.parse_args()

    metrics_path = ROOT / "benchmark" / "results" / args.version / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    gates: dict = {
        "dataset_version": metrics["dataset_version"],
        "dataset_sha256": metrics["dataset_sha256"],
        "measured_run_utc": metrics["run_utc"],
        "tolerance": TOLERANCE,
        "how_to_read": (
            "Each floor is the value measured at the recorded run minus the tolerance. "
            "A test fails when a current measurement drops below its floor. Regenerate "
            "with benchmark/harness/make_gates.py only when a change is understood and "
            "intended — silently lowering a floor defeats the purpose of the gate."
        ),
        "excluded_baselines": {
            "embedding/*": "not version-stable; would need ~2GB of weights in CI",
            "nomenklatura/er-unstable": "declared unstable by its own name",
            "llm-judge": "non-deterministic and credential-gated",
        },
        "slices": {},
    }

    for slice_name, per_baseline in metrics["slices"].items():
        floors: dict = {}
        for name, data in per_baseline.items():
            if name.startswith("_"):
                continue
            if name.startswith(EXCLUDED_PREFIXES) or name in EXCLUDED_EXACT:
                continue
            entry: dict = {}
            for key, getter in GATED:
                value = getter(data)
                if value is None:
                    continue
                entry[key] = {
                    "measured": round(float(value), 6),
                    "floor": round(max(0.0, float(value) - TOLERANCE), 6),
                }
            if entry:
                floors[name] = entry
        gates["slices"][slice_name] = floors

    # The corpus-level gate: the headline claim the benchmark exists to support.
    hard = metrics["slices"]["hard-negatives-only"]
    best = max(
        ((n, d) for n, d in hard.items() if not n.startswith("_")),
        key=lambda kv: kv[1]["max_f1"]["f1"],
    )
    # Two verdicts, because the overall one now rests on a baseline CI cannot reproduce.
    #
    # The P0 gate fires on the best baseline of any kind, and that is an LLM judge — a
    # non-deterministic, credential-gated, network-bound scorer. A CI job cannot recompute
    # it, so the overall verdict is recorded from the committed measurement and asserted
    # against `metrics.json`. The deterministic-only verdict is what CI can and does
    # recompute from the corpus, and it answers a different, still-useful question: what
    # the gate would say if an auditable matcher were the best available.
    gateable = {n: d for n, d in hard.items()
                if not n.startswith("_")
                and not n.startswith(EXCLUDED_PREFIXES) and n not in EXCLUDED_EXACT}
    det_f1 = max(d["max_f1"]["f1"] for d in gateable.values())
    det_recall = max((d["recall_at_1pct_fpr"].get("recall") or 0.0)
                     for d in gateable.values())
    det_kill = det_f1 >= 0.93 and det_recall >= GATE_KILL_RECALL
    gates["gate_verdict"] = {
        "verdict": hard["_gate_verdict"]["verdict"],
        "best_baseline": best[0],
        "best_max_f1": round(best[1]["max_f1"]["f1"], 6),
        "reproducible_in_ci": False,
        "note": "PLAN.md P0 gate over every baseline. The best is an LLM judge, which is "
                "non-deterministic and credential-gated, so CI asserts this against the "
                "committed metrics.json rather than recomputing it. A change here is a "
                "finding to write up, not a test to silence.",
    }
    gates["gate_verdict_deterministic_only"] = {
        "verdict": "KILL" if det_kill else ("GO" if det_f1 <= 0.85 else "IN-BETWEEN"),
        "best_max_f1": round(det_f1, 6),
        "best_recall_at_1pct_fpr": round(det_recall, 6),
        "reproducible_in_ci": True,
        "note": "Restricted to deterministic, auditable baselines. This is what CI "
                "recomputes from the corpus.",
    }

    out = ROOT / "tests" / "accuracy_gates.json"
    out.write_text(json.dumps(gates, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    n = sum(len(v) for v in gates["slices"].values())
    print(f"wrote {out} ({n} baseline/slice floors, tolerance {TOLERANCE})")


if __name__ == "__main__":
    main()
