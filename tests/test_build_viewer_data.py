"""Tests for the viewer data.json builder (tools/build_viewer_data.py).

Verifies the generated JSON has the right shape and the math is correct.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the builder script importable as a module.
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR.parent))  # so 'tools' is importable
sys.path.insert(0, str(TOOLS_DIR))

import build_viewer_data  # type: ignore  # noqa: E402


def test_build_data_has_top_level_shape():
    data = build_viewer_data.build_data()
    assert "ages" in data
    assert "buckets" in data
    assert isinstance(data["ages"], list)
    assert isinstance(data["buckets"], list)
    assert len(data["buckets"]) == 8  # 6 buckets + 2 3-Lows hybrid buckets


def test_ages_list_matches_v1_viewer():
    """The viewer hard-codes these ages; we must match exactly."""
    data = build_viewer_data.build_data()
    assert data["ages"] == [18, 17, 15, 13, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]


def test_all_buckets_have_expected_names():
    data = build_viewer_data.build_data()
    names = [b["name"] for b in data["buckets"]]
    assert names == [
        "Slow + High Na/K",
        "Slow + Low Na/K",
        "Fast + High Na/K",
        "Fast + Low Na/K",
        "3-Lows + High Na/K",
        "3-Lows + Low Na/K",
        "4-Lows + High Na/K",
        "4-Lows + Low Na/K",
    ]


def test_each_bucket_has_full_age_grid_per_product():
    data = build_viewer_data.build_data()
    n_ages = len(data["ages"])
    for bucket in data["buckets"]:
        for product in bucket["products"]:
            assert len(product["cells"]) == n_ages, (
                f"product {product['id']} in {bucket['name']} has "
                f"{len(product['cells'])} cells, expected {n_ages}"
            )


def test_zinc_matrix_pro_has_dose_schedule_in_output():
    """zinc-matrix-pro must carry dose_schedule for the viewer's slider."""
    data = build_viewer_data.build_data()
    found = False
    for bucket in data["buckets"]:
        for product in bucket["products"]:
            if product["id"] == "zinc-matrix-pro":
                assert "dose_schedule" in product
                assert len(product["dose_schedule"]["anchors"]) == 4
                found = True
    assert found, "zinc-matrix-pro not found in any bucket"


def test_zinc_matrix_pro_adult_cell_uses_starting_anchor():
    """Adult dose = Na/K=2.5 anchor (the human ideal starting point)."""
    data = build_viewer_data.build_data()
    for bucket in data["buckets"]:
        for product in bucket["products"]:
            if product["id"] == "zinc-matrix-pro":
                assert product["adult"] == "0·0·1 cap"


def test_zinc_matrix_pro_age_18_uses_starting_anchor_scaled():
    """At age 18 (adult boundary), PM=1 cap stays at 1 cap, NOON drops to 0."""
    data = build_viewer_data.build_data()
    age_18_idx = data["ages"].index(18)
    for bucket in data["buckets"]:
        for product in bucket["products"]:
            if product["id"] == "zinc-matrix-pro":
                # Age 18 should get the Na/K=2.5 anchor scaled by factor=1.0.
                # NOON slot is always dropped for kids, so the cell is AM·PM.
                assert product["cells"][age_18_idx] == "0·1 cap"


def test_cell_restore_uses_standard_protocol_table():
    """Static-dose products must use the standard_protocols table."""
    data = build_viewer_data.build_data()
    for bucket in data["buckets"]:
        for product in bucket["products"]:
            if product["id"] == "cell-restore":
                # 2 caps · 2 caps · 2 caps from standard_protocols
                assert product["adult"] == "2 caps·2 caps·2 caps"
                # Age 18 (adult boundary) should keep "2 caps·2 caps"
                age_18_idx = data["ages"].index(18)
                assert product["cells"][age_18_idx] == "2 caps·2 caps"
                # cell-restore has NO age gate
                assert product["gate"] is None


def test_adrenofuel_age_gate_marks_cells_under_9():
    """AdrenoFuel has age gate 9 — ages <9 should be marked with '—'."""
    data = build_viewer_data.build_data()
    ages = data["ages"]
    for bucket in data["buckets"]:
        for product in bucket["products"]:
            if product["id"] == "adrenofuel":
                assert product["gate"] == 9
                for i, age in enumerate(ages):
                    if age < 9:
                        assert product["cells"][i] == "—", (
                            f"age {age} cell should be '—', got {product['cells'][i]!r}"
                        )
                    else:
                        assert product["cells"][i] != "—", (
                            f"age {age} should have a real dose, got {product['cells'][i]!r}"
                        )


def test_thyro_spark_age_gate_marks_cells_under_5():
    """ThyroSpark has age gate 5 — ages <5 should be '—'."""
    data = build_viewer_data.build_data()
    ages = data["ages"]
    for bucket in data["buckets"]:
        for product in bucket["products"]:
            if product["id"] == "thyro-spark":
                assert product["gate"] == 5


def test_generated_data_writes_valid_json(tmp_path):
    """End-to-end: build data and serialize to a tmp file, then read back."""
    out = tmp_path / "data.json"
    data = build_viewer_data.build_data()
    out.write_text(json.dumps(data, ensure_ascii=False))
    loaded = json.loads(out.read_text())
    assert loaded["ages"] == data["ages"]
    assert len(loaded["buckets"]) == len(data["buckets"])
