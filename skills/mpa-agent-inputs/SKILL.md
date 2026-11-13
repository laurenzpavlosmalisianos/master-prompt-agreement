---
name: mpa-agent-inputs
description: Checks for features where untrusted text reaches a model, an agent, a tool call, or stored memory. Use when designing or reviewing defences against prompt injection, MCP or other tool servers, RAG and retrieval, tool results, browser agents, or agent memory.
---

# Untrusted input to models and agents

Trace each untrusted input to what it can cause: a model decision, a tool call, a write to durable state, a disclosure, or another side effect. That path decides the risk. Instructions to the model and input filters lower the odds. They do not close the path.

## Inputs that get overlooked

- Tool output, tool descriptions and schemas, resource payloads, and capability-discovery responses from tool servers.
- Output of other agents, especially a lower-privilege agent feeding a higher-privilege one.
- Review comments, CI diagnostics, lint and test messages, and generated remediation text.
- Skills, plugins, editor extensions, and agent configuration stored in a repository. Being installed or popular does not make them trusted.
- Images, PDFs, OCR output, and rendered documents. Hidden or low-contrast text, invisible Unicode, font glyph remapping, and metadata make the text a model reads differ from what a person sees.
- Tool surfaces that a web page declares for browser agents.

## Patterns

- Instructions inside tool descriptions or metadata.
- Encoded, translated, or look-alike text that becomes an instruction after decoding.
- Role-play, "developer mode", or puzzle framing that says the rules do not apply; gradual drift over many turns.
- A summary that carries an injected instruction forward as if it were trusted text.
- Setup or recovery commands taken from retrieved text and run before reading what they execute.
- A chain of individually harmless tool calls that adds up to reconnaissance, persistence, or exfiltration.

## Containment

- Enforce authorization, approval, and disclosure limits in deterministic code, bound to the acting identity and the exact action and parameters. A model's decision, an approval visible only to a model, model self-review, redaction, and pattern filters are heuristics, not authorization.
- Require confirmation by a person before consequential actions: state changes, payments, credential changes, deletions, outbound messages. Auto-submit attributes and autonomous loops must not skip it.
- Tool allowlists deny by default. Validate parameters on the tool side and give each tool the narrowest scope.
- Pin approved tool manifests and descriptions. A changed tool definition or scope voids the earlier approval.
- For tool-server protocols, verify token audience and issuer, do not pass a user's token through to another service, and bind session state to the authenticated client. Authorization requirements differ between protocol versions; check the specification version the server implements.
- Bind browser-agent actions to verified origins, so that injected content cannot act with the user's existing session.
- Outbound requests disclose data even when read-only and to an allowed domain: through the URL path and query, headers, the choice of link, DNS lookups, fetched images, and request order. An allowlist limits capability. It does not authorize disclosure.
- Loopback is not a trust boundary when an agent or browser that reads untrusted content runs on the same host. Local services need authentication.
- Keep secrets out of prompts, memory, traces, and tool output. Untrusted content must not be able to trigger a secret lookup.
- Screenshots and inline images in stored traces carry whatever was on screen. Redact before storing.

## Stored memory

- Untrusted input does not write to persistent memory directly. A write needs a request or confirmation from the user, or independent validation under a stated policy.
- Store declarative facts with source, time, and validation status, in a form that can be rolled back. Do not store instructions or secret values.
- Where a claim came from is evidence about it, not permission to store it.

## Claims

- Report an injection as successful only when unintended influence on output, state, tool use, or data handling was demonstrated.
- Call a defence robust only after adaptive testing that varies encoding, rendering path, payload position, framing, and tool path. A static payload list supports no broad claim.
- For document and browser agents, compare rendered text with extracted text.
