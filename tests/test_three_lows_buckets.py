"""Tests for the new 3-Lows hybrid buckets + adult_dose_overrides field.

The 3-Lows hybrid sits between slow-ox and true 4-Lows on the depletion
spectrum (per Luke 2026-09-12). 8 buckets total (slow × 2, fast × 2,
3-Lows × 2, 4-Lows × 2).
"""
from __future__ import annotations

import pytest

from htma_decision_matrix import load_matrix
from htma_decision_matrix.loader import Matrix


def test_eight_buckets_total():
    """8 buckets: slow × 2, fast × 2, 3-Lows × 2, 4-Lows × 2."""
    m = load_matrix()
    assert len(m.buckets) == 8, f"expected 8 buckets, got {len(m.buckets)}"


def test_three_lows_buckets_exist_with_correct_ids():
    m = load_matrix()
    assert "three_lows_high_nak" in m.buckets
    assert "three_lows_low_nak" in m.buckets


def test_three_lows_high_nak_has_cal_mag_fusion():
    m = load_matrix()
    b = m.buckets["three_lows_high_nak"]
    product_ids = [p.id for p in b.products]
    assert "cal-mag-fusion" in product_ids


def test_three_lows_low_nak_has_na_k_up_not_zinc():
    m = load_matrix()
    b = m.buckets["three_lows_low_nak"]
    product_ids = [p.id for p in b.products]
    assert "na-k-up" in product_ids
    assert "zinc-matrix-pro" not in product_ids


def test_three_lows_buckets_have_slowox_and_thyro_spark_no_adrenofuel():
    """Per Luke 2026-09-12: 3-Lows gets slowox + thyro-spark, no adrenofuel."""
    m = load_matrix()
    for bid in ("three_lows_high_nak", "three_lows_low_nak"):
        product_ids = [p.id for p in m.buckets[bid].products]
        assert "slowox" in product_ids, f"{bid} missing slowox"
        assert "thyro-spark" in product_ids, f"{bid} missing thyro-spark"
        assert "adrenofuel" not in product_ids, f"{bid} has adrenofuel (should omit)"


def test_three_lows_cal_mag_fusion_adult_dose_override():
    """3-Lows cal-mag-fusion: 4·4·4 (per Luke 2026-09-12).

    Verified via adult_dose_overrides field on the bucket — the
    SupplementBucket dataclass carries it through to the viewer.
    """
    m = load_matrix()
    b = m.buckets["three_lows_high_nak"]
    assert "cal-mag-fusion" in b.adult_dose_overrides
    override = b.adult_dose_overrides["cal-mag-fusion"]
    assert override == {"am": "4 caps", "noon": "4 caps", "pm": "4 caps"}


def test_three_lows_slowox_thyro_spark_dose_overrides():
    m = load_matrix()
    for bid in ("three_lows_high_nak", "three_lows_low_nak"):
        b = m.buckets[bid]
        for product_id in ("slowox", "thyro-spark"):
            assert product_id in b.adult_dose_overrides, (
                f"{bid} missing {product_id} override"
            )
            assert b.adult_dose_overrides[product_id] == {
                "am": "1 cap", "noon": "0", "pm": "0",
            }


def test_four_lows_cal_mag_fusion_adult_dose_override():
    """4-Lows cal-mag-fusion: 7·7·7 (per Luke 2026-09-12 session override).

    Originally the override lived in Luke's localStorage. This test
    pins the value to the bucket YAML so fresh sessions open with
    the right defaults.
    """
    m = load_matrix()
    for bid in ("four_lows_high_nak", "four_lows_low_nak"):
        b = m.buckets[bid]
        assert b.adult_dose_overrides["cal-mag-fusion"] == {
            "am": "7 caps", "noon": "7 caps", "pm": "7 caps",
        }


def test_slow_ox_buckets_have_no_adult_dose_overrides():
    """Slow-ox cal-mag-fusion stays at the standard 2·2·2 — no override."""
    m = load_matrix()
    for bid in ("slow_high_nak", "slow_low_nak", "fast_high_nak", "fast_low_nak"):
        b = m.buckets[bid]
        assert b.adult_dose_overrides == {}, (
            f"{bid} unexpectedly has adult_dose_overrides: {b.adult_dose_overrides}"
        )


def test_oxidation_enum_includes_three_lows():
    """The bucket.schema.json oxidation enum was extended to 'three_lows'."""
    import json
    from pathlib import Path
    schema = json.loads(
        Path(__file__).resolve().parent.parent.joinpath(
            "schemas/bucket.schema.json"
        ).read_text()
    )
    enum = schema["properties"]["oxidation"]["enum"]
    assert "three_lows" in enum
    assert "four_lows" in enum  # sanity: not removed


def test_bucket_id_enum_includes_three_lows_both_bands():
    import json
    from pathlib import Path
    schema = json.loads(
        Path(__file__).resolve().parent.parent.joinpath(
            "schemas/bucket.schema.json"
        ).read_text()
    )
    enum = schema["properties"]["bucket_id"]["enum"]
    assert "three_lows_high_nak" in enum
    assert "three_lows_low_nak" in enum


def test_three_lows_doses_render_correctly_in_data_json():
    """End-to-end: build_data → data.json shows the 3-Lows doses."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from tools import build_viewer_data

    data = build_viewer_data.build_data()
    by_name = {b["name"]: b for b in data["buckets"]}

    # 3-Lows + High Na/K: cal-mag 4·4·4, slowox 1·0·0, thyro-spark 1·0·0
    b = by_name["3-Lows + High Na/K"]
    cal = next(p for p in b["products"] if p["id"] == "cal-mag-fusion")
    assert cal["adult"] == "4 caps·4 caps·4 caps"
    sox = next(p for p in b["products"] if p["id"] == "slowox")
    assert sox["adult"] == "1 cap·0·0"
    ts = next(p for p in b["products"] if p["id"] == "thyro-spark")
    assert ts["adult"] == "1 cap·0·0"

    # 4-Lows cal-mag 7·7·7 (Luke's clinical-practice value, baked into YAML)
    b4 = by_name["4-Lows + High Na/K"]
    cal4 = next(p for p in b4["products"] if p["id"] == "cal-mag-fusion")
    assert cal4["adult"] == "7 caps·7 caps·7 caps"

    # Slow-ox cal-mag stays at standard 2·2·2 (no override)
    b1 = by_name["Slow + High Na/K"]
    cal1 = next(p for p in b1["products"] if p["id"] == "cal-mag-fusion")
    assert cal1["adult"] == "2 caps·2 caps·2 caps"
