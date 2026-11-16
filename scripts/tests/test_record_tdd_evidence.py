from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common import (  # noqa: E402
    DesignPactError,
    canonical_json,
    dump_yaml,
    event_hash,
    load_jsonl,
    load_yaml,
)
from record_tdd_evidence import record_evidence  # noqa: E402


TEMPLATE = SCRIPTS_DIR.parent / "assets" / "project-docs-template"
TEST_RELATIVE = (
    "app/src/test/java/com/example/pact/HomeScreenTest.kt"
)


class RecordTddEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "project"
        shutil.copytree(TEMPLATE, self.root)

        contract_dir = (
            self.root
            / "docs"
            / "verification"
            / "test-cases"
            / "SCREEN-001-home"
        )
        contract_dir.mkdir(parents=True)
        contract = load_yaml(
            self.root / "templates" / "test-cases.yaml"
        )
        contract["source_ids"] = ["SPEC-002"]
        contract["tests"][0]["implementation_path"] = TEST_RELATIVE
        dump = dump_yaml(contract)
        (contract_dir / "test-cases.yaml").write_text(dump, encoding="utf-8")

        test_path = self.root / TEST_RELATIVE
        test_path.parent.mkdir(parents=True)
        test_path.write_text(
            "package com.example.pact\n\n"
            "class HomeScreenTest {\n"
            "    // DESIGN_PACT: TEST-001 => AC-001\n"
            "    @Test\n"
            "    fun observableBehavior() {\n"
            "        println(\"observable behavior\")\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

    def invoke(
        self,
        *,
        phase: str,
        exit_code: int = 0,
        failure_kind: str | None = None,
        command: list[str] | None = None,
    ):
        command = command or [
            sys.executable,
            "-c",
            f"raise SystemExit({exit_code})",
        ]
        return record_evidence(
            project_root=self.root,
            spec_id="SPEC-002",
            test_id="TEST-001",
            ac_ids=["AC-001"],
            phase=phase,
            command=command,
            failure_kind=failure_kind,
            actor="test-runner",
            timeout=30,
        )

    def ledger(self) -> list[dict]:
        return load_jsonl(
            self.root / "docs" / "verification" / "tdd-ledger.jsonl"
        )

    def test_red_and_green_append_valid_hash_chain_and_complete_logs(self) -> None:
        _, red = self.invoke(
            phase="red",
            exit_code=3,
            failure_kind="behavior",
        )
        _, green = self.invoke(phase="green")
        events = self.ledger()

        self.assertEqual([event["phase"] for event in events], ["red", "green"])
        self.assertEqual(events[0]["exit_code"], 3)
        self.assertEqual(events[0]["failure_kind"], "behavior")
        self.assertEqual(events[1]["prev_event_sha256"], red["event_sha256"])
        self.assertEqual(events[1]["event_sha256"], green["event_sha256"])
        self.assertEqual(events[0]["event_sha256"], event_hash(events[0]))
        log = (self.root / events[0]["artifact_path"]).read_text(encoding="utf-8")
        self.assertIn("exit_code: 3", log)
        self.assertIn("--- stderr ---", log)

    def test_commands_are_arguments_and_never_interpreted_by_a_shell(self) -> None:
        marker = self.root / "shell-injection-marker"
        payload = f"$(touch {marker}); `touch {marker}`"
        self.invoke(
            phase="green",
            command=[sys.executable, "-c", "import sys; print(sys.argv[1])", payload],
        )
        self.assertFalse(marker.exists())

    def test_compile_failure_is_not_valid_red_and_does_not_write_ledger(self) -> None:
        with self.assertRaisesRegex(DesignPactError, "failure-kind behavior"):
            self.invoke(
                phase="red",
                exit_code=1,
                failure_kind="compile",
            )
        self.assertEqual(self.ledger(), [])

    def test_non_red_failure_does_not_write_ledger_or_log(self) -> None:
        with self.assertRaisesRegex(DesignPactError, "must pass"):
            self.invoke(phase="green", exit_code=1)
        self.assertEqual(self.ledger(), [])
        self.assertEqual(
            list((self.root / "docs" / "verification" / "tdd-artifacts").glob("*.log")),
            [],
        )

    def test_unknown_executable_does_not_write_evidence(self) -> None:
        with self.assertRaisesRegex(DesignPactError, "does not exist"):
            self.invoke(
                phase="green",
                command=[str(self.root / "missing-command")],
            )
        self.assertEqual(self.ledger(), [])

    def test_tampered_prior_event_blocks_new_evidence(self) -> None:
        self.invoke(phase="red", exit_code=1, failure_kind="behavior")
        ledger_path = (
            self.root / "docs" / "verification" / "tdd-ledger.jsonl"
        )
        events = self.ledger()
        events[0]["exit_code"] = 9
        ledger_path.write_text(canonical_json(events[0]) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(DesignPactError, "event hash is invalid"):
            self.invoke(phase="green")

    def test_ac_mismatch_is_rejected_before_execution(self) -> None:
        marker = self.root / "should-not-run"
        with self.assertRaisesRegex(DesignPactError, "must exactly match"):
            record_evidence(
                project_root=self.root,
                spec_id="SPEC-002",
                test_id="TEST-001",
                ac_ids=["AC-002"],
                phase="green",
                command=[sys.executable, "-c", f"open('{marker}', 'w').close()"],
                failure_kind=None,
                actor="test-runner",
                timeout=30,
            )
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
