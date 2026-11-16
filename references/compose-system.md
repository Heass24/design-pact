# Compose System

Read this reference after the design contract is ready and before implementing
the design system or a page.

## Layers

1. Theme: semantic tokens for color, typography, spacing, shape, motion, and
   elevation.
2. Components: composables mapped from approved Figma components and variants.
3. Page: an L2 composition of approved components, layout rules, and state
   interactions.

Pages cannot bypass the theme with hard-coded colors, font sizes, spacing,
shapes, motion, or one-off visual effects.

## Token Rules

Use purpose-based names such as `color.surface.default`,
`space.content.horizontal`, and `type.body.primary`. When Figma variables exist,
bind each semantic token to the variable. A source token for a non-variable
value requires an approved design exception. A token name must describe purpose,
not a literal pixel or color value.

## Component Contract

Every reusable component:

- accepts `modifier: Modifier = Modifier` and applies it to its outer node;
- receives state and callbacks rather than owning navigation, network, or
  persistence side effects;
- implements only approved variants and states;
- exposes stable semantics for behavioral and accessibility tests;
- has previews for required states using deterministic fixtures;
- has behavior/accessibility tests and an approved visual baseline;
- exists only for repeated design structure, not speculative reuse.

## Page Sequence

1. Read the L2, state inventory, interaction contract, and mapped dependencies.
2. Confirm tokens, components, assets, and fixtures exist or are approved.
3. Create deterministic state and preview skeletons.
4. Write a minimal failing test for the next AC.
5. Implement the smallest UI that can satisfy it using approved layers.
6. Run behavior and accessibility tests.
7. Capture visual evidence against Figma and approved baselines.
8. Obtain independent review and lock the slice.

Adding a new component or token during a page requires returning to the design
contract, mapping the source, testing the component, and approving its baseline.
Do not hide a new design system inside a feature screen.

## Platform Quality

Use semantic roles and labels, a logical focus order, at least 48dp interaction
targets, approved contrast, and font-scale behavior. Apply dark mode,
orientation, localization, motion, and system-bar rules only from explicit
approved design states.
