#!/usr/bin/env python3
"""Render deterministic, inspectable Design Pact human views."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common import (
    DesignPactError,
    allocate_artifact_entry,
    approved_tdd_event_hashes,
    artifact_registry_errors,
    assess_tdd_test,
    compose_markdown,
    dump_yaml,
    emit_result,
    hash_sources,
    load_artifact_registry,
    load_jsonl,
    load_specs,
    load_yaml,
    parse_iso8601,
    project_relative,
    read_text,
    rejected_tdd_event_hashes,
    retire_artifact_entry,
    safe_project_path,
    sha256_bytes,
    split_frontmatter,
    validate_metadata,
    validate_schema,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEST_CONTRACT_SCHEMA = (
    SKILL_ROOT
    / "assets"
    / "project-docs-template"
    / "schemas"
    / "test-case-contract.schema.json"
)
TEST_CASES_RELATIVE = "docs/verification/test-cases"
APPROVALS_RELATIVE = "docs/project/approvals.jsonl"
TDD_LEDGER_RELATIVE = "docs/verification/tdd-ledger.jsonl"
ARTIFACT_INDEX_RELATIVE = "docs/project/artifact-index.yaml"
README_RELATIVE = "docs/README.md"
TDD_REPORT_RELATIVE = "docs/verification/tdd-report.md"
TEST_INDEX_RELATIVE = "docs/verification/test-cases/index.md"

RESULT_CATEGORIES = (
    "passing",
    "failing",
    "blocked",
    "unverified",
    "planned",
    "deferred",
    "out_of_scope",
)
PAGE_DIRECTORY_RE = re.compile(
    r"^(SCREEN|FLOW)-(?!000)[0-9]{3}-[a-z0-9]+(?:-[a-z0-9]+)*$"
)
PAGE_REPORT_RE = re.compile(
    r"^docs/verification/test-cases/"
    r"(?:SCREEN|FLOW)-(?!000)[0-9]{3}-[a-z0-9]+(?:-[a-z0-9]+)*/"
    r"test-cases\.md$"
)


@dataclass(frozen=True)
class ContractView:
    contract: dict[str, Any]
    contract_path: str
    spec_path: str
    report_directory: str
    report_path: str
    slice_id: str
    slice_type: str
    slug: str
    spec_id: str


@dataclass(frozen=True)
class ReportOutput:
    artifact_id: str
    artifact_type: str
    content: bytes
    source_ids: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, help="Design Pact project.")
    parser.add_argument(
        "--generated-at",
        help="Override generation time with a timezone-aware ISO-8601 timestamp.",
    )
    return parser.parse_args()


def _load_contract_schema() -> dict[str, Any]:
    try:
        value = json.loads(read_text(TEST_CONTRACT_SCHEMA))
    except json.JSONDecodeError as exc:
        raise DesignPactError(
            f"{TEST_CONTRACT_SCHEMA}: invalid bundled schema: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise DesignPactError(f"{TEST_CONTRACT_SCHEMA}: schema must be an object")
    return value


def _invalid(errors: list[str], location: str) -> None:
    if errors:
        raise DesignPactError("; ".join(f"{location}: {error}" for error in errors))


def _spec_index(
    root: Path,
) -> tuple[dict[str, tuple[Path, dict[str, Any]]], list[str]]:
    specs: dict[str, tuple[Path, dict[str, Any]]] = {}
    source_paths: list[str] = []
    errors: list[str] = []
    for path, metadata, _ in load_specs(root):
        if "generator" in metadata:
            continue
        location = project_relative(path, root)
        source_paths.append(location)
        spec_id = metadata.get("spec_id")
        if not isinstance(spec_id, str) or not spec_id:
            errors.append(f"{location}: missing spec_id")
            continue
        if spec_id in specs:
            errors.append(f"{location}: duplicate spec_id {spec_id}")
            continue
        specs[spec_id] = (path, metadata)
    return specs, sorted(set(source_paths))


def _discover_contracts(root: Path) -> tuple[list[ContractView], list[str]]:
    base = root / TEST_CASES_RELATIVE
    if not base.is_dir():
        raise DesignPactError(f"{base}: test-case directory is missing")
    schema = _load_contract_schema()
    specs, _ = _spec_index(root)
    contracts: list[ContractView] = []
    errors: list[str] = []
    seen_test_ids: dict[str, str] = {}
    for path in sorted(base.rglob("test-cases.yaml")):
        relative = project_relative(path, root)
        try:
            safe_path = safe_project_path(root, relative, relative)
        except DesignPactError as exc:
            errors.append(str(exc))
            continue
        if safe_path != path.resolve():
            errors.append(f"{relative}: contract path must not resolve through a symlink")
            continue
        try:
            directory_relative = path.parent.relative_to(base)
        except ValueError:
            errors.append(f"{relative}: contract is outside the test-case directory")
            continue
        if len(directory_relative.parts) != 1:
            errors.append(
                f"{relative}: contract must be directly inside one page directory"
            )
            continue
        directory = directory_relative.parts[0]
        if not PAGE_DIRECTORY_RE.fullmatch(directory):
            errors.append(
                f"{relative}: page directory must be "
                "SCREEN-###-slug or FLOW-###-slug with a lowercase slug"
            )
            continue
        try:
            contract = load_yaml(path)
        except DesignPactError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(contract, dict):
            errors.append(f"{relative}: contract must be a mapping")
            continue
        schema_errors = validate_schema(contract, schema, relative)
        metadata_errors = validate_metadata(contract, relative)
        if schema_errors or metadata_errors:
            errors.extend(schema_errors + metadata_errors)
            continue
        slice_id = contract.get("slice_id")
        slice_type = contract.get("slice_type")
        spec_id = contract.get("spec_id")
        if not isinstance(slice_id, str) or not isinstance(slice_type, str):
            errors.append(f"{relative}: slice_id and slice_type must be strings")
            continue
        expected_prefix = "SCREEN" if slice_type == "screen" else "FLOW"
        if not slice_id.startswith(f"{expected_prefix}-"):
            errors.append(
                f"{relative}: slice_type {slice_type!r} does not match {slice_id}"
            )
        expected_directory_prefix = f"{slice_id}-"
        if not directory.startswith(expected_directory_prefix):
            errors.append(
                f"{relative}: directory {directory!r} does not belong to {slice_id}"
            )
            continue
        slug = directory[len(expected_directory_prefix) :]
        if not slug:
            errors.append(f"{relative}: page slug must not be empty")
            continue
        if not isinstance(spec_id, str) or spec_id not in specs:
            errors.append(f"{relative}: referenced spec {spec_id!r} does not exist")
            continue
        spec_path, spec = specs[spec_id]
        if spec.get("spec_level") != "L2":
            errors.append(f"{relative}: {spec_id} is not an L2 specification")
        source_ids = contract.get("source_ids", [])
        if spec_id not in source_ids:
            errors.append(f"{relative}: source_ids must contain {spec_id}")
        tests = contract.get("tests", [])
        if not isinstance(tests, list):
            errors.append(f"{relative}: tests must be a list")
            continue
        for index, test in enumerate(tests):
            if not isinstance(test, dict):
                continue
            test_id = test.get("test_id")
            if not isinstance(test_id, str):
                continue
            if test_id in seen_test_ids:
                errors.append(
                    f"duplicate {test_id} in {relative}:{index} and "
                    f"{seen_test_ids[test_id]}"
                )
            else:
                seen_test_ids[test_id] = f"{relative}:{index}"
        contracts.append(
            ContractView(
                contract=contract,
                contract_path=relative,
                spec_path=project_relative(spec_path, root),
                report_directory=directory,
                report_path=f"{TEST_CASES_RELATIVE}/{directory}/test-cases.md",
                slice_id=slice_id,
                slice_type=slice_type,
                slug=slug,
                spec_id=spec_id,
            )
        )
    contracts.sort(key=lambda item: item.report_path)
    return contracts, errors


def _canonical_paths(
    contracts: list[ContractView],
    spec_paths: list[str],
) -> list[str]:
    paths = {contract.contract_path for contract in contracts}
    paths.update(spec_paths)
    paths.update((APPROVALS_RELATIVE, TDD_LEDGER_RELATIVE))
    return sorted(paths)


def _page_source_paths(contract: ContractView) -> list[str]:
    return sorted(
        {
            contract.contract_path,
            contract.spec_path,
            APPROVALS_RELATIVE,
            TDD_LEDGER_RELATIVE,
        }
    )


def _metadata(
    *,
    artifact_id: str,
    artifact_type: str,
    created_at_state: str,
    source_ids: list[str],
    source_paths: list[str],
    source_sha256: str,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "schema_version": "1.0",
        "version": 1,
        "owner": "render_reports.py",
        "created_at_state": created_at_state,
        "status": "draft",
        "source_ids": source_ids,
        "upstream_sha256": "",
        "approval_required": False,
        "generator": "render_reports.py",
        "generated_from": source_paths,
        "source_sha256": source_sha256,
        "generated_at": generated_at,
    }


def _escape(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _list_or_none(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return "none"
    return ", ".join(str(value) for value in values)


def _classification(
    test: dict[str, Any],
    assessment_status: str,
) -> str:
    planning_status = test.get("planning_status")
    if planning_status in ("blocked", "deferred", "out_of_scope"):
        return str(planning_status)
    if planning_status == "planned":
        return "planned"
    if planning_status != "active":
        return "blocked"
    if assessment_status == "pass":
        return "passing"
    if assessment_status == "failed":
        return "failing"
    return "unverified"


def _category_counts(tests: list[dict[str, Any]]) -> dict[str, int]:
    counts = {category: 0 for category in RESULT_CATEGORIES}
    for test in tests:
        category = str(test["_category"])
        counts[category] += 1
    return counts


def _category_table(tests: list[dict[str, Any]]) -> str:
    counts = _category_counts(tests)
    lines = [
        "| Result category | Count | Meaning |",
        "| --- | ---: | --- |",
        f"| passing | {counts['passing']} | Accepted Red/Green/Refactor/Verify cycle |",
        f"| failing | {counts['failing']} | Cycles exist but are invalid or incomplete |",
        f"| blocked | {counts['blocked']} | A named gap or dependency stops execution |",
        f"| unverified | {counts['unverified']} | Active behavior has no accepted TDD cycle |",
        f"| planned | {counts['planned']} | Intent exists; execution has not started |",
        f"| deferred | {counts['deferred']} | Explicitly postponed with a reason |",
        f"| out_of_scope | {counts['out_of_scope']} | Excluded by approved scope |",
    ]
    return "\n".join(lines)


def _phase_status(test: dict[str, Any], phase: str) -> str:
    cycle = test.get("_cycle", [])
    events = [event for event in cycle if event.get("phase") == phase]
    if not events:
        return "not captured"
    event = events[0]
    kind = event.get("failure_kind")
    suffix = f" ({kind})" if phase == "red" and kind else ""
    return f"captured: {event.get('event_id')}{suffix}"


def _test_table(tests: list[dict[str, Any]]) -> str:
    lines = [
        "| Test | Result | Title | Type | Priority | AC / State | Precondition | "
        "Data | Action | Expected |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for test in tests:
        ac_state = (
            f"{_list_or_none(test.get('ac_ids'))} / "
            f"{_list_or_none(test.get('state_ids'))}"
        )
        lines.append(
            "| "
            + " | ".join(
                _escape(value)
                for value in (
                    test.get("test_id"),
                    test.get("_category"),
                    test.get("title"),
                    test.get("test_type"),
                    test.get("priority"),
                    ac_state,
                    test.get("precondition"),
                    _list_or_none(test.get("test_data")),
                    test.get("action"),
                    test.get("expected"),
                )
            )
            + " |"
        )
    return "\n".join(lines)


def _phase_table(test: dict[str, Any]) -> str:
    return "\n".join(
        (
            "| Phase | Evidence |",
            "| --- | --- |",
            f"| Red | {_phase_status(test, 'red')} |",
            f"| Green | {_phase_status(test, 'green')} |",
            f"| Refactor | {_phase_status(test, 'refactor')} |",
            f"| Verify | {_phase_status(test, 'verify')} |",
        )
    )


def _reasons_section(tests: list[dict[str, Any]]) -> str:
    relevant = [
        test
        for test in tests
        if test.get("_category") in ("blocked", "deferred", "out_of_scope")
    ]
    if not relevant:
        return "No blocked, deferred, or out-of-scope tests."
    return "\n".join(
        f"- `{test.get('test_id')}` ({test.get('_category')}): "
        f"{test.get('planning_reason', 'missing planning_reason')}"
        for test in relevant
    )


def _page_body(
    contract: ContractView,
    tests: list[dict[str, Any]],
    generated_at: str,
) -> str:
    uncovered = [
        test.get("test_id")
        for test in tests
        if test.get("_category") != "passing"
    ]
    state_ids: list[str] = []
    ac_ids: list[str] = []
    for test in tests:
        state_ids.extend(str(value) for value in test.get("state_ids", []))
        ac_ids.extend(str(value) for value in test.get("ac_ids", []))
    page_label = (
        "Screen"
        if contract.slice_type == "screen"
        else "Flow"
    )
    lines = [
        f"# {page_label} {contract.slice_id}: {contract.slug.replace('-', ' ').title()}",
        "",
        "> Generated human view. Edit the YAML contract or L2 specification, "
        "then regenerate. Do not edit this file.",
        "",
        "## Contract Summary",
        "",
        f"- Contract: `{contract.contract_path}`",
        f"- Specification: `{contract.spec_id}` at `{contract.spec_path}`",
        f"- Slice: `{contract.slice_id}` ({contract.slice_type})",
        f"- Generation time: `{generated_at}`",
        f"- Covered states: {_list_or_none(sorted(set(state_ids)))}",
        f"- Acceptance criteria: {_list_or_none(sorted(set(ac_ids)))}",
        f"- Gate conclusion: `{'unverified' if uncovered else 'passing'}`",
        "",
        "## Result Summary",
        "",
        _category_table(tests),
        "",
        "The seven categories are always listed so unresolved work cannot be "
        "hidden behind a single total.",
        "",
        "## Test Cases",
        "",
        _test_table(tests) if tests else "No tests are defined.",
        "",
        "## TDD Evidence",
        "",
    ]
    if not tests:
        lines.append("No Red, Green, Refactor, or Verify cycle exists.")
    for test in tests:
        lines.extend(
            (
                f"### {test.get('test_id')}: {test.get('title')}",
                "",
                f"- Classification: `{test.get('_category')}`",
                f"- Assessment: {test.get('_assessment') or 'no accepted cycle'}",
                f"- Kotlin path: `{test.get('implementation_path', 'missing')}`",
                f"- Kotlin symbol: `{test.get('implementation_symbol', 'missing')}`",
                f"- Accessibility assertions: "
                f"{_list_or_none(test.get('accessibility_assertions'))}",
                "",
                _phase_table(test),
                "",
            )
        )
    lines.extend(
        (
            "## Visual Evidence",
            "",
        )
    )
    visual_ids: list[str] = []
    for test in tests:
        visual_ids.extend(str(value) for value in test.get("visual_shot_ids", []))
    lines.append(
        f"- Required shots: {_list_or_none(sorted(set(visual_ids)))}"
    )
    lines.append(
        "- Evidence state: `unverified` until visual report and baseline "
        "manifests link the current screenshot."
    )
    lines.extend(
        (
            "",
            "## Deferred and Excluded",
            "",
            _reasons_section(tests),
            "",
            "## Human review",
            "",
            "- [ ] Every product-visible state is represented by an approved AC.",
            "- [ ] Test preconditions, actions, and expected results are deterministic.",
            "- [ ] Kotlin marker, path, symbol, ACs, and ledger agree.",
            "- [ ] Red failed for behavior, not compilation or environment setup.",
            "- [ ] Green, Refactor, and Verify retain the same test declaration.",
            "- [ ] Visual screenshots and accessibility evidence are current.",
            "- [ ] Every blocked, deferred, or excluded item has a human-approved reason.",
            "",
            "## Sources and Regeneration",
            "",
        )
    )
    for source in _page_source_paths(contract):
        lines.append(f"- `{source}`")
    lines.extend(
        (
            "",
            "Regenerate this page without editing it directly:",
            "",
            "```bash",
            "python3 scripts/render_reports.py --project-root <project>",
            "```",
            "",
        )
    )
    return "\n".join(lines)


def _index_body(contracts: list[ContractView], tests: list[dict[str, Any]]) -> str:
    lines = [
        "# Test Cases",
        "",
        "> Generated project navigator. Canonical intent remains in each "
        "`test-cases.yaml`; executable behavior remains in Kotlin.",
        "",
        "## Pages",
        "",
        "| Page | Contract | Tests |",
        "| --- | --- | ---: |",
    ]
    for contract in contracts:
        page_tests = contract.contract.get("tests", [])
        lines.append(
            f"| [{contract.slice_id}]({contract.report_directory}/test-cases.md) "
            f"| `{contract.contract_path}` | {len(page_tests)} |"
        )
    lines.extend(
        (
            "",
            "## Project Result Summary",
            "",
            _category_table(tests),
            "",
            "### Unresolved Work",
            "",
        )
    )
    # A single explicit list makes unresolved work visible without opening each page.
    unresolved = [
        test for test in tests if test.get("_category") != "passing"
    ]
    if unresolved:
        for test in unresolved:
            lines.append(
                f"- `{test.get('test_id')}` ({test.get('_category')}): "
                f"{test.get('title')} at `{test.get('_report_path')}`"
                + (
                    f" — {test.get('planning_reason')}"
                    if test.get("planning_reason")
                    else ""
                )
            )
    else:
        lines.append("No unresolved tests.")
    lines.extend(
        (
            "",
            "## Human Review",
            "",
            "- [ ] Every page appears exactly once.",
            "- [ ] Passing means a complete accepted Red/Green/Refactor/Verify cycle.",
            "- [ ] All blocked, deferred, and out-of-scope reasons are approved.",
            "",
            "## Regeneration",
            "",
            "```bash",
            "python3 scripts/render_reports.py --project-root <project>",
            "```",
            "",
        )
    )
    return "\n".join(lines)


def _tdd_report_body(
    contracts: list[ContractView],
    tests: list[dict[str, Any]],
    generated_at: str,
) -> str:
    lines = [
        "# TDD Evidence Report",
        "",
        f"Generated at `{generated_at}` from canonical contracts, approvals, "
        "and the append-only ledger.",
        "",
        "## Result Categories",
        "",
        _category_table(tests),
        "",
        "## Cycle Matrix",
        "",
        "| Page | Test | Result | Red | Green | Refactor | Verify | Assessment |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for test in tests:
        lines.append(
            "| "
            + " | ".join(
                _escape(value)
                for value in (
                    test.get("_slice_id"),
                    test.get("test_id"),
                    test.get("_category"),
                    _phase_status(test, "red"),
                    _phase_status(test, "green"),
                    _phase_status(test, "refactor"),
                    _phase_status(test, "verify"),
                    test.get("_assessment") or "no accepted cycle",
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            "## Evidence Details",
            "",
        )
    )
    for test in tests:
        lines.extend(
            (
                f"### {test.get('test_id')}: {test.get('title')}",
                "",
                f"- Page: `{test.get('_slice_id')}`",
                f"- Contract: `{test.get('_contract_path')}`",
                f"- Expected behavior: {test.get('expected')}",
                f"- Kotlin: `{test.get('implementation_path', 'missing')}` "
                f"`{test.get('implementation_symbol', 'missing')}`",
                "",
            )
        )
        cycle = test.get("_cycle", [])
        if cycle:
            lines.extend(
                (
                    "| Event | Phase | Exit | Failure kind | Command | Artifact |",
                    "| --- | --- | ---: | --- | --- | --- |",
                )
            )
            for event in cycle:
                lines.append(
                    "| "
                    + " | ".join(
                        _escape(value)
                        for value in (
                            event.get("event_id"),
                            event.get("phase"),
                            event.get("exit_code"),
                            event.get("failure_kind") or "none",
                            " ".join(str(part) for part in event.get("command", [])),
                            event.get("artifact_path"),
                        )
                    )
                    + " |"
                )
        else:
            lines.append("No independently accepted TDD event is recorded.")
        lines.append("")
    lines.extend(
        (
            "## Human Review",
            "",
            "- [ ] Red is behavior-level and precedes Green in each accepted cycle.",
            "- [ ] Every phase references the same declaration, contract, and implementation.",
            "- [ ] Refactor and Verify preserve the test behavior.",
            "- [ ] No rejected event remains in a passing cycle.",
            "",
            "## Regeneration",
            "",
            "```bash",
            "python3 scripts/render_reports.py --project-root <project>",
            "```",
            "",
        )
    )
    return "\n".join(lines)


def _readme_body(
    contracts: list[ContractView],
    tests: list[dict[str, Any]],
    generated_at: str,
) -> str:
    lines = [
        "# Design Pact Documentation",
        "",
        f"Generated at `{generated_at}`. This page is navigation, not an "
        "editable authority.",
        "",
        "## Project Views",
        "",
        "- [Project state](project/state.yaml)",
        "- [Artifact index](project/artifact-index.yaml)",
        "- [Test-case navigator](verification/test-cases/index.md)",
        "- [TDD evidence report](verification/tdd-report.md)",
        "- [Scope audit](verification/scope-audit.md)",
        "",
        "## Contract Sources",
        "",
        "| Page | Specification | Test contract | Human view |",
        "| --- | --- | --- | --- |",
    ]
    for contract in contracts:
        lines.append(
            f"| {contract.slice_id} | `{contract.spec_path}` | "
            f"`{contract.contract_path}` | "
            f"[test-cases.md](verification/test-cases/"
            f"{contract.report_directory}/test-cases.md) |"
        )
    lines.extend(
        (
            "",
            "## Result Categories",
            "",
            _category_table(tests),
            "",
            "## Human Intervention",
            "",
            "Edit the canonical YAML/Markdown source, never a generated view. "
            "For scope or design changes, record `DEC-###` and an independent "
            "human approval first.",
            "",
            "## Regeneration",
            "",
            "```bash",
            "python3 scripts/render_reports.py --project-root <project>",
            "```",
            "",
        )
    )
    return "\n".join(lines)


def _stale_page_paths(
    registry: dict[str, Any],
    expected_paths: set[str],
) -> list[str]:
    stale: list[str] = []
    for entry in registry.get("entries", []):
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if (
            isinstance(path, str)
            and PAGE_REPORT_RE.fullmatch(path)
            and path not in expected_paths
            and entry.get("lifecycle", "active") == "active"
        ):
            stale.append(path)
    return sorted(stale)


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def render_reports(
    root: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Validate all canonical sources, then rebuild every generated report."""

    root = root.expanduser().resolve()
    if not root.is_dir():
        raise DesignPactError(f"{root}: project root is not a directory")
    generated_at = generated_at or __import__("common").now_iso()
    if parse_iso8601(generated_at, "generated_at") is None:
        raise DesignPactError("generated_at must be timezone-aware ISO-8601")

    registry_errors = artifact_registry_errors(root)
    if registry_errors:
        raise DesignPactError("; ".join(registry_errors))
    registry = load_artifact_registry(root)
    initial_registry = dump_yaml(registry)

    contracts, contract_errors = _discover_contracts(root)
    if contract_errors:
        raise DesignPactError("; ".join(contract_errors))
    _specs, spec_paths = _spec_index(root)
    canonical_paths = _canonical_paths(contracts, spec_paths)

    try:
        ledger_events = load_jsonl(root / TDD_LEDGER_RELATIVE)
        load_jsonl(root / APPROVALS_RELATIVE)
    except DesignPactError:
        raise
    event_approvals = approved_tdd_event_hashes(root)
    rejected_approvals = rejected_tdd_event_hashes(root)
    events_by_test: dict[str, list[dict[str, Any]]] = {}
    for event in ledger_events:
        test_id = event.get("test_id")
        if isinstance(test_id, str):
            events_by_test.setdefault(test_id, []).append(event)

    tests: list[dict[str, Any]] = []
    tests_by_contract_path: dict[str, list[dict[str, Any]]] = {}
    for contract in contracts:
        contract_tests = contract.contract.get("tests", [])
        page_tests = tests_by_contract_path.setdefault(contract.contract_path, [])
        for source_test in contract_tests:
            test = dict(source_test)
            test_id = str(test.get("test_id"))
            assessment = assess_tdd_test(
                events_by_test.get(test_id, []),
                event_approvals,
                test_id,
                rejected_approvals,
            )
            test["_assessment"] = (
                "; ".join(assessment.errors)
                if assessment.errors
                else assessment.status
            )
            test["_cycle"] = list(assessment.cycle)
            test["_category"] = _classification(test, assessment.status)
            test["_slice_id"] = contract.slice_id
            test["_contract_path"] = contract.contract_path
            test["_spec_path"] = contract.spec_path
            test["_report_path"] = contract.report_path
            tests.append(test)
            page_tests.append(test)
    tests.sort(key=lambda item: (str(item["test_id"]), str(item["_slice_id"])))

    outputs: dict[str, ReportOutput] = {}
    fixed_artifacts = (
        (
            README_RELATIVE,
            "documentation_navigation",
            "ART-100",
            "discovery",
            [],
        ),
        (
            TDD_REPORT_RELATIVE,
            "tdd_report",
            "ART-032",
            "implementation",
            [contract.spec_id for contract in contracts],
        ),
        (
            TEST_INDEX_RELATIVE,
            "test_case_index",
            "ART-600",
            "verification",
            [contract.spec_id for contract in contracts],
        ),
    )
    allocated: dict[str, tuple[str, str, str, list[str]]] = {}
    for relative, artifact_type, preferred_id, state, source_ids in fixed_artifacts:
        artifact_id = allocate_artifact_entry(
            registry,
            key=relative,
            path=relative,
            artifact_type=artifact_type,
            preferred_id=preferred_id,
        )
        allocated[relative] = (
            artifact_id,
            artifact_type,
            state,
            source_ids,
        )
    for contract in contracts:
        artifact_id = allocate_artifact_entry(
            registry,
            key=contract.report_path,
            path=contract.report_path,
            artifact_type="test_case_report",
        )
        allocated[contract.report_path] = (
            artifact_id,
            "test_case_report",
            "verification",
            [contract.spec_id, contract.slice_id],
        )

    expected_page_paths = {contract.report_path for contract in contracts}
    stale_paths = _stale_page_paths(registry, expected_page_paths)
    for stale_path in stale_paths:
        retire_artifact_entry(
            registry,
            key=stale_path,
            removed_at=generated_at,
            reason="canonical test-case contract no longer exists",
        )

    for contract in contracts:
        source_paths = _page_source_paths(contract)
        source_hash = hash_sources(root, source_paths)
        artifact_id, artifact_type, state, source_ids = allocated[
            contract.report_path
        ]
        metadata = _metadata(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            created_at_state=state,
            source_ids=source_ids,
            source_paths=source_paths,
            source_sha256=source_hash,
            generated_at=generated_at,
        )
        content = compose_markdown(
            metadata,
            _page_body(
                contract,
                tests_by_contract_path.get(contract.contract_path, []),
                generated_at,
            ),
        ).encode("utf-8")
        outputs[contract.report_path] = ReportOutput(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            content=content,
            source_ids=tuple(source_ids),
        )

    global_source_hash = hash_sources(root, canonical_paths)
    global_bodies = {
        README_RELATIVE: _readme_body(contracts, tests, generated_at),
        TDD_REPORT_RELATIVE: _tdd_report_body(contracts, tests, generated_at),
        TEST_INDEX_RELATIVE: _index_body(contracts, tests),
    }
    for relative, body in global_bodies.items():
        artifact_id, artifact_type, state, source_ids = allocated[relative]
        metadata = _metadata(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            created_at_state=state,
            source_ids=source_ids,
            source_paths=canonical_paths,
            source_sha256=global_source_hash,
            generated_at=generated_at,
        )
        outputs[relative] = ReportOutput(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            content=compose_markdown(metadata, body).encode("utf-8"),
            source_ids=tuple(source_ids),
        )

    index_entries: list[dict[str, Any]] = []
    registry_by_path = {
        str(entry.get("path")): entry
        for entry in registry.get("entries", [])
        if isinstance(entry, dict)
    }
    for relative in sorted(outputs):
        output = outputs[relative]
        entry = registry_by_path.get(relative, {})
        index_entries.append(
            {
                "path": relative,
                "format": Path(relative).suffix.lstrip("."),
                "sha256": sha256_bytes(output.content),
                "status": "current",
                "authority": "generated human view",
                "validator": "python3 scripts/validate_artifacts.py",
                "human_view": "yes",
                "approval_required": False,
                "artifact_id": output.artifact_id,
                "artifact_type": output.artifact_type,
                "lifecycle": entry.get("lifecycle", "active"),
            }
        )
    index_metadata = _metadata(
        artifact_id="ART-002",
        artifact_type="artifact_index",
        created_at_state="verification",
        source_ids=[],
        source_paths=canonical_paths,
        source_sha256=global_source_hash,
        generated_at=generated_at,
    )
    index_metadata["result_categories"] = list(RESULT_CATEGORIES)
    artifact_index = dict(index_metadata)
    artifact_index["entries"] = index_entries

    registry_errors = artifact_registry_errors(root)
    if registry_errors:
        raise DesignPactError("; ".join(registry_errors))

    for relative, output in sorted(outputs.items()):
        _write_atomic(root / relative, output.content)
    _write_atomic(
        root / ARTIFACT_INDEX_RELATIVE,
        dump_yaml(artifact_index).encode("utf-8"),
    )
    for stale_path in stale_paths:
        (root / stale_path).unlink(missing_ok=True)

    if dump_yaml(registry) != initial_registry:
        version = registry.get("version", 1)
        registry["version"] = version + 1 if isinstance(version, int) else 1
    _write_atomic(
        root / "docs" / "project" / "artifact-ids.yaml",
        dump_yaml(registry).encode("utf-8"),
    )
    return {
        "generated_at": generated_at,
        "generated_files": sorted(
            [*outputs, ARTIFACT_INDEX_RELATIVE]
        ),
        "test_count": len(tests),
        "page_count": len(contracts),
        "result_categories": list(RESULT_CATEGORIES),
    }


def main() -> int:
    args = parse_args()
    try:
        summary = render_reports(
            Path(args.project_root),
            generated_at=args.generated_at,
        )
    except DesignPactError as exc:
        return emit_result([str(exc)])
    return emit_result([], summary=summary)


if __name__ == "__main__":
    raise SystemExit(main())
