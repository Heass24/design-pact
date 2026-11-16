# Discovery and Scope Closure

Read this reference while establishing L0 and before declaring
`scope_defined`.

## Inputs

Collect or locate:

- application name, package intent, target users, and product goal;
- Figma file key, relevant pages/frames, and node scope;
- supported Android API range, orientation, locale, theme, and font-scale scope;
- launch inclusions, explicit exclusions, success criteria, and external
  dependencies;
- copy, assets, fonts, licenses, and interaction specifications;
- backend fixtures or network constraints needed for deterministic tests.

Do not infer a package name, user-facing copy, data behavior, or unsupported
state from visual similarity.

## Coverage Closure

Every known user-observable object enters `coverage-matrix.yaml`:

| Status | Meaning |
| --- | --- |
| `covered` | First-release scope with a complete intended trace |
| `out_of_scope` | Explicitly excluded with rationale |
| `deferred` | Planned later with target or trigger |
| `blocked` | Needed but waiting on a named input or decision |

Include screens, overlays, flows, applicable states, navigation, input
behavior, system behavior, and non-functional requirements. A state that is not
applicable still needs an explicit classification or a `not_applicable_reason`
on its parent.

Required state families to assess include loading, empty, content, error,
disabled, success, offline, permission, and confirmation. Include font scale,
TalkBack, dark mode, orientation, localization, deep links, storage/restore,
and back-stack behavior when applicable.

## Trace

```text
JRN → FEAT → SPEC-L1 → SCREEN/FLOW → STATE
→ SPEC-L2 → AC → TEST → IMPL/SHOT
```

For each covered screen/flow there is one L2 spec. Each covered state is bound
to at least one AC or a reviewed not-applicable reason. Each AC has at least one
test. Each test returns to an AC and an approved source. Each implementation or
visual evidence item traces back to the approved contract.

## Scope Review

Run the mechanical validator, then perform a source-first review:

1. Traverse every Figma page, frame, component state, and interaction.
2. Traverse every product goal and journey.
3. Compare the two directions to find missing or invented objects.
4. Confirm all exclusions and deferrals have rationale and human approval.
5. Record input revisions, findings, conclusion, reviewer, and decision in
   `scope-audit.md`.

When a new user-observable object appears, stop the active slice, record the
change, update L0/L1/L2/L3, re-audit, obtain approval, then restart TDD from the
new contract. Passing code does not legitimize an unapproved addition.
