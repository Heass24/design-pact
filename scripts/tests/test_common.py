from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common import (  # noqa: E402
    DesignPactError,
    allocate_artifact_entry,
    append_jsonl,
    approval_errors,
    assess_tdd_test,
    artifact_registry_errors,
    canonical_json,
    event_hash,
    extract_test_declaration,
    retire_artifact_entry,
    safe_project_path,
    sha256_bytes,
    sha256_file,
    validate_schema,
    validate_tdd_ledger,
)
from preflight import inspect_figma_manifest  # noqa: E402


class KotlinDeclarationTests(unittest.TestCase):
    def parse(self, source: str, symbol: str = "observableBehavior"):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "FeatureTest.kt"
            path.write_text(source, encoding="utf-8")
            return extract_test_declaration(path, "TEST-001", symbol)

    def test_block_body_with_multiline_generic_signature(self) -> None:
        declaration = self.parse(
            """\
class FeatureTest {
    // DESIGN_PACT: TEST-001 => AC-001,AC-002
    @Test
    fun <T> observableBehavior(
        value: Map<String, List<T>>,
        callback: (T) -> Unit = {},
    ): Result<List<T>> {
        val text = "} not a block"
        return Result.success(emptyList())
    }
}
"""
        )
        self.assertEqual(declaration.ac_ids, ("AC-001", "AC-002"))
        self.assertEqual(declaration.marker_line, 2)
        self.assertIn("Result<List<T>>", declaration.source)

    def test_comments_and_literals_do_not_close_body(self) -> None:
        declaration = self.parse(
            """\
// DESIGN_PACT: TEST-001 => AC-001
@Test
fun observableBehavior() {
    /* outer { /* nested } */ still a comment } */
    val raw = \"\"\"literal } { // text\"\"\"
    val character = '}'
    check(raw.isNotEmpty() && character == '}')
}
"""
        )
        self.assertIn("nested", declaration.source)
        self.assertIn("literal", declaration.source)
        self.assertTrue(declaration.source.rstrip().endswith("}"))

    def test_expression_body_stops_before_next_declaration(self) -> None:
        declaration = self.parse(
            """\
// DESIGN_PACT: TEST-001 => AC-001
@Test
fun observableBehavior() =
    run {
        val label = "not the end }"
        check(label.isNotEmpty())
    }

@Test
fun differentTest() {
    error("must not be captured")
}
"""
        )
        self.assertIn('val label = "not the end }"', declaration.source)
        self.assertNotIn("differentTest", declaration.source)

    def test_function_name_must_be_exact(self) -> None:
        with self.assertRaisesRegex(DesignPactError, "function name is not exact"):
            self.parse(
                """\
// DESIGN_PACT: TEST-001 => AC-001
@Test
fun observableBehaviorExtra() {
    Unit
}
""",
                symbol="observableBehavior",
            )

    def test_marker_must_be_unique_and_adjacent(self) -> None:
        with self.assertRaisesRegex(DesignPactError, "exactly one marker"):
            self.parse(
                """\
// DESIGN_PACT: TEST-001 => AC-001
@Test
fun observableBehavior() = Unit
// DESIGN_PACT: TEST-001 => AC-001
@Test
fun anotherBehavior() = Unit
"""
            )
        with self.assertRaisesRegex(DesignPactError, "directly above @Test"):
            self.parse(
                """\
// DESIGN_PACT: TEST-001 => AC-001
// intervening comment
@Test
fun observableBehavior() = Unit
"""
            )

    def test_declaration_hash_is_stable_and_sensitive(self) -> None:
        base = """\
// DESIGN_PACT: TEST-001 => AC-001
@Test
fun observableBehavior() {
    assertEquals(1, 1)
}
"""
        first = self.parse(base)
        second = self.parse(base.replace("\n", "\r\n"))
        changed = self.parse(base.replace("assertEquals(1, 1)", "assertEquals(2, 2)"))
        self.assertEqual(first.sha256, sha256_bytes(first.source.encode("utf-8")))
        self.assertEqual(first.sha256, second.sha256)
        self.assertNotEqual(first.sha256, changed.sha256)

    def test_declaration_source_is_exact_without_duplicated_prefix(self) -> None:
        base = """\
// DESIGN_PACT: TEST-001 => AC-001
@Test
fun observableBehavior() {
    assertEquals(1, 1)
}
"""
        declaration = self.parse(base)
        self.assertEqual(declaration.source, base.rstrip("\n"))
        self.assertEqual(declaration.source.count("// DESIGN_PACT: TEST-001"), 1)
        self.assertEqual(declaration.source.count("@Test"), 1)
        self.assertEqual(
            declaration.sha256,
            sha256_bytes(base.rstrip("\n").encode("utf-8")),
        )


class SchemaTests(unittest.TestCase):
    def test_ref_keeps_sibling_constraints(self) -> None:
        schema = {
            "type": "object",
            "$defs": {
                "image": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string", "minLength": 1}},
                }
            },
            "properties": {
                "image": {
                    "$ref": "#/$defs/image",
                    "required": ["sha256"],
                }
            },
        }
        errors = validate_schema({"image": {"path": "x.png"}}, schema, "report")
        self.assertTrue(any("sha256" in error for error in errors), errors)

    def test_conditional_branch_validates_nested_properties(self) -> None:
        schema = {
            "type": "object",
            "allOf": [
                {
                    "if": {
                        "properties": {"kind": {"const": "screen"}},
                        "required": ["kind"],
                    },
                    "then": {
                        "properties": {
                            "count": {"type": "integer", "minimum": 1}
                        }
                    },
                }
            ],
        }
        self.assertEqual(
            validate_schema({"kind": "screen", "count": 1}, schema, "sample"),
            [],
        )
        self.assertTrue(
            validate_schema({"kind": "screen", "count": 0}, schema, "sample")
        )

    def test_not_and_dependent_required_are_enforced(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "not": {"enum": ["placeholder", "unknown"]},
                },
                "approver": {"type": "string"},
                "author": {"type": "string"},
            },
            "dependentRequired": {"approver": ["author"]},
        }
        self.assertEqual(
            validate_schema(
                {"kind": "human", "approver": "Ada", "author": "Lin"},
                schema,
                "sample",
            ),
            [],
        )
        self.assertTrue(
            validate_schema({"kind": "placeholder"}, schema, "sample")
        )
        self.assertTrue(validate_schema({"approver": "Ada"}, schema, "sample"))


class PathSafetyTests(unittest.TestCase):
    def test_relative_path_inside_project_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            self.assertEqual(
                safe_project_path(root, "docs/state.yaml", "path"),
                root / "docs" / "state.yaml",
            )

    def test_blank_escape_root_and_home_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve() / "project"
            root.mkdir()
            for value in ("", "   ", ".", "../outside", str(Path(raw).resolve())):
                with self.subTest(value=value):
                    with self.assertRaises(DesignPactError):
                        safe_project_path(root, value, "path")


class ArtifactRegistryLifecycleTests(unittest.TestCase):
    def write_registry(self, root: Path, entries: list[dict]) -> None:
        path = root / "docs/project/artifact-ids.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        registry = {
            "artifact_type": "artifact_registry",
            "schema_version": "1.0",
            "version": 1,
            "entries": entries,
        }
        path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    def entry(self, **changes: object) -> dict:
        entry = {
            "key": "docs/specs/L2/SPEC-001-SCREEN-001-home.md",
            "artifact_id": "ART-601",
            "path": "docs/specs/L2/SPEC-001-SCREEN-001-home.md",
            "artifact_type": "spec_l2",
        }
        entry.update(changes)
        return entry

    def test_missing_lifecycle_remains_backward_compatible_active(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.write_registry(root, [self.entry()])
            self.assertEqual(artifact_registry_errors(root), [])

    def test_tombstone_requires_removal_time_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.write_registry(
                root,
                [self.entry(lifecycle="tombstone")],
            )
            errors = artifact_registry_errors(root)
            self.assertTrue(any("removed_at" in error for error in errors), errors)
            self.assertTrue(any("reason" in error for error in errors), errors)

    def test_tombstone_and_active_entries_cannot_share_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tombstone = self.entry(
                lifecycle="tombstone",
                removed_at="2026-01-01T00:00:00+00:00",
                reason="Screen removed from approved scope",
            )
            duplicate_id = self.entry(
                key="docs/specs/L2/SPEC-002-SCREEN-002-settings.md",
                path="docs/specs/L2/SPEC-002-SCREEN-002-settings.md",
            )
            self.write_registry(root, [tombstone, duplicate_id])
            errors = artifact_registry_errors(root)
            self.assertTrue(
                any("artifact_id ART-601" in error for error in errors),
                errors,
            )

            duplicate_path = self.entry(
                key="replacement-key",
                artifact_id="ART-602",
            )
            self.write_registry(root, [tombstone, duplicate_path])
            errors = artifact_registry_errors(root)
            self.assertTrue(
                any("duplicate artifact path" in error for error in errors),
                errors,
            )

    def test_tombstone_rejects_unsafe_path_and_invalid_time(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.write_registry(
                root,
                [
                    self.entry(
                        path="../outside.md",
                        lifecycle="tombstone",
                        removed_at="2026-01-01",
                        reason="Screen removed",
                    )
                ],
            )
            errors = artifact_registry_errors(root)
            self.assertTrue(any("escapes project root" in error for error in errors), errors)
            self.assertTrue(any("removed_at" in error for error in errors), errors)

    def test_retire_is_irreversible_and_allocation_cannot_reuse_identity(self) -> None:
        registry = {"entries": [self.entry()]}
        retire_artifact_entry(
            registry,
            key=self.entry()["key"],
            removed_at="2026-01-01T00:00:00+00:00",
            reason="Screen removed from approved scope",
        )
        tombstone = registry["entries"][0]
        self.assertEqual(tombstone["lifecycle"], "tombstone")

        with self.assertRaisesRegex(DesignPactError, "tombstoned"):
            allocate_artifact_entry(
                registry,
                key=str(tombstone["key"]),
                path=str(tombstone["path"]),
                artifact_type=str(tombstone["artifact_type"]),
            )
        with self.assertRaisesRegex(DesignPactError, "already in use"):
            allocate_artifact_entry(
                registry,
                key="docs/specs/L2/SPEC-002-SCREEN-002-settings.md",
                path="docs/specs/L2/SPEC-002-SCREEN-002-settings.md",
                artifact_type="spec_l2",
                preferred_id="ART-601",
            )
        with self.assertRaisesRegex(DesignPactError, "already registered"):
            allocate_artifact_entry(
                registry,
                key="new-artifact-at-old-path",
                path=str(tombstone["path"]),
                artifact_type="generated_test_view",
            )

    def test_retire_rejects_active_only_inputs_and_missing_key(self) -> None:
        registry = {"entries": [self.entry()]}
        with self.assertRaisesRegex(DesignPactError, "unknown artifact key"):
            retire_artifact_entry(
                registry,
                key="missing",
                removed_at="2026-01-01T00:00:00+00:00",
                reason="Removed",
            )
        with self.assertRaisesRegex(DesignPactError, "reason"):
            retire_artifact_entry(
                registry,
                key=self.entry()["key"],
                removed_at="2026-01-01T00:00:00+00:00",
                reason=" ",
            )


class TddLedgerTests(unittest.TestCase):
    def setup_project(self, root: Path) -> tuple[Path, Path]:
        test_path = (
            root
            / "app/src/test/java/com/example/app/FeatureTest.kt"
        )
        test_path.parent.mkdir(parents=True, exist_ok=True)
        if not test_path.exists():
            test_path.write_text(
                """\
class FeatureTest {
    // DESIGN_PACT: TEST-001 => AC-001
    @Test
    fun observableBehavior() {
        check(false)
    }
}
""",
                encoding="utf-8",
            )
        implementation = (
            root
            / "app/src/main/java/com/example/app/Feature.kt"
        )
        implementation.parent.mkdir(parents=True, exist_ok=True)
        if not implementation.exists():
            implementation.write_text(
                "package com.example.app\n\nobject Feature { fun observe() = true }\n",
                encoding="utf-8",
            )
        contract_path = (
            root
            / "docs/verification/test-cases/SCREEN-001-home/test-cases.yaml"
        )
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        if not contract_path.exists():
            contract_path.write_text(
                """\
slice_id: SCREEN-001
slice_type: screen
spec_id: SPEC-001
tests:
  - test_id: TEST-001
    ac_ids: [AC-001]
    state_ids: [STATE-001]
    title: Observable behavior
    test_type: unit
    priority: P0
    planning_status: planned
    precondition: Feature test harness is available
    test_data: []
    action: Observe the feature
    expected: The approved behavior is returned
    accessibility_assertions: []
    visual_shot_ids: []
    implementation_path: app/src/test/java/com/example/app/FeatureTest.kt
    implementation_symbol: observableBehavior
""",
                encoding="utf-8",
            )
        (root / "docs/project").mkdir(parents=True, exist_ok=True)
        approvals = root / "docs/project/approvals.jsonl"
        if not approvals.exists():
            approvals.write_text("", encoding="utf-8")
        return contract_path, implementation

    def event(
        self,
        previous: str = "",
        *,
        phase: str = "red",
        number: int = 1,
        **changes: object,
    ) -> dict:
        root = Path(changes.pop("_root"))
        contract, implementation = self.setup_project(root)
        exit_code = 1 if phase == "red" else 0
        record = {
            "event_id": f"TDD-{number:03d}",
            "schema_version": "1.0",
            "spec_id": "SPEC-001",
            "ac_ids": ["AC-001"],
            "test_id": "TEST-001",
            "phase": phase,
            "command": ["./gradlew", "testDebugUnitTest", "--tests", "*FeatureTest*"],
            "exit_code": exit_code,
            "failure_kind": "behavior" if phase == "red" else None,
            "started_at": f"2026-01-01T00:00:{number:02d}+00:00",
            "finished_at": f"2026-01-01T00:00:{number + 1:02d}+00:00",
            "actor": "test-runner",
            "artifact_path": (
                f"docs/verification/tdd-artifacts/TDD-{number:03d}.log"
            ),
            "artifact_sha256": sha256_bytes(
                b"AssertionError\n" if phase == "red" else b"PASS\n"
            ),
            "test_declaration_sha256": extract_test_declaration(
                root / "app/src/test/java/com/example/app/FeatureTest.kt",
                "TEST-001",
                "observableBehavior",
            ).sha256,
            "contract_sha256": sha256_file(contract),
            "implementation_path": implementation.relative_to(root).as_posix(),
            "implementation_sha256": sha256_file(implementation),
            "status": "captured",
            "prev_event_sha256": previous,
        }
        record.update(changes)
        record["event_sha256"] = event_hash(record)
        return record

    def write_artifacts(self, root: Path, events: list[dict]) -> None:
        for event in events:
            path = root / str(event["artifact_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                b"AssertionError\n"
                if event["phase"] == "red"
                else b"PASS\n"
            )

    def append_cycle(self, root: Path, previous: str = "") -> tuple[list[dict], str]:
        events: list[dict] = []
        for number, phase in enumerate(("red", "green", "refactor", "verify"), 1):
            event = self.event(
                previous,
                phase=phase,
                number=number,
                _root=root,
            )
            events.append(event)
            previous = str(event["event_sha256"])
        return events, previous

    def approve_events(self, root: Path, events: list[dict]) -> None:
        def event_time(event: dict) -> str:
            return str(event["finished_at"])

        for number, event in enumerate(events, 1):
            approval = {
                "approval_id": f"APR-{number:03d}",
                "schema_version": "1.0",
                "kind": "tdd_event",
                "subject_type": "tdd_event",
                "subject_id": event["event_id"],
                "subject_path": "docs/verification/tdd-ledger.jsonl",
                "subject_sha256": event["event_sha256"],
                "decision": "approved",
                "author": "test-runner",
                "approver": "Product Owner",
                "decided_at": event_time(event).replace(":01+", ":02+").replace(
                    ":05+00:00", ":06+00:00"
                ),
                "rationale": "Reviewed the executable evidence.",
                "related_test_id": event["test_id"],
                "related_spec_id": event["spec_id"],
            }
            append_jsonl(root / "docs/project/approvals.jsonl", approval)

    def test_complete_accepted_cycle_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            events, _ = self.append_cycle(root)
            self.write_artifacts(root, events)
            ledger = root / "docs/verification/tdd-ledger.jsonl"
            for event in events:
                append_jsonl(ledger, event)
            self.approve_events(root, events)
            self.assertEqual(validate_tdd_ledger(root), [])

    def test_isolated_red_never_passes_even_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            event = self.event(_root=root)
            self.write_artifacts(root, [event])
            append_jsonl(root / "docs/verification/tdd-ledger.jsonl", event)
            self.approve_events(root, [event])
            errors = validate_tdd_ledger(root, require_accepted=True)
            self.assertTrue(any("latest TDD cycle" in error for error in errors), errors)

    def test_tampered_event_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            events, _ = self.append_cycle(root)
            events[0]["exit_code"] = 0
            self.write_artifacts(root, events)
            ledger = root / "docs/verification/tdd-ledger.jsonl"
            for event in events:
                append_jsonl(ledger, event)
            self.approve_events(root, events)
            errors = validate_tdd_ledger(root)
            self.assertTrue(any("Red evidence" in error for error in errors), errors)
            self.assertTrue(any("event hash is invalid" in error for error in errors), errors)

    def test_event_status_cannot_claim_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            events, _ = self.append_cycle(root)
            events[0]["status"] = "accepted"
            events[0]["event_sha256"] = event_hash(events[0])
            self.write_artifacts(root, events)
            ledger = root / "docs/verification/tdd-ledger.jsonl"
            for event in events:
                append_jsonl(ledger, event)
            self.approve_events(root, events)
            errors = validate_tdd_ledger(root)
            self.assertTrue(any("status" in error for error in errors), errors)

    def test_rejected_event_makes_assessment_fail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            events, _ = self.append_cycle(root)
            approved = {
                str(event["event_id"]): str(event["event_sha256"])
                for event in events
            }
            rejected = {
                str(events[0]["event_id"]): str(events[0]["event_sha256"])
            }
            assessment = assess_tdd_test(
                events,
                approved,
                "TEST-001",
                rejected,
            )
            self.assertEqual(assessment.status, "failed")
            self.assertTrue(
                any("rejected" in error for error in assessment.errors),
                assessment.errors,
            )

    def test_rejection_wins_when_approval_and_rejection_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            events, _ = self.append_cycle(root)
            self.write_artifacts(root, events)
            ledger = root / "docs/verification/tdd-ledger.jsonl"
            for event in events:
                append_jsonl(ledger, event)
            self.approve_events(root, events)
            rejected = {
                "approval_id": "APR-005",
                "schema_version": "1.0",
                "kind": "tdd_event",
                "subject_type": "tdd_event",
                "subject_id": events[0]["event_id"],
                "subject_path": "docs/verification/tdd-ledger.jsonl",
                "subject_sha256": events[0]["event_sha256"],
                "decision": "rejected",
                "author": "test-runner",
                "approver": "Product Owner",
                "decided_at": "2026-01-01T00:00:08+00:00",
                "rationale": "The Red failure came from test setup.",
                "related_test_id": "TEST-001",
                "related_spec_id": "SPEC-001",
            }
            append_jsonl(root / "docs/project/approvals.jsonl", rejected)
            errors = validate_tdd_ledger(root, require_accepted=True)
            self.assertTrue(
                any("conflicting decisions" in error for error in errors),
                errors,
            )
            assessment = assess_tdd_test(
                events,
                {
                    str(event["event_id"]): str(event["event_sha256"])
                    for event in events
                },
                "TEST-001",
                {str(events[0]["event_id"]): str(events[0]["event_sha256"])},
            )
            self.assertEqual(assessment.status, "failed")

    def test_unknown_event_status_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            events, _ = self.append_cycle(root)
            events[0]["status"] = "rejected"
            events[0]["event_sha256"] = event_hash(events[0])
            self.write_artifacts(root, events)
            ledger = root / "docs/verification/tdd-ledger.jsonl"
            for event in events:
                append_jsonl(ledger, event)
            errors = validate_tdd_ledger(root)
            self.assertTrue(
                any("invalid status" in error for error in errors), errors
            )

    def test_contract_and_implementation_hashes_are_bound(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            events, _ = self.append_cycle(root)
            self.write_artifacts(root, events)
            ledger = root / "docs/verification/tdd-ledger.jsonl"
            for event in events:
                append_jsonl(ledger, event)
            self.approve_events(root, events)
            contract, _ = self.setup_project(root)
            contract.write_text(contract.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            errors = validate_tdd_ledger(root)
            self.assertTrue(any("contract hash" in error for error in errors), errors)

    def test_latest_implementation_must_match_verify_event(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            events, _ = self.append_cycle(root)
            self.write_artifacts(root, events)
            ledger = root / "docs/verification/tdd-ledger.jsonl"
            for event in events:
                append_jsonl(ledger, event)
            self.approve_events(root, events)
            _, implementation = self.setup_project(root)
            implementation.write_text(
                implementation.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            errors = validate_tdd_ledger(root)
            self.assertTrue(
                any("implementation hash" in error for error in errors), errors
            )


class ApprovalTests(unittest.TestCase):
    def setup_project(self, root: Path) -> tuple[Path, dict]:
        target = root / "docs/product/release-scope.yaml"
        target.parent.mkdir(parents=True)
        target.write_text("release_id: '1.0'\n", encoding="utf-8")
        (root / "docs/project").mkdir(parents=True)
        approval = {
            "approval_id": "APR-001",
            "schema_version": "1.0",
            "kind": "scope",
            "subject_type": "release_scope",
            "subject_id": "release-1.0",
            "subject_path": "docs/product/release-scope.yaml",
            "subject_sha256": sha256_file(target),
            "decision": "approved",
            "author": "Scope Author",
            "approver": "Product Owner",
            "decided_at": "2026-01-02T00:00:00+00:00",
            "rationale": "Reviewed against the approved product brief.",
        }
        return target, approval

    def write(self, root: Path, approval: dict) -> None:
        (root / "docs/project/approvals.jsonl").write_text(
            canonical_json(approval) + "\n",
            encoding="utf-8",
        )

    def test_valid_independent_human_approval_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _, approval = self.setup_project(root)
            self.write(root, approval)
            self.assertEqual(approval_errors(root), [])

    def test_missing_author_self_approval_and_ai_approver_are_rejected(self) -> None:
        variants = (
            {"author": ""},
            {"approver": "Scope Author"},
            {"approver": "AI Agent"},
            {"approver": "automation-bot"},
            {"approver": "TODO"},
        )
        for change in variants:
            with self.subTest(change=change):
                with tempfile.TemporaryDirectory() as raw:
                    root = Path(raw)
                    _, approval = self.setup_project(root)
                    approval.update(change)
                    self.write(root, approval)
                    self.assertTrue(approval_errors(root))

    def test_zero_hash_and_subject_type_mismatch_are_rejected(self) -> None:
        variants = (
            {"subject_sha256": "0" * 64},
            {"subject_type": "design_contract"},
        )
        for change in variants:
            with self.subTest(change=change):
                with tempfile.TemporaryDirectory() as raw:
                    root = Path(raw)
                    _, approval = self.setup_project(root)
                    approval.update(change)
                    self.write(root, approval)
                    self.assertTrue(approval_errors(root))

    def test_tdd_approval_must_follow_event_completion(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "docs/project").mkdir(parents=True)
            event = {
                "event_id": "TDD-001",
                "finished_at": "2026-01-02T00:00:00+00:00",
                "event_sha256": "a" * 64,
                "test_id": "TEST-001",
                "spec_id": "SPEC-001",
            }
            append_jsonl(root / "docs/verification/tdd-ledger.jsonl", event)
            approval = {
                "approval_id": "APR-001",
                "schema_version": "1.0",
                "kind": "tdd_event",
                "subject_type": "tdd_event",
                "subject_id": "TDD-001",
                "subject_path": "docs/verification/tdd-ledger.jsonl",
                "subject_sha256": "a" * 64,
                "decision": "approved",
                "author": "test-runner",
                "approver": "Product Owner",
                "decided_at": "2026-01-01T23:59:59+00:00",
                "rationale": "Reviewed.",
            }
            self.write(root, approval)
            errors = approval_errors(root)
            self.assertTrue(any("before" in error for error in errors), errors)


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAusB9Y9Z4nYAAAAASUVORK5CYII="
)


class FigmaEvidenceTests(unittest.TestCase):
    def write_manifest(
        self,
        root: Path,
        *,
        change: dict | None = None,
    ) -> Path:
        image = root / "SCREEN-001/STATE-001.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(PNG_1X1)
        manifest = {
            "artifact_id": "ART-050",
            "artifact_type": "figma_reference",
            "schema_version": "1.0",
            "version": 1,
            "owner": "design-contract-owner",
            "created_at_state": "design_contract_ready",
            "status": "draft",
            "source_ids": ["SCREEN-001", "STATE-001"],
            "upstream_sha256": "",
            "approval_required": False,
            "source_kind": "figma-mcp",
            "structured": True,
            "file_key": "AbCdE12345",
            "node_id": "12:34",
            "node_name": "Home / Ready",
            "revision": "2026-01-01T00:00:00Z",
            "source_url": (
                "https://www.figma.com/design/AbCdE12345/App"
                "?node-id=12-34"
            ),
            "screen_id": "SCREEN-001",
            "state_id": "STATE-001",
            "path": "STATE-001.png",
            "format": "png",
            "sha256": sha256_bytes(PNG_1X1),
            "width_px": 1,
            "height_px": 1,
            "export_scale": 1.0,
        }
        if change:
            manifest.update(change)
        path = image.parent / "manifest.yaml"
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return path

    def test_valid_structured_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = self.write_manifest(Path(raw))
            summary, errors = inspect_figma_manifest(path)
            self.assertEqual(errors, [])
            self.assertEqual(summary["status"], "structured")

    def test_placeholders_url_mismatch_and_bad_image_are_rejected(self) -> None:
        variants = (
            {"file_key": "FIGMA_FILE_KEY"},
            {"node_id": "FIGMA_NODE_ID"},
            {"revision": "FIGMA_REVISION"},
            {"source_url": "https://www.figma.com/design/OtherKey/App?node-id=12-34"},
            {"source_url": "https://www.figma.com/design/AbCdE12345/App?node-id=99-99"},
            {"width_px": 2},
            {"format": "png", "sha256": "0" * 64},
        )
        for change in variants:
            with self.subTest(change=change):
                with tempfile.TemporaryDirectory() as raw:
                    path = self.write_manifest(Path(raw), change=change)
                    _, errors = inspect_figma_manifest(path)
                    self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
