"""htma-decision-matrix — runtime loader for the Wilson/Valence decision matrix.

This package wraps the YAML rules in `matrix/` so the lab_pipeline can
import them as Python objects instead of parsing YAML at every call site.

Public surface:
    load_matrix(repo_path) -> Matrix
    load_matrix_for_age(age, repo_path) -> Matrix   (v2 — kid age-gating)
    age_scaling — kid dose reducer module (v2)

A `Matrix` instance carries:
    buckets: dict[bucket_id, SupplementBucket]
    overrides: list[SupplementOverride]
    patterns: dict[pattern_id, InterpretationPattern]

The decision YAMLs are the source of truth. This package only loads them.
"""
from __future__ import annotations

from . import age_scaling
from .loader import (
    InterpretationPattern,
    Matrix,
    SupplementBucket,
    SupplementOverride,
    SupplementProduct,
    load_matrix,
    load_matrix_for_age,
)

__all__ = [
    "InterpretationPattern",
    "Matrix",
    "SupplementBucket",
    "SupplementOverride",
    "SupplementProduct",
    "age_scaling",
    "load_matrix",
    "load_matrix_for_age",
]
