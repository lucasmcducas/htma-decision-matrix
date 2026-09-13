"""Age-scaled dosing rules — HTMA Kids Matrix v2.

Lifted from lab_pipeline.interpreter.kids_dosing (HTMA Kids Matrix v1,
2026-09-08) and made data-driven: rules live in
matrix/age_scaling/age_scaling.yml so the matrix repo owns both adult
and kid protocols.

Pure functions, no DB or matrix access. Public API mirrors v1 for
search/replace migration:

    is_kid(age) -> bool
    kids_factor(age) -> float
    floor_to_fraction(n) -> float
    format_kid_caps(n) -> str
    parse_caps(s) -> float
    kids_dose(adult_am, adult_noon, adult_pm, age, *, calmag_skew=False)
        -> (am, noon, pm)
    apply_age_gate(product_id, age) -> bool
    age_gate_for(product_id) -> int | None
    drop_age_gated_products(products, age) -> (kept, warnings)

Wiring into a clinical writer lives in the consumer (e.g.
lab_pipeline.interpreter.writer). This module stays self-contained and
importable from any test.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

import yaml


# ── Rules loading ────────────────────────────────────────────────────────────

_RULES_PATH = (
    Path(__file__).resolve().parent.parent / "matrix" / "age_scaling" / "age_scaling.yml"
)


def _load_rules() -> dict:
    return yaml.safe_load(_RULES_PATH.read_text())


_RULES = _load_rules()
_AGE_ANCHORS: tuple[tuple[float, float], ...] = tuple(
    (p["age"], p["factor"]) for p in _RULES["anchor_curve"]["points"]
)
_ADULT_THRESHOLD: int = _RULES["anchor_curve"]["adult_threshold"]
_NEWBORN_THRESHOLD: int = _RULES["anchor_curve"]["newborn_threshold"]
_FRACTION_VALUES: dict[str, float] = _RULES["fraction_symbols"]["map"]
_AGE_GATES: dict[str, int] = _RULES["age_gates"]["products"]
_CALMAG_SKEW_FACTOR: float = _RULES["calmag_skew"]["factor"]
_CALMAG_SKEW_APPLIES_TO: frozenset[str] = frozenset(_RULES["calmag_skew"]["applies_to"])

# Fraction ladder: ordered list of (threshold_float, floor_value) pairs.
# The `null` in the YAML becomes float('inf') here so it sorts last.
def _build_fraction_ladder() -> tuple[tuple[float, float], ...]:
    ladder: list[tuple[float, float]] = []
    for entry in _RULES["fraction_ladder"]["thresholds"]:
        thresh = entry["if_below"]
        if thresh is None:
            thresh = math.inf
        floor_raw = entry["floor_to"]
        # floor_to is either 0, 1, or a fraction symbol ("¼", "½", etc.)
        if isinstance(floor_raw, str):
            floor_val = _FRACTION_VALUES[floor_raw]
        else:
            floor_val = float(floor_raw)
        ladder.append((thresh, floor_val))
    return tuple(ladder)


_FRACTION_LADDER: tuple[tuple[float, float], ...] = _build_fraction_ladder()

_ZERO_VALUES: tuple[str, ...] = tuple(_RULES["dose_string_parsing"]["zero_values"])
_CAP_SINGULAR: str = _RULES["dose_string_parsing"]["cap_word_singular"]
_CAP_PLURAL: str = _RULES["dose_string_parsing"]["cap_word_plural"]


def get_rules() -> dict:
    """Return the raw age_scaling rules dict. Useful for tests and introspection."""
    return _RULES


# ── Age factor (anchor points + linear interpolation) ───────────────────────


def kids_factor(age: int | float | None) -> float:
    """Return the age scaling factor for an HTMA kid dose.

    Args:
        age: patient age in years. None is treated as "unknown / adult" and
             returns 1.0 (no scaling) — keeps the adult path unchanged when
             an adult panel lacks an age field.

    Returns:
        A float in [0.0, 1.0]. 1.0 for age >= adult_threshold (adult dose,
        no scaling). 0.0 for age <= newborn_threshold (drops everything that
        has a non-zero factor).
    """
    if age is None:
        return 1.0
    if age >= _ADULT_THRESHOLD:
        return 1.0
    if age <= _NEWBORN_THRESHOLD:
        return 0.0

    a = float(age)
    for i in range(len(_AGE_ANCHORS) - 1):
        a_lo, f_lo = _AGE_ANCHORS[i]
        a_hi, f_hi = _AGE_ANCHORS[i + 1]
        if a_lo <= a <= a_hi:
            t = (a - a_lo) / (a_hi - a_lo)
            return f_lo + (f_hi - f_lo) * t
    return 1.0  # unreachable — guarded by age >= _ADULT_THRESHOLD above


def is_kid(age: int | float | None) -> bool:
    """Return True when the patient is a kid (age < adult_threshold and known).

    None / missing age returns False so the adult path runs unchanged.
    """
    if age is None:
        return False
    return age < _ADULT_THRESHOLD


# ── Fraction rounding (FLOOR semantics) ─────────────────────────────────────


def floor_to_fraction(n: float) -> float:
    """Round n DOWN to the nearest whole/½/⅓/¼ per the YAML fraction_ladder.

    FLOOR — never exceed the computed value.

    Threshold ladder (smallest first, first match wins):
        n < 0.125  -> 0 (drop entirely)
        n < 1/3    -> floor to nearest 1/4
        n < 0.5    -> floor to nearest 1/3
        n < 1.0    -> floor to nearest 1/2
        else       -> floor to nearest whole

    A small epsilon is added to defeat floating-point underrounds elsewhere
    (e.g. 0.33 * 4 computes as 1.31999...; without the eps, floor() drops
    0.33 to 0 in the 1/4 band).
    """
    if n < 0:
        return 0.0
    eps = 1e-9
    for threshold, floor_val in _FRACTION_LADDER:
        if n < threshold:
            if floor_val == 0.0:
                # "Drop entirely" rule — no rounding needed.
                return 0.0
            # Round to nearest 1/floor_val multiple of floor_val.
            return math.floor(n * (1.0 / floor_val) + eps) * floor_val
    return float(math.floor(n + eps))


# ── String <-> cap-count conversion ─────────────────────────────────────────


def parse_caps(s: str | None) -> float:
    """Parse a dose string to a float cap count.

    "0" or "" -> 0.0; "1 cap" -> 1.0; "2 caps" -> 2.0; "¾ cap" -> 0.75.
    Anything unparseable falls back to 0.0.
    """
    if not s or s in _ZERO_VALUES:
        return 0.0
    s = s.strip()
    # Mixed-number detection: a leading digit followed by a fraction symbol
    # (e.g. "1½ caps" -> 1.5). Must run BEFORE the bare-fraction map so we
    # don't pick up the standalone "½" inside "1½" and return 0.5.
    for sym, val in _FRACTION_VALUES.items():
        idx = s.find(sym)
        if idx <= 0:
            continue  # not a mixed number — bare fraction handled below
        prefix = s[:idx]
        if prefix.isdigit():
            return int(prefix) + val
    # Bare fraction (e.g. "½ cap").
    for sym, val in _FRACTION_VALUES.items():
        if sym in s:
            return val
    try:
        return float(s.split()[0])
    except (ValueError, IndexError):
        return 0.0


def format_kid_caps(n: float) -> str:
    """Format a fractional cap count as a human-readable dose string.

    0.0   -> "0"
    0.25  -> "¼ cap"
    0.5   -> "½ cap"
    1.0   -> "1 cap"
    1.5   -> "1½ caps"
    2.0   -> "2 caps"
    """
    if n == 0:
        return "0"
    # Round to 2 decimals to defeat float precision noise (e.g. 0.33
    # computed as 0.3333333...).
    rounded = round(n, 2)
    fraction_map = {round(v, 2): sym for sym, v in _FRACTION_VALUES.items()}
    if rounded in fraction_map:
        return f"{fraction_map[rounded]} {_CAP_SINGULAR}"
    # Whole number.
    if rounded == int(rounded):
        n_int = int(rounded)
        return f"{n_int} {_CAP_SINGULAR}" if n_int == 1 else f"{n_int} {_CAP_PLURAL}"
    # Mixed number (e.g. 1.5).
    whole = int(rounded)
    frac = round(rounded - whole, 2)
    frac_str = fraction_map.get(frac, f"{frac:.2f}")
    return f"{whole}{frac_str} {_CAP_PLURAL}" if whole != 1 else f"1{frac_str} {_CAP_PLURAL}"


# ── Age gates (AdrenoFuel, ThyroSpark) ──────────────────────────────────────


def apply_age_gate(product_id: str, age: int | float | None) -> bool:
    """Return True when the product is allowed for this kid.

    Products without an entry in `_AGE_GATES` are always allowed (the bucket
    YAML is the source of truth for product placement; this only enforces
    the kid-specific age gates). For kids below the gate, return False so
    the writer drops the product from the protocol entirely.
    """
    if not is_kid(age):
        return True
    if age is None:
        return True
    gate = _AGE_GATES.get(product_id)
    if gate is None:
        return True
    return age >= gate


def age_gate_for(product_id: str) -> int | None:
    """Return the minimum age for a product (None if no gate)."""
    return _AGE_GATES.get(product_id)


def calmag_skew_applies_to(product_id: str) -> bool:
    """Return True if the Cal-Mag skew (1.25x pre-age-scale) applies to this product."""
    return product_id in _CALMAG_SKEW_APPLIES_TO


# ── Main kid dose reducer ──────────────────────────────────────────────────


def kids_dose(
    adult_am: str | None,
    adult_noon: str | None,
    adult_pm: str | None,
    age: int | float | None,
    *,
    calmag_skew: bool = False,
) -> tuple[str, str, str]:
    """Reduce an adult 3-slot dose to a kid 2-slot dose.

    Pipeline (per Luke 2026-09-08, carried to v2):
        1. Merge NOON into PM via MAX(NOON, PM).
        2. Compute the age factor.
        3. If `calmag_skew`, multiply the adult caps by 1.25 BEFORE the age
           factor — Clark gives kids more Cal-Mag relative to other
           supplements for size.
        4. Scale AM and PM by factor (and skew if applicable).
        5. Floor to the fraction ladder.
        6. Format. NOON is always "0" for kids (strict 2x/day).

    Args:
        adult_am: adult AM dose string (e.g. "1 cap", "2 caps", "0").
        adult_noon: adult NOON dose string.
        adult_pm: adult PM dose string.
        age: patient age in years. None / >= adult_threshold returns the
              adult dose unchanged.
        calmag_skew: when True, multiply the adult dose by 1.25 BEFORE the
                     age factor. Only Cal-Mag Fusion uses this (driven by
                     calmag_skew_applies_to() at the consumer).

    Returns:
        (kid_am, "0", kid_pm) — a 3-tuple where the noon slot is always
        "0" for kids and the format matches the rest of the codebase
        ("¼ cap", "1 cap", "2 caps", "0").
    """
    # Adult path: untouched 3-slot dose.
    if not is_kid(age):
        return (adult_am or "0", adult_noon or "0", adult_pm or "0")

    factor = kids_factor(age)
    skew = _CALMAG_SKEW_FACTOR if calmag_skew else 1.0

    noon_caps = parse_caps(adult_noon)
    pm_caps = parse_caps(adult_pm)
    # Rule 9: NOON value merges into PM via MAX.
    pm_merged = max(noon_caps, pm_caps)

    am_caps = parse_caps(adult_am)

    # Skew applied BEFORE age scaling (rule 5). For non-Cal-Mag products
    # skew is 1.0 so this is a no-op.
    am_scaled = am_caps * factor * skew
    pm_scaled = pm_merged * factor * skew

    am_rounded = floor_to_fraction(am_scaled)
    pm_rounded = floor_to_fraction(pm_scaled)

    return (
        format_kid_caps(am_rounded),
        "0",  # Rule 2: strict 2x/day — NOON slot dropped.
        format_kid_caps(pm_rounded),
    )


def drop_age_gated_products(
    products: Iterable, age: int | float | None
) -> tuple[list, list[str]]:
    """Filter a sequence of SupplementProduct-like objects by age gate.

    For each product, `apply_age_gate(product.id, age)` decides whether to
    keep it. Returns (kept, warnings) where `warnings` is a list of human-
    readable messages for products that were dropped.

    Products without an age gate pass through unchanged.
    """
    if not is_kid(age):
        return list(products), []
    kept: list = []
    warnings: list[str] = []
    for product in products:
        if apply_age_gate(product.id, age):
            kept.append(product)
            continue
        gate = age_gate_for(product.id)
        gate_int = gate if gate is not None else 0
        warnings.append(
            f"{product.id} dropped from protocol: kid age {age} is below "
            f"the age-{gate_int} gate (per HTMA Kids Matrix v2 age gates)."
        )
    return kept, warnings
