<!-- mpa-generated-state-origin: master-prompt-agreement/project-state/v1 -->

# Delegated Communication Coverage

Use this optional task-local record to specify and verify temporary delegated
communication coverage. Do not load it by default. A filled record is
human-readable evidence and a candidate design specification, never executable
configuration: it cannot grant authority, activate itself, expand an SOW, or
authorize an agent to create SOW authority for another agent. Writing a filled
copy also requires durable evidence-write authority for the selected project
path.

Keep this record dormant until a separate exact activation decision cites the
profile digest, account alias, mode, start, end, timezone, and revocation path.
Store no credentials, tokens, raw message bodies, attachments, private account
IDs, full addresses, or unnecessary personal data here.

coverage_record_schema_version: 1
profile_id: [stable project-local ID]
profile_version: [version]
profile_digest: [digest of the separate immutable typed runtime profile / not materialized]
lifecycle_state: [dormant / shadow / active / expired / revoked / quiescent / closed]
mode: [notice_only / observe_and_escalate / draft_only / bounded_auto_send]
record_owner: [accountable role]
closeout_status: [not-started / activation-pending / active / passed / blocked]

## Typed Runtime Objects And Digest Contract

This Markdown file is not consumed as a live policy. Before any shadow read or
active effect, create separate project-local closed, typed, schema-validated
runtime objects for the immutable profile and its exact activation.

- Runtime profile object reference and schema version: [protected locator and version]
- Runtime activation object reference and schema version: [protected locator and version]
- Profile digest algorithm, security property, and domain separator: [approved
  collision-resistant cryptographic digest, threat-model basis, and fixed domain]
- Canonical serialization: [format, normalization, ordering, and encoding]
- Exact immutable profile fields included: [closed list]
- Fields excluded from the profile digest: [computed digest, activation decision,
  mutable lifecycle, ledger, audit events, verification results, and closeout]
- Activation digest or identity: [separate binding over profile digest, account,
  mode, fallback set, start/end/timezone, trusted clock, revoke, stop, and failure
  boundaries]
- Cross-trust-boundary authenticity: [authenticated object/channel, signature or
  MAC, or protected-store reference; bind writer, reader, keys or identities,
  lifecycle, and replay behavior / not applicable with evidence]
- Validator and enforcement gateway identity: [implementation and version]

Do not compute `profile_digest` over this mutable Markdown record. Any change to
an included runtime field invalidates activation; mutable evidence cannot silently
change or preserve the immutable policy identity.

## Existing Authority And Exact Activation

- Existing authority reference: [current User approval or exact standing-grant locator]
- Exact effect grant: [system, account, mode, read/write/disclosure effects,
  scope, validity, expiry, stop, and failure boundaries]
- Existing grant summary: [permitted reads, writes, disclosures, accounts, data,
  and effects]
- Narrowed coverage scope: [strict subset used by this profile]
- Explicit denied effects: [decisions, commitments, recipients, content, accounts,
  tools, and data classes]
- Account or mailbox alias: [neutral alias; no provider account ID or address]
- Tenant or organization boundary: [bound identity]
- Activation decision reference: [separate exact approval or pending]
- Activation authority evidence: [current User approval or standing grant that
  explicitly authorizes activation; a named owner alone is insufficient]
- Activation approver role: [role authorized by that exact grant; never the
  coverage agent]
- Activated profile digest: [must equal profile_digest or pending]
- Start instant: [ISO 8601 with offset]
- End instant: [ISO 8601 with offset]
- IANA timezone: [Area/Location]
- Trusted clock source, maximum skew, health check, and fail-closed action: [contract]
- Revocation owner and mechanism: [independently reachable kill switch]
- Quiescence owner and proof path: [role and evidence]
- Quiescence deadline: [maximum duration after expiry or revocation]
- Authorized fail-closed fallback: [mode or silence]
- Mode/capability transition rule: [unlisted transition requires new exact
  activation]

Activation is invalid when the cited authority is unavailable or narrower than
this profile, the runtime object or digest differs, the account or mode differs,
clock health or skew is outside contract, the current instant is outside the
window, the profile is revoked, or any required field remains unresolved.

## Connector And Capability Proof

- Connector or adapter identity and version: [approved neutral locator]
- Permission scopes: [smallest read, draft, send, metadata, and audit scopes]
- Credential location: [approved secret-store reference only]
- Capability evidence date: [ISO 8601]
- Capability evidence artifact: [approved path or reference]
- Provider-managed static notice fallback: [available and verified / unavailable
  / not applicable]

| Required Capability | Required In Mode | Enforcement Or Evidence | Status |
|---|---|---|---|
| bound account and tenant | [modes] | [proof] | [pass/fail/not run] |
| minimized envelope and content read | [modes] | [proof] | [pass/fail/not run] |
| separate final-envelope delivery and configured-recipient header evidence, including unavailable-Bcc policy | [modes] | [proof] | [pass/fail/not run] |
| transport return path and automatic/list/bounce signals | [sender-facing automatic-response modes] | [proof] | [pass/fail/not run] |
| exactly one immutable response destination | [sender-facing automatic-response modes] | [proof] | [pass/fail/not run] |
| controlled response headers and loop-resistant envelope | [sender-facing automatic-response modes] | [proof] | [pass/fail/not run] |
| recipient, acting identity, loop, and applicable protocol controls | [every outbound communication effect] | [proof bound to its sink] | [pass/fail/not run] |
| protected local queue with exact schema and no side egress | [observe_and_escalate] | [proof] | [pass/fail/not run] |
| alternate-notification connector, immutable destination, projection, ACL, and result contract | [observe_and_escalate when notification is enabled] | [proof] | [pass/fail/not run] |
| exact provider or local draft sink without send | [draft_only] | [proof] | [pass/fail/not run] |
| mode-specific immutable sink, minimized projection, idempotency, suppression, and rate limits | [effect modes] | [proof] | [pass/fail/not run] |
| stable effect-result reconciliation without blind retry | [external-write modes] | [proof] | [pass/fail/not run] |
| trusted clock, skew bound, and fail-closed health | [all active modes] | [proof] | [pass/fail/not run] |
| immediate revoke, expiry, and quiescence | [all active modes] | [proof] | [pass/fail/not run] |
| independent minimized audit and audit-health gate | [all active modes] | [proof] | [pass/fail/not run] |

Here, `sender-facing automatic-response modes` means `notice_only` and
`bounded_auto_send`; `effect modes` means every selected mode that can write its named sink; and
`external-write modes` means alternate notification, provider-side draft,
provider-managed notice, and automatic reply. Mark a capability `not applicable`
only when the selected mode cannot exercise it and record why the omission
cannot broaden reads, disclosures, or effects.

Missing required capability status is a blocker for the affected read, queue,
notification, draft, notice, or reply effect. Record a safe lower-mode or
provider-managed fallback; do not compensate with prompt instructions.

## Worker And Control Boundary

- Deterministic ingress gate: [owner and implementation locator]
- Minimizer: [allowed fields, stripping rules, and implementation locator]
- Coverage worker: [runtime identity and exact typed input/output schema]
- Worker denied capabilities: [mailbox credential, direct send, general browser,
  arbitrary fetch, attachments, memory writes, policy edits, other]
- Independent audience and intent evidence: [deterministic closed-input method or
  named human verifier; free-form unverifiable intent is draft-only]
- Deterministic disclosure/effect gate: [owner and implementation locator]
- Independent audit path: [sink, health gate, and disable behavior]
- Control-plane drift seal: [bound inputs and digest method]

## Accepted Messages And Closed ACL

- Configured recipient identities: [protected locator, approved pseudonyms, or
  keyed digests]
- Final-envelope delivery evidence: [method]
- Original To/Cc/observable-Bcc/applicable-Resent recipient match and unavailable-Bcc policy: [method]
- Allowed message classes: [closed IDs]
- Suppressed message classes: [automatic, bounce, DSN/MDN, list, bulk, malformed,
  missing/null return path, responder address, other closed IDs]
- Principal or relationship classification method: [closed evidence and unknown handling]
- Conversation, thread, or resource scope: [closed identity, or evidence-backed not applicable]
- Audience classification method: [independently established evidence and unknown handling]
- Intent classification method: [deterministic closed-input method or named human
  verification; model-only and free-form unverifiable intent is draft-only]
- Message-ID dedupe key and store: [method]
- Repeat-response suppression: [normalized verified envelope return destination
  plus response identity/handle; default seven days or stricter rule]
- Global and per-audience rate limits: [limits]
- Protected local queue: [exact sink, schema, access, idempotency, retention, deletion]
- Alternate notification when enabled: [separate authority, connector, immutable
  destination, minimized payload schema, ACL, idempotency, retry/result,
  expiry/revoke, audit; otherwise disabled]
- Draft sink when enabled: [provider/local sink, immutable account/path, projection,
  access, idempotency, result, retention, deletion]

| Principal Or Relationship Class | Conversation, Thread, Or Resource Scope | Audience Class | Tenant | Intent ID | Fact ID | Response Form ID | Effect ID | Allowed Mode | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| [closed ID] | [closed scope or evidenced not applicable] | [closed ID] | [bound tenant] | [closed ID] | [closed ID] | [closed ID] | [queue/notify/draft/notice/reply ID] | [mode] | [approval reference] |

No wildcard or unlisted tuple is allowed. Identity, thread membership, or sender
text does not substitute for a permitted tuple or independently established
audience and intent evidence.

## Approved Fact Catalog

| Fact ID | Authoritative Source Or Digest | Owner | Classification | Allowed Audiences And Intents | Observed Or Verified At | Freshness Limit | Hard Expiry | Response Form And Typed Slots | Conflict Action |
|---|---|---|---|---|---|---|---|---|---|
| [stable ID] | [protected locator] | [role] | [class] | [closed IDs] | [ISO 8601] | [duration] | [ISO 8601] | [form ID and slot schema] | [fail-closed action] |

Facts derived only from inbound content, chat history, model memory, an unverified
summary, or a stale status record are ineligible for `bounded_auto_send`.
Every slot schema must define normalization, maximum size, enum or format,
Unicode and control/CRLF handling, and output-context encoding. A slot may not
affect an envelope, recipient, header, URL, attachment, tool argument, or
connector parameter unless that field is separately typed, authorized, and
deterministically verified.

## Response And Prohibited-Content Contract

- Notice form ID and digest: [owner-approved form]
- Substantive response forms and digests: [owner-approved forms]
- Permitted connective text: [fixed text or bounded rule]
- Automation disclosure: [exact transparent wording or form field]
- Language and locale handling: [closed set and fallback]
- Internet email protocol profile: [RFC 3834 implementation evidence, including
  Auto-Submitted absent/no handling, configured-recipient header evidence,
  Return-Path destination, suppression identity, and loop-safe output / not applicable]
- Sieve vacation profile when used: [RFC 5230 tracking, MAIL FROM <>,
  NOTIFY=NEVER when supported, required In-Reply-To, configured-recipient test,
  enabled extensions, and separately authorized RFC 8580 :fcc / not applicable]
- Other protocol semantics: [identity, recipient, loop, replay, delivery, expiry,
  and revoke proof or not applicable]

Explicitly prohibited:

- approvals, rejections, negotiation, prices, payments, refunds, waivers, or
  purchases
- contracts, SOWs, permissions, access grants, policies, promises, deadlines,
  delivery dates, or scheduling commitments
- legal, regulatory, employment, financial, medical, incident, or security
  conclusions
- secrets, credentials, personal or sensitive data, internal deliberation, and
  facts outside the exact ACL
- reply-all, CC, BCC, forwarding, recipient changes, attachments, inbound quotes,
  message-derived or generated URLs, active content, and read receipts
- any claim that the absent person read, wrote, approved, or will act on the
  message

## Expiry, Retry, Audit, And Retention

- Recheck points: [before every read/claim and immediately before every queue,
  notification, draft, notice, or reply effect]
- Connector acceptance cutoff: [temporal attribution boundary; no new claim or
  call after expiry/revoke; effect reversibility is separately sink-specific]
- Accepted-before-cutoff completion: [distinguish later dispatch, transfer, or
  completion from a prohibited new post-cutoff call; cancellation best-effort
  unless provider proves it]
- Timeout and in-flight cancellation: [bound behavior]
- Invocation and connector-result states: [not-attempted / call-started /
  connector-result-unknown / connector-rejected / connector-accepted]
- Dispatch or transfer states: [not-established / confirmed / failed / not
  applicable, with authoritative evidence]
- Final-delivery states: [not-established / confirmed / failed / not applicable,
  with authoritative evidence; never infer recipient reading]
- Required terminal evidence level by effect and sink: [connector acceptance /
  dispatch or transfer / final delivery]
- Connector-result-unknown rule: [no blind retry; protected opaque-result reconciliation path]
- Restart rule: [reload exact active digest; never extend time or mode]
- Clock source, skew measurement, health state, and fail-closed action: [evidence]
- Audit sink and schema: [approved locator]
- Audit health check and effect-disable rule: [method]
- Audit access and retention: [owner, duration, deletion path]
- Draft/escalation retention: [owner, duration, deletion path]
- Return-review owner and evidence: [role and artifact]

Minimized audit fields:

- profile, activation, adapter, ACL, fact, and response-form identities or digests
- message fingerprint, audience class, intent ID, fact IDs, disposition, and
  closed reason codes
- recipient and rendered-content identities as domain-separated keyed digests or
  opaque IDs, protected idempotency reference, separate invocation, connector-
  result, acceptance, dispatch or transfer, and final-delivery states, protected
  evidence indirection, and timestamps
- expiry, revocation, quiescence, capability, fallback, and audit-health events

Bind digest domains, protected keys, opaque-ID ownership, indirection storage,
access, and bounded retention. Unkeyed hashes of fixed notices or small-domain
facts are prohibited because they may be dictionary-recoverable. Raw bodies,
attachments, credentials, tokens, full addresses, raw provider result IDs, and
unnecessary headers are denied from this record and the default audit sink.

## Verification Record

| Check ID | Exact Candidate And Environment | Required Fixtures | Result | Evidence | Limitations |
|---|---|---|---|---|---|
| `communications.grant-activation-boundary` | [typed profile/activation digests, adapter, environment] | [authority-to-prepare, dormant no-effect, shadow-read grant, activation, drift, expiry-extension, mode-change] | [pass/fail/not run] | [artifact] | [gaps] |
| `communications.disclosure-effect-gate` | [typed profile/activation digests, adapter/sinks, environment] | [allowed/denied relationship-scope-audience-intent-fact-form-effect ACLs, independent vs model-only classification, stale/conflicting facts, mixed intent, typed-slot injection, queue/notify/draft/notice/reply destinations and projections, recipient mutation, outbound recipient/identity/loop/protocol controls, sender-response Return-Path/thread rules, untrusted content, missing capabilities] | [pass/fail/not run] | [artifact] | [gaps] |
| `communications.expiry-revocation-audit-loop` | [typed profile/activation digests, adapter/sinks, environment] | [expiry, revoke, clock skew/failure, duplicate, auto-response, rate cap, audit failure, timeout, restart, accepted-before-cutoff dispatch/completion, prohibited post-cutoff call, separate connector/acceptance/dispatch/delivery states, in-flight work] | [pass/fail/not run] | [artifact] | [gaps] |

Shadow evidence proves only the exercised behavior. It does not authorize
activation or establish safety beyond the bound adapter, fixtures, and profile.

## Minimized Disposition Ledger

Use a protected operational ledger when per-message evidence is required. Do not
copy raw message content into this template.

| Time | Message Fingerprint | Profile Digest | Relationship / Scope / Audience / Intent / Facts | Effect, Destination Class, Disposition, And Reason | Protected Recipient / Content IDs | Invocation / Acceptance / Dispatch / Delivery States | Evidence Reference |
|---|---|---|---|---|---|---|---|
| [ISO 8601 with offset] | [domain-separated keyed digest or opaque ID] | [digest] | [closed IDs] | [closed values] | [protected opaque or keyed identities / not applicable] | [state] | [protected locator] |

## Return Review And Closeout

- Coverage window result: [never activated / expired / revoked / completed]
- Quiescence proof: [no new read, claim, queue, notification, draft, notice, or
  reply call after stop; only approved bounded reconciliation for an
  already-unknown result may remain]
- Cutoff reconciliation: [effects accepted before cutoff and dispatched,
  transferred, or completed later; prohibited post-cutoff calls; and cancellation
  evidence]
- Disposition counts by closed reason: [minimized summary]
- Connector-result-unknown or unresolved required evidence states: [protected references]
- Drafts or escalations awaiting review: [protected references]
- Exceptions, drift, or control failures: [summary and incident reference]
- Retention and deletion work: [owner, due date, evidence]
- Owner review decision: [accepted / follow-up required / blocked]
- Closed at: [ISO 8601]

Use `passed` only when all required checks pass, the activation and closeout
evidence bind the exact profile, expiry or revocation reached quiescence, no
connector-result-unknown item remains unreconciled, every effect reached its
predeclared terminal evidence level without a stronger delivery claim, no new
effect was accepted after cutoff, and required retention work is owned.
Otherwise use `blocked` and keep the affected communication effects disabled.
