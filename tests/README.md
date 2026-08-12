# tests/

Three layers, all in CI:

1. **Unit** — normalisation, transliteration rules, phenomenon tagging.
2. **Corpus integrity** — the corpus rebuilds byte-identically from the committed
   snapshots, the manifest checksum agrees with it, and the composition targets hold.
3. **Accuracy gates** — every deterministic baseline is **recomputed from the committed
   corpus** and fails if it drops below a floor in `accuracy_gates.json`, so a refactor
   that quietly costs recall fails the build.

Layer 3 is the one that matters and the one most projects skip. It deliberately does not
read `metrics.json`, which would only prove a JSON file is self-consistent rather than
catching a change to `translit.py` that degraded matching.

Floors are `measured − 0.01`, so a two-point regression fails while library noise does not.
Embedding and LLM baselines are measured but never used as floors — they are not
version-stable, which [`../CLAUDE.md`](../CLAUDE.md) §4 disqualifies from an audited
pipeline.

Regenerate floors only when a change is understood and intended:

```bash
python3 benchmark/harness/make_gates.py --version v1.0
```

**Lowering a floor to make CI pass defeats the entire purpose of the gate.**

The LLM baselines require `ANTHROPIC_API_KEY` and are marked `slow`; CI runs
`-m "not slow"`. Everything else runs offline.
