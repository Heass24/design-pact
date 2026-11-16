# Visual Verification

Read this reference before capturing or approving screenshots.

## Keep Three Image Classes Separate

1. Figma reference: exported from a locked approved node/state.
2. Approved Compose baseline: implementation screenshot approved under fixed
   rendering conditions.
3. Current Compose screenshot: this run's candidate.

The Figma comparison proves design fidelity. The baseline comparison proves
regression stability. Never substitute one comparison for the other.

## Fixed Rendering Policy

Record renderer/version, Android API, dimensions, density, orientation, Compose
and screenshot-library versions, fonts, font scale, locale, theme, system bars,
fixtures, clock, timezone, network stubs, animation policy, approved masks,
comparison algorithms, and thresholds in `visual-policy.yaml`.

Default release thresholds:

- exact approved presence, order, and text for mapped elements;
- semantic tokens for color, typography, spacing, and shapes;
- key-region geometry error at most 4dp;
- Figma/current SSIM at least 0.98;
- Figma/current masked pixel difference at most 2%;
- baseline/current SSIM at least 0.995;
- baseline/current masked pixel difference at most 0.5%.

Any unapproved missing/extra key element or semantic mismatch fails regardless
of whole-page similarity. Projects may tighten thresholds. Relaxation, masks,
and exceptions require a decision and human approval.

## Capture and Review

1. Render the deterministic state.
2. Save current and difference images plus a manifest with hashes and metrics.
3. Compare to Figma and to the approved baseline separately.
4. Review key regions and semantic tree, not percentage alone.
5. Mark missing fonts, emulator, tooling, fixtures, or thresholds `unverified`.
6. Store the candidate baseline; never overwrite a locked one.
7. Obtain human/independent approval with subject hashes.

An unavailable visual check blocks `released`; prose such as “looks close” is
not evidence.
