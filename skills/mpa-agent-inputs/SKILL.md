---
name: mpa-agent-inputs
description: "Checks for features where untrusted text reaches a model, a tool call, or stored memory, and Model Context Protocol changes through revision 2026-07-28. Use when building or reviewing MCP or other tool servers and clients, prompt-injection defences, retrieval, browser agents, or agent memory."
---

# Untrusted input to models and agents

Current to Model Context Protocol revision 2026-07-28, checked 2026-11-27. For a newer revision, read what changed after 2026-07-28 in the release notes (https://modelcontextprotocol.io/specification/) before relying on this file; up to 2026-07-28 no lookup is needed.

Trace each untrusted input to what it can cause: a model decision, a tool call, a write to durable state, a disclosure, or another side effect. That path decides the risk. Instructions to the model and input filters lower the odds; they do not close the path.

## Overlooked inputs and chains

- Images, PDFs, OCR output, and rendered documents: hidden or low-contrast text, invisible Unicode, font glyph remapping, and metadata make extracted text differ from what a person sees.
- Summaries that carry an injected instruction forward as trusted text, and chains of individually harmless tool calls that add up to reconnaissance, persistence, or exfiltration.

## Containment

- Require confirmation by a person before consequential actions: state changes, payments, credential changes, deletions, outbound messages. Auto-submit attributes, autonomous loops, and a tool's own read-only or non-destructive annotation must not skip it. Show the exact action and parameters from code, not a model-written summary.
- Run model-generated code and commands in an isolated environment without secrets and with bounded network, behind a review or policy check between generating and executing.
- Tool allowlists deny by default. Validate parameters on the tool side and give each tool the narrowest scope.
- Pin approved tool manifests and descriptions; a changed tool definition or scope voids the earlier approval.
- Do not let an agent modify, override, or impersonate its own policy, approval, or credential store.

## Stored memory

- Untrusted input does not write to persistent memory directly; writes need a user request or confirmation, or independent validation under a stated policy.

## Claims

- Report an injection as successful only when unintended influence on output, state, tool use, or data handling was demonstrated.

## Model Context Protocol 2026-07-28

- The revision removes protocol sessions and the `Mcp-Session-Id` header and drops the `initialize` handshake: each request carries its protocol version and client capabilities in `_meta`, and a server describes itself through `server/discover`. A server that needs state across calls mints its own handle and receives it back as an ordinary tool argument, so the server binds that handle to the authenticated user itself.
- Server-initiated requests (`sampling/createMessage`, `elicitation/create`, `roots/list`) are gone. A server asks for more input by returning `resultType: "input_required"` with `inputRequests`, and the client answers by sending the request again; every result carries `resultType`, and a client treats a result without it as `complete`.
- A broken response stream is not resumed (`Last-Event-ID` and SSE event IDs are removed): the client sends the request again under a new request ID, so a tool that changes state has to be safe to call twice.
- A client checks a present `iss` in the authorization response against the recorded issuer before redeeming the code, keys stored client credentials by issuer, and registers again when the authorization server changes.
