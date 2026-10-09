# Risk Routing Practice Guide

Use this Practice Guide before non-trivial work to choose the right Risk Level, work mode, authority class, Practice Guides, Evidence Scope, and verification burden. Route the task from observed risk, not from a fixed default.

## Rate These Axes

Use `low`, `medium`, or `high` for each axis:

1. consequence and blast radius
2. ambiguity and unknowns
3. irreversibility and recovery uncertainty (`low` means reversible with a verified recovery path; `high` means irreversible or recovery is unclear)
4. trust-boundary or security exposure
5. protected-data exposure
6. source or recency sensitivity
7. privileged or external effect

Then state the authority class separately: `read-only`, `workspace-write`, `external-write`, or `privileged`.

## Routing Rules

Treat ratings as risk contribution: `low < medium < high`. Apply the highest matching tier; a lower-tier rule never overrides an adversarial or forensic trigger.

- `fast`: all axes low, the task is small/local/reversible, local evidence is enough, and there is no privileged or external effect.
- `standard`: ordinary implementation or review work where all axes remain low, risk is understood, and verification is straightforward.
- `careful`: any axis at least medium, including high ambiguity, source sensitivity, public/user-facing impact, multiple affected surfaces, or recoverable but costly/rollback-sensitive work, unless an adversarial or forensic trigger matches. High consequence may remain careful only when boundaries are understood and recovery is verified and reversible. Generated code touching an unfamiliar module, runtime, API contract, or integration point is careful unless it crosses a trust/security, protected-data, privileged, external-effect, destructive, or abuse boundary.
- `adversarial`: trust-boundary or security exposure, protected data, deletion, overwrite, irreversible change, destructive action without a verified recovery path, privileged/external effect, suspected bypass or prompt-injection path, disputed safety claim, or high consequence with unclear recovery or material abuse potential.
- `forensic`: suspected compromise, secret exposure, destructive regression, corrupted state, data-loss path, or disputed facts requiring evidence preservation.

Work mode is separate from tier:

- `implementation`: make the scoped change and verify it.
- `review`: inspect and report without editing.
- `adversarial-review`: actively look for failure paths, bypasses, prompt injection, unsafe assumptions, or false positives.
- `incident-response`: preserve evidence first, minimize writes, and use incident authority.

Minimum burdens:

- `fast`: patch or touched-file evidence, smallest meaningful verification, no persistent artifact unless the task or verification requires it.
- `standard`: changed-behavior evidence, ordinary verification, and residual-risk reporting.
- `careful`: explicit acceptance checks, touched-file evidence plus affected-edge inspection, feature-slice evidence following the changed behavior across its relevant consumer or integration path only when the evidence path crosses consumers, modules, flows, or trust boundaries, rollback or containment story, and focused verification.
- `adversarial`: trust-boundary, abuse-case, or critical-surface evidence; independent refutation where feasible; explicit approval for privileged or external effects; and failure-path or bypass verification.
- `forensic`: preserve evidence first, record timeline and custody, require owner approval for state changes, and verify containment or recovery.

## Practice Guide Routing

- ambiguity or unclear scope: `task_contract`
- logic-heavy rules, policies, state machines, or generated specs: `logical_spec_review`
- multi-step execution sequencing after the approach is chosen: `implementation_planning`
- recurring autonomous work or scheduler-backed agent jobs: `scheduled_automation`
- configuring or operating time-bounded delegated communication coverage that inspects inbound messages and may create drafts, protected escalations, notices, or replies: `delegated_communication_coverage` plus `prompt_injection_review` and `privacy_data_handling`; do not infer this route from a generic external effect alone
- maintained validators, source registries, prompt linters, policy scanners, or reusable verification scripts: load the guide for the artifact under review; add `logical_spec_review` only when policy semantics are encoded; add `change_impact_review` only for release gates or high-blast-radius changes; add `secure_development` only for security-relevant gates; add `prompt_agent_quality` only for prompt, agent, rubric, or workflow artifacts
- debugging or unproven failure cause: `root_cause_investigation`
- review, audit, or low-diff high-blast-radius changes: `change_impact_review`
- current external docs, changing facts, or source-sensitive recommendations that depend on living primary sources: `source_grounded_research`
- current-source changes that should become review, audit, or planning checks: `source_freshness_review`
- test strategy, generated tests, test-suite adequacy, flaky tests, oracle quality, or acceptance evidence based on tests: `testing_strategy_quality`
- data-intensive architecture, storage, replication, consistency, streams, analytics, search, vector indexes, managed data services, or local-first sync: `data_systems_review`
- API contracts, endpoint schemas, operation authorization, generated API artifacts, webhooks, GraphQL, gRPC, or REST trust boundaries: `api_contract_security`
- personal, customer, private, production-derived, sensitive, regulated, or protected data; logs, traces, screenshots, prompts, model outputs, egress, retention, deletion, redaction, test data, or data minimization: `privacy_data_handling`
- SQL/database-backed backend exposure, credentials, grants, migrations, backups, restores, tenant isolation, model-generated SQL, or natural-language-to-query execution: `backend_database_security`
- embedded SQL engines or file-backed local stores, including database files, lock files, journal or WAL side files, snapshots, exports, and helper-agent access to local state: `sql_query_quality` plus `secure_development`
- platform, cloud, DevOps, SRE, gateway, service mesh, edge, control-plane, deployment, internal developer platform architecture, cross-platform support claims, host/container/VM runtime boundaries, hardware-backed capability claims, or native-platform support claims: `platform_architecture_review`; add `testing_strategy_quality` for support matrices, and add `secure_development` when data, process, filesystem, IPC, or credential boundaries are crossed
- Kubernetes manifests, rendered Helm/Kustomize/GitOps output, workloads, RBAC, NetworkPolicies, storage, CRDs, admission, or rollout behavior: `kubernetes_workload_review`
- infrastructure-as-code source, generated or transformed output, providers, modules, state, plans, previews, diff artifacts, drift, policy-as-code, import/move operations, or apply/deploy gates: `infrastructure_as_code_review`
- Containerfiles, OCI images, base images, build contexts, image layers, build secrets, SBOMs, provenance attestations, signatures, registries, or container image scanning: `container_image_security`
- CI/CD workflow files, build jobs, release jobs, runner trust, workflow permissions, OIDC, secrets, caches, artifacts, provenance, SBOMs, attestations, signatures, or publish handoffs: `build_pipeline_integrity`
- Apple `container` CLI workflows, local Linux containers on macOS, machines, images, registries, mounts, volumes, networks, ports, or host/container command boundaries: `apple_container_workflow`
- prompts, agent entrypoints, coding-agent instructions, tool-use contracts, model-output quality, evals, or reusable agent workflow tuning: `prompt_agent_quality`
- external code, assets, demos, product references, generated prototypes, third-party patches, source-originality claims, or clean-room implementation risk: `source_originality_review`
- secure code generation, application or binary hardening, loader trust, software-update integrity, static analysis, authorized dynamic checks, fuzzing, secret scanning, or recurring security verification profiles while building or modifying code: `secure_development`
- dependency additions or upgrades: `dependency_risk`
- schema, storage, or compatibility changes: `migration_safety`
- release, deploy, or merge-readiness work: `release_readiness`
- website frontend quality, CSS architecture, generated output, assets, metadata, privacy/legal, or release-quality review: `website_frontend_quality`
- authored or generated HTML semantics, forms, links, tables, media, embeds, metadata, ARIA, or validator output: `html_quality`
- CSS architecture, selectors, cascade, layout, animation, support, or modern CSS features: `css_quality`
- plain JavaScript source, module semantics, runtime APIs, package entry points, generated JavaScript, or JavaScript async/resource behavior: `javascript_coding_quality`
- Swift, SwiftUI, Apple-platform app, resources, concurrency, or package work: `swift_coding_quality`
- Rust, Cargo, crate APIs, unsafe code, target, or release-sensitive work: `rust_coding_quality`
- TypeScript, tsconfig, module resolution, declaration emit, package types, or type-boundary work: `typescript_coding_quality`
- Python, `pyproject.toml`, uv workflow, type checking, packaging, tests, or runtime behavior: `python_coding_quality`
- Go, `go.mod`, `go.sum`, `go.work`, package APIs, command packages, concurrency, cgo, tests, or Go release behavior: `go_coding_quality`
- shell scripts, CLI wrappers, install/bootstrap scripts, automation command strings, or reusable shell-driven workflows: `shell_cli_coding_quality`
- handwritten SQL, schema DDL, query shape, migrations' SQL text, transactions, result shape, or query performance: `sql_query_quality`
- rendered UI, screenshots, layout, images, canvas, or browser-visible output: `visual_verification`
- producing or revising a temporal audiovisual deliverable, including its brief, script, storyboard, edit, audio, captions, encoding, playback, or delivery package: `video_creation_quality`; do not route video used only as research input, a still-image task, or HTML media embedding alone
- untrusted external content, agentic retrieval, tool/MCP/connector flows, or persistent memory/state writes: `prompt_injection_review`
- incidents, suspected compromise, or secret exposure: `incident_response`
- SEO work: `seo`
- adversarial security review, vulnerability triage, threat-path analysis, or a security-sensitive change that needs independent attack-minded findings: `security_audit`
- briefing or recommendation memo: `decision_brief`
- teaching, onboarding, session/change explanation, or comprehension check: `knowledge_transfer`
- writing or style-profile work: load `scholarly_writing` only for academic, citation, or source-heavy writing; otherwise ask for the desired style source during setup or task intake when none is supplied
- academic writing, citation, or source-heavy scholarly revision: `scholarly_writing`

## Evidence Scope

Start with the smallest scope that can justify the task: `patch`, `touched-files`, `commit-series`, `feature-slice`, `trust-boundary`, or `repo-slice`. Widen only when the evidence path crosses files, layers, consumers, runtimes, or trust boundaries.

## Output Shape

Produce: Risk Level, Work Mode, Authority Class, Reason, Practice Guides to Load, Evidence Scope, Required Checks, and Second-Review Recommendation.

## Guardrails

- Do not pick `fast` when protected data, security-sensitive code, external side effects, irreversible operations, or disputed facts are involved.
- Do not load every Practice Guide. Load only the ones the route justifies.
- Do not review the full repository when a patch or feature slice is enough.
- Do not confuse a tiny diff with a tiny blast radius.
- Raise the tier when new evidence expands the blast radius or authority class.
