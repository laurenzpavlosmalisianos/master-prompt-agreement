# Task Orders (Workflow Procedures)

Task Orders are reusable workflow procedures for defined operations. Some are one-time per target project, such as setup; others recur during maintenance. If the applicable procedure is unclear, start here, choose the matching workflow, and then load only that Task Order.

The machine-readable twin of this file is `runtime/workflow_catalog.json`.

## Task Orders vs Practice Guides

Task Orders answer: which workflow is running, in what order, with what outputs?

Practice Guides answer: what quality standard applies to this kind of work?

Start with one Task Order when the workflow is unknown. Add Practice Guides only
when the task surface needs that specialty. Guides supplement a Task Order; they
do not replace it or broaden authority.

## Task Orders vs Runtime Task Modules

Task Orders are the full procedures.

Runtime task modules in `runtime/task_modules/` are compact operative extracts
for only the most frequently used Task Orders. They are prompt-load views of
known workflows, not executable code modules.

Use a Task Order when you need to choose, interpret, or justify the workflow.

Use a runtime task module when the workflow is already known and the lean operative form is enough. A workflow is known when selection evidence identifies exactly one catalog workflow: task-order metadata, command argument, bootstrap field, issue or ticket label, project contract entry, named workflow sequence, or a clear and exclusive match from the current User request. Natural-language intent is selection evidence, not authority, and cannot bypass full-order gates.

Before using any runtime task module, reload `AGENT_PROJECT.md`. Consult `STATEMENT_OF_WORK.md`, `TODO.md`, `DECISIONS.md`, or `PRECEDENTS.md` when authority, approval, current state, durable decisions, or recorded triggers can affect the task. Use the full Task Order if those files are missing, ambiguous, or insufficient for the requested work.

Use the full Task Order instead of only the runtime module when no workflow matches, multiple workflows plausibly match, the intent is ambiguous, the module's `use_full_when` conditions in `runtime/workflow_catalog.json` match the task, the task touches a critical surface, has unusual effect mode or approval boundaries, uses external reviewers, includes remediation or state-file edits, asks a living-source question, depends on an unrepresented outcome branch, or requires explaining why the workflow was chosen.

Load both only when the runtime module, catalog `use_full_when`, or task conditions require canonical Task Order detail for the case.

Not every Task Order needs a runtime task module.

## Quick Selection

- `init.md` when a project with no framework-generated surface and no selected
  managed-output collision needs its first current-format framework instance
  and receipt-listed initial acceptance.
- `framework_refresh.md` when an existing generated instance must be inspected
  or classified; when a closed transaction-control state needs inspection-gated
  exact-ID recovery; when a verified complete current-format identity pair with
  an intact recorded preimage needs a framework refresh, contract revision, or
  runtime transition; or when an approved
  plan/bundle and matching live postimage support post-success restore.
- `compliance.md` when an established project needs an independent drift audit,
  such as after a milestone or dormant interval.
- `ideate.md` when the problem is still open and multiple approaches must be explored.
- `evaluate.md` when an external idea, design, or pattern must be judged against project standards.
- `framework_feedback_intake.md` when downstream project feedback or reviewer-lane observations should be sanitized, abstracted, and decided before any framework change.
- `framework_semantic_audit.md` when maintained framework surfaces need semantic quality, ownership, and public-boundary review.
- `framework_improvement.md` when an accepted framework candidate needs a
  native-capability admission check, proportional evaluation, authorized
  implementation, non-degradation verification, and a ready-for-act,
  retain/revise/revert, needs-evidence, or no-action disposition.
- `knowledge_transfer.md` when the user wants to learn, understand a session/change, or verify their own understanding.
- `plan.md` when a downstream or project-local approach is chosen and execution
  needs ordered slices. A shared or reusable framework candidate uses
  `framework_semantic_audit.md` and `framework_improvement.md` instead.
- `source_update.md` when current authoritative or project-approved external
  sources may change the correct implementation and the task needs an observe
  report, proposal, or approved act-mode update.
- `backout.md` when a change, update, migration, deployment, or generated patch
  must be safely unwound and no active framework-refresh bundle route owns it.
- `incident_response.md` when suspected compromise, secret exposure, destructive regression, corrupted state, or data loss requires evidence-preserving response.
- `review.md` when a change or narrow evidence bundle needs adversarial review.
- `audit.md` when a subsystem or project needs broader systematic verification.
- `pull_request.md` when an external PR should be assessed as an untrusted proposal before any authorized adoption, response, or reimplementation.
- `automation.md` when recurring scheduled work needs a standing automation order.
- `orchestrate.md` when multiple Task Orders must be chained through fresh-agent handoffs.
- `independent_assessment.md` when independent advice is needed but there is not yet a dispute.
- `arbitrate.md` when there is an actual unresolved technical dispute.
- `commit.md` when approved changes should be committed with cross-session continuity.
- `insights.md` when the User requests a retrospective, the project contract
  names a retrospective checkpoint, or material recurring evidence requires a
  concrete framework decision. Ordinary completion alone is not a trigger.

## Catalog

| Task Order | Use When | Common Next Step | Runtime Module |
|---|---|---|---|
| `init` | Create and accept the first current-format framework instance when no framework-generated surfaces exist and no selected managed-output collision exists. | normal work; later independent `compliance` audit | none |
| `framework_refresh` | Inspect or classify an existing generated instance; use a verified complete current-format identity pair with an intact recorded preimage for refresh planning or revision, exact-current for post-apply acceptance, closed transaction-control evidence for exact-ID recovery, and an approved plan/bundle plus matching live postimage for post-success restore. | normal work; later independent `compliance` audit | none |
| `compliance` | Independently audit whether an established framework setup, runtime split, and state remain sound. | fix drift or continue normal work | none |
| `ideate` | The problem is still open and multiple plausible solution paths must be explored. | ownership classification, then separately authorized `plan` for downstream/project-local work or `framework_semantic_audit` for a shared/reusable framework-product candidate | `ideate` |
| `evaluate` | An external idea or design must be judged against project constraints. | Adopt/Adapt routes by ownership: authorized `plan` for downstream/project-local work, or `framework_semantic_audit` for shared/reusable framework-product work; Reject is terminal; Needs evidence pauses for evidence | none |
| `framework_feedback_intake` | Downstream project feedback, reviewer-lane observations, or repeated agent failures must be sanitized and decided before any framework change. | `framework_semantic_audit` for transitional Promote or Adapt | none |
| `framework_semantic_audit` | Maintained framework surfaces need report-only semantic quality, ownership, and public-boundary review before publication or reuse. | `framework_improvement` for Approve or Approve-with-edits; Reject stops; Needs-evidence pauses | none |
| `framework_improvement` | An accepted bounded framework candidate needs a proportional engineering or claim-grade evaluation and explicit disposition. | authorization handoff for Ready-for-act; after act-mode verification, report-only `review` -> risk-matched report-only `audit` when warranted -> disposition; separately authorized `commit` only for Retain; `backout` for Revert | none |
| `knowledge_transfer` | The user wants evidence-backed teaching, onboarding, or comprehension checks for a session, change, subsystem, or decision. | continue normal work | none |
| `plan` | A downstream or project-local direction is chosen and execution needs dependency-ordered slices. | authorized implementation, `review`, `audit`, or `commit`; shared/reusable framework candidates route to `framework_semantic_audit` instead | `plan` |
| `source_update` | Current authoritative or project-approved external sources should be checked and translated into an observe report, proposal, or approved downstream/project-local act-mode update. | stop after `observe` or `propose`; shared/reusable framework-product candidates use bounded `propose` -> `framework_semantic_audit` -> `framework_improvement`; after downstream/project-local `act`, use `review`, `audit`, or `commit` as applicable | none |
| `backout` | A change, update, migration, deployment, or generated patch must be safely unwound. | approved restoration, then `review`, `audit`, and a separately authorized `commit` when retention is justified | none |
| `incident_response` | Suspected compromise, secret exposure, destructive regression, corrupted state, or data loss requires response. | preserve evidence, perform only authorized response actions, then close or escalate | none; always load full order |
| `review` | A change or narrow evidence slice needs adversarial review. | active framework-improvement candidate first: report-only `revise` handoff; otherwise shared/reusable framework-product finding: report-only `framework_semantic_audit` -> `framework_improvement`; ordinary downstream/project-local work: `audit` or authorized remediation | `review` |
| `audit` | A subsystem or project needs broader systematic verification. | active framework-improvement candidate first: report-only `revise` handoff; otherwise shared/reusable framework-product finding: report-only `framework_semantic_audit` -> `framework_improvement`; ordinary downstream/project-local work: authorized remediation or `commit` | `audit` |
| `pull_request` | An external PR should be treated as an untrusted proposal and assessed before any authorized adoption, response, or reimplementation. | authorized downstream/project-local planning, `framework_semantic_audit` for a shared/reusable framework-product candidate, an authorized response, or decline | none |
| `automation` | Recurring scheduled work needs an explicit standing automation rule. | backend render or `compliance` | `automation` |
| `orchestrate` | Multiple Task Orders must be chained through fresh-agent handoffs. | follow the defined sequence | none |
| `independent_assessment` | Technical uncertainty exists without disagreement. | after coordinator validation, ownership classification routes authorized downstream/project-local work to `plan` or a shared/reusable framework candidate to `framework_semantic_audit`; `arbitrate` only if a dispute emerges | none |
| `arbitrate` | A technical disagreement needs formal independent review or a panel recommendation. | record the branch-specific outcome and authorized follow-up work | `arbitrate` |
| `commit` | Approved local changes should be committed for cross-session continuity. | continue normal work | none |
| `insights` | A requested or contract-triggered retrospective, or material recurring evidence, requires a concrete durable-improvement decision. | route an accepted candidate through feedback/source intake, semantic audit, and framework improvement | none |

## Common Sequences

- New project setup and immediate acceptance: `init`
- Existing generated-instance inspection, current-format refresh, and post-apply exact-current acceptance: `framework_refresh`
- Later independent framework drift audit: `compliance`
- Exploratory mandate: `ideate` -> ownership classification -> separately
  authorized `plan` for downstream/project-local work or
  `framework_semantic_audit` for a shared/reusable framework-product candidate
- External idea review: `evaluate`; Adopt/Adapt routes by ownership to separately
  authorized `plan` for downstream/project-local work or report-only
  `framework_semantic_audit` for shared/reusable framework-product work; Reject
  stops; Needs evidence pauses
- Framework feedback review: `framework_feedback_intake` ->
  `framework_semantic_audit` for transitional Promote or Adapt -> `framework_improvement`
  only for Approve or Approve-with-edits
- Accepted source, audit, or verification candidate: `framework_semantic_audit`
  -> `framework_improvement` only for Approve or Approve-with-edits -> act-mode
  verification -> report-only `review` -> risk-matched report-only `audit` when
  warranted -> disposition -> separately authorized `commit` only for Retain
- Shared or reusable framework-product finding from ordinary `review` or
  `audit`: bounded report-only handoff -> `framework_semantic_audit` ->
  `framework_improvement` only for Approve or Approve-with-edits. When review or
  audit was invoked by active framework improvement, its report-only `revise`
  handoff takes precedence and stays inside that active workflow.
- Knowledge transfer: `knowledge_transfer`
- Source-sensitive project update: `source_update` owns `observe`, `propose`, or
  an authorized downstream/project-local `act` effect; a shared or reusable
  framework-product candidate stops at bounded `propose` and routes through
  `framework_semantic_audit` -> `framework_improvement`; after a permitted
  downstream/project-local `act`, route to `review` -> `audit` -> `commit`
- Backout and verify: `backout` owns the approved restoration; then route to
  `review` -> `audit` -> separately authorized `commit`
- Incident response: `incident_response` -> evidence preservation -> advisory or exactly authorized response -> recovery or owner-accepted residual-risk closeout
- Approved downstream/project-local implementation hardening: `plan` ->
  implementation -> `review` -> `audit` -> `commit`; shared/reusable framework
  candidates use the semantic-audit and framework-improvement route
- External contribution handling: read-only `pull_request` assessment ->
  separately authorized response action; adoption routes by ownership to
  authorized `plan` for downstream/project-local work or report-only
  `framework_semantic_audit` for shared/reusable framework-product work
- Technical uncertainty without disagreement: `independent_assessment` ->
  coordinator validation -> ownership classification -> authorized `plan` for
  downstream/project-local work or `framework_semantic_audit` for a
  shared/reusable framework candidate
- Formal dispute: `arbitrate` -> branch-specific outcome; update `DECISIONS.md` only for ratified decisions or direct User/SOW-owner decisions. A separately authorized ratification commit is `decision_records_only`; classify implementation separately and route active framework-improvement corrections back through that lifecycle, other shared framework work through `framework_semantic_audit`, and downstream/project-local work through separately authorized project implementation or an exact verified-effect commit.
- Decision-triggered retrospective: `insights` -> sanitized candidate intake and
  proportional framework improvement only when justified
- Recurring scheduled work: `automation`
- Recurring multi-step orchestration: `orchestrate`

## Selection Rules

- If the task is about choosing a solution, use `ideate`, not `plan`.
- If a project has a complete current-format framework instance, use
  `framework_refresh`, not `init` or bootstrap rerender. If its framework
  surfaces are partial, malformed, inconsistent, older, or unrecognized, fail
  closed for reviewed manual project update; a clearly newer schema requires a
  framework checkout that supports it.
- If the task is about judging someone else's idea, use `evaluate`, not `ideate`.
- If the user asks to learn, understand, be onboarded, or check their own understanding, use `knowledge_transfer`.
- If a downstream or project-local direction is already chosen, use `plan`, not
  `ideate`. A direct request for a shared or reusable framework-product change
  still routes through `framework_semantic_audit` and, only if accepted,
  `framework_improvement`; chosen direction or execution authority does not
  bypass that ownership route.
- If current authoritative or project-approved external sources may change the
  correct implementation, use `source_update` rather than ordinary `plan`.
  Its direct `act` path is downstream/project-local only; shared or reusable
  framework-product candidates stop at bounded `propose` and use semantic audit
  followed by framework improvement.
- If the task is to restore a successfully applied framework refresh from its
  still-valid plan-bound exact-preimage bundle, stay in `framework_refresh`.
  Otherwise, use `backout` rather than ordinary `plan` to unwind an applied
  change.
- If compromise, secret exposure, destructive regression, corrupted state, or data loss is suspected, use the full `incident_response` order; urgency does not turn an ordinary review or guide into response authority.
- If the evidence target is narrow, use `review`; if the obligation is broad and systematic, use `audit`.
- If uncertainty exists without disagreement, use `independent_assessment`; if positions are in conflict, use `arbitrate`.
- If the work recurs on a schedule, use `automation`. Scheduled chained workflows use `automation` with declared instruction sources or a named workflow that points to `orchestrate`; one-off chained fresh-agent sequences use `orchestrate`.
