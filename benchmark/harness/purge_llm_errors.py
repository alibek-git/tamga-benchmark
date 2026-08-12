#!/usr/bin/env python3
"""Drop errored entries from the LLM-judge response caches so they are re-asked.

A failed API call is cached with score 0.0 and a raw value of `ERROR: ...`. Left in place
that reads as "confidently not a match", which biases the baseline downward on precisely
the pairs that happened to fail — an API credit exhaustion mid-run once left 54 such
entries on one model.

This removes only the errored entries. Successful responses are kept, so re-running costs
API calls for the repaired pairs alone.

    python3 benchmark/harness/purge_llm_errors.py
    python3 benchmark/harness/run.py --version v1.0
"""

from __future__ import annotations

import json
from pathlib import Path

CACHE = Path(__file__).resolve().parents[2] / "benchmark" / ".cache" / "models"


def main() -> None:
    caches = sorted(CACHE.glob("llm-judge-*.jsonl"))
    if not caches:
        print(f"no LLM caches under {CACHE}")
        return
    for path in caches:
        rows = [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]
        kept = [r for r in rows if not str(r.get("raw", "")).startswith("ERROR")]
        dropped = len(rows) - len(kept)
        with path.open("w", encoding="utf-8") as fh:
            for row in sorted(kept, key=lambda r: r["key"]):
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  {path.name}: dropped {dropped} errored, kept {len(kept)}")
    print("now re-run: python3 benchmark/harness/run.py --version v1.0")


if __name__ == "__main__":
    main()
