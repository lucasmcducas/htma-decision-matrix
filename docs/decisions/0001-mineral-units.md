# 0001 — Mineral units (mg% vs ppm)

**Date:** 2026-09-08
**Status:** Accepted
**Drives:** fixture naming, ratio computation, ARL data ingestion

## Context

Wilson's published reference (MIN.IDEALS.htm, Oct 2025) and every threshold quoted in
`drlwilson-extraction.md` are in **mg%** (milligrams percent — milligrams per 100 grams of
hair). ARL's lab reports come back in **ppm** (parts per million — milligrams per kilogram),
where `mg% = ppm / 10`.

The Dart pattern engine in `htma_labs/lib/core/wilson/pattern_detector.dart` was built
against the ARL data, so its mineral fields are named `_ppm` despite holding mg%-scaled
values. To stay byte-compatible with the engine and not lose the Wilson reference, this
repo follows the same convention.

## Decision

- All numeric mineral values in fixtures, ratios, and threshold YAMLs are in **mg%**.
- Fixture keys are named `*_ppm` for historical compatibility with the Dart engine.
- The ratio computation is unit-less: a ppm reading and a mg% reading yield the same
  ratio as long as both are in the same units. The ratios in fixtures and thresholds
  match.
- A docstring at the top of every fixture and the README's "Units" section call this out.
- The pipeline-side conversion happens in `lab_pipeline`, not in the matrix.

## Consequences

- New contributors may briefly confuse `ppm` (the name) with `ppm` (the unit). The
  docstring and README both warn about this.
- When ARL ships true ppm (mg/kg) data, the pipeline must divide by 10 before applying
  these YAMLs. That conversion is a single, well-isolated step in `lab_pipeline`.

## Alternatives considered

- Rename everything `*_mgpct` and break the Dart engine. Rejected — would require a
  one-line data model change in Dart, with knock-on effects across the bridge.
- Store two keys per mineral (`*_ppm` and `*_mgpct`). Rejected — duplicate data, two
  places to drift apart.
