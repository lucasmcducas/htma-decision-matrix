"""HTMA Standard Protocols — per-product default doses.

Lifted from lab_pipeline.interpreter.doses.STANDARD_DOSES (2026-09-08,
locked rule 6). Lives in the matrix repo so the matrix owns the complete
dose picture and downstream consumers don't need a parallel table.

Each entry is a (am, noon, pm) dose triple — strings like "1 cap",
"2 caps", "0", "½ cap". The runtime prefers `dose_schedule.anchors`
when present (zinc-matrix-pro, na-k-up); this module provides the
fallback for products without an Na/K-driven ladder.

Usage:
    from htma_decision_matrix import standard_protocols
    dose = standard_protocols.get("cell-restore")
    # -> ("2 caps", "2 caps", "2 caps")
"""
from __future__ import annotations

from pathlib import Path

import yaml


_PROTOCOLS_PATH = (
    Path(__file__).resolve().parent.parent / "matrix" / "standard_protocols.yml"
)


def _load() -> dict[str, tuple[str, str, str]]:
    data = yaml.safe_load(_PROTOCOLS_PATH.read_text())
    products = data.get("products", {})
    return {
        pid: (entry["am"], entry["noon"], entry["pm"])
        for pid, entry in products.items()
    }


_TABLE: dict[str, tuple[str, str, str]] = _load()


def get(product_id: str) -> tuple[str, str, str] | None:
    """Return (am, noon, pm) for a product, or None if not in the table."""
    return _TABLE.get(product_id)


def all_products() -> tuple[str, ...]:
    """Return all product IDs in the standard protocols table."""
    return tuple(sorted(_TABLE.keys()))


def format_dose_string(dose: tuple[str, str, str]) -> str:
    """Format a (am, noon, pm) tuple as the viewer's "am·noon·pm" string."""
    return f"{dose[0]}·{dose[1]}·{dose[2]}"
