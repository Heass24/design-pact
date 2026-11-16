#!/usr/bin/env python3
"""Execute one TDD phase and append only valid, hash-chained evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from common import (
    DesignPactError,
    FAILURE_KINDS,
    ID_PATTERNS,
    TDD_PHASES,
    append_jsonl,
    canonical_json,
    event_hash,
    extract_test_declaration,
    load_all_test_contracts,
    load_jsonl,
    load_yaml,
    now_iso,
    project_relative,
    safe_project_path,
    sha256_file,
    validate_metadata,
    validate_schema,
    validate_tdd_ledger,
)


LEDGER_RELATIVE = "docs/verification/tdd-ledger.jsonl"
CONTRACT_SCHEMA_RELATIVE = "schemas/test-case-contract.schema.json"
EVENT_SCHEMA_RELATIVE = "schemas/tdd-event.schema.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--spec-id", required=True)
    parser.add_argument("--test-id", required=True)
    parser.add_argument(
        "--ac-id",
        action="append",
        required=True,
        help="Acceptance criterion covered by this test; repeat for multiple ACs.",
    )
    parser.add_argument("--phase", required=True, choices=TDD_PHASES)
    parser.add_argument(
        "--command-json",
        required=True,
        help='Command as a JSON string array, for example \'["/bin/tool","arg"]\'.',
    )
    parser.add_argument(
        "--failure-kind",
        choices=FAILURE_KINDS,
        help="Required for Red and must be behavior; omitted for other phases.",
    )
    parser.add_argument(
        "--actor",
        default="design-pact-agent",
        help="Execution identity recorded with the captured event.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Command timeout in seconds.",
    )
    return parser.parse_args()


def _load_schema(root: Path, relative: str) -> dict[str, Any]:
    value = load_yaml(root / relative)
    if not isinstance(value, dict):
        raise DesignPactError(f"{root / relative}: expected a mapping")
    return value


def _parse_command(raw: str) -> list[str]:
    try:
        command = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DesignPactError(f"--command-json is invalid JSON: {exc}") from exc
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(part, str) or not part for part in command)
    ):
        raise DesignPactError(
            "--command-json must decode to a non-empty array of non-empty strings"
        )
    return command


def _next_event_id(events: list[dict[str, Any]]) -> str:
    numbers = [
        int(str(event["event_id"]).split("-", 1)[1])
        for event in events
        if isinstance(event.get("event_id"), str)
        and ID_PATTERNS["TDD"].fullmatch(str(event["event_id"]))
    ]
    return f"TDD-{max(numbers, default=0) + 1:03d}"


def _resolve_test(
    root: Path,
    spec_id: str,
    test_id: str,
    requested_ac_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    contracts = load_all_test_contracts(root)
    contract_schema = _load_schema(root, CONTRACT_SCHEMA_RELATIVE)
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for contract in contracts:
        contract_path = root / str(contract.get("_path", ""))
        errors = validate_metadata(contract, str(contract_path))
        errors.extend(
            validate_schema(contract, contract_schema, str(contract_path))
        )
        if errors:
            raise DesignPactError("; ".join(errors))
        tests = contract.get("tests", [])
        if not isinstance(tests, list):
            raise DesignPactError(f"{contract_path}: tests must be a list")
        for test in tests:
            if isinstance(test, dict) and test.get("test_id") == test_id:
                matches.append((contract, test))
    if len(matches) != 1:
        raise DesignPactError(
            f"{test_id}: expected exactly one test contract, found {len(matches)}"
        )
    contract, test = matches[0]
    if contract.get("spec_id") != spec_id:
        raise DesignPactError(
            f"{test_id}: belongs to {contract.get('spec_id')!r}, not {spec_id!r}"
        )
    contract_acs = test.get("ac_ids")
    if not isinstance(contract_acs, list) or not contract_acs:
        raise DesignPactError(f"{test_id}: contract must declare at least one AC")
    if len(requested_ac_ids) != len(set(requested_ac_ids)):
        raise DesignPactError(f"{test_id}: duplicate --ac-id values are not allowed")
    if set(requested_ac_ids) != set(contract_acs):
        raise DesignPactError(
            f"{test_id}: --ac-id values {requested_ac_ids!r} must exactly match "
            f"the test contract {contract_acs!r}"
        )
    if test.get("planning_status") not in ("planned", "active"):
        raise DesignPactError(
            f"{test_id}: TDD evidence requires planning_status planned or active"
        )
    return contract, test


def _test_binding(
    root: Path, test: dict[str, Any], test_id: str
) -> tuple[Path, Any]:
    relative = test.get("implementation_path")
    symbol = test.get("implementation_symbol")
    if not isinstance(relative, str) or not isinstance(symbol, str):
        raise DesignPactError(
            f"{test_id}: contract must declare implementation_path and symbol"
        )
    test_path = safe_project_path(root, relative, test_id)
    if not test_path.is_file():
        raise DesignPactError(f"{test_id}: Kotlin test does not exist: {relative}")
    declaration = extract_test_declaration(test_path, test_id, symbol)
    expected_acs = tuple(str(item) for item in test.get("ac_ids", []))
    if declaration.ac_ids != expected_acs:
        raise DesignPactError(
            f"{test_id}: Kotlin marker ACs {declaration.ac_ids!r} do not match "
            f"the contract {expected_acs!r}"
        )
    return test_path, declaration


def _execution_log(
    command: list[str],
    cwd: Path,
    result: subprocess.CompletedProcess[bytes],
) -> str:
    return (
        f"$ {json.dumps(command, ensure_ascii=False)}\n"
        f"cwd: {cwd.resolve().as_posix()}\n"
        f"exit_code: {result.returncode}\n"
        "--- stdout ---\n"
        f"{result.stdout.decode('utf-8', errors='replace')}"
        "--- stderr ---\n"
        f"{result.stderr.decode('utf-8', errors='replace')}"
    )


def record_evidence(
    *,
    project_root: Path,
    spec_id: str,
    test_id: str,
    ac_ids: list[str],
    phase: str,
    command: list[str],
    failure_kind: str | None,
    actor: str,
    timeout: int,
) -> tuple[list[str], dict[str, Any]]:
    root = project_root.expanduser().resolve()
    if not root.is_dir():
        raise DesignPactError(f"{root}: project root must be an existing directory")
    if not actor.strip() or actor != actor.strip():
        raise DesignPactError("--actor must be non-empty without surrounding whitespace")
    if timeout <= 0:
        raise DesignPactError("--timeout must be positive")
    if phase == "red" and failure_kind != "behavior":
        raise DesignPactError(
            "Red evidence requires --failure-kind behavior; compile, syntax, "
            "environment, dependency, and setup failures are not valid Red"
        )
    if phase != "red" and failure_kind is not None:
        raise DesignPactError("--failure-kind is allowed only for Red evidence")

    contract, test = _resolve_test(root, spec_id, test_id, ac_ids)
    contract_path = safe_project_path(root, contract["_path"], test_id)
    test_path, declaration = _test_binding(root, test, test_id)
    contracts = load_all_test_contracts(root)
    ledger_errors = validate_tdd_ledger(
        root,
        contracts=contracts,
        require_accepted=False,
    )
    if ledger_errors:
        raise DesignPactError("; ".join(ledger_errors))

    ledger_path = root / LEDGER_RELATIVE
    events = load_jsonl(ledger_path)
    event_id = _next_event_id(events)
    started_at = now_iso()
    started_clock = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=root,
            shell=False,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DesignPactError(
            f"command executable does not exist: {command[0]!r}"
        ) from exc
    except PermissionError as exc:
        raise DesignPactError(
            f"command is not executable: {command[0]!r}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DesignPactError(
            f"command exceeded {timeout} seconds; no evidence was recorded"
        ) from exc
    elapsed = round(time.monotonic() - started_clock, 3)
    finished_at = now_iso()

    if phase == "red" and result.returncode == 0:
        raise DesignPactError("Red must fail; command exited zero")
    if phase != "red" and result.returncode != 0:
        raise DesignPactError(
            f"{phase} must pass; command exited {result.returncode}"
        )

    log_text = _execution_log(command, root, result)
    log_text += f"elapsed_seconds: {elapsed}\n"
    log_relative = f"docs/verification/tdd-artifacts/{event_id}.log"
    log_path = safe_project_path(root, log_relative, event_id)
    log_bytes = log_text.encode("utf-8")
    artifact_sha256 = hashlib.sha256(log_bytes).hexdigest()

    event: dict[str, Any] = {
        "event_id": event_id,
        "schema_version": "1.0",
        "spec_id": spec_id,
        "ac_ids": list(test["ac_ids"]),
        "test_id": test_id,
        "phase": phase,
        "command": command,
        "exit_code": result.returncode,
        "failure_kind": failure_kind,
        "started_at": started_at,
        "finished_at": finished_at,
        "actor": actor,
        "artifact_path": log_relative,
        "artifact_sha256": artifact_sha256,
        "test_declaration_sha256": declaration.sha256,
        "contract_sha256": sha256_file(contract_path),
        "implementation_path": project_relative(test_path, root),
        "implementation_sha256": sha256_file(test_path),
        "status": "captured",
        "prev_event_sha256": str(events[-1].get("event_sha256", "")) if events else "",
    }
    event["event_sha256"] = event_hash(event)

    event_schema = _load_schema(root, EVENT_SCHEMA_RELATIVE)
    shape_errors = validate_schema(event, event_schema, event_id)
    if shape_errors:
        raise DesignPactError("; ".join(shape_errors))

    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_path.write_bytes(log_bytes)
        append_jsonl(ledger_path, event)
    except OSError:
        log_path.unlink(missing_ok=True)
        raise
    return [], {
        "event_id": event_id,
        "phase": phase,
        "exit_code": result.returncode,
        "log_path": log_relative,
        "event_sha256": event["event_sha256"],
    }


def main() -> int:
    args = parse_args()
    errors, summary = record_evidence(
        project_root=Path(args.project_root),
        spec_id=args.spec_id,
        test_id=args.test_id,
        ac_ids=args.ac_id,
        phase=args.phase,
        command=_parse_command(args.command_json),
        failure_kind=args.failure_kind,
        actor=args.actor,
        timeout=args.timeout,
    )
    print(json.dumps({"ok": not errors, "errors": errors, "summary": summary}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    from common import run_main

    run_main(main)
