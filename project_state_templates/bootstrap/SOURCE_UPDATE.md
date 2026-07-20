<!-- mpa-generated-state-origin: master-prompt-agreement/project-state/v1 -->

# Source Update Plan

Project-local source-update state for source-sensitive work.

## Update Policy

- Source Acquisition Boundary: use the project contract
- Approved Check Method: project-approved local or external acquisition only
- Egress Boundary: use only approved endpoints, tools, or user-supplied artifacts
- Source Registry Scope: {{SOURCE_REGISTRY_SCOPE}}
- Default Review Cadence: {{SOURCE_REVIEW_CADENCE}}
- Volatility Model: classify per source before adopting changes
- Version Review Rule: {{VERSION_REVIEW_RULE}}
- Approval Boundary: material version, dependency, migration, feature, deployment, or irreversible changes require approval
- Output Location: TODO.md for unresolved work; DECISIONS.md for durable decisions

## Source Registry

Use SOURCE_PACKS.md for durable source identity, tier, scope, volatility, and action rules. Before doing new external research for a source family, check SOURCE_PACKS.md and any approved shared framework source reference.

When adding Source Registry rows, set `Monitoring Mode` to exactly `recurring` or `one_off`. Only `recurring` rows create source-root coverage obligations; keep schedule or trigger detail in `Cadence` without using it to imply the mode. Omit disabled sources and record unresolved acquisition gaps under `Open Gaps`.

## Recent Checks

Keep one current summary per source surface. Replace closed superseded checks
after their result is represented by the owning registry, decision,
implementation, or retained verification evidence.

- None.

## Open Gaps

- None.

## Framework Source Feedback

- None.
