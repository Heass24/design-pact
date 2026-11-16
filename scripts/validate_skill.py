#!/usr/bin/env python3
"""Run an end-to-end, temporary-project regression check for Design Pact."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from bootstrap_project import CommandResult, bootstrap_project
from common import (
    canonical_json,
    load_approvals,
    load_yaml,
    read_text,
    split_frontmatter,
)
from validate_artifacts import validate_artifacts
from validate_scope import validate_scope


SKILL_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from validation_fixture import build_validation_fixture  # noqa: E402


def _check_skill_package(errors: list[str]) -> None:
    skill_path = SKILL_ROOT / "SKILL.md"
    if not skill_path.is_file():
        errors.append("SKILL.md is missing")
        return
    try:
        metadata, body = split_frontmatter(read_text(skill_path), skill_path)
    except Exception as exc:
        errors.append(str(exc))
        return
    if metadata.get("name") != "design-pact":
        errors.append("SKILL.md name must be design-pact")
    description = metadata.get("description")
    if not isinstance(description, str) or len(description.strip()) < 40:
        errors.append("SKILL.md description must explain the capability and boundary")
    if "## Scope Boundary" not in body or "## Stop Conditions" not in body:
        errors.append("SKILL.md is missing its scope or stop-condition contract")
    for relative in (
        "agents/openai.yaml",
        "LICENSE",
        "README.md",
        "references/artifact-contract.md",
        "references/spec-quality.md",
        "references/figma-contract.md",
        "references/tdd-evidence.md",
        "references/visual-verification.md",
        "references/scope-audit.md",
        "references/compose-system.md",
        "references/discovery.md",
        "references/requirement-discovery.md",
        "THIRD_PARTY_NOTICES.md",
        "scripts/preflight.py",
        "scripts/bootstrap_project.py",
        "scripts/validate_scope.py",
        "scripts/validate_artifacts.py",
        "scripts/record_tdd_evidence.py",
        "scripts/render_reports.py",
    ):
        if not (SKILL_ROOT / relative).is_file():
            errors.append(f"{relative}: required skill resource is missing")
    for relative in (
        "docs/project/state.yaml",
        "schemas/state.schema.json",
    ):
        if not (SKILL_ROOT / "assets/project-docs-template" / relative).is_file():
            errors.append(f"project template is missing {relative}")
    try:
        import yaml

        interface = yaml.safe_load(
            read_text(SKILL_ROOT / "agents/openai.yaml")
        )
    except Exception as exc:
        errors.append(f"agents/openai.yaml is invalid: {exc}")
    else:
        if not isinstance(interface, dict) or "interface" not in interface:
            errors.append("agents/openai.yaml must define interface metadata")


def _bootstrap_discovery_check(workspace: Path) -> list[str]:
    errors: list[str] = []
    root = workspace / "bootstrap-only"
    java = workspace / "tools/bin/java"
    gradle = workspace / "tools/gradle/bin/gradle"
    sdk = workspace / "tools/android-sdk"
    for path in (java, gradle):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    (sdk / "platforms/android-35").mkdir(parents=True, exist_ok=True)

    def runner(
        argv: list[str],
        cwd: Path,
        environment: dict[str, str],
        timeout: int,
    ) -> CommandResult:
        del environment, timeout
        if argv[1:2] == ["wrapper"]:
            wrapper = cwd / "gradlew"
            wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            wrapper.chmod(0o755)
        return CommandResult(0, "simulated command passed\n")

    with patch("bootstrap_project.java_major", return_value=17):
        bootstrap_errors, _ = bootstrap_project(
            target=root,
            app_name="Discovery Check",
            package_name="com.example.discovery",
            display_name="Discovery Check",
            owner="Project Owner",
            java=java,
            android_sdk=sdk,
            gradle=gradle,
            timeout=30,
            command_runner=runner,
        )
    errors.extend(bootstrap_errors)
    state = load_yaml(root / "docs/project/state.yaml")
    if not isinstance(state, dict) or state.get("state") != "discovery":
        errors.append("bootstrap did not leave the new project in discovery")
    manifest = load_yaml(root / "docs/verification/bootstrap/manifest.yaml")
    if not isinstance(manifest, dict) or manifest.get("conclusion") != "pass":
        errors.append("simulated bootstrap did not capture passing build evidence")
    return errors


def _release_errors(root: Path) -> list[str]:
    errors, _ = validate_scope(root, require_release=True)
    artifact_errors, _ = validate_artifacts(root, require_release=True)
    return errors + artifact_errors


def _assert_blocked(
    errors: list[str],
    expected: str,
    check: str,
    failures: list[str],
) -> None:
    if not any(expected in error for error in errors):
        failures.append(
            f"{check}: expected a failure containing {expected!r}; "
            f"observed {errors}"
        )


def _mutate_and_restore(
    path: Path,
    replacement: bytes,
    *,
    expected: str,
    check: str,
    root: Path,
    failures: list[str],
) -> None:
    original = path.read_bytes()
    try:
        path.write_bytes(replacement)
        errors = _release_errors(root)
        _assert_blocked(errors, expected, check, failures)
    finally:
        path.write_bytes(original)


def _full_project_checks(root: Path, workspace: Path) -> list[str]:
    failures: list[str] = []
    errors = _release_errors(root)
    if errors:
        failures.append(f"complete fixture did not pass release: {errors}")

    approvals_path = root / "docs/project/approvals.jsonl"
    original_approvals = approvals_path.read_bytes()
    approvals = load_approvals(root)
    try:
        for kind in (
            "scope",
            "design_contract",
            "visual_baseline",
            "exception",
            "release",
        ):
            filtered = [
                record for record in approvals if record.get("kind") != kind
            ]
            approvals_path.write_text(
                "".join(canonical_json(record) + "\n" for record in filtered),
                encoding="utf-8",
            )
            errors = _release_errors(root)
            _assert_blocked(
                errors,
                f"approved {kind} decision",
                f"missing {kind} approval",
                failures,
            )
    finally:
        approvals_path.write_bytes(original_approvals)

    visual_report = (
        root / "docs/verification/visual-reports/SCREEN-001-home/manifest.yaml"
    )
    visual_text = visual_report.read_text(encoding="utf-8")
    _mutate_and_restore(
        visual_report,
        visual_text.replace(
            "comparison_status: pass",
            "comparison_status: unverified",
        ).encode("utf-8"),
        expected="release visual comparison must pass",
        check="unverified visual evidence",
        root=root,
        failures=failures,
    )

    generated_view = (
        root / "docs/verification/test-cases/SCREEN-001-home/test-cases.md"
    )
    _mutate_and_restore(
        generated_view,
        generated_view.read_bytes() + b"\nManual edit.\n",
        expected="hash is stale or modified",
        check="manual generated-view edit",
        root=root,
        failures=failures,
    )

    release_scope = root / "docs/product/release-scope.yaml"
    _mutate_and_restore(
        release_scope,
        release_scope.read_bytes() + b"\n# changed after approval\n",
        expected="approval is stale",
        check="stale approval after source change",
        root=root,
        failures=failures,
    )

    ledger = root / "docs/verification/tdd-ledger.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    _mutate_and_restore(
        ledger,
        ("\n".join(lines[1:]) + "\n").encode("utf-8"),
        expected="latest TDD cycle is not valid",
        check="missing Red evidence",
        root=root,
        failures=failures,
    )

    current = (
        root
        / "docs/verification/visual-reports/SCREEN-001-home/current/STATE-001.png"
    )
    _mutate_and_restore(
        current,
        b"not the approved current screenshot",
        expected="declared hash does not match",
        check="unverified current screenshot",
        root=root,
        failures=failures,
    )

    restored_errors = _release_errors(root)
    if restored_errors:
        failures.append(
            f"restoring the original evidence did not restore release readiness: "
            f"{restored_errors}"
        )

    if not (workspace / "bootstrap-only/docs/project/state.yaml").is_file():
        failures.append("bootstrap discovery check did not create its project")
    return failures


def validate_skill() -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    _check_skill_package(errors)
    temporary = tempfile.TemporaryDirectory()
    workspace = Path(temporary.name).resolve()
    try:
        errors.extend(_bootstrap_discovery_check(workspace))
        try:
            root = build_validation_fixture(workspace)
        except Exception as exc:
            errors.append(f"could not build the end-to-end fixture: {exc}")
            root = workspace / "project"
        else:
            errors.extend(_full_project_checks(root, workspace))
        summary = {
            "skill_root": str(SKILL_ROOT),
            "simulated_environment": True,
            "complete_release_fixture": not errors,
            "approval_isolation": "checked",
            "missing_evidence_blocking": "checked",
            "generated_view_tamper_detection": "checked",
            "bootstrap_discovery": "checked",
            "limitations": [
                "Simulation does not call a live Figma integration.",
                "Simulation does not replace an emulator or real device.",
                "Simulation cannot provide human visual approval.",
                "A passing self-check does not prove a real application matches Figma.",
            ],
        }
        return errors, summary
    finally:
        temporary.cleanup()


def main() -> int:
    try:
        errors, summary = validate_skill()
    except Exception as exc:
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
