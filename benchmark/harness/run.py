"""Run every baseline against the corpus and write results as data.

Outputs, all under `benchmark/results/<dataset_version>/`:

- `scores.jsonl`      — one record per (pair, baseline). The raw material; everything else
                        is derived from it, so any published figure can be recomputed.
- `metrics.json`      — the full metric set per baseline, per slice.
- `per_phenomenon.csv` — the error taxonomy, flat, for spreadsheet inspection.
- `summary.csv`       — headline numbers per baseline.
- `REPORT.md`         — generated *from* `metrics.json`, never hand-written, so no number
                        in prose can drift from the number that was measured
                        (`CLAUDE.md` §3).
- `environment.json`  — versions and availability diagnostics, including which baselines
                        did not run and why.

Metrics are reported on two slices, because a curated corpus's difficulty is chosen by
whoever built it:

- **full** — the whole corpus, hard and easy negatives together.
- **hard-negatives-only** — easy negatives removed. A *lower bound* on baseline quality,
  not a production FPR estimate. Reporting only this would overstate the gap; reporting
  only the full mix would understate it.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import baselines as B     # noqa: E402
from harness import metrics as M       # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PAIRS = ROOT / "benchmark" / "pairs"
RESULTS = ROOT / "benchmark" / "results"


def load_env_file() -> None:
    """Load `.env` into the environment if present, without overriding real env vars.

    The LLM-judge baseline needs a credential. `.env` is gitignored and never read into
    any output — only into `os.environ`, so a key cannot reach a committed file.
    """
    import re
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
        if match and match.group(1) not in os.environ:
            os.environ[match.group(1)] = match.group(2).strip().strip('"').strip("'")

# P0 gate thresholds, from `PLAN.md`. Hard-coded here so the verdict is computed against
# the criterion decided *before* the work, not one chosen after seeing the numbers.
GATE_KILL_F1 = 0.93
GATE_KILL_RECALL_AT_1PCT = 0.95
GATE_GO_F1 = 0.85


def load_corpus(version: str) -> tuple[list[dict], dict]:
    path = PAIRS / f"{version}.jsonl"
    manifest_path = PAIRS / f"{version}.manifest.json"
    with path.open(encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return records, manifest


def collect_baselines(cache_dir: Path, skip: set[str]) -> tuple[list[B.Baseline], dict]:
    env: dict = {}
    all_baselines: list[B.Baseline] = list(B.CORE_BASELINES)
    env["core"] = {"count": len(B.CORE_BASELINES)}

    if "nomenklatura" not in skip:
        noms, diag = B.nomenklatura_baselines()
        all_baselines += noms
        env["nomenklatura"] = diag
    else:
        env["nomenklatura"] = {"available": False, "reason": "skipped by flag"}

    if "embeddings" not in skip:
        embs, diag = B.embedding_baselines(cache_dir=str(cache_dir))
        all_baselines += embs
        env["embeddings"] = diag
    else:
        env["embeddings"] = {"available": False, "reason": "skipped by flag"}

    llm, diag = B.llm_judge_baselines(cache_dir=cache_dir)
    all_baselines += llm
    env["llm_judge"] = diag

    return all_baselines, env


def slices_of(records: list[dict]) -> dict[str, list[int]]:
    """Index sets for each reporting slice."""
    full = list(range(len(records)))
    hard_only = [
        i for i, r in enumerate(records)
        if r["same_entity"] or r["difficulty"] == "hard"
    ]
    return {"full": full, "hard-negatives-only": hard_only}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="pilot-v0.1")
    ap.add_argument("--skip", default="", help="comma-separated: nomenklatura,embeddings")
    ap.add_argument("--allow-llm-errors", action="store_true",
                    help="publish even if cached LLM responses contain errors (biased)")
    args = ap.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    records, manifest = load_corpus(args.version)
    out_dir = RESULTS / args.version
    out_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = ROOT / "benchmark" / ".cache" / "models"
    cache_dir.mkdir(parents=True, exist_ok=True)

    load_env_file()
    started = time.time()
    all_baselines, env = collect_baselines(cache_dir, skip)
    print(f"  baselines: {len(all_baselines)}", file=sys.stderr)

    # ---------------------------------------------------------------------------------
    # score every pair with every baseline
    # ---------------------------------------------------------------------------------
    scores: dict[str, list[float]] = {}
    timings: dict[str, float] = {}
    for baseline in all_baselines:
        t0 = time.time()
        if baseline.prepare is not None:
            # Network-backed baselines fetch every verdict concurrently first; scoring
            # then reads from their cache. Without this the LLM judges would issue 5,127
            # sequential requests.
            summary = baseline.prepare(records)
            print(f"      prepared {baseline.name}: {summary}", file=sys.stderr)
            # A failed API call is cached as 0.0, i.e. "confidently not a match", so any
            # errored entry biases this baseline downward on the pairs that happened to
            # fail. Publishing that as a measurement would be a fabricated comparison.
            # Refuse rather than warn: an API outage must not become a quiet finding.
            errored = summary.get("errored_entries_in_cache", 0)
            if errored and not args.allow_llm_errors:
                raise SystemExit(
                    f"\n{baseline.name}: {errored} cached responses are errors, scored "
                    f"0.0.\nThis understates the baseline on exactly those pairs. Purge "
                    f"them and re-run:\n"
                    f"  python3 benchmark/harness/purge_llm_errors.py\n"
                    f"Override only if you accept a biased figure: --allow-llm-errors"
                )
        row = [baseline.score(r["name_a"], r["name_b"], r) for r in records]
        scores[baseline.name] = row
        timings[baseline.name] = time.time() - t0
        print(f"    {baseline.name:44s} {timings[baseline.name]:7.2f}s", file=sys.stderr)

    with (out_dir / "scores.jsonl").open("w", encoding="utf-8") as fh:
        for i, record in enumerate(records):
            fh.write(json.dumps({
                "id": record["id"],
                "same_entity": record["same_entity"],
                "difficulty": record["difficulty"],
                "language": record["language"],
                "phenomena": record["phenomena"],
                "scores": {name: round(scores[name][i], 6) for name in scores},
            }, ensure_ascii=False, sort_keys=True) + "\n")

    # ---------------------------------------------------------------------------------
    # metrics
    # ---------------------------------------------------------------------------------
    index_sets = slices_of(records)
    results: dict = {
        "dataset_version": args.version,
        "dataset_sha256": manifest["sha256_of_corpus"],
        "run_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corpus_counts": manifest["counts"],
        "slices": {},
        "gate": {
            "source": "PLAN.md P0 gate, fixed before the run",
            "kill_if": f"best baseline >= {GATE_KILL_F1} max-F1 AND "
                       f">= {GATE_KILL_RECALL_AT_1PCT} recall @ 1% FPR",
            "go_if": f"best baseline <= {GATE_GO_F1} max-F1 with errors clustering in "
                     f"nameable phenomena",
        },
    }

    for slice_name, indices in index_sets.items():
        slice_records = [records[i] for i in indices]
        labels = [r["same_entity"] for r in slice_records]
        n_neg = sum(1 for y in labels if not y)
        per_baseline: dict = {}

        for baseline in all_baselines:
            slice_scores = [scores[baseline.name][i] for i in indices]
            evaluated = M.evaluate(slice_scores, labels, n_neg=n_neg)

            # The taxonomy is reported at the 1% FPR operating point, which is the one a
            # compliance buyer would actually run at.
            op = evaluated.get("recall_at_1pct_fpr", {})
            threshold = op.get("threshold")
            if threshold is not None:
                evaluated["per_phenomenon_recall"] = M.per_phenomenon_recall(
                    slice_records, slice_scores, threshold)
                evaluated["per_phenomenon_fpr"] = M.per_phenomenon_false_positive_rate(
                    slice_records, slice_scores, threshold)
            evaluated["deterministic"] = baseline.deterministic
            evaluated["family"] = baseline.family
            evaluated["notes"] = baseline.notes
            evaluated["seconds"] = round(timings[baseline.name], 3)
            per_baseline[baseline.name] = evaluated

        results["slices"][slice_name] = per_baseline

    # ---------------------------------------------------------------------------------
    # gate verdict, computed not asserted
    # ---------------------------------------------------------------------------------
    for slice_name in index_sets:
        best_f1_name, best_f1 = None, -1.0
        best_recall_name, best_recall = None, -1.0
        for name, data in results["slices"][slice_name].items():
            f1 = data.get("max_f1", {}).get("f1", 0.0)
            if f1 > best_f1:
                best_f1, best_f1_name = f1, name
            op = data.get("recall_at_1pct_fpr", {})
            recall = op.get("recall") or 0.0
            if recall > best_recall:
                best_recall, best_recall_name = recall, name
        kill = best_f1 >= GATE_KILL_F1 and best_recall >= GATE_KILL_RECALL_AT_1PCT
        go = best_f1 <= GATE_GO_F1
        results["slices"][slice_name]["_gate_verdict"] = {
            "best_max_f1": {"baseline": best_f1_name, "value": best_f1},
            "best_recall_at_1pct_fpr": {"baseline": best_recall_name,
                                        "value": best_recall},
            "kill_criterion_met": kill,
            "go_criterion_met": go and not kill,
            "verdict": "KILL" if kill else ("GO" if go else "IN-BETWEEN"),
        }

    (out_dir / "metrics.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ---------------------------------------------------------------------------------
    # flat CSVs
    # ---------------------------------------------------------------------------------
    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["slice", "baseline", "family", "max_f1",
                         "trivial_all_positive_f1", "max_f1_above_trivial",
                         "f1_threshold", "precision_at_max_f1", "recall_at_max_f1",
                         "recall_at_1pct_fpr", "achieved_fpr_at_1pct_target",
                         "recall_at_0_1pct_fpr", "recall_at_0_1pct_resolvable",
                         "recall_at_zero_fp",
                         "fpr_at_95pct_recall", "alerts_per_true_hit_at_95pct_recall",
                         "fpr_at_99pct_recall", "alerts_per_true_hit_at_99pct_recall",
                         "roc_auc", "deterministic", "seconds"])
        for slice_name in index_sets:
            for name, data in results["slices"][slice_name].items():
                if name.startswith("_"):
                    continue
                f1 = data.get("max_f1", {})
                op1 = data.get("recall_at_1pct_fpr", {})
                op01 = data.get("recall_at_0_1pct_fpr", {})
                zero = data.get("recall_at_zero_fp", {})
                r95 = data.get("fpr_at_95pct_recall", {})
                r99 = data.get("fpr_at_99pct_recall", {})
                writer.writerow([
                    slice_name, name, data.get("family"),
                    round(f1.get("f1", 0.0), 4),
                    round(data.get("trivial_all_positive_f1", 0.0), 4),
                    round(data.get("max_f1_above_trivial", 0.0), 4),
                    f1.get("threshold"),
                    round(f1.get("precision", 0.0), 4), round(f1.get("recall", 0.0), 4),
                    round(op1.get("recall") or 0.0, 4),
                    round(op1.get("achieved_fpr") or 0.0, 4),
                    "" if op01.get("recall") is None else round(op01["recall"], 4),
                    op01.get("resolvable"),
                    round(zero.get("recall", 0.0), 4),
                    "" if not r95.get("reachable") else
                    round(r95["false_positive_rate"], 4),
                    "" if not r95.get("reachable") else
                    round(r95["alerts_per_true_hit"], 3),
                    "" if not r99.get("reachable") else
                    round(r99["false_positive_rate"], 4),
                    "" if not r99.get("reachable") else
                    round(r99["alerts_per_true_hit"], 3),
                    round(data.get("roc_auc", float("nan")), 4),
                    data.get("deterministic"), data.get("seconds"),
                ])

    with (out_dir / "per_phenomenon.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["slice", "baseline", "phenomenon", "kind", "n", "value",
                         "missed_or_fp", "low_support"])
        for slice_name in index_sets:
            for name, data in results["slices"][slice_name].items():
                if name.startswith("_"):
                    continue
                for tag, info in (data.get("per_phenomenon_recall") or {}).items():
                    writer.writerow([slice_name, name, tag, "recall", info["n"],
                                     round(info["recall"], 4), info["missed"],
                                     info["low_support"]])
                for tag, info in (data.get("per_phenomenon_fpr") or {}).items():
                    writer.writerow([slice_name, name, tag, "fpr", info["n"],
                                     round(info["false_positive_rate"], 4),
                                     info["false_positives"], info["low_support"]])

    # ---------------------------------------------------------------------------------
    # environment
    # ---------------------------------------------------------------------------------
    env_doc = {
        "run_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "elapsed_seconds": round(time.time() - started, 1),
        "baselines_run": [b.name for b in all_baselines],
        "baselines_not_run": [],
        "diagnostics": env,
    }
    if not env.get("llm_judge", {}).get("available"):
        env_doc["baselines_not_run"].append({
            "baseline": "llm-judge",
            "reason": env["llm_judge"].get("reason"),
            "result": "TBD — not estimated",
        })
    if not env.get("embeddings", {}).get("available"):
        env_doc["baselines_not_run"].append({
            "baseline": "multilingual embeddings (LaBSE, multilingual-e5)",
            "reason": env["embeddings"].get("reason", "unavailable"),
            "result": "TBD — not estimated",
        })
    (out_dir / "environment.json").write_text(
        json.dumps(env_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    write_report(out_dir, results, manifest, env_doc)

    print(f"\nwrote {out_dir}", file=sys.stderr)
    for slice_name in index_sets:
        verdict = results["slices"][slice_name]["_gate_verdict"]
        print(f"  {slice_name:22s} verdict={verdict['verdict']:11s} "
              f"best max-F1={verdict['best_max_f1']['value']:.4f} "
              f"({verdict['best_max_f1']['baseline']})  "
              f"best recall@1%FPR={verdict['best_recall_at_1pct_fpr']['value']:.4f}",
              file=sys.stderr)


def write_report(out_dir: Path, results: dict, manifest: dict, env: dict) -> None:
    """Generate REPORT.md from the measured metrics.

    Every number here is read out of `results`. Nothing is typed by hand, so the prose
    cannot drift from the measurement (`CLAUDE.md` §3, `benchmark/README.md`).
    """
    lines: list[str] = []
    add = lines.append

    add(f"# P0 pilot benchmark results — `{results['dataset_version']}`")
    add("")
    add("**Generated by `benchmark/harness/run.py` from `metrics.json`. Do not edit by "
        "hand.** Every figure below was produced by the run recorded in "
        "`environment.json`.")
    add("")
    add(f"- Corpus: `{results['dataset_version']}.jsonl`, "
        f"sha256 `{results['dataset_sha256'][:16]}…`")
    add(f"- Run: {results['run_utc']}")
    counts = results["corpus_counts"]
    add(f"- Pairs: **{counts['total']}** "
        f"({counts['positive']} positive / {counts['negative']} negative; "
        f"{counts['hard_negative']} hard negatives, {counts['easy_negative']} easy; "
        f"{counts['synthetic_positive']} synthetic positives)")
    add("")
    add("## Scope and what these numbers cannot tell you")
    add("")
    add("This is a **pilot** of 300–500 pairs built for a same-day signal, not the "
        "≥5,000-pair corpus specified in `benchmark/README.md`.")
    add("")
    add("1. **Corpus difficulty is a choice, not a measurement.** Whoever builds the "
        "negatives sets how hard the benchmark is. Results are therefore given on two "
        "slices: `hard-negatives-only` is a *lower bound* on baseline quality, `full` "
        "includes easy negatives. Neither is a production FPR estimate, because the "
        "corpus is not a sample of any real screening queue.")
    add("2. **`max_f1` is oracle-tuned.** The threshold is chosen knowing the labels, "
        "which flatters every baseline. That is deliberate: the gate should only fire "
        "against a baseline that fails even at its best possible threshold.")
    add("3. **Positives are biased toward canonical romanisations.** Wikidata `en` "
        "labels are usually the spelling a Wikipedia editor chose, often an English "
        "exonym rather than any transliteration standard, so the ad-hoc variance that "
        "causes real screening pain is under-represented relative to production.")
    add("4. **`Alerts per true hit` is corpus-dependent and is not a production "
        "figure.** This corpus is roughly half positives; a real screening queue is "
        "overwhelmingly non-matches, so the production alert ratio at the same recall "
        "would be far worse. `FPR` transfers across composition; the alert ratio does "
        "not. Quote the FPR, not the ratio.")
    add("5. **`recall @ 0.1% FPR` is unmeasurable at this size** and is reported as "
        "such rather than interpolated — see the note under each table.")
    add("")

    for slice_name, per_baseline in results["slices"].items():
        verdict = per_baseline["_gate_verdict"]
        add(f"## Slice: `{slice_name}`")
        add("")
        add(f"**Gate verdict: {verdict['verdict']}** — best max-F1 "
            f"{verdict['best_max_f1']['value']:.4f} "
            f"(`{verdict['best_max_f1']['baseline']}`), best recall @ 1% FPR "
            f"{verdict['best_recall_at_1pct_fpr']['value']:.4f} "
            f"(`{verdict['best_recall_at_1pct_fpr']['baseline']}`).")
        add("")
        rows = [(n, d) for n, d in per_baseline.items() if not n.startswith("_")]
        rows.sort(key=lambda kv: -kv[1].get("max_f1", {}).get("f1", 0.0))

        trivial = rows[0][1].get("trivial_all_positive_f1", 0.0) if rows else 0.0
        add(f"On this slice, calling **every** pair a match scores max-F1 "
            f"{trivial:.4f}. That is the floor for the F1 column below, so read F1 "
            f"against {trivial:.3f}, not against zero.")
        add("")
        add("| Baseline | Family | max-F1 | F1 above trivial | R@1%FPR | R@0.1%FPR "
            "| R@0 FP | FPR@95% recall | Alerts per true hit @95% recall | ROC-AUC |")
        add("|---|---|---|---|---|---|---|---|---|---|")
        for name, data in rows:
            f1 = data.get("max_f1", {}).get("f1", 0.0)
            above = data.get("max_f1_above_trivial", 0.0)
            r1 = data.get("recall_at_1pct_fpr", {}).get("recall")
            r01 = data.get("recall_at_0_1pct_fpr", {})
            r0 = data.get("recall_at_zero_fp", {}).get("recall", 0.0)
            r95 = data.get("fpr_at_95pct_recall", {})
            auc = data.get("roc_auc", float("nan"))
            r01_text = "not resolvable" if not r01.get("resolvable") else \
                f"{r01.get('recall', 0.0):.3f}"
            if r95.get("reachable"):
                fpr95 = f"{r95['false_positive_rate']:.3f}"
                alerts95 = f"{r95['alerts_per_true_hit']:.2f}"
            else:
                fpr95, alerts95 = "unreachable", "unreachable"
            add(f"| `{name}` | {data.get('family')} | {f1:.4f} | {above:+.4f} | "
                f"{(r1 or 0.0):.4f} | {r01_text} | {r0:.4f} | {fpr95} | {alerts95} | "
                f"{auc:.4f} |")
        add("")
        add("`FPR@95% recall` and `Alerts per true hit` answer the question the "
            "commercial thesis actually rests on: to catch 95% of true matches, how much "
            "false-positive volume must a compliance team absorb? `unreachable` means no "
            "threshold reaches 95% recall at all.")
        add("")

        example = next((d for _, d in rows), None)
        if example:
            r01 = example.get("recall_at_0_1pct_fpr", {})
            if not r01.get("resolvable"):
                add(f"> **Recall @ 0.1% FPR is not resolvable at this corpus size.** "
                    f"{r01.get('reason')} Resolving it needs at least "
                    f"{r01.get('negatives_required_for_resolution')} negatives. "
                    f"The `R@0 FP` column is the strictest operating point this corpus "
                    f"*can* resolve; its 95% upper bound on the true FPR is "
                    f"{example.get('recall_at_zero_fp', {}).get('fpr_95pct_upper_bound', 0):.4f}.")
                add("")

    # ---------------------------------------------------------------------------------
    # error taxonomy — the diagnostic output, per benchmark/README.md
    # ---------------------------------------------------------------------------------
    hard = results["slices"].get("hard-negatives-only", {})
    compare = [n for n in ("nomenklatura/logic-v2", "embedding/LaBSE",
                           "icu-any-latin-ascii+levenshtein", "icu+soundex")
               if n in hard]
    if compare:
        add("## Error taxonomy — recall per phenomenon at the 1% FPR operating point")
        add("")
        add("Slice: `hard-negatives-only`. This is the output that decides whether an "
            "engine has anything to add, and it is far more informative than the "
            "aggregate scores above.")
        add("")
        add("| Phenomenon | n | " + " | ".join(f"`{n.split('/')[-1]}`" for n in compare)
            + " |")
        add("|---|---|" + "---|" * len(compare))
        reference = hard[compare[0]].get("per_phenomenon_recall") or {}
        ordered = sorted(
            (t for t, i in reference.items() if not i["low_support"]),
            key=lambda t: reference[t]["recall"],
        )
        for tag in ordered:
            cells = []
            for name in compare:
                info = (hard[name].get("per_phenomenon_recall") or {}).get(tag)
                cells.append(f"{info['recall']:.3f}" if info else "—")
            add(f"| `{tag}` | {reference[tag]['n']} | " + " | ".join(cells) + " |")
        add("")
        add("Phenomena with fewer than "
            f"{__import__('harness.metrics', fromlist=['M']).MIN_PHENOMENON_SUPPORT} "
            "positives are omitted: recall over a handful of pairs is noise, not a "
            "finding. The full table including them is in `per_phenomenon.csv`.")
        add("")

    add("## Baselines that did not run")
    add("")
    if env["baselines_not_run"]:
        for entry in env["baselines_not_run"]:
            add(f"- **{entry['baseline']}** — {entry['reason']}. Result: "
                f"`{entry['result']}`.")
    else:
        add("All baselines ran.")
    add("")
    add("## Files")
    add("")
    add("| File | Contents |")
    add("|---|---|")
    add("| `scores.jsonl` | one record per pair with every baseline's score — the raw "
        "material for every figure above |")
    add("| `metrics.json` | full metric set per baseline per slice, including the "
        "per-phenomenon taxonomy |")
    add("| `per_phenomenon.csv` | error taxonomy, flat |")
    add("| `summary.csv` | headline numbers per baseline |")
    add("| `environment.json` | versions, timings, and what did not run |")
    add("")

    (out_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
