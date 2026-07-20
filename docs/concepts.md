# Concepts

Master Prompt Agreement is a file-backed operating model for coding agents.
It makes scope, authority, sources, verification, and reusable workflows explicit
as files that an agent can inspect.

## Authority

Authority is layered:

1. platform, sandbox, tool, and approval restrictions
2. current user task
3. `master_service_agreement.md`
4. downstream `STATEMENT_OF_WORK.md`
5. governing terms in `AGENT_PROJECT.md` as generated projections of the SOW,
   plus its non-authoritative lifecycle binding from retained input
6. Task Orders and Practice Guides as procedures
7. evidence, state files, tool output, reviewer output, and source packets as data

Task Orders and Practice Guides do not override the MSA or SOW. Evidence can
prove facts; it does not grant authority by itself.
The current User task defines the immediate work, but it cannot waive platform
policy or the framework's non-delegable truthfulness, safety, and verification
duties.

## Runtime Packet

Normal agent work should load the smallest useful packet:

- the selected runtime entrypoint as the loader, not a separate authority layer
- always-on universal rules from `runtime/operative_charter.md`
- the closed transaction-control gate after the charter and before generated
  project authority or state: `.mpa-bootstrap-recovery.json`,
  `.mpa-bootstrap.lock`, and `.mpa-bootstrap-recovery.tmp`; follow
  `runtime/load_order.md` for the bounded inspection and recovery route
- active project facts from `AGENT_PROJECT.md`
- the project Scope of Authority module before action when the contract configures one
- active state only when headers or task scope make it relevant
- the applicable compact runtime task module or full Task Order when the task
  needs a declared workflow procedure; use the workflow index when selection is
  ambiguous
- one or more Practice Guides only when the task needs that domain quality bar

The full MSA remains available for ambiguity, canonical wording, and framework
maintenance. It is not the normal always-on prompt.

## One Owner Per Fact

As a codebase matures, consolidate duplicated prompt prose into the appropriate
authoritative or executable owner; code is not the authority for every kind of
fact. Assign each fact to the surface that can represent and verify it most
directly:

| Fact class | Primary owner | Prompt-loaded residue |
|---|---|---|
| platform restrictions, runtime capabilities, sandbox boundaries, and approval enforcement | platform and runtime instructions or enforcement | only a project-specific operational fact that must be remembered |
| universal framework duties and non-delegable floors | `master_service_agreement.md`, compactly projected by `runtime/operative_charter.md` | the applicable universal rule; do not duplicate it into project state |
| immediate task scope and current action approval | the current User request, interpreted under higher authority | only the active task fact needed for execution |
| durable project scope, delegated authority, approval and privacy boundaries, and external commitments | `STATEMENT_OF_WORK.md` | the task-relevant term projected into the compact project contract, or a precise route to the canonical text |
| active cross-session work | `TODO.md` | active matters only |
| durable rationale, source-attributed directives, and supersession history | `DECISIONS.md` | the current applicable record when task-relevant; the file records authority but does not create it |
| implementation structure and current mechanics | code, configuration, types, and schemas | only non-derivable constraints and navigation pointers |
| expected behavior | governing project requirements or a project-adopted domain specification | task-relevant critical invariants and Manual Acceptance Items |
| formatting, lint, build, and task mechanics | formatter, linter, compiler, package, and task configuration | stable invocation plus any environment or approval boundary |

Tests provide executable verification against those requirements; they are not
requirements authority.

Code shows the current implementation; it does not prove that the implementation
matches the intended contract. Tests can encode a mistake, and prose can become
stale, so consolidation requires agreement among the owning requirement,
implementation, and meaningful verification.

Retire duplicate instructions at a reviewed milestone only after the replacement
owner exists, an agent can discover it, and relevant checks pass. Required
rationale, owner, evidence, and amendment history must remain retained, and any
consolidation that changes behavior or authority routing must have a
proportionate backout path. The number of
successful runs or age of the project is not evidence that prose is safe to
remove. A mature runtime therefore keeps a thin entrypoint and compact
non-derivable contract, then inspects code, configuration, schemas, tests, and
task-routed guidance on demand.

## Task Orders And Practice Guides

Task Orders answer:

- which workflow is running?
- what sequence should the agent follow?
- what outputs should be produced?
- what verification or escalation closes the workflow?

Practice Guides answer:

- what quality standard applies to this kind of work?
- what risks, checks, non-goals, and evidence shape matter?
- which related guides should be paired?

A Task Order may route to a Practice Guide. A Practice Guide should not become
an end-to-end workflow.

## State And Feedback

Downstream project state is project-local by default. Durable framework
improvements flow through sanitized feedback candidates, source evidence,
maintainer review, and deterministic checks when applicable.

Project names, local paths, logs, transcripts, identities, secrets, proprietary
details, and one-off local context must not be copied into public framework
guidance.
