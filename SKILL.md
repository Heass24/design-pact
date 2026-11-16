---
name: design-pact
description: "Create a new Figma-driven Android Jetpack Compose app with SDD, design contracts, TDD evidence, strict scope control, and visual verification. Use when design fidelity matters and every screen, state, interaction, test, and screenshot must trace to approved Figma evidence."
metadata:
  short-description: "Figma-driven Android SDD + TDD delivery"
---

# Design Pact

Design Pact turns Figma into an executable design contract for new Android
Jetpack Compose applications. It establishes product scope, traces every screen
and state to approved acceptance criteria and tests, builds a token-driven
Compose system, and refuses release without build, behavior, visual,
accessibility, and scope evidence.

## Scope Boundary

The first release supports only a new Kotlin + Jetpack Compose application in
an empty output directory, with one `app` module and structured Figma evidence.
Do not apply this workflow silently to an existing repository, XML Views,
multi-module projects, Flutter, React Native, Web, iOS, or screenshot-only
designs. Explain the boundary and stop instead of weakening the contract.

## Non-Negotiable Contract

1. Figma nodes are design facts. Never invent a page, state, copy, asset,
   navigation path, interaction, or visual effect.
2. Every known user-observable object is `covered`, `out_of_scope`, `deferred`,
   or `blocked`. Unknown is not permission to proceed.
3. A missing required input creates a stable `GAP-###`; block the affected
   slice.
4. Do not implement UI until the relevant L2 contract and test-case contract
   pass their quality gates.
5. Capture every independently approved evidence event, including a valid Red
   followed by Green. Passing tests without a valid failing phase is not TDD
   evidence.
6. Keep YAML as structured truth, Markdown plus frontmatter as narrative truth,
   Kotlin tests as executable truth, and JSONL/images as append-only evidence.
7. Never hand-edit generated Markdown. Edit canonical sources, regenerate, and
   rerun gates.
8. AI may propose but may not approve product scope, the design contract,
   design gaps or exceptions, visual baselines, or release. These are five
   independent human approvals: `scope`, `design_contract`, `visual_baseline`,
   `exception`, and `release`. Evidence approvals such as `artifact` and
   `tdd_event` never substitute for any professional approval.
9. An unavailable tool or check is `unverified` or `blocked`; never report it as
   passed.

## State Machine

```text
discovery
→ scope_defined
→ design_contract_ready
→ project_initialized
→ design_system_ready
→ implementation
→ verification
→ released
```

Read `docs/project/state.yaml` before acting. Enter a state only after recording
its gate evidence. A `blocked` flag can exist in any state; clear it only when
the named owner and recovery input satisfy the recorded condition.

Return to `scope_defined` for a new user-observable object. Return to
`design_contract_ready` when Figma changes. Return to the affected L2 when a
specification conflicts with implementation or test evidence. Never advance
past a failed or unverified gate.

## Standard Route

1. Inspect the request and run:
   `python3 scripts/preflight.py --target <empty-dir>`
2. Bootstrap the empty destination with
   `python3 scripts/bootstrap_project.py ...`. This creates the Android
   project, the documentation skeleton, the Artifact ID registry, and
   bootstrap build evidence. The project state remains `discovery`; a
   successful bootstrap does not enter `project_initialized`.
3. Read [references/discovery.md](references/discovery.md). Establish the L0
   product scope, journeys, functions, screens, flows, states, interactions, and
   exclusions.
4. Read [references/figma-contract.md](references/figma-contract.md). Extract
   structured Figma nodes, variables, components, assets, and interactions.
   Create `GAP-###` records for every absence or conflict.
5. Read [references/requirement-discovery.md](references/requirement-discovery.md).
   Run an evidence-bounded requirement scan, clarify only the highest-impact
   ambiguities, and write unresolved facts to `GAP-###` records. Do not create
   a separate authoritative `spec.md` or a second planning workflow.
6. Read [references/spec-quality.md](references/spec-quality.md). Write L1/L2
   specifications and atomic ACs. Do not proceed if an AC is not observable or
   testable.
7. Define the test intent contracts, then run
   `python3 scripts/validate_scope.py --project-root <project>`.
8. After the scope and design-contract gates pass, record their evidence and
   enter `project_initialized`. Read
   [references/compose-system.md](references/compose-system.md). Build the
   semantic token and component layers before the page layer.
9. Add Kotlin tests matching each approved `test-cases.yaml` entry with the exact
   marker:
   `// DESIGN_PACT: TEST-001 => AC-001`
10. Read [references/tdd-evidence.md](references/tdd-evidence.md). Record a
   behavior-level Red, implement minimally, record Green, refactor, then verify.
11. Read [references/visual-verification.md](references/visual-verification.md).
    Capture differences against the Figma reference and regressions against an
    approved Compose baseline separately.
12. Regenerate human views with
    `python3 scripts/render_reports.py --project-root <project>`.
13. Run the artifact, scope, and release checks:

```bash
python3 scripts/validate_artifacts.py --project-root <project> --require-release
python3 scripts/validate_scope.py --project-root <project> --require-release
```

The `release` result is allowed only when every gate passes and all five
independent professional approvals are present for the exact current subject
hashes: `scope`, `design_contract`, `visual_baseline`, `exception`, and
`release`. One approval kind cannot satisfy another.

## Artifact Routing

Read [references/artifact-contract.md](references/artifact-contract.md) before
creating, moving, or validating any project artifact. It defines the sole
authority for each file, required metadata, hashes, generated views, and the
human intervention path.

- Use `scripts/preflight.py` before bootstrap and again when the environment
  changes.
- Use `scripts/bootstrap_project.py` only for a new empty destination.
- Use `scripts/validate_artifacts.py` for paths, metadata, source freshness,
  test markers, binary manifests, and generated-view drift.
- Use `scripts/validate_scope.py` for ID integrity, coverage, traceability, and
  release blockers.
- Use `scripts/record_tdd_evidence.py` to execute and append test evidence.
- Use `scripts/render_reports.py` to rebuild test-case documents, TDD reports,
  artifact index, and documentation navigation.
- Use `scripts/validate_skill.py` only to regression-test this skill in a
  temporary directory.

## Test-Case Documents

Every covered L2 has both:

```text
docs/verification/test-cases/SCREEN-###-<slug>/test-cases.yaml
docs/verification/test-cases/SCREEN-###-<slug>/test-cases.md
```

The YAML is canonical intent. Kotlin is executable behavior. The JSONL ledger is
execution evidence. The per-page Markdown is a generated, standalone human
view. It must show passing, failing, blocked, unverified, planned, deferred, and
out-of-scope tests rather than hiding anything behind a total.

If the user asks to change a test result, trace the request to an approved
specification or design decision, edit the canonical source, regenerate, and
rerun evidence. Never edit `test-cases.md` directly.

## Stop Conditions

Stop the affected work and report the exact recovery input when:

- the target directory is not empty;
- the app name, package, or path is invalid;
- structured Figma nodes are unavailable;
- a required page, state, copy, asset, navigation rule, or interaction is
  missing;
- product and design sources conflict;
- a new user-observable behavior appears during implementation;
- a test is unstable, cannot run, or lacks valid Red/Green evidence;
- test IDs, ACs, implementation paths, or source hashes disagree;
- generated views are stale or manually changed;
- a visual baseline is unapproved or a required rendering tool is unavailable;
- a state-entry gate lacks recorded evidence.

The failure report must name the location, affected IDs, checks already tried,
why progress is unsafe, and the precise user decision or missing input required.
