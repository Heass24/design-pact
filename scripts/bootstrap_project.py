#!/usr/bin/env python3
"""Create a new Design Pact Android Compose project and capture build evidence."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common import (
    DesignPactError,
    allocate_artifact_entry,
    artifact_registry_errors,
    dump_yaml,
    emit_result,
    load_artifact_registry,
    load_yaml,
    now_iso,
    project_relative,
    sha256_file,
    split_frontmatter,
    validate_schema,
)
from preflight import (
    MIN_JDK,
    android_sdk as discover_android_sdk,
    executable,
    gradle_launcher as discover_gradle_launcher,
    java_major,
    target_errors,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
ANDROID_TEMPLATE = SKILL_ROOT / "assets" / "android-compose-template"
DOCS_TEMPLATE = SKILL_ROOT / "assets" / "project-docs-template"
BOOTSTRAP_MANIFEST_ID = "ART-090"
BOOTSTRAP_MANIFEST_RELATIVE = "docs/verification/bootstrap/manifest.yaml"

PACKAGE_NAME = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$"
)
JAVA_KEYWORDS = frozenset(
    {
        "abstract",
        "assert",
        "boolean",
        "break",
        "byte",
        "case",
        "catch",
        "char",
        "class",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "extends",
        "final",
        "finally",
        "float",
        "for",
        "goto",
        "if",
        "implements",
        "import",
        "instanceof",
        "int",
        "interface",
        "long",
        "native",
        "new",
        "package",
        "private",
        "protected",
        "public",
        "return",
        "short",
        "static",
        "strictfp",
        "super",
        "switch",
        "synchronized",
        "this",
        "throw",
        "throws",
        "transient",
        "try",
        "void",
        "volatile",
        "while",
    }
)
KOTLIN_HARD_KEYWORDS = frozenset(
    {
        "as",
        "break",
        "class",
        "continue",
        "do",
        "else",
        "false",
        "for",
        "fun",
        "if",
        "in",
        "interface",
        "is",
        "null",
        "object",
        "package",
        "return",
        "super",
        "this",
        "throw",
        "true",
        "try",
        "typealias",
        "typeof",
        "val",
        "var",
        "when",
        "while",
    }
)
REQUIRED_DIRECTORIES = (
    "docs/project/decisions",
    "docs/design/figma-references",
    "docs/specs/L1",
    "docs/specs/L2",
    "docs/verification/test-cases",
    "docs/verification/tdd-artifacts",
    "docs/verification/visual-reports",
    "docs/verification/baselines",
    "docs/verification/bootstrap",
)


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    output: str
    launch_error: str = ""


CommandRunner = Callable[[list[str], Path, dict[str, str], int], CommandResult]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="New empty project directory.")
    parser.add_argument("--app-name", required=True, help="Gradle root project name.")
    parser.add_argument("--package-name", required=True, help="Android application ID.")
    parser.add_argument(
        "--display-name",
        help="User-visible application name; defaults to --app-name.",
    )
    parser.add_argument(
        "--owner",
        default="project-owner",
        help="Initial human owner recorded in project identity documents.",
    )
    parser.add_argument(
        "--android-sdk",
        help="Android SDK path; discovered locally when omitted.",
    )
    parser.add_argument(
        "--gradle-launcher",
        help="Gradle launcher used once to generate the project wrapper.",
    )
    parser.add_argument(
        "--java",
        help="Java 17+ executable; discovered locally when omitted.",
    )
    parser.add_argument(
        "--command-timeout",
        type=int,
        default=1800,
        help="Per-command timeout in seconds.",
    )
    return parser.parse_args()


def _validate_human_text(value: str, label: str) -> None:
    if not value or value != value.strip():
        raise DesignPactError(f"{label} must be non-empty without surrounding whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise DesignPactError(f"{label} must not contain control characters")


def validate_identity(
    app_name: str,
    package_name: str,
    display_name: str,
    owner: str,
) -> None:
    _validate_human_text(app_name, "app name")
    _validate_human_text(display_name, "display name")
    _validate_human_text(owner, "owner")
    if len(package_name) > 255 or not PACKAGE_NAME.fullmatch(package_name):
        raise DesignPactError(
            "package name must contain at least two dot-separated Java identifiers, "
            "each starting with an ASCII letter"
        )
    invalid_java_segments = [
        segment for segment in package_name.split(".") if segment in JAVA_KEYWORDS
    ]
    if invalid_java_segments:
        raise DesignPactError(
            "package name contains Java keyword segment(s): "
            + ", ".join(sorted(invalid_java_segments))
        )
    invalid_kotlin_segments = [
        segment
        for segment in package_name.split(".")
        if segment in KOTLIN_HARD_KEYWORDS
    ]
    if invalid_kotlin_segments:
        raise DesignPactError(
            "package name contains Kotlin hard keyword segment(s): "
            + ", ".join(sorted(invalid_kotlin_segments))
        )


def kotlin_escape(value: str) -> str:
    escapes = {
        "\\": "\\\\",
        '"': '\\"',
        "$": "\\$",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
        "\b": "\\b",
    }
    return "".join(escapes.get(character, character) for character in value)


def _resolved_target(raw: str) -> Path:
    target = Path(raw).expanduser()
    if target.is_symlink():
        raise DesignPactError(f"{target}: refusing to bootstrap through a symbolic link")
    errors = target_errors(target)
    if errors:
        raise DesignPactError("; ".join(errors))
    return target.resolve()


def _copy_template(
    source_root: Path,
    destination_root: Path,
    package_name: str,
    replacements: dict[str, str],
) -> None:
    package_parts = package_name.split(".")
    destination_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        relative = source.relative_to(source_root)
        destination_parts: list[str] = []
        for part in relative.parts:
            if part == "__PACKAGE_DIR__":
                destination_parts.extend(package_parts)
            else:
                destination_parts.append(part)
        destination = destination_root.joinpath(*destination_parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            destination.write_bytes(data)
            shutil.copymode(source, destination)
            continue
        for placeholder, value in replacements.items():
            text = text.replace(placeholder, value)
        destination.write_text(text, encoding="utf-8")
        shutil.copymode(source, destination)


def _template_replacements(
    *,
    app_name: str,
    package_name: str,
    display_name: str,
    owner: str,
    created_at: str,
) -> dict[str, str]:
    kotlin_app_name = kotlin_escape(app_name)
    kotlin_display_name = kotlin_escape(display_name)
    return {
        "__APP_NAME__": kotlin_app_name,
        "__PACKAGE_NAME__": package_name,
        "__DISPLAY_NAME_XML__": html.escape(display_name, quote=True),
        "__DISPLAY_NAME__": kotlin_display_name,
        "__PROJECT_OWNER__": json.dumps(owner, ensure_ascii=False),
        "__PACKAGE_DIR__": package_name.replace(".", "/"),
        "__CREATED_AT__": created_at,
    }


def _assert_no_identity_placeholders(root: Path) -> None:
    placeholders = (
        "__APP_NAME__",
        "__PACKAGE_NAME__",
        "__DISPLAY_NAME__",
        "__DISPLAY_NAME_XML__",
        "__PROJECT_OWNER__",
        "__PACKAGE_DIR__",
        "__CREATED_AT__",
    )
    errors: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for placeholder in placeholders:
            if placeholder in text:
                errors.append(f"{path}: unresolved template placeholder {placeholder}")
    if errors:
        raise DesignPactError("; ".join(errors))


def _write_local_properties(root: Path, android_sdk: Path) -> None:
    escaped_sdk = str(android_sdk).replace("\\", "\\\\")
    (root / "local.properties").write_text(
        f"sdk.dir={escaped_sdk}\n",
        encoding="utf-8",
    )


def _ensure_directories(root: Path) -> None:
    for relative in REQUIRED_DIRECTORIES:
        directory = root / relative
        directory.mkdir(parents=True, exist_ok=True)
        if not any(directory.iterdir()):
            (directory / ".gitkeep").write_text("", encoding="utf-8")


def _metadata_artifact(path: Path) -> tuple[str, str] | None:
    try:
        if path.suffix in {".yaml", ".yml"}:
            value = load_yaml(path)
        elif path.suffix == ".md":
            value, _ = split_frontmatter(path.read_text(encoding="utf-8"), path)
        else:
            return None
    except (DesignPactError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    artifact_id = value.get("artifact_id")
    artifact_type = value.get("artifact_type")
    if isinstance(artifact_id, str) and isinstance(artifact_type, str):
        return artifact_id, artifact_type
    return None


def register_document_artifacts(root: Path) -> dict[str, Any]:
    registry = load_artifact_registry(root)
    for path in sorted((root / "docs").rglob("*")):
        if not path.is_file() or path.suffix not in {".yaml", ".yml", ".md"}:
            continue
        metadata = _metadata_artifact(path)
        if metadata is None:
            continue
        artifact_id, artifact_type = metadata
        relative = project_relative(path, root)
        allocate_artifact_entry(
            registry,
            key=relative,
            path=relative,
            artifact_type=artifact_type,
            preferred_id=artifact_id,
        )
    registry_path = root / "docs/project/artifact-ids.yaml"
    registry_path.write_text(dump_yaml(registry), encoding="utf-8")
    errors = artifact_registry_errors(root)
    if errors:
        raise DesignPactError("; ".join(errors))
    return registry


def _execute_process(
    argv: list[str],
    cwd: Path,
    environment: dict[str, str],
    timeout: int,
) -> CommandResult:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return CommandResult(None, str(output), f"command timed out after {timeout}s")
    except OSError as exc:
        return CommandResult(None, "", f"could not launch command: {exc}")
    return CommandResult(result.returncode, result.stdout or "")


def _recorded_command(
    *,
    name: str,
    argv: list[str],
    cwd: Path,
    environment: dict[str, str],
    log_relative: str,
    timeout: int,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    started_at = now_iso()
    started_monotonic = time.monotonic()
    result = command_runner(argv, cwd, environment, timeout)
    duration = round(time.monotonic() - started_monotonic, 3)
    finished_at = now_iso()
    log_path = cwd / log_relative
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_content = result.output
    if result.launch_error:
        if log_content and not log_content.endswith("\n"):
            log_content += "\n"
        log_content += f"[design-pact] {result.launch_error}\n"
    log_path.write_text(log_content, encoding="utf-8")
    record: dict[str, Any] = {
        "name": name,
        "argv": argv,
        "status": "passed" if result.exit_code == 0 else "failed",
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration,
        "log_path": log_relative,
        "log_sha256": sha256_file(log_path),
    }
    if result.exit_code is not None:
        record["exit_code"] = result.exit_code
    if result.launch_error:
        record["launch_error"] = result.launch_error
    return record


def _not_run_command(name: str, argv: list[str], reason: str) -> dict[str, Any]:
    return {
        "name": name,
        "argv": argv,
        "status": "not_run",
        "launch_error": reason,
    }


def _tool_environment(
    *,
    java: Path,
    android_sdk: Path,
    gradle: Path,
) -> tuple[dict[str, str], str | None]:
    environment = dict(os.environ)
    environment["ANDROID_HOME"] = str(android_sdk)
    environment["ANDROID_SDK_ROOT"] = str(android_sdk)
    java_home: str | None = None
    if java.name == "java" and java.parent.name == "bin":
        java_home = str(java.parent.parent)
    elif os.environ.get("JAVA_HOME"):
        java_home = os.environ["JAVA_HOME"]
    if java_home:
        environment["JAVA_HOME"] = java_home
    path_entries = [
        str(java.parent),
        str(android_sdk / "platform-tools"),
        str(gradle.parent),
    ]
    existing_path = environment.get("PATH", "")
    environment["PATH"] = os.pathsep.join(path_entries + ([existing_path] if existing_path else []))
    return environment, java_home


def _write_bootstrap_manifest(
    root: Path,
    *,
    app_name: str,
    package_name: str,
    display_name: str,
    owner: str,
    created_at: str,
    java: Path,
    android_sdk: Path,
    gradle: Path,
    commands: list[dict[str, Any]],
    conclusion: str,
) -> None:
    manifest = {
        "artifact_id": BOOTSTRAP_MANIFEST_ID,
        "artifact_type": "bootstrap_manifest",
        "schema_version": "1.0",
        "version": 1,
        "owner": "bootstrap_project.py",
        "created_at_state": "discovery",
        "status": "draft",
        "source_ids": [],
        "upstream_sha256": "",
        "approval_required": False,
        "created_at": created_at,
        "project": {
            "app_name": app_name,
            "package_name": package_name,
            "display_name": display_name,
            "state": "discovery",
        },
        "toolchain": {
            "java": str(java),
            "android_sdk": str(android_sdk),
            "gradle": str(gradle),
        },
        "commands": commands,
        "conclusion": conclusion,
    }
    manifest_path = root / BOOTSTRAP_MANIFEST_RELATIVE
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(dump_yaml(manifest), encoding="utf-8")
    schema = json.loads(
        (root / "schemas/bootstrap-manifest.schema.json").read_text(encoding="utf-8")
    )
    schema_errors = validate_schema(manifest, schema, str(manifest_path))
    if schema_errors:
        raise DesignPactError("; ".join(schema_errors))


def bootstrap_project(
    *,
    target: Path,
    app_name: str,
    package_name: str,
    display_name: str,
    owner: str,
    java: Path,
    android_sdk: Path,
    gradle: Path,
    timeout: int,
    command_runner: CommandRunner = _execute_process,
) -> tuple[list[str], dict[str, Any]]:
    validate_identity(app_name, package_name, display_name, owner)
    if timeout <= 0:
        raise DesignPactError("command timeout must be positive")
    if not ANDROID_TEMPLATE.is_dir() or not DOCS_TEMPLATE.is_dir():
        raise DesignPactError("Design Pact project templates are missing")
    resolved_target = _resolved_target(str(target))
    if not java.is_file() or not os.access(java, os.X_OK):
        raise DesignPactError(f"{java}: Java executable is unavailable")
    detected_java = java_major(str(java))
    if detected_java is None or detected_java < MIN_JDK:
        raise DesignPactError(f"JDK {MIN_JDK}+ required; found {detected_java or 'unknown'}")
    if not (android_sdk / "platforms" / "android-35").is_dir():
        raise DesignPactError(
            f"{android_sdk}: Android SDK platform android-35 is unavailable"
        )
    if not gradle.is_file() or not os.access(gradle, os.X_OK):
        raise DesignPactError(f"{gradle}: Gradle launcher is unavailable")

    created_at = now_iso()
    resolved_target.mkdir(parents=True, exist_ok=True)
    replacements = _template_replacements(
        app_name=app_name,
        package_name=package_name,
        display_name=display_name,
        owner=owner,
        created_at=created_at,
    )
    _copy_template(
        ANDROID_TEMPLATE,
        resolved_target,
        package_name,
        replacements,
    )
    _copy_template(
        DOCS_TEMPLATE,
        resolved_target,
        package_name,
        replacements,
    )
    _ensure_directories(resolved_target)
    _write_local_properties(resolved_target, android_sdk)
    _assert_no_identity_placeholders(resolved_target)

    # Register the document skeleton before build evidence is appended.
    register_document_artifacts(resolved_target)

    environment, _ = _tool_environment(
        java=java,
        android_sdk=android_sdk,
        gradle=gradle,
    )
    wrapper_argv = [str(gradle), "wrapper", "--gradle-version", "8.9"]
    build_argv = [
        "./gradlew",
        ":app:assembleDebug",
        ":app:testDebugUnitTest",
    ]
    commands = [
        _recorded_command(
            name="generate-gradle-wrapper",
            argv=wrapper_argv,
            cwd=resolved_target,
            environment=environment,
            log_relative="docs/verification/bootstrap/gradle-wrapper.log",
            timeout=timeout,
            command_runner=command_runner,
        )
    ]
    if commands[0]["status"] == "passed":
        commands.append(
            _recorded_command(
                name="assemble-debug-and-unit-test",
                argv=build_argv,
                cwd=resolved_target,
                environment=environment,
                log_relative="docs/verification/bootstrap/android-build.log",
                timeout=timeout,
                command_runner=command_runner,
            )
        )
    else:
        commands.append(
            _not_run_command(
                "assemble-debug-and-unit-test",
                build_argv,
                "Gradle wrapper generation failed",
            )
        )

    build_errors: list[str] = []
    for command in commands:
        if command["status"] == "failed":
            build_errors.append(
                f"{command['name']} failed"
                + (
                    f" with exit code {command['exit_code']}"
                    if "exit_code" in command
                    else ""
                )
                + (
                    f": {command['launch_error']}"
                    if command.get("launch_error")
                    else f"; inspect {command['log_path']}"
                )
            )
        elif command["status"] == "not_run":
            build_errors.append(
                f"{command['name']} was not run: {command['launch_error']}"
            )
    conclusion = "pass" if not build_errors else "fail"
    _write_bootstrap_manifest(
        resolved_target,
        app_name=app_name,
        package_name=package_name,
        display_name=display_name,
        owner=owner,
        created_at=created_at,
        java=java,
        android_sdk=android_sdk,
        gradle=gradle,
        commands=commands,
        conclusion=conclusion,
    )
    register_document_artifacts(resolved_target)
    state = load_yaml(resolved_target / "docs/project/state.yaml")
    if not isinstance(state, dict) or state.get("state") != "discovery":
        raise DesignPactError("bootstrap must leave the project in discovery state")
    summary = {
        "project_root": str(resolved_target),
        "app_name": app_name,
        "package_name": package_name,
        "display_name": display_name,
        "state": "discovery",
        "bootstrap_build": conclusion,
        "bootstrap_manifest": BOOTSTRAP_MANIFEST_RELATIVE,
        "commands": [
            {
                "name": command["name"],
                "argv": command["argv"],
                "status": command["status"],
                **(
                    {"exit_code": command["exit_code"]}
                    if "exit_code" in command
                    else {}
                ),
            }
            for command in commands
        ],
    }
    return build_errors, summary


def main() -> int:
    args = parse_args()
    target = Path(args.target).expanduser()
    java = Path(args.java).expanduser() if args.java else executable("java")
    if java is None:
        return emit_result(["JDK not found; set JAVA_HOME or install JDK 17+"])
    android_sdk = (
        Path(args.android_sdk).expanduser()
        if args.android_sdk
        else discover_android_sdk()
    )
    if android_sdk is None:
        return emit_result(
            ["Android SDK not found; set ANDROID_HOME or install SDK platform 35"]
        )
    gradle = (
        Path(args.gradle_launcher).expanduser()
        if args.gradle_launcher
        else discover_gradle_launcher()
    )
    if gradle is None:
        return emit_result(
            ["Gradle launcher not found and no cached Gradle distribution exists"]
        )
    display_name = args.display_name if args.display_name is not None else args.app_name
    errors, summary = bootstrap_project(
        target=target,
        app_name=args.app_name,
        package_name=args.package_name,
        display_name=display_name,
        owner=args.owner,
        java=Path(java) if not isinstance(java, Path) else java,
        android_sdk=android_sdk,
        gradle=gradle,
        timeout=args.command_timeout,
    )
    return emit_result(errors, summary)


if __name__ == "__main__":
    from common import run_main

    run_main(main)
