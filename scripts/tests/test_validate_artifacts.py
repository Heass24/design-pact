from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for path in (SCRIPTS_DIR, TESTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common import (  # noqa: E402
    canonical_json,
    event_hash,
    load_approvals,
    load_jsonl,
)
from validate_artifacts import validate_artifacts  # noqa: E402
from validation_fixture import build_validation_fixture  # noqa: E402


class ArtifactValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = build_validation_fixture(Path(self.temporary.name))

    def errors(self, *, require_release: bool = True) -> list[str]:
        errors, _ = validate_artifacts(
            self.root,
            require_release=require_release,
        )
        return errors

    def write_approvals(self, records: list[dict]) -> None:
        path = self.root / "docs/project/approvals.jsonl"
        path.write_text(
            "".join(canonical_json(record) + "\n" for record in records),
            encoding="utf-8",
        )

    def rehash_cycle(self) -> list[dict]:
        path = self.root / "docs/verification/tdd-ledger.jsonl"
        events = load_jsonl(path)
        previous = ""
        for event in events:
            event["prev_event_sha256"] = previous
            event["event_sha256"] = event_hash(event)
            previous = event["event_sha256"]
        path.write_text(
            "".join(canonical_json(event) + "\n" for event in events),
            encoding="utf-8",
        )
        approvals = load_approvals(self.root)
        by_id = {str(event["event_id"]): event for event in events}
        for approval in approvals:
            if approval.get("kind") == "tdd_event":
                event = by_id[str(approval["subject_id"])]
                approval["subject_sha256"] = event["event_sha256"]
        self.write_approvals(approvals)
        return events

    def test_complete_artifacts_pass_release_with_all_professional_approvals(self) -> None:
        errors, summary = validate_artifacts(self.root, require_release=True)
        self.assertEqual(errors, [])
        self.assertEqual(summary["bootstrap_conclusion"], "pass")
        self.assertEqual(summary["state"], "verification")
        self.assertEqual(summary["visual_reports"], 1)
        self.assertEqual(summary["visual_baselines"], 1)
        self.assertIn("approvals_and_tdd", summary["checks_completed"])

    def test_each_professional_approval_is_independent_and_required(self) -> None:
        original = load_approvals(self.root)
        for kind in (
            "scope",
            "design_contract",
            "visual_baseline",
            "exception",
            "release",
        ):
            with self.subTest(kind=kind):
                self.write_approvals(original)
                self.write_approvals(
                    [
                        record
                        for record in original
                        if record.get("kind") != kind
                    ]
                )
                errors = self.errors()
                self.assertTrue(
                    any(f"approved {kind} decision" in error for error in errors),
                    errors,
                )
        self.write_approvals(original)

    def test_artifact_and_tdd_approvals_do_not_replace_professional_signoff(self) -> None:
        records = load_approvals(self.root)
        self.write_approvals(
            [
                record
                for record in records
                if record.get("kind") != "visual_baseline"
            ]
        )
        errors = self.errors()
        self.assertTrue(
            any("approved visual_baseline decision" in error for error in errors),
            errors,
        )

    def test_stale_approval_is_rejected_after_source_change(self) -> None:
        path = self.root / "docs/product/release-scope.yaml"
        path.write_text(
            path.read_text(encoding="utf-8") + "\n# changed after approval\n",
            encoding="utf-8",
        )
        errors = self.errors()
        self.assertTrue(
            any("approval is stale" in error for error in errors),
            errors,
        )

    def test_every_design_contract_source_has_its_own_current_approval(self) -> None:
        path = self.root / "docs/design/token-map.yaml"
        path.write_text(
            path.read_text(encoding="utf-8") + "\n# token changed\n",
            encoding="utf-8",
        )
        errors = self.errors()
        self.assertTrue(
            any("approval is stale" in error for error in errors),
            errors,
        )

    def test_manual_generated_view_edit_is_rejected(self) -> None:
        path = (
            self.root
            / "docs/verification/test-cases/SCREEN-001-home/test-cases.md"
        )
        path.write_text(
            path.read_text(encoding="utf-8") + "\nManual edit.\n",
            encoding="utf-8",
        )
        errors = self.errors()
        self.assertTrue(
            any("hash is stale or modified" in error for error in errors),
            errors,
        )

    def test_canonical_source_change_makes_generated_view_stale(self) -> None:
        path = (
            self.root
            / "docs/verification/test-cases/SCREEN-001-home/test-cases.yaml"
        )
        path.write_text(
            path.read_text(encoding="utf-8") + "\n# canonical source changed\n",
            encoding="utf-8",
        )
        errors = self.errors()
        self.assertTrue(
            any("generated view is stale" in error for error in errors),
            errors,
        )

    def test_missing_human_test_view_and_image_hash_are_rejected(self) -> None:
        test_view = (
            self.root
            / "docs/verification/test-cases/SCREEN-001-home/test-cases.md"
        )
        test_view.unlink()
        image = (
            self.root
            / "docs/design/figma-references/SCREEN-001-home/STATE-001.png"
        )
        image.write_bytes(b"tampered image bytes")
        errors = self.errors()
        self.assertTrue(
            any("test-cases.md is missing" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("declared hash does not match" in error for error in errors),
            errors,
        )

    def test_bootstrap_log_and_command_evidence_are_hashed(self) -> None:
        log = self.root / "docs/verification/bootstrap/android-build.log"
        log.write_text("tampered log\n", encoding="utf-8")
        errors = self.errors(require_release=False)
        self.assertTrue(
            any("command log hash does not match" in error for error in errors),
            errors,
        )

    def test_tdd_missing_red_and_compile_only_red_are_rejected(self) -> None:
        ledger = self.root / "docs/verification/tdd-ledger.jsonl"
        events = load_jsonl(ledger)
        ledger.write_text(
            "".join(canonical_json(event) + "\n" for event in events[1:]),
            encoding="utf-8",
        )
        errors = self.errors()
        self.assertTrue(
            any("latest TDD cycle is not valid" in error for error in errors),
            errors,
        )

    def test_behavior_red_cannot_be_replaced_by_compile_failure(self) -> None:
        ledger = self.root / "docs/verification/tdd-ledger.jsonl"
        events = load_jsonl(ledger)
        events[0]["failure_kind"] = "compile"
        ledger.write_text(
            "".join(canonical_json(event) + "\n" for event in events),
            encoding="utf-8",
        )
        self.rehash_cycle()
        errors = self.errors()
        self.assertTrue(
            any("Red failure_kind must be behavior" in error for error in errors),
            errors,
        )

    def test_missing_visual_report_blocks_release(self) -> None:
        path = (
            self.root
            / "docs/verification/visual-reports/SCREEN-001-home/manifest.yaml"
        )
        path.unlink()
        errors = self.errors()
        self.assertTrue(
            any("SHOT-001: visual report is missing" in error for error in errors),
            errors,
        )

    def test_generic_artifact_approval_cannot_stand_in_for_visual_review(self) -> None:
        path = (
            self.root
            / "docs/verification/visual-reports/SCREEN-001-home/manifest.yaml"
        )
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                "approval_id: APR-003",
                "approval_id: APR-006",
            ),
            encoding="utf-8",
        )
        errors = self.errors()
        self.assertTrue(
            any("requires a visual_baseline approval" in error for error in errors),
            errors,
        )


if __name__ == "__main__":
    unittest.main()
