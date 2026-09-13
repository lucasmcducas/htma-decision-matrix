"""Tests for HTMA Standard Protocols — per-product default doses."""
from __future__ import annotations

import pytest

from htma_decision_matrix import standard_protocols


def test_loads_table_with_expected_count():
    """17 products in the standard protocols table (per Luke 2026-09-08)."""
    products = standard_protocols.all_products()
    # We have 17 entries (slowox, fast-oxidizer, fastcalm, valence-fastcalm,
    # adrenofuel, thyro-spark, cal-mag-fusion, zinc-matrix-pro, na-k-up,
    # bile-flow-plus, cell-restore, valence-d3-k2, kelp-max,
    # red-pilled-sockeye, valence-se, kidney-flow, nervcalm).
    assert len(products) == 17


@pytest.mark.parametrize(
    "product_id,expected",
    [
        ("slowox", ("1 cap", "1 cap", "1 cap")),
        ("cal-mag-fusion", ("2 caps", "2 caps", "2 caps")),
        ("cell-restore", ("2 caps", "2 caps", "2 caps")),
        ("valence-d3-k2", ("0", "0", "1 cap")),
        ("red-pilled-sockeye", ("0", "0", "1 cap")),
    ],
)
def test_known_product_doses(product_id, expected):
    assert standard_protocols.get(product_id) == expected


def test_get_unknown_product_returns_none():
    assert standard_protocols.get("not-a-product") is None


def test_format_dose_string_uses_center_dot():
    assert standard_protocols.format_dose_string(("1 cap", "1 cap", "1 cap")) == "1 cap·1 cap·1 cap"
    assert standard_protocols.format_dose_string(("0", "0", "1 cap")) == "0·0·1 cap"
    assert standard_protocols.format_dose_string(("2 caps", "2 caps", "2 caps")) == "2 caps·2 caps·2 caps"


def test_zinc_matrix_pro_fallback_is_starting_anchor():
    """zinc-matrix-pro is in the table as a fallback only — runtime prefers
    dose_schedule. The table value matches the Na/K=2.5 anchor."""
    assert standard_protocols.get("zinc-matrix-pro") == ("1 cap", "0", "1 cap")


def test_na_k_up_fallback_matches_starting_anchor():
    """na-k-up is also a fallback — table value matches low-Na/K starting dose."""
    assert standard_protocols.get("na-k-up") == ("1 cap", "0", "1 cap")
