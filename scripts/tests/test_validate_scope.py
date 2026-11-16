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

from common import dump_yaml, load_yaml  # noqa: E402
from validate_scope import validate_scope  # noqa: E402
from validation_fixture import build_validation_fixture  # noqa: E402


class ScopeValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = build_validation_fixture(Path(self.temporary.name))

    def write_yaml(self, relative: str, value: dict) -> None:
        path = self.root / relative
        path.write_text(dump_yaml(value), encoding="utf-8")

    def errors(self, *, require_release: bool = True) -> list[str]:
        errors, _ = validate_scope(
            self.root,
            require_release=require_release,
        )
        return errors

    def test_complete_scope_has_bidirectional_trace_and_passes_release(self) -> None:
        errors, summary = validate_scope(self.root, require_release=True)
        self.assertEqual(errors, [])
        self.assertEqual(summary["journeys"], 1)
        self.assertEqual(summary["slices"], 1)
        self.assertEqual(summary["states"], 1)
        self.assertEqual(summary["tests"], 1)

    def test_duplicate_id_is_rejected(self) -> None:
        path = self.root / "docs/product/journey-map.yaml"
        value = load_yaml(path)
        value["journeys"].append(dict(value["journeys"][0]))
        self.write_yaml("docs/product/journey-map.yaml", value)
        self.assertTrue(
            any("duplicate journey ID JRN-001" in error for error in self.errors()),
            self.errors(),
        )

    def test_dangling_or_nonreciprocal_reference_is_rejected(self) -> None:
        path = self.root / "docs/product/feature-map.yaml"
        value = load_yaml(path)
        value["features"][0]["journey_id"] = "JRN-002"
        self.write_yaml("docs/product/feature-map.yaml", value)
        errors = self.errors()
        self.assertTrue(any("missing object JRN-002" in error for error in errors), errors)
        self.assertTrue(any("not reciprocal" in error for error in errors), errors)

    def test_missing_l2_breaks_the_covered_trace(self) -> None:
        (
            self.root
            / "docs/specs/L2/SPEC-002-SCREEN-001-home.md"
        ).unlink()
        errors = self.errors()
        self.assertTrue(
            any("covered slice has no L2 specification" in error for error in errors),
            errors,
        )

    def test_missing_test_or_human_test_view_is_rejected(self) -> None:
        (
            self.root
            / "docs/verification/test-cases/SCREEN-001-home/test-cases.md"
        ).unlink()
        errors = self.errors()
        self.assertTrue(
            any("test-cases.md is missing" in error for error in errors),
            errors,
        )

    def test_coverage_release_and_exclusions_must_match(self) -> None:
        path = self.root / "docs/product/coverage-matrix.yaml"
        value = load_yaml(path)
        value["objects"][-1]["status"] = "out_of_scope"
        value["objects"][-1]["rationale"] = "The approved state is excluded."
        self.write_yaml("docs/product/coverage-matrix.yaml", value)
        errors = self.errors(require_release=False)
        self.assertTrue(any("exclusions: missing references STATE-001" in error for error in errors), errors)

    def test_blocked_coverage_gap_and_state_blockers_must_agree(self) -> None:
        coverage_path = self.root / "docs/product/coverage-matrix.yaml"
        coverage = load_yaml(coverage_path)
        coverage["objects"][-1]["status"] = "blocked"
        coverage["objects"][-1]["rationale"] = "Copy is missing."
        self.write_yaml("docs/product/coverage-matrix.yaml", coverage)
        gaps_path = self.root / "docs/design/gaps.yaml"
        gaps = load_yaml(gaps_path)
        gaps["gaps"] = [
            {
                "id": "GAP-001",
                "blocker_class": "blocked_by_content",
                "affected_ids": ["STATE-001"],
                "owner": "Content Owner",
                "required_input": "Approved empty-state copy",
                "recovery_condition": "Copy is approved and bound to STATE-001",
                "status": "open",
            }
        ]
        self.write_yaml("docs/design/gaps.yaml", gaps)
        errors = self.errors(require_release=False)
        self.assertTrue(any("blockers: missing references GAP-001" in error for error in errors), errors)

        state_path = self.root / "docs/project/state.yaml"
        state = load_yaml(state_path)
        state["blockers"] = [
            {
                "id": "GAP-001",
                "reason": "Copy is missing.",
                "owner": "Content Owner",
                "required_input": "Approved empty-state copy",
                "recovery_condition": "Copy is approved and bound to STATE-001",
            }
        ]
        self.write_yaml("docs/project/state.yaml", state)
        errors = self.errors(require_release=False)
        self.assertFalse(any("blockers:" in error for error in errors), errors)

    def test_release_requires_a_passing_scope_audit(self) -> None:
        path = self.root / "docs/verification/scope-audit.md"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("conclusion: pass", "conclusion: unverified"),
            encoding="utf-8",
        )
        errors = self.errors()
        self.assertTrue(
            any("must conclude 'pass'" in error for error in errors),
            errors,
        )


if __name__ == "__main__":
    unittest.main()
