# Evidence-Bounded Requirement Discovery

Read this after discovery and structured Figma extraction, and before drafting
L1/L2 specifications. It turns known product and design evidence into candidate
requirements, exposes gaps, and asks only questions that can materially change
scope, behavior, visual truth, or testability.

This workflow is native to Design Pact. Do not create an authoritative
Spec Kit-style `spec.md`, `plan.md`, or `tasks.md`, and do not start a second
planning pipeline. The canonical outputs remain the files defined in
`artifact-contract.md`.

## Inputs

Start from the current L0 sources and structured evidence:

- product goal, target users, success outcomes, inclusions, and exclusions;
- `JRN-###`, `FEAT-###`, `SCREEN-###`, `FLOW-###`, and `STATE-###` inventory;
- Figma node references, interaction behavior, components, tokens, and assets;
- platform, locale, theme, orientation, font-scale, accessibility, backend, and
  fixture constraints;
- existing `GAP-###` records and coverage classifications.

If a category has no source, do not fill it from convention. Record the missing
input as a gap and block every slice whose behavior depends on it.

## Evidence Discipline

Classify every statement before turning it into a requirement:

| Class | Meaning | Permitted use |
| --- | --- | --- |
| `observed` | Directly present in an approved Figma node or interaction | Bind it to the source ID and describe only what is visible |
| `stated` | Present in an approved product or technical source | Preserve its meaning and cite the source |
| `testable-derived` | A deterministic implication of known requirements | Use only when it adds no new user-observable behavior |
| `unknown` | No approved source establishes the fact | Do not write a requirement; create or update a `GAP-###` |

Never invent a screen, state, copy, data value, permission, navigation result,
interaction, asset, or visual treatment. A plausible platform convention is
still `unknown` until an approved source establishes it.

## Requirement Scan

For each covered journey, feature, screen, and flow, assess these categories.
Mark each category internally as clear, partial, or missing.

| Category | Resolve |
| --- | --- |
| Outcome and scope | Goal, actor, trigger, observable outcome, inclusions, exclusions, and release boundary |
| Journey and feature | Entry, sequence, completion, abandonment, dependencies, and cross-screen effects |
| States and interactions | Loading, empty, content, error, disabled, success, offline, permission, confirmation, retry, and cancellation where applicable |
| Data | Source, fixture, schema, identity, validation, boundaries, empty/null values, lifecycle, and failure |
| Navigation | Entry, exit, back, deep link, repeat action, restore, and back-stack behavior |
| Visual truth | Figma node, component, token, asset, adaptation, and baseline source |
| Accessibility | Semantics, labels, roles, focus order, target size, TalkBack, and font scale |
| Quality attributes | Measurable performance, reliability, security, privacy, localization, and observability constraints |
| External behavior | Service, permission, storage, network, timeout, conflict, and recovery behavior |
| Terminology | One canonical term per concept and no conflicting synonyms across sources |
| Testability | Deterministic precondition, action, observable result, fixture, clock, randomness, and locale |

Requirements state what must be true and why. Keep architecture, framework
selection, file layout, and task decomposition out of this pass; those belong
to Design Pact's design-system and TDD stages.

## Ambiguity Questions

Ask at most five questions per discovery pass. Ask one question at a time and
stop as soon as all material ambiguities are resolved.

Before asking, prioritize by:

```text
impact on scope, user-observable behavior, visual truth, or test design
× uncertainty
```

Each question must:

- be answerable with a short answer or two to five mutually exclusive options;
- identify the affected requirement or `GAP-###`;
- explain in one sentence why the answer changes the contract or tests;
- include a recommended answer and its reasoning when a recommendation is
  defensible.

A recommendation is a proposal, never an implied decision. If the answer
introduces a new screen, state, copy, asset, or interaction, the input still
requires an approved Figma source even when the user accepts the wording.

After each answer:

1. Update the canonical product or design source that owns the decision.
2. Resolve or narrow the related `GAP-###`.
3. Update coverage and affected transition records.
4. Recheck terminology and dependent journeys or states.

Do not preserve answers only in conversation. Do not create a free-standing
clarifications document as the source of truth.

If five questions are exhausted or the user cannot answer, leave the affected
item `blocked` with a precise recovery input. Asking no question is correct when
the evidence already closes the requirement.

## Canonical Write-Through

Map findings directly into the existing Design Pact artifacts:

| Finding | Canonical destination |
| --- | --- |
| Goal, users, success, inclusion, exclusion | `product-charter.md` and `release-scope.yaml` |
| Journey and feature intent | `journey-map.yaml`, `feature-map.yaml`, and L1 |
| Screen, flow, and state behavior | `screen-inventory.yaml`, L2, and related contracts |
| Missing or conflicting evidence | `gaps.yaml` plus affected coverage entries |
| Atomic observable result | L2 `acceptance_criteria` with an `AC-###` |
| Test objective | `test-cases.yaml` with a `TEST-###` |
| Unresolved decision | blocked `GAP-###`; never a guessed requirement |

Assign IDs through the project's artifact registry and preserve every existing
trace. Do not import a parallel numbering scheme.

## Completion Check

The discovery pass is complete only when:

- every candidate requirement cites an approved source or is marked unknown;
- every included and excluded item has an explicit coverage classification;
- every applicable state is represented or has a reviewed
  `not_applicable_reason`;
- every proposed AC has one deterministic observable outcome;
- every unresolved fact is a stable gap with a blocked slice and recovery input;
- no requirement silently relies on a guessed Figma state or business rule;
- the L1/L2 and test-intent drafts are ready for the normal
  `spec-quality.md` gate and human approval.

## Source Note

This reference adapts requirement-clarification concepts from GitHub Spec Kit,
not its command runtime or canonical artifact model. See
`THIRD_PARTY_NOTICES.md`.
