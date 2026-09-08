# htma-decision-matrix

**Source of truth** for HTMA (hair tissue mineral analysis) interpretation and supplement
recommendations. Everything a report says about a client is derived from the YAML in this repo.

## Why this repo exists

Before this repo, Wilson's rules lived in three incompatible places: the Dart pattern engine
(`htma_labs/lib/core/wilson/pattern_detector.dart`), the platform's JS bundle, and Luke's head.
This repo is the single, reviewable, version-controlled definition.

- **YAML files are edited by Luke** (the practitioner). No code changes required to tune a bucket,
  a threshold, or a piece of prose.
- **JSON Schemas validate them** (`schemas/`), so a typo fails CI instead of shipping to a client.
- **`lab_pipeline` loads them at runtime.** The pipeline contains no clinical rules of its own.

## Two parallel products

| Product | Directory | Drives |
|---|---|---|
| **Interpretation patterns** | `matrix/patterns/` | Chart annotations, prose, severity scoring |
| **Supplement buckets** | `matrix/supplements/` | The Valence product list on the report |

These are deliberately decoupled. A client can carry ten interpretation patterns (calcium shell,
bowl, poor eliminator, spiritual defensiveness…) and still receive exactly the supplement list of
their one bucket.

## The 7 locked rules

1. **6 buckets ONLY drive supplements** — `{slow, fast, four_lows} × {Na/K above 2.5, below 2.5}`.
   No other pattern adds, removes, or re-doses a product.
2. **Valence products only.** No Endomet brand IDs. No MegaPan (SlowOx is the equivalent).
   No LimComin (Na/K Up is the equivalent).
3. **Every low-Na/K bucket swaps Zinc Matrix Pro → Na/K Up.** Never both in one list.
4. **Cell Restore is in all 6 buckets** (universal methylation support).
5. **Sympathetic Dominance is the only supplement override** — a separate file
   (`matrix/supplements/sympathetic_dominance_override.yml`) that annotates bucket 2 only:
   SlowOx at a lower dose, AdrenoFuel → ThyroSpark.
6. **The other 4 contradiction flags are chart annotations only** — Step Up copper, Four Highs
   crash-landing, Double High zinc, Belligerence magnesium. They never touch the product list.
7. **Oxidation thresholds:** slow = `Ca/K > 4 AND Na/Mg < 4.17`; fast = `Ca/K < 4 AND Na/Mg > 4.17`;
   mixed = the two ratios disagree, classify by whichever is more extreme;
   four_lows = `Ca < 40 AND Mg < 6 AND Na < 25 AND K < 10 mg%`.

All 7 are enforced by tests in `tests/`, not just by documentation.

## Layout

```
matrix/
  supplements/   bucket_1..6_*.yml  + sympathetic_dominance_override.yml
  patterns/      oxidation.yml + 10 interpretation-only patterns
  prose/         (Phase 1) long-form report copy per bucket/pattern
  severity/      (Phase 1) quantification tiers (Wilson's 1x/2x/3x multipliers)
schemas/         bucket / pattern / override JSON Schemas (Draft 2020-12)
tests/
  fixtures/      real panels with expected classification
  test_panels/   (Phase 1) raw ARL PDF-derived panels
docs/
  sources/       Wilson extraction provenance
  decisions/     ADRs for every deviation from Wilson's published advice
```

## Units

All mineral values are **mg%** (Wilson's convention). ARL reports in ppm; `mg% = ppm / 10`.
Fixture keys are named `*_ppm` for historical compatibility with the Dart engine but hold **mg%**
values — see `docs/decisions/0001-mineral-units.md`.

## Running the tests

```bash
/home/luke/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/ -v
```

## Sources

- Wilson book extraction: `~/.hermes/plans/2026-09-08-wilson-book-extraction.md`
- drlwilson.com extraction: `~/.hermes/plans/2026-09-08-drlwilson-extraction.md`
- Locked rules / synthesis: `~/.hermes/plans/2026-09-08_133000-synthesis-for-luke.md`
- Existing Dart engine (threshold parity): `htma_labs/lib/core/wilson/pattern_detector.dart`
- Canonical Valence product IDs: `htma_app_bridge/syncers/protocols.py`
