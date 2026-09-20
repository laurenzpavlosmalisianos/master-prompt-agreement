Task Order — Agent Orchestration

Objective

Coordinate multiple task orders, practice-guide checks, and authorized action steps in sequence, or in bounded independent parallel steps when authorized. Each sub-agent receives a structured handoff for its step. The Agent orchestrates the workflow and aggregates results.

This Task Order owns generic live reviewer and scoped-worker fan-out: lane selection, launch envelopes, handoffs, lifecycle, coordinator validation, and closeout. Formal dispute panels remain procedurally owned by `task_orders/arbitrate.md`; independent consultation remains owned by `task_orders/independent_assessment.md`; and recurring scheduled lanes remain owned by `task_orders/automation.md`. Those workflows may invoke this Task Order for common launch mechanics, but their case, outcome, authority, and lifecycle rules remain controlling. `practice_guides/prompt_agent_quality.md` owns design and evaluation quality for reusable agent workflows.

Procedure

0. Confirm Runtime Support

Confirm that the current runtime can launch fresh agent instances. If it cannot, stop and report that this task order is unsupported in the current runtime.

0.5. Optional Review Topology Setup

Use this setup only when the task is high-consequence, architecture-critical, source-policy-sensitive, public/private-boundary-sensitive, security/privacy-sensitive, or when independent reviewers materially reduce a stated failure risk. Do not invoke multiple reviewers only because they are available.

Before using reviewer lanes, record a reviewer lane plan in the handoff. A reviewer lane is any bounded source of candidate review output or objective verification, including a fresh agent, browser-backed external reviewer, external CLI reviewer, deterministic script, connector, or human reviewer. Availability does not grant authority; it may disqualify or constrain a lane, but it must not justify selecting one.

Every selected lane must have at least:

- Lane id, runtime class, discovery source, availability, effect mode, independence group, and fallback or abort rule.
- Allowed data packet, prohibited data classes, redaction rule, egress endpoint, auth/session policy, retained artifacts, timeout, rate or cost cap, and teardown rule.
- Output contract, artifact path or transcript policy, verifier gate, and coordinator validation requirement.
- A task-specific reason tied to a distinct failure mode, evidence perspective, deterministic check, policy challenge, security/privacy challenge, or architecture challenge.

For a low-risk internal lane, the handoff may use a compact manifest with lane id, runtime class, internal/external status, task-specific reason, evidence packet, prohibited data or redaction rule, egress endpoint if any, effect mode, verifier gate, fallback or abort rule, and retained artifact rule. External, connector, browser, human, paid, credentialed, or high-risk lanes require the full manifest above. If required fields are unknown, reduce the evidence packet, convert to an internal lane, use a deterministic check, defer the lane, or abort the lane.

Every durable review packet records typed `lane_controls` for independence
group, fallback or abort, authentication/session policy, timeout, rate or cost
cap, and teardown. A full manifest uses `manifest_kind: full` and records every
control as an explicit, nonempty value with its basis. External, connector,
browser, human, paid, credentialed, and high-risk packets require that full
manifest. A low-risk internal packet may use `manifest_kind: compact_internal`;
each control still appears and records whether its value is explicit, inherited
from a named universal control, derived with a stated basis, or not applicable
with a null value and stated basis. Compactness never means omission. The
validator rejects a human runtime or supplied external-reviewer status with a
compact manifest; the lane inventory and operator remain responsible for
classifying the other full-manifest cases. These controls and the manifest kind
belong to the canonical approval binding.

An `independence_group` is an operator-declared correlation label, not proof of
blindness or statistical independence. When a review relies on either property,
its control basis and preflight evidence must record the actual context
inheritance (`none`, bounded handoff only, or full history) and shared
model/provider, runtime, session, tool, state, and evidence dependencies. Verify
those facts from the runtime when it exposes them. If they cannot be verified,
label the lanes correlated or non-blind and narrow the claim rather than
asserting independence.

Scoped workers use the Section 2 handoff rather than a reviewer manifest. The handoff must still state the worker's purpose and scope, evidence or input packet, tool and data boundary, budget or usage cap when material, output shape, verifier gate, and stop condition.

Capability discovery is manual or declarative by default. The Agent may read project-approved capability records, SOW entries, runtime tool lists, or explicit User grants. The Agent must not auto-probe browser profiles, signed-in accounts, API keys, environment variables, shell history, credentials, cloud accounts, paid endpoints, or external services to discover lanes. If a lane requires account/session access or data egress that is not already authorized, ask the User or mark the lane unavailable.

External reviewer lanes receive only an approved evidence packet, built from a positive allowlist, not an open workspace. The packet records each evidence item, source, classification, redaction, recipient endpoint, retention expectation, and inclusion reason before egress. Before transmission, the exact packet manifest must have current User/SOW approval or pass a named deterministic sanitization gate authorized for that data class; protected data still requires the applicable action-time approval. Browser screenshots, uploads, clipboard content, and visible session state are egress events. Browser-backed lanes use isolated sessions by default, or an explicitly approved user session named in the manifest.

Use `runtime/review_packet.schema.json` and validate the live lifecycle bundle
with `scripts/review_packet_contract.py` when an external or high-risk reviewer
lane needs a durable record. The schema owns structural shape; the validator
owns stage coherence, canonical binding, receipts, chronology, disclosure-byte
identity, and retained output and verification evidence. The project-specific
lane inventory may narrow permitted lane IDs, invocation owners, destination or
account boundaries, effect modes, and required checks; it must not weaken those
invariants. Schema version 5 is current-only: older packet formats require a
supporting implementation and are rejected rather than silently upgraded. The
selected `effect_mode` is `observe` or `propose`, belongs in the canonical
approval binding, and must be allowed by the selected lane.

The lifecycle distinguishes invocation ownership from reviewer runtime class.
Classify the runtime as model, human, deterministic tool, or hybrid. Do not
invent model provenance for a human or deterministic tool. Every active
invocation records its exact runtime label and execution mode; model and hybrid
lanes additionally record a pre-approval `planned_model_policy`. That policy
states its planned model identifier when exposed, one version kind from
`immutable_snapshot`, `stable_alias`, `moving_alias`, or `not_exposed`, and the
selection basis. The active invocation records `observed_model` with the
observed identifier when exposed, the same version-kind vocabulary, whether it
matched the planned policy, and the comparison basis. A moving alias is an
identifier, not an exact immutable model identity. Do not infer version kind
from identifier spelling; use runtime or provider evidence, and use
`not_exposed` without an invented identifier when identity is unavailable.
When `matches_planned_policy` is true, an immutable planned snapshot requires
the same observed immutable snapshot. A planned stable or moving alias may
match the same alias or an observed immutable snapshot resolved from that alias,
with the comparison basis recording the resolution evidence. A planned
`not_exposed` policy may transition to any observed version kind because no
model identity was approval-visible; in that case the match attests conformance
to the bound selection basis, not equality to an undisclosed immutable identity.
A false match requires a blocked lifecycle.
Model and hybrid invocations also record either the reasoning effort or that the
runtime did not expose it. Human and deterministic-tool lanes use null planned
and observed model records. The planned runtime class, model policy, lane
controls, and selected effect mode are part of the packet approval binding;
changing any of them invalidates the packet-ready and pre-submission receipts
and requires a fresh approval cycle. See `docs/verification_and_quality.md` for
the broader provenance semantics.

Before approval, run the public validator with `--prepare-receipt packet_ready`
and an explicit `--validated-at` timestamp. It prints a validated proposal and
does not write the bundle. Record its packet digest, lifecycle update, and
receipt, rerun ordinary validation, and bind approval to that receipt digest.
After exact approval and the passed, timestamped lane preflight, repeat with
`--prepare-receipt pre_submission` immediately before invocation. Record that
proposal and rerun ordinary validation. Never submit when either preparation or
ordinary validation reports an error. If approval is declined, record matching
`declined` approval and lifecycle states, keep invocation unstarted or skipped,
and do not create a pre-submission receipt.

For long-running, hosted, browser-backed, paid, or external lanes, the manifest must include the run lifecycle policy. Once submitted and running, the coordinator defaults to passive polling and final-result extraction only. Abort, restart, replacement, or abandonment requires explicit User instruction, safety or privacy incident, wrong destination, unrecoverable tool or browser failure, quota or cost runaway, materially wrong packet before useful reviewer work starts, or a predeclared timeout or stuck-run rule. Record actor, time, reason, policy basis, partial-output handling, and whether the lane must be rerun from a corrected packet.

Reviewer, connector, human, browser, and model output is candidate material unless a named SOW or MSA authority designates the human as the approving owner for that exact decision. Factual claims still require evidence unless that authority is itself the primary source for the fact. The coordinator must deduplicate returned findings, reload primary evidence for every material claim, validate claims against primary evidence and deterministic checks when available, and reject findings that cannot be tied to evidence. Reviewer agreement, model diversity, model prestige, availability, or majority count is not adoption evidence.

For blind independent review, keep first-pass reports isolated. Comparable lanes receive the same approved sanitized evidence packet and output schema unless a recorded scope split requires distinct packets. A post-blind round, when authorized, must be evidence-directed and bounded to material contradictions, missing evidence, citation defects, rule-interpretation disputes, or proposed verifier checks; it must use an anonymized issue packet that excludes reviewer identities, model/provider cues, votes, tallies, leading-option language, hidden reasoning, raw traces, and pressure to agree. Record a second-pass packet sanitization check before distribution. Stop at the declared pass or stop condition. The review must not become open-ended consensus, persuasion, or convergence under another label.

1. Define the Workflow

The User specifies a sequence of workflow steps to execute. A step is one of: `order`, `guide`, or `authorized action`. The SOW may define named workflows for recurring sequences. Example gated workflows:

feature: task contract → plan → authorized implementation → review → audit → authorized commit
external-pr: read-only PR assessment → owner decision → optional authorized implementation → review or audit → authorized response
release: audit → review → `practice_guides/release_readiness.md` → authorized release action

If no named workflow applies, the User specifies the sequence directly.

2. Prepare the Handoff Document

<!-- mpa-orchestration-contract: orchestration-reload-bundle-v1 -->

Before each step, the Agent prepares the active handoff. When project
state-file maintenance is authorized and relevant, write that handoff to
TODO.md. Otherwise keep the handoff transient and carry unresolved handoff
items as candidates in the final report. The handoff includes:

- Reload bundle: the exact files the sub-agent must load before acting.
- Current step status: what is done and what remains.
- Files modified: what changed in the active slice.
- Step identifier, ownership boundary, expected output schema, verifier gate, checkpoint or resume rule, and integration owner when the workflow is long, parallel, or safety-sensitive. When repository or acquired-source identity matters, the rule binds the active acquisition transport, exact materialized revision or snapshot digest, only project-required selector or reference assertions, and relationships among differing produced, hosted, reviewed, and integrated immutable revisions; when live context may be lost, it also binds the expected candidate/source identity, completed phases and evidence locators, and last observed remote lifecycle status. Verify identity through its owning transport; on drift, stop or explicitly supersede the candidate.
- Open items: unresolved issues for the next step.
- Context for next step: what the sub-agent needs to know now.
- Durable decisions: identify separately. Record an adopted decision in
  DECISIONS.md only when state-file maintenance is authorized and relevant;
  otherwise return it as a candidate.

The reload bundle must include:

- Exact current User task or approved task contract
- Framework reference: [approved framework reference from the runtime entrypoint]
- Relevant project-contract slice from AGENT_PROJECT.md
- Current task order, if this is an order step: [framework reference]/task_orders/[step].md, or the matching runtime task module when explicitly chosen
- Current practice guide, if this is a guide step: [framework reference]/practice_guides/[guide].md
- Authorized action boundary, if this is an action step: exact approved action, write set or external target, verification gate, and stop condition
- Active handoff pointer in TODO.md when a handoff file exists

Load only on named triggers:

- Operative charter: [framework reference]/runtime/operative_charter.md when the worker has not already loaded its runtime charter
- MSA: [framework reference]/master_service_agreement.md when canonical MSA text, ambiguity, conflict, or framework revision requires it
- SOW: STATEMENT_OF_WORK.md when canonical project terms or omitted details matter
- Project state: TODO.md and DECISIONS.md when the step depends on current state or durable decisions
- Precedents: PRECEDENTS.md only when the step matches a recorded trigger

<!-- mpa-orchestration-contract: orchestration-authority-rule-v1 -->
<!-- mpa-orchestration-contract: orchestration-handoff-context-only-v1 -->
<!-- mpa-orchestration-contract: orchestration-sow-conflict-winner-v1 -->
<!-- mpa-orchestration-contract: orchestration-procedural-modules-v1 -->

The handoff must state the authority rule: platform/runtime instructions and the exact current User task govern the present step; the MSA, SOW, projected governing terms in the project contract, and non-delegable duties constrain and interpret that scope; selected Task Orders and Practice Guides provide procedures only; summaries, handoff prose, and resume evidence are non-authoritative context. The sub-agent reloads the files from disk before acting; on resume, it revalidates the bound candidate/source identity, governing authority, and live mutable state against current authoritative sources before relying on the handoff. If a governing term in AGENT_PROJECT.md conflicts with STATEMENT_OF_WORK.md, the SOW governs interpretation; report the drift, stop relying on the conflicting term, and never hand-edit the generated file. Its model-owned framework-reference binding is non-authoritative lifecycle data. An otherwise verified complete current-format retained-input/receipt pair with an intact recorded preimage may use candidate-input refresh; invalid managed-file preimage requires a separately reviewed manual correction. Task Orders and Practice Guides are procedures and do not override higher authority.

3. Execute Each Step

For each step in the sequence:

3.1. Launch a sub-agent (fresh agent instance) with the applicable Task Order, Practice Guide, or authorized-action envelope, plus the reload bundle and relevant handoff context.
3.2. The sub-agent executes that envelope and follows its acceptance criteria or verifier gate. A guide-only step applies the named guide to a bounded evidence packet; an authorized-action step states the exact grant, effect boundary, verifier gate, and stop condition.
3.3. On completion, the sub-agent returns a structured report with conclusion, material claims, evidence cited for each claim, checks performed, unverified assumptions, risks found, recommended disposition, confidence, scope limits, proposed actions, and proposed TODO.md or DECISIONS.md updates when needed. Source-policy reviews cite source references; code reviews cite file paths and line references where possible; privacy or egress reviews name the exact data class and egress path.
3.4. The Agent reloads primary evidence for material claims, validates or labels unresolved claims as hypotheses, and preserves the raw report at its evidence location when needed. When state-file maintenance is authorized and relevant, the coordinator updates TODO.md and DECISIONS.md only with validated open work or adopted decisions before proceeding to the next step; otherwise the coordinator carries those items as candidates in the final report.

A verification phase result is reusable only while its bound candidate,
material inputs, tools, environment, predecessor results, completion status,
and evidence locator remain unchanged; otherwise restart at the earliest
invalidated phase and complete the full required lane. After an authorized
durable repository mutation, bind any subsequent verifier to the immutable
revision established by authoritative repository readback.

Gate rule: If any step fails its acceptance criteria or verifier gate, stop dependent steps and report the failure. When the current task already authorizes an in-scope correction, correct the failure and reverify the affected gate before continuing; independent authorized work may proceed. Ask the User when correction requires new authority, changes the agreed scope, or leaves a decision that the Agent cannot safely resolve. Never treat a failed gate as passing or weaken it to continue.

4. Parallel Steps

When steps are independent and do not require sequential handoff, the Agent may launch worker agents in parallel only with User approval or explicit named-workflow authorization. The Agent must confirm independence before parallelizing. When in doubt, run sequentially.

Before launching parallel or fresh-agent fan-out, state the maximum workers, total agent/session limit, time or cost ceiling, write ownership, integration owner, verifier gate, and abort or backout path. Descendants require separate authority from the exact User task, SOW, or a named workflow that explicitly grants descendant creation; selecting a workflow or launching a worker does not suffice. For descendants, the same envelope also binds maximum depth, cumulative subtree workers and sessions, aggregate time or cost ceilings, parent lineage and validation, coordinator acceptance, and downward stop, cancel, timeout, abort, and teardown propagation. Each child receives a separate parent-to-child handoff narrowed to scope, data, tools, effects, and write ownership. If the runtime cannot verify cumulative limits or teardown propagation, require coordinator-owned fan-out or prohibit descendants.

In parallel mode, workers return structured reports or write per-worker artifacts. When state-file maintenance is authorized and relevant, only the coordinator updates TODO.md and DECISIONS.md. This write-ownership rule does not itself grant state-file authority.

When workers are authorized to edit files, each worker owns only its assigned write set. In parallel contexts, workers must not run VCS staging, commit, branch, merge, rebase, tag, push, or other repository-index commands. The coordinator performs any authorized VCS staging or commit only after sequential integration and status/diff inspection.

For large generated ports, rewrite shards, compiler-fix queues, or resource-heavy verification, define shared translation artifacts, shard ownership, and coordinator-only expensive commands before launch. Coordinator or named-verifier ownership applies to global builds, full tests, packaging, benchmarks, global or shared-state cleanup, operations that mutate shared runtime, lifecycle, cache, or index state, other non-isolated stateful operations, and work that materially contends for a bounded shared resource; ordinary isolated project-scoped commands, including cleanup confined to worker-owned outputs, are not serialized merely because they execute in the same runtime. A bounded handoff exception must define how access is serialized or isolated. Workers should report local diagnostics and small focused checks.

For external reviewers participating in an audit, use the coverage ledger defined in `task_orders/audit.md`. For other workflows, record reviewer, evidence scope, findings, and coordinator validation status in the handoff. Before sending evidence outside the local/project environment, record the approved data boundary, evidence packet, redaction rule, egress endpoint, auth/session policy, retained artifacts, and whether the reviewer may only observe or may also propose changes.

When reviewer-lane feedback is in scope and `REVIEWER_LANE_FEEDBACK.md` exists, each planned reviewer lane should be accounted for with an explicit structured marker in the normal report or feedback file: `REVIEWER_LANE_USED` when the lane contributed, or `REVIEWER_LANE_SKIPPED` when it was planned but not used. Adopted reviewer findings should emit `REVIEWER_FINDING_ACCEPTED`; rejected reviewer findings should emit `REVIEWER_FINDING_REJECTED`; durable lane-fit observations should emit `LANE_FIT_OBSERVATION`. These markers are project-local evidence for routing and improvement only. They do not prove model quality, do not authorize framework changes, and must not use raw local agent session logs, browser transcripts, screenshots, or private wrapper logs as primary evidence.

At closeout, update reviewer-lane feedback when reviewer lanes were used, planned then skipped, accepted or rejected, or when a commit, pull request, release, or milestone claims external review, but only when `REVIEWER_LANE_FEEDBACK.md` is receipt-declared mutable state; otherwise retain the structured markers in the ordinary report. Preserve the file's exact generated-state origin marker. If the condition applies but the reusable lesson is unclear, ask one concise follow-up before closeout. Do not create the optional file ad hoc, install mandatory VCS hooks, or block commits only because the optional feedback file is absent.

For protocol-backed, daemon-backed, or persistent agent sessions, record the session identity, workspace or cwd scope, capability discovery or agent-card source, protocol and endpoint, typed input/output contract, queueing, cancellation, status or task lifecycle, timeout and retry policy, structured-output, replay/export, and teardown behavior in the handoff or project contract before relying on the session as an orchestration primitive. If a remote worker performs hard policy or compliance checks, prefer deterministic implementation and reproducible verdict evidence over LLM judgment; if the worker is unreachable or returns invalid data, route to the named fallback rather than silently continuing.

5. Report Results

After all steps complete, deliver a summary:

- Steps executed and their outcomes.
- Files modified across all steps.
- Material verification results with their basis or provenance, state, and limitations.
- Open items and follow-up tasks.
- Whether all acceptance criteria were met.

Acceptance Criteria

- Every step in the sequence was executed or the workflow was stopped at a gate failure.
- Each handoff contains the reload bundle and authority rule.
- Each sub-agent followed its applicable Task Order, Practice Guide, or authorized-action envelope and its acceptance criteria or verifier gate.
- Worker claims were validated against primary evidence before state updates.
- TODO.md contains the current handoff and remaining open matters only when state-file maintenance is authorized and relevant; otherwise the final report carries them as candidates.
- The final summary preserves the basis or provenance, state, and limitations of every material verification result.
- The final summary accounts for all steps.

Notes

- Worker agents are separate work lanes, not presumed independent. Give each only the task order, reload bundle, and bounded handoff context when the runtime supports that isolation; record actual context inheritance and shared dependencies when blindness or independence matters, otherwise label the lanes correlated or non-blind.
- Do not silently rewrite a sub-agent's report. The coordinator may integrate approved file changes and must identify coordinator edits; substantive corrections should be returned to the worker or escalated.
- Agent orchestration is orchestration, not delegation. The Agent remains responsible for the workflow and reports to the User.
