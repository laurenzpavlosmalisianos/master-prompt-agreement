# Platform Architecture Review Practice Guide

Use this Practice Guide when designing, changing, or reviewing platform, cloud, DevOps, SRE, deployment, internal developer platform, service mesh, gateway, edge, or control-plane architecture.

Load this guide only when the task is about architecture quality, operational scalability, developer-platform abstractions, or production operations. For storage, queues, streams, replication, and data consistency, also use `data_systems_review.md`. For security-sensitive architecture, also use `security_audit.md` or `secure_development.md`. For release gates, also use `release_readiness.md`. For IaC source, generated output, plan, state, preview, change-set, drift, or apply/deploy review, use `infrastructure_as_code_review.md`. For CI/CD workflow configuration, runner trust, token permissions, caches, artifacts, provenance, or publish handoffs, use `build_pipeline_integrity.md`.

Before making source-sensitive recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check the smallest credible current primary source set for the active surface.

## Source Scope

- Treat external talks, videos, third-party incident writeups, vendor case studies, and AI summaries as comparative evidence, not authority.
- Use current official documentation before making technology-specific claims about cloud services, proxies, service meshes, orchestrators, IaC tools, CI/CD systems, or runtime behavior.
- For host, VM, or Linux-server hardening, use the target distribution, version, support channel, selected compliance baseline, and official hardening source before adopting checklist settings. Treat generic or third-party hardening guides as source-discovery input, not authority.
- For AI serving, local inference, or on-device inference, treat the model runtime as a platform surface. Verify model format including quantized variants, tokenizer or chat template, backend acceleration, batching, KV-cache memory limits at the target context length, multimodal preprocessing and resolution-token tradeoffs, retention, tenant/session isolation, local server exposure, artifact provenance, observability, and upgrade path against the selected runtime.
- Prefer project workload evidence, ownership facts, and existing constraints over fashionable platform patterns.

## Workflow

1. Define workload, users, and invariants.
- identify product teams, platform users, operators, service owners, and incident responders
- state request path, background work, control operations, deployment path, and recovery path
- capture latency, throughput, availability, recovery-point and recovery-time, compliance, cost, and support expectations
- name invariants that must survive deploys, partial failure, retries, and operator error
- map public, partner, internal, administrative, tenant, and private data/control surfaces, including secrets, sensitive data, logs, artifacts, and egress paths

2. Review the platform contract.
- describe what the platform abstracts, what it exposes, and what remains the application team's responsibility
- for cross-platform architecture, classify each claimed capability as portable core, platform-specific backend, user or harness adapter, bridge/export/cache/test convenience, or unsupported path; separate shared core invariants from platform-owned adapters or native integrations; avoid lowest-common-denominator abstractions unless workload evidence shows they reduce total complexity without degrading required behavior
- do not label a mounted path, copied binary, host helper, status export, cache, or agent workaround as native platform support; unsupported paths should fail closed with useful diagnostics
- for compiled, native, AI-serving, data-processing, or hardware-backed workloads, classify state boundaries before changing architecture: static description such as schema or metadata, durable data, transient runtime-allocated resources, build or executable artifacts, external side effects, and cleanup or release paths. Do not assume transient resources are safe merely because construction succeeds; define the owner and verifier for allocation, teardown, and reuse.
- check whether the interface is self-service, discoverable, versioned, observable, and supportable
- record ownership for provision, update, rotate, scale, deprecate, incident, and decommission
- provide an owned exception or contribution path for valid outlier use cases

3. Separate control-plane, data-plane, and background-work paths.
- keep user-facing request paths separate from provisioning, reconciliation, migration, and administrative work
- for asynchronous work, define delivery, ordering, duplication, cancellation, visibility, retry, recovery, and repair semantics; require only the mechanisms needed to satisfy those semantics
- for dynamic configuration or routing, define propagation delay, consistency expectations, safe defaults, validation, staged rollout, rollback, and control-plane-unavailable behavior
- choose static configuration, redeploys, or simple managed services when they meet the workload with less operational burden

4. Place cross-cutting concerns deliberately.
- centralize shared authentication, policy decisions, routing, rate limits, telemetry, and common hardening only when ownership and bypass control are clear
- enforce resource-specific authorization at the service or resource boundary
- choose edge, gateway, sidecar, library, or application placement based on failure isolation, latency, resource cost, upgrade cadence, debuggability, and override needs

5. Review infrastructure and delivery mechanics.
- prefer declarative, reviewed, reproducible infrastructure and deployment changes where the project supports them
- check delivery assumptions at the architecture level; use `build_pipeline_integrity.md` for workflow triggers, tokens, runner trust, caches, artifacts, provenance, attestations, signatures, SBOMs, and publish handoffs
- for host or VM hardening, record OS distribution and version, package/update channel, exposed services and ports, SSH or break-glass recovery path, firewall and remote-access boundary, mandatory-access-control status, audit/logging path, compliance profile or benchmark, and the verification command or scan that provides evidence the applied settings match the selected baseline and stated workload constraints; report runtime, recovery, and operational-fit gaps separately
- for agent execution platforms, review sandbox isolation, runtime trust boundary, workload identity, tool and connector permission scope, secret/session exposure, prompt-injection and source-trust boundaries, persistent state, snapshot and restore semantics, warm-pool capacity, network default-deny and egress rules, lifecycle routing, teardown, observability, support boundary, and control-plane scaling limits
- when an agent workload requires containment, verify that it cannot modify or impersonate its policy, approval, or credential authority. Confirm required controls before launch, preserve containment through control loss or revocation, and define bounded authenticated recovery that rechecks current identity and policy before resuming affected work
- for agent-facing development harnesses, prefer topology, resource dependencies, environment checks, and lifecycle controls that are typed, schema-validated, or compile/test checked; review isolated parallel runs, port and secret allocation, process ownership, resource-level restart, structured logs, traces, metrics, and browser or user-flow feedback hooks before relying on unattended agent iteration
- treat immutable images, IaC, golden paths, service catalogs, and platform templates as implementation options, not universal requirements
- for Kubernetes, AI serving, supply-chain-sensitive delivery, or self-managed clusters, verify target version and official docs before advising on product-specific details
- keep manual break-glass operations explicit, least-privileged, time-bounded, audited, expired where possible, and rehearsed

6. Verify operability.
- name health signals, diagnostic evidence, thresholds, owner, escalation path, and recovery path
- require logs, metrics, traces, dashboards, alerts, SLOs, or runbooks only when they are needed to diagnose claimed failure modes or operate the service
- for public developer tools, verify tested platform support, unsupported paths, setup prerequisites, verification commands, data-flow or architecture notes where material, license and security-reporting surfaces, and cleanup guidance before claiming publication readiness
- test failure modes the architecture claims to tolerate: dependency outage, queue delay, duplicate work, stale config, bad deploy, zone or region failure, capacity pressure, and operator mistake

7. Use maintenance signals as triage, not proof.
- repeated code churn, incident areas, brittle runbooks, and emergency patches are hotspot signals
- before refactoring, inspect coupling, ownership, test gaps, defect history, user impact, and planned change stream

## Output

Provide the smallest applicable subset:

1. workload, users, and critical invariants
2. platform contract, public/private data/control boundaries, and ownership boundaries
3. control-plane, data-plane, and background-work map
4. selected patterns and rejected alternatives
5. cross-cutting concern placement
6. delivery, artifact, rollout, and recovery assumptions
7. operability and failure-mode verification plan
8. maintenance hotspots and refactoring decision, when applicable

## Guardrails

- Do not prescribe microservices, service mesh, sidecars, queues, IaC, immutable images, or dynamic proxies without workload evidence.
- Do not treat one company's scale pattern as general doctrine.
- Do not let self-service abstractions remove clear ownership, support, or incident responsibility.
- Do not move complexity into a platform layer unless it reduces total cognitive load and operational risk for the organization.
- Do not claim reliability from redundancy diagrams without failure-mode tests and recovery evidence.
- Do not treat upstream model safety evaluations, serving filters, or benchmark results as complete downstream safety evidence; use system-level safeguards, input and output controls, sandboxing, and task-specific verification for the deployed use case.
- Do not choose or change architecture, stack, dependency, deployment, VCS, cloud account, secret store, or orchestration authority without explicit project grant or inspected project evidence.
