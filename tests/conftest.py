"""Shared fixtures. Makes `harness` importable and loads the corpus once per session."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmark"))

DATASET_VERSION = "v1.0"
PAIRS = ROOT / "benchmark" / "pairs"
RESULTS = ROOT / "benchmark" / "results" / DATASET_VERSION


@pytest.fixture(scope="session")
def dataset_version() -> str:
    return DATASET_VERSION


@pytest.fixture(scope="session")
def corpus() -> list[dict]:
    path = PAIRS / f"{DATASET_VERSION}.jsonl"
    if not path.exists():
        pytest.skip(f"corpus {path.name} not built")
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="session")
def manifest() -> dict:
    path = PAIRS / f"{DATASET_VERSION}.manifest.json"
    if not path.exists():
        pytest.skip(f"manifest for {DATASET_VERSION} not built")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def metrics() -> dict:
    path = RESULTS / "metrics.json"
    if not path.exists():
        pytest.skip("metrics.json not present; run benchmark/harness/run.py")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def gates() -> dict:
    path = Path(__file__).parent / "accuracy_gates.json"
    if not path.exists():
        pytest.skip("accuracy_gates.json not present")
    return json.loads(path.read_text(encoding="utf-8"))
