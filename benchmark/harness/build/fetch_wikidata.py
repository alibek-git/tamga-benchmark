"""Snapshot cross-script name pairs from Wikidata.

Wikidata is the single richest source of cross-script *positive* pairs and it is CC0:
the `ru`, `kk`, `uk` and `en` labels of one item are the same entity by construction
(`docs/data-sources.md` §3b).

Two things this script does that matter for the benchmark's integrity:

1. **`ORDER BY ?item` on every query.** SPARQL without an explicit order returns rows in
   an unspecified sequence, so an unordered query makes the corpus build
   non-reproducible — a direct violation of `CLAUDE.md` §4.
2. **Writes a snapshot to `benchmark/sources/`.** Wikidata is live and edited
   continuously, so re-running this script on a later date legitimately returns
   different data. The committed snapshot is what makes the corpus rebuildable
   byte-identically without network access. The snapshot, not this script, is the
   reproducibility guarantee.

Known sampling bias, recorded here because it shapes how results must be read: Wikidata
`en` labels are usually the *canonical* romanisation a Wikipedia editor chose, and for
well-known people that is frequently an English exonym (`Александр`→`Alexander`,
`Пётр`→`Peter`) rather than any transliteration standard. So this source
under-represents the ad-hoc romanisation variance that causes real screening pain and
over-represents exonyms. The OFAC AKA and synthetic slices exist partly to offset that.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "benchmark" / "sources"
ENDPOINT = "https://query.wikidata.org/sparql"
UA = "tamga-benchmark/0.1 (P0 research corpus; a.zhubekov@prpillar.com)"

# Occupations relevant to sanctions and PEP screening: politician, businessperson,
# military officer, diplomat, banker. Applied to the large populations only.
#
# This is a restriction with a *benefit*: screening populations are politically exposed
# persons and businesspeople, not the general public, so an occupation-restricted sample
# is closer to the entities a compliance team actually screens than an unrestricted one.
# It is applied for a mundane reason too — `ORDER BY ?item` over every human with
# Russian citizenship exceeds the query service's 60s limit.
PEP_OCCUPATIONS = ["Q82955", "Q43845", "Q189290", "Q193391", "Q806798"]

# language code -> (country QIDs, note, restrict_by_occupation, row limit)
#
# Limits are sized for the ≥5,000-pair corpus. `ky` is capped by Wikidata itself, not by
# this limit: roughly 489 Kyrgyzstani people carry both a `ky` and an `en` label, so no
# limit raises it further and Kyrgyz coverage stays thin by necessity.
PERSON_TARGETS = {
    "ru": (["Q159", "Q15180"], "Russia, Soviet Union", True, 6000),
    "kk": (["Q232"], "Kazakhstan", False, 4000),
    "uk": (["Q212"], "Ukraine", True, 6000),
    "uz": (["Q265"], "Uzbekistan", False, 3000),
    "ky": (["Q813"], "Kyrgyzstan", False, 2000),
    "be": (["Q184"], "Belarus", False, 4000),
    "tg": (["Q863"], "Tajikistan", False, 2000),
    "az": (["Q227"], "Azerbaijan", False, 3000),
}

ORG_TARGETS = {
    "ru": (["Q159"], "Russia"),
    "kk": (["Q232"], "Kazakhstan"),
    "uk": (["Q212"], "Ukraine"),
    "uz": (["Q265"], "Uzbekistan"),
}

# Date of birth is **optional**, not required.
#
# It is only needed on the *negative* side, where two differing dates are what prove two
# entities are genuinely distinct. Requiring it of every row shrank the positive pool for
# exactly the languages that needed it most — measured against this endpoint, dropping the
# requirement takes `kk` from 1,534 to 2,141 usable rows and `be` from 1,468 to 6,000.
# The corpus builder filters for a present, differing DOB when constructing negatives.
PERSON_QUERY = """
SELECT ?item ?native ?en ?dob ?sexLabel WHERE {{
  VALUES ?country {{ {countries} }}
  {occ_values}
  ?item wdt:P31 wd:Q5 ;
        wdt:P27 ?country ;
        {occ_clause}
        rdfs:label ?native .
  FILTER(lang(?native) = "{lang}")
  ?item rdfs:label ?en . FILTER(lang(?en) = "en")
  OPTIONAL {{ ?item wdt:P569 ?dob }}
  OPTIONAL {{ ?item wdt:P21 ?sex . ?sex rdfs:label ?sexLabel FILTER(lang(?sexLabel)="en") }}
}}
ORDER BY ?item
LIMIT {limit}
"""

ORG_QUERY = """
SELECT ?item ?native ?en WHERE {{
  VALUES ?country {{ {countries} }}
  ?item wdt:P31/wdt:P279* wd:Q4830453 ;
        wdt:P17 ?country .
  ?item rdfs:label ?native . FILTER(lang(?native) = "{lang}")
  ?item rdfs:label ?en . FILTER(lang(?en) = "en")
}}
ORDER BY ?item
LIMIT {limit}
"""


def run_query(query: str, attempts: int = 4) -> list[dict]:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = requests.get(
                ENDPOINT,
                params={"query": query, "format": "json"},
                headers={"User-Agent": UA, "Accept": "application/sparql-results+json"},
                timeout=180,
            )
            if resp.status_code == 429:
                time.sleep(15 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()["results"]["bindings"]
        except Exception as exc:  # noqa: BLE001 - retried, then surfaced
            last = exc
            time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"wikidata query failed after {attempts} attempts: {last}")


def collect() -> list[dict]:
    rows: list[dict] = []

    for lang, (countries, note, by_occ, limit) in PERSON_TARGETS.items():
        values = " ".join(f"wd:{q}" for q in countries)
        query = PERSON_QUERY.format(
            countries=values,
            lang=lang,
            limit=limit,
            occ_values=("VALUES ?occ { " + " ".join(f"wd:{q}" for q in PEP_OCCUPATIONS)
                        + " }") if by_occ else "",
            occ_clause="wdt:P106 ?occ ;" if by_occ else "",
        )
        got = run_query(query)
        print(f"  persons {lang:3s} ({note}, occ={by_occ}): {len(got)}", file=sys.stderr)
        for r in got:
            rows.append({
                "qid": r["item"]["value"].rsplit("/", 1)[-1],
                "native": r["native"]["value"],
                "native_lang": lang,
                "en": r["en"]["value"],
                "dob": r.get("dob", {}).get("value"),
                "sex": r.get("sexLabel", {}).get("value"),
                "entity_type": "person",
            })
        time.sleep(2)

    for lang, (countries, note) in ORG_TARGETS.items():
        values = " ".join(f"wd:{q}" for q in countries)
        query = ORG_QUERY.format(countries=values, lang=lang, limit=1200)
        try:
            got = run_query(query)
        except RuntimeError as exc:
            print(f"  orgs {lang:3s}: FAILED ({exc})", file=sys.stderr)
            continue
        print(f"  orgs    {lang:3s} ({note}): {len(got)}", file=sys.stderr)
        for r in got:
            rows.append({
                "qid": r["item"]["value"].rsplit("/", 1)[-1],
                "native": r["native"]["value"],
                "native_lang": lang,
                "en": r["en"]["value"],
                "dob": None,
                "sex": None,
                "entity_type": "organisation",
            })
        time.sleep(2)

    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d", time.gmtime())
    rows = collect()

    # Deterministic order and de-duplication on (qid, native_lang).
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for row in sorted(rows, key=lambda r: (r["qid"], r["native_lang"])):
        key = (row["qid"], row["native_lang"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    path = OUT / f"wikidata-snapshot-{stamp}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for row in unique:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    meta = {
        "source": "Wikidata Query Service",
        "endpoint": ENDPOINT,
        "licence": "CC0 1.0 (Wikidata data) [VERIFY: confirmed against "
                   "https://www.wikidata.org/wiki/Wikidata:Licensing before publication]",
        "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rows": len(unique),
        "person_targets": {k: {"countries": v[0], "occupation_restricted": v[2],
                                 "limit": v[3]}
                           for k, v in PERSON_TARGETS.items()},
        "pep_occupations": PEP_OCCUPATIONS,
        "org_targets": {k: v[0] for k, v in ORG_TARGETS.items()},
        "note": "Wikidata is live; re-running this script on another date returns "
                "different rows. The snapshot file is the reproducibility guarantee.",
    }
    (OUT / f"wikidata-snapshot-{stamp}.meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {path} ({len(unique)} rows)", file=sys.stderr)


if __name__ == "__main__":
    main()
