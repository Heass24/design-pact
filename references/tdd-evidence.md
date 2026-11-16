# TDD Evidence

Read this reference before creating executable tests or validating a Red/Green
chain.

## Test Intent Before Code

For each AC, create an entry in `test-cases.yaml`. Each `TEST-###` has one
primary verification objective and records:

```text
test_id, ac_ids, state_ids, title, test_type, priority,
precondition, test_data, action, expected,
accessibility_assertions, visual_shot_ids,
implementation_path, implementation_symbol
```

Then add the matching marker immediately above the Kotlin test:

```kotlin
// DESIGN_PACT: TEST-001 => AC-001,AC-002
@Test
fun approvedTitleIsVisible() { ... }
```

Never change a test expectation to make an unapproved implementation pass.

## Valid Cycle

| Phase | Required fact | Valid exit |
| --- | --- | --- |
| Red | Behavior assertion is absent/incorrect | Non-zero, behavior-level assertion failure |
| Green | Minimal implementation | Zero for the same test declaration |
| Refactor | Behavior assertions unchanged | Zero full relevant suite |
| Verify | Boundary/error/accessibility/visual additions | Zero plus review evidence |

Syntax, compilation, environment, missing dependency, or test setup failure is
not a valid Red. Record the failure class and reject it.

Tests must assert observable behavior, not private structure or mock calls
alone. They must be deterministic, independent of execution order and external
network state, and retain equivalent behavior assertions after refactoring.

## Ledger

Use:

```bash
python3 scripts/record_tdd_evidence.py \
  --project-root <project> \
  --spec-id SPEC-001 \
  --test-id TEST-001 \
  --ac-id AC-001 \
  --phase red \
  --command-json '["/path/to/project/gradlew",":app:testDebugUnitTest","--tests","*HomeScreenTest"]' \
  --failure-kind behavior
```

Repeat for `green`, `refactor`, and `verify`, omitting `--failure-kind`.

The script runs without a shell, stores combined output in
`tdd-artifacts/`, computes file and declaration hashes, appends a hash-chained
JSONL event, and enforces phase/exit-code rules. Every TDD event is permanently
`captured`; acceptance or rejection is a separate, independently approved
record in `docs/project/approvals.jsonl`. The release gate requires an approved
approval for each event in the qualifying cycle.

## Coverage Gate

- Every covered page has an L2.
- Every covered state has an AC or reviewed not-applicable reason.
- Every AC has a valid accepted behavior test.
- Every `TEST-###` agrees across YAML, Kotlin marker/symbol/path, and ledger.
- Every test document is regenerated from current sources.
- Every visual AC has approved visual evidence.

Line coverage is diagnostic only. Never let a high total hide an uncovered
state or missing test.
