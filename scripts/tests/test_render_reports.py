from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common import (  # noqa: E402
    DesignPactError,
    dump_yaml,
    event_hash,
    load_yaml,
    sha256_file,
    split_frontmatter,
)

try:
    from render_reports import render_reports  # noqa: E402
except ModuleNotFoundError:
    render_reports = None


GENERATED_AT = "2026-11-13T08:30:00+00:00"


class RenderReportsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "project"
        self.root.mkdir()
        self.base = self.root / "docs" / "verification" / "test-cases"
        self.specs = self.root / "docs" / "specs" / "L2"
        self.base.mkdir(parents=True)
        self.specs.mkdir(parents=True)
        (self.root / "docs" / "project").mkdir(parents=True)
        (self.root / "docs" / "verification").mkdir(parents=True, exist_ok=True)
        self.write_registry([])
        self.next_artifact_number = 701
        (self.root / "docs" / "project" / "approvals.jsonl").write_text(
            "",
            encoding="utf-8",
        )
        (self.root / "docs" / "verification" / "tdd-ledger.jsonl").write_text(
            "",
            encoding="utf-8",
        )

    def require_renderer(self):
        if render_reports is None:
            self.fail("render_reports.py is not implemented")
        return render_reports

    def write_registry(self, entries: list[dict]) -> None:
        registry = {
            "artifact_type": "artifact_registry",
            "schema_version": "1.0",
            "version": 1,
            "entries": entries,
        }
        (self.root / "docs" / "project" / "artifact-ids.yaml").write_text(
            dump_yaml(registry),
            encoding="utf-8",
        )

    def artifact_id(self) -> str:
        artifact_id = f"ART-{self.next_artifact_number:03d}"
        self.next_artifact_number += 1
        return artifact_id

    def add_spec(
        self,
        spec_id: str,
        slice_id: str,
        slug: str,
        *,
        title: str = "Home",
    ) -> Path:
        path = self.specs / f"{spec_id}-{slice_id}-{slug}.md"
        state_id = "STATE-001"
        metadata = {
            "artifact_id": self.artifact_id(),
            "artifact_type": "specification",
            "schema_version": "1.0",
            "version": 1,
            "owner": "design-owner",
            "created_at_state": "design_contract_ready",
            "status": "approved",
            "source_ids": ["SCREEN-001"],
            "upstream_sha256": "",
            "approval_required": True,
            "spec_id": spec_id,
            "spec_level": "L2",
            "journey_ids": ["JRN-001"],
            "feature_ids": ["FEAT-001"],
            "screen_ids": [slice_id] if slice_id.startswith("SCREEN-") else [],
            "flow_ids": [slice_id] if slice_id.startswith("FLOW-") else [],
            "state_ids": [state_id],
            "ac_ids": ["AC-001"],
            "acceptance_criteria": [
                {
                    "id": "AC-001",
                    "state_id": state_id,
                    "title": f"{title} is observable",
                    "given": "An approved fixture",
                    "when": "The user performs the action",
                    "then": "The approved result is visible",
                    "test_ids": ["TEST-001"],
                    "visual_required": True,
                    "visual_shot_ids": ["SHOT-001"],
                }
            ],
        }
        path.write_text(
            f"---\n{dump_yaml(metadata)}---\n\n# {spec_id}: {title}\n",
            encoding="utf-8",
        )
        return path

    def make_test(self, test_id: str, **changes) -> dict:
        value = {
            "test_id": test_id,
            "ac_ids": ["AC-001"],
            "state_ids": ["STATE-001"],
            "title": f"Observable behavior {test_id}",
            "test_type": "ui",
            "priority": "P0",
            "planning_status": "planned",
            "precondition": "The approved fixture is visible",
            "test_data": ["fixture=approved"],
            "action": "Perform the approved action",
            "expected": "The approved result is visible",
            "accessibility_assertions": ["A stable semantic label is exposed"],
            "visual_shot_ids": ["SHOT-001"],
            "implementation_path": (
                "app/src/test/java/com/example/app/HomeScreenTest.kt"
            ),
            "implementation_symbol": "observableBehavior",
        }
        value.update(changes)
        return value

    def add_contract(
        self,
        *,
        slice_id: str = "SCREEN-001",
        spec_id: str = "SPEC-002",
        slug: str = "home",
        tests: list[dict] | None = None,
    ) -> Path:
        slice_type = "screen" if slice_id.startswith("SCREEN-") else "flow"
        directory = self.base / f"{slice_id}-{slug}"
        directory.mkdir(parents=True)
        contract = {
            "artifact_id": self.artifact_id(),
            "artifact_type": "test_case_contract",
            "schema_version": "1.0",
            "version": 1,
            "owner": "test-owner",
            "created_at_state": "implementation",
            "status": "review",
            "source_ids": [spec_id],
            "upstream_sha256": "",
            "approval_required": True,
            "slice_id": slice_id,
            "slice_type": slice_type,
            "spec_id": spec_id,
            "tests": tests or [self.make_test("TEST-001")],
        }
        path = directory / "test-cases.yaml"
        path.write_text(dump_yaml(contract), encoding="utf-8")
        return path

    def add_tdd_cycle(
        self,
        test_id: str,
        *,
        phases: tuple[str, ...] = ("red", "green", "refactor", "verify"),
        spec_id: str = "SPEC-002",
    ) -> None:
        ledger = self.root / "docs" / "verification" / "tdd-ledger.jsonl"
        approvals = self.root / "docs" / "project" / "approvals.jsonl"
        previous = ""
        lines: list[str] = []
        approval_lines: list[str] = []
        for index, phase in enumerate(phases, start=1):
            event = {
                "event_id": f"TDD-{index:03d}",
                "schema_version": "1.0",
                "spec_id": spec_id,
                "ac_ids": ["AC-001"],
                "test_id": test_id,
                "phase": phase,
                "command": ["./gradlew", ":app:testDebugUnitTest"],
                "exit_code": 1 if phase == "red" else 0,
                "failure_kind": "behavior" if phase == "red" else None,
                "started_at": f"2026-11-13T08:0{index}:00+00:00",
                "finished_at": f"2026-11-13T08:0{index}:01+00:00",
                "actor": "Test Engineer",
                "artifact_path": f"docs/verification/tdd-artifacts/{test_id}-{phase}.log",
                "artifact_sha256": "a" * 64,
                "test_declaration_sha256": "b" * 64,
                "contract_sha256": "c" * 64,
                "implementation_path": (
                    f"app/src/test/java/com/example/app/{test_id}Test.kt"
                ),
                "implementation_sha256": "d" * 64,
                "status": "captured",
                "prev_event_sha256": previous,
            }
            event["event_sha256"] = event_hash(event)
            previous = event["event_sha256"]
            lines.append(json.dumps(event, sort_keys=True))
            approval_lines.append(
                json.dumps(
                    {
                        "approval_id": f"APR-{index:03d}",
                        "kind": "tdd_event",
                        "decision": "approved",
                        "subject_id": event["event_id"],
                        "subject_sha256": event["event_sha256"],
                    },
                    sort_keys=True,
                )
            )
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        approvals.write_text("\n".join(approval_lines) + "\n", encoding="utf-8")

    def render(self, generated_at: str = GENERATED_AT) -> dict:
        renderer = self.require_renderer()
        return renderer(self.root, generated_at=generated_at)

    def generated_files(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in sorted((self.root / "docs").rglob("*"))
            if path.is_file()
            and path.suffix in {".md", ".yaml"}
            and path.name in {
                "README.md",
                "artifact-index.yaml",
                "tdd-report.md",
                "index.md",
                "test-cases.md",
            }
        }

    def test_renders_complete_page_and_project_views_with_all_result_categories(
        self,
    ) -> None:
        self.add_spec("SPEC-002", "SCREEN-001", "home")
        self.add_contract(
            tests=[
                self.make_test("TEST-001", planning_status="active"),
                self.make_test(
                    "TEST-002",
                    planning_status="blocked",
                    planning_reason="GAP-001",
                ),
                self.make_test("TEST-003", planning_status="planned"),
                self.make_test(
                    "TEST-004",
                    planning_status="deferred",
                    planning_reason="Not in the approved first release",
                ),
                self.make_test(
                    "TEST-005",
                    planning_status="out_of_scope",
                    planning_reason="Excluded by the approved scope",
                ),
            ]
        )
        self.add_tdd_cycle("TEST-001", phases=("red",))
        self.add_spec("SPEC-003", "FLOW-001", "checkout", title="Checkout flow")
        self.add_contract(
            slice_id="FLOW-001",
            spec_id="SPEC-003",
            slug="checkout",
            tests=[self.make_test("TEST-006")],
        )
        self.add_tdd_cycle("TEST-006", spec_id="SPEC-003")

        result = self.render()

        self.assertEqual(result["generated_at"], GENERATED_AT)
        expected = (
            "docs/README.md",
            "docs/project/artifact-index.yaml",
            "docs/verification/tdd-report.md",
            "docs/verification/test-cases/index.md",
            "docs/verification/test-cases/SCREEN-001-home/test-cases.md",
            "docs/verification/test-cases/FLOW-001-checkout/test-cases.md",
        )
        for relative in expected:
            self.assertTrue((self.root / relative).is_file(), relative)

        categories = (
            "passing",
            "failing",
            "blocked",
            "unverified",
            "planned",
            "deferred",
            "out_of_scope",
        )
        for relative in expected:
            path = self.root / relative
            text = path.read_text(encoding="utf-8")
            for category in categories:
                self.assertIn(category, text, f"{relative}: {category}")
            if relative.endswith(".md"):
                metadata, _ = split_frontmatter(text, path)
                self.assertEqual(metadata["generator"], "render_reports.py")
                self.assertEqual(metadata["generated_at"], GENERATED_AT)
                self.assertEqual(len(metadata["source_sha256"]), 64)
                self.assertEqual(metadata["generated_from"], sorted(metadata["generated_from"]))

        screen = (
            self.root
            / "docs/verification/test-cases/SCREEN-001-home/test-cases.md"
        ).read_text(encoding="utf-8")
        for fact in (
            "TEST-001",
            "AC-001",
            "STATE-001",
            "SHOT-001",
            "HomeScreenTest.kt",
            "observableBehavior",
            "Red",
            "Green",
            "Refactor",
            "Verify",
            "Human review",
            "render_reports.py --project-root",
            "GAP-001",
            "Excluded by the approved scope",
        ):
            self.assertIn(fact, screen)

        index = (
            self.root / "docs/verification/test-cases/index.md"
        ).read_text(encoding="utf-8")
        self.assertIn("SCREEN-001-home/test-cases.md", index)
        self.assertIn("FLOW-001-checkout/test-cases.md", index)

        artifact_index = load_yaml(
            self.root / "docs/project/artifact-index.yaml"
        )
        indexed_paths = {entry["path"] for entry in artifact_index["entries"]}
        self.assertNotIn("docs/project/artifact-index.yaml", indexed_paths)
        self.assertIn("docs/README.md", indexed_paths)
        self.assertIn(
            "docs/verification/test-cases/SCREEN-001-home/test-cases.md",
            indexed_paths,
        )
        for entry in artifact_index["entries"]:
            self.assertEqual(
                entry["sha256"],
                sha256_file(self.root / entry["path"]),
                entry["path"],
            )

    def test_output_is_deterministic_except_for_injected_generation_time(self) -> None:
        self.add_spec("SPEC-002", "SCREEN-001", "home")
        self.add_contract()
        self.render()
        first = self.generated_files()
        first_registry = (
            self.root / "docs/project/artifact-ids.yaml"
        ).read_bytes()

        self.render()
        second = self.generated_files()
        second_registry = (
            self.root / "docs/project/artifact-ids.yaml"
        ).read_bytes()

        self.assertEqual(first, second)
        self.assertEqual(first_registry, second_registry)

        self.render("2026-11-13T09:30:00+00:00")
        third = self.generated_files()
        for relative in first:
            first_text = first[relative].decode("utf-8")
            third_text = third[relative].decode("utf-8")
            first_normalized = re.sub(
                r"(?m)^  sha256: [0-9a-f]{64}$",
                "  sha256: <generated-file-hash>",
                first_text,
            )
            third_normalized = re.sub(
                r"(?m)^  sha256: [0-9a-f]{64}$",
                "  sha256: <generated-file-hash>",
                third_text,
            )
            self.assertEqual(
                first_normalized.replace(GENERATED_AT, "<time>"),
                third_normalized.replace(
                    "2026-11-13T09:30:00+00:00",
                    "<time>",
                ),
                relative,
            )

    def test_source_change_updates_hash_and_artifact_ids_remain_stable(self) -> None:
        self.add_spec("SPEC-002", "SCREEN-001", "home")
        contract_path = self.add_contract()
        self.render()
        page_path = (
            self.root
            / "docs/verification/test-cases/SCREEN-001-home/test-cases.md"
        )
        page_before = split_frontmatter(
            page_path.read_text(encoding="utf-8"),
            page_path,
        )[0]
        registry_before = load_yaml(
            self.root / "docs/project/artifact-ids.yaml"
        )
        ids_before = {
            entry["key"]: entry["artifact_id"] for entry in registry_before["entries"]
        }

        contract = load_yaml(contract_path)
        contract["tests"][0]["title"] = "Changed observable behavior"
        contract_path.write_text(dump_yaml(contract), encoding="utf-8")
        self.render()

        page_after = split_frontmatter(
            page_path.read_text(encoding="utf-8"),
            page_path,
        )[0]
        self.assertNotEqual(page_before["source_sha256"], page_after["source_sha256"])
        self.assertIn("Changed observable behavior", page_path.read_text(encoding="utf-8"))
        registry_after = load_yaml(
            self.root / "docs/project/artifact-ids.yaml"
        )
        ids_after = {
            entry["key"]: entry["artifact_id"] for entry in registry_after["entries"]
        }
        for key, artifact_id in ids_before.items():
            if key in ids_after:
                self.assertEqual(ids_after[key], artifact_id, key)
        all_ids = [entry["artifact_id"] for entry in registry_after["entries"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_duplicate_test_ids_abort_without_writing_reports(self) -> None:
        self.add_spec("SPEC-002", "SCREEN-001", "home")
        self.add_contract()
        self.add_spec("SPEC-003", "FLOW-001", "checkout", title="Checkout")
        self.add_contract(
            slice_id="FLOW-001",
            spec_id="SPEC-003",
            slug="checkout",
        )

        with self.assertRaisesRegex(DesignPactError, "duplicate TEST-001"):
            self.render()

        self.assertFalse((self.root / "docs/README.md").exists())

    def test_unsafe_slice_id_is_rejected_before_any_path_is_written(self) -> None:
        self.add_spec("SPEC-002", "SCREEN-001", "home")
        self.add_contract(slice_id="SCREEN-../../outside")

        with self.assertRaises(DesignPactError):
            self.render()

        self.assertFalse((self.root.parent / "outside").exists())
        self.assertFalse((self.root / "docs/README.md").exists())

    def test_removed_page_report_is_deleted_and_identity_is_tombstoned(self) -> None:
        self.add_spec("SPEC-002", "SCREEN-001", "home")
        self.add_contract()
        self.add_spec("SPEC-003", "FLOW-001", "checkout", title="Checkout")
        removed_contract = self.add_contract(
            slice_id="FLOW-001",
            spec_id="SPEC-003",
            slug="checkout",
            tests=[self.make_test("TEST-002")],
        )
        self.render()
        removed_report = (
            self.root
            / "docs/verification/test-cases/FLOW-001-checkout/test-cases.md"
        )
        self.assertTrue(removed_report.is_file())

        removed_contract.unlink()
        self.render("2026-11-13T10:30:00+00:00")

        self.assertFalse(removed_report.exists())
        registry = load_yaml(self.root / "docs/project/artifact-ids.yaml")
        removed_entry = next(
            entry
            for entry in registry["entries"]
            if entry["path"].endswith(
                "FLOW-001-checkout/test-cases.md"
            )
        )
        self.assertEqual(removed_entry["lifecycle"], "tombstone")
        self.assertEqual(removed_entry["removed_at"], "2026-11-13T10:30:00+00:00")
        index = (
            self.root / "docs/verification/test-cases/index.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("FLOW-001-checkout/test-cases.md", index)

    def test_manual_edit_is_detectable_through_the_artifact_index(self) -> None:
        self.add_spec("SPEC-002", "SCREEN-001", "home")
        self.add_contract()
        self.render()
        page = (
            self.root
            / "docs/verification/test-cases/SCREEN-001-home/test-cases.md"
        )
        relative = page.relative_to(self.root).as_posix()
        artifact_index = load_yaml(
            self.root / "docs/project/artifact-index.yaml"
        )
        recorded = next(
            entry["sha256"]
            for entry in artifact_index["entries"]
            if entry["path"] == relative
        )

        page.write_text(
            page.read_text(encoding="utf-8") + "\nManual edit\n",
            encoding="utf-8",
        )

        self.assertNotEqual(recorded, sha256_file(page))
        self.render()
        self.assertNotIn(
            "Manual edit",
            page.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
