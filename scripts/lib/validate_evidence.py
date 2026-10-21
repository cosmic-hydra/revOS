#!/usr/bin/env python3
"""Validate every **/*.json under subsystems/ against evidence/schema.json.

Usage:
  scripts/lib/validate_evidence.py [ROOT_DIR]

ROOT_DIR defaults to the repository root (the parent of `evidence/`).
The script is intentionally dependency-free: it ships its own minimal JSON-Schema
2020-12 validator using only the Python stdlib so the harness CI lane stays green
without `pip install jsonschema`.

Exit codes:
  0  all evidence records conform
  1  one or more records failed validation (printed)
  2  schema load failure (printed)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


SCHEMA_FILE = Path(__file__).resolve().parent.parent.parent / "evidence" / "schema.json"
EVIDENCE_ROOTS = ("subsystems",)
SKIP_PARTS = ("raw",)
URI = "uri"  # placeholder for the format vocabulary key below


# ---------------------------------------------------------------------------
# Minimal JSON Schema 2020-12 validator — handles only the keys revOS uses.
# Intentionally NOT a general-purpose validator. If the schema grows beyond
# what is listed in REQUIRED_KEYS / SUPPORTED_KEYS, extend this dict first.
# ---------------------------------------------------------------------------

SUPPORTED_KEYS = {
    "$schema", "$id", "title", "description", "type",
    "required", "additionalProperties", "properties", "items",
    "enum", "pattern", "minLength", "minimum", "maximum", "format",
}


def load_schema() -> dict[str, Any]:
    if not SCHEMA_FILE.is_file():
        raise SystemExit(f"schema not found: {SCHEMA_FILE}")
    with SCHEMA_FILE.open() as fh:
        schema = json.load(fh)
    return schema


def _walk(instance: Any, schema: dict[str, Any], path: str = "") -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors

    typ = schema.get("type")
    if typ and not _check_type(instance, typ):
        errors.append(f"{path}: expected type {typ!r}, got {type(instance).__name__}")
        return errors  # no further checks make sense

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} not in enum {schema['enum']!r}")

    if "pattern" in schema and isinstance(instance, str):
        if not re.search(schema["pattern"], instance):
            errors.append(f"{path}: value {instance!r} does not match pattern {schema['pattern']!r}")

    if "minLength" in schema and isinstance(instance, str) and len(instance) < schema["minLength"]:
        errors.append(f"{path}: string shorter than minLength={schema['minLength']}")

    if "minimum" in schema and isinstance(instance, (int, float)) and instance < schema["minimum"]:
        errors.append(f"{path}: value {instance!r} below minimum={schema['minimum']}")

    if "maximum" in schema and isinstance(instance, (int, float)) and instance > schema["maximum"]:
        errors.append(f"{path}: value {instance!r} above maximum={schema['maximum']}")

    if "format" in schema and isinstance(instance, str):
        if schema["format"] == URI and not _looks_like_uri(instance):
            # Strict URI check is the only format we depend on; report rather than crash.
            errors.append(f"{path}: value {instance!r} is not a syntactically valid URI")

    required = schema.get("required", [])
    if isinstance(instance, dict):
        for key in required:
            if key not in instance:
                errors.append(f"{path}: missing required key {key!r}")
        if schema.get("additionalProperties") is False:
            props = set(schema.get("properties", {}).keys())
            for key in instance.keys():
                if key not in props:
                    errors.append(f"{path}: unexpected additional property {key!r}")
        for key, subschema in schema.get("properties", {}).items():
            if key in instance:
                errors.extend(_walk(instance[key], subschema, f"{path}.{key}"))

    if "items" in schema and isinstance(instance, list):
        for i, item in enumerate(instance):
            errors.extend(_walk(item, schema["items"], f"{path}[{i}]"))

    return errors


def _check_type(instance: Any, typ: Any) -> bool:
    if isinstance(typ, list):
        return any(_check_type(instance, t) for t in typ)
    return {
        "object": lambda x: isinstance(x, dict),
        "array": lambda x: isinstance(x, list),
        "string": lambda x: isinstance(x, str),
        "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
        "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
        "boolean": lambda x: isinstance(x, bool),
        "null": lambda x: x is None,
    }.get(typ, lambda x: True)(instance)


def _looks_like_uri(s: str) -> bool:
    # Lightweight: scheme://anything. We do not need RFC 3986 conformance for
    # GitHub URLs in cross_reference.
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://\S+", s))


# ---------------------------------------------------------------------------
# Filesystem walk
# ---------------------------------------------------------------------------


def iter_evidence_files(root: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    for sub in EVIDENCE_ROOTS:
        base = root / sub
        if not base.is_dir():
            continue
        for path in base.rglob("*.json"):
            rel = path.relative_to(base)
            if any(part in SKIP_PARTS for part in rel.parts):
                continue
            if path in seen:
                continue
            seen.add(path)
            yield path


def main(argv: list[str]) -> int:
    repo_root = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parent.parent.parent
    try:
        schema = load_schema()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"schema load failure: {exc}", file=sys.stderr)
        return 2

    files = sorted(iter_evidence_files(repo_root))
    if not files:
        print(f"no evidence records found under {repo_root}/subsystems/")
        return 0

    failures: list[tuple[Path, list[str]]] = []
    successes = 0
    for path in files:
        try:
            with path.open() as fh:
                payload = json.load(fh)
        except json.JSONDecodeError as exc:
            failures.append((path, [f"json decode error: {exc}"]))
            continue
        errors = _walk(payload, schema, path=str(path.relative_to(repo_root)))
        if errors:
            failures.append((path, errors))
        else:
            successes += 1

    print(f"validated {len(files)} evidence records: {successes} ok, {len(failures)} failing")
    for path, errors in failures:
        print(f"\nFAIL: {path}")
        for err in errors:
            print(f"  - {err}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
