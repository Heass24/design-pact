# Specification Quality

Read this reference when writing or reviewing L0-L4.
Use [requirement-discovery.md](requirement-discovery.md) after the evidence
inventory exists and before drafting L1/L2.

| Level | Unit | Required result |
| --- | --- | --- |
| L0 | Release | Goals, users, success, inclusions, exclusions, and closure |
| L1 | Journey/domain | Entry, outcome, screens, dependencies, and business rules |
| L2 | Screen/overlay/flow | States, data, navigation, visual, accessibility, and ACs |
| L3 | Atomic AC | Deterministic precondition, action, observable result |
| L4 | Test/implementation | Exactly which test and evidence proves each AC |

## Quality Gate

An L2/L3 passes only when all are true:

1. Sources identify product requirements and Figma nodes/states.
2. Scope lists included and excluded behavior.
3. Every applicable state, variant, permission, input, and error is explicit.
4. ACs use observable, deterministic language.
5. Data format, source, empty/null, length, and failure are defined.
6. Entry, exit, back, repeated action, and restoration are defined.
7. Figma node, tokens, key regions, adaptation, and assets are bound.
8. Semantics, focus order, labels, target size, and font scale are defined.
9. Every deviation has a design exception and approval.
10. Every AC has stable ID, at least one test, and implementation ownership.

Reject vague terms such as “correct,” “beautiful,” “smooth,” “responsive
enough,” or “handle errors” unless converted to a measurable condition.

## L2 Frontmatter

Use
`assets/project-docs-template/templates/SPEC-###-SCREEN-###-<slug>.md`.
The following fields are machine-validated:

```yaml
spec_id: SPEC-002
spec_level: L2
screen_ids: [SCREEN-001]
state_ids: [STATE-001, STATE-002]
ac_ids: [AC-001, AC-002]
approval_required: true
acceptance_criteria:
  - id: AC-001
    state_id: STATE-001
    title: Show the initial content state
    given: The approved content fixture is available
    when: The screen is opened
    then: The approved title and primary action are visible
    test_ids: [TEST-001]
    visual_required: true
```

The body explains business rules and references; frontmatter carries trace IDs.

## AC Rules

Each AC must have:

- one primary observable outcome;
- a state ID;
- deterministic fixture/time/locale assumptions;
- a testable boundary when an input or failure is involved;
- at least one behavior test unless the AC is solely visual;
- a visual shot ID when the result is visual.

Split compound ACs rather than allowing one test to prove several unrelated
outcomes. Tests may assert closely related ACs, but each contract objective
remains distinct.

## Definition of Ready

Do not enter TDD until:

- all applicable states and ACs are present;
- Figma evidence and mapped components/tokens/assets exist;
- no unresolved gap can change behavior or scope;
- fixtures, clocks, randomness, locale, and render configuration are fixed;
- each AC has a planned test objective;
- the spec is approved by someone other than its author.
