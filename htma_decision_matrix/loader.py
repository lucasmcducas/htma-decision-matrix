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
