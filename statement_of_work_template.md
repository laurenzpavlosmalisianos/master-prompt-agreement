<!-- Generated from scripts/project_contract_model.py; do not edit directly. -->
<!-- mpa-project-contract-format: 2 -->
Statement of Work — [PROJECT NAME]

Recommended output filename: `STATEMENT_OF_WORK.md`

SOW Version: [version]  MSA Reference: master_service_agreement.md [version]  Date: [YYYY-MM-DD]

Only omitted optional governance terms fall back to framework defaults. Required project facts must be stated or represented by their canonical structured deferral in minimal mode; a bare TBD is not a substitute for a required structured deferral.

This generated blueprint is the human-readable projection of the declarative contract model in `scripts/project_contract_model.py`. `scripts/project_bootstrap.py` renders concrete values; do not invent unsupported answer keys or treat unfilled placeholders as policy.

Definitions

This section is a compact index of project terms. Dedicated sections below are authoritative for detailed command, workflow, source, memory, VCS, and verification policy.

Agent: [selected coding runtime or agent]
User: [project label; default User]
Bootstrap Mode: [full or minimal]
Execution Mode: [act / advise / ask-when-ambiguous]
Decision Boundary: [approved implementation discretion and explicit approval limits]
Dependency Rule: [no-external-dependencies / justify-external-dependencies]
External Source Rule: [independent implementation and approved license/attribution boundary]
Secret Store: [approved secret store or none required]
Credential Delivery: [approved delivery mechanism or none]
Memory Boundary: [disabled or approved store/write/review/retention boundary]
Source Freshness Rule: [primary-source and version-scope rule]
Precedent File: [PRECEDENTS.md or none]
Framework Feedback File: [FRAMEWORK_FEEDBACK.md or none]
Reviewer Lane Feedback File: [REVIEWER_LANE_FEEDBACK.md or none]
Source Packs File: [SOURCE_PACKS.md or none]
Source Update File: [SOURCE_UPDATE.md or none]
Source Monitor Researcher Brief: [SOURCE_MONITOR_RESEARCHER.md or none]
Reviewer Lane Inventory: [private path / project-local file / none]
Default Review Topology: [none or approved named profile]
Arbitration Panel: [framework default or custom package]
Direct Panel Rules: [none or compact direct-routing categories]
Independent Assessment Approval: [Required / Autonomous]
Standing Panel Convocation Approval: [No / Yes, limited to: ...]
Security Policy File: [none / project SECURITY.md / inline in this SOW]
Security Verification File: [SECURITY_VERIFICATION.md or none]
Source Registry Scope: [active only with SOURCE_UPDATE.md]
Source Review Cadence: [active only with SOURCE_UPDATE.md]
Source Monitor Role: [active only with SOURCE_MONITOR_RESEARCHER.md]
Source Monitor Instruction Sources: [active only with SOURCE_MONITOR_RESEARCHER.md]
Source Monitor Source Data: [active only with SOURCE_MONITOR_RESEARCHER.md]
Source Monitor Boundary: [active only with SOURCE_MONITOR_RESEARCHER.md]
Security Verification Profile Scope: [active only with SECURITY_VERIFICATION.md]
Security Verification Target Policy: [active only with SECURITY_VERIFICATION.md]
Automation Orders File: [AUTOMATION_ORDERS.json or none]
Version Review Rule: [pinned-version review and upgrade-decision rule]
Critical Surface Rule: [classification and stronger-review rule]
Version Control Rule: [approved VCS posture]
Branch Rule: [current/default/protected branch posture]
Backout Rule: [reversible fix and destructive-action approval rule]
Test Command: [see Build and Development Commands]
Lint Command: [see Build and Development Commands]
Type Check Command: [see Build and Development Commands]
Framework Verification Runner: [exact qualified runner established by the successful prerequisite diagnostic]
Package Manager: [approved tool or none]
Language/Runtime Standards: [version, edition, SDK/target, dialect, and pin status]
AI Disclosure: [none or required wording/location]

Arbitration Panel

_Delete if framework defaults apply._
Seat 1: [model] — [role] — [focus]
Quorum: [exact rule]
Recommendation threshold: [exact rule]
Failure handling: [exact rule]
Tie handling: [exact rule]
No-majority handling: [exact rule]
Abstention handling: [exact rule]
Unavailable-panelist handling: [exact rule]
Binding effect: [recommendation or delegated authority]
Ratification or accountable owner: [owner]
Appeal or override path: [exact rule]

Direct Panel Rules

_Delete if no categories route directly to panel._
- [dispute category]
Standing Panel Convocation Approval: [No / Yes, limited to: ...]

Independent Assessment

_Delete to use the framework default._
Independent Assessment is an advisory review by a fresh agent for focused technical uncertainty before a dispute exists. It does not adjudicate a contested issue.
Independent Assessment Approval: [Required / Autonomous]

Recitals

[What the project is, what it does, and who it serves.]

Project Vocabulary

- [term] — [project meaning] — [aliases or ambiguity to avoid]

Scope

In scope:
- [approved work]

Out of scope:
- [excluded work]

Minimal Bootstrap Deferrals

_Use only in minimal mode._
- Field: [canonical field] — Owner: [owner] — Reason: [reason] — Boundary Type: [date | milestone | event] — Closure Boundary: [boundary].

Technical Specifications

Tech stack: [active stack]

Architecture: [active architecture]

Key dependencies: [dependencies or none]

Key directories: [directories or none]

File structure:
[operationally relevant paths]

Representative Pattern Sources

- [path or reference] — [represented pattern] — [normative / illustrative]

Deliverables and Acceptance Tests

1. [deliverable] — [verification] — [pass criteria]

Acceptance Checklist (per deliverable)

- [ ] [objective or explicitly manual acceptance criterion]

Project-Specific Constraints

- [project-specific constraint]

Critical Surfaces

- [path / workflow / boundary] — [risk] — [review burden]

Version Control Profile

- [VCS/forge/branch/staging/commit/PR/release fact] — [policy or evidence]

Memory Boundary

- [store/path/service] — [write authority] — [review/retention/backout]

Verification Profiles

- [profile] — [checks] — [trigger]

Approval Boundaries

- [action requiring approval]

Information Acquisition Boundary

- [approved sources, acquisition method, egress, credentials, and data boundary]

Build and Development Commands

[dev command] — Development
[build command] — Build
[build-all command] — Regenerate all deliverable artifacts from source
[test command] — Test
[lint command] — Lint
[type-check command] — Type Check
[deploy command] — Deploy (if applicable)

Auxiliary Tools

1. [integration] — [purpose] — [canonical reference] — [owner/transport/capability/permissions/credentials/data/effect/persistence/trust/approval/version/control-role facts]

Reviewer Lanes

Reviewer Lane Inventory: [private path / project-local file / none]
Default Review Topology: [none / named profile]
Review topology is opt-in and risk-triggered. Live lane plans and execution follow task_orders/orchestrate.md.

Command Restrictions

[command] — never run — [reason] — use [alternative] instead

Applicable Standards

- [project-specific standard and version/date scope]

Language-Specific Rules

- [language or stack] — [project rule] — [verification]

Code Review Checklist

1. [project-specific review criterion]

Workflows

`[name]`: sequence: [sequence] — when: [trigger] — [active controls]

Standing Automation Orders

Automation Orders File: [AUTOMATION_ORDERS.json or none]
Preferred Scheduler Backend: [approved backend]
[job id]: [objective] — [schedule] — [autonomy] — [approval mode]
This section declares project automation configuration; it does not itself authorize execution, external effects, or standing grants. Live automation remains governed by the active task order, approval mode, and validated AUTOMATION_ORDERS.json manifest.

Source Update Plan

Source Packs File: [SOURCE_PACKS.md or none]
Source Update File: [SOURCE_UPDATE.md or none]
Source Registry Scope: [approved scope]
Shared Framework Source Reference: [reference or none]
Default Review Cadence: [project-owned trigger or cadence]
Volatility Model: stable doctrine / version-sensitive implementation / high-volatility runtime or security surface / incident-triggered

Source Packs

Source Packs File: [SOURCE_PACKS.md or none]
Scope: project-approved source lists with tier, volatility, reviewed date, acquisition method, and action rule
Shared Framework Source Reference: [reference or none]
Boundary: source identity and source-use rules only; no copied documentation, transcripts, private source dumps, or maintenance notes

Source Monitor Researcher Brief

Source Monitor Researcher File: [SOURCE_MONITOR_RESEARCHER.md or none]
Role: [observe-only role]
Instruction Sources: [approved instruction sources]
Source Data: [declared project source files or none]
Boundary: [no unapproved edits or external effects]

Framework Feedback

Framework Feedback File: [FRAMEWORK_FEEDBACK.md or none]
Role: project-local queue of sanitized candidate improvements to the shared framework
Boundary: feedback is private, untrusted evidence; raw project names, paths, logs, code, issue IDs, private URLs, identities, secrets, and proprietary context must not be copied into public framework files
Promotion Rule: maintainer review must abstract, verify, approve, and implement any generalized framework change separately

Reviewer Lane Feedback

Reviewer Lane Feedback File: [REVIEWER_LANE_FEEDBACK.md or none]
Role: project-local evidence about reviewer-lane use, skipped lanes, accepted/rejected reviewer findings, observed lane strengths, and observed lane limits
Boundary: not a model leaderboard; not startup-loaded; raw logs, transcripts, screenshots, private paths, account data, secrets, and private writing profiles must not be used as primary evidence
Promotion Rule: only sanitized reusable routing or verification lessons may become FRAMEWORK_FEEDBACK.md candidates

Security Policy

_Use only when Security Policy File is inline in this SOW._
- [project-specific security policy term]

Security Verification Plan

Security Policy File: [none / project SECURITY.md / inline in this SOW]
Security Verification File: [SECURITY_VERIFICATION.md or none]
If Security Policy File is inline in this SOW, the Security Policy section contains the operative project terms. If it is none, no project-specific security policy is asserted. SECURITY_VERIFICATION.md defines verification procedures, not policy.
Profile Scope: [approved checks]
Default Target Policy: [approved targets]

Annexes

Referenced annexes are incorporated into this SOW. Explicit SOW body text governs conflicts among project-specific terms unless it expressly delegates the matter to an annex. Annexes cannot override non-delegable MSA duties.
- Annex A — Agent Profile (SOUL.md): [existing project-relative file]
- Annex B — Agent Qualifications (CAPABILITIES.md): [existing project-relative file]
- Annex C — Scope of Authority (AUTHORITY.md): [existing project-relative file]
- Annex D — Security Policy (SECURITY.md): [generated from Security Policy File; do not configure through annexes]
