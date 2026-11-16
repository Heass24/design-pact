#!/usr/bin/env python3
"""Check the local Android and Figma-evidence prerequisites."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from common import DesignPactError, emit_result, load_yaml, run_main, sha256_file


MIN_PYTHON = (3, 10)
MIN_JDK = 17
STRUCTURED_FIGMA_SOURCES = frozenset({"figma-mcp", "figma-rest", "structured-node"})
PLACEHOLDER_VALUE = re.compile(
    r"(?:^|[\s_.:/-])(?:figma_file_key|figma_node_id|figma_revision|todo|tbd|"
    r"placeholder|unknown)(?:$|[\s_.:/-])",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        required=True,
        help="New Android project directory; it must be absent or empty.",
    )
    parser.add_argument(
        "--figma-evidence",
        help="Structured Figma manifest or evidence directory to validate.",
    )
    parser.add_argument(
        "--require-figma-evidence",
        action="store_true",
        help="Fail unless structured Figma evidence is present and usable.",
    )
    return parser.parse_args()


def executable(name: str) -> str | None:
    from_path = shutil.which(name)
    if from_path:
        return from_path
    candidates: list[Path] = []
    if name == "java":
        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            candidates.append(Path(java_home) / "bin" / "java")
        candidates.extend(
            [
                Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin/java"),
                Path("/usr/libexec/java_home"),
            ]
        )
    elif name == "adb":
        android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        roots = [Path(android_home)] if android_home else []
        roots.append(Path.home() / "Library" / "Android" / "sdk")
        candidates.extend(root / "platform-tools" / "adb" for root in roots)
    elif name == "emulator":
        android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        roots = [Path(android_home)] if android_home else []
        roots.append(Path.home() / "Library" / "Android" / "sdk")
        candidates.extend(root / "emulator" / "emulator" for root in roots)
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def java_major(java: str | None) -> int | None:
    if not java:
        return None
    result = subprocess.run(
        [java, "-version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    match = re.search(r'version "(?:1\.)?(\d+)', result.stdout)
    return int(match.group(1)) if match else None


def android_sdk() -> Path | None:
    raw = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    candidates = [Path(raw)] if raw else []
    candidates.append(Path.home() / "Library" / "Android" / "sdk")
    for candidate in candidates:
        if (candidate / "platforms").is_dir():
            return candidate
    return None


def gradle_launcher() -> str | None:
    direct = shutil.which("gradle")
    if direct:
        return direct
    home = Path.home() / ".gradle" / "wrapper" / "dists"
    candidates = sorted(
        home.glob("gradle-*-bin/*/gradle-*/bin/gradle"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


def android_devices(adb: str | None) -> list[str]:
    if not adb:
        return []
    try:
        result = subprocess.run(
            [adb, "devices", "-l"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    devices: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(" ".join(parts))
    return sorted(devices)


def available_avds(emulator: str | None) -> list[str]:
    if not emulator:
        return []
    try:
        result = subprocess.run(
            [emulator, "-list-avds"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return sorted(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.lstrip().startswith(("INFO", "WARNING", "ERROR"))
    )


def target_errors(target: Path) -> list[str]:
    if target.exists() and not target.is_dir():
        return [f"{target}: target exists and is not a directory"]
    if target.exists() and any(target.iterdir()):
        return [
            f"{target}: target directory is not empty; choose an empty destination"
        ]
    if target.resolve() == Path(target.anchor):
        return [f"{target}: refusing to use a filesystem root as the project"]
    if target.resolve() == Path.home().resolve():
        return [f"{target}: refusing to use the home directory as the project"]
    return []


def normalize_node_id(value: str) -> str:
    return value.replace("-", ":")


def image_dimensions(path: Path) -> tuple[str, int, int] | None:
    data = path.read_bytes()
    if (
        len(data) >= 24
        and data.startswith(b"\x89PNG\r\n\x1a\n")
        and data[12:16] == b"IHDR"
    ):
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if len(data) >= 12 and data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 4 <= len(data):
            if data[offset] != 0xFF:
                offset += 1
                continue
            while offset < len(data) and data[offset] == 0xFF:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xD8, 0xD9):
                continue
            if offset + 2 > len(data):
                break
            segment_length = struct.unpack(">H", data[offset : offset + 2])[0]
            if segment_length < 2 or offset + segment_length > len(data):
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            } and segment_length >= 7:
                height, width = struct.unpack(
                    ">HH", data[offset + 3 : offset + 7]
                )
                return "jpeg", width, height
            offset += segment_length
    if len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return "webp", width, height
        if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            width = int.from_bytes(data[26:28], "little") & 0x3FFF
            height = int.from_bytes(data[28:30], "little") & 0x3FFF
            return "webp", width, height
        if chunk == b"VP8L" and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return "webp", width, height
    return None


def inspect_figma_manifest(path: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    summary: dict[str, Any] = {"status": "unverified", "path": str(path)}
    candidates: list[Path] = []
    if path.is_dir():
        candidates.extend(sorted(path.glob("**/manifest.yaml")))
        candidates.extend(sorted(path.glob("*.yaml")))
        candidates.extend(sorted(path.glob("*.yml")))
    else:
        candidates.append(path)
    if not candidates:
        return summary, [f"{path}: no structured Figma manifest found"]

    discovered: list[dict[str, Any]] = []
    for manifest_path in sorted(set(candidates)):
        try:
            manifest = load_yaml(manifest_path)
        except DesignPactError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(manifest, dict):
            errors.append(f"{manifest_path}: expected a mapping")
            continue
        source_kind = manifest.get("source_kind")
        if source_kind not in STRUCTURED_FIGMA_SOURCES:
            errors.append(
                f"{manifest_path}: source_kind must identify structured Figma data"
            )
            continue
        if manifest.get("structured") is not True:
            errors.append(
                f"{manifest_path}: structured must be true; screenshots and "
                "unstructured exports cannot satisfy the Figma contract"
            )
        for key in ("file_key", "node_id", "node_name", "revision", "source_url"):
            value = manifest.get(key)
            if value in (None, ""):
                errors.append(f"{manifest_path}: missing required Figma field {key!r}")
            elif not isinstance(value, str):
                errors.append(f"{manifest_path}: Figma field {key!r} must be a string")
            elif PLACEHOLDER_VALUE.search(value):
                errors.append(f"{manifest_path}: Figma field {key!r} is a placeholder")
        file_key = manifest.get("file_key")
        node_id = manifest.get("node_id")
        source_url = manifest.get("source_url")
        if isinstance(file_key, str) and file_key and not re.fullmatch(
            r"[A-Za-z0-9_-]+", file_key
        ):
            errors.append(f"{manifest_path}: file_key has an invalid format")
        if isinstance(node_id, str) and node_id and not re.fullmatch(
            r"[0-9]+[:-][0-9]+", node_id
        ):
            errors.append(f"{manifest_path}: node_id has an invalid format")
        if isinstance(source_url, str) and source_url:
            parsed = urlparse(source_url)
            parts = [part for part in parsed.path.split("/") if part]
            if (
                parsed.scheme not in ("https", "http")
                or parsed.hostname not in ("www.figma.com", "figma.com")
                or len(parts) < 3
                or parts[0] not in ("design", "file")
            ):
                errors.append(f"{manifest_path}: source_url is not a Figma file URL")
            else:
                url_key = parts[1]
                if file_key and url_key != file_key:
                    errors.append(
                        f"{manifest_path}: source_url file key disagrees with file_key"
                    )
                query = parse_qs(parsed.query)
                url_node = query.get("node-id", [""])[0]
                if isinstance(node_id, str) and (
                    not url_node
                    or normalize_node_id(url_node) != normalize_node_id(node_id)
                ):
                    errors.append(
                        f"{manifest_path}: source_url node-id disagrees with node_id"
                    )
        scale = manifest.get("export_scale")
        if (
            not isinstance(scale, (int, float))
            or isinstance(scale, bool)
            or scale <= 0
        ):
            errors.append(f"{manifest_path}: export_scale must be a positive number")
        image_path = manifest.get("path")
        if image_path:
            image = (manifest_path.parent / str(image_path)).resolve()
            try:
                image.relative_to(manifest_path.parent.resolve())
            except ValueError:
                errors.append(
                    f"{manifest_path}: image path must stay inside the evidence folder"
                )
                image = None
            if image is not None and not image.is_file():
                errors.append(f"{manifest_path}: image is missing: {image_path}")
            elif image is not None:
                expected_hash = manifest.get("sha256")
                if (
                    not isinstance(expected_hash, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
                    or expected_hash == "0" * 64
                ):
                    errors.append(
                        f"{manifest_path}: image sha256 must be non-zero SHA-256"
                    )
                elif sha256_file(image) != expected_hash:
                    errors.append(f"{manifest_path}: image hash does not match")
                detected = image_dimensions(image)
                if detected is None:
                    errors.append(
                        f"{manifest_path}: image bytes are not PNG, JPEG, or WebP"
                    )
                else:
                    actual_format, width, height = detected
                    declared_format = str(manifest.get("format", "")).lower()
                    if declared_format == "jpg":
                        declared_format = "jpeg"
                    if declared_format != actual_format:
                        errors.append(
                            f"{manifest_path}: declared image format "
                            f"{manifest.get('format')!r} does not match {actual_format}"
                        )
                    if manifest.get("width_px") != width:
                        errors.append(
                            f"{manifest_path}: width_px does not match image "
                            f"({width})"
                        )
                    if manifest.get("height_px") != height:
                        errors.append(
                            f"{manifest_path}: height_px does not match image "
                            f"({height})"
                        )
        else:
            errors.append(f"{manifest_path}: missing required image path")
        discovered.append(manifest)

    if discovered:
        summary["status"] = "structured"
        summary["manifest_count"] = len(discovered)
        summary["file_keys"] = sorted(
            {str(item.get("file_key")) for item in discovered if item.get("file_key")}
        )
    return summary, errors


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    warnings: list[str] = []
    target = Path(args.target).expanduser()
    errors.extend(target_errors(target))

    python_version = sys.version_info[:2]
    if python_version < MIN_PYTHON:
        errors.append(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required; found {platform.python_version()}"
        )

    java = executable("java")
    jdk = java_major(java)
    if not java:
        errors.append("JDK not found; set JAVA_HOME or install a supported JDK")
    elif jdk is None or jdk < MIN_JDK:
        errors.append(f"JDK {MIN_JDK}+ required; found {jdk or 'unknown'}")

    sdk = android_sdk()
    platforms: list[str] = []
    if sdk is None:
        errors.append("Android SDK not found; set ANDROID_HOME or install SDK platforms")
    else:
        platforms = sorted(
            path.name for path in (sdk / "platforms").iterdir() if path.is_dir()
        )
        if "android-35" not in platforms:
            errors.append("Android SDK platform android-35 is required by this template")

    gradle = gradle_launcher()
    if not gradle:
        errors.append("Gradle launcher not found and no cached Gradle distribution exists")

    adb = executable("adb")
    emulator = executable("emulator")
    if not adb or not emulator:
        warnings.append(
            "Android adb/emulator is unavailable; visual verification may be unverified"
        )
    online_devices = android_devices(adb)
    avds = available_avds(emulator)
    if not online_devices:
        warnings.append(
            "No online Android device or emulator; visual verification is unverified"
        )

    figma_summary: dict[str, Any] = {"status": "not_checked"}
    if args.figma_evidence:
        figma_summary, figma_errors = inspect_figma_manifest(
            Path(args.figma_evidence).expanduser()
        )
        errors.extend(figma_errors)
    elif args.require_figma_evidence:
        errors.append("--require-figma-evidence needs --figma-evidence")

    status = "fail" if errors else ("verified" if args.figma_evidence else "environment_ready")
    summary = {
        "status": status,
        "python": platform.python_version(),
        "java": {"path": java, "major": jdk},
        "android_sdk": str(sdk) if sdk else None,
        "android_platforms": platforms,
        "gradle": gradle,
        "adb": adb,
        "emulator": emulator,
        "online_devices": online_devices,
        "available_avds": avds,
        "visual_verification": {
            "status": "available" if online_devices else "unverified",
            "reason": "" if online_devices else "No online Android device or emulator",
        },
        "figma": figma_summary,
        "warnings": warnings,
    }
    return emit_result(errors, summary)


if __name__ == "__main__":
    run_main(main)
