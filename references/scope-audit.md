# Scope Audit

Mechanical validation cannot prove Figma traversal was complete. Use this
reference for the independent source review and scope-change protocol.

## Forward Traversal

Start from the approved Figma file and product charter:

1. Enumerate every in-scope page, frame, overlay, variant, and component state.
2. Enumerate every interaction, navigation edge, permission prompt, and system
   behavior described by the design.
3. Check each item against `screen-inventory.yaml` and
   `coverage-matrix.yaml`.
4. Record absent items as a gap or add them to scope with approval.

## Reverse Traversal

Start from every implementation/evidence item and product goal:

1. Find its source AC, state, screen, L1, function, and journey.
2. Confirm the source is approved and in first-release scope.
3. Flag orphaned ACs, tests, screens, components, tokens, or screenshots.
4. Remove unsupported UI or return to scope definition; do not preserve it
   merely because tests pass.

## Review Record

`docs/verification/scope-audit.md` must record:

- audit ID and revision;
- Figma file/node revisions and product input revision;
- reviewer identity;
- exact traversal scope;
- mechanical commands and outcomes;
- findings with affected IDs;
- conclusion `pass`, `fail`, or `unverified`;
- approvals and unresolved blockers.

A review cannot conclude `pass` with an unchecked area. If a source is
inaccessible, the conclusion is `unverified`.

## Change Protocol

On discovering a new screen, state, interaction, copy, asset, or visual effect:

1. Freeze additions to the current slice.
2. Append a decision/change record with source, user impact, and reason.
3. Update coverage and the applicable L0-L3 contract.
4. Update tests only after the specification change is approved.
5. Re-run scope and artifact validation.
6. Return to implementation only after approval and a refreshed Definition of
   Ready.

Use `validate_scope.py --require-release` for the hard gate. Approval cannot be
inferred from test success, an existing screenshot, or the AI's own review.
