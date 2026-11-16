#!/usr/bin/env python3
"""Validate Design Pact artifact paths, schemas, hashes, and evidence freshness."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import (
    DesignPactError,
    approval_errors,
    hash_sources,
    load_all_test_contracts,
    load_artifact_registry,
    load_approvals,
    load_jsonl,
    load_specs,
    load_yaml,
    parse_iso8601,
    project_relative,
    read_text,
    safe_project_path,
    sha256_file,
    split_frontmatter,
    validate_metadata,
    validate_schema,
    validate_tdd_ledger,
    artifact_registry_errors,
    extract_test_declaration,
    valid_id,
)
from preflight import inspect_figma_manifest


SKILL_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_SCHEMAS = SKILL_ROOT / "assets" / "project-docs-template" / "schemas"

STATE_PATH = "docs/project/state.yaml"
REGISTRY_PATH = "docs/project/artifact-ids.yaml"
ARTIFACT_INDEX_PATH = "docs/project/artifact-index.yaml"
APPROVALS_PATH = "docs/project/approvals.jsonl"
CHARTER_PATH = "docs/product/product-charter.md"
RELEASE_SCOPE_PATH = "docs/product/release-scope.yaml"
SCREEN_INVENTORY_PATH = "docs/design/screen-inventory.yaml"
EXCEPTIONS_PATH = "docs/design/design-exceptions.yaml"
VISUAL_POLICY_PATH = "docs/verification/visual-policy.yaml"
SCOPE_AUDIT_PATH = "docs/verification/scope-audit.md"
TDD_LEDGER_PATH = "docs/verification/tdd-ledger.jsonl"
TDD_REPORT_PATH = "docs/verification/tdd-report.md"
TEST_INDEX_PATH = "docs/verification/test-cases/index.md"
README_PATH = "docs/README.md"
BOOTSTRAP_MANIFEST_PATH = "docs/verification/bootstrap/manifest.yaml"

REQUIRED_DIRECTORIES = (
    "docs/project/decisions",
    "docs/product",
    "docs/design/figma-references",
    "docs/specs/L1",
    "docs/specs/L2",
    "docs/verification/test-cases",
    "docs/verification/tdd-artifacts",
    "docs/verification/visual-reports",
    "docs/verification/baselines",
    "docs/verification/bootstrap",
)
REQUIRED_FILES = (
    STATE_PATH,
    REGISTRY_PATH,
    ARTIFACT_INDEX_PATH,
    APPROVALS_PATH,
    CHARTER_PATH,
    "docs/product/journey-map.yaml",
    "docs/product/feature-map.yaml",
    "docs/product/coverage-matrix.yaml",
    RELEASE_SCOPE_PATH,
    "docs/design/screen-inventory.yaml",
    "docs/design/component-map.yaml",
    "docs/design/token-map.yaml",
    "docs/design/asset-inventory.yaml",
    "docs/design/interaction-contract.md",
    EXCEPTIONS_PATH,
    "docs/design/gaps.yaml",
    TEST_INDEX_PATH,
    TDD_LEDGER_PATH,
    TDD_REPORT_PATH,
    BOOTSTRAP_MANIFEST_PATH,
    SCOPE_AUDIT_PATH,
    VISUAL_POLICY_PATH,
    README_PATH,
)
SCHEMA_BY_ARTIFACT_TYPE = {
    "project_state": "state.schema.json",
    "journey_map": "journey-map.schema.json",
    "feature_map": "feature-map.schema.json",
    "coverage_matrix": "coverage-matrix.schema.json",
    "release_scope": "release-scope.schema.json",
    "screen_inventory": "screen-inventory.schema.json",
    "component_map": "design-maps.schema.json",
    "token_map": "design-maps.schema.json",
    "asset_inventory": "design-maps.schema.json",
    "design_exceptions": "design-maps.schema.json",
    "gaps": "design-maps.schema.json",
    "test_case_contract": "test-case-contract.schema.json",
    "visual_policy": "visual-policy.schema.json",
    "bootstrap_manifest": "bootstrap-manifest.schema.json",
    "artifact_index": "artifact-index.schema.json",
    "figma_reference": "binary-manifest.schema.json",
    "visual_baseline": "binary-manifest.schema.json",
    "visual_report": "visual-report.schema.json",
}
METADATA_MARKDOWN_TYPES = {
    "product_charter",
    "interaction_contract",
    "scope_audit",
    "specification",
    "decision",
}
GENERATOR_DOC_PATH_RE = re.compile(
    r"^docs/(?:README\.md|verification/(?:tdd-report\.md|"
    r"test-cases/(?:index|(?:SCREEN|FLOW)-[^/]+/test-cases)\.md))$"
)
PAGE_DIRECTORY_RE = re.compile(
    r"^(SCREEN|FLOW)-(?!000)[0-9]{3}-[a-z0-9]+(?:-[a-z0-9]+)*$"
)
MARKER_TEST_RE = re.compile(r"^\s*// DESIGN_PACT: (TEST-(?!000)[0-9]{3}) =>", re.MULTILINE)
PLACEHOLDER_RE = re.compile(
    r"(?:^|[\s_.:/-])(?:ai|agent|bot|automation|todo|tbd|placeholder|unknown)"
    r"(?:$|[\s.:/-])",
    re.IGNORECASE,
)
DESIGN_CONTRACT_PATHS = (
    "docs/design/screen-inventory.yaml",
    "docs/design/component-map.yaml",
    "docs/design/token-map.yaml",
    "docs/design/asset-inventory.yaml",
    "docs/design/interaction-contract.md",
    EXCEPTIONS_PATH,
    "docs/design/gaps.yaml",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, help="Design Pact project.")
    parser.add_argument(
        "--require-release",
        action="store_true",
        help="Require current generated views, accepted TDD, visual evidence, and approvals.",
    )
    return parser.parse_args()


def _try_load_yaml(path: Path, errors: list[str], *, metadata: bool = True) -> dict[str, Any] | None:
    try:
        value = load_yaml(path)
    except DesignPactError as exc:
        errors.append(str(exc))
        return None
    if not isinstance(value, dict):
        errors.append(f"{path}: expected a mapping")
        return None
    if metadata:
        location = str(path)
        errors.extend(validate_metadata(value, location))
    return value


def _schema_path(root: Path, name: str) -> Path:
    return root / "schemas" / name


def _load_schema(root: Path, name: str, errors: list[str]) -> dict[str, Any] | None:
    path = _schema_path(root, name)
    if not path.is_file():
        errors.append(f"{project_relative(path, root)}: bundled schema is missing")
        return None
    try:
        value = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        errors.append(f"{project_relative(path, root)}: invalid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{project_relative(path, root)}: schema must be an object")
        return None
    return value


def _validate_with_schema(
    value: Any,
    schema: dict[str, Any] | None,
    location: str,
    errors: list[str],
) -> None:
    if schema is None:
        return
    errors.extend(validate_schema(value, schema, location))


def _validate_schema_copies(root: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    project_dir = root / "schemas"
    if not project_dir.is_dir():
        errors.append("schemas: project-local schema directory is missing")
        return schemas
    bundled_names = sorted(path.name for path in BUNDLED_SCHEMAS.glob("*.json"))
    project_names = sorted(path.name for path in project_dir.glob("*.json"))
    for name in bundled_names:
        bundled = BUNDLED_SCHEMAS / name
        project = project_dir / name
        if not project.is_file():
            errors.append(f"schemas/{name}: required project schema is missing")
            continue
        if sha256_file(project) != sha256_file(bundled):
            errors.append(
                f"schemas/{name}: project schema differs from the Design Pact schema"
            )
        schema = _load_schema(root, name, errors)
        if schema is not None:
            schemas[name] = schema
    for name in sorted(set(project_names) - set(bundled_names)):
        errors.append(f"schemas/{name}: unexpected schema file")
    return schemas


def _metadata_for_document(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        metadata, _ = split_frontmatter(read_text(path), path)
    except DesignPactError as exc:
        errors.append(str(exc))
        return None
    errors.extend(validate_metadata(metadata, str(path)))
    return metadata


def _register_metadata_documents(
    root: Path,
    errors: list[str],
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, dict[str, Any]]]:
    documents: list[tuple[str, dict[str, Any]]] = []
    by_path: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "docs").rglob("*")):
        if not path.is_file():
            continue
        relative = project_relative(path, root)
        if path.suffix in (".yaml", ".yml"):
            try:
                value = load_yaml(path)
            except DesignPactError as exc:
                errors.append(str(exc))
                continue
            if not isinstance(value, dict):
                errors.append(f"{relative}: expected a mapping")
                continue
            if "artifact_id" not in value and relative != REGISTRY_PATH:
                continue
            if relative == REGISTRY_PATH:
                continue
            errors.extend(validate_metadata(value, relative))
            documents.append((relative, value))
            by_path[relative] = value
        elif path.suffix == ".md":
            metadata = _metadata_for_document(path, errors)
            if metadata is None:
                continue
            documents.append((relative, metadata))
            by_path[relative] = metadata
    return documents, by_path


def _validate_registry_completeness(
    root: Path,
    documents: list[tuple[str, dict[str, Any]]],
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    errors.extend(artifact_registry_errors(root))
    try:
        registry = load_artifact_registry(root)
    except DesignPactError as exc:
        errors.append(str(exc))
        return {}
    entries = {
        str(entry.get("path")): entry
        for entry in registry.get("entries", [])
        if isinstance(entry, dict) and entry.get("path")
    }
    schema = _load_schema(root, "artifact-registry.schema.json", errors)
    _validate_with_schema(registry, schema, REGISTRY_PATH, errors)
    registered_documents = set()
    for relative, metadata in documents:
        entry = entries.get(relative)
        if entry is None:
            errors.append(f"{relative}: metadata-bearing artifact is not registered")
            continue
        registered_documents.add(relative)
        if entry.get("lifecycle", "active") != "active":
            errors.append(f"{relative}: registered artifact must have active lifecycle")
        if entry.get("artifact_id") != metadata.get("artifact_id"):
            errors.append(
                f"{relative}: registry artifact_id does not match document metadata"
            )
        if entry.get("artifact_type") != metadata.get("artifact_type"):
            errors.append(
                f"{relative}: registry artifact_type does not match document metadata"
            )
    for relative, entry in sorted(entries.items()):
        target = root / relative
        if entry.get("lifecycle", "active") == "tombstone":
            if target.exists():
                errors.append(
                    f"{REGISTRY_PATH}: tombstoned path still exists: {relative}"
                )
            continue
        if not target.is_file():
            errors.append(
                f"{REGISTRY_PATH}: active artifact file is missing: {relative}"
            )
        if target.is_file() and relative not in registered_documents:
            errors.append(
                f"{REGISTRY_PATH}: active entry {relative} has no document metadata"
            )
    return entries


def _validate_yaml_schemas(
    root: Path,
    schemas: dict[str, dict[str, Any]],
    documents: list[tuple[str, dict[str, Any]]],
    errors: list[str],
) -> None:
    for relative, value in documents:
        artifact_type = value.get("artifact_type")
        schema_name = SCHEMA_BY_ARTIFACT_TYPE.get(str(artifact_type))
        if schema_name:
            _validate_with_schema(value, schemas.get(schema_name), relative, errors)
    try:
        specs = load_specs(root)
    except DesignPactError as exc:
        errors.append(str(exc))
    else:
        for path, metadata, _ in specs:
            if "generator" in metadata:
                continue
            relative = project_relative(path, root)
            _validate_with_schema(
                metadata,
                schemas.get("spec.schema.json"),
                relative,
                errors,
            )
    try:
        contracts = load_all_test_contracts(root)
    except DesignPactError as exc:
        errors.append(str(exc))
    else:
        for contract in contracts:
            relative = str(contract.get("_path"))
            _validate_with_schema(
                contract,
                schemas.get("test-case-contract.schema.json"),
                relative,
                errors,
            )


def _validate_approvals_and_ledger(
    root: Path,
    schemas: dict[str, dict[str, Any]],
    *,
    require_release: bool,
    errors: list[str],
) -> None:
    errors.extend(approval_errors(root))
    approval_schema = schemas.get("approval.schema.json")
    try:
        approvals = load_approvals(root)
    except DesignPactError as exc:
        errors.append(str(exc))
        approvals = []
    for index, record in enumerate(approvals, start=1):
        _validate_with_schema(
            record,
            approval_schema,
            f"{APPROVALS_PATH}:{index}",
            errors,
        )
    event_schema = schemas.get("tdd-event.schema.json")
    try:
        events = load_jsonl(root / TDD_LEDGER_PATH)
    except DesignPactError as exc:
        errors.append(str(exc))
        events = []
    for index, event in enumerate(events, start=1):
        _validate_with_schema(
            event,
            event_schema,
            f"{TDD_LEDGER_PATH}:{index}",
            errors,
        )
    errors.extend(
        validate_tdd_ledger(root, require_accepted=require_release)
    )


def _resolve_evidence_path(
    root: Path,
    manifest_path: Path,
    raw: Any,
    location: str,
    errors: list[str],
) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        errors.append(f"{location}: expected a non-empty evidence path")
        return None
    if Path(raw).is_absolute():
        errors.append(f"{location}: evidence path must be project-relative")
        return None
    candidates = [root / raw, manifest_path.parent / raw]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        if resolved.is_file():
            return resolved
    errors.append(f"{location}: evidence image is missing: {raw}")
    return None


def _check_hash(
    path: Path,
    declared: Any,
    location: str,
    errors: list[str],
) -> None:
    if (
        not isinstance(declared, str)
        or not re.fullmatch(r"[0-9a-f]{64}", declared)
        or declared == "0" * 64
    ):
        errors.append(f"{location}: sha256 must be a non-zero lowercase SHA-256")
        return
    if sha256_file(path) != declared:
        errors.append(f"{location}: declared hash does not match current bytes")


def _validate_figma_references(
    root: Path,
    documents: dict[str, dict[str, Any]],
    state: dict[str, Any],
    *,
    require_release: bool,
    errors: list[str],
) -> list[dict[str, Any]]:
    base = root / "docs/design/figma-references"
    manifests = sorted(base.rglob("manifest.yaml"))
    references: list[dict[str, Any]] = []
    inventory = (
        _try_load_yaml(root / SCREEN_INVENTORY_PATH, errors)
        if (root / SCREEN_INVENTORY_PATH).is_file()
        else {}
    )
    if inventory is None:
        inventory = {}
    screens = {
        str(item.get("id")): item
        for item in inventory.get("screens", [])
        if isinstance(item, dict)
    }
    flows = {
        str(item.get("id")): item
        for item in inventory.get("flows", [])
        if isinstance(item, dict)
    }
    states = {
        str(item.get("id")): item
        for item in inventory.get("states", [])
        if isinstance(item, dict)
    }
    snapshot = state.get("design_snapshot", {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    for path in manifests:
        relative = project_relative(path, root)
        try:
            manifest = load_yaml(path)
        except DesignPactError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(manifest, dict):
            errors.append(f"{relative}: expected a mapping")
            continue
        references.append(manifest)
        for key in ("screen_id", "state_id"):
            prefix = "SCREEN" if key == "screen_id" else "STATE"
            if not valid_id(manifest.get(key), prefix):
                errors.append(f"{relative}: invalid {key} {manifest.get(key)!r}")
        screen_id = str(manifest.get("screen_id"))
        state_id = str(manifest.get("state_id"))
        if screen_id not in screens and screen_id not in flows:
            errors.append(f"{relative}: screen_id references an unknown slice")
        if state_id not in states:
            errors.append(f"{relative}: state_id references an unknown state")
        elif states[state_id].get("screen_id") != screen_id:
            errors.append(f"{relative}: state does not belong to the declared screen")
        if require_release:
            if manifest.get("revision") != snapshot.get("revision"):
                errors.append(f"{relative}: Figma revision differs from the project snapshot")
            if manifest.get("file_key") not in snapshot.get("file_keys", []):
                errors.append(f"{relative}: Figma file key is absent from the project snapshot")
        path_value = manifest.get("path")
        image = _resolve_evidence_path(
            root, path, path_value, f"{relative}.path", errors
        )
        if image is not None:
            _check_hash(image, manifest.get("sha256"), relative, errors)
        registered = documents.get(relative)
        if registered is None:
            errors.append(f"{relative}: Figma manifest is not registered")
        elif registered.get("artifact_type") != "figma_reference":
            errors.append(f"{relative}: artifact_type must be figma_reference")
        summary, manifest_errors = inspect_figma_manifest(path)
        errors.extend(manifest_errors)
        if summary.get("status") != "structured":
            errors.append(f"{relative}: structured Figma evidence is required")
    if require_release and not manifests:
        errors.append("docs/design/figma-references: no structured Figma evidence")
    return references


def _validate_bootstrap(
    root: Path,
    schemas: dict[str, dict[str, Any]],
    *,
    require_release: bool,
    errors: list[str],
) -> dict[str, Any]:
    path = root / BOOTSTRAP_MANIFEST_PATH
    manifest = _try_load_yaml(path, errors)
    if manifest is None:
        return {}
    _validate_with_schema(
        manifest,
        schemas.get("bootstrap-manifest.schema.json"),
        BOOTSTRAP_MANIFEST_PATH,
        errors,
    )
    if manifest.get("artifact_id") != "ART-090":
        errors.append(f"{BOOTSTRAP_MANIFEST_PATH}: artifact_id must be ART-090")
    created_at = parse_iso8601(manifest.get("created_at"), BOOTSTRAP_MANIFEST_PATH)
    if created_at is None:
        errors.append(f"{BOOTSTRAP_MANIFEST_PATH}: created_at must be ISO-8601")
    toolchain = manifest.get("toolchain", {})
    if isinstance(toolchain, dict):
        java = Path(str(toolchain.get("java", "")))
        gradle = Path(str(toolchain.get("gradle", "")))
        sdk = Path(str(toolchain.get("android_sdk", "")))
        if not java.is_file():
            errors.append(f"{BOOTSTRAP_MANIFEST_PATH}: Java toolchain path is missing")
        if not gradle.is_file():
            errors.append(f"{BOOTSTRAP_MANIFEST_PATH}: Gradle launcher path is missing")
        if not (sdk / "platforms" / "android-35").is_dir():
            errors.append(
                f"{BOOTSTRAP_MANIFEST_PATH}: Android SDK platform 35 is missing"
            )
    commands = manifest.get("commands")
    if not isinstance(commands, list):
        errors.append(f"{BOOTSTRAP_MANIFEST_PATH}: commands must be a list")
        commands = []
    names = [str(command.get("name")) for command in commands if isinstance(command, dict)]
    expected_names = ("generate-gradle-wrapper", "assemble-debug-and-unit-test")
    if names != list(expected_names):
        errors.append(
            f"{BOOTSTRAP_MANIFEST_PATH}: commands must be exactly "
            f"{', '.join(expected_names)}"
        )
    all_passed = True
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            continue
        location = f"{BOOTSTRAP_MANIFEST_PATH}.commands[{index}]"
        argv = command.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(part, str) or not part for part in argv)
        ):
            errors.append(f"{location}: argv must be a non-empty string array")
        status = command.get("status")
        if status == "passed":
            if command.get("exit_code") != 0:
                errors.append(f"{location}: passed command must exit with 0")
        elif status == "failed":
            all_passed = False
            code = command.get("exit_code")
            if code == 0:
                errors.append(f"{location}: failed command cannot exit with 0")
        elif status == "not_run":
            all_passed = False
            if not command.get("launch_error"):
                errors.append(f"{location}: not_run command needs launch_error")
        else:
            all_passed = False
            errors.append(f"{location}: invalid command status {status!r}")
        if status in ("passed", "failed"):
            started = parse_iso8601(command.get("started_at"), f"{location}.started_at")
            finished = parse_iso8601(command.get("finished_at"), f"{location}.finished_at")
            if started is None or finished is None or finished < started:
                errors.append(f"{location}: command timestamps are invalid")
            log_path = command.get("log_path")
            if not isinstance(log_path, str) or not log_path:
                errors.append(f"{location}: command log_path is required")
            else:
                try:
                    log = safe_project_path(root, log_path, f"{location}.log_path")
                except DesignPactError as exc:
                    errors.append(str(exc))
                else:
                    if not log.is_file():
                        errors.append(f"{location}: command log is missing")
                    elif command.get("log_sha256") != sha256_file(log):
                        errors.append(f"{location}: command log hash does not match")
    conclusion = manifest.get("conclusion")
    expected_conclusion = "pass" if all_passed and len(commands) == 2 else "fail"
    if conclusion != expected_conclusion:
        errors.append(
            f"{BOOTSTRAP_MANIFEST_PATH}: conclusion must be {expected_conclusion!r}"
        )
    if require_release and conclusion != "pass":
        errors.append(f"{BOOTSTRAP_MANIFEST_PATH}: release requires a passing build")
    if require_release and not (root / "gradlew").is_file():
        errors.append("gradlew: release requires the generated Gradle wrapper")
    return manifest


def _generated_view_errors(
    root: Path,
    documents: dict[str, dict[str, Any]],
    index_entries: dict[str, dict[str, Any]],
    *,
    require_release: bool,
    errors: list[str],
) -> None:
    generated = [
        (relative, metadata)
        for relative, metadata in documents.items()
        if metadata.get("generator") == "render_reports.py"
    ]
    for relative, metadata in generated:
        sources = metadata.get("generated_from")
        source_hash = metadata.get("source_sha256")
        generated_at = parse_iso8601(metadata.get("generated_at"), relative)
        if generated_at is None:
            errors.append(f"{relative}: generated_at must be ISO-8601")
        if not isinstance(sources, list):
            errors.append(f"{relative}: generated_from must be a list")
            continue
        normalized_sources: list[str] = []
        for source in sources:
            try:
                safe_project_path(root, source, f"{relative}.generated_from")
            except DesignPactError as exc:
                errors.append(str(exc))
            else:
                normalized_sources.append(str(source))
        unrendered = not normalized_sources and source_hash == "0" * 64
        if require_release and unrendered:
            errors.append(f"{relative}: generated view has not been rendered")
        elif normalized_sources and source_hash != hash_sources(root, normalized_sources):
            errors.append(
                f"{relative}: generated view is stale; canonical source hash changed"
            )
        if relative != ARTIFACT_INDEX_PATH and relative not in index_entries:
            if require_release or not unrendered:
                errors.append(f"{relative}: generated view is missing from artifact index")
        if not GENERATOR_DOC_PATH_RE.fullmatch(relative) and relative != ARTIFACT_INDEX_PATH:
            errors.append(f"{relative}: unexpected generated Markdown path")


def _validate_artifact_index(
    root: Path,
    schemas: dict[str, dict[str, Any]],
    documents: dict[str, dict[str, Any]],
    *,
    require_release: bool,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    value = _try_load_yaml(root / ARTIFACT_INDEX_PATH, errors)
    if value is None:
        return {}
    _validate_with_schema(
        value,
        schemas.get("artifact-index.schema.json"),
        ARTIFACT_INDEX_PATH,
        errors,
    )
    raw_entries = value.get("entries")
    if not isinstance(raw_entries, list):
        errors.append(f"{ARTIFACT_INDEX_PATH}: entries must be a list")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(raw_entries):
        location = f"{ARTIFACT_INDEX_PATH}.entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{location}: expected a mapping")
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative:
            errors.append(f"{location}.path: required")
            continue
        if relative in result:
            errors.append(f"{location}: duplicate indexed path {relative}")
            continue
        result[relative] = entry
        try:
            path = safe_project_path(root, relative, f"{location}.path")
        except DesignPactError as exc:
            errors.append(str(exc))
            continue
        if not path.is_file():
            errors.append(f"{location}: indexed file is missing: {relative}")
            continue
        if entry.get("status") != "current":
            errors.append(f"{location}: indexed status must be current")
        if entry.get("sha256") != sha256_file(path):
            errors.append(f"{location}: indexed file hash is stale or modified")
        registered = documents.get(relative) or {}
        if entry.get("artifact_id") != registered.get("artifact_id"):
            errors.append(f"{location}: indexed artifact_id is stale")
        if entry.get("artifact_type") != registered.get("artifact_type"):
            errors.append(f"{location}: indexed artifact_type is stale")
    _generated_view_errors(
        root,
        documents,
        result,
        require_release=require_release,
        errors=errors,
    )
    return result


def _validate_test_documents(
    root: Path,
    *,
    require_release: bool,
    errors: list[str],
) -> set[str]:
    contracts_dir = root / "docs/verification/test-cases"
    contracts = sorted(contracts_dir.glob("*/test-cases.yaml"))
    slices: set[str] = set()
    known_tests: set[str] = set()
    for path in contracts:
        relative = project_relative(path, root)
        directory = path.parent.name
        if not PAGE_DIRECTORY_RE.fullmatch(directory):
            errors.append(f"{relative}: invalid page directory {directory!r}")
        try:
            contract = load_yaml(path)
        except DesignPactError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(contract, dict):
            errors.append(f"{relative}: expected a mapping")
            continue
        slice_id = contract.get("slice_id")
        if isinstance(slice_id, str):
            slices.add(slice_id)
            if not directory.startswith(f"{slice_id}-"):
                errors.append(f"{relative}: directory does not belong to {slice_id}")
        if not path.with_suffix(".md").is_file():
            errors.append(f"{relative}: test-cases.md is missing")
        tests = contract.get("tests", [])
        if not isinstance(tests, list):
            continue
        for index, test in enumerate(tests):
            if not isinstance(test, dict):
                continue
            test_id = test.get("test_id")
            if not isinstance(test_id, str):
                continue
            known_tests.add(test_id)
            planning_status = test.get("planning_status")
            implementation_path = test.get("implementation_path")
            symbol = test.get("implementation_symbol")
            if not isinstance(implementation_path, str) or not implementation_path:
                if planning_status == "active" or require_release:
                    errors.append(f"{relative}:{index}: implementation_path is required")
                continue
            try:
                test_path = safe_project_path(
                    root, implementation_path, f"{relative}.{test_id}"
                )
            except DesignPactError as exc:
                errors.append(str(exc))
                continue
            try:
                relative_test_path = test_path.relative_to(root.resolve()).as_posix()
            except ValueError:
                relative_test_path = implementation_path
            if not relative_test_path.startswith("app/src/test/"):
                errors.append(
                    f"{relative}.{test_id}: implementation_path must be a Kotlin "
                    "JVM test under app/src/test/"
                )
            if not test_path.is_file():
                if planning_status == "active" or require_release:
                    errors.append(
                        f"{relative}.{test_id}: Kotlin test file is missing"
                    )
                continue
            if not isinstance(symbol, str):
                errors.append(f"{relative}.{test_id}: implementation_symbol is required")
                continue
            try:
                declaration = extract_test_declaration(
                    test_path, str(test_id), symbol
                )
            except DesignPactError as exc:
                errors.append(str(exc))
                continue
            expected_acs = tuple(str(item) for item in test.get("ac_ids", []))
            if declaration.ac_ids != expected_acs:
                errors.append(
                    f"{relative}.{test_id}: Kotlin marker ACs disagree with YAML"
                )
    marker_owners: dict[str, list[str]] = {}
    for path in sorted((root / "app/src/test").rglob("*.kt")):
        relative = project_relative(path, root)
        try:
            text = read_text(path)
        except DesignPactError as exc:
            errors.append(str(exc))
            continue
        for match in MARKER_TEST_RE.finditer(text):
            marker_owners.setdefault(match.group(1), []).append(relative)
    for test_id in sorted(set(marker_owners) - known_tests):
        errors.append(
            f"{test_id}: Kotlin marker has no test contract at "
            f"{', '.join(marker_owners[test_id])}"
        )
    if require_release:
        for test_id, paths in sorted(marker_owners.items()):
            if len(paths) > 1:
                errors.append(
                    f"{test_id}: marker appears in multiple Kotlin files: "
                    f"{', '.join(paths)}"
                )
    return slices


def _load_spec_visual_requirements(root: Path, errors: list[str]) -> set[str]:
    required: set[str] = set()
    for path, metadata, _ in load_specs(root):
        if metadata.get("spec_level") != "L2":
            continue
        criteria = metadata.get("acceptance_criteria", [])
        if not isinstance(criteria, list):
            continue
        for index, criterion in enumerate(criteria):
            if not isinstance(criterion, dict):
                continue
            if criterion.get("visual_required") is True:
                shots = criterion.get("visual_shot_ids", [])
                if not isinstance(shots, list) or not shots:
                    errors.append(
                        f"{project_relative(path, root)}.acceptance_criteria[{index}]: "
                        "visual AC has no SHOT ID"
                    )
                    continue
                required.update(str(shot) for shot in shots)
    return required


def _validate_visual_evidence(
    root: Path,
    documents: dict[str, dict[str, Any]],
    approvals: list[dict[str, Any]],
    *,
    require_release: bool,
    errors: list[str],
) -> tuple[int, int]:
    policy = _try_load_yaml(root / VISUAL_POLICY_PATH, errors)
    if policy is None:
        policy = {}
    thresholds = policy.get("thresholds", {})
    if not isinstance(thresholds, dict):
        thresholds = {}
    approvals_by_id = {
        str(record.get("approval_id")): record
        for record in approvals
        if record.get("decision") == "approved"
    }
    if require_release:
        renderer = policy.get("renderer", {})
        device = policy.get("device", {})
        application = policy.get("application", {})
        if not isinstance(renderer, dict) or not all(
            renderer.get(key) not in (None, "") for key in ("name", "version")
        ):
            errors.append(f"{VISUAL_POLICY_PATH}: release requires renderer identity/version")
        if not isinstance(device, dict) or any(
            not isinstance(device.get(key), int) or device.get(key, 0) <= 0
            for key in ("width_px", "height_px", "density_dpi")
        ):
            errors.append(f"{VISUAL_POLICY_PATH}: release requires concrete device geometry")
        if not isinstance(application, dict):
            application = {}
        for key in ("locale", "theme", "timezone", "clock"):
            if not isinstance(application.get(key), str) or not application[key].strip():
                errors.append(f"{VISUAL_POLICY_PATH}.application.{key}: required")
        masks = policy.get("masks", [])
        if not isinstance(masks, list):
            errors.append(f"{VISUAL_POLICY_PATH}: masks must be a list")
            masks = []
        seen_masks: set[str] = set()
        for index, mask in enumerate(masks):
            if not isinstance(mask, dict):
                errors.append(f"{VISUAL_POLICY_PATH}.masks[{index}]: expected a mapping")
                continue
            mask_id = mask.get("id")
            if not isinstance(mask_id, str) or not mask_id.strip():
                errors.append(f"{VISUAL_POLICY_PATH}.masks[{index}].id: required")
            elif mask_id in seen_masks:
                errors.append(f"{VISUAL_POLICY_PATH}: duplicate mask {mask_id}")
            else:
                seen_masks.add(mask_id)
            reason = mask.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{VISUAL_POLICY_PATH}.masks[{index}].reason: required")
            approval = approvals_by_id.get(str(mask.get("approval_id")))
            if approval is None or approval.get("kind") != "exception":
                errors.append(
                    f"{VISUAL_POLICY_PATH}.masks[{index}]: mask needs an approved "
                    "exception decision"
                )
    policy_hash = sha256_file(root / VISUAL_POLICY_PATH)
    reference_records: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted((root / "docs/design/figma-references").rglob("manifest.yaml")):
        try:
            value = load_yaml(path)
        except DesignPactError:
            continue
        if isinstance(value, dict):
            reference_records[
                (str(value.get("state_id")), str(value.get("sha256")))
            ] = value

    reports: dict[tuple[str, str], dict[str, Any]] = {}
    report_manifests = sorted(
        (root / "docs/verification/visual-reports").rglob("manifest.yaml")
    )
    for path in report_manifests:
        relative = project_relative(path, root)
        value = _try_load_yaml(path, errors)
        if value is None:
            continue
        screen_id = str(value.get("screen_id"))
        state_id = str(value.get("state_id"))
        shot_id = str(value.get("shot_id"))
        reports[(state_id, shot_id)] = value
        if not path.parent.name.startswith(f"{screen_id}-"):
            errors.append(f"{relative}: directory does not belong to {screen_id}")
        for field in ("figma_reference", "current", "diff"):
            evidence = value.get(field)
            if not isinstance(evidence, dict):
                errors.append(f"{relative}.{field}: expected image evidence")
                continue
            image = _resolve_evidence_path(
                root,
                path,
                evidence.get("path"),
                f"{relative}.{field}.path",
                errors,
            )
            if image is not None:
                _check_hash(image, evidence.get("sha256"), f"{relative}.{field}", errors)
        figma_reference = value.get("figma_reference")
        if isinstance(figma_reference, dict):
            expected_hash = figma_reference.get("sha256")
            if (state_id, str(expected_hash)) not in reference_records:
                errors.append(
                    f"{relative}: Figma reference is not a registered state export"
                )
        metrics = value.get("metrics")
        review = value.get("review")
        if not isinstance(metrics, dict):
            metrics = {}
        if not isinstance(review, dict):
            review = {}
        if value.get("comparison_status") == "pass":
            checks = (
                ("figma_ssim", "figma_ssim", True),
                ("figma_pixel_difference", "figma_pixel_difference", False),
                ("baseline_ssim", "baseline_ssim", True),
                ("baseline_pixel_difference", "baseline_pixel_difference", False),
                ("key_region_geometry_dp", "key_region_geometry_dp", False),
            )
            for metric, threshold, minimum in checks:
                value_metric = metrics.get(metric)
                limit = thresholds.get(threshold)
                if not isinstance(value_metric, (int, float)) or isinstance(
                    value_metric, bool
                ):
                    errors.append(f"{relative}.metrics.{metric}: numeric value required")
                elif isinstance(limit, (int, float)) and not isinstance(limit, bool):
                    if minimum and value_metric < limit:
                        errors.append(
                            f"{relative}.metrics.{metric}: below release threshold {limit}"
                        )
                    if not minimum and value_metric > limit:
                        errors.append(
                            f"{relative}.metrics.{metric}: above release threshold {limit}"
                        )
            reviewer = review.get("reviewer")
            if not isinstance(reviewer, str) or not reviewer.strip() or PLACEHOLDER_RE.search(reviewer):
                errors.append(f"{relative}: visual review requires a named human")
            if review.get("conclusion") != "pass":
                errors.append(f"{relative}: pass comparison requires human pass review")
            reviewed_at = parse_iso8601(review.get("reviewed_at"), relative)
            if reviewed_at is None:
                errors.append(f"{relative}: visual reviewed_at must be ISO-8601")
            approval = approvals_by_id.get(str(review.get("approval_id")))
            if approval is None:
                errors.append(f"{relative}: visual review approval is missing")
            elif approval.get("kind") != "visual_baseline":
                errors.append(
                    f"{relative}: visual review requires a visual_baseline approval"
                )
            elif approval.get("decision") != "approved":
                errors.append(f"{relative}: visual review approval was not accepted")
            elif reviewed_at is not None:
                decided_at = parse_iso8601(
                    approval.get("decided_at"),
                    f"{relative}.review.approval_id",
                )
                if decided_at is None or decided_at < reviewed_at:
                    errors.append(
                        f"{relative}: visual approval must follow the review"
                    )

    baselines: dict[tuple[str, str], dict[str, Any]] = {}
    baseline_manifests = sorted(
        (root / "docs/verification/baselines").rglob("manifest.yaml")
    )
    for path in baseline_manifests:
        relative = project_relative(path, root)
        value = _try_load_yaml(path, errors)
        if value is None:
            continue
        screen_id = str(value.get("screen_id"))
        state_id = str(value.get("state_id"))
        shot_id = str(value.get("shot_id"))
        baselines[(state_id, shot_id)] = value
        if not path.parent.name.startswith(f"{screen_id}-"):
            errors.append(f"{relative}: directory does not belong to {screen_id}")
        image = _resolve_evidence_path(
            root,
            path,
            value.get("path"),
            f"{relative}.path",
            errors,
        )
        if image is not None:
            _check_hash(image, value.get("sha256"), relative, errors)
        if value.get("render_policy_sha256") != policy_hash:
            errors.append(f"{relative}: render policy hash is stale")
        approval_id = value.get("approval_id")
        approval = approvals_by_id.get(str(approval_id))
        if approval is None:
            errors.append(f"{relative}: approved visual baseline is required")
        elif approval.get("kind") != "visual_baseline":
            errors.append(f"{relative}: baseline approval kind must be visual_baseline")
        elif approval.get("subject_path") != relative:
            errors.append(f"{relative}: baseline approval subject_path is stale")

    for (state_id, shot_id), report in reports.items():
        baseline = baselines.get((state_id, shot_id))
        if baseline is None:
            if require_release:
                errors.append(f"{shot_id}: release visual report has no baseline")
            continue
        current = report.get("current")
        if not isinstance(current, dict):
            continue
        if current.get("sha256") != baseline.get("sha256"):
            errors.append(f"{shot_id}: current screenshot differs from approved baseline")

    if require_release:
        required = _load_spec_visual_requirements(root, errors)
        for shot_id in sorted(required):
            matching_reports = [
                report for (state_id, shot), report in reports.items() if shot == shot_id
            ]
            matching_baselines = [
                baseline
                for (state_id, shot), baseline in baselines.items()
                if shot == shot_id
            ]
            if not matching_reports:
                errors.append(f"{shot_id}: visual report is missing")
            if not matching_baselines:
                errors.append(f"{shot_id}: approved visual baseline is missing")
            for report in matching_reports:
                if report.get("comparison_status") != "pass":
                    errors.append(f"{shot_id}: release visual comparison must pass")
    return len(reports), len(baselines)


def _professional_approval_errors(
    root: Path,
    approvals: list[dict[str, Any]],
    release_scope: dict[str, Any],
    state: dict[str, Any],
    errors: list[str],
) -> None:
    approved = [record for record in approvals if record.get("decision") == "approved"]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for record in approved:
        by_kind.setdefault(str(record.get("kind")), []).append(record)
    for kind in (
        "scope",
        "design_contract",
        "visual_baseline",
        "exception",
        "release",
    ):
        if not by_kind.get(kind):
            errors.append(
                f"{APPROVALS_PATH}: release requires an independent approved "
                f"{kind} decision"
            )
    requirements = {
        "scope": (
            lambda record: record.get("subject_path") == RELEASE_SCOPE_PATH
            and record.get("subject_id") == str(release_scope.get("release_id"))
        ),
        "visual_baseline": lambda record: str(record.get("subject_path", "")).startswith(
            (
                "docs/verification/baselines/",
                "docs/verification/visual-reports/",
                VISUAL_POLICY_PATH,
            )
        ),
        "exception": lambda record: record.get("subject_path") == EXCEPTIONS_PATH,
        "release": lambda record: record.get("subject_path") == RELEASE_SCOPE_PATH,
    }
    for kind, predicate in requirements.items():
        records = by_kind.get(kind, [])
        if records and not any(predicate(record) for record in records):
            errors.append(
                f"{APPROVALS_PATH}: approved {kind} decision does not bind the "
                "correct current professional subject"
            )
    design_approvals = by_kind.get("design_contract", [])
    approved_design_paths = {
        str(record.get("subject_path")) for record in design_approvals
    }
    for relative in DESIGN_CONTRACT_PATHS:
        if relative not in approved_design_paths:
            errors.append(
                f"{APPROVALS_PATH}: design_contract approval is missing for "
                f"current artifact {relative}"
            )
    if state.get("state") == "released":
        release_id = state.get("release", {}).get("approval_id") if isinstance(
            state.get("release"), dict
        ) else None
        matching = [
            record
            for record in by_kind.get("release", [])
            if record.get("approval_id") == release_id
        ]
        if not matching:
            errors.append(
                f"{STATE_PATH}: released state must cite the approved release decision"
            )


def _validate_required_paths(root: Path, errors: list[str]) -> None:
    for relative in REQUIRED_DIRECTORIES:
        path = root / relative
        if not path.is_dir():
            errors.append(f"{relative}: required directory is missing")
    for relative in REQUIRED_FILES:
        path = root / relative
        if not path.is_file():
            errors.append(f"{relative}: required artifact is missing")


def _markdown_contract_paths(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    specs: list[str] = []
    for path in sorted((root / "docs/specs").rglob("*.md")):
        relative = project_relative(path, root)
        try:
            metadata, _ = split_frontmatter(read_text(path), path)
        except DesignPactError as exc:
            errors.append(str(exc))
            continue
        if metadata.get("artifact_type") != "specification":
            errors.append(f"{relative}: artifact_type must be specification")
        if metadata.get("spec_level") not in ("L1", "L2"):
            errors.append(f"{relative}: spec_level must be L1 or L2")
        specs.append(relative)
    contracts: list[str] = []
    for path in sorted((root / "docs/verification/test-cases").glob("*/test-cases.yaml")):
        try:
            metadata = load_yaml(path)
        except DesignPactError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(metadata, dict):
            errors.append(f"{path}: expected a mapping")
            continue
        if "test-cases.md" not in str(path.with_suffix(".md")):
            errors.append(f"{path}: malformed generated test view path")
        contracts.append(project_relative(path, root))
    return specs, contracts


def validate_artifacts(
    root: Path,
    *,
    require_release: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    root = root.expanduser().resolve()
    errors: list[str] = []
    checks: list[str] = []
    _validate_required_paths(root, errors)
    checks.append("required_paths")
    schemas = _validate_schema_copies(root, errors)
    checks.append("bundled_schemas")

    documents, document_map = _register_metadata_documents(root, errors)
    checks.append("artifact_metadata")
    entries = _validate_registry_completeness(root, documents, errors)
    checks.append("artifact_registry")
    _validate_yaml_schemas(root, schemas, documents, errors)
    checks.append("structured_schemas")

    try:
        approvals = (
            load_approvals(root) if (root / APPROVALS_PATH).is_file() else []
        )
    except DesignPactError as exc:
        errors.append(str(exc))
        approvals = []
    _validate_approvals_and_ledger(
        root,
        schemas,
        require_release=require_release,
        errors=errors,
    )
    checks.append("approvals_and_tdd")

    state = _try_load_yaml(root / STATE_PATH, errors) if (root / STATE_PATH).is_file() else {}
    release_scope = (
        _try_load_yaml(root / RELEASE_SCOPE_PATH, errors)
        if (root / RELEASE_SCOPE_PATH).is_file()
        else {}
    )
    if state is None:
        state = {}
    if release_scope is None:
        release_scope = {}
    _validate_with_schema(
        state,
        schemas.get("state.schema.json"),
        STATE_PATH,
        errors,
    )
    _validate_with_schema(
        release_scope,
        schemas.get("release-scope.schema.json"),
        RELEASE_SCOPE_PATH,
        errors,
    )

    figma_references = _validate_figma_references(
        root,
        document_map,
        state,
        require_release=require_release,
        errors=errors,
    )
    checks.append("figma_evidence")
    bootstrap = _validate_bootstrap(
        root,
        schemas,
        require_release=require_release,
        errors=errors,
    )
    checks.append("bootstrap_evidence")
    index_entries = _validate_artifact_index(
        root,
        schemas,
        document_map,
        require_release=require_release,
        errors=errors,
    )
    checks.append("artifact_index")
    slices = _validate_test_documents(
        root,
        require_release=require_release,
        errors=errors,
    )
    checks.append("kotlin_bindings")
    report_count, baseline_count = _validate_visual_evidence(
        root,
        document_map,
        approvals,
        require_release=require_release,
        errors=errors,
    )
    checks.append("visual_evidence")

    for relative, metadata in document_map.items():
        if metadata.get("status") != "approved":
            continue
        try:
            subject_hash = sha256_file(root / relative)
        except OSError:
            continue
        matching = [
            record
            for record in approvals
            if record.get("decision") == "approved"
            and record.get("subject_path") == relative
            and record.get("subject_sha256") == subject_hash
        ]
        if not matching:
            errors.append(
                f"{relative}: approved metadata has no current human approval record"
            )
    checks.append("authored_approval_bindings")

    if require_release:
        _professional_approval_errors(
            root,
            approvals,
            release_scope,
            state,
            errors,
        )
        if state.get("state") == "discovery":
            errors.append(f"{STATE_PATH}: release evidence cannot remain in discovery")
        if state.get("blockers"):
            errors.append(f"{STATE_PATH}: release cannot contain active blockers")
        if not slices:
            errors.append("docs/verification/test-cases: release requires a covered page")
        checks.append("release_approvals")

    spec_paths, contract_paths = _markdown_contract_paths(root)
    summary = {
        "require_release": require_release,
        "checks_completed": checks,
        "registered_entries": len(entries),
        "metadata_artifacts": len(documents),
        "artifact_index_entries": len(index_entries),
        "approvals": len(approvals),
        "figma_references": len(figma_references),
        "specifications": len(spec_paths),
        "test_contracts": len(contract_paths),
        "covered_slices": len(slices),
        "visual_reports": report_count,
        "visual_baselines": baseline_count,
        "bootstrap_conclusion": bootstrap.get("conclusion"),
        "state": state.get("state"),
    }
    return list(dict.fromkeys(errors)), summary


def main() -> int:
    args = parse_args()
    try:
        errors, summary = validate_artifacts(
            Path(args.project_root),
            require_release=args.require_release,
        )
    except (OSError, DesignPactError) as exc:
        errors, summary = [str(exc)], {}
    payload = {
        "ok": not errors,
        "conclusion": "pass" if not errors else "fail",
        "errors": errors,
        "summary": summary,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
