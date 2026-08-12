"""The publication write-up must agree with the measurement it reports.

`docs/findings.md` is generated from `metrics.json` by
`benchmark/harness/make_findings.py`. This test regenerates it and diffs, so a re-run that
changes a figure cannot leave a stale number in the published document —
`CLAUDE.md` §3 and `docs/legal-and-ethics.md` §6 both make that a defect rather than a
copy-editing issue.

If this fails, regenerate the document. Do not edit the numbers by hand.
"""

from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "findings.md"
GENERATOR = ROOT / "benchmark" / "harness" / "make_findings.py"


def test_findings_doc_matches_the_measurement(tmp_path, dataset_version) -> None:
    if not DOC.exists():
        pytest.skip("docs/findings.md not generated")
    regenerated = tmp_path / "findings.md"
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--version", dataset_version,
         "--out", str(regenerated)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr

    committed = DOC.read_text(encoding="utf-8")
    fresh = regenerated.read_text(encoding="utf-8")
    if committed != fresh:
        diff = "\n".join(difflib.unified_diff(
            committed.splitlines(), fresh.splitlines(),
            fromfile="committed docs/findings.md", tofile="regenerated", lineterm="",
        )[:40])
        pytest.fail(
            "docs/findings.md disagrees with the committed metrics. Regenerate with "
            "`python3 benchmark/harness/make_findings.py`:\n" + diff
        )


def test_findings_doc_states_the_scope_guardrail() -> None:
    """Defensive use only, and no commercial product benchmarked — both are publication
    conditions in `docs/legal-and-ethics.md` §1 and §3, not optional framing."""
    if not DOC.exists():
        pytest.skip("docs/findings.md not generated")
    text = DOC.read_text(encoding="utf-8")
    assert "Defensive use only" in text
    assert "No commercial screening product was benchmarked" in text
    assert "[VERIFY]" in text, "OFAC redistribution terms must stay flagged"


def test_findings_doc_states_the_single_vendor_limitation() -> None:
    """The largest gap in the work. It must not be buried."""
    if not DOC.exists():
        pytest.skip("docs/findings.md not generated")
    text = DOC.read_text(encoding="utf-8")
    assert "Single vendor" in text
    assert "untested" in text
