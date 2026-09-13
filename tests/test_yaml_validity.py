"""Validate every matrix YAML against its JSON schema.

This is the load-bearing test: if a YAML doesn't validate, the matrix is inconsistent
with the locked rules. The three schemas (bucket, pattern, override) cover all files
in matrix/supplements/ and matrix/patterns/.

The classifier logic here is the same one the lab_pipeline will use at runtime — see
test_buckets.py for the classification-side checks.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent

SCHEMA_DIR = REPO / "schemas"
SCHEMAS = {
    "supplements": json.loads((SCHEMA_DIR / "bucket.schema.json").read_text()),
    "patterns": json.loads((SCHEMA_DIR / "pattern.schema.json").read_text()),
    "overrides": json.loads((SCHEMA_DIR / "override.schema.json").read_text()),
    "age_scaling": json.loads((SCHEMA_DIR / "age_scaling.schema.json").read_text()),
    "standard_protocols": json.loads((SCHEMA_DIR / "standard_protocols.schema.json").read_text()),
}


def _classify_yaml(yaml_path: Path) -> str:
    """Map a YAML file path to the schema key it should validate against."""
    parts = yaml_path.parts
    if "supplements" in parts and yaml_path.stem.startswith("bucket"):
        return "supplements"
    if "supplements" in parts and "override" in yaml_path.stem:
        return "overrides"
    if "patterns" in parts:
        return "patterns"
    if "age_scaling" in parts:
        return "age_scaling"
    if yaml_path.stem == "standard_protocols":
        return "standard_protocols"
    raise ValueError(f"Cannot classify YAML: {yaml_path}")


def _all_yamls() -> list[Path]:
    return sorted(REPO.glob("matrix/**/*.yml"))


@pytest.mark.parametrize("yaml_path", _all_yamls(), ids=lambda p: str(p.relative_to(REPO)))
def test_yaml_validates_against_schema(yaml_path: Path) -> None:
    data = yaml.safe_load(yaml_path.read_text())
    schema_key = _classify_yaml(yaml_path)
    jsonschema.validate(data, SCHEMAS[schema_key])


def test_every_yaml_is_classified() -> None:
    """Catch the case where a new YAML is added without updating the classifier."""
    for path in _all_yamls():
        _classify_yaml(path)  # raises if unmapped


def test_schemas_are_valid_draft_2020() -> None:
    """Each schema must itself parse as a JSON Schema Draft 2020-12 document."""
    for name, schema in SCHEMAS.items():
        assert schema.get("$schema", "").endswith("2020-12/schema"), f"{name} not Draft 2020-12"
        jsonschema.Draft202012Validator.check_schema(schema)
