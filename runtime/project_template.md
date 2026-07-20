<!-- Generated from scripts/project_contract_model.py; do not edit directly. -->
<!-- mpa-project-contract-format: 2 -->
# Runtime Project Contract Template

<!-- mpa-clause-projections: msa-2-6 msa-article-5 msa-article-6 msa-article-9 -->
Recommended output filename: `AGENT_PROJECT.md`
Source: distilled from `STATEMENT_OF_WORK.md`

Project: [PROJECT NAME]
Date: [YYYY-MM-DD]

This file contains only active runtime facts projected from STATEMENT_OF_WORK.md plus the non-authoritative framework-reference binding in Framework Verification.
Omit inactive optional sections and rows plus model-owned default Definition values. Retain every required core section, exact resolved or minimally deferred command row, non-default runtime fact, and structured minimal-mode deferral.

Authority: Generated projection, not independent authority. `STATEMENT_OF_WORK.md` governs conflicting project terms. Never hand-edit this file.

## Active Stack

- Languages and frameworks: [active stack]
- Architecture: [active architecture]
- Key dependencies: [only when active]
- Key directories: [only when operationally relevant]

## Active Project Modules

- Annex A — Agent Profile (SOUL.md): [existing project-relative file]
- Annex B — Agent Qualifications (CAPABILITIES.md): [existing project-relative file]
- Annex C — Scope of Authority (AUTHORITY.md): [existing project-relative file]
- Annex D — Security Policy (SECURITY.md): [derived from Security Policy File]

## Project Vocabulary

- [term] — [project meaning] — [ambiguity to avoid]

## Common Commands

- Development: [command or none]
- Build: [command or none]
- Regenerate artifacts: [command or none]
- Test: [command or none]
- Lint: [command or none]
- Type check: [command or none]
- Deploy: [command or none]

## Framework Verification Commands

- Framework reference: [framework reference]
- Framework Verification Runner: [confirmed framework verification runner]
- Run from the project root; the routine gate calls the framework-owned aggregate checker through the framework reference. Use its named child checks only for setup or diagnosis.
- Core conformance: [confirmed framework verification runner] [framework reference]/scripts/conformance_check.py --profile core-project --root . --project-kind downstream
- Runner fallback: do not silently replace the configured runner. If it is unavailable, stop and resolve the project runner requirement; when available, its prerequisite command is [confirmed framework verification runner] [framework reference]/scripts/check_prereqs.py.

## Active Deliverables

1. [deliverable] — [verification] — [pass criteria]

## Acceptance Checklist

- [ ] [objective or explicitly manual acceptance criterion]

## Active Scope

In scope:
- [active scope]

Out of scope:
- [active exclusions]

## Active Workflows

- [name]: load the same-named SOW Workflows entry when [trigger] — [active control, ownership, verification, and stop facts]

## Review Routing

- [active review override or canonical SOW route]

## Canonical Detail Routes

- [task trigger]: load [same-named SOW entry] before governed work

## Minimal Bootstrap Deferrals

- Field: [field] — Owner: [owner] — Reason: [reason] — Boundary Type: [type] — Closure Boundary: [boundary].

## Non-Negotiable Constraints

- [active constraint]

## Applicable Standards

- [project-specific standard and version/date scope]

## Critical Surfaces

- [surface] — [risk] — [review burden]

## Security Policy

- [project-specific term copied from the SOW]

## Version Control Profile

- [active VCS fact] — [policy or evidence]

## Memory Boundary

- [active memory boundary]

## Verification Profiles

- [profile] — [checks] — [trigger]

## Approval Boundaries

- [action requiring approval]

## Acquisition Boundary

- [approved source/acquisition/egress/data boundary]

## Definitions

- Agent: [selected coding runtime or agent]
- Bootstrap Mode: [full or minimal]
- Execution Mode: [act / advise / ask-when-ambiguous]
- Decision Boundary: [approved implementation discretion and explicit approval limits]
- Dependency Rule: [no-external-dependencies / justify-external-dependencies]
- External Source Rule: [independent implementation and approved license/attribution boundary]
- Secret Store: [approved secret store or none required]
- Credential Delivery: [approved delivery mechanism or none]
- Memory Boundary: [disabled or approved store/write/review/retention boundary]
- Source Freshness Rule: [primary-source and version-scope rule]
- Precedent File: [PRECEDENTS.md or none]
- Framework Feedback File: [FRAMEWORK_FEEDBACK.md or none]
- Reviewer Lane Feedback File: [REVIEWER_LANE_FEEDBACK.md or none]
- Source Packs File: [SOURCE_PACKS.md or none]
- Source Update File: [SOURCE_UPDATE.md or none]
- Source Monitor Researcher Brief: [SOURCE_MONITOR_RESEARCHER.md or none]
- Reviewer Lane Inventory: [private path / project-local file / none]
- Default Review Topology: [none or approved named profile]
- Arbitration Panel: [framework default or custom package]
- Direct Panel Rules: [none or compact direct-routing categories]
- Independent Assessment Approval: [Required / Autonomous]
- Standing Panel Convocation Approval: [No / Yes, limited to: ...]
- Security Policy File: [none / project SECURITY.md / inline in this SOW]
- Security Verification File: [SECURITY_VERIFICATION.md or none]
- Source Registry Scope: [active only with SOURCE_UPDATE.md]
- Source Review Cadence: [active only with SOURCE_UPDATE.md]
- Source Monitor Role: [active only with SOURCE_MONITOR_RESEARCHER.md]
- Source Monitor Instruction Sources: [active only with SOURCE_MONITOR_RESEARCHER.md]
- Source Monitor Source Data: [active only with SOURCE_MONITOR_RESEARCHER.md]
- Source Monitor Boundary: [active only with SOURCE_MONITOR_RESEARCHER.md]
- Security Verification Profile Scope: [active only with SECURITY_VERIFICATION.md]
- Security Verification Target Policy: [active only with SECURITY_VERIFICATION.md]
- Automation Orders File: [AUTOMATION_ORDERS.json or none]
- Version Review Rule: [pinned-version review and upgrade-decision rule]
- Critical Surface Rule: [classification and stronger-review rule]
- Version Control Rule: [approved VCS posture]
- Branch Rule: [current/default/protected branch posture]
- Backout Rule: [reversible fix and destructive-action approval rule]
- Framework Verification Runner: [exact qualified runner established by the successful prerequisite diagnostic]
- Package Manager: [approved tool or none]
- Language/Runtime Standards: [version, edition, SDK/target, dialect, and pin status]
- AI Disclosure: [none or required wording/location]

## Command Restrictions

- [command] — never run — [reason] — use [alternative] instead

## Auxiliary Tools

- [integration] — [purpose] — load the same-named SOW Auxiliary Tools entry before use — [use trigger / approval / control role]

## Loading Rule

_Blueprint-only authoring guidance; concrete generated contracts retain only applicable facts and operative rules._
- Delete unused sections, leave no placeholder prose, and keep the concrete contract factual and short.
- Record auxiliary-integration facts only to the bounded purpose, reference, capability, permission, provenance, credential, data, effect, persistence, trust, approval, version, audit, rollback, and control-coverage surfaces that apply.
- Record source-freshness facts as source, version or date scope, and approved acquisition method; do not copy documentation into the contract.
- Keep Project Vocabulary to terms that reduce operational ambiguity; do not turn it into an implementation specification.
- Keep scope and critical-surface facts explicit; represent unresolved minimal-mode facts as structured deferrals rather than placeholder Definitions.
- Keep active VCS, release, rollback, and memory-boundary facts concise; detailed history and standing policy remain in their owning project surfaces.

- After context compaction, restart, or handoff, reload this file from disk; do not rely on summaries.
- Resolve Active Project Modules references from the project root. Load Scope of Authority before any action and each other listed module before work governed by its subject; after compaction, restart, or handoff, reload applicable modules before resuming that work.
- Active Workflows, Auxiliary Tools, Review Routing, and Canonical Detail Routes are indexes, not complete procedures. Before executing a workflow, invoking a tool, convening custom review, or using routed canonical detail, load the same-named STATEMENT_OF_WORK.md entry.
- If this file conflicts with STATEMENT_OF_WORK.md, the SOW governs; stop relying on the conflicting projection. Diagnose and correct a generated contract, framework-reference binding, or generated optional-state lifecycle only through the selected framework's `task_orders/framework_refresh.md` route; never hand-edit managed projections or add or retire generated state ad hoc.
- Preserve the exact framework-generated origin marker when editing receipt-declared mutable state.
- Keep project-specific rules in this contract rather than growing the runtime entrypoint unless that entrypoint itself must carry the rule.
