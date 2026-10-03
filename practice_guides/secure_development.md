# Secure Development Practice Guide

Use this Practice Guide when generating or modifying code where security quality is an explicit goal, when the task mentions secure code, secure applications, hardening, SAST, DAST, fuzzing, secret scanning, or when a project security verification profile applies. Use `security_audit` for adversarial review findings; use this guide while building and verifying.

Before selecting checks, read the project contract, Annex D if present, any project `SECURITY_VERIFICATION.md`, and project `SOURCE_PACKS.md` or `SOURCE_UPDATE.md` when present. For SQL-backed backend setup, credential flow, migrations, grants, backups, tenant isolation, model-generated SQL, or natural-language-to-query systems, also use `backend_database_security.md` and current official database/security sources.

When untrusted content can affect model behavior, tools, memory, MCP, skills, plugins, rendered artifacts, data disclosure, or side effects, also use `prompt_injection_review.md`.

## Workflow

1. Define the security contract before editing.

- identify protected assets, actors, trust boundaries, attacker-controlled inputs, privilege boundaries, secrets, and externally visible endpoints
- select and version the applicable security requirement baseline before tailoring it; record release/publication status, treat missing or unknown status as draft or preview until verified, and prefer adopted final baselines only when the SOW does not explicitly scope a draft or preview; use ASVS requirement IDs with release and level, WSTG scenarios as test procedures, CWE as weakness taxonomy, SSDF as lifecycle practices, and project rules as local requirements. For durable WSTG evidence, use versioned scenario IDs and versioned links; treat `latest`, stable, draft, or preview references as exploratory unless the SOW explicitly adopts them
- decide which project verification profile applies: secure-code, dependency-and-secrets, application-dynamic, high-risk input, release hardening, agentic, supply-chain, or database-query-generation
- state which checks are unavailable, unauthorized, too expensive, or outside scope before relying on a partial result
- when AI agents generate, review, or execute code, define their authority, sandbox/isolation boundary, credential access, network access, write scope, approval gates, and logging before running them on untrusted material
- treat AI-generated code, AI-written tests, and AI-assisted review output as evidence needing review, not proof of safety; apply the same security contract and verification profile as for human-authored code
- treat prompts, retrieved content, tool or connector results, and model output as untrusted data; validate model output against narrow schemas and business rules before it reaches interpreters, tools, or side-effecting APIs
- never place secrets or authorization decisions solely in prompts; independently authorize each tool, resource, data disclosure, and side effect outside the model
- when security instructions or examples are needed for an assistant, keep them concise, stack-specific, and derived from the approved SOW or local secure patterns; do not use generic "best practices" wording as the only security requirement
- for autonomous or recurring agents, define unique agent identity, per-agent credential boundary, least-privilege task-scoped permissions, deterministic human-review triggers, trace/replay retention, and rollback before allowing side effects
- for personal or single-tenant agent runtimes, state whether callers, sessions, plugins, skills, and gateway users share one trust envelope; do not treat routing handles, memory scope, or approval heuristics as multi-tenant authorization boundaries

2. Run a lightweight threat-model pass when the change touches design, trust boundaries, or high-risk behavior.

- describe the changed flow in the smallest useful form: actor, entry point, process, data store, external dependency, network or DNS egress path, data flow, and trust boundary
- identify what can go wrong with a project-approved lens such as STRIDE, ASVS, WSTG, CWE, attack trees, abuse cases, or a domain-specific threat library
- map each material threat to a response: mitigate, eliminate, transfer, accept with rationale, or defer with owner and evidence needed
- translate mitigations into implementation requirements and verification checks before editing; do not rely on a scanner to discover missing design controls
- update the threat model when a new endpoint, role, parser, renderer, text-extraction path, permission, external integration, data store, secret path, or agent/tool capability changes the attack surface
- for kernel, driver, firmware, co-processor, hardware-adjacent, or privileged runtime interfaces, include endpoints, message tags, shared memory, MMIO or DMA-like paths, host callbacks, permission or entitlement gates, and parser dispatch tables in the attack-surface map
- for agentic systems, include privilege creep, credential reuse, behavioral drift, tool misuse, tool-parameter abuse, memory/context poisoning, hidden data egress, opaque audit trails, and cascade failure as first-pass threat prompts
- for skill, plugin, MCP, connector, or agent-package changes, include supply-chain compromise, unsafe manifests, overbroad permissions, update drift, weak isolation, and audit-log gaps as first-pass threat prompts
- for tool, skill, plugin, MCP, connector, or agent-package changes, threat-model model-visible metadata and control-plane changes: tool names, descriptions, annotations, prompt templates, resource descriptions, tool-list-change notifications, registry or package metadata, and approval UI/model-visible mismatches are untrusted unless source, version, and owner are trusted and pinned

3. Build with secure defaults.

- prefer framework security primitives for authentication, authorization, sessions, CSRF, CORS, cookies, headers, escaping, validation, and secret handling
- validate at trust boundaries; encode at output boundaries; keep authorization server-side and close to the protected operation
- where requests cross routing, proxy, or cache layers, verify that security decisions apply to the resource and operation ultimately reached and that reused responses remain within their authorized audience; exercise relevant alternate request forms and cache hits while preserving intentional route distinctions
- use typed or structured APIs for queries, shell/process execution, serialization, parsing, filesystem paths, and URLs
- typed URL construction is not an SSRF control; when untrusted data influences a server-side request, allowlist protocols, destinations, ports, and paths, restrict redirects and egress, and isolate the fetcher where risk requires it
- for database-backed services, verify network exposure, TLS, credential delivery, role separation, least-privilege grants, migration authority, backup/restore, and log/error redaction before treating query parameterization as sufficient
- for local embedded databases, lock files, cache files, status snapshots, or export files, treat the filesystem path as a trust boundary: reject symlinked state directories, database files, lock files, and export targets before opening or replacing them; prefer owner-only directories and files; verify permissions after create, chmod, replace, or migration steps; make lock and journal or sidecar files part of the protected storage contract; use atomic write or replace patterns for snapshots; fail closed when state paths are unsafe or unverifiable; and add negative tests for symlink directories, symlink data files, symlink locks, symlink exports, broad permissions, partial writes, and stale snapshot revalidation
- do not pass untrusted free-form JSON, query filters, or user-controlled DSL fragments into libraries that can compile, interpret, or evaluate code; disable dynamic-eval modes and avoid reflecting detailed evaluator errors to untrusted callers
- prefer structured parsers or linear-time parsing for untrusted or model-generated text; bound input size and test pathological cases before relying on regex-heavy extraction
- when requests, jobs, queries, files, or model calls can consume material resources or paid services, enforce server-side per-principal and global limits for input, output, decompressed size, batch, query cost, execution time, concurrency, memory, storage, queued actions, and downstream spend
- for new memory-safety-relevant code, prefer memory-safe languages, maintained safe libraries, or isolated wrappers when compatible with the project contract; when memory-unsafe code remains necessary, minimize the unsafe surface and verify compiler hardening, sanitizer, fuzz, and boundary tests where risk and tooling justify them
- for native parsers, protocol handlers, codecs, deserializers, or pointer/offset-heavy code, verify cursor advancement, buffer growth, bounds checks, allocator ownership, and skip/error paths together; add sanitizer or fuzz harnesses when tooling and risk justify them
- for shared-memory, mailbox, RPC, or firmware-facing interfaces, validate message length, offset, tag, context, subtype, allocation size, ownership, lifetime, and callback direction at both sides of the boundary; treat host-to-device and device-to-host paths as separate trust crossings
- for MCP servers, connectors, local agent tools, or tool-server implementations, classify each tool as read-only, side-effecting, disclosure-sensitive, or operator-diagnostic before implementation; keep tool schemas and handlers equivalent; reject malformed `params` or `arguments` instead of treating them as empty defaults; use strict boundary parsing for numbers, booleans, enums, paths, URLs, and object fields unless coercion is explicitly supported; do not use tool descriptions or annotations as authorization, safety, or approval contracts unless an independent policy or runtime enforces them; default missing or untrusted annotations to higher risk; minimize default outputs; and add negative tests for schema/handler mismatch, non-object arguments, unknown arguments, type coercion, raw-output leakage, side-effect defaulting, and disabled-policy bypass
- for timing-sensitive, hardware-adjacent, race-dependent, or compiler-layout-sensitive code, record exact hardware, firmware, toolchain, clock, optimization, and runtime configuration, then verify representative reliability after code layout, dependency, or build-flag changes
- when patching allowlists, scopes, roles, or other boundary arrays, prefer explicit replacement semantics and verify removed entries no longer retain access through stale merges
- when configuration changes security enforcement, define the validity of dependent sessions, credentials, cached decisions, and prior check results through supported transitions, mixed deployments, recovery, and configuration failure; verify downstream consumers reject evidence whose required policy no longer holds while retaining evidence still valid under that policy
- make insecure modes, debug paths, broad permissions, disabled verification, and test bypasses unavailable in production by default; any necessary exception must require explicit privileged opt-in, be narrowly scoped, auditable, and fail closed when configuration is absent or invalid
- when cryptography is in scope, use maintained, well-reviewed, project-approved implementations and algorithms; require formally validated modules only when a contract, assurance target, or regulation names that requirement. Define key and certificate lifecycle, use CSPRNGs for non-guessable values, password-specific KDFs for password storage, authenticated encryption when confidentiality and integrity are required, and design for replacement
- define fail-closed exceptional-condition behavior for authorization, validation, integrity, and state-changing work; roll back multi-step transactions where possible, return generic external errors, retain diagnostics in protected logs, and test dependency failure, timeout, cancellation, and partial-write paths
- keep deferred timeout, cancellation, and cleanup actions bound to the original operation or resource instance through the effect; revalidate ownership across asynchronous waits and replacement. A reused session, job, or plugin identifier must not authorize stale work to affect a successor instance or read its credentials
- add negative tests for authz failure, malformed input, path traversal, injection payloads, replay, missing secrets, and unsafe configuration when the surface exists
- prefer isolated, disposable, least-privilege execution for untrusted generated code, dependency installation, exploit reproduction, and agent-authored scripts; treat containers and sandboxes as containment layers that still need explicit mounts, secrets, network, and persistence review

4. Run layered verification, not one magic scanner.

- select scanner categories from the actual threat surface and project evidence, not from acronym coverage
- static checks: language lint/type/test, project custom lints, optional SAST, IaC scan, secret scan, dependency/SCA audit, license/provenance checks
- language-server or editor diagnostics: useful for type, symbol, import, and configuration defects when a CLI-equivalent command or approved local tool exists; record the exact command, configuration file, selected toolchain, and limitations
- dynamic checks: local or approved staging DAST where authorized, API/security regression tests, browser/security-header checks, auth/session checks, and representative attack-path probes
- for compliance, review, or user-flow obligations, distinguish static evidence that a capability exists from runtime evidence that the claimed flow works; add an approved runtime, UI, API, or manual check when a dead control, no-op path, missing entitlement, or incomplete backend action would still pass source inspection
- high-risk input checks: fuzzing, property-based tests, parser corpus tests, authorized hostile document corpora, rendered-versus-extracted text checks for document/web ingestion, sanitizer builds, race/concurrency tests, or replay tests when tooling and risk justify them
- privileged-interface checks: negative tests, parser corpus or fuzz inputs, sanitizer or emulator-backed runs where available, patch-diff regression tests, and explicit confirmation that deleted or restricted subcommands, message types, entitlements, or callbacks are no longer reachable
- generated output checks: inspect built artifacts, bundled code, source maps, routes, headers, permissions, and environment defaults, not just source files
- custom gate checks: for repository validators, release checks, source registries, prompt linters, or policy scanners, verify the declared product surface, excluded workspace roots, one declared owner for each shared policy family, negative fixtures, and failure messages before treating the gate as security or quality evidence
- supply-chain checks: verify lockfile-respecting installs, release-age, lifecycle-script, registry-source, and CI-credential policies where supported; scan the resolved dependency graph and built artifact or container when release risk is in scope
- provenance checks: when required, verify signature or envelope, subject digest, predicate type, trusted builder or source-control identity, canonical source and revision, build type, and external parameters against pinned expectations; record SLSA Build and Source tracks separately
- release-hardening checks: bind SBOM, provenance, integrity data, and verification results to the exact release artifact; archive release evidence under defined retention and access controls
- vulnerability-remediation checks: check current vendor advisories and the CISA KEV catalog, then rank urgency by confirmed exploitation, public exposure, exploit automation, technical impact, reachability, asset criticality, and available remediation; for exposed or high-impact systems, verify an emergency patch, workaround, isolation, rollback, or disconnect path; apply CISA directive timelines only when in scope or contractually adopted
- untrusted setup checks: before running unfamiliar repository setup, dependency installation, package init, doctor, or agent error-recovery commands, inspect the execution chain for lifecycle hooks, package entrypoints, shell scripts, subprocess calls, dynamic configuration, remote fetches, DNS lookups, shell interpretation, filesystem writes, and secret-bearing environment access. Use disposable no-secret execution with bounded network when execution is approved
- agent-harness checks: inspect traces, operation IDs, or replayable runs for unauthorized resource access, direct-IP or DNS egress, user-visible versus model-visible content mismatch, unsafe tool chaining, missing tool allowlists or parameter validation, inter-agent data leakage, failed deterministic gates, and verifier blind spots when the runtime exposes that evidence
- log and transcript checks: verify coverage and alerting for authentication operations, failed authorization, security-control bypass attempts, and unexpected control failures; include actor, action, resource, outcome, time, and correlation metadata; encode untrusted fields, protect logs from unauthorized access or modification, route them to the approved sink, and retain, expose, or redact hidden model traces and internal prompts according to the project's data-classification and retention policy. Redact secrets, raw screenshots, data URLs, and large base64 media payloads

5. Triage tool output before acting.

- classify each material SAST, DAST, dependency, secret, scanner, or fuzz finding as confirmed defect, not affected with evidence, accepted risk, false positive, stale advisory or rule, tool limitation, or unresolved question
- for not-affected, suppression, or accepted-risk decisions, record exact scope, owner, rationale, compensating controls, review or expiry date, and revalidation trigger
- verify scanner claims against the actual code path, package version, configuration, runtime route, and exploit preconditions
- fix confirmed blockers and defects directly only when remediation is explicitly in scope or approved and the fix is unambiguous; otherwise report the finding, minimal correction, verification, and any decision need without editing
- for confirmed vulnerabilities, perform proportionate root-cause and variant analysis, search adjacent code or supported releases for the same weakness, add regression detection, and update the applicable requirement, pattern, tool, or development process
- preserve useful recurring scanner rules in project verification profiles only after they have a good signal-to-noise ratio

For security fixes, restate the issue as source, control, sink, reachable path, trust boundary, and expected invariant before editing. When feasible, encode the original vulnerable behavior as a focused regression test, PoC, or static validation artifact first. After the fix, prove the original path no longer succeeds, legitimate behavior still works, and nearby bypasses or equivalent call paths do not evade the new control.

## Output

Provide:

1. assets, trust boundaries, and security requirements in scope
2. threat-model delta, material threats considered, and mitigations or accepted risks
3. secure defaults and negative tests added or checked
4. applicable static, dynamic, dependency, secret, fuzz, sanitizer, or manual security checks run
5. scanner-output triage and confirmed findings fixed or recorded
6. residual risk, unauthenticated or untested surfaces, and follow-up verification profile changes
7. evidence identifiers: baseline versions, tool versions and configs, target artifact digest or commit, timestamp, and material exclusions or disabled checks

## Guardrails

- Do not run DAST, fuzzing, load-like probes, exploit scripts, or scanners against third-party, production, or shared systems without explicit authorization.
- Do not treat SAST, DAST, SCA, fuzzing, or AI review as proof of safety.
- Do not treat STRIDE, a diagram, or a scanner dashboard as a complete threat model. The model must name the changed system, trust boundaries, threats, responses, and verification evidence.
- Do not add a security tool as a permanent gate until false positives, runtime assumptions, and ownership are understood.
- Do not treat a custom validator as meaningful because it counts files, words, links, or rows. A gate must enforce a named invariant on the declared surface and have negative examples that would have caught the failure class.
- Do not assume AI-assisted review, exploit generation, or vulnerability discovery reduces the need for human triage, patch ownership, regression tests, and rollback planning.
- Do not expose secrets, tokens, customer data, production identifiers, non-public source, configuration, logs, traces, vulnerability details, reproducers, or internal architecture to scanners, hosted LLMs, or hosted analysis tools unless the SOW or accountable owner explicitly permits it. Minimize and redact the submitted material.
- Do not treat removal alone as remediation when a secret appears in code, history, logs, artifacts, prompts, screenshots, or generated output; identify the owner or provider, revoke or rotate the credential, update affected services, check for unauthorized use where feasible, and record residual exposure.
- Do not spread generic security boilerplate across language guides when a project verification profile or this guide can carry the reusable rule.
