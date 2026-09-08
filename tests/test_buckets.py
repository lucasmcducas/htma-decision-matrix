"""Enforce the 7 locked supplement rules against the bucket YAMLs and the SD override.

Rules enforced here:
  1. 6 buckets ONLY drive supplements (covered by fixture classification tests below).
  2. Valence products only (covered by the bucket schema's product enum).
  3. All low-Na/K buckets swap Zinc Matrix Pro -> Na/K Up. Never both.
  4. Cell Restore is in all 6 buckets.
  5. SD override exists and applies to bucket 2.
  6. The other 4 contradiction flags (Step Up copper, Four Highs crash, Double High zinc,
     Belligerence Mg) are annotation only — no override file.
  7. Oxidation thresholds (covered by fixture classification tests).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent

SUPPLEMENTS_DIR = REPO / "matrix/supplements"
FIXTURES_DIR = REPO / "tests/fixtures"

LOW_NAK_BUCKETS = [
    SUPPLEMENTS_DIR / "bucket_2_slow_low_nak.yml",
    SUPPLEMENTS_DIR / "bucket_4_fast_low_nak.yml",
    SUPPLEMENTS_DIR / "bucket_6_four_lows_low_nak.yml",
]

ALL_BUCKETS = sorted(SUPPLEMENTS_DIR.glob("bucket_*.yml"))
HIGH_NAK_BUCKETS = [p for p in ALL_BUCKETS if p not in LOW_NAK_BUCKETS]


# ---------------------------------------------------------------------------
# Rule 4: Cell Restore is in all 6 buckets
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bucket_yaml", ALL_BUCKETS, ids=lambda p: p.name)
def test_bucket_has_cell_restore(bucket_yaml: Path) -> None:
    data = yaml.safe_load(bucket_yaml.read_text())
    product_ids = [p["id"] for p in data["products"]]
    assert "cell-restore" in product_ids, (
        f"{bucket_yaml.name} missing Cell Restore (locked rule 4)"
    )


# ---------------------------------------------------------------------------
# Rule 3: low-Na/K buckets use Na/K Up, never Zinc Matrix Pro
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bucket_yaml", LOW_NAK_BUCKETS, ids=lambda p: p.name)
def test_low_nak_bucket_has_na_k_up(bucket_yaml: Path) -> None:
    data = yaml.safe_load(bucket_yaml.read_text())
    product_ids = [p["id"] for p in data["products"]]
    assert "na-k-up" in product_ids, (
        f"{bucket_yaml.name} missing Na/K Up — every low-Na/K bucket must include it "
        "(locked rule 3)"
    )


@pytest.mark.parametrize("bucket_yaml", LOW_NAK_BUCKETS, ids=lambda p: p.name)
def test_low_nak_bucket_has_no_zinc(bucket_yaml: Path) -> None:
    data = yaml.safe_load(bucket_yaml.read_text())
    product_ids = [p["id"] for p in data["products"]]
    assert "zinc-matrix-pro" not in product_ids, (
        f"{bucket_yaml.name} has Zinc Matrix Pro — low-Na/K buckets swap it for Na/K Up "
        "and must never supplement both (locked rule 3)"
    )


@pytest.mark.parametrize("bucket_yaml", HIGH_NAK_BUCKETS, ids=lambda p: p.name)
def test_high_nak_bucket_has_zinc(bucket_yaml: Path) -> None:
    data = yaml.safe_load(bucket_yaml.read_text())
    product_ids = [p["id"] for p in data["products"]]
    assert "zinc-matrix-pro" in product_ids, (
        f"{bucket_yaml.name} missing Zinc Matrix Pro — high-Na/K buckets include zinc "
        "(low-Na/K buckets substitute Na/K Up instead)"
    )


# ---------------------------------------------------------------------------
# Rule 2: Valence products only — no Endomet, no MegaPan, no LimComin
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bucket_yaml", ALL_BUCKETS, ids=lambda p: p.name)
def test_bucket_has_no_endomet_products(bucket_yaml: Path) -> None:
    data = yaml.safe_load(bucket_yaml.read_text())
    product_ids = [p["id"] for p in data["products"]]
    for endomet in ("endomet-megapan", "endomet-limcomin", "endomet-gb3", "endomet-paramin",
                    "endomet-kelp", "endomet-renamide", "endomet-thyro-complex", "endomet-zinc",
                    "endomet-endo-dren", "endomet-epa-dha", "endomet-endo-veggies",
                    "endomet-selenium", "endomet-sbf-formula", "endomet-vitamin-d3",
                    "endomet-taurine", "endomet-stress-pak", "endomet-thym-adren",
                    "endomet-chelated-mag", "endomet-endo-ac", "endomet-enz-aid",
                    "endomet-chromium", "endomet-mchc"):
        assert endomet not in product_ids, (
            f"{bucket_yaml.name} contains Endomet product '{endomet}' — Valence only "
            "(locked rule 2)"
        )


@pytest.mark.parametrize("bucket_yaml", ALL_BUCKETS, ids=lambda p: p.name)
def test_bucket_has_no_classic_brand_ids(bucket_yaml: Path) -> None:
    """Classic Endomet brand names (MegaPan, LimComin) must never appear as product IDs.

    The prose notes that mention 'equivalent of MegaPan' are intentional — they help Luke
    translate between the two catalogs. The test only blocks the IDs themselves.
    """
    data = yaml.safe_load(bucket_yaml.read_text())
    product_ids = [p["id"].lower() for p in data["products"]]
    for forbidden in ("endomet-megapan", "megapan", "endomet-limcomin", "limcomin"):
        assert forbidden not in product_ids, (
            f"{bucket_yaml.name} lists '{forbidden}' as a product ID — use SlowOx "
            "(equivalent of MegaPan) and Na/K Up (equivalent of LimComin) instead "
            "(locked rule 2)"
        )


# ---------------------------------------------------------------------------
# Rule 5: SD override exists, applies to bucket 2 only
# ---------------------------------------------------------------------------

def test_sympathetic_dominance_override_file_exists() -> None:
    override = SUPPLEMENTS_DIR / "sympathetic_dominance_override.yml"
    assert override.exists(), "Missing sympathetic_dominance_override.yml (locked rule 5)"


def test_sd_override_targets_bucket_2() -> None:
    data = yaml.safe_load((SUPPLEMENTS_DIR / "sympathetic_dominance_override.yml").read_text())
    assert data["applies_to_bucket"] == "slow_low_nak", (
        f"SD override must target slow_low_nak (bucket 2), got {data['applies_to_bucket']}"
    )


def test_sd_override_reduces_slowox_and_swaps_adrenofuel() -> None:
    """The two SD-specific supplement changes per Wilson: SlowOx lower, AdrenoFuel -> ThyroSpark."""
    data = yaml.safe_load((SUPPLEMENTS_DIR / "sympathetic_dominance_override.yml").read_text())
    by_replace = {ov["replace"]: ov for ov in data["overrides"]}

    assert "slowox" in by_replace, "SD override must modify SlowOx"
    assert by_replace["slowox"]["dose_modifier"] == "lower", (
        "SD override must reduce SlowOx (Wilson's MegaPan 2-2-2 -> 1-1-1)"
    )

    assert "adrenofuel" in by_replace, "SD override must modify AdrenoFuel"
    assert by_replace["adrenofuel"]["with"] == "thyro-spark", (
        "SD override must swap AdrenoFuel for ThyroSpark (Wilson's Thyro-Complex for Endo-dren)"
    )


# ---------------------------------------------------------------------------
# Rule 6: The other 4 contradiction flags are annotation-only (no override file)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("forbidden_file,forbidden_flag", [
    ("step_up_copper_override.yml",        "Step Up copper"),
    ("four_highs_crash_landing_override.yml", "Four Highs crash-landing"),
    ("double_high_zinc_override.yml",      "Double High zinc emphasis"),
    ("belligerence_mg_override.yml",       "Belligerence Mg dose"),
])
def test_no_override_files_for_other_contradiction_flags(forbidden_file: str, forbidden_flag: str) -> None:
    """These 4 are chart-annotation only (locked rule 6)."""
    assert not (SUPPLEMENTS_DIR / forbidden_file).exists(), (
        f"Found {forbidden_file} — '{forbidden_flag}' must be annotation only, "
        "no supplement override (locked rule 6)"
    )


# ---------------------------------------------------------------------------
# Rule 1 + 7: Oxidation classifier + 6-bucket structure
# ---------------------------------------------------------------------------

def _classify_panel(data: dict) -> dict:
    """Mirror the matrix's classifier logic for fixture-based tests."""
    ca_k = data["ratios"]["ca_k"]
    na_k = data["ratios"]["na_k"]
    na_mg = data["ratios"]["na_mg"]
    m = data["minerals"]
    is_four_lows = all([
        m["ca_ppm"] < 40, m["mg_ppm"] < 6,
        m["na_ppm"] < 25, m["k_ppm"] < 10,
    ])
    if is_four_lows:
        oxidation = "four_lows"
    elif ca_k > 4 and na_mg < 4.17:
        oxidation = "slow"
    elif ca_k < 4 and na_mg > 4.17:
        oxidation = "fast"
    else:
        # Mixed: whichever is more extreme from ideal
        slow_distance = (ca_k - 4) + (4.17 - na_mg)
        fast_distance = (4 - ca_k) + (na_mg - 4.17)
        oxidation = "slow" if slow_distance > fast_distance else "fast"

    na_k_band = "above_2.5" if na_k > 2.5 else "below_2.5"
    return {
        "oxidation": oxidation,
        "na_k_band": na_k_band,
        "bucket_id": f"{oxidation}_{'high' if na_k_band == 'above_2.5' else 'low'}_nak",
    }


@pytest.mark.parametrize(
    "fixture_path",
    sorted(FIXTURES_DIR.glob("*.json")),
    ids=lambda p: p.name,
)
def test_fixture_classifies_to_expected_bucket(fixture_path: Path) -> None:
    """Rule 1 (6 buckets) + Rule 7 (oxidation thresholds)."""
    data = json.loads(fixture_path.read_text())
    classified = _classify_panel(data)
    expected = data["expected_classification"]
    assert classified["bucket_id"] == expected["bucket_id"], (
        f"{fixture_path.name}: classifier produced {classified['bucket_id']}, "
        f"fixture expected {expected['bucket_id']}"
    )
    assert classified["oxidation"] == expected["oxidation"], (
        f"{fixture_path.name}: oxidation mismatch — {classified['oxidation']} vs "
        f"{expected['oxidation']}"
    )
    assert classified["na_k_band"] == expected["na_k_band"], (
        f"{fixture_path.name}: Na/K band mismatch — {classified['na_k_band']} vs "
        f"{expected['na_k_band']}"
    )


def test_six_buckets_exist() -> None:
    """Rule 1: exactly 6 supplement buckets."""
    buckets = sorted(SUPPLEMENTS_DIR.glob("bucket_*.yml"))
    assert len(buckets) == 6, f"Expected 6 buckets, found {len(buckets)}"
    expected_ids = {
        "slow_high_nak", "slow_low_nak",
        "fast_high_nak", "fast_low_nak",
        "four_lows_high_nak", "four_lows_low_nak",
    }
    found_ids = {yaml.safe_load(b.read_text())["bucket_id"] for b in buckets}
    assert found_ids == expected_ids, f"Bucket IDs mismatch: {found_ids} vs {expected_ids}"
