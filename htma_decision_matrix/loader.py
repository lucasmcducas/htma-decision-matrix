"""Loads the htma-decision-matrix YAML rules at runtime.

The matrix repo is a sibling of lab_pipeline. The loader walks matrix/patterns/
and matrix/supplements/ and parses each YAML into a typed structure.

This module is intentionally agnostic about clinical decisions: it only mirrors
the YAML schema. All classification logic lives in `lab_pipeline.interpreter`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Locate the matrix repo. In editable installs we sit at:
#   htma-decision-matrix/htma_decision_matrix/loader.py
# → repo root = parent.parent
MATRIX_REPO = Path(__file__).resolve().parent.parent


@dataclass
class SupplementProduct:
    """One supplement product in a bucket or override result."""

    id: str
    role: str
    dose_modifier: str
    notes: str = ""
    # Optional metadata from the YAML (e.g., conditional additions)
    conditional: dict | None = None
    # Optional Na/K-ratio-driven dose ladder. When set, products like
    # zinc-matrix-pro and na-k-up have their dose vary by the panel's Na/K.
    # Schema: {"type": "linear", "metric": "na_k",
    #          "anchors": [{"na_k_max": float|null,
    #                       "dose": {"am": str, "noon": str, "pm": str}}, ...]}
    # Audit Critical 1 fix (2026-09-12): the v1 loader silently discarded
    # this field. v2 carries it through so consumers can drive per-slot doses
    # from the matrix without re-parsing YAML.
    dose_schedule: dict | None = None


@dataclass
class SupplementBucket:
    """One of the 6 supplement buckets."""

    bucket_id: str
    label: str
    oxidation: str
    na_k_band: str
    products: list[SupplementProduct]
    description: str = ""
    references: list[str] = field(default_factory=list)
    # Populated by load_matrix_for_age() when products are dropped
    # due to age gates. Empty for the adult path.
    age_warnings: list[str] = field(default_factory=list)


@dataclass
class SupplementOverride:
    """A supplement-level override (only sympathetic_dominance currently)."""

    override_id: str
    applies_to_bucket: str
    detection_requires: dict
    overrides: list[dict]
    description: str = ""
    notes: str = ""


@dataclass
class InterpretationPattern:
    """A chart annotation pattern (oxidation, calcium_shell, etc.)."""

    pattern_id: str
    display_name: str = ""
    affects: str = ""
    description: str = ""
    classifier: dict = field(default_factory=dict)
    chart_annotations: dict = field(default_factory=dict)
    sub_patterns: list[dict] = field(default_factory=list)
    reinforcing_combinations: list = field(default_factory=list)
    references: list[str] = field(default_factory=list)


@dataclass
class Matrix:
    """In-memory representation of the htma-decision-matrix repo."""

    buckets: dict[str, SupplementBucket]
    overrides: list[SupplementOverride]
    patterns: dict[str, InterpretationPattern]
    repo_path: Path

    @classmethod
    def load(cls, repo_path: Path | None = None) -> "Matrix":
        """Load all YAML rules under `repo_path/matrix/`.

        Args:
            repo_path: Path to the htma-decision-matrix repo. Defaults to
                      the package's sibling `matrix/` directory.

        Returns:
            Matrix with all 6 buckets, all overrides, and all interpretation
            patterns loaded.
        """
        repo = repo_path or MATRIX_REPO
        if not (repo / "matrix").exists():
            raise FileNotFoundError(
                f"matrix/ directory not found under {repo} — "
                "pass repo_path explicitly if you moved the repo"
            )

        # Buckets — files matching bucket_*.yml
        buckets: dict[str, SupplementBucket] = {}
        for yml in sorted((repo / "matrix/supplements").glob("bucket_*.yml")):
            data = yaml.safe_load(yml.read_text())
            if not isinstance(data, dict) or "products" not in data:
                # Not a bucket (shouldn't happen given glob, but defensive)
                continue
            products: list[SupplementProduct] = []
            for p in data["products"]:
                products.append(
                    SupplementProduct(
                        id=p["id"],
                        role=p.get("role", ""),
                        dose_modifier=p.get("dose_modifier", "standard"),
                        notes=p.get("notes", ""),
                        conditional=p.get("conditional"),
                        dose_schedule=p.get("dose_schedule"),
                    )
                )
            buckets[data["bucket_id"]] = SupplementBucket(
                bucket_id=data["bucket_id"],
                label=data.get("label", data["bucket_id"]),
                oxidation=data["oxidation"],
                na_k_band=data["na_k_band"],
                products=products,
                description=data.get("description", ""),
                references=data.get("references", []),
            )

        # Overrides — files matching *override*.yml that aren't buckets
        overrides: list[SupplementOverride] = []
        for yml in sorted((repo / "matrix/supplements").glob("*override*.yml")):
            data = yaml.safe_load(yml.read_text())
            if not isinstance(data, dict):
                continue
            detection = data.get("detection", {}) or {}
            overrides.append(
                SupplementOverride(
                    override_id=data["override_id"],
                    applies_to_bucket=data["applies_to_bucket"],
                    detection_requires=detection.get("requires", {}),
                    overrides=data.get("overrides", []),
                    description=data.get("description", ""),
                    notes=detection.get("notes", ""),
                )
            )

        # Patterns — all files under matrix/patterns/
        patterns: dict[str, InterpretationPattern] = {}
        for yml in sorted((repo / "matrix/patterns").glob("*.yml")):
            data = yaml.safe_load(yml.read_text())
            if not isinstance(data, dict) or "pattern_id" not in data:
                continue
            patterns[data["pattern_id"]] = InterpretationPattern(
                pattern_id=data["pattern_id"],
                display_name=data.get("display_name", data["pattern_id"]),
                affects=data.get("affects", ""),
                description=data.get("description", ""),
                classifier=data.get("classifier", {}) or {},
                chart_annotations=data.get("chart_annotations", {}) or {},
                sub_patterns=data.get("sub_patterns", []) or [],
                reinforcing_combinations=data.get("reinforcing_combinations", []) or [],
                references=data.get("references", []),
            )

        return cls(buckets=buckets, overrides=overrides, patterns=patterns, repo_path=repo)


def load_matrix(repo_path: Path | None = None) -> Matrix:
    """Convenience wrapper around Matrix.load(repo_path)."""
    return Matrix.load(repo_path)


def load_matrix_for_age(age: int | float | None, repo_path: Path | None = None) -> Matrix:
    """Load the matrix, optionally with kid age-gating applied.

    Phase 1 (v2.0.0):
        - Adults (age >= 19 or None): same as load_matrix().
        - Kids (age < 19): products below their age gate are dropped
          (AdrenoFuel <9, ThyroSpark <5). The dropped product IDs and
          reasons are recorded in `bucket.age_warnings`.

    Phase 2 (planned, separate commit):
        - Per-slot dose scaling via age_scaling.kids_dose(). Requires
          `dose_schedule` to be exposed on SupplementProduct (audit
          Critical 1 finding). Today the matrix repo's loader doesn't
          carry per-slot doses — lab_pipeline has its own loader fork
          that does, and v2 Phase 2 will reconcile them.

    Args:
        age: patient age in years. None = adult (same as load_matrix()).
        repo_path: optional repo path override.

    Returns:
        A Matrix where every bucket's products reflect the given age's
        gate policy. The Matrix is a NEW object (load_matrix is not
        mutated); mutate freely.

    Backward compat: passing age=None returns the same shape as load_matrix().
    """
    from .age_scaling import drop_age_gated_products, is_kid

    matrix = load_matrix(repo_path)
    if not is_kid(age):
        return matrix

    # Build a NEW Matrix; do not mutate the source.
    new_buckets: dict[str, SupplementBucket] = {}
    for bucket_id, bucket in matrix.buckets.items():
        kept, warnings = drop_age_gated_products(bucket.products, age)
        new_bucket = SupplementBucket(
            bucket_id=bucket.bucket_id,
            label=bucket.label,
            oxidation=bucket.oxidation,
            na_k_band=bucket.na_k_band,
            products=kept,
            description=bucket.description,
            references=list(bucket.references),
            age_warnings=warnings,
        )
        new_buckets[bucket_id] = new_bucket

    return Matrix(
        buckets=new_buckets,
        overrides=list(matrix.overrides),
        patterns=dict(matrix.patterns),
        repo_path=matrix.repo_path,
    )
