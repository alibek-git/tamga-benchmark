"""Layer 2 — corpus integrity and determinism.

`tests/README.md` calls this the golden-file layer: byte-identical output for a pinned
version. For a benchmark the artifact under that guarantee is the corpus itself, since
every published figure is attributed to a specific `sha256`.

These tests are cheap and run on every commit. They exist because a corpus defect is
worse than a code defect: it produces plausible numbers that are quietly wrong.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harness import names as N

ROOT = Path(__file__).resolve().parents[1]

SCHEMA = {"id", "name_a", "name_b", "script_a", "script_b", "language", "entity_type",
          "same_entity", "phenomena", "difficulty", "source", "notes"}


def test_every_record_matches_the_documented_schema(corpus) -> None:
    for record in corpus:
        assert set(record) == SCHEMA, f"{record['id']}: {set(record) ^ SCHEMA}"


def test_ids_are_unique(corpus) -> None:
    ids = [r["id"] for r in corpus]
    assert len(ids) == len(set(ids))


def test_no_empty_or_identical_name_pairs(corpus) -> None:
    for record in corpus:
        assert record["name_a"].strip(), record["id"]
        assert record["name_b"].strip(), record["id"]
        assert record["name_a"].strip() != record["name_b"].strip(), record["id"]


def test_labels_are_booleans_and_both_classes_present(corpus) -> None:
    for record in corpus:
        assert isinstance(record["same_entity"], bool), record["id"]
    labels = {r["same_entity"] for r in corpus}
    assert labels == {True, False}


def test_every_pair_carries_at_least_one_phenomenon(corpus) -> None:
    """A pair with no tag contributes to the aggregate score but not to the taxonomy,
    which `benchmark/README.md` calls the whole point."""
    untagged = [r["id"] for r in corpus if not r["phenomena"]]
    assert not untagged, f"{len(untagged)} untagged pairs, e.g. {untagged[:5]}"


def test_difficulty_values_are_valid(corpus) -> None:
    assert {r["difficulty"] for r in corpus} <= {"easy", "hard"}


def test_every_pair_has_provenance(corpus) -> None:
    for record in corpus:
        assert record["source"], record["id"]
        assert any(record["source"].startswith(p)
                   for p in ("wikidata:", "ofac-sdn:", "synthetic:")), record["source"]


def test_declared_scripts_match_the_actual_strings(corpus) -> None:
    for record in corpus:
        assert N.detect_script(record["name_a"]) == record["script_a"], record["id"]
        assert N.detect_script(record["name_b"]) == record["script_b"], record["id"]


def test_synthetic_output_is_never_mixed_script(corpus) -> None:
    """**Regression.** A romanisation table missing a letter emitted Cyrillic inside a
    supposedly Latin string. That is corrupt data, not a hard pair, and it would make
    every baseline look worse for the wrong reason.
    """
    for record in corpus:
        if record["source"].startswith("synthetic:"):
            assert record["script_b"] == "Latn", f"{record['id']}: {record['name_b']!r}"


def test_manifest_checksum_matches_the_corpus_on_disk(manifest, dataset_version) -> None:
    path = ROOT / "benchmark" / "pairs" / f"{dataset_version}.jsonl"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == manifest["sha256_of_corpus"]


def test_manifest_counts_match_the_corpus(manifest, corpus) -> None:
    counts = manifest["counts"]
    assert counts["total"] == len(corpus)
    assert counts["positive"] == sum(1 for r in corpus if r["same_entity"])
    assert counts["negative"] == sum(1 for r in corpus if not r["same_entity"])


# --------------------------------------------------------------------------------------
# composition requirements from benchmark/README.md
# --------------------------------------------------------------------------------------

def test_corpus_meets_the_minimum_size(manifest) -> None:
    assert manifest["counts"]["total"] >= 5000, manifest["counts"]


def test_synthetic_share_of_positives_is_capped(manifest) -> None:
    """≤30%: rule-generated pairs only test transformations already modelled, so a corpus
    dominated by them measures our own assumptions back at us."""
    target = manifest["composition_targets"]["synthetic_share_of_positives"]
    assert target["met"], target


def test_hard_negatives_are_the_majority_of_negatives(manifest) -> None:
    """≥60%: a corpus of easy negatives makes every matcher look excellent."""
    target = manifest["composition_targets"]["hard_share_of_negatives"]
    assert target["met"], target


def test_required_languages_are_present(manifest) -> None:
    missing = [k for k, v in manifest["required_languages_present"].items() if not v]
    assert not missing, f"missing required languages: {missing}"


def test_enough_negatives_to_resolve_the_required_fpr(manifest) -> None:
    """`PLAN.md` requires recall at 0.1% FPR. With `n` negatives the finest FPR step is
    `1/n`, so below 1,000 negatives that metric cannot be expressed at all — the pilot's
    230 could not, and the harness correctly refused to interpolate it.
    """
    assert manifest["counts"]["negative"] >= 1000, manifest["counts"]
    assert manifest["counts"]["hard_negative"] >= 1000, manifest["counts"]


def test_both_directions_of_matching_are_represented(manifest) -> None:
    """`PLAN.md`: Cyrillic↔Latin, and Latin↔Latin across romanisation systems."""
    pairs = manifest["by_script_pair"]
    assert pairs.get("Cyrl->Latn", 0) > 0
    assert pairs.get("Latn->Latn", 0) > 0, "no cross-romanisation pairs"


def test_organisations_are_covered(manifest) -> None:
    """Screening is not only people (`docs/domain-notes.md` §6)."""
    assert manifest["by_entity_type"].get("organisation", 0) > 0


def test_reported_shortfalls_are_visible_not_hidden(manifest) -> None:
    """Shortfalls against target are allowed — silent truncation is not. If a slice came
    up short the manifest must say so, with the number available."""
    for slice_name, info in manifest["shortfalls_against_target"].items():
        assert "wanted" in info and "available" in info, slice_name
        assert info["available"] < info["wanted"], slice_name


def test_results_reference_the_committed_corpus(metrics, manifest) -> None:
    """Results attributed to a corpus that is no longer on disk cannot be reproduced."""
    assert metrics["dataset_sha256"] == manifest["sha256_of_corpus"]


def test_every_pair_was_scored_by_every_baseline(dataset_version, corpus) -> None:
    path = ROOT / "benchmark" / "results" / dataset_version / "scores.jsonl"
    if not path.exists():
        pytest.skip("scores.jsonl not present")
    with path.open(encoding="utf-8") as fh:
        scored = [json.loads(line) for line in fh if line.strip()]
    assert len(scored) == len(corpus)
    names = {n for row in scored for n in row["scores"]}
    for row in scored:
        assert set(row["scores"]) == names, row["id"]
        for name, value in row["scores"].items():
            assert 0.0 <= value <= 1.0, f"{row['id']}/{name}={value}"


def test_no_duplicate_name_pairs(corpus) -> None:
    """**Regression.** 25 pairs shared identical `(name_a, name_b)` strings — a synthetic
    romanisation reproducing the real label exactly, or one negative found by two
    generators. None disagreed on the label, but keeping both double-weighted those pairs
    in every metric and split them across two source slices in the breakdown.
    """
    import collections
    counts = collections.Counter((r["name_a"], r["name_b"]) for r in corpus)
    duplicated = [pair for pair, n in counts.items() if n > 1]
    assert not duplicated, f"{len(duplicated)} duplicated name pairs, e.g. {duplicated[:3]}"


def test_duplicate_removal_found_no_label_conflicts(manifest) -> None:
    """If two identical name pairs ever disagree on `same_entity`, that is a labelling
    contradiction and the corpus must not ship until it is understood."""
    excluded = manifest["excluded"]
    assert excluded["duplicate_labels_that_disagreed"] == 0, excluded["duplicate_examples"]
