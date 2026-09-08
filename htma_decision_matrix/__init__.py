"""htma-decision-matrix — runtime loader for the Wilson/Valence decision matrix.

This package wraps the YAML rules in `matrix/` so the lab_pipeline can
import them as Python objects instead of parsing YAML at every call site.

Public surface:
    load_matrix(repo_path) -> Matrix

A `Matrix` instance carries:
    buckets: dict[bucket_id, SupplementBucket]
    overrides: list[SupplementOverride]
    patterns: dict[pattern_id, InterpretationPattern]

The decision YAMLs are the source of truth. This package only loads them.
"""
from __future__ import annotations

from .loader import (
    InterpretationPattern,
    Matrix,
    SupplementBucket,
    SupplementOverride,
    SupplementProduct,
    load_matrix,
)

__all__ = [
    "InterpretationPattern",
    "Matrix",
    "SupplementBucket",
    "SupplementOverride",
    "SupplementProduct",
    "load_matrix",
]
