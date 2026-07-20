<!-- mpa-generated-state-origin: master-prompt-agreement/project-state/v1 -->

# Security Verification

Use this file when a project needs recurring secure-code or application-security checks beyond normal tests. Keep entries project-specific, runnable, owned, and justified by the project's real threat surface.

## Scope

- Protected assets: [accounts / payments / secrets / files / admin actions / personal data / other]
- Trust boundaries: [browser / API / CLI / filesystem / database / third-party service / agent tool / CI release pipeline / package registry / privileged runtime / firmware or device interface / other]
- Agentic boundaries: [agent identity / runtime-native skills, hooks, permissions, or extensions / direct APIs or CLIs / connectors / protocol servers such as MCP when adopted / persistent memory / generated-code execution / automations / none]
- Security standard: [ASVS version / WSTG version / CWE class / compliance rule / project rule]
- Out of scope: [surfaces not covered by this profile]

## Threat Model Triggers

- Update threat model when: [new endpoint / role / parser / permission / external integration / data store / secret path / agent tool / deployment boundary / other]
- Minimum threat-model record: [actor / entry point / data flow / trust boundary / material threat / response / verification evidence]
- Threat lens: [STRIDE / ASVS / WSTG / CWE / attack tree / abuse case / project-specific]

## Profiles

- secure-code — [format/type/lint/test/custom rules/approved static analysis where justified] — [when code changes touch trust boundaries]
- dependency-and-secrets — [SCA/dependency audit/secret scan/license check] — [when dependencies, configs, CI, or deploy files change]
- supply-chain — [lockfile-only install / release-age or age-gate policy / lifecycle-script policy / provenance or trust-policy check / registry-source restriction / SBOM, AI SBOM, or artifact inventory review / CI credential exposure check] — [when package, lockfile, release, CI, publishing, AI-system inventory, or dependency-source behavior changes]
- agentic-runtime — [agent identity / credential boundary / runner lifecycle / least-agency permission review / sandbox, mount, network, secret, cache, and teardown checks] — [when agent runtimes, generated-code execution, or AI-assisted security tooling changes]
- agentic-tools — [prompt-injection review / tool allowlist / parameter validation / native skill, hook, permission, extension, API, CLI, connector, protocol-server, local-daemon, GUI, or browser-automation provenance and boundary review / demonstrated lifecycle coverage and enforcement strength for claimed controls / protocol health or status check / record-replay fixture review where available] — [when agent tools, runtime-native surfaces, APIs or CLIs, connectors, protocol servers such as MCP, automations, local control planes, or desktop/browser automation change]
- agentic-egress-memory — [model-router or provider list / multi-provider egress / inner tool and domain controls / output format validation / protected-data boundary / memory provenance, integrity, retention, and rollback review] — [when external model routing, persistent memory, retrieved context, or protected-data flows change]
- agentic-operations — [failure, degradation, recursion, cost, latency, provenance, trace-redaction, dwell-time, alert-coverage, and approval-boundary checks] — [when long-running, recursive, scheduled, or multi-agent workflows change]
- database-query-generation — [read-only role / schema, tenant, and business-rule grounding / parameterized execution path / allowlisted identifiers / destructive-query approval / query and result audit / authorization and tenant-negative tests / execution-based correctness tests] — [when natural-language or model-generated database queries can run]
- application-dynamic — [local or approved staging dynamic security checks/API/browser/header checks, if authorized] — [when a runnable web/API app changes]
- high-risk-input — [fuzz/property/sanitizer/parser corpus/rendered-versus-extracted text/replay checks] — [when parsers, file formats, protocols, uploads, web/document ingestion, or shell/filesystem inputs change]
- privileged-interface — [message-format negative tests / shared-memory and callback review / permission or entitlement checks / variant-handler coverage / parser corpus, fuzz, emulator, or sanitizer checks where available / patch-diff regression] — [when kernel, driver, firmware, co-processor, hardware-adjacent, RPC, mailbox, or shared-memory interfaces change]
- release-hardening — [production config/header/cookie/CORS/CSRF/auth/logging/permission checks] — [before release or deployment]

## Tool Output Triage

For each material scanner or test finding, record:

- status: [confirmed defect / accepted exception / false positive / stale rule / tool limitation / unresolved question]
- coverage: [instructions / manifests / bundled files / executable scripts / dependencies / malware signatures or reputation / permission declarations / tool metadata / semantic mismatch / runtime traces / vulnerability lookups / other]
- evidence: [file, route, package version, config, exploit preconditions, or reproduction]
- action: [fixed / added to TODO.md / recorded as an accepted exception or precedent / recorded in FINDINGS.md only when it is a framework/process observation / no action with rationale]

## Authorization Boundaries

- Dynamic-test target allowlist: [local URLs / staging URLs / none]
- Prohibited targets: [production / third-party systems / customer data / shared infrastructure]
- Data limits: [synthetic data only / anonymized fixtures / approved test accounts]
- Approval required before: [scan type / payload class / external service / credentialed scan]
- Approval required before agentic changes: [installing or enabling skills/plugins / broadening MCP scopes / enabling external multi-model analysis or inner web tools / sending protected data through model routers / disabling approval or sandboxing / persistent memory writes from untrusted content / external data egress / other]
- Redaction boundary: [tool-enforced / proxy-enforced / manual review with residual risk / not applicable] — [owner, location, and protected-data rule]

## Rules

- Do not add scanner categories because they are fashionable or mentioned generically.
- Do not treat a clean scanner run as proof of safety.
- Keep only checks with a clear owner, authorization boundary, expected signal, and triage path.
