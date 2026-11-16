#!/usr/bin/env python3
"""Shared deterministic helpers for Design Pact project gates."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ModuleNotFoundError as exc:
    if exc.name != "yaml":
        raise
    executable = Path(sys.executable)
    print(
        "Design Pact requires PyYAML. Install it with: "
        f"{executable} -m pip install PyYAML",
        file=sys.stderr,
    )
    raise SystemExit(2) from None


_STANDARD_ID_PREFIXES = (
    "JRN",
    "FEAT",
    "INT",
    "NFR",
    "COMP",
    "TOKEN",
    "ASSET",
    "SPEC",
    "SCREEN",
    "FLOW",
    "STATE",
    "AC",
    "TEST",
    "IMPL",
    "SHOT",
    "GAP",
    "EXC",
    "ART",
    "DEC",
)
ID_PATTERNS = {
    prefix: re.compile(rf"^{prefix}-(?!000)[0-9]{{3}}$")
    for prefix in _STANDARD_ID_PREFIXES
}
ID_PATTERNS.update(
    {
        "APR": re.compile(r"^APR-(?!000)[0-9]{3,}$"),
        "TDD": re.compile(r"^TDD-(?!000)[0-9]{3,}$"),
    }
)

META_KEYS = (
    "artifact_id",
    "artifact_type",
    "schema_version",
    "version",
    "owner",
    "created_at_state",
    "status",
    "source_ids",
    "upstream_sha256",
    "approval_required",
)

STATES = (
    "discovery",
    "scope_defined",
    "design_contract_ready",
    "project_initialized",
    "design_system_ready",
    "implementation",
    "verification",
    "released",
)

COVERAGE_STATUSES = ("covered", "out_of_scope", "deferred", "blocked")
AUTHORED_STATUSES = (
    "draft",
    "review",
    "approved",
    "blocked",
    "removed",
    "superseded",
)
TEST_TYPES = ("unit", "component", "ui", "integration", "visual", "accessibility")
TDD_PHASES = ("red", "green", "refactor", "verify")
TDD_STATUSES = ("captured",)
PLANNING_STATUSES = ("planned", "active", "blocked", "deferred", "out_of_scope")
FAILURE_KINDS = (
    "behavior",
    "compile",
    "syntax",
    "environment",
    "missing_dependency",
    "test_setup",
    "unknown",
)
APPROVAL_KINDS = (
    "scope",
    "design_contract",
    "visual_baseline",
    "exception",
    "release",
    "tdd_event",
    "artifact",
)
APPROVAL_DECISIONS = ("approved", "rejected")
APPROVAL_SUBJECT_TYPES = {
    "scope": "release_scope",
    "design_contract": "design_contract",
    "visual_baseline": "visual_baseline",
    "exception": "design_exception",
    "release": "release",
    "tdd_event": "tdd_event",
    "artifact": "artifact",
}
_PLACEHOLDER_IDENTITY = re.compile(
    r"(?:^|[\s_.:/-])(?:ai|agent|bot|automation|todo|tbd|placeholder|unknown)"
    r"(?:$|[\s_.:/-])",
    re.IGNORECASE,
)


class DesignPactError(ValueError):
    """A deterministic contract violation."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso8601(value: Any, location: str) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_sources(root: Path, relative_paths: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for raw in sorted(set(relative_paths)):
        relative = Path(raw).as_posix()
        path = root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if not path.exists():
            digest.update(b"<missing>")
        elif path.is_dir():
            digest.update(b"<directory>")
        else:
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise DesignPactError(f"{path}: expected UTF-8 text") from exc


def load_yaml(path: Path) -> Any:
    try:
        value = yaml.safe_load(read_text(path))
    except yaml.YAMLError as exc:
        raise DesignPactError(f"{path}: invalid YAML: {exc}") from exc
    if value is None:
        raise DesignPactError(f"{path}: YAML document is empty")
    return value


def load_yaml_or_default(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return load_yaml(path)


def dump_yaml(value: Any) -> str:
    return yaml.safe_dump(
        value,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )


def split_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise DesignPactError(f"{path}: missing YAML frontmatter")
    try:
        _, raw_matter, body = text.split("---\n", 2)
    except ValueError as exc:
        raise DesignPactError(f"{path}: unterminated YAML frontmatter") from exc
    try:
        metadata = yaml.safe_load(raw_matter)
    except yaml.YAMLError as exc:
        raise DesignPactError(f"{path}: invalid YAML frontmatter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise DesignPactError(f"{path}: frontmatter must be a mapping")
    return metadata, body


def compose_markdown(metadata: dict[str, Any], body: str) -> str:
    return f"---\n{dump_yaml(metadata)}---\n\n{body.lstrip()}"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(read_text(path).splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DesignPactError(f"{path}:{number}: invalid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise DesignPactError(f"{path}:{number}: expected a JSON object")
        records.append(record)
    return records


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(record))
        handle.write("\n")


def valid_id(value: Any, prefix: str) -> bool:
    return isinstance(value, str) and bool(ID_PATTERNS[prefix].fullmatch(value))


def assert_id(value: Any, prefix: str, location: str) -> None:
    if not valid_id(value, prefix):
        raise DesignPactError(f"{location}: invalid {prefix} ID {value!r}")


def require_keys(
    mapping: dict[str, Any],
    keys: Iterable[str],
    location: str,
) -> list[str]:
    return [
        f"{location}: missing required field {key!r}"
        for key in keys
        if key not in mapping
    ]


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise DesignPactError(f"unsupported schema type {expected!r}")


def _resolve_local_schema_ref(
    root_schema: dict[str, Any],
    reference: Any,
    location: str,
) -> dict[str, Any]:
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise DesignPactError(
            f"{location}: unsupported schema $ref {reference!r}; "
            "only local JSON pointers are allowed"
        )
    current: Any = root_schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise DesignPactError(
                f"{location}: schema $ref {reference!r} does not resolve"
            )
        current = current[part]
    if not isinstance(current, dict):
        raise DesignPactError(
            f"{location}: schema $ref {reference!r} must resolve to an object"
        )
    return current


def validate_schema(
    value: Any,
    schema: dict[str, Any],
    location: str,
    *,
    _root_schema: dict[str, Any] | None = None,
    _ref_stack: tuple[str, ...] = (),
) -> list[str]:
    """Validate the small JSON-Schema subset used by bundled Design Pact schemas."""

    root_schema = schema if _root_schema is None else _root_schema
    errors: list[str] = []
    reference = schema.get("$ref")
    if reference is not None:
        if not isinstance(reference, str):
            raise DesignPactError(f"{location}: schema $ref must be a string")
        if reference in _ref_stack:
            raise DesignPactError(
                f"{location}: cyclic schema $ref {reference!r} is not supported"
            )
        resolved = _resolve_local_schema_ref(root_schema, reference, location)
        errors.extend(
            validate_schema(
                value,
                resolved,
                location,
                _root_schema=root_schema,
                _ref_stack=_ref_stack + (reference,),
            )
        )
        siblings = {key: item for key, item in schema.items() if key != "$ref"}
        if siblings:
            errors.extend(
                validate_schema(
                    value,
                    siblings,
                    location,
                    _root_schema=root_schema,
                    _ref_stack=_ref_stack,
                )
            )
        return errors
    if "const" in schema and value != schema["const"]:
        errors.append(f"{location}: expected constant {schema['const']!r}")
    if "anyOf" in schema:
        alternatives = schema["anyOf"]
        if not isinstance(alternatives, list) or not alternatives:
            raise DesignPactError(f"{location}: anyOf must be a non-empty list")
        if not any(
            not validate_schema(
                value,
                item,
                location,
                _root_schema=root_schema,
                _ref_stack=_ref_stack,
            )
            for item in alternatives
            if isinstance(item, dict)
        ):
            errors.append(f"{location}: value does not match any allowed schema")
    if "allOf" in schema:
        alternatives = schema["allOf"]
        if not isinstance(alternatives, list):
            raise DesignPactError(f"{location}: allOf must be a list")
        for item in alternatives:
            if isinstance(item, dict):
                errors.extend(
                    validate_schema(
                        value,
                        item,
                        location,
                        _root_schema=root_schema,
                        _ref_stack=_ref_stack,
                    )
                )
    if "not" in schema:
        forbidden = schema["not"]
        if not isinstance(forbidden, dict):
            raise DesignPactError(f"{location}: not must be an object")
        if not validate_schema(
            value,
            forbidden,
            location,
            _root_schema=root_schema,
            _ref_stack=_ref_stack,
        ):
            errors.append(f"{location}: value matches a forbidden schema")
    if "if" in schema:
        condition = schema["if"]
        if not isinstance(condition, dict):
            raise DesignPactError(f"{location}: if must be an object")
        condition_matches = not validate_schema(
            value,
            condition,
            location,
            _root_schema=root_schema,
            _ref_stack=_ref_stack,
        )
        branch = schema.get("then" if condition_matches else "else")
        if isinstance(branch, dict):
            errors.extend(
                validate_schema(
                    value,
                    branch,
                    location,
                    _root_schema=root_schema,
                    _ref_stack=_ref_stack,
                )
            )
        elif branch is not None:
            raise DesignPactError(f"{location}: conditional schema must be an object")

    expected = schema.get("type")
    if expected:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(_schema_type_matches(value, item) for item in expected_types):
            errors.append(
                f"{location}: expected type {expected!r}, got "
                f"{type(value).__name__}"
            )
            return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{location}: value {value!r} is not in {schema['enum']!r}")

    if isinstance(value, str):
        pattern = schema.get("pattern")
        if pattern and not re.fullmatch(str(pattern), value):
            errors.append(f"{location}: value {value!r} does not match {pattern!r}")
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{location}: string is shorter than {min_length}")
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and len(value) > max_length:
            errors.append(f"{location}: string is longer than {max_length}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{location}: value is less than minimum {minimum!r}")
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{location}: value is greater than maximum {maximum!r}")

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{location}: expected at least {min_items} item(s)")
        max_items = schema.get("maxItems")
        if isinstance(max_items, int) and len(value) > max_items:
            errors.append(f"{location}: expected at most {max_items} item(s)")
        if schema.get("uniqueItems"):
            rendered = [canonical_json(item) for item in value]
            if len(rendered) != len(set(rendered)):
                errors.append(f"{location}: array items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(
                    validate_schema(
                        item,
                        item_schema,
                        f"{location}[{index}]",
                        _root_schema=root_schema,
                        _ref_stack=_ref_stack,
                    )
                )

    if isinstance(value, dict):
        min_properties = schema.get("minProperties")
        if isinstance(min_properties, int) and len(value) < min_properties:
            errors.append(f"{location}: expected at least {min_properties} propert(ies)")
        errors.extend(require_keys(value, schema.get("required", []), location))
        dependent_required = schema.get("dependentRequired", {})
        if dependent_required is not None:
            if not isinstance(dependent_required, dict):
                raise DesignPactError(
                    f"{location}: dependentRequired must be an object"
                )
            for key, required_keys in dependent_required.items():
                if key not in value:
                    continue
                if not isinstance(required_keys, list) or any(
                    not isinstance(item, str) for item in required_keys
                ):
                    raise DesignPactError(
                        f"{location}: dependentRequired values must be string arrays"
                    )
                errors.extend(require_keys(value, required_keys, location))
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, dict):
                    errors.extend(
                        validate_schema(
                            value[key],
                            child_schema,
                            f"{location}.{key}",
                            _root_schema=root_schema,
                            _ref_stack=_ref_stack,
                        )
                    )
        if schema.get("additionalProperties") is False:
            known = set(properties) | set(schema.get("required", []))
            for key in value:
                if key not in known:
                    errors.append(f"{location}: unexpected field {key!r}")
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            for key, child in value.items():
                if key not in properties:
                    errors.extend(
                        validate_schema(
                            child,
                            additional,
                            f"{location}.{key}",
                            _root_schema=root_schema,
                            _ref_stack=_ref_stack,
                        )
                    )
    return errors


def validate_metadata(metadata: dict[str, Any], location: str) -> list[str]:
    errors = require_keys(metadata, META_KEYS, location)
    artifact_id = metadata.get("artifact_id")
    if artifact_id and not valid_id(artifact_id, "ART"):
        errors.append(f"{location}: invalid artifact_id {artifact_id!r}")
    if metadata.get("schema_version") != "1.0":
        errors.append(f"{location}: schema_version must be '1.0'")
    if not isinstance(metadata.get("version"), int) or metadata.get("version", 0) < 1:
        errors.append(f"{location}: version must be a positive integer")
    if metadata.get("status") not in AUTHORED_STATUSES:
        errors.append(f"{location}: invalid status {metadata.get('status')!r}")
    if not isinstance(metadata.get("approval_required"), bool):
        errors.append(f"{location}: approval_required must be boolean")
    if not isinstance(metadata.get("source_ids"), list):
        errors.append(f"{location}: source_ids must be a list")
    upstream = metadata.get("upstream_sha256")
    if upstream not in ("", None) and (
        not isinstance(upstream, str)
        or not re.fullmatch(r"[0-9a-f]{64}", upstream)
    ):
        errors.append(f"{location}: upstream_sha256 must be empty or SHA-256")
    if "generator" in metadata:
        for key in ("generated_from", "source_sha256", "generated_at"):
            if key not in metadata:
                errors.append(f"{location}: generated view missing {key!r}")
        if not isinstance(metadata.get("generated_from"), list):
            errors.append(f"{location}: generated_from must be a list")
        source_hash = metadata.get("source_sha256")
        if not isinstance(source_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", source_hash
        ):
            errors.append(f"{location}: source_sha256 must be SHA-256")
    return errors


@dataclass(frozen=True)
class TestDeclaration:
    marker_line: int
    source: str
    sha256: str
    ac_ids: tuple[str, ...]


MARKER_RE = re.compile(
    r"^\s*// DESIGN_PACT: (TEST-(?!000)[0-9]{3}) => "
    r"((?:AC-(?!000)[0-9]{3})(?:,AC-(?!000)[0-9]{3})*)\s*$"
)
TEST_ANNOTATION_RE = re.compile(r"^\s*@Test\s*$")


def _skip_kotlin_space_and_comments(text: str, index: int, path: Path) -> int:
    """Advance over Kotlin whitespace and comments without interpreting them as code."""

    length = len(text)
    while index < length:
        if text[index].isspace():
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            return length if newline < 0 else newline + 1
        if text.startswith("/*", index):
            depth = 1
            cursor = index + 2
            while cursor < length and depth:
                if text.startswith("/*", cursor):
                    depth += 1
                    cursor += 2
                elif text.startswith("*/", cursor):
                    depth -= 1
                    cursor += 2
                else:
                    cursor += 1
            if depth:
                raise DesignPactError(f"{path}: unterminated block comment")
            index = cursor
            continue
        break
    return index


def _skip_kotlin_literal(text: str, index: int, path: Path) -> int:
    """Return the index after a Kotlin string or character literal."""

    if text.startswith('"""', index):
        closing = text.find('"""', index + 3)
        if closing < 0:
            raise DesignPactError(f"{path}: unterminated raw string literal")
        return closing + 3
    quote = text[index]
    cursor = index + 1
    while cursor < len(text):
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == quote:
            return cursor + 1
        cursor += 1
    raise DesignPactError(f"{path}: unterminated string or character literal")


def _find_kotlin_matching(
    text: str,
    opening_index: int,
    opening: str,
    closing: str,
    path: Path,
) -> int:
    depth = 0
    index = opening_index
    while index < len(text):
        if text.startswith("//", index) or text.startswith("/*", index):
            index = _skip_kotlin_space_and_comments(text, index, path)
            continue
        if text[index] in ('"', "'"):
            index = _skip_kotlin_literal(text, index, path)
            continue
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise DesignPactError(
        f"{path}: unterminated Kotlin delimiter {opening!r}"
    )


def _skip_kotlin_angle_group(text: str, index: int, path: Path) -> int:
    if index >= len(text) or text[index] != "<":
        return index
    depth = 0
    cursor = index
    while cursor < len(text):
        if text.startswith("//", cursor) or text.startswith("/*", cursor):
            cursor = _skip_kotlin_space_and_comments(text, cursor, path)
            continue
        if text[cursor] in ('"', "'"):
            cursor = _skip_kotlin_literal(text, cursor, path)
            continue
        if text[cursor] == "<":
            depth += 1
        elif text[cursor] == ">":
            depth -= 1
            if depth == 0:
                return cursor + 1
        cursor += 1
    raise DesignPactError(f"{path}: unterminated generic parameter list")


def _expression_declaration_end(
    text: str,
    expression_start: int,
    path: Path,
) -> int:
    """Find the end of a top-level Kotlin expression body."""

    stack: list[str] = []
    index = expression_start
    last_non_space = ""
    line_has_code = False
    pairs = {")": "(", "]": "[", "}": "{"}
    while index < len(text):
        if text.startswith("//", index) or text.startswith("/*", index):
            index = _skip_kotlin_space_and_comments(text, index, path)
            continue
        if text[index] in ('"', "'"):
            index = _skip_kotlin_literal(text, index, path)
            last_non_space = "literal"
            line_has_code = True
            continue
        char = text[index]
        if char in "([{":
            stack.append(char)
            line_has_code = True
        elif char in ")]}":
            if not stack or stack[-1] != pairs[char]:
                raise DesignPactError(f"{path}: unbalanced Kotlin expression")
            stack.pop()
            line_has_code = True
        elif char == ";" and not stack:
            return index + 1
        elif char == "\n":
            if stack:
                index += 1
                continue
            lookahead = _skip_kotlin_space_and_comments(text, index + 1, path)
            continuation = text[lookahead : lookahead + 2]
            if continuation.startswith((".", "?.", "?:", "&&", "||")):
                index += 1
                continue
            if (
                line_has_code
                and last_non_space
                and last_non_space not in ".,+-*/%?:=&|<>"
            ):
                return index
        elif not char.isspace():
            last_non_space = char
            line_has_code = True
        index += 1
    if stack:
        raise DesignPactError(f"{path}: unterminated Kotlin expression body")
    return len(text)


def extract_test_declaration(
    path: Path,
    test_id: str,
    symbol: str,
) -> TestDeclaration:
    if not path.exists():
        raise DesignPactError(f"{path}: test implementation does not exist")
    lines = read_text(path).splitlines(keepends=True)
    base_symbol = symbol.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", base_symbol):
        raise DesignPactError(
            f"{path}: implementation_symbol must be an exact Kotlin function name, "
            f"got {symbol!r}"
        )
    marker_indexes: list[int] = []
    marker_acs: dict[int, tuple[str, ...]] = {}
    for index, line in enumerate(lines):
        match = MARKER_RE.match(line.rstrip("\n"))
        if match and match.group(1) == test_id:
            marker_indexes.append(index)
            marker_acs[index] = tuple(
                item.strip() for item in match.group(2).split(",")
            )
    if len(marker_indexes) != 1:
        raise DesignPactError(
            f"{path}: expected exactly one marker for {test_id}, found "
            f"{len(marker_indexes)}"
        )
    marker_index = marker_indexes[0]
    if marker_index + 2 >= len(lines):
        raise DesignPactError(
            f"{path}: marker for {test_id} is not followed by @Test and its function"
        )
    if not TEST_ANNOTATION_RE.fullmatch(lines[marker_index + 1].rstrip("\n")):
        raise DesignPactError(
            f"{path}: marker for {test_id} must sit directly above @Test"
        )
    declaration_text = "".join(lines[marker_index:])
    function_offset = sum(len(line) for line in lines[marker_index : marker_index + 2])
    cursor = _skip_kotlin_space_and_comments(declaration_text, function_offset, path)
    fun_match = re.match(r"fun\b", declaration_text[cursor:])
    if not fun_match:
        raise DesignPactError(
            f"{path}: marker for {test_id} must be followed by "
            f"'fun {base_symbol}(...)' with no extra annotation or declaration"
        )
    cursor += 3
    cursor = _skip_kotlin_space_and_comments(declaration_text, cursor, path)
    if cursor < len(declaration_text) and declaration_text[cursor] == "<":
        cursor = _skip_kotlin_angle_group(declaration_text, cursor, path)
        cursor = _skip_kotlin_space_and_comments(declaration_text, cursor, path)
    if not declaration_text.startswith(base_symbol, cursor):
        raise DesignPactError(
            f"{path}: marker for {test_id} must be followed by exact function "
            f"name {base_symbol!r}"
        )
    cursor += len(base_symbol)
    if cursor < len(declaration_text) and (
        declaration_text[cursor].isalnum() or declaration_text[cursor] == "_"
    ):
        raise DesignPactError(
            f"{path}: marker for {test_id} function name is not exact"
        )
    cursor = _skip_kotlin_space_and_comments(declaration_text, cursor, path)
    if cursor >= len(declaration_text) or declaration_text[cursor] != "(":
        raise DesignPactError(
            f"{path}: marker for {test_id} must bind directly to Kotlin function "
            f"{base_symbol} with a parameter list"
        )
    parameter_close = _find_kotlin_matching(
        declaration_text, cursor, "(", ")", path
    )
    cursor = _skip_kotlin_space_and_comments(
        declaration_text, parameter_close + 1, path
    )
    if cursor < len(declaration_text) and declaration_text[cursor] == ":":
        cursor = _skip_kotlin_space_and_comments(
            declaration_text, cursor + 1, path
        )
        return_type_start = cursor
        while cursor < len(declaration_text):
            if declaration_text.startswith("//", cursor) or declaration_text.startswith(
                "/*", cursor
            ):
                cursor = _skip_kotlin_space_and_comments(
                    declaration_text, cursor, path
                )
                continue
            if declaration_text[cursor] in ('"', "'"):
                cursor = _skip_kotlin_literal(declaration_text, cursor, path)
                continue
            if declaration_text[cursor] in "{=":
                break
            if declaration_text[cursor] in "([":
                cursor = _find_kotlin_matching(
                    declaration_text,
                    cursor,
                    declaration_text[cursor],
                    {"(": ")", "[": "]"}[declaration_text[cursor]],
                    path,
                ) + 1
                continue
            if declaration_text[cursor] == "<":
                cursor = _skip_kotlin_angle_group(
                    declaration_text, cursor, path
                )
                continue
            cursor += 1
        if cursor == return_type_start:
            raise DesignPactError(
                f"{path}: marker for {test_id} has an empty return type"
            )
        cursor = _skip_kotlin_space_and_comments(declaration_text, cursor, path)
    if cursor >= len(declaration_text) or declaration_text[cursor] not in "{=":
        raise DesignPactError(
            f"{path}: marker for {test_id} must bind to a Kotlin function body"
        )
    if declaration_text[cursor] == "{":
        closing = _find_kotlin_matching(declaration_text, cursor, "{", "}", path)
        declaration_end = closing + 1
    else:
        declaration_end = _expression_declaration_end(
            declaration_text, cursor + 1, path
        )
    declaration = declaration_text[:declaration_end]
    marker_line = marker_index + 1
    return TestDeclaration(
        marker_line=marker_line,
        source=declaration,
        sha256=sha256_bytes(declaration.encode("utf-8")),
        ac_ids=marker_acs[marker_index],
    )


def iter_frontmatter_docs(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    docs: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((root / "docs").rglob("*.md")):
        metadata, _ = split_frontmatter(read_text(path), path)
        if "generator" in metadata:
            continue
        docs.append((path, metadata))
    return docs


def load_all_test_contracts(root: Path) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    base = root / "docs" / "verification" / "test-cases"
    paths = sorted(base.glob("SCREEN-*/test-cases.yaml"))
    paths.extend(sorted(base.glob("FLOW-*/test-cases.yaml")))
    for path in paths:
        contract = load_yaml(path)
        if not isinstance(contract, dict):
            raise DesignPactError(f"{path}: expected a mapping")
        contract["_path"] = path.relative_to(root).as_posix()
        contracts.append(contract)
    return contracts


def load_specs(root: Path) -> list[tuple[Path, dict[str, Any], str]]:
    specs: list[tuple[Path, dict[str, Any], str]] = []
    for path in sorted((root / "docs" / "specs").rglob("*.md")):
        metadata, body = split_frontmatter(read_text(path), path)
        specs.append((path, metadata, body))
    return specs


def load_approvals(root: Path) -> list[dict[str, Any]]:
    return load_jsonl(root / "docs" / "project" / "approvals.jsonl")


def approval_errors(root: Path) -> list[str]:
    errors: list[str] = []
    path = root / "docs" / "project" / "approvals.jsonl"
    ledger_path = root / "docs" / "verification" / "tdd-ledger.jsonl"
    seen: set[str] = set()
    decisions_by_subject: dict[tuple[str, str, str], dict[str, list[int]]] = {}
    try:
        approvals = load_approvals(root)
    except DesignPactError as exc:
        return [str(exc)]
    try:
        events = load_jsonl(ledger_path)
    except DesignPactError as exc:
        events = []
        errors.append(str(exc))
    events_by_id = {
        str(event.get("event_id")): event
        for event in events
        if isinstance(event.get("event_id"), str)
    }
    for index, record in enumerate(approvals, start=1):
        location = f"{path}:{index}"
        required = (
            "approval_id",
            "schema_version",
            "kind",
            "subject_type",
            "subject_id",
            "subject_path",
            "subject_sha256",
            "decision",
            "author",
            "approver",
            "decided_at",
            "rationale",
        )
        errors.extend(require_keys(record, required, location))
        approval_id = record.get("approval_id")
        if not valid_id(approval_id, "APR"):
            errors.append(f"{location}: invalid approval_id {approval_id!r}")
        if approval_id in seen:
            errors.append(f"{location}: duplicate approval_id {approval_id}")
        seen.add(str(approval_id))
        if record.get("schema_version") != "1.0":
            errors.append(f"{location}: schema_version must be '1.0'")
        if record.get("kind") not in APPROVAL_KINDS:
            errors.append(f"{location}: invalid approval kind {record.get('kind')!r}")
        if record.get("decision") not in APPROVAL_DECISIONS:
            errors.append(
                f"{location}: invalid approval decision {record.get('decision')!r}"
            )
        author = record.get("author")
        if not isinstance(author, str) or not author.strip():
            errors.append(f"{location}: author must be a non-empty identity")
        elif _PLACEHOLDER_IDENTITY.search(author):
            errors.append(f"{location}: author identity is a placeholder")
        approver = record.get("approver")
        if not isinstance(approver, str) or not approver.strip():
            errors.append(f"{location}: approver must be a non-empty human identity")
        elif _PLACEHOLDER_IDENTITY.search(approver):
            errors.append(
                f"{location}: approver must be a named human, not an AI, bot, "
                "or placeholder"
            )
        if (
            isinstance(author, str)
            and author.strip()
            and isinstance(approver, str)
            and approver.strip()
            and author.strip().casefold() == approver.strip().casefold()
        ):
            errors.append(f"{location}: author cannot approve their own subject")
        rationale = record.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            errors.append(f"{location}: rationale must be non-empty")
        decided_at = parse_iso8601(record.get("decided_at"), location)
        if decided_at is None:
            errors.append(f"{location}: decided_at must be timezone-aware ISO-8601")
        subject_hash = record.get("subject_sha256")
        if not isinstance(subject_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", subject_hash
        ):
            errors.append(f"{location}: subject_sha256 must be lowercase SHA-256")
        elif subject_hash == "0" * 64:
            errors.append(f"{location}: subject_sha256 cannot be all zeroes")
        expected_subject_type = APPROVAL_SUBJECT_TYPES.get(str(record.get("kind")))
        if expected_subject_type and record.get("subject_type") != expected_subject_type:
            errors.append(
                f"{location}: approval kind {record.get('kind')!r} requires "
                f"subject_type {expected_subject_type!r}"
            )
        subject_path = record.get("subject_path")
        if record.get("kind") == "tdd_event":
            subject_id = record.get("subject_id")
            if not valid_id(subject_id, "TDD"):
                errors.append(f"{location}: invalid TDD event subject_id {subject_id!r}")
            expected_path = project_relative(ledger_path, root)
            if subject_path != expected_path:
                errors.append(
                    f"{location}: TDD approval subject_path must be {expected_path!r}"
                )
            event = events_by_id.get(str(subject_id))
            if event is None:
                errors.append(
                    f"{location}: approved TDD event {subject_id!r} does not exist"
                )
            elif subject_hash != event.get("event_sha256"):
                errors.append(
                    f"{location}: TDD approval does not match event {subject_id}"
                )
            if event is not None:
                event_test = event.get("test_id")
                event_spec = event.get("spec_id")
                if record.get("related_test_id") != event_test:
                    errors.append(
                        f"{location}: TDD approval related_test_id must agree with event"
                    )
                if record.get("related_spec_id") != event_spec:
                    errors.append(
                        f"{location}: TDD approval related_spec_id must agree with event"
                    )
                if event.get("status") != "captured":
                    errors.append(
                        f"{location}: TDD approval can reference only captured evidence"
                    )
                finished_at = parse_iso8601(event.get("finished_at"), location)
                if finished_at is None:
                    errors.append(
                        f"{location}: referenced TDD event has invalid finished_at"
                    )
                elif decided_at is not None and decided_at < finished_at:
                    errors.append(
                        f"{location}: approval was decided before the TDD event "
                        f"{subject_id} completed"
                    )
        elif subject_path:
            try:
                target = safe_project_path(root, subject_path, location)
            except DesignPactError as exc:
                errors.append(str(exc))
            else:
                if not target.is_file():
                    errors.append(f"{location}: approval subject is missing: {subject_path}")
                elif sha256_file(target) != subject_hash:
                    errors.append(
                        f"{location}: approval is stale; subject hash has changed"
                    )
        kind = record.get("kind")
        subject_id = record.get("subject_id")
        decision = record.get("decision")
        if (
            isinstance(kind, str)
            and isinstance(subject_id, str)
            and isinstance(subject_hash, str)
            and isinstance(decision, str)
        ):
            decisions_by_subject.setdefault(
                (kind, subject_id, subject_hash), {}
            ).setdefault(decision, []).append(index)
    for (kind, subject_id, subject_hash), decisions in sorted(
        decisions_by_subject.items()
    ):
        if "approved" in decisions and "rejected" in decisions:
            approved_at = ", ".join(str(index) for index in decisions["approved"])
            rejected_at = ", ".join(str(index) for index in decisions["rejected"])
            errors.append(
                f"{path}: conflicting decisions for {kind} {subject_id} "
                f"({subject_hash}): approved at record(s) {approved_at}, "
                f"rejected at record(s) {rejected_at}; rejection takes precedence"
            )
    return errors


def approved_records(root: Path, kind: str | None = None) -> list[dict[str, Any]]:
    records = []
    for record in load_approvals(root):
        if record.get("decision") != "approved":
            continue
        if kind is not None and record.get("kind") != kind:
            continue
        records.append(record)
    return records


def event_hash(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key != "event_sha256"}
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def approved_tdd_event_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for approval in approved_records(root, "tdd_event"):
        subject_id = approval.get("subject_id")
        subject_hash = approval.get("subject_sha256")
        if isinstance(subject_id, str) and isinstance(subject_hash, str):
            result[subject_id] = subject_hash
    return result


def rejected_tdd_event_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for approval in load_approvals(root):
        if approval.get("kind") != "tdd_event":
            continue
        if approval.get("decision") != "rejected":
            continue
        subject_id = approval.get("subject_id")
        subject_hash = approval.get("subject_sha256")
        if isinstance(subject_id, str) and isinstance(subject_hash, str):
            result[subject_id] = subject_hash
    return result


def qualifying_tdd_events(
    events: Iterable[dict[str, Any]],
    event_approvals: dict[str, str],
    test_id: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in events:
        if event.get("test_id") != test_id:
            continue
        approved = (
            event_approvals.get(str(event.get("event_id")))
            == event.get("event_sha256")
        )
        if approved:
            result.append(event)
    return result


def latest_tdd_cycle(
    events: Iterable[dict[str, Any]],
    event_approvals: dict[str, str],
    test_id: str,
) -> list[dict[str, Any]]:
    """Return the latest cycle, resetting at each qualifying Red event."""

    latest: list[dict[str, Any]] = []
    for event in qualifying_tdd_events(events, event_approvals, test_id):
        if event.get("phase") == "red":
            latest = [event]
        elif latest:
            latest.append(event)
    return latest


@dataclass(frozen=True)
class TddAssessment:
    test_id: str
    status: str
    cycle: tuple[dict[str, Any], ...]
    errors: tuple[str, ...]


def assess_tdd_test(
    events: list[dict[str, Any]],
    event_approvals: dict[str, str],
    test_id: str,
    rejected_event_approvals: dict[str, str] | None = None,
) -> TddAssessment:
    cycle = latest_tdd_cycle(events, event_approvals, test_id)
    rejected_in_cycle = [
        event
        for event in cycle
        if (rejected_event_approvals or {}).get(str(event.get("event_id")))
        == event.get("event_sha256")
    ]
    if rejected_in_cycle:
        rejected_ids = ", ".join(
            str(event.get("event_id")) for event in rejected_in_cycle
        )
        return TddAssessment(
            test_id,
            "failed",
            tuple(cycle),
            (
                "latest evidence was independently rejected: "
                f"{rejected_ids}",
            ),
        )
    if not cycle:
        rejected = [
            event
            for event in events
            if event.get("test_id") == test_id
            and (rejected_event_approvals or {}).get(str(event.get("event_id")))
            == event.get("event_sha256")
        ]
        status = "failed" if rejected else "unverified"
        errors = (
            ("latest evidence was independently rejected",)
            if rejected
            else ()
        )
        return TddAssessment(test_id, status, (), errors)
    phases = [str(event.get("phase")) for event in cycle]
    cycle_errors: list[str] = []
    if phases != list(TDD_PHASES):
        cycle_errors.append(
            "latest accepted cycle must be red, green, refactor, verify; "
            f"found {phases}"
        )
    if cycle[0].get("failure_kind") != "behavior":
        cycle_errors.append("Red failure_kind must be behavior")
    stable_fields = (
        ("spec_id", "spec ID"),
        ("test_id", "test ID"),
        ("test_declaration_sha256", "test declaration"),
        ("contract_sha256", "test contract"),
        ("implementation_path", "implementation path"),
        ("implementation_sha256", "implementation hash"),
    )
    for field, label in stable_fields:
        values = {str(event.get(field, "")) for event in cycle}
        if len(values) != 1:
            cycle_errors.append(f"{label} changed during the latest TDD cycle")
    declarations = {
        str(event.get("test_declaration_sha256", "")) for event in cycle
    }
    if len(declarations) != 1:
        cycle_errors.append("test declaration changed during the latest TDD cycle")
    ac_sets = {
        tuple(str(item) for item in event.get("ac_ids", [])) for event in cycle
    }
    if len(ac_sets) != 1:
        cycle_errors.append("AC IDs changed during the latest TDD cycle")
    status = "pass" if not cycle_errors else "failed"
    return TddAssessment(test_id, status, tuple(cycle), tuple(cycle_errors))


def validate_tdd_ledger(
    root: Path,
    contracts: list[dict[str, Any]] | None = None,
    require_accepted: bool = False,
) -> list[str]:
    errors: list[str] = []
    ledger_path = root / "docs" / "verification" / "tdd-ledger.jsonl"
    try:
        events = load_jsonl(ledger_path)
    except DesignPactError as exc:
        return [str(exc)]

    required = (
        "event_id",
        "schema_version",
        "spec_id",
        "ac_ids",
        "test_id",
        "phase",
        "command",
        "exit_code",
        "failure_kind",
        "started_at",
        "finished_at",
        "actor",
        "artifact_path",
        "artifact_sha256",
        "test_declaration_sha256",
        "contract_sha256",
        "implementation_path",
        "implementation_sha256",
        "status",
        "prev_event_sha256",
        "event_sha256",
    )
    previous = ""
    seen_events: set[str] = set()
    try:
        approvals = load_approvals(root)
    except DesignPactError as exc:
        return [str(exc)]
    errors.extend(approval_errors(root))
    approved_event_hashes: dict[str, str] = {}
    for approval in approvals:
        if (
            approval.get("kind") == "tdd_event"
            and approval.get("decision") == "approved"
            and isinstance(approval.get("subject_id"), str)
            and isinstance(approval.get("subject_sha256"), str)
        ):
            approved_event_hashes[str(approval["subject_id"])] = str(
                approval["subject_sha256"]
            )
    rejected_event_hashes = rejected_tdd_event_hashes(root)

    if contracts is None:
        try:
            contracts = load_all_test_contracts(root)
        except DesignPactError as exc:
            contracts = []
            errors.append(str(exc))
    contract_tests: dict[str, dict[str, Any]] = {}
    contract_specs: dict[str, str] = {}
    contract_paths: dict[str, Path] = {}
    for contract in contracts:
        tests = contract.get("tests", [])
        if not isinstance(tests, list):
            continue
        contract_path = root / str(contract.get("_path", ""))
        for test in tests:
            if not isinstance(test, dict):
                continue
            test_id = str(test.get("test_id", ""))
            if test_id in contract_tests:
                errors.append(f"{test_id}: duplicate test contract across L2 files")
            contract_tests[test_id] = test
            contract_specs[test_id] = str(contract.get("spec_id", ""))
            contract_paths[test_id] = contract_path

    for index, event in enumerate(events, start=1):
        location = f"{ledger_path}:{index}"
        errors.extend(
            f"{location}: missing required field {key!r}"
            for key in required
            if key not in event
        )
        event_id = event.get("event_id")
        if not valid_id(event_id, "TDD"):
            errors.append(f"{location}: invalid event_id {event_id!r}")
        if event_id in seen_events:
            errors.append(f"{location}: duplicate event_id {event_id}")
        seen_events.add(event_id)
        assert_values = (
            ("spec_id", "SPEC"),
            ("test_id", "TEST"),
        )
        for key, prefix in assert_values:
            if not valid_id(event.get(key), prefix):
                errors.append(f"{location}: invalid {key} {event.get(key)!r}")
        ac_ids = event.get("ac_ids")
        if not isinstance(ac_ids, list) or not ac_ids:
            errors.append(f"{location}: ac_ids must be a non-empty list")
        else:
            for ac_id in ac_ids:
                if not valid_id(ac_id, "AC"):
                    errors.append(f"{location}: invalid AC ID {ac_id!r}")
        if event.get("schema_version") != "1.0":
            errors.append(f"{location}: schema_version must be '1.0'")
        if event.get("phase") not in TDD_PHASES:
            errors.append(f"{location}: invalid phase {event.get('phase')!r}")
        if event.get("status") not in TDD_STATUSES:
            errors.append(f"{location}: invalid status {event.get('status')!r}")
        failure_kind = event.get("failure_kind")
        if failure_kind is not None and failure_kind not in FAILURE_KINDS:
            errors.append(f"{location}: invalid failure_kind {failure_kind!r}")
        command = event.get("command")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(part, str) or not part for part in command)
        ):
            errors.append(
                f"{location}: command must be a non-empty JSON array of strings"
            )
        actor = event.get("actor")
        if not isinstance(actor, str) or not actor.strip():
            errors.append(f"{location}: actor must be a non-empty identity")
        started_at = parse_iso8601(event.get("started_at"), location)
        finished_at = parse_iso8601(event.get("finished_at"), location)
        if started_at is None:
            errors.append(f"{location}: started_at must be timezone-aware ISO-8601")
        if finished_at is None:
            errors.append(f"{location}: finished_at must be timezone-aware ISO-8601")
        if started_at and finished_at and finished_at < started_at:
            errors.append(f"{location}: finished_at precedes started_at")
        exit_code = event.get("exit_code")
        if not isinstance(exit_code, int):
            errors.append(f"{location}: exit_code must be an integer")
        elif event.get("phase") == "red" and exit_code == 0:
            errors.append(f"{location}: Red evidence must have non-zero exit_code")
        elif event.get("phase") != "red" and exit_code != 0:
            errors.append(
                f"{location}: captured {event.get('phase')} must have zero exit_code"
            )
        artifact_path = event.get("artifact_path")
        if artifact_path:
            try:
                artifact = safe_project_path(root, artifact_path, location)
            except DesignPactError as exc:
                errors.append(str(exc))
                artifact = None
            if artifact is not None and not artifact.exists():
                errors.append(f"{location}: evidence artifact is missing: {artifact_path}")
            elif (
                artifact is not None
                and artifact.is_file()
                and sha256_file(artifact) != event.get("artifact_sha256")
            ):
                errors.append(f"{location}: evidence artifact hash mismatch")
        artifact_hash = event.get("artifact_sha256")
        if not isinstance(artifact_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", artifact_hash
        ):
            errors.append(f"{location}: artifact_sha256 must be lowercase SHA-256")
        declaration_hash = event.get("test_declaration_sha256")
        if not isinstance(declaration_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", declaration_hash
        ):
            errors.append(
                f"{location}: test_declaration_sha256 must be lowercase SHA-256"
            )
        contract_hash = event.get("contract_sha256")
        if (
            not isinstance(contract_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", contract_hash)
            or contract_hash == "0" * 64
        ):
            errors.append(f"{location}: contract_sha256 must be non-zero SHA-256")
        implementation_path = event.get("implementation_path")
        implementation = None
        if not isinstance(implementation_path, str) or not implementation_path.strip():
            errors.append(f"{location}: implementation_path must be non-empty")
        else:
            try:
                implementation = safe_project_path(
                    root, implementation_path, location
                )
            except DesignPactError as exc:
                errors.append(str(exc))
            else:
                if not implementation.is_file():
                    errors.append(
                        f"{location}: implementation file is missing: "
                        f"{implementation_path}"
                    )
        implementation_hash = event.get("implementation_sha256")
        if (
            not isinstance(implementation_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", implementation_hash)
            or implementation_hash == "0" * 64
        ):
            errors.append(
                f"{location}: implementation_sha256 must be non-zero SHA-256"
            )
        test_id = str(event.get("test_id", ""))
        contract_path = contract_paths.get(test_id)
        if contract_path is None:
            errors.append(f"{location}: TDD evidence has no matching test contract")
        elif not contract_path.is_file():
            errors.append(
                f"{location}: current test contract is missing: "
                f"{project_relative(contract_path, root)}"
            )
        elif contract_hash != sha256_file(contract_path):
            errors.append(
                f"{location}: current contract hash differs from TDD evidence"
            )
        if implementation is not None and implementation.is_file():
            if implementation_hash != sha256_file(implementation):
                errors.append(
                    f"{location}: current implementation hash differs from TDD "
                    "evidence"
                )
            contract_test = contract_tests.get(test_id)
            if contract_test is not None:
                test_path = contract_test.get("implementation_path")
                symbol = contract_test.get("implementation_symbol")
                if isinstance(test_path, str) and test_path and isinstance(symbol, str) and symbol:
                    try:
                        current_declaration = extract_test_declaration(
                            root / test_path,
                            test_id,
                            symbol,
                        )
                    except DesignPactError as exc:
                        errors.append(str(exc))
                    else:
                        if current_declaration.sha256 != declaration_hash:
                            errors.append(
                                f"{location}: current test declaration hash differs "
                                "from TDD evidence"
                            )
        if event.get("prev_event_sha256") != previous:
            errors.append(f"{location}: ledger hash chain predecessor mismatch")
        expected_hash = event_hash(event)
        if event.get("event_sha256") != expected_hash:
            errors.append(f"{location}: event hash is invalid")
        approval_hash = approved_event_hashes.get(str(event_id))
        if approval_hash is not None and approval_hash != event.get("event_sha256"):
            errors.append(f"{location}: approval for {event_id} is stale")
        previous = str(event.get("event_sha256", ""))

    if not require_accepted:
        return errors

    by_test: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_test.setdefault(str(event.get("test_id")), []).append(event)

    for test_id in sorted(set(by_test) - set(contract_tests)):
        errors.append(f"{test_id}: TDD evidence has no matching test contract")

    for test_id, test in contract_tests.items():
        planning_status = test.get("planning_status", "planned")
        if planning_status in ("blocked", "out_of_scope", "deferred"):
            continue
        assessment = assess_tdd_test(
            by_test.get(test_id, []),
            approved_event_hashes,
            test_id,
            rejected_event_hashes,
        )
        if assessment.status != "pass":
            phase_names = [str(event.get("phase")) for event in assessment.cycle]
            errors.append(
                f"{test_id}: latest TDD cycle is not valid "
                f"({phase_names or 'no accepted phases'}): "
                f"{'; '.join(assessment.errors) or assessment.status}"
            )
            continue
        cycle = list(assessment.cycle)
        expected_acs = list(test.get("ac_ids", []))
        first_declaration: str | None = None
        for phase in TDD_PHASES:
            phase_events = [e for e in cycle if e.get("phase") == phase]
            if not phase_events:
                continue
            event = phase_events[0]
            if event.get("spec_id") != contract_specs.get(test_id):
                errors.append(f"{test_id}: {phase} spec ID disagrees with contract")
            if list(event.get("ac_ids", [])) != expected_acs:
                errors.append(f"{test_id}: {phase} AC IDs disagree with contract")
            declaration_hash = str(event.get("test_declaration_sha256", ""))
            if first_declaration is None:
                first_declaration = declaration_hash
            elif declaration_hash != first_declaration:
                errors.append(f"{test_id}: test declaration changed during {phase}")
            if phase == "red" and event.get("failure_kind") != "behavior":
                errors.append(f"{test_id}: Red failure is not behavior-level")
        implementation_path = test.get("implementation_path")
        implementation_symbol = test.get("implementation_symbol")
        if implementation_path and implementation_symbol:
            try:
                current = extract_test_declaration(
                    root / str(implementation_path),
                    test_id,
                    str(implementation_symbol),
                )
                if current.ac_ids != tuple(expected_acs):
                    errors.append(
                        f"{test_id}: Kotlin marker ACs disagree with contract"
                    )
                if first_declaration and current.sha256 != first_declaration:
                    errors.append(
                        f"{test_id}: current test declaration differs from ledger"
                    )
            except DesignPactError as exc:
                errors.append(str(exc))
    return errors


ARTIFACT_REGISTRY_RELATIVE = "docs/project/artifact-ids.yaml"
ARTIFACT_LIFECYCLES = ("active", "tombstone")

RESERVED_ARTIFACT_IDS = frozenset(
    {
        "ART-001",
        "ART-002",
        "ART-010",
        "ART-011",
        "ART-012",
        "ART-013",
        "ART-014",
        "ART-020",
        "ART-021",
        "ART-022",
        "ART-023",
        "ART-024",
        "ART-025",
        "ART-026",
        "ART-030",
        "ART-031",
        "ART-032",
        "ART-040",
        "ART-050",
        "ART-070",
        "ART-080",
        "ART-090",
        "ART-100",
        "ART-200",
        "ART-201",
        "ART-202",
        "ART-300",
        "ART-301",
        "ART-600",
    }
)


def artifact_registry_path(root: Path) -> Path:
    return root / ARTIFACT_REGISTRY_RELATIVE


def load_artifact_registry(root: Path) -> dict[str, Any]:
    path = artifact_registry_path(root)
    registry = load_yaml(path)
    if not isinstance(registry, dict):
        raise DesignPactError(f"{path}: expected a mapping")
    entries = registry.get("entries")
    if not isinstance(entries, list):
        raise DesignPactError(f"{path}: entries must be a list")
    return registry


def artifact_registry_errors(root: Path) -> list[str]:
    path = artifact_registry_path(root)
    try:
        registry = load_artifact_registry(root)
    except DesignPactError as exc:
        return [str(exc)]
    errors: list[str] = []
    if registry.get("artifact_type") != "artifact_registry":
        errors.append(f"{path}: artifact_type must be 'artifact_registry'")
    if registry.get("schema_version") != "1.0":
        errors.append(f"{path}: schema_version must be '1.0'")
    version = registry.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        errors.append(f"{path}: version must be a positive integer")
    allowed_registry_keys = {"artifact_type", "schema_version", "version", "entries"}
    for key in registry:
        if key not in allowed_registry_keys:
            errors.append(f"{path}: unexpected registry field {key!r}")
    seen_ids: dict[str, str] = {}
    seen_keys: dict[str, tuple[str, str]] = {}
    seen_paths: dict[str, str] = {}
    for index, entry in enumerate(registry.get("entries", []), start=1):
        location = f"{path}:{index}"
        if not isinstance(entry, dict):
            errors.append(f"{location}: expected a mapping")
            continue
        allowed_entry_keys = {
            "key",
            "artifact_id",
            "path",
            "artifact_type",
            "lifecycle",
            "removed_at",
            "reason",
        }
        for entry_key in entry:
            if entry_key not in allowed_entry_keys:
                errors.append(f"{location}: unexpected entry field {entry_key!r}")
        key = entry.get("key")
        artifact_id = entry.get("artifact_id")
        relative = entry.get("path")
        artifact_type = entry.get("artifact_type")
        lifecycle = entry.get("lifecycle", "active")
        if not isinstance(key, str) or not key:
            errors.append(f"{location}: key must be a non-empty string")
        if not valid_id(artifact_id, "ART"):
            errors.append(f"{location}: invalid artifact_id {artifact_id!r}")
        elif artifact_id in seen_ids:
            errors.append(
                f"{location}: artifact_id {artifact_id} is already assigned to "
                f"{seen_ids[artifact_id]!r}"
            )
        else:
            seen_ids[str(artifact_id)] = str(key)
        if not isinstance(artifact_type, str) or not artifact_type:
            errors.append(f"{location}: artifact_type must be a non-empty string")
        if lifecycle not in ARTIFACT_LIFECYCLES:
            errors.append(
                f"{location}: lifecycle must be one of "
                f"{', '.join(ARTIFACT_LIFECYCLES)}"
            )
        removed_at = entry.get("removed_at")
        reason = entry.get("reason")
        if lifecycle == "tombstone":
            if parse_iso8601(removed_at, f"{location}/removed_at") is None:
                errors.append(
                    f"{location}: tombstone removed_at must be a timezone-aware "
                    "ISO-8601 timestamp"
                )
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{location}: tombstone reason must be non-empty")
        else:
            if "removed_at" in entry:
                errors.append(
                    f"{location}: removed_at is only valid for tombstone entries"
                )
            if "reason" in entry:
                errors.append(
                    f"{location}: reason is only valid for tombstone entries"
                )
        if not isinstance(relative, str) or not relative:
            errors.append(f"{location}: path must be a non-empty string")
        elif relative in seen_paths:
            errors.append(
                f"{location}: duplicate artifact path {relative!r}; already owned "
                f"by {seen_paths[relative]!r}"
            )
        else:
            seen_paths[relative] = str(key)
            try:
                safe_project_path(root, relative, location)
            except DesignPactError as exc:
                errors.append(str(exc))
        if isinstance(key, str) and key:
            identity = (str(relative), str(artifact_type))
            if key in seen_keys:
                errors.append(f"{location}: duplicate registry key {key!r}")
            else:
                seen_keys[key] = identity
    return errors


def allocate_artifact_entry(
    registry: dict[str, Any],
    *,
    key: str,
    path: str,
    artifact_type: str,
    preferred_id: str | None = None,
) -> str:
    """Return a stable registered ART ID, allocating a new ID only when needed."""

    entries = registry.setdefault("entries", [])
    if not isinstance(entries, list):
        raise DesignPactError("artifact registry entries must be a list")
    by_key = {
        str(entry.get("key")): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("key")
    }
    used = {
        str(entry.get("artifact_id"))
        for entry in entries
        if isinstance(entry, dict) and valid_id(entry.get("artifact_id"), "ART")
    }
    entry = by_key.get(key)
    if entry is not None:
        if entry.get("lifecycle", "active") == "tombstone":
            raise DesignPactError(
                f"{key}: artifact identity is tombstoned and cannot be reactivated"
            )
        if entry.get("path") != path or entry.get("artifact_type") != artifact_type:
            raise DesignPactError(
                f"{key}: registry identity is immutable; refuse to change "
                f"{entry.get('path')!r}/{entry.get('artifact_type')!r} to "
                f"{path!r}/{artifact_type!r}"
            )
        if preferred_id and entry.get("artifact_id") != preferred_id:
            raise DesignPactError(
                f"{key}: existing artifact ID {entry.get('artifact_id')} does not "
                f"match preferred ID {preferred_id}"
            )
        return str(entry["artifact_id"])
    if path in {
        str(item.get("path"))
        for item in entries
        if isinstance(item, dict) and item.get("path")
    }:
        raise DesignPactError(f"{key}: artifact path {path!r} is already registered")
    if preferred_id:
        if not valid_id(preferred_id, "ART"):
            raise DesignPactError(f"{key}: invalid preferred artifact ID {preferred_id!r}")
        if preferred_id in used:
            raise DesignPactError(
                f"{key}: preferred artifact ID {preferred_id} is already in use"
            )
        artifact_id = preferred_id
    else:
        artifact_id = ""
        for number in range(101, 1000):
            candidate = f"ART-{number:03d}"
            if candidate not in used and candidate not in RESERVED_ARTIFACT_IDS:
                artifact_id = candidate
                break
        if not artifact_id:
            raise DesignPactError("no Artifact IDs remain in ART-101..ART-999")
    entries.append(
        {
            "key": key,
            "artifact_id": artifact_id,
            "path": path,
            "artifact_type": artifact_type,
        }
    )
    entries.sort(key=lambda item: (str(item.get("artifact_id")), str(item.get("key"))))
    return artifact_id


def retire_artifact_entry(
    registry: dict[str, Any],
    *,
    key: str,
    removed_at: str,
    reason: str,
) -> None:
    """Permanently retire an active artifact while preserving its ID and path."""

    if parse_iso8601(removed_at, "removed_at") is None:
        raise DesignPactError(
            "removed_at must be a timezone-aware ISO-8601 timestamp"
        )
    if not isinstance(reason, str) or not reason.strip():
        raise DesignPactError("tombstone reason must be non-empty")
    if any(ord(character) < 32 or ord(character) == 127 for character in reason):
        raise DesignPactError("tombstone reason must not contain control characters")
    entries = registry.get("entries")
    if not isinstance(entries, list):
        raise DesignPactError("artifact registry entries must be a list")
    entry = next(
        (
            item
            for item in entries
            if isinstance(item, dict) and item.get("key") == key
        ),
        None,
    )
    if entry is None:
        raise DesignPactError(f"unknown artifact key {key!r}")
    if entry.get("lifecycle", "active") == "tombstone":
        raise DesignPactError(f"{key}: artifact identity is already tombstoned")
    entry["lifecycle"] = "tombstone"
    entry["removed_at"] = removed_at
    entry["reason"] = reason.strip()


def project_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise DesignPactError(f"{path}: must be inside project root {root}") from exc


def safe_project_path(root: Path, relative: Any, location: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise DesignPactError(f"{location}: expected a non-empty relative path")
    raw = Path(relative.strip())
    if raw.is_absolute():
        raise DesignPactError(f"{location}: expected a relative path: {relative}")
    resolved_root = root.expanduser().resolve()
    candidate = (resolved_root / raw).resolve()
    if candidate == resolved_root:
        raise DesignPactError(
            f"{location}: expected a path inside the project, not the project root"
        )
    if candidate == Path(candidate.anchor):
        raise DesignPactError(f"{location}: path must not be a filesystem root")
    if candidate == Path.home().resolve():
        raise DesignPactError(f"{location}: path must not be the home directory")
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise DesignPactError(f"{location}: path escapes project root: {relative}") from exc
    return candidate


def emit_result(errors: Iterable[str], summary: dict[str, Any] | None = None) -> int:
    error_list = list(errors)
    payload: dict[str, Any] = {
        "ok": not error_list,
        "conclusion": "pass" if not error_list else "fail",
        "errors": error_list,
    }
    if summary:
        payload["summary"] = summary
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not error_list else 1


def result_payload(
    errors: Iterable[str],
    checks: Iterable[str],
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error_list = list(errors)
    payload: dict[str, Any] = {
        "ok": not error_list,
        "conclusion": "pass" if not error_list else "fail",
        "checks_completed": list(checks),
        "errors": error_list,
    }
    if summary:
        payload["summary"] = summary
    return payload


def run_main(function: Any) -> None:
    try:
        raise SystemExit(function())
    except DesignPactError as exc:
        print(
            json.dumps(
                {"ok": False, "conclusion": "fail", "errors": [str(exc)]},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
