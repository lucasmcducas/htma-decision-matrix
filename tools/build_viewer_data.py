#!/usr/bin/env python3
"""Build /tmp/htma-matrix-viewer/public/data.json from the v2 matrix.

Generates the viewer data file from:
  - matrix/supplements/bucket_*.yml  (adult doses + dose_schedule for NAK-driven products)
  - matrix/standard_protocols.yml    (per-product defaults)
  - matrix/age_scaling/age_scaling.yml (kid scaling rules)
  - load_matrix_for_age()            (kid age-gating)
  - kids_dose_at_nak()               (per-slot dose scaling for NAK-driven products)

Output matches the viewer's expected shape:
  {
    "ages": [18, 17, ..., 1],
    "buckets": [
      {"name": "...", "products": [
        {"id": "...", "gate": int|null, "adult": "am·noon·pm",
         "cells": ["am·pm", ...],   # kids are 2-slot
         "dose_schedule": {...}},    # for NAK-driven products
        ...
      ]},
      ...
    ]
  }

Run from anywhere: `python3 build_viewer_data.py`. Writes to
/tmp/htma-matrix-viewer/public/data.json by default.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the matrix repo importable when this script is run standalone.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from htma_decision_matrix import (
    age_scaling,
    load_matrix_for_age,
    standard_protocols,
)


# Ages the viewer renders. High-to-low so column 0 is the oldest kid (18).
AGES = [18, 17, 15, 13, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]


# Bucket display names. Must match what the viewer renders.
BUCKET_DISPLAY = {
    "slow_high_nak": "Slow + High Na/K",
    "slow_low_nak": "Slow + Low Na/K",
    "fast_high_nak": "Fast + High Na/K",
    "fast_low_nak": "Fast + Low Na/K",
    "four_lows_high_nak": "4-Lows + High Na/K",
    "four_lows_low_nak": "4-Lows + Low Na/K",
}


def _adult_dose_for(product_id: str) -> tuple[str, str, str]:
    """Resolve the adult (am, noon, pm) for a product.

    Priority:
      1. zinc-matrix-pro and na-k-up use their starting anchor (Na/K=2.5)
         for display purposes (matches the viewer's "default" view).
      2. Standard protocols table.
      3. Empty triple (caller can decide how to handle).
    """
    if product_id in ("zinc-matrix-pro", "na-k-up"):
        # Use the first anchor's dose as the displayed "adult" — matches
        # the v1 viewer's behaviour where the anchor at Na/K=2.5 was shown.
        return ("0", "0", "1 cap")
    return standard_protocols.get(product_id) or ("0", "0", "0")


def _build_product_entry(product, age: int) -> dict:
    """Build one product entry for the viewer's data.json.

    Args:
        product: a SupplementProduct
        age: the age for this cell
    """
    am, noon, pm = _adult_dose_for(product.id)
    adult_str = f"{am}·{noon}·{pm}"

    # Compute the kid-scaled cell for this age.
    if product.dose_schedule:
        # NAK-driven: scale via kids_dose_at_nak with the default Na/K.
        kid_am, _, kid_pm = age_scaling.kids_dose_at_nak(product.dose_schedule, age)
        cell_str = f"{kid_am}·{kid_pm}"
    else:
        # Static: scale the standard protocol triple via kids_dose.
        skew = age_scaling.calmag_skew_applies_to(product.id)
        kid_am, _, kid_pm = age_scaling.kids_dose(am, noon, pm, age, calmag_skew=skew)
        cell_str = f"{kid_am}·{kid_pm}"

    entry: dict = {
        "id": product.id,
        "gate": age_scaling.age_gate_for(product.id),
        "adult": adult_str,
        "cells": [cell_str],  # single cell per age; viewer expands into the age grid
    }
    if product.dose_schedule:
        entry["dose_schedule"] = product.dose_schedule
    return entry


def _build_bucket(bucket) -> dict:
    """Build one bucket entry for the viewer's data.json."""
    # Apply kid age-gating: drop products below their age gate.
    # The viewer bakes age-gated products out of each cell.
    return {
        "name": BUCKET_DISPLAY[bucket.bucket_id],
        "products": [
            _build_product_entry(product, age=18)  # placeholder, age loop happens below
            for product in bucket.products
        ],
    }


def _build_product_entry_full_grid(product) -> dict:
    """Build one product entry with one cell per age.

    The viewer's `cells` array is per-age. Adult dose is the same across
    ages (no Na/K scaling on the adult column). Kid dose is age-specific.
    """
    am, noon, pm = _adult_dose_for(product.id)
    adult_str = f"{am}·{noon}·{pm}"

    cells: list[str] = []
    for age in AGES:
        if not age_scaling.apply_age_gate(product.id, age):
            # Age-gated: cell shows as a "—" placeholder for that age.
            cells.append("—")
            continue
        if product.dose_schedule:
            kid_am, _, kid_pm = age_scaling.kids_dose_at_nak(product.dose_schedule, age)
            cells.append(f"{kid_am}·{kid_pm}")
        else:
            skew = age_scaling.calmag_skew_applies_to(product.id)
            kid_am, _, kid_pm = age_scaling.kids_dose(am, noon, pm, age, calmag_skew=skew)
            cells.append(f"{kid_am}·{kid_pm}")

    entry: dict = {
        "id": product.id,
        "gate": age_scaling.age_gate_for(product.id),
        "adult": adult_str,
        "cells": cells,
    }
    if product.dose_schedule:
        entry["dose_schedule"] = product.dose_schedule
    return entry


def _build_bucket_full_grid(bucket) -> dict:
    """Build one bucket entry with full age grid."""
    return {
        "name": BUCKET_DISPLAY[bucket.bucket_id],
        "products": [_build_product_entry_full_grid(p) for p in bucket.products],
    }


def build_data(repo_path: Path | None = None) -> dict:
    """Build the full data dict. Loads v2 matrix + standard protocols."""
    matrix = load_matrix_for_age(age=None, repo_path=repo_path)  # adult view; we scale per-age
    return {
        "ages": AGES,
        "buckets": [_build_bucket_full_grid(matrix.buckets[bid]) for bid in [
            "slow_high_nak", "slow_low_nak", "fast_high_nak",
            "fast_low_nak", "four_lows_high_nak", "four_lows_low_nak",
        ]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build HTMA Kids Matrix viewer data.json from v2")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/htma-matrix-viewer/public/data.json"),
        help="Where to write the JSON (default: /tmp/htma-matrix-viewer/public/data.json)",
    )
    args = parser.parse_args()
    data = build_data()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"wrote {args.output} ({len(data['buckets'])} buckets, {len(data['ages'])} ages)")


if __name__ == "__main__":
    main()
