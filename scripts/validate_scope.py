#!/usr/bin/env python3
"""Validate Design Pact scope closure and end-to-end traceability."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

from common import (
    DesignPactError,
    load_approvals,
    load_specs,
    load_yaml,
    project_relative,
    read_text,
    split_frontmatter,
    valid_id,
)


PRODUCT_DIR = "docs/product"
DESIGN_DIR = "docs/design"
VERIFICATION_DIR = "docs/verification"
TEST_CASES_DIR = f"{VERIFICATION_DIR}/test-cases"
SCOPE_AUDIT = f"{VERIFICATION_DIR}/scope-audit.md"
STATE_PATH = "docs/project/state.yaml"

JOURNEY_MAP = f"{PRODUCT_DIR}/journey-map.yaml"
FEATURE_MAP = f"{PRODUCT_DIR}/feature-map.yaml"
COVERAGE_MATRIX = f"{PRODUCT_DIR}/coverage-matrix.yaml"
RELEASE_SCOPE = f"{PRODUCT_DIR}/release-scope.yaml"
SCREEN_INVENTORY = f"{DESIGN_DIR}/screen-inventory.yaml"
EXCEPTIONS = f"{DESIGN_DIR}/design-exceptions.yaml"
GAPS = f"{DESIGN_DIR}/gaps.yaml"

OBJECT_PREFIXES = {
    "journey": "JRN",
    "feature": "FEAT",
    "screen": "SCREEN",
    "flow": "FLOW",
    "state": "STATE",
    "interaction": "INT",
    "non_functional": "NFR",
}
TRACE_PREFIXES = ("JRN", "FEAT", "SCREEN", "FLOW", "STATE", "AC", "TEST", "SHOT")
PAGE_DIRECTORY_RE = re.compile(
    r"^(SCREEN|FLOW)-(?!000)[0-9]{3}-[a-z0-9]+(?:-[a-z0-9]+)*$"
)
PLACEHOLDER_IDENTITY_RE = re.compile(
    r"(?:^|[\s_.:/-])(?:ai|agent|bot|automation|todo|tbd|placeholder|unknown)"
    r"(?:$|[\s_.:/-])",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, help="Design Pact project.")
    parser.add_argument(
        "--require-release",
        action="store_true",
        help="Require complete, approved first-release scope and evidence intent.",
    )
    return parser.parse_args()


def _mapping(root: Path, relative: str, errors: list[str]) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        errors.append(f"{relative}: required artifact is missing")
        return {}
    try:
        value = load_yaml(path)
    except DesignPactError as exc:
        errors.append(str(exc))
        return {}
    if not isinstance(value, dict):
        errors.append(f"{relative}: expected a mapping")
        return {}
    return value


def _items(value: Any, field: str, location: str, errors: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{location}.{field}: expected a list")
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"{location}.{field}[{index}]: expected a mapping")
            continue
        result.append(item)
    return result


def _string_list(
    value: Any,
    location: str,
    errors: list[str],
    *,
    required: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{location}: expected a list")
        return []
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{location}[{index}]: expected a non-empty string")
            continue
        result.append(item)
    if required and not result:
        errors.append(f"{location}: must contain at least one ID")
    return result


def _record_id(
    record: dict[str, Any],
    field: str,
    prefix: str,
    location: str,
    errors: list[str],
) -> str | None:
    value = record.get(field)
    if not valid_id(value, prefix):
        errors.append(f"{location}.{field}: invalid {prefix} ID {value!r}")
        return None
    return str(value)


def _require_unique(
    value: str,
    known: dict[str, str],
    location: str,
    errors: list[str],
) -> None:
    if value in known:
        errors.append(
            f"{location}: duplicate stable ID {value}; first declared at {known[value]}"
        )
    else:
        known[value] = location


def _require_ref(
    value: str,
    available: set[str],
    location: str,
    errors: list[str],
) -> None:
    if value not in available:
        errors.append(f"{location}: references missing object {value}")


def _set_mismatch(
    *,
    actual: Iterable[str],
    expected: Iterable[str],
    location: str,
    errors: list[str],
) -> None:
    actual_set = set(actual)
    expected_set = set(expected)
    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)
    if missing:
        errors.append(f"{location}: missing references {', '.join(missing)}")
    if extra:
        errors.append(f"{location}: contains unsupported references {', '.join(extra)}")


def _approval_by_id(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    try:
        records = load_approvals(root)
    except DesignPactError as exc:
        return {}, [str(exc)]
    errors: list[str] = []
    result: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records, start=1):
        approval_id = record.get("approval_id")
        if not isinstance(approval_id, str):
            continue
        if approval_id in result:
            errors.append(
                f"docs/project/approvals.jsonl:{index}: duplicate {approval_id}"
            )
        else:
            result[approval_id] = record
    return result, errors


def _audit_errors(
    root: Path,
    state: dict[str, Any],
    require_release: bool,
) -> list[str]:
    errors: list[str] = []
    path = root / SCOPE_AUDIT
    if not path.is_file():
        return [f"{SCOPE_AUDIT}: required scope audit is missing"]
    try:
        metadata, body = split_frontmatter(read_text(path), path)
    except DesignPactError as exc:
        return [str(exc)]
    required = (
        "audit_id",
        "conclusion",
        "reviewer",
        "figma_revision",
        "product_revision",
    )
    for key in required:
        if key not in metadata:
            errors.append(f"{SCOPE_AUDIT}: missing audit field {key!r}")
    conclusion = metadata.get("conclusion")
    if conclusion not in ("pass", "fail", "unverified"):
        errors.append(f"{SCOPE_AUDIT}: conclusion must be pass, fail, or unverified")
    for key in ("audit_id", "reviewer", "figma_revision", "product_revision"):
        value = metadata.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{SCOPE_AUDIT}: {key} must be a non-empty string")
        elif PLACEHOLDER_IDENTITY_RE.search(value):
            errors.append(f"{SCOPE_AUDIT}: {key} cannot be a placeholder")
    if not body.lstrip().startswith("#"):
        errors.append(f"{SCOPE_AUDIT}: audit body must contain a review report")
    if require_release:
        if conclusion != "pass":
            errors.append(
                f"{SCOPE_AUDIT}: release scope audit must conclude 'pass'; "
                f"found {conclusion!r}"
            )
        if metadata.get("status") != "approved":
            errors.append(
                f"{SCOPE_AUDIT}: release scope audit must have approved status"
            )
        snapshot = state.get("design_snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("status") != "structured":
            errors.append(
                f"{STATE_PATH}: release requires a structured design snapshot"
            )
        elif metadata.get("figma_revision") != snapshot.get("revision"):
            errors.append(
                f"{SCOPE_AUDIT}: figma_revision must equal the current "
                "state.design_snapshot.revision"
            )
    return errors


def _scope_summary(
    *,
    journeys: set[str],
    features: set[str],
    slices: set[str],
    states: set[str],
    specs: set[str],
    acs: set[str],
    tests: set[str],
    gaps: set[str],
    exceptions: set[str],
    require_release: bool,
) -> dict[str, Any]:
    return {
        "require_release": require_release,
        "journeys": len(journeys),
        "features": len(features),
        "slices": len(slices),
        "states": len(states),
        "specifications": len(specs),
        "acceptance_criteria": len(acs),
        "tests": len(tests),
        "gaps": len(gaps),
        "exceptions": len(exceptions),
    }


def validate_scope(root: Path, *, require_release: bool = False) -> tuple[list[str], dict[str, Any]]:
    root = root.expanduser().resolve()
    errors: list[str] = []
    journeys_doc = _mapping(root, JOURNEY_MAP, errors)
    features_doc = _mapping(root, FEATURE_MAP, errors)
    coverage_doc = _mapping(root, COVERAGE_MATRIX, errors)
    release_doc = _mapping(root, RELEASE_SCOPE, errors)
    inventory_doc = _mapping(root, SCREEN_INVENTORY, errors)
    exceptions_doc = _mapping(root, EXCEPTIONS, errors)
    gaps_doc = _mapping(root, GAPS, errors)
    state = _mapping(root, STATE_PATH, errors)

    stable_ids: dict[str, str] = {}
    journeys: set[str] = set()
    features: set[str] = set()
    screens: set[str] = set()
    flows: set[str] = set()
    slices: set[str] = set()
    states: set[str] = set()
    specs: set[str] = set()
    acs: set[str] = set()
    tests: set[str] = set()
    shots: set[str] = set()
    gaps: set[str] = set()
    exceptions: set[str] = set()

    journey_records = _items(journeys_doc.get("journeys"), "journeys", JOURNEY_MAP, errors)
    journey_features: dict[str, set[str]] = {}
    for index, record in enumerate(journey_records):
        location = f"{JOURNEY_MAP}.journeys[{index}]"
        journey_id = _record_id(record, "id", "JRN", location, errors)
        if journey_id is None:
            continue
        if journey_id in journeys:
            errors.append(f"{location}: duplicate journey ID {journey_id}")
        journeys.add(journey_id)
        _require_unique(journey_id, stable_ids, location, errors)
        journey_features[journey_id] = set(
            _string_list(
                record.get("feature_ids"),
                f"{location}.feature_ids",
                errors,
                required=True,
            )
        )

    feature_records = _items(features_doc.get("features"), "features", FEATURE_MAP, errors)
    feature_journeys: dict[str, str] = {}
    feature_slices: dict[str, set[str]] = {}
    for index, record in enumerate(feature_records):
        location = f"{FEATURE_MAP}.features[{index}]"
        feature_id = _record_id(record, "id", "FEAT", location, errors)
        if feature_id is None:
            continue
        if feature_id in features:
            errors.append(f"{location}: duplicate feature ID {feature_id}")
        features.add(feature_id)
        _require_unique(feature_id, stable_ids, location, errors)
        journey_id = record.get("journey_id")
        if not valid_id(journey_id, "JRN"):
            errors.append(f"{location}.journey_id: invalid JRN ID {journey_id!r}")
        else:
            feature_journeys[feature_id] = str(journey_id)
        feature_slices[feature_id] = set(
            _string_list(
                record.get("screen_ids"),
                f"{location}.screen_ids",
                errors,
                required=True,
            )
        )

    screen_records = _items(inventory_doc.get("screens"), "screens", SCREEN_INVENTORY, errors)
    flow_records = _items(inventory_doc.get("flows"), "flows", SCREEN_INVENTORY, errors)
    state_records = _items(inventory_doc.get("states"), "states", SCREEN_INVENTORY, errors)
    slice_features: dict[str, set[str]] = {}
    slice_states: dict[str, set[str]] = {}
    state_owner: dict[str, str] = {}

    for object_type, records, field, values in (
        ("screen", screen_records, "screens", screens),
        ("flow", flow_records, "flows", flows),
    ):
        prefix = OBJECT_PREFIXES[object_type]
        for index, record in enumerate(records):
            location = f"{SCREEN_INVENTORY}.{field}[{index}]"
            object_id = _record_id(record, "id", prefix, location, errors)
            if object_id is None:
                continue
            if object_id in values:
                errors.append(f"{location}: duplicate {object_type} ID {object_id}")
            values.add(object_id)
            slices.add(object_id)
            _require_unique(object_id, stable_ids, location, errors)
            slice_features[object_id] = set(
                _string_list(
                    record.get("feature_ids"),
                    f"{location}.feature_ids",
                    errors,
                    required=True,
                )
            )
            slice_states[object_id] = set(
                _string_list(
                    record.get("state_ids"),
                    f"{location}.state_ids",
                    errors,
                    required=True,
                )
            )
            figma = record.get("figma")
            if not isinstance(figma, dict) or not figma:
                errors.append(f"{location}.figma: structured Figma binding is required")

    for index, record in enumerate(state_records):
        location = f"{SCREEN_INVENTORY}.states[{index}]"
        state_id = _record_id(record, "id", "STATE", location, errors)
        if state_id is None:
            continue
        if state_id in states:
            errors.append(f"{location}: duplicate state ID {state_id}")
        states.add(state_id)
        _require_unique(state_id, stable_ids, location, errors)
        owner = record.get("screen_id")
        if not isinstance(owner, str) or not owner:
            errors.append(f"{location}.screen_id: owner slice is required")
        elif owner not in slices:
            errors.append(f"{location}.screen_id: references missing slice {owner}")
        else:
            if state_id in state_owner:
                errors.append(f"{location}: state has more than one owner")
            state_owner[state_id] = owner
        figma = record.get("figma")
        if not isinstance(figma, dict) or not figma:
            errors.append(f"{location}.figma: structured Figma binding is required")

    for journey_id, linked in journey_features.items():
        for feature_id in sorted(linked):
            _require_ref(feature_id, features, f"{JOURNEY_MAP}.{journey_id}", errors)
    for feature_id in sorted(features):
        linked_journey = feature_journeys.get(feature_id)
        if linked_journey:
            _require_ref(linked_journey, journeys, f"{FEATURE_MAP}.{feature_id}", errors)
            if feature_id not in journey_features.get(linked_journey, set()):
                errors.append(
                    f"{FEATURE_MAP}.{feature_id}: journey reference is not reciprocal"
                )
        for slice_id in sorted(feature_slices.get(feature_id, set())):
            _require_ref(slice_id, slices, f"{FEATURE_MAP}.{feature_id}", errors)
            if feature_id not in slice_features.get(slice_id, set()):
                errors.append(
                    f"{FEATURE_MAP}.{feature_id}: screen/flow reference is not reciprocal"
                )
    for slice_id in sorted(slices):
        for feature_id in sorted(slice_features.get(slice_id, set())):
            _require_ref(feature_id, features, f"{SCREEN_INVENTORY}.{slice_id}", errors)
            if slice_id not in feature_slices.get(feature_id, set()):
                errors.append(
                    f"{SCREEN_INVENTORY}.{slice_id}: feature reference is not reciprocal"
                )
        owned_states = {state for state, owner in state_owner.items() if owner == slice_id}
        _set_mismatch(
            actual=slice_states.get(slice_id, set()),
            expected=owned_states,
            location=f"{SCREEN_INVENTORY}.{slice_id}.state_ids",
            errors=errors,
        )

    try:
        spec_records = load_specs(root)
    except DesignPactError as exc:
        spec_records = []
        errors.append(str(exc))
    spec_levels: dict[str, str] = {}
    spec_slices: dict[str, set[str]] = {}
    spec_states: dict[str, set[str]] = {}
    spec_tests: dict[str, set[str]] = {}
    spec_acs: dict[str, set[str]] = {}
    ac_state: dict[str, str] = {}
    ac_spec: dict[str, str] = {}
    ac_tests: dict[str, set[str]] = {}
    ac_shots: dict[str, set[str]] = {}
    visual_acs: set[str] = set()

    for path, metadata, _ in spec_records:
        if "generator" in metadata:
            continue
        location = project_relative(path, root)
        spec_id = _record_id(metadata, "spec_id", "SPEC", location, errors)
        level = metadata.get("spec_level")
        if level not in ("L1", "L2"):
            errors.append(f"{location}: spec_level must be L1 or L2")
            continue
        if spec_id is None:
            continue
        if spec_id in specs:
            errors.append(f"{location}: duplicate specification ID {spec_id}")
        specs.add(spec_id)
        _require_unique(spec_id, stable_ids, location, errors)
        spec_levels[spec_id] = str(level)
        spec_journeys = set(
            _string_list(metadata.get("journey_ids"), f"{location}.journey_ids", errors, required=True)
        )
        spec_features = set(
            _string_list(metadata.get("feature_ids"), f"{location}.feature_ids", errors, required=True)
        )
        spec_state_ids = set(
            _string_list(metadata.get("state_ids"), f"{location}.state_ids", errors)
        )
        spec_screen_ids = set(
            _string_list(metadata.get("screen_ids"), f"{location}.screen_ids", errors)
        )
        spec_flow_ids = set(
            _string_list(metadata.get("flow_ids"), f"{location}.flow_ids", errors)
        )
        for journey_id in sorted(spec_journeys):
            _require_ref(journey_id, journeys, location, errors)
        for feature_id in sorted(spec_features):
            _require_ref(feature_id, features, location, errors)
        if level == "L1":
            spec_levels[spec_id] = "L1"
            continue
        bound_slices = spec_screen_ids | spec_flow_ids
        if len(bound_slices) != 1:
            errors.append(
                f"{location}: L2 must bind exactly one screen or flow; found "
                f"{', '.join(sorted(bound_slices)) or 'none'}"
            )
            continue
        slice_id = next(iter(bound_slices))
        if slice_id not in slices:
            errors.append(f"{location}: L2 binds missing slice {slice_id}")
        if spec_screen_ids and slice_id not in screens:
            errors.append(f"{location}: screen_ids contains a non-screen {slice_id}")
        if spec_flow_ids and slice_id not in flows:
            errors.append(f"{location}: flow_ids contains a non-flow {slice_id}")
        spec_slices[spec_id] = bound_slices
        spec_states[spec_id] = spec_state_ids
        for state_id in sorted(spec_state_ids):
            _require_ref(state_id, states, location, errors)
            if state_owner.get(state_id) != slice_id:
                errors.append(
                    f"{location}: state {state_id} does not belong to {slice_id}"
                )
        ac_ids = _string_list(metadata.get("ac_ids"), f"{location}.ac_ids", errors, required=True)
        criteria = _items(
            metadata.get("acceptance_criteria"),
            "acceptance_criteria",
            location,
            errors,
        )
        declared_acs = [str(item) for item in ac_ids]
        if len(declared_acs) != len(set(declared_acs)):
            errors.append(f"{location}.ac_ids: duplicate AC IDs")
        criteria_ids: list[str] = []
        for index, criterion in enumerate(criteria):
            ac_location = f"{location}.acceptance_criteria[{index}]"
            ac_id = _record_id(criterion, "id", "AC", ac_location, errors)
            if ac_id is None:
                continue
            criteria_ids.append(ac_id)
            if ac_id in acs:
                errors.append(f"{ac_location}: duplicate acceptance criterion {ac_id}")
            acs.add(ac_id)
            _require_unique(ac_id, stable_ids, ac_location, errors)
            state_id = criterion.get("state_id")
            if not valid_id(state_id, "STATE"):
                errors.append(f"{ac_location}.state_id: invalid STATE ID {state_id!r}")
            else:
                _require_ref(str(state_id), states, ac_location, errors)
                if str(state_id) not in spec_state_ids:
                    errors.append(
                        f"{ac_location}: state {state_id} is not declared by {spec_id}"
                    )
                ac_state[ac_id] = str(state_id)
            ac_spec[ac_id] = spec_id
            criterion_tests = set(
                _string_list(
                    criterion.get("test_ids"),
                    f"{ac_location}.test_ids",
                    errors,
                    required=True,
                )
            )
            ac_tests[ac_id] = criterion_tests
            spec_tests.setdefault(spec_id, set()).update(criterion_tests)
            criterion_shots = set(
                _string_list(
                    criterion.get("visual_shot_ids"),
                    f"{ac_location}.visual_shot_ids",
                    errors,
                )
            )
            ac_shots[ac_id] = criterion_shots
            for shot_id in sorted(criterion_shots):
                if not valid_id(shot_id, "SHOT"):
                    errors.append(f"{ac_location}: invalid SHOT ID {shot_id!r}")
                if shot_id in shots:
                    errors.append(f"{ac_location}: duplicate visual shot {shot_id}")
                shots.add(shot_id)
            if criterion.get("visual_required") is True:
                visual_acs.add(ac_id)
                if not criterion_shots:
                    errors.append(
                        f"{ac_location}: visual_required AC needs at least one SHOT ID"
                    )
        _set_mismatch(
            actual=criteria_ids,
            expected=declared_acs,
            location=f"{location}.ac_ids",
            errors=errors,
        )
        spec_acs[spec_id] = set(criteria_ids)

    l1_for_journey: dict[str, set[str]] = {}
    l1_for_feature: dict[str, set[str]] = {}
    for path, metadata, _ in spec_records:
        if metadata.get("spec_level") != "L1":
            continue
        spec_id = str(metadata.get("spec_id"))
        for journey_id in metadata.get("journey_ids", []):
            if isinstance(journey_id, str):
                l1_for_journey.setdefault(journey_id, set()).add(spec_id)
        for feature_id in metadata.get("feature_ids", []):
            if isinstance(feature_id, str):
                l1_for_feature.setdefault(feature_id, set()).add(spec_id)

    l2_by_slice: dict[str, set[str]] = {}
    for spec_id, bound in spec_slices.items():
        for slice_id in bound:
            l2_by_slice.setdefault(slice_id, set()).add(spec_id)

    coverage_records = _items(
        coverage_doc.get("objects"),
        "objects",
        COVERAGE_MATRIX,
        errors,
    )
    coverage_status: dict[str, str] = {}
    coverage_type: dict[str, str] = {}
    for index, record in enumerate(coverage_records):
        location = f"{COVERAGE_MATRIX}.objects[{index}]"
        object_id = record.get("object_id")
        object_type = record.get("object_type")
        status = record.get("status")
        if not isinstance(object_id, str) or not object_id:
            errors.append(f"{location}.object_id: expected a non-empty ID")
            continue
        if object_id in coverage_status:
            errors.append(f"{location}: duplicate coverage object {object_id}")
        coverage_status[object_id] = str(status)
        coverage_type[object_id] = str(object_type)
        expected_prefix = OBJECT_PREFIXES.get(str(object_type))
        if expected_prefix and not object_id.startswith(f"{expected_prefix}-"):
            errors.append(
                f"{location}: object_type {object_type!r} does not match {object_id}"
            )
        if status not in ("covered", "out_of_scope", "deferred", "blocked"):
            errors.append(f"{location}: invalid coverage status {status!r}")
        rationale = record.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            errors.append(f"{location}: rationale must be non-empty")
        sources = _string_list(
            record.get("source_ids"),
            f"{location}.source_ids",
            errors,
            required=True,
        )
        if status != "covered" and len(sources) == 1 and sources[0] == object_id:
            errors.append(
                f"{location}.source_ids: must cite the source, not repeat the object ID"
            )

    known_objects = journeys | features | slices | states
    for object_id in sorted(known_objects):
        if object_id not in coverage_status:
            errors.append(
                f"{COVERAGE_MATRIX}: missing user-observable object {object_id}"
            )
            continue
        expected_type = (
            "journey"
            if object_id.startswith("JRN-")
            else "feature"
            if object_id.startswith("FEAT-")
            else "screen"
            if object_id.startswith("SCREEN-")
            else "flow"
            if object_id.startswith("FLOW-")
            else "state"
        )
        if coverage_type.get(object_id) != expected_type:
            errors.append(
                f"{COVERAGE_MATRIX}.{object_id}: object_type must be {expected_type!r}"
            )
    for object_id in sorted(set(coverage_status) - known_objects):
        if object_id.startswith(("JRN-", "FEAT-", "SCREEN-", "FLOW-", "STATE-")):
            errors.append(
                f"{COVERAGE_MATRIX}.{object_id}: coverage object is orphaned; "
                "it has no source inventory record"
            )

    covered_journeys = {
        item for item in journeys if coverage_status.get(item) == "covered"
    }
    covered_features = {
        item for item in features if coverage_status.get(item) == "covered"
    }
    covered_slices = {
        item for item in slices if coverage_status.get(item) == "covered"
    }
    covered_states = {
        item for item in states if coverage_status.get(item) == "covered"
    }
    noncovered_objects = {
        item
        for item in known_objects
        if coverage_status.get(item) in ("out_of_scope", "deferred", "blocked")
    }

    for journey_id in sorted(covered_journeys):
        if not l1_for_journey.get(journey_id):
            errors.append(f"{journey_id}: covered journey has no L1 specification")
    for feature_id in sorted(covered_features):
        if not l1_for_feature.get(feature_id):
            errors.append(f"{feature_id}: covered feature has no L1 specification")

    contract_tests: dict[str, dict[str, Any]] = {}
    contract_by_slice: dict[str, str] = {}
    test_contract: dict[str, str] = {}
    test_acs: dict[str, set[str]] = {}
    test_states: dict[str, set[str]] = {}
    test_shots: dict[str, set[str]] = {}
    contract_paths: list[Path] = sorted((root / TEST_CASES_DIR).glob("*/test-cases.yaml"))
    for path in contract_paths:
        location = project_relative(path, root)
        directory = path.parent.name
        if not PAGE_DIRECTORY_RE.fullmatch(directory):
            errors.append(
                f"{location}: page directory must be SCREEN-###-slug or FLOW-###-slug"
            )
        try:
            contract = load_yaml(path)
        except DesignPactError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(contract, dict):
            errors.append(f"{location}: expected a mapping")
            continue
        slice_id = contract.get("slice_id")
        slice_type = contract.get("slice_type")
        if not isinstance(slice_id, str) or slice_id not in slices:
            errors.append(f"{location}: slice_id references a missing slice {slice_id!r}")
            continue
        expected_type = "screen" if slice_id.startswith("SCREEN-") else "flow"
        if slice_type != expected_type:
            errors.append(
                f"{location}: slice_type must be {expected_type!r} for {slice_id}"
            )
        if not directory.startswith(f"{slice_id}-"):
            errors.append(f"{location}: directory does not belong to {slice_id}")
        if slice_id in contract_by_slice:
            errors.append(
                f"{location}: duplicate test contract for {slice_id}; first at "
                f"{contract_by_slice[slice_id]}"
            )
        contract_by_slice[slice_id] = location
        spec_id = contract.get("spec_id")
        if not isinstance(spec_id, str) or spec_id not in spec_slices:
            errors.append(f"{location}: spec_id references a missing L2 {spec_id!r}")
            continue
        if slice_id not in spec_slices.get(spec_id, set()):
            errors.append(f"{location}: L2 {spec_id} does not bind {slice_id}")
        source_ids = _string_list(
            contract.get("source_ids"),
            f"{location}.source_ids",
            errors,
            required=True,
        )
        if spec_id not in source_ids:
            errors.append(f"{location}: source_ids must include {spec_id}")
        docs_path = path.with_suffix(".md")
        if not docs_path.is_file():
            errors.append(f"{location}: generated human view test-cases.md is missing")
        contract_items = _items(contract.get("tests"), "tests", location, errors)
        if not contract_items and coverage_status.get(slice_id) == "covered":
            errors.append(f"{location}: covered slice must define at least one test")
        for index, test in enumerate(contract_items):
            test_location = f"{location}.tests[{index}]"
            test_id = _record_id(test, "test_id", "TEST", test_location, errors)
            if test_id is None:
                continue
            if test_id in contract_tests:
                errors.append(
                    f"{test_location}: duplicate test ID {test_id}; first at "
                    f"{contract_tests[test_id]['_path']}"
                )
                continue
            contract_tests[test_id] = {**test, "_path": test_location}
            test_contract[test_id] = spec_id
            tests.add(test_id)
            _require_unique(test_id, stable_ids, test_location, errors)
            linked_acs = set(
                _string_list(
                    test.get("ac_ids"),
                    f"{test_location}.ac_ids",
                    errors,
                    required=True,
                )
            )
            linked_states = set(
                _string_list(
                    test.get("state_ids"),
                    f"{test_location}.state_ids",
                    errors,
                    required=True,
                )
            )
            test_acs[test_id] = linked_acs
            test_states[test_id] = linked_states
            for ac_id in sorted(linked_acs):
                _require_ref(ac_id, acs, test_location, errors)
                if ac_spec.get(ac_id) != spec_id:
                    errors.append(
                        f"{test_location}: AC {ac_id} belongs to {ac_spec.get(ac_id)}"
                    )
                if test_id not in ac_tests.get(ac_id, set()):
                    errors.append(
                        f"{test_location}: AC {ac_id} test_ids lack {test_id}"
                    )
            for state_id in sorted(linked_states):
                _require_ref(state_id, states, test_location, errors)
                if state_id not in spec_states.get(spec_id, set()):
                    errors.append(
                        f"{test_location}: state {state_id} is not in {spec_id}"
                    )
                if state_id not in {
                    ac_state.get(ac_id) for ac_id in linked_acs if ac_id in ac_state
                }:
                    errors.append(
                        f"{test_location}: test states do not include its AC state"
                    )
            linked_shots = set(
                _string_list(
                    test.get("visual_shot_ids"),
                    f"{test_location}.visual_shot_ids",
                    errors,
                )
            )
            test_shots[test_id] = linked_shots
            for shot_id in sorted(linked_shots):
                if shot_id not in shots:
                    errors.append(
                        f"{test_location}: SHOT {shot_id} is not declared by an AC"
                    )
            planning_status = test.get("planning_status")
            if require_release and planning_status != "active":
                errors.append(
                    f"{test_location}: release tests must be active; "
                    f"found {planning_status!r}"
                )
            if planning_status in ("blocked", "deferred", "out_of_scope"):
                reason = test.get("planning_reason")
                if not isinstance(reason, str) or not reason.strip():
                    errors.append(
                        f"{test_location}: {planning_status} test needs planning_reason"
                    )

    for spec_id in sorted(spec_acs):
        for ac_id in sorted(spec_acs[spec_id]):
            expected = ac_tests.get(ac_id, set())
            actual = {
                test_id
                for test_id, linked_acs in test_acs.items()
                if ac_id in linked_acs
            }
            _set_mismatch(
                actual=actual,
                expected=expected,
                location=f"{ac_id}: acceptance_criteria.test_ids",
                errors=errors,
            )
            if len([test_id for test_id in actual if test_contract.get(test_id) == spec_id]) == 0:
                errors.append(f"{ac_id}: no behavior test is bound in {spec_id}")
            for shot_id in ac_shots.get(ac_id, set()):
                if not any(
                    shot_id in test_shots.get(test_id, set())
                    for test_id in actual
                    if ac_id in test_acs.get(test_id, set())
                ):
                    errors.append(
                        f"{ac_id}: visual shot {shot_id} is not bound to any test"
                    )

    for slice_id in sorted(covered_slices):
        l2s = l2_by_slice.get(slice_id, set())
        if not l2s:
            errors.append(f"{slice_id}: covered slice has no L2 specification")
        elif len(l2s) != 1:
            errors.append(
                f"{slice_id}: covered slice must have exactly one L2 specification; "
                f"found {', '.join(sorted(l2s))}"
            )
        if slice_id not in contract_by_slice:
            errors.append(f"{slice_id}: covered slice has no test-cases.yaml")
        owned_covered = {
            state_id
            for state_id in covered_states
            if state_owner.get(state_id) == slice_id
        }
        for spec_id in sorted(l2s):
            missing_states = owned_covered - spec_states.get(spec_id, set())
            if missing_states:
                errors.append(
                    f"{spec_id}: L2 omits covered states "
                    f"{', '.join(sorted(missing_states))}"
                )
            for state_id in sorted(owned_covered):
                if not any(
                    ac_state.get(ac_id) == state_id
                    for ac_id in spec_acs.get(spec_id, set())
                ):
                    errors.append(
                        f"{spec_id}: covered state {state_id} has no acceptance criterion"
                    )

    exceptions_by_id: dict[str, dict[str, Any]] = {}
    exception_records = _items(
        exceptions_doc.get("exceptions"),
        "exceptions",
        EXCEPTIONS,
        errors,
    )
    for index, record in enumerate(exception_records):
        location = f"{EXCEPTIONS}.exceptions[{index}]"
        exception_id = _record_id(record, "id", "EXC", location, errors)
        if exception_id is None:
            continue
        if exception_id in exceptions_by_id:
            errors.append(f"{location}: duplicate exception ID {exception_id}")
        exceptions_by_id[exception_id] = record
        exceptions.add(exception_id)
        for affected in _string_list(
            record.get("affected_ids"),
            f"{location}.affected_ids",
            errors,
            required=True,
        ):
            if affected.startswith(("JRN-", "FEAT-", "SCREEN-", "FLOW-", "STATE-", "AC-")):
                known = known_objects | acs
                _require_ref(affected, known, location, errors)

    approvals, approval_load_errors = _approval_by_id(root)
    errors.extend(approval_load_errors)
    for exception_id, record in sorted(exceptions_by_id.items()):
        status = record.get("status")
        approval_id = record.get("approval_id")
        approval = approvals.get(str(approval_id))
        if status == "approved":
            if not isinstance(approval_id, str) or not valid_id(approval_id, "APR"):
                errors.append(
                    f"{EXCEPTIONS}.{exception_id}: approved exception needs approval_id"
                )
            elif approval is None:
                errors.append(
                    f"{EXCEPTIONS}.{exception_id}: approval {approval_id} does not exist"
                )
            elif (
                approval.get("kind") != "exception"
                or approval.get("decision") != "approved"
                or approval.get("subject_id") != exception_id
            ):
                errors.append(
                    f"{EXCEPTIONS}.{exception_id}: approval {approval_id} must be an "
                    "approved exception decision for this exception"
                )
        if require_release and status != "approved":
            errors.append(
                f"{EXCEPTIONS}.{exception_id}: release cannot contain a "
                f"{status!r} design exception"
            )

    gaps_by_id: dict[str, dict[str, Any]] = {}
    gap_records = _items(gaps_doc.get("gaps"), "gaps", GAPS, errors)
    for index, record in enumerate(gap_records):
        location = f"{GAPS}.gaps[{index}]"
        gap_id = _record_id(record, "id", "GAP", location, errors)
        if gap_id is None:
            continue
        if gap_id in gaps_by_id:
            errors.append(f"{location}: duplicate gap ID {gap_id}")
        gaps_by_id[gap_id] = record
        gaps.add(gap_id)
        for affected in _string_list(
            record.get("affected_ids"),
            f"{location}.affected_ids",
            errors,
            required=True,
        ):
            if affected.startswith(("JRN-", "FEAT-", "SCREEN-", "FLOW-", "STATE-", "AC-")):
                _require_ref(affected, known_objects | acs, location, errors)
        if record.get("status") not in ("open", "resolved", "rejected"):
            errors.append(f"{location}: invalid gap status {record.get('status')!r}")

    open_gaps = {
        gap_id for gap_id, record in gaps_by_id.items() if record.get("status") == "open"
    }
    blocked_objects = {
        object_id
        for object_id, status in coverage_status.items()
        if status == "blocked" and object_id in known_objects
    }
    for object_id in sorted(blocked_objects):
        if not any(
            gap_id in open_gaps
            and object_id in record.get("affected_ids", [])
            for gap_id, record in gaps_by_id.items()
        ):
            errors.append(
                f"{COVERAGE_MATRIX}.{object_id}: blocked object has no open GAP"
            )
    for gap_id, record in sorted(gaps_by_id.items()):
        if record.get("status") != "open":
            continue
        for affected in record.get("affected_ids", []):
            if affected in known_objects and coverage_status.get(affected) != "blocked":
                errors.append(
                    f"{GAPS}.{gap_id}: open gap affects {affected}, but coverage "
                    "does not mark it blocked"
                )

    state_blockers = _items(state.get("blockers"), "blockers", STATE_PATH, errors)
    blocker_ids: list[str] = []
    for index, blocker in enumerate(state_blockers):
        blocker_id = blocker.get("id")
        if not valid_id(blocker_id, "GAP"):
            errors.append(f"{STATE_PATH}.blockers[{index}]: invalid GAP ID {blocker_id!r}")
            continue
        blocker_ids.append(str(blocker_id))
        _require_ref(str(blocker_id), gaps, f"{STATE_PATH}.blockers[{index}]", errors)
    _set_mismatch(
        actual=blocker_ids,
        expected=open_gaps,
        location=f"{STATE_PATH}.blockers",
        errors=errors,
    )

    release_journeys = set(
        _string_list(release_doc.get("journey_ids"), f"{RELEASE_SCOPE}.journey_ids", errors)
    )
    release_features = set(
        _string_list(release_doc.get("feature_ids"), f"{RELEASE_SCOPE}.feature_ids", errors)
    )
    release_screens = set(
        _string_list(release_doc.get("screen_ids"), f"{RELEASE_SCOPE}.screen_ids", errors)
    )
    release_flows = set(
        _string_list(release_doc.get("flow_ids"), f"{RELEASE_SCOPE}.flow_ids", errors)
    )
    release_exclusion_records = _items(
        release_doc.get("exclusions"),
        "exclusions",
        RELEASE_SCOPE,
        errors,
    )
    release_exclusions: set[str] = set()
    for index, item in enumerate(release_exclusion_records):
        exclusion_id = item.get("id")
        reason = item.get("reason")
        if not isinstance(exclusion_id, str) or not exclusion_id:
            errors.append(f"{RELEASE_SCOPE}.exclusions[{index}].id: required")
        elif exclusion_id in release_exclusions:
            errors.append(
                f"{RELEASE_SCOPE}.exclusions[{index}]: duplicate {exclusion_id}"
            )
        else:
            release_exclusions.add(exclusion_id)
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{RELEASE_SCOPE}.exclusions[{index}].reason: required")
    for release_id in sorted(release_journeys):
        _require_ref(release_id, journeys, f"{RELEASE_SCOPE}.journey_ids", errors)
    for release_id in sorted(release_features):
        _require_ref(release_id, features, f"{RELEASE_SCOPE}.feature_ids", errors)
    for release_id in sorted(release_screens):
        _require_ref(release_id, screens, f"{RELEASE_SCOPE}.screen_ids", errors)
    for release_id in sorted(release_flows):
        _require_ref(release_id, flows, f"{RELEASE_SCOPE}.flow_ids", errors)
    _set_mismatch(
        actual=release_journeys,
        expected=covered_journeys,
        location=f"{RELEASE_SCOPE}.journey_ids",
        errors=errors,
    )
    _set_mismatch(
        actual=release_features,
        expected=covered_features,
        location=f"{RELEASE_SCOPE}.feature_ids",
        errors=errors,
    )
    _set_mismatch(
        actual=release_screens,
        expected={item for item in covered_slices if item in screens},
        location=f"{RELEASE_SCOPE}.screen_ids",
        errors=errors,
    )
    _set_mismatch(
        actual=release_flows,
        expected={item for item in covered_slices if item in flows},
        location=f"{RELEASE_SCOPE}.flow_ids",
        errors=errors,
    )
    _set_mismatch(
        actual=release_exclusions,
        expected=noncovered_objects,
        location=f"{RELEASE_SCOPE}.exclusions",
        errors=errors,
    )

    errors.extend(_audit_errors(root, state, require_release))

    if require_release:
        for object_id in sorted(known_objects):
            status = coverage_status.get(object_id)
            if status in ("blocked", "deferred"):
                errors.append(
                    f"{object_id}: release cannot include a {status} object"
                )
        scope_approvals = [
            record
            for record in approvals.values()
            if record.get("kind") == "scope"
            and record.get("decision") == "approved"
            if record.get("subject_path") == RELEASE_SCOPE
            and record.get("subject_id") == str(release_doc.get("release_id"))
        ]
        if not scope_approvals:
            errors.append(
                f"{RELEASE_SCOPE}: release scope has no current approved scope decision"
            )
        state_release = state.get("release")
        if not isinstance(state_release, dict):
            state_release = {}
        if state_release.get("approval_id"):
            release_approval = approvals.get(str(state_release["approval_id"]))
            if (
                release_approval is None
                or release_approval.get("kind") != "release"
                or release_approval.get("decision") != "approved"
            ):
                errors.append(
                    f"{STATE_PATH}: release.approval_id does not identify an "
                    "approved release decision"
                )

    summary = _scope_summary(
        journeys=journeys,
        features=features,
        slices=slices,
        states=states,
        specs=specs,
        acs=acs,
        tests=tests,
        gaps=gaps,
        exceptions=exceptions,
        require_release=require_release,
    )
    return list(dict.fromkeys(errors)), summary


def main() -> int:
    args = parse_args()
    try:
        errors, summary = validate_scope(
            Path(args.project_root),
            require_release=args.require_release,
        )
    except (OSError, DesignPactError) as exc:
        errors, summary = [str(exc)], {}
    payload = {
        "ok": not errors,
        "conclusion": "pass" if not errors else "fail",
        "errors": errors,
        "summary": summary,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
