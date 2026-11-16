from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

from bootstrap_project import CommandResult, bootstrap_project, register_document_artifacts
from common import (
    append_jsonl,
    compose_markdown,
    dump_yaml,
    event_hash,
    extract_test_declaration,
    load_yaml,
    sha256_file,
)
from render_reports import render_reports


GENERATED_AT = "2026-11-16T08:30:00+00:00"
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)
TEST_PATH = "app/src/test/java/com/example/pact/HomeScreenTest.kt"
IMPLEMENTATION_PATH = "app/src/main/java/com/example/pact/HomeScreen.kt"
CONTRACT_PATH = (
    "docs/verification/test-cases/SCREEN-001-home/test-cases.yaml"
)
SPEC_L1_PATH = "docs/specs/L1/SPEC-001-JRN-001-onboarding.md"
SPEC_L2_PATH = "docs/specs/L2/SPEC-002-SCREEN-001-home.md"
FIGMA_MANIFEST_PATH = (
    "docs/design/figma-references/SCREEN-001-home/manifest.yaml"
)
VISUAL_REPORT_PATH = (
    "docs/verification/visual-reports/SCREEN-001-home/manifest.yaml"
)
BASELINE_PATH = "docs/verification/baselines/SCREEN-001-home/manifest.yaml"


def write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(value), encoding="utf-8")


def write_markdown(path: Path, metadata: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(compose_markdown(metadata, body), encoding="utf-8")


def metadata(
    artifact_id: str,
    artifact_type: str,
    state: str,
    *,
    source_ids: list[str] | None = None,
    status: str = "draft",
    approval_required: bool = True,
) -> dict:
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "schema_version": "1.0",
        "version": 1,
        "owner": "Design Pact Fixture",
        "created_at_state": state,
        "status": status,
        "source_ids": source_ids or [],
        "upstream_sha256": "",
        "approval_required": approval_required,
    }


def _relative_to_project(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _approval_record(
    root: Path,
    path: Path,
    approval_id: str,
    kind: str,
    subject_type: str,
    subject_id: str,
    *,
    decided_at: str = "2026-11-16T08:20:00+00:00",
    **extra: str,
) -> dict:
    record = {
        "approval_id": approval_id,
        "schema_version": "1.0",
        "kind": kind,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "subject_path": _relative_to_project(path, root),
        "subject_sha256": sha256_file(path),
        "decision": "approved",
        "author": "Design Pact Author",
        "approver": f"{kind.replace('_', ' ').title()} Reviewer",
        "decided_at": decided_at,
        "rationale": "Independently reviewed the exact current subject.",
    }
    record.update(extra)
    return record


def build_validation_fixture(workspace: Path) -> Path:
    workspace = workspace.resolve()
    root = workspace / "project"
    java = workspace / "bin/java"
    java.parent.mkdir(parents=True, exist_ok=True)
    java.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    java.chmod(0o755)
    gradle = workspace / "gradle/bin/gradle"
    gradle.parent.mkdir(parents=True, exist_ok=True)
    gradle.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    gradle.chmod(0o755)
    sdk = workspace / "android-sdk"
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
        return CommandResult(0, f"fixture command passed: {' '.join(argv)}\n")

    with patch("bootstrap_project.java_major", return_value=17):
        errors, _ = bootstrap_project(
            target=root,
            app_name="Pact Fixture",
            package_name="com.example.pact",
            display_name="Pact Fixture",
            owner="Project Owner",
            java=java,
            android_sdk=sdk,
            gradle=gradle,
            timeout=30,
            command_runner=runner,
        )
    if errors:
        raise AssertionError(errors)

    write_yaml(
        root / "docs/product/journey-map.yaml",
        {
            **load_yaml(root / "docs/product/journey-map.yaml"),
            "journeys": [
                {
                    "id": "JRN-001",
                    "title": "Open the approved home screen",
                    "feature_ids": ["FEAT-001"],
                }
            ],
        },
    )
    write_yaml(
        root / "docs/product/feature-map.yaml",
        {
            **load_yaml(root / "docs/product/feature-map.yaml"),
            "features": [
                {
                    "id": "FEAT-001",
                    "journey_id": "JRN-001",
                    "title": "Show approved home content",
                    "screen_ids": ["SCREEN-001"],
                }
            ],
        },
    )
    write_yaml(
        root / "docs/design/screen-inventory.yaml",
        {
            **load_yaml(root / "docs/design/screen-inventory.yaml"),
            "screens": [
                {
                    "id": "SCREEN-001",
                    "name": "Home",
                    "feature_ids": ["FEAT-001"],
                    "state_ids": ["STATE-001"],
                    "figma": {
                        "file_key": "FKEY1",
                        "node_id": "1:2",
                        "revision": "FIG-R1",
                    },
                }
            ],
            "flows": [],
            "states": [
                {
                    "id": "STATE-001",
                    "screen_id": "SCREEN-001",
                    "name": "Content",
                    "figma": {
                        "file_key": "FKEY1",
                        "node_id": "1:3",
                        "revision": "FIG-R1",
                    },
                }
            ],
        },
    )
    coverage_objects = [
        {
            "object_id": object_id,
            "object_type": object_type,
            "status": "covered",
            "rationale": "Approved first-release scope.",
            "source_ids": [source],
        }
        for object_id, object_type, source in (
            ("JRN-001", "journey", "PRODUCT-CHARTER"),
            ("FEAT-001", "feature", "JRN-001"),
            ("SCREEN-001", "screen", "FEAT-001"),
            ("STATE-001", "state", "SCREEN-001"),
        )
    ]
    write_yaml(
        root / "docs/product/coverage-matrix.yaml",
        {
            **load_yaml(root / "docs/product/coverage-matrix.yaml"),
            "objects": coverage_objects,
        },
    )
    write_yaml(
        root / "docs/product/release-scope.yaml",
        {
            **load_yaml(root / "docs/product/release-scope.yaml"),
            "release_id": "1.0",
            "journey_ids": ["JRN-001"],
            "feature_ids": ["FEAT-001"],
            "screen_ids": ["SCREEN-001"],
            "flow_ids": [],
            "exclusions": [],
        },
    )

    write_markdown(
        root / SPEC_L1_PATH,
        {
            **metadata(
                "ART-200",
                "specification",
                "scope_defined",
                source_ids=["JRN-001", "FEAT-001"],
            ),
            "spec_id": "SPEC-001",
            "spec_level": "L1",
            "journey_ids": ["JRN-001"],
            "feature_ids": ["FEAT-001"],
            "screen_ids": [],
            "flow_ids": [],
            "state_ids": [],
        },
        "# SPEC-001: Home journey\n\n## Entry and Outcome\n\nOpen the approved home screen.\n",
    )
    acceptance = [
        {
            "id": "AC-001",
            "state_id": "STATE-001",
            "title": "Approved home content is visible",
            "given": "The approved deterministic fixture",
            "when": "The home screen opens",
            "then": "The approved title and primary action are visible",
            "test_ids": ["TEST-001"],
            "visual_required": True,
            "visual_shot_ids": ["SHOT-001"],
        }
    ]
    write_markdown(
        root / SPEC_L2_PATH,
        {
            **metadata(
                "ART-201",
                "specification",
                "design_contract_ready",
                source_ids=["JRN-001", "FEAT-001", "SCREEN-001"],
            ),
            "spec_id": "SPEC-002",
            "spec_level": "L2",
            "journey_ids": ["JRN-001"],
            "feature_ids": ["FEAT-001"],
            "screen_ids": ["SCREEN-001"],
            "flow_ids": [],
            "state_ids": ["STATE-001"],
            "ac_ids": ["AC-001"],
            "acceptance_criteria": acceptance,
        },
        "# SPEC-002: Home\n\n## Included and Excluded Behavior\n\nOnly approved home content.\n",
    )
    test_path = root / TEST_PATH
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(
        "package com.example.pact\n\n"
        "class HomeScreenTest {\n"
        "    // DESIGN_PACT: TEST-001 => AC-001\n"
        "    @Test\n"
        "    fun approvedHomeContentIsVisible() {\n"
        "        check(true)\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    implementation = root / IMPLEMENTATION_PATH
    implementation.parent.mkdir(parents=True, exist_ok=True)
    implementation.write_text(
        "package com.example.pact\n\nobject HomeScreen { val visible = true }\n",
        encoding="utf-8",
    )
    test_contract = {
        **metadata(
            "ART-300",
            "test_case_contract",
            "implementation",
            source_ids=["SPEC-002"],
        ),
        "slice_id": "SCREEN-001",
        "slice_type": "screen",
        "spec_id": "SPEC-002",
        "tests": [
            {
                "test_id": "TEST-001",
                "ac_ids": ["AC-001"],
                "state_ids": ["STATE-001"],
                "title": "Approved home content is visible",
                "test_type": "ui",
                "priority": "P0",
                "planning_status": "active",
                "precondition": "The approved fixture is active",
                "test_data": ["fixture=home"],
                "action": "Open the approved home screen",
                "expected": "The approved title and primary action are visible",
                "accessibility_assertions": ["A stable semantic label is exposed"],
                "visual_shot_ids": ["SHOT-001"],
                "implementation_path": TEST_PATH,
                "implementation_symbol": "approvedHomeContentIsVisible",
            }
        ],
    }
    write_yaml(root / CONTRACT_PATH, test_contract)
    write_markdown(
        root / CONTRACT_PATH.replace("test-cases.yaml", "test-cases.md"),
        metadata(
            "ART-301",
            "test_case_report",
            "implementation",
            status="draft",
            approval_required=False,
        ),
        "# Pending generated view\n",
    )

    for relative in (
        "docs/design/figma-references/SCREEN-001-home/STATE-001.png",
        "docs/verification/visual-reports/SCREEN-001-home/reference/STATE-001.png",
        "docs/verification/visual-reports/SCREEN-001-home/current/STATE-001.png",
        "docs/verification/visual-reports/SCREEN-001-home/diff/STATE-001.png",
        "docs/verification/baselines/SCREEN-001-home/images/STATE-001.png",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG_BYTES)
    image_hash = sha256_file(
        root / "docs/design/figma-references/SCREEN-001-home/STATE-001.png"
    )
    write_yaml(
        root / FIGMA_MANIFEST_PATH,
        {
            **metadata(
                "ART-050",
                "figma_reference",
                "design_contract_ready",
                source_ids=["SCREEN-001", "STATE-001", "SHOT-001"],
                approval_required=False,
            ),
            "source_kind": "figma-mcp",
            "structured": True,
            "file_key": "FKEY1",
            "node_id": "1:3",
            "node_name": "Home / Content",
            "revision": "FIG-R1",
            "source_url": "https://www.figma.com/design/FKEY1/Home?node-id=1-3",
            "screen_id": "SCREEN-001",
            "state_id": "STATE-001",
            "format": "png",
            "path": "STATE-001.png",
            "sha256": image_hash,
            "width_px": 1,
            "height_px": 1,
            "export_scale": 1.0,
        },
    )
    write_yaml(
        root / "docs/verification/visual-policy.yaml",
        {
            **load_yaml(root / "docs/verification/visual-policy.yaml"),
            "renderer": {
                "name": "Compose screenshot",
                "version": "1.0",
                "android_api": 35,
            },
            "device": {
                "width_px": 1080,
                "height_px": 2400,
                "density_dpi": 420,
                "orientation": "portrait",
            },
            "application": {
                "locale": "en-US",
                "font_scale": 1.0,
                "theme": "light",
                "animation_policy": "disabled",
                "font_files": [],
                "timezone": "UTC",
                "clock": "2026-11-16T08:00:00Z",
            },
            "fixtures": {
                "clock": "2026-11-16T08:00:00Z",
                "timezone": "UTC",
                "network": "stubbed",
            },
        },
    )
    policy_hash = sha256_file(root / "docs/verification/visual-policy.yaml")
    write_yaml(
        root / BASELINE_PATH,
        {
            **metadata(
                "ART-080",
                "visual_baseline",
                "verification",
                source_ids=["SCREEN-001", "STATE-001", "SHOT-001"],
            ),
            "screen_id": "SCREEN-001",
            "state_id": "STATE-001",
            "shot_id": "SHOT-001",
            "path": "images/STATE-001.png",
            "sha256": sha256_file(
                root
                / "docs/verification/baselines/SCREEN-001-home/images/STATE-001.png"
            ),
            "render_policy_sha256": policy_hash,
            "approval_id": "APR-003",
        },
    )
    current_hash = sha256_file(
        root
        / "docs/verification/visual-reports/SCREEN-001-home/current/STATE-001.png"
    )
    write_yaml(
        root / VISUAL_REPORT_PATH,
        {
            **metadata(
                "ART-070",
                "visual_report",
                "verification",
                source_ids=["SCREEN-001", "STATE-001", "SHOT-001"],
            ),
            "screen_id": "SCREEN-001",
            "state_id": "STATE-001",
            "shot_id": "SHOT-001",
            "comparison_status": "pass",
            "figma_reference": {
                "path": "docs/design/figma-references/SCREEN-001-home/STATE-001.png",
                "sha256": image_hash,
            },
            "current": {
                "path": "docs/verification/visual-reports/SCREEN-001-home/current/STATE-001.png",
                "sha256": current_hash,
            },
            "diff": {
                "path": "docs/verification/visual-reports/SCREEN-001-home/diff/STATE-001.png",
                "sha256": sha256_file(
                    root
                    / "docs/verification/visual-reports/SCREEN-001-home/diff/STATE-001.png"
                ),
            },
            "metrics": {
                "key_region_geometry_dp": 0.0,
                "figma_ssim": 0.999,
                "figma_pixel_difference": 0.001,
                "baseline_ssim": 1.0,
                "baseline_pixel_difference": 0.0,
            },
            "review": {
                "reviewer": "Visual Reviewer",
                "reviewed_at": "2026-11-16T08:19:00+00:00",
                "conclusion": "pass",
                "approval_id": "APR-003",
            },
        },
    )

    contract_hash = sha256_file(root / CONTRACT_PATH)
    declaration = extract_test_declaration(
        test_path,
        "TEST-001",
        "approvedHomeContentIsVisible",
    )
    test_hash = sha256_file(test_path)
    events: list[dict] = []
    previous = ""
    for number, (phase, exit_code, failure_kind) in enumerate(
        (
            ("red", 1, "behavior"),
            ("green", 0, None),
            ("refactor", 0, None),
            ("verify", 0, None),
        ),
        start=1,
    ):
        event_id = f"TDD-{number:03d}"
        artifact_path = f"docs/verification/tdd-artifacts/{event_id}.log"
        artifact = root / artifact_path
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(f"{phase} fixture log\n", encoding="utf-8")
        event = {
            "event_id": event_id,
            "schema_version": "1.0",
            "spec_id": "SPEC-002",
            "ac_ids": ["AC-001"],
            "test_id": "TEST-001",
            "phase": phase,
            "command": ["./gradlew", ":app:testDebugUnitTest", "--tests", "*HomeScreenTest"],
            "exit_code": exit_code,
            "failure_kind": failure_kind,
            "started_at": f"2026-11-16T08:0{number}:00+00:00",
            "finished_at": f"2026-11-16T08:0{number}:30+00:00",
            "actor": "test-runner",
            "artifact_path": artifact_path,
            "artifact_sha256": sha256_file(artifact),
            "test_declaration_sha256": declaration.sha256,
            "contract_sha256": contract_hash,
            "implementation_path": TEST_PATH,
            "implementation_sha256": test_hash,
            "status": "captured",
            "prev_event_sha256": previous,
        }
        event["event_sha256"] = event_hash(event)
        previous = event["event_sha256"]
        events.append(event)
    ledger = root / "docs/verification/tdd-ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    for event in events:
        append_jsonl(ledger, event)

    state_path = root / "docs/project/state.yaml"
    state = load_yaml(state_path)
    state.update(
        {
            "state": "verification",
            "created_at_state": "verification",
            "revision": 2,
            "design_snapshot": {
                "status": "structured",
                "file_keys": ["FKEY1"],
                "revision": "FIG-R1",
            },
            "blockers": [],
            "release": {"approval_id": "APR-005"},
        }
    )
    write_yaml(state_path, state)

    write_markdown(
        root / "docs/verification/scope-audit.md",
        {
            **metadata(
                "ART-031",
                "scope_audit",
                "verification",
                status="approved",
            ),
            "audit_id": "SCOPE-AUDIT-001",
            "conclusion": "pass",
            "reviewer": "Independent Scope Reviewer",
            "figma_revision": "FIG-R1",
            "product_revision": "release-1.0",
        },
        "# Scope Audit\n\n## Traversal\n\nFigma and product scope were traversed in both directions.\n",
    )
    write_yaml(
        root / "docs/design/design-exceptions.yaml",
        {**load_yaml(root / "docs/design/design-exceptions.yaml"), "exceptions": []},
    )
    write_yaml(
        root / "docs/design/gaps.yaml",
        {**load_yaml(root / "docs/design/gaps.yaml"), "gaps": []},
    )

    approvals_path = root / "docs/project/approvals.jsonl"
    approvals_path.write_text("", encoding="utf-8")
    records = [
        _approval_record(
            root,
            root / "docs/product/release-scope.yaml",
            "APR-001",
            "scope",
            "release_scope",
            "1.0",
        ),
        _approval_record(
            root,
            root / "docs/design/component-map.yaml",
            "APR-002",
            "design_contract",
            "design_contract",
            "design-contract-1.0",
        ),
        _approval_record(
            root,
            root / BASELINE_PATH,
            "APR-003",
            "visual_baseline",
            "visual_baseline",
            "SHOT-001",
        ),
        _approval_record(
            root,
            root / "docs/design/design-exceptions.yaml",
            "APR-004",
            "exception",
            "design_exception",
            "design-exceptions",
        ),
        _approval_record(
            root,
            root / "docs/product/release-scope.yaml",
            "APR-005",
            "release",
            "release",
            "release-1.0",
        ),
        _approval_record(
            root,
            root / "docs/verification/scope-audit.md",
            "APR-006",
            "artifact",
            "artifact",
            "ART-031",
        ),
        _approval_record(
            root,
            root / "docs/design/screen-inventory.yaml",
            "APR-011",
            "design_contract",
            "design_contract",
            "screen-inventory-1.0",
        ),
        _approval_record(
            root,
            root / "docs/design/token-map.yaml",
            "APR-012",
            "design_contract",
            "design_contract",
            "token-map-1.0",
        ),
        _approval_record(
            root,
            root / "docs/design/asset-inventory.yaml",
            "APR-013",
            "design_contract",
            "design_contract",
            "asset-inventory-1.0",
        ),
        _approval_record(
            root,
            root / "docs/design/interaction-contract.md",
            "APR-014",
            "design_contract",
            "design_contract",
            "interaction-contract-1.0",
        ),
        _approval_record(
            root,
            root / "docs/design/design-exceptions.yaml",
            "APR-015",
            "design_contract",
            "design_contract",
            "design-exceptions-1.0",
        ),
        _approval_record(
            root,
            root / "docs/design/gaps.yaml",
            "APR-016",
            "design_contract",
            "design_contract",
            "gaps-1.0",
        ),
    ]
    for number, event in enumerate(events, start=7):
        record = _approval_record(
            root,
            ledger,
            f"APR-{number:03d}",
            "tdd_event",
            "tdd_event",
            str(event["event_id"]),
        )
        record.update(
            {
                "subject_sha256": event["event_sha256"],
                "related_test_id": "TEST-001",
                "related_spec_id": "SPEC-002",
            }
        )
        records.append(record)
    for record in records:
        append_jsonl(approvals_path, record)

    register_document_artifacts(root)
    render_reports(root, generated_at=GENERATED_AT)
    return root
