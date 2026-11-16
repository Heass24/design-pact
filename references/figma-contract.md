# Figma Design Contract

Read this reference before extracting a design or creating design mappings.

## Evidence Rule

Prefer structured Figma file/page/frame/component/variable/style data from an
available Figma integration. Record file key, node ID, node name, revision or
snapshot time, and source URL for every screen and state.

A screenshot alone can produce a discovery report only. It cannot satisfy
`design_contract_ready` and cannot support a claim of high-fidelity
implementation. If the Figma integration is unavailable, stop that extraction
and mark the affected items `unverified`.

## Extraction Order

1. Lock the Figma file and root node scope.
2. Enumerate all screens, overlays, flows, states, and variants.
3. Extract layout hierarchy, auto-layout, constraints, and responsive rules.
4. Extract semantic variables/styles for color, type, spacing, shape, elevation,
   and motion.
5. Map components, variants, booleans, and text/property overrides.
6. Inventory icons, images, fonts, licenses, and export constraints.
7. Extract prototype interactions, destinations, back behavior, gestures,
   timing, and curves.
8. Export one reference image per covered state with deterministic node and
   export settings.
9. Compute and record image SHA-256 hashes.

## Mapping Files

- `screen-inventory.yaml`: every screen, overlay, entry, state, variant, node,
  and product trace.
- `component-map.yaml`: Figma component/variant to Compose composable, states,
  parameters, and reuse.
- `token-map.yaml`: Figma variable/style to semantic Compose token.
- `asset-inventory.yaml`: source node, target path, format, dimensions,
  license, and hash.
- `interaction-contract.md`: navigation, back, transitions, gestures, motion,
  and system behavior.
- `design-exceptions.yaml`: approved platform deviations with source and
  rationale.
- `gaps.yaml`: missing, conflicting, inaccessible, or unapproved inputs.

Do not create a UI component, token, icon, or string that has no approved
mapping. Do not use a visual guess to fill missing data.

## Gap Protocol

Create a `GAP-###` for missing pages, states, copy, assets, navigation, motion,
responsive behavior, dark mode, font-scale, localization, or accessibility
design. Choose one blocker class:

```text
blocked_by_design
blocked_by_product
blocked_by_content
blocked_by_asset
blocked_by_platform
```

The gap names its affected screen/state/AC, required input, owner, and recovery
condition. Until resolution, the affected L2 cannot enter TDD.

## Figma Reference Manifests

Each image records its artifact ID, screen/state, file key, node ID/name,
revision, export format/scale, pixel dimensions, SHA-256, source link, and
approval state. A placeholder image is never approved Figma evidence.
