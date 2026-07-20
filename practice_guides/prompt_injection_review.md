# Prompt Injection Review Practice Guide

<!-- mpa-clause-projections: msa-11-5 msa-11-7 -->
Use this Practice Guide for agentic systems, retrieval systems, web-ingesting agents, tool-using assistants, or any workflow where untrusted content can affect model behavior. It provides a scoped review of cross-trust instruction, tool, memory, and state boundaries.

When current behavior or a security claim depends on the active surface, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check current official security, model-runtime, MCP, browser, retrieval, and tool documentation.

Scope this review by tracing untrusted content to a model decision, tool call, durable state write, data disclosure, or side effect. Route SSRF, XSS, malicious-package, iframe, callback, or dependency findings to the security, dependency, or frontend guide unless prompt influence changes exploitability.

## Workflow

1. Identify the untrusted inputs.
- web content
- user uploads
- issue text
- pull requests
- retrieved documents
- embedded or remote fonts, stylesheets, layout metadata, and document resources that affect rendered or extracted text
- API responses
- tool output
- review comments, CI diagnostics, lint/test failure messages, and generated remediation text
- images, screenshots, PDFs, office documents, audio transcripts, and OCR output
- MCP server tool definitions, tool results, elicitation prompts, and sampled content
- third-party tool descriptions, tool schemas, connector metadata, and capability-discovery responses
- agent-rendered UI schemas, component catalogs, generated HTML, iframe app resources, and UI-to-agent event payloads
- subagent outputs, delegated task packets, agent-to-agent messages, planner/executor handoffs, and lower-privilege agent requests consumed by higher-privilege agents
- skills, plugins, agent packages, repository-controlled runtime configuration, and installer or marketplace metadata

2. Map the control surfaces.
- system or developer instructions
- project docs
- runtime tool schemas, tool descriptions, capability discovery, and tool-routing behavior
- browser, PDF, office-document, OCR, and text-extraction pipelines
- memory writes
- persistent memory, profile memory, vector memory, and generated long-term context
- agent-facing prompts embedded in tests, linters, reviewer agents, CI, or SDK-based checks
- tool calls
- inter-agent routing, privilege transfer, task delegation, tool-result forwarding, and agent-to-agent memory or context propagation
- MCP server configuration, allowed tools, scopes, and approval mode
- agent UI renderer, schema/catalog validator, iframe sandbox, CSP, `postMessage` or event bridge, and user-action-to-tool routing
- skill, plugin, or agent package manifests, declared permissions, bundled scripts, dependencies, update path, and provenance
- secret-store, vault, keychain, CI secret, or environment-delivery paths exposed to agent tools
- approval flows
- outbound channels and localhost, loopback, WebSocket, HTTP, RPC, browser, code-executor, or MCP control planes reachable by the agent runtime

3. Look for boundary failures.
- untrusted content treated as instruction
- model-written memory without review
- memory entries created from untrusted content without user request, provenance, or verification
- untrusted review comments, diagnostics, or generated remediation text treated as trusted project guidance
- tool descriptions, schemas, or capability-discovery text treated as higher authority than the SOW
- skill or plugin instructions treated as trusted because they are packaged, popular, or installed locally
- repository-controlled config or skill metadata executed before explicit trust or provenance review
- tool calls, setup/init/doctor commands, or error-recovery commands derived directly from retrieved text, untrusted repository docs, package diagnostics, issue text, comments, or generated remediation text before the full execution chain is inspected
- MCP server output causing a second tool call, broader query, credential use, config write, external-review packet, or outbound disclosure
- secret exposure through prompt or tool output
- secret-store lookups triggered by untrusted content
- protected, derived, or inferred data encoded in an attacker-observable outbound choice, including the destination; URL path, query, or fragment; header or body; acting account or credential; selected link, action, or redirect; or cumulative request ordering, even when each operation is nominally read-only or uses an allowlisted domain
- outbound fetches, DNS queries, direct-IP calls, document callbacks, privileged localhost services, runtime-fetched configuration, remote scripts, package metadata, or other dynamic content reaching shell interpretation, subprocess execution, lifecycle hooks, or agent-approved tools
- summaries that preserve or introduce instructions later consumed as control text
- hidden or low-contrast text, invisible Unicode, malicious font/glyph mapping, metadata, or puzzle framing that steers reasoning or tool use
- encoded, translated, homoglyph, or otherwise normalized text that reveals tool-affecting instructions after decoding or rendering
- nested virtual machines, terminals, personas, sandboxes, or "developer mode" frames that claim the SOW does not apply inside the frame
- forced assistant prefixes, role labels, or continuation text that pressure the model to begin with unauthorized compliance
- multi-turn topic drift that gradually moves tool, memory, or approval behavior away from the original task contract
- source comments, policy-triggering decoys, or prompt-like headers that cause an AI scanner to stop before inspecting executable payloads, metadata, or generated artifacts
- rendered text differing from model-visible, OCR-derived, or extracted text, or document resources that execute network callbacks during conversion or preview in high-risk document-ingestion paths
- chain-of-tools execution without verification, including multi-stage promptware behavior that turns an initial injection into privilege escalation, reconnaissance, persistence or memory poisoning, command-and-control, lateral movement, or actions on objective

4. Check the mitigations.
- clear trust labeling
- rendered-versus-extracted text comparison and realistic action-oriented test cases for high-risk HTML, PDFs, office documents, screenshots, OCR inputs, browser agents, web-ingesting agents, and computer-use agents. Add authorized callback or SSRF tests against owned, non-production endpoints with synthetic data and no real secrets only when the ingestion, conversion, browser, tool, callback, or server-side request path can dereference remote resources. Static payload sets, harmless text-output tests, or non-adaptive red-team prompts do not support broad robustness claims
- approved tool registry with source, scope, and review date for nontrivial tool surfaces
- inventory, version pinning, provenance review, and permission review for installed skills, plugins, IDE/editor extensions, MCP servers, connectors, and agent packages
- provenance labels for memory and retrieved facts
- declarative memory entries that record facts or preferences, not future commands or standing policy
- tool scoping
- tool-side parameter validation and deny-by-default tool allowlists
- least-privilege MCP tool exposure and OAuth scopes
- for MCP or MCP-like protocols, verify token audience and issuer, reject token passthrough, require per-client or per-user consent where the protocol or deployment model requires it, validate authorization and redirect URLs, apply SSRF-safe discovery and fetch policy, verify inbound requests, and bind session or request state to the authenticated user or client
- no secret values in prompts, memory, traces, logs, or tool outputs
- no long-lived provider keys pasted into unvetted plugins or editor extensions
- no automatic promotion of generated, retrieved, or media-derived facts into trusted memory
- approval boundaries
- default disclosure minimization for agent tools, MCP results, review packets, and summaries; treat derived classifications, thresholds, event types, labels, decision reasons, local paths, identifiers, trace data, and diagnostic metadata as potentially sensitive when they reveal protected state or enable later tool misuse
- treat domain allowlists and read-only methods as capability limits, not disclosure authorization. Bind the permitted operation, acting identity or credential, target, parameters, and data, and evaluate the aggregate request sequence when separately permitted choices can encode protected state
- sandboxing plus authentication and deterministic authorization for local control planes; loopback alone is not sufficient when an agent can browse untrusted content on the same host
- treat model-only approval, model self-review, redaction, and pattern matching as heuristics. Enforce authorization, exact action and parameter binding, data-disclosure policy, and side-effect limits in deterministic application code. Add process, filesystem, credential, or network isolation where the threat model requires it
- schema validation and safe parsing for skill, plugin, and agent configuration files
- comparison of declared skill, plugin, IDE/editor extension, MCP, or agent-package purpose, triggers, permissions, and metadata against bundled behavior, tool calls, file/network effects, trace evidence, and execution-chain previews for unfamiliar setup or recovery commands where available
- syntax-aware source, package, and artifact inspection that treats prompt-like comments as untrusted data rather than authoritative instructions or refusal triggers
- decoding or normalization used only for inspection, with decoded text kept untrusted unless independently authorized by the task source
- redaction of raw screenshots, inline images, data URLs, high-entropy base64 media, and sensitive visual state before prompts, traces, transcripts, exports, or logs are persisted
- output filtering and adaptive-attacker review when a defense claim matters: vary encoding, rendering path, payload location, task framing, timing, model, tool path, and action target before claiming the mitigation is robust
- human review at irreversible steps

## Multimodal And Persistent Memory Checks
Use these checks when the task includes images, PDFs, screenshots, hidden text, retrieval, MCP, tools, or memory.

- Inspect model-visible or OCR-derived text separately from the user's instruction; compare visible rendering with extracted text when custom fonts, embedded resources, hidden layers, OCR, or document conversion can change what the model sees; treat OCR and document-parsing model output as model-derived extracted evidence, not a neutral transcript, preserving page, image, region, render settings, model or extractor version, and confidence or proof gaps when downstream action, citation, data extraction, or memory writes depend on it.
- Treat puzzle, challenge, roleplay, and "solve this" framing as possible social engineering when tool or memory use follows.
- Permit every persistent write only when an enabled project policy authorizes the write class and, in addition, the current User requests or confirms the write or the claim is independently validated under that policy; require a trusted caller identity as a separate control.
- Store declarative data in a constrained schema with source, timestamp, validation status, tenant, retention, and deletion or rollback metadata.
- Do not store executable instructions or secret values in general-purpose memory.
- Require current explicit User confirmation for sensitive, identity- or profile-changing writes even when an exact SOW grant authorizes that write class. Provenance is evidence only and never write authority; imperative instructions and secrets are never general-purpose memory entries.

## Output

Provide:

1. confirmed injection paths
2. plausible but unconfirmed risks
3. current mitigations
4. missing mitigations
5. smallest credible fixes
6. acceptance evidence with objective checks, manual acceptance items, and any unverifiable residuals

## Guardrails

- Do not treat all untrusted text as equally dangerous. Trace the execution path.
- Do not claim injection success without demonstrated unintended influence over model output, decision-making, state, tool use, or data handling. Record exploitability and impact separately.
- Do not confuse prompt injection with generic bad content quality.
