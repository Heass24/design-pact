# Artifact Contract

This file is the source of truth for project-artifact paths and authority.

## Authority Model

| Class | Default format | Authority |
| --- | --- | --- |
| Structured facts | YAML | Scope, design mapping, test intent, state, and indexes |
| Narrative decisions | Markdown + YAML frontmatter | Business rules, boundaries, rationale, and review |
| Executable behavior | Kotlin / Compose | Actual application and test behavior |
| Immutable evidence | JSONL, PNG/WebP, SHA-256 | Execution history and rendered evidence |
| Human views | Generated Markdown | Read-only projections of canonical sources |

Word, Excel, PDF, HTML, and screenshots supplied by a user may be exports or
source inputs, but they must not become a second editable workflow authority.
Create an explicit export only when requested.

## Required Tree

```text
docs/
├── README.md
├── project/
│   ├── state.yaml
│   ├── artifact-ids.yaml
│   ├── artifact-index.yaml
│   ├── approvals.jsonl
│   └── decisions/DEC-###-<slug>.md
├── product/
│   ├── product-charter.md
│   ├── release-scope.yaml
│   ├── journey-map.yaml
│   ├── feature-map.yaml
│   └── coverage-matrix.yaml
├── design/
│   ├── screen-inventory.yaml
│   ├── component-map.yaml
│   ├── token-map.yaml
│   ├── asset-inventory.yaml
│   ├── interaction-contract.md
│   ├── design-exceptions.yaml
│   ├── gaps.yaml
│   └── figma-references/SCREEN-###-<slug>/manifest.yaml
├── specs/
│   ├── L1/SPEC-###-JRN-###-<slug>.md
│   └── L2/SPEC-###-SCREEN-###-<slug>.md
└── verification/
    ├── test-cases/
    │   ├── index.md
    │   └── SCREEN-###-<slug>/
    │       ├── test-cases.yaml
    │       └── test-cases.md
    ├── tdd-ledger.jsonl
    ├── tdd-artifacts/
    ├── tdd-report.md
    ├── bootstrap/
    │   ├── manifest.yaml
    │   ├── gradle-wrapper.log
    │   └── android-build.log
    ├── scope-audit.md
    ├── visual-policy.yaml
    ├── visual-reports/SCREEN-###-<slug>/
    │   ├── manifest.yaml
    │   ├── current/
    │   ├── diff/
    │   └── report.md
    └── baselines/SCREEN-###-<slug>/
        ├── manifest.yaml
        └── images/
```

Stable IDs, not path slugs, define identity. A slug may change without changing
`SPEC-###`, `TEST-###`, `STATE-###`, or another stable ID.

`docs/project/artifact-ids.yaml` is the complete, stable Artifact Registry. It
contains every active artifact entry and every tombstone, including retired
paths and IDs that must never be reused. `docs/project/artifact-index.yaml` is
not the registry: it is a generated, read-only index of the currently rendered
Markdown views and their file hashes. Missing an entry from the generated index
does not remove it from the registry, and deleting a generated view must not
delete its stable identity.

## File-Level Rules

| Artifact | Format | Authority | Required validation |
| --- | --- | --- | --- |
| `docs/project/state.yaml` | YAML | canonical | Schema, state entry evidence, blockers |
| `docs/project/artifact-ids.yaml` | YAML | canonical registry | Complete active entries and tombstones; stable IDs are never reused |
| `docs/project/artifact-index.yaml` | YAML | generated view | Current generated Markdown paths and file hashes only |
| `docs/project/approvals.jsonl` | JSONL | canonical evidence | Append-only, subject hash, human approver |
| `docs/project/decisions/DEC-###-*.md` | Markdown + frontmatter | canonical | Background, alternatives, decision, impact, approval |
| `docs/product/product-charter.md` | Markdown + frontmatter | canonical | Users, goals, success, exclusions |
| `docs/product/*.yaml` | YAML | canonical | IDs, states, references, scope closure |
| `docs/design/*.yaml` | YAML | canonical | Figma nodes, gaps, exceptions, assets |
| `docs/design/interaction-contract.md` | Markdown + frontmatter | canonical | Navigation, back, transitions, motion, system behavior |
| `docs/design/figma-references/**` | Manifest + images | canonical evidence | Node/state/version/export/hash |
| `docs/specs/L1/*.md` | Markdown + frontmatter | canonical | Journey, rules, page list, approval |
| `docs/specs/L2/*.md` | Markdown + frontmatter | canonical | Complete states, data, navigation, visual, accessibility, ACs |
| `.../test-cases.yaml` | YAML | canonical intent | AC/state coverage and implementation binding |
| `.../test-cases.md` | Markdown | generated view | Source hash and every result category |
| `.../test-cases/index.md` | Markdown | generated view | Project-wide coverage and unresolved items |
| Kotlin test files | Kotlin | executable | Marker, symbol, path, AC IDs |
| `docs/verification/tdd-ledger.jsonl` | JSONL | canonical evidence | Append-only hash chain and phase validity |
| `docs/verification/tdd-artifacts/**` | Log/JSON/text | evidence | SHA-256 referenced by ledger |
| `docs/verification/tdd-report.md` | Markdown | generated view | Rebuilt from ledger and test contract |
| `docs/verification/bootstrap/manifest.yaml` | YAML | generated evidence manifest | Initial JSON-free command array, exit code, time, log hash, and toolchain paths |
| `docs/verification/bootstrap/*.log` | Text log | generated evidence | SHA-256 referenced by the bootstrap manifest |
| `docs/verification/scope-audit.md` | Markdown + frontmatter | reviewed report | Inputs, findings, conclusion, reviewer |
| `docs/verification/visual-policy.yaml` | YAML | canonical | Fixed rendering, thresholds, masks, exceptions |
| `docs/verification/visual-reports/**` | YAML/PNG/WebP/Markdown | evidence + view | Reference, current, diff, metrics, status |
| `docs/verification/baselines/**` | YAML/images | approved evidence | Human approval, hashes, rendering config |
| `docs/README.md` | Markdown | generated view | Navigation to all authoritative and human-view files |

## Metadata

Every authored canonical YAML and Markdown artifact starts with:

```yaml
artifact_id: ART-001
artifact_type: project_state
schema_version: "1.0"
version: 1
owner: human-name-or-role
created_at_state: discovery
status: draft
source_ids: []
upstream_sha256: ""
approval_required: true
```

Allowed authored status is `draft`, `review`, `approved`, `blocked`, `removed`,
or `superseded`. Approval status needs a matching approval record.

Generated views add:

```yaml
generator: render_reports.py
generated_from: [relative/path.yaml, relative/path.md]
source_sha256: sha256-of-canonical-inputs
generated_at: ISO-8601 timestamp
```

A generated view is current only when recomputing its `source_sha256` produces
the same value and `artifact-index.yaml` hashes the view as currently stored.

Binary evidence is described by a manifest containing `artifact_id`,
`artifact_type`, `path`, `sha256`, upstream IDs, approval ID when relevant, and
format version. Hashes are lowercase 64-character SHA-256.

## Test-Case Contract

Each `TEST-###` has exactly one primary verification objective and one or more
ACs. At minimum:

```text
test_id, ac_ids, state_ids, title, test_type, priority,
precondition, test_data, action, expected,
accessibility_assertions, visual_shot_ids,
implementation_path, implementation_symbol
```

Allowed `test_type` values are `unit`, `component`, `ui`, `integration`,
`visual`, and `accessibility`.

Kotlin position marker:

```kotlin
// DESIGN_PACT: TEST-031 => AC-017,AC-018
@Test
fun submitWithoutEmailShowsRequiredError() {
    // assertion
}
```

The marker must be immediately adjacent to the test declaration. The path and
symbol in `test-cases.yaml` must agree with source.

## Generated Test Documents

Each `SCREEN-###/test-cases.md` must contain:

1. Sources, SPEC, SCREEN, spec version, and generation time.
2. Covered states, ACs, test counts, and current gate conclusion.
3. A test table with title, type, priority, precondition, data, action, and
   expected result.
4. Links to AC, state, implementation, symbol, and visual evidence.
5. Red, Green, Refactor, and Verify evidence summaries.
6. Passing, failing, blocked, unverified, planned, deferred, and out-of-scope
   items.
7. Reasons for deferral or exclusion.
8. A human-review checklist and links to sources.

The project `test-cases/index.md` lists every page and the same unresolved
categories. Missing pages in this index are a gate failure.

## Human Intervention

1. Open `docs/README.md`.
2. Open `docs/verification/test-cases/index.md`.
3. Open the affected page's `test-cases.md`.
4. Follow its source links to the L2 spec, `test-cases.yaml`, Kotlin test, and
   TDD ledger.
5. For a scope/design change, create or update `DEC-###`, then append a human
   approval with the subject hash.
6. Edit the canonical source. Never edit a generated view.
7. Run `render_reports.py`, then artifact, scope, TDD, and visual gates.

Generated reports must show their source paths, source hash, and regeneration
command. A manual edit is invalid even if its prose looks plausible.

## Bootstrap Evidence

`bootstrap_project.py` writes `docs/verification/bootstrap/manifest.yaml` and
the referenced command logs. The manifest records the Android SDK, Java, Gradle
launcher, exact argument arrays, real exit codes, timestamps, and log hashes.
Bootstrap never advances `docs/project/state.yaml` beyond `discovery`: it
prepares an inspectable project, not an approved product or design contract.
