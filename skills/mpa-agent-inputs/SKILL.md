---
name: mpa-agent-inputs
description: "Checks for features where untrusted text reaches a model, an agent, a tool call, or stored memory. Use when designing or reviewing defences against prompt injection, MCP or other tool servers, RAG and retrieval, tool results, browser agents, or agent memory. For AGENTS.md or skills, use mpa-agent-instructions."
---

# Untrusted input to models and agents

Trace each untrusted input to what it can cause: a model decision, a tool call, a write to durable state, a disclosure, or another side effect. That path decides the risk. Instructions to the model and input filters lower the odds; they do not close the path.

## Overlooked inputs and chains

- Tool output, tool descriptions and schemas, resource payloads, and capability-discovery responses from tool servers.
- Output of other agents, especially a lower-privilege agent feeding a higher-privilege one.
- Review comments, CI diagnostics, lint and test messages, generated remediation text, and repository-stored skills, plugins, or agent config (`mpa-dependency-change`).
- Images, PDFs, OCR output, and rendered documents: hidden or low-contrast text, invisible Unicode, font glyph remapping, and metadata make extracted text differ from what a person sees.
- Tool surfaces that a web page declares for browser agents.
- Summaries that carry an injected instruction forward as trusted text, and chains of individually harmless tool calls that add up to reconnaissance, persistence, or exfiltration.

## Containment

- Enforce authorization, approval, and disclosure limits in deterministic code bound to the acting identity, exact action, and parameters. A model's decision, a model-only approval, model self-review, redaction, and pattern filters are heuristics, not authorization.
- Require confirmation by a person before consequential actions: state changes, payments, credential changes, deletions, outbound messages. Auto-submit attributes and autonomous loops must not skip it.
- Tool allowlists deny by default. Validate parameters on the tool side and give each tool the narrowest scope.
- Pin approved tool manifests and descriptions; a changed tool definition or scope voids the earlier approval.
- For tool-server protocols, verify token audience and issuer, do not pass a user's token through to another service, and bind session state to the authenticated client. Authorization requirements differ between protocol versions; check the specification version the server implements.
- Bind browser-agent actions to verified origins, so injected content cannot act with the user's existing session.
- Outbound requests disclose data even when read-only and to an allowed domain: through URL path and query, headers, link choice, DNS lookups, fetched images, and request order. An allowlist limits capability; it does not authorize disclosure.
- Loopback is not a trust boundary when an agent or browser reading untrusted content runs on the same host; local services need authentication.
- Keep secrets out of prompts, memory, traces, screenshots, and tool output (`mpa-data-privacy`). Untrusted content must not be able to trigger a secret lookup.
- Do not let an agent modify, override, or impersonate its own policy, approval, or credential store.

## Stored memory

- Untrusted input does not write to persistent memory directly; writes need a user request or confirmation, or independent validation under a stated policy.
- Store declarative facts with source, time, and validation status in a form that can be rolled back. Do not store instructions or secret values.
- Where a claim came from is evidence about it, not permission to store it.

## Claims

- Report an injection as successful only when unintended influence on output, state, tool use, or data handling was demonstrated.
- Call a defence robust only after adaptive testing that varies encoding, rendering path, payload position, framing, and tool path. A static payload list supports no broad claim.
- For document and browser agents, compare rendered text with extracted text.
