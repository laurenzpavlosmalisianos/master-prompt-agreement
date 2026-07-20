# MSA Clause Classification

Date: 2026-07-18
MSA version: 1.0.18

This is the operative classification baseline for `master_service_agreement.md`. Its job is to decide what stays always-on, what loads on demand, what should be enforced by tooling, and what should remain canonical only.

The companion machine-readable form lives in `runtime/msa_clause_map.json`. Scripts should use that file. This document is the human-readable overview.

## Disposition Legend

- `projected`: represented in the compact runtime core or runtime project contract
- `task-scoped`: load only for matching workflows
- `path-scoped`: load only when relevant files or domains are in play
- `tool-enforced`: prefer runtime or tooling enforcement over prompt text
- `canonical-only`: keep in the MSA but do not load by default

## Clause Map

| Source | Disposition | Operative Home | Notes |
|---|---|---|---|
| Article 1 Definitions | canonical-only | `master_service_agreement.md` | Keep for canonical precision. Do not load at runtime by default. |
| 2.1 Think Before Coding | projected | `runtime/operative_charter.md` | Core truthfulness and non-omission behavior. |
| 2.2 Simplicity First | projected | `runtime/operative_charter.md` | Fundamental coding posture. |
| 2.3 Surgical Changes | projected | `runtime/operative_charter.md` | Core change-scope discipline. |
| 2.4 Goal-Driven Execution | projected + task-scoped | `runtime/operative_charter.md`, `practice_guides/task_contract.md` | Core verification rule plus task framing support. |
| 2.5 Epistemic Standards | projected + task-scoped | `runtime/operative_charter.md`, `practice_guides/source_grounded_research.md`, `practice_guides/security_audit.md` | Keep the short reasoning rules projected. Put heavier analysis method on demand. |
| 2.6 Decision Authority | projected + canonical-only | `runtime/operative_charter.md`, `runtime/project_template.md` | Keep the short default in core. Put project overrides in the project contract. Minor ambiguity should be resolved through approved project context or tools when safe. Creative or implementation grants do not imply architecture, stack, dependency, deployment, VCS, acquisition, memory, or policy authority. |
| Article 3 Dispute Resolution | task-scoped + canonical-only | `task_orders/independent_assessment.md`, `task_orders/arbitrate.md`, `runtime/task_modules/arbitrate.md` | Load for independent assessment or arbitration. Default quorum is a strict majority of configured seats returning valid, in-scope, verifier-accepted responses; the default recommendation threshold remains a strict majority of configured seats supporting the same option. Panel output is a recommendation unless ratified or expressly binding by SOW. |
| Article 4 Applicable Standards | projected + task-scoped | `runtime/operative_charter.md`, `practice_guides/source_grounded_research.md` | Keep short primary-source and version-check rules projected. |
| Article 5 Acceptance and Verification | projected + task-scoped | `runtime/operative_charter.md`, `runtime/project_template.md`, `practice_guides/task_contract.md` | Verification discipline is projected. Specific acceptance definitions are task and project scoped. |
| Article 6 Session Continuity | projected + task-scoped | `runtime/operative_charter.md`, `runtime/project_template.md`, `practice_guides/prompt_injection_review.md`, `TODO.md`, `DECISIONS.md`, `FINDINGS.md`, `REVIEWER_LANE_FEEDBACK.md`, `FRAMEWORK_FEEDBACK.md`, `PRECEDENTS.md` | Core state-management behavior plus scoped persistent-memory boundary review. |
| 7.1 Writing Style | projected | `runtime/operative_charter.md` | Agent communication style belongs in the core. |
| 7.2 Git Workflow | projected + task-scoped + tool-enforced | `runtime/operative_charter.md`, `task_orders/commit.md` | Core destructive-command bans, VCS freshness disclosure, and staging discipline are projected or tool-enforced; load the full commit workflow for commit work, including recent-history inspection. |
| 8.1 Universal Code Review Checklist | projected + task-scoped | `runtime/operative_charter.md`, `practice_guides/dependency_risk.md`, `practice_guides/backend_database_security.md`, `practice_guides/secure_development.md`, `practice_guides/security_audit.md` | Keep universal checks in core. Route specialized dependency, backend-database, secure-development, and security-audit checks to Practice Guides. |
| 8.2 Feedback Loop | task-scoped | `task_orders/insights.md`, `task_orders/framework_improvement.md`, `FINDINGS.md`, `FRAMEWORK_FEEDBACK.md`, `REVIEWER_LANE_FEEDBACK.md` | Decision-triggered only: User request, an explicit project retrospective checkpoint, or material recurring evidence requiring a concrete framework decision. Ordinary completion is not a trigger. |
| 8.3 Dependency Hygiene | task-scoped + path-scoped | `practice_guides/dependency_risk.md` | Load only when dependencies are touched. |
| Article 9 Intellectual Property and Licensing Compliance | projected + task-scoped + canonical-only | `runtime/operative_charter.md`, `runtime/project_template.md`, `practice_guides/source_originality_review.md`, `practice_guides/dependency_risk.md` | Keep a short no-copy rule projected. Load fuller clean-room, attribution, and dependency licensing logic only when external code or assets are in play. |
| Article 10 Continuous Improvement | task-scoped | `task_orders/insights.md`, `task_orders/framework_improvement.md`, `FINDINGS.md`, `FRAMEWORK_FEEDBACK.md`, `REVIEWER_LANE_FEEDBACK.md`, `PRECEDENTS.md` | Improvement should use proportionate objective, real-work, comparative, or causal evidence selected for a concrete decision, not automatic completion retrospectives or always-on prompt text. |
| 11.1 File System | projected + tool-enforced | `runtime/operative_charter.md` | Strong candidate for runtime enforcement. |
| 11.2 External Systems | projected + tool-enforced | `runtime/operative_charter.md` | Approval policy should be enforced by tooling where supported. |
| 11.3 Secrets and Credentials | projected | `runtime/operative_charter.md` | High-risk universal rule. |
| 11.4 Failure Handling | projected | `runtime/operative_charter.md` | Universal operational discipline. |
| 11.5 Untrusted Content | projected + task-scoped | `runtime/operative_charter.md`, `practice_guides/prompt_injection_review.md`, `practice_guides/source_grounded_research.md` | Keep the trust-boundary reminder projected. Load deeper analysis only when relevant. |
| 11.6 Irreversible Actions | projected + tool-enforced | `runtime/operative_charter.md` | High-risk rule. Runtime approvals should reinforce it. |
| 11.7 Trust Boundaries | projected + task-scoped | `runtime/operative_charter.md`, `practice_guides/prompt_injection_review.md`, `practice_guides/backend_database_security.md`, `practice_guides/secure_development.md`, `practice_guides/security_audit.md` | Core model plus deeper backend-database, secure-development, and audit workflows on demand. |
| Article 12 Default Values | canonical-only + task-scoped | `runtime/project_template.md` | Distill only the active defaults into the project contract. |

## Projection Boundary Summary

Keep these projected:

- truthfulness and omission rules
- scope control
- verification discipline
- state maintenance
- communication style
- trust-boundary reminders
- approval rules for destructive or external actions

Keep these outside the projected payload:

- definitions
- dispute mechanics
- decision-triggered retrospectives
- long licensing detail
- default-value catalog

## Optional Refinements

- split rows further when a specific project repeatedly needs finer-grained extraction
- use this map to cut a shorter canonical-to-operative extraction path when the runtime layer changes
- keep one active operative home per rule where practical
