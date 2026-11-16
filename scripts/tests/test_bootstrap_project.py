from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from bootstrap_project import (  # noqa: E402
    BOOTSTRAP_MANIFEST_ID,
    CommandResult,
    _resolved_target,
    bootstrap_project,
    kotlin_escape,
    register_document_artifacts,
    validate_identity,
)
from common import (  # noqa: E402
    DesignPactError,
    load_yaml,
    sha256_file,
    split_frontmatter,
    validate_schema,
)


class BootstrapProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name).resolve()
        self.project = self.workspace / "project"

        self.java = self.workspace / "bin" / "java"
        self.java.parent.mkdir(parents=True)
        self.java.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.java.chmod(0o755)

        self.android_sdk = self.workspace / "android-sdk"
        (self.android_sdk / "platforms" / "android-35").mkdir(parents=True)

        self.gradle = self.workspace / "gradle" / "bin" / "gradle"
        self.gradle.parent.mkdir(parents=True)
        self.gradle.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.gradle.chmod(0o755)

    def successful_runner(
        self,
        argv: list[str],
        cwd: Path,
        environment: dict[str, str],
        timeout: int,
    ) -> CommandResult:
        del cwd, environment, timeout
        return CommandResult(0, f"command passed: {' '.join(argv)}\n")

    def invoke(
        self,
        *,
        target: Path | None = None,
        app_name: str = "Example Pact",
        package_name: str = "com.example.pact",
        display_name: str = "Example Pact",
        owner: str = "Project Owner",
        command_runner=None,
    ):
        runner = command_runner or self.successful_runner
        with patch("bootstrap_project.java_major", return_value=17):
            return bootstrap_project(
                target=target or self.project,
                app_name=app_name,
                package_name=package_name,
                display_name=display_name,
                owner=owner,
                java=self.java,
                android_sdk=self.android_sdk,
                gradle=self.gradle,
                timeout=30,
                command_runner=runner,
            )

    def bootstrap_schema(self, project: Path) -> dict:
        return json.loads(
            (project / "schemas" / "bootstrap-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )

    def bootstrap_manifest(self, project: Path) -> dict:
        value = load_yaml(
            project / "docs" / "verification" / "bootstrap" / "manifest.yaml"
        )
        self.assertIsInstance(value, dict)
        return value

    def test_rejects_non_directory_non_empty_root_home_and_symlink_targets(self) -> None:
        regular_file = self.workspace / "regular-file"
        regular_file.write_text("not a directory", encoding="utf-8")
        non_empty = self.workspace / "non-empty"
        non_empty.mkdir()
        (non_empty / "existing.txt").write_text("existing", encoding="utf-8")
        real_directory = self.workspace / "real-directory"
        real_directory.mkdir()
        symlink = self.workspace / "symlink"
        symlink.symlink_to(real_directory, target_is_directory=True)

        for target in (
            regular_file,
            non_empty,
            Path(Path.cwd().anchor),
            Path.home(),
            symlink,
        ):
            with self.subTest(target=str(target)):
                with self.assertRaises(DesignPactError):
                    self.invoke(target=target)

    def test_resolved_target_returns_an_absolute_empty_destination(self) -> None:
        self.assertEqual(
            _resolved_target(str(self.project)),
            self.project.resolve(),
        )
        self.assertFalse(self.project.exists())

    def test_rejects_invalid_package_and_java_or_kotlin_keywords(self) -> None:
        invalid_packages = (
            "com",
            "one",
            "com.1example.app",
            "com.example.class",
            "com.example.when",
        )
        for package_name in invalid_packages:
            with self.subTest(package_name=package_name):
                with self.assertRaises(DesignPactError):
                    validate_identity(
                        "Example",
                        package_name,
                        "Example",
                        "Project Owner",
                    )

        with self.assertRaisesRegex(DesignPactError, "Java keyword"):
            validate_identity(
                "Example",
                "com.example.class",
                "Example",
                "Project Owner",
            )
        with self.assertRaisesRegex(DesignPactError, "Kotlin hard keyword"):
            validate_identity(
                "Example",
                "com.example.when",
                "Example",
                "Project Owner",
            )

    def test_creates_documented_android_sources_under_the_real_package_path(self) -> None:
        errors, summary = self.invoke(
            package_name="com.example.special_app",
        )
        self.assertEqual(errors, [])
        self.assertEqual(summary["bootstrap_build"], "pass")
        self.assertEqual(summary["state"], "discovery")

        package_root = (
            self.project
            / "app"
            / "src"
            / "main"
            / "java"
            / "com"
            / "example"
            / "special_app"
        )
        self.assertTrue((package_root / "MainActivity.kt").is_file())
        self.assertTrue((package_root / "AppIdentity.kt").is_file())
        test_root = (
            self.project
            / "app"
            / "src"
            / "test"
            / "java"
            / "com"
            / "example"
            / "special_app"
        )
        self.assertTrue((test_root / "AppIdentityTest.kt").is_file())
        self.assertFalse(any(self.project.rglob("__PACKAGE_DIR__")))

        for path in self.project.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            self.assertNotIn("__PACKAGE_DIR__", text, str(path))
            self.assertNotIn("__PROJECT_OWNER__", text, str(path))

    def test_replaces_identity_and_escapes_gradle_kotlin_and_xml_text(self) -> None:
        app_name = 'Pact "Studio" $cash \\ lab'
        display_name = "A&B <Pact> 'Live' \"Now\" $cash"
        owner = 'Ada "Ace" Lovelace'

        errors, _ = self.invoke(
            app_name=app_name,
            display_name=display_name,
            owner=owner,
        )
        self.assertEqual(errors, [])

        escaped_app_name = kotlin_escape(app_name)
        settings = (self.project / "settings.gradle.kts").read_text(encoding="utf-8")
        self.assertIn(f'rootProject.name = "{escaped_app_name}"', settings)

        identity_source = (
            self.project
            / "app"
            / "src"
            / "main"
            / "java"
            / "com"
            / "example"
            / "pact"
            / "AppIdentity.kt"
        ).read_text(encoding="utf-8")
        self.assertIn(
            f'const val DISPLAY_NAME = "{kotlin_escape(display_name)}"',
            identity_source,
        )

        strings_root = ElementTree.parse(
            self.project
            / "app"
            / "src"
            / "main"
            / "res"
            / "values"
            / "strings.xml"
        ).getroot()
        self.assertEqual(
            strings_root.find("string").text,
            display_name,
        )

        state = load_yaml(self.project / "docs" / "project" / "state.yaml")
        self.assertEqual(state["owner"], owner)
        charter_text = (
            self.project / "docs" / "product" / "product-charter.md"
        ).read_text(encoding="utf-8")
        charter_metadata, _ = split_frontmatter(charter_text, Path("charter"))
        self.assertEqual(charter_metadata["owner"], owner)

        decision_template = (
            self.project / "templates" / "DEC-###-<slug>.md"
        ).read_text(encoding="utf-8")
        decision_metadata, _ = split_frontmatter(
            decision_template, Path("decision-template")
        )
        self.assertEqual(decision_metadata["owner"], "project-owner")

    def test_successful_bootstrap_registers_unique_stable_artifact_ids(self) -> None:
        errors, _ = self.invoke()
        self.assertEqual(errors, [])

        registry_path = self.project / "docs" / "project" / "artifact-ids.yaml"
        registry_before = load_yaml(registry_path)
        entries = registry_before["entries"]
        ids = [entry["artifact_id"] for entry in entries]
        paths = [entry["path"] for entry in entries]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn(BOOTSTRAP_MANIFEST_ID, ids)

        manifest_entry = next(
            entry
            for entry in entries
            if entry["path"] == "docs/verification/bootstrap/manifest.yaml"
        )
        self.assertEqual(manifest_entry["artifact_id"], BOOTSTRAP_MANIFEST_ID)

        register_document_artifacts(self.project)
        registry_after = load_yaml(registry_path)
        self.assertEqual(registry_after, registry_before)

    def test_successful_bootstrap_leaves_discovery_state_and_valid_build_evidence(
        self,
    ) -> None:
        errors, summary = self.invoke()
        self.assertEqual(errors, [])

        state = load_yaml(self.project / "docs" / "project" / "state.yaml")
        self.assertEqual(state["state"], "discovery")
        self.assertEqual(summary["state"], "discovery")

        manifest = self.bootstrap_manifest(self.project)
        self.assertEqual(manifest["conclusion"], "pass")
        self.assertEqual(manifest["project"]["state"], "discovery")
        self.assertEqual(
            [command["status"] for command in manifest["commands"]],
            ["passed", "passed"],
        )
        self.assertEqual(
            validate_schema(
                manifest,
                self.bootstrap_schema(self.project),
                "bootstrap manifest",
            ),
            [],
        )
        for command in manifest["commands"]:
            log_path = self.project / command["log_path"]
            self.assertTrue(log_path.is_file())
            self.assertEqual(command["log_sha256"], sha256_file(log_path))

    def test_failed_build_preserves_exit_code_log_and_hash(self) -> None:
        def failing_build_runner(
            argv: list[str],
            cwd: Path,
            environment: dict[str, str],
            timeout: int,
        ) -> CommandResult:
            del cwd, environment, timeout
            if argv[0] == "./gradlew":
                return CommandResult(7, "unit test failed\n")
            return CommandResult(0, "wrapper generated\n")

        errors, summary = self.invoke(command_runner=failing_build_runner)
        self.assertTrue(errors)
        self.assertEqual(summary["bootstrap_build"], "fail")

        manifest = self.bootstrap_manifest(self.project)
        build = manifest["commands"][1]
        self.assertEqual(manifest["conclusion"], "fail")
        self.assertEqual(build["status"], "failed")
        self.assertEqual(build["exit_code"], 7)
        log_path = self.project / build["log_path"]
        self.assertEqual(log_path.read_text(encoding="utf-8"), "unit test failed\n")
        self.assertEqual(build["log_sha256"], sha256_file(log_path))
        self.assertEqual(
            validate_schema(
                manifest,
                self.bootstrap_schema(self.project),
                "bootstrap manifest",
            ),
            [],
        )

    def test_wrapper_launch_failure_marks_build_not_run_and_remains_schema_valid(
        self,
    ) -> None:
        calls: list[list[str]] = []

        def wrapper_failure_runner(
            argv: list[str],
            cwd: Path,
            environment: dict[str, str],
            timeout: int,
        ) -> CommandResult:
            del cwd, environment, timeout
            calls.append(argv)
            return CommandResult(None, "", "could not launch command: missing runner")

        errors, summary = self.invoke(command_runner=wrapper_failure_runner)
        self.assertEqual(len(calls), 1)
        self.assertTrue(errors)
        self.assertEqual(summary["bootstrap_build"], "fail")

        manifest = self.bootstrap_manifest(self.project)
        wrapper, build = manifest["commands"]
        self.assertEqual(wrapper["status"], "failed")
        self.assertNotIn("exit_code", wrapper)
        self.assertEqual(
            wrapper["launch_error"],
            "could not launch command: missing runner",
        )
        self.assertEqual(build["status"], "not_run")
        self.assertEqual(build["launch_error"], "Gradle wrapper generation failed")
        self.assertNotIn("log_path", build)
        self.assertEqual(
            validate_schema(
                manifest,
                self.bootstrap_schema(self.project),
                "bootstrap manifest",
            ),
            [],
        )

    @unittest.skipUnless(os.name != "nt", "symbolic-link semantics differ on Windows")
    def test_symlink_rejection_does_not_create_the_project(self) -> None:
        real_directory = self.workspace / "real"
        real_directory.mkdir()
        link = self.workspace / "project-link"
        link.symlink_to(real_directory, target_is_directory=True)
        with self.assertRaisesRegex(DesignPactError, "symbolic link"):
            self.invoke(target=link)
        self.assertEqual(list(real_directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
