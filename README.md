# Design Pact

Design Pact is a Codex skill for building Figma-driven, traceable Android
Jetpack Compose applications. It connects product scope, Figma evidence,
specifications, acceptance criteria, test contracts, TDD evidence, visual
verification, and release approvals.

The repository root is the installable skill directory. `SKILL.md` must stay at
the repository root so GitHub installers and other compatible agents can find
the skill.

## Requirements

- An agent that supports the `SKILL.md` skill format.
- Figma access for structured design evidence.
- For Android delivery: Java, an Android SDK, Gradle, and an emulator or device
  supported by the project's preflight checks.

Design Pact does not invent missing Figma pages, states, copy, interactions, or
assets. Missing evidence becomes a `GAP-###` and blocks the affected slice.

## Install in Codex From GitHub

This repository is private by default. Authenticate `gh` on the destination
machine first:

```bash
gh auth login
```

Install with Codex's bundled GitHub skill installer:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --repo Heass24/design-pact \
  --path . \
  --name design-pact \
  --ref main
```

Alternatively, clone the repository directly:

```bash
git clone https://github.com/Heass24/design-pact.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/design-pact"
```

The skill is available on the next Codex turn. Invoke it with:

```text
$design-pact
```

## Install in Another Skill-Compatible Agent

Place the repository contents in that agent's discovered skills directory,
keeping `design-pact/SKILL.md` at the directory root:

```text
<agent-skills-directory>/
└── design-pact/
    ├── SKILL.md
    ├── agents/
    ├── assets/
    ├── references/
    └── scripts/
```

Use the agent's documented skills location and discovery command. Design Pact
uses relative links to its `references/`, `assets/`, and `scripts/` directories,
so keep the complete directory tree together.

## Update an Installed Copy

For a direct clone:

```bash
git -C "${CODEX_HOME:-$HOME/.codex}/skills/design-pact" pull --ff-only
```

For the installer workflow, remove or move the existing installation before
reinstalling. The installer deliberately refuses to overwrite an existing skill
directory.

## Validate

From the repository root:

```bash
python3 scripts/validate_skill.py
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
```

The validation suite creates temporary projects and does not prove a live
Figma match, real-device behavior, or human visual approval.

## Third-Party Notices

The requirement-discovery guidance adapts selected concepts from GitHub Spec
Kit. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
