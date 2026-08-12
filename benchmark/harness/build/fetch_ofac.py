"""Extract cross-script and cross-romanisation name variants from the OFAC SDN list.

Why this source is the best positives available: sanctions entries carry alternate
spellings curated by government analysts, and for Cyrillic-origin entries those are
frequently *exactly* the romanisation variants the engine would need to handle
(`docs/data-sources.md` §3a). Unlike Wikidata's canonical `en` label, an OFAC AKA set is
a record of how one entity's name is actually written across systems.

The SDN Advanced XML is used rather than SDN.CSV because it exposes three things the CSV
does not:

- `ScriptID` per name part, so Cyrillic-script alternate names are identifiable as such;
- `NamePartTypeID`, including a dedicated `Patronymic` type, so patronymic phenomena can
  be tagged from the source's own structure rather than guessed;
- `LowQuality` on each alias, so OFAC's own weak-alias flag can be honoured.

Weak (`LowQuality="true"`) aliases are **excluded**. They are frequently partial names or
nicknames, and a benchmark positive must be a name a screening system should reasonably
be expected to resolve — not a fragment.

Licence: OFAC SDN data is a US Government work published for public compliance use.
`[VERIFY]` the current terms at https://ofac.treasury.gov before redistributing the
extract as part of a published benchmark (`docs/data-sources.md` §6).
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from harness import names as N  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "benchmark" / "sources"
CACHE = ROOT / "benchmark" / ".cache"
URL = ("https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/"
       "SDN_ADVANCED.XML")
NS = "{https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ADVANCED_XML}"

SCRIPT_LATIN, SCRIPT_CYRILLIC = "215", "220"
PART_LAST, PART_FIRST, PART_MIDDLE = "1520", "1521", "1522"
PART_MAIDEN, PART_ENTITY, PART_NICKNAME = "1523", "1525", "1528"
PART_PATRONYMIC, PART_MATRONYMIC = "91708", "91709"
SUBTYPE_ENTITY, SUBTYPE_INDIVIDUAL = "3", "4"

# Render order for a person: given, middle/patronymic, surname. Fixed and applied to
# *both* sides of every pair, so that surname-first order never leaks in as an accidental
# untagged phenomenon — `order:swapped` must be introduced deliberately or not at all.
PERSON_RENDER_ORDER = (PART_FIRST, PART_MIDDLE, PART_PATRONYMIC, PART_MATRONYMIC,
                       PART_MAIDEN, PART_LAST)


def download() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "sdn_advanced.xml"
    if path.exists() and path.stat().st_size > 50_000_000:
        print(f"  using cached {path} ({path.stat().st_size} bytes)", file=sys.stderr)
        return path
    print("  downloading SDN_ADVANCED.XML ...", file=sys.stderr)
    with requests.get(URL, stream=True, timeout=900) as resp:
        resp.raise_for_status()
        with path.open("wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)
    # A truncated download parses as invalid XML only at the very end of a long parse,
    # so check the closing tag up front.
    with path.open("rb") as fh:
        fh.seek(-64, 2)
        if b"</Sanctions>" not in fh.read():
            raise RuntimeError("SDN_ADVANCED.XML download is truncated")
    return path


def issue_date(root: ET.Element) -> str:
    node = root.find(f"{NS}DateOfIssue")
    if node is None:
        return "unknown"
    parts = {c.tag.replace(NS, ""): c.text for c in node}
    return f"{parts.get('Year')}-{int(parts.get('Month', 1)):02d}-{int(parts.get('Day', 1)):02d}"


def render(parts: list[tuple[str, str]], is_person: bool) -> str:
    """`parts` is [(name_part_type_id, value)] in document order."""
    if not is_person:
        return N.normalise_ws(" ".join(v for _, v in parts))
    ordered: list[str] = []
    for wanted in PERSON_RENDER_ORDER:
        ordered += [v for t, v in parts if t == wanted]
    leftover = [v for t, v in parts if t not in PERSON_RENDER_ORDER]
    return N.normalise_ws(" ".join(ordered + leftover))


def extract(root: ET.Element) -> list[dict]:
    records: list[dict] = []

    for party in root.iter(f"{NS}DistinctParty"):
        fixed_ref = party.get("FixedRef")
        profile = party.find(f"{NS}Profile")
        if profile is None:
            continue
        subtype = profile.get("PartySubTypeID")
        if subtype not in (SUBTYPE_ENTITY, SUBTYPE_INDIVIDUAL):
            continue  # vessels and aircraft: name matching alone is the wrong signal
        is_person = subtype == SUBTYPE_INDIVIDUAL

        for identity in profile.iter(f"{NS}Identity"):
            group_type: dict[str, str] = {}
            for grp in identity.iter(f"{NS}NamePartGroup"):
                group_type[grp.get("ID")] = grp.get("NamePartTypeID")

            variants: list[dict] = []
            for alias in identity.iter(f"{NS}Alias"):
                if alias.get("LowQuality") == "true":
                    continue
                alias_type = alias.get("AliasTypeID")
                for doc in alias.iter(f"{NS}DocumentedName"):
                    parts: list[tuple[str, str]] = []
                    scripts: set[str] = set()
                    for value in doc.iter(f"{NS}NamePartValue"):
                        text = (value.text or "").strip()
                        if not text:
                            continue
                        ptype = group_type.get(value.get("NamePartGroupID"), "")
                        if ptype == PART_NICKNAME:
                            continue
                        parts.append((ptype, text))
                        scripts.add(value.get("ScriptID") or "")
                    if not parts or len(scripts) != 1:
                        continue
                    script_id = scripts.pop()
                    if script_id not in (SCRIPT_LATIN, SCRIPT_CYRILLIC):
                        continue
                    variants.append({
                        "text": render(parts, is_person),
                        "script": "Cyrl" if script_id == SCRIPT_CYRILLIC else "Latn",
                        "alias_type": alias_type,
                        "doc_status": doc.get("DocNameStatusID"),
                        "part_types": sorted({t for t, _ in parts if t}),
                        "has_patronymic_part": any(
                            t in (PART_PATRONYMIC, PART_MATRONYMIC) for t, _ in parts
                        ),
                        "n_parts": len(parts),
                    })

            if not any(v["script"] == "Cyrl" for v in variants):
                continue
            if not any(v["script"] == "Latn" for v in variants):
                continue

            cyr_text = next(v["text"] for v in variants if v["script"] == "Cyrl")
            lang, basis = N.guess_language_from_orthography(cyr_text)

            # De-duplicate variants on (text, script), preserving first occurrence.
            seen: set[tuple[str, str]] = set()
            unique: list[dict] = []
            for v in variants:
                key = (v["text"], v["script"])
                if key in seen:
                    continue
                seen.add(key)
                unique.append(v)

            records.append({
                "ofac_fixed_ref": fixed_ref,
                "identity_id": identity.get("ID"),
                "entity_type": "person" if is_person else "organisation",
                "language": lang,
                "language_basis": basis,
                "variants": unique,
            })

    records.sort(key=lambda r: (int(r["ofac_fixed_ref"]), r["identity_id"]))
    return records


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = download()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    root = ET.parse(path).getroot()
    published = issue_date(root)
    records = extract(root)

    out_path = OUT / f"ofac-sdn-extract-{published}.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

    n_person = sum(1 for r in records if r["entity_type"] == "person")
    meta = {
        "source": "US Treasury OFAC — Specially Designated Nationals (SDN) Advanced XML",
        "url": URL,
        "sdn_publication_date": published,
        "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sha256_of_source_xml": digest,
        "identities_with_both_scripts": len(records),
        "of_which_persons": n_person,
        "of_which_organisations": len(records) - n_person,
        "exclusions": [
            "LowQuality (weak) aliases excluded — frequently partial names or nicknames",
            "Nickname name-parts excluded",
            "vessels and aircraft excluded — IMO number is the stable key, not the name "
            "(docs/domain-notes.md §6)",
            "DocumentedNames mixing scripts within one name excluded as unrenderable",
        ],
        "licence": "US Government work, published for public compliance use. "
                   "[VERIFY current terms at https://ofac.treasury.gov before "
                   "redistributing this extract in a published benchmark]",
        "language_field_note": "OFAC records script, not language. `language` is inferred "
                               "from Cyrillic letter inventory; `language_basis` records "
                               "the evidence. Not ground truth.",
    }
    (OUT / f"ofac-sdn-extract-{published}.meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {out_path} ({len(records)} identities, {n_person} persons)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
