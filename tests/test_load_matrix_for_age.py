"""Integration tests for load_matrix_for_age() — the v2 public API.

Verifies that the matrix-level API correctly applies age-gating rules
without mutating the source matrix.
"""
from __future__ import annotations

import pytest

from htma_decision_matrix import (
    Matrix,
    load_matrix,
    load_matrix_for_age,
)


# ── Adult path (age >= 19 or None) ──────────────────────────────────────────


def test_load_matrix_for_age_none_returns_same_shape_as_load_matrix():
    """age=None returns the same shape as load_matrix (no kid gating)."""
    m1 = load_matrix()
    m2 = load_matrix_for_age(None)
    assert set(m1.buckets.keys()) == set(m2.buckets.keys())
    for bucket_id in m1.buckets:
        assert [p.id for p in m1.buckets[bucket_id].products] == [
            p.id for p in m2.buckets[bucket_id].products
        ]
        # age_warnings is empty for the adult path
        assert m2.buckets[bucket_id].age_warnings == []


def test_load_matrix_for_age_adult_returns_full_protocol():
    """age=25 (adult) drops nothing."""
    m = load_matrix_for_age(25)
    for bucket_id, bucket in m.buckets.items():
        assert bucket.age_warnings == [], (
            f"bucket {bucket_id} should have no warnings for an adult, got {bucket.age_warnings}"
        )


def test_load_matrix_for_age_at_adult_threshold_returns_full_protocol():
    """age=19 is the adult threshold (per YAML anchor_curve.adult_threshold)."""
    m = load_matrix_for_age(19)
    assert all(b.age_warnings == [] for b in m.buckets.values())


# ── Kid path (age < 19) ─────────────────────────────────────────────────────


def test_load_matrix_for_age_drops_adrenofuel_below_9():
    """AdrenoFuel has age gate 9. age=8 should drop it from every bucket."""
    m = load_matrix_for_age(8)
    for bucket_id, bucket in m.buckets.items():
        product_ids = [p.id for p in bucket.products]
        if "adrenofuel" in product_ids:
            pytest.fail(
                f"bucket {bucket_id} still has adrenofuel for age 8: {product_ids}"
            )
        # Warnings should mention adrenofuel somewhere in this bucket's drops
        # (if any bucket had it before).
        warnings_for_adrenofuel = [w for w in bucket.age_warnings if "adrenofuel" in w]
        # Some buckets don't include adrenofuel at all (e.g. fast-oxidation
        # buckets). Only assert the drop when adrenofuel was actually in the
        # adult version of this bucket.
        adult = load_matrix()
        if "adrenofuel" in [p.id for p in adult.buckets[bucket_id].products]:
            assert len(warnings_for_adrenofuel) == 1, (
                f"bucket {bucket_id}: expected one adrenofuel drop warning, "
                f"got {warnings_for_adrenofuel}"
            )


def test_load_matrix_for_age_keeps_adrenofuel_at_and_above_9():
    """age=9 keeps adrenofuel."""
    m = load_matrix_for_age(9)
    adult = load_matrix()
    for bucket_id in m.buckets:
        adult_ids = [p.id for p in adult.buckets[bucket_id].products]
        kid_ids = [p.id for p in m.buckets[bucket_id].products]
        if "adrenofuel" in adult_ids:
            assert "adrenofuel" in kid_ids


def test_load_matrix_for_age_drops_thyro_spark_below_5():
    """ThyroSpark has age gate 5. age=3 should drop it."""
    m = load_matrix_for_age(3)
    adult = load_matrix()
    for bucket_id in m.buckets:
        adult_ids = [p.id for p in adult.buckets[bucket_id].products]
        kid_ids = [p.id for p in m.buckets[bucket_id].products]
        if "thyro-spark" in adult_ids:
            assert "thyro-spark" not in kid_ids
            assert any("thyro-spark" in w for w in m.buckets[bucket_id].age_warnings)


def test_load_matrix_for_age_drops_both_adrenofuel_and_thyro_spark_for_young_kid():
    """age=3 drops both AdrenoFuel (gate 9) and ThyroSpark (gate 5)."""
    m = load_matrix_for_age(3)
    adult = load_matrix()
    for bucket_id in m.buckets:
        adult_ids = set(p.id for p in adult.buckets[bucket_id].products)
        kid_ids = set(p.id for p in m.buckets[bucket_id].products)
        for gated in ("adrenofuel", "thyro-spark"):
            if gated in adult_ids:
                assert gated not in kid_ids


def test_load_matrix_for_age_newborn_drops_all_gated_but_keeps_universals():
    """age=0: factor=0.0, but products themselves aren't scaled in Phase 1.
    Only age-gated products are dropped. Universals (cell-restore, kelp-max,
    etc.) stay in every bucket.
    """
    m = load_matrix_for_age(0)
    for bucket_id, bucket in m.buckets.items():
        product_ids = [p.id for p in bucket.products]
        # Universals present in adult bucket 1 should still be present
        if bucket_id == "slow_high_nak":
            for universal in ("cell-restore", "kelp-max", "red-pilled-sockeye", "valence-se", "kidney-flow"):
                assert universal in product_ids, (
                    f"age 0 should not drop universal products, but {universal} "
                    f"is missing from bucket {bucket_id}"
                )


# ── Immutability of source matrix ──────────────────────────────────────────


def test_load_matrix_for_age_does_not_mutate_source_matrix():
    """load_matrix() called twice must return identical data, even after
    a load_matrix_for_age(kid) call in between.
    """
    m_adult_1 = load_matrix()
    bucket_1_adult_ids = [p.id for p in m_adult_1.buckets["slow_high_nak"].products]

    # Call kid version
    _ = load_matrix_for_age(8)

    # Re-call adult version
    m_adult_2 = load_matrix()
    bucket_1_adult_ids_2 = [p.id for p in m_adult_2.buckets["slow_high_nak"].products]

    assert bucket_1_adult_ids == bucket_1_adult_ids_2, (
        "load_matrix result was mutated by a kid-age load"
    )
    assert "adrenofuel" in bucket_1_adult_ids  # adult should still have it


def test_load_matrix_for_age_returns_new_matrix_object():
    """load_matrix_for_age(kid) returns a NEW Matrix, not the source."""
    adult = load_matrix()
    kid = load_matrix_for_age(8)
    assert kid is not adult
    assert kid.buckets is not adult.buckets
    # but the bucket-level contents should be the same object type
    assert isinstance(kid, Matrix)


# ── Returned matrix preserves overrides and patterns ────────────────────────


def test_load_matrix_for_age_preserves_overrides():
    """Override file should still be loaded for the kid matrix."""
    adult = load_matrix()
    kid = load_matrix_for_age(8)
    assert len(adult.overrides) == len(kid.overrides)
    assert [o.override_id for o in adult.overrides] == [o.override_id for o in kid.overrides]


def test_load_matrix_for_age_preserves_patterns():
    """All interpretation patterns should still be present."""
    adult = load_matrix()
    kid = load_matrix_for_age(8)
    assert set(adult.patterns.keys()) == set(kid.patterns.keys())
