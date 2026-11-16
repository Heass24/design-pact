from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from validate_skill import validate_skill  # noqa: E402


class ValidateSkillTests(unittest.TestCase):
    def test_temporary_end_to_end_release_and_negative_checks_pass(self) -> None:
        errors, summary = validate_skill()
        self.assertEqual(errors, [])
        self.assertTrue(summary["simulated_environment"])
        self.assertTrue(summary["complete_release_fixture"])
        self.assertEqual(summary["approval_isolation"], "checked")
        self.assertIn("does not prove", " ".join(summary["limitations"]))


if __name__ == "__main__":
    unittest.main()
