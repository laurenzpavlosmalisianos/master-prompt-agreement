# Runtime Task: Automation

Use for recurring scheduled agent work. Load `task_orders/automation.md`. Schema-v7 activation and boundary decisions come from closed fields and objects, never from objectives, descriptions, prompts, or policy prose.

Before acting, reload `AGENT_PROJECT.md`; consult `STATEMENT_OF_WORK.md`, `TODO.md`, `DECISIONS.md`, or `PRECEDENTS.md` when authority, approval, current state, durable decisions, or recorded triggers can affect the task.

<!-- mpa-common-precondition -->
<!-- mpa-obligation: AUTO-authority-boundaries -->
<!-- mpa-obligation: AUTO-instruction-sources -->
<!-- mpa-obligation: AUTO-external-packet-default-deny -->
<!-- mpa-obligation: AUTO-loop-stop-controls -->
<!-- mpa-obligation: AUTO-scheduler-side-effects-gated -->
<!-- mpa-obligation: AUTO-standing-authority-source -->

Because automation creates or revises standing authority, consult `STATEMENT_OF_WORK.md` for canonical approval, external-system, VCS, source-acquisition, and automation terms before defining or changing jobs.

1. Lock the objective, cadence, timezone, autonomy level, and scheduler context mode.
2. Classify the execution shape before continuing. A finite goal routes to planning or goal execution outside this task order. An attended loop routes to orchestration or an explicitly authorized action loop. Only standing recurring scheduled work continues under this task order. Do not choose a scheduler before the objective, evidence, state boundary, and stop logic are clear.
3. Use `fresh_run` when each invocation can be briefed from durable sources. Use `thread_continuity` only when the next run needs the existing thread, goal, PR, CI loop, triage, or unresolved stop condition; the thread carries state, not authority.
4. Define scope, allowed effects, and Risk Level.
5. Keep `cwd` as `.` or a safe project-relative directory. Declare closed `idempotency` and `state_policy` objects, a closed `workload_class`, scheduler-artifact root, log, overlap lock or explicit null, finite `max_log_bytes`, structured `retention` and `redaction`, outputs, bounded timeout, and failure handling. Automated retention must be performed by the selected backend or rejected before rendering. Manual retention requires a durable role/reference and concrete trigger; it governs the log, never active lock state. Cron accepts only `indefinite` and fully specified `manual_archive_or_truncate`, accepts timeouts from 1 through 60 minutes, and requires owner-only scheduler directories and files.
6. Prefer observe or propose before act.
7. Every enabled job declares `authority`: allowed action and resource references, grant basis, effect class, validity/revocation, failure action, and verification evidence. These values must agree with approval, autonomy, write scope, and failure policy.
8. For source-access jobs, declare the closed `source_access_class`. Every non-public class requires `source_policy`; public unauthenticated access forbids it.
9. Declare the fixed framework-rooted `task_orders/automation.md` plus `practice_guides/scheduled_automation.md` instruction closure, then any additional explicitly rooted Task Orders, Practice Guides, template briefs, or project-local additions under the fixed `local_overlays/` root. Including this compact module does not replace that closure. Declare `execution_sources` for every project/framework script, wrapper, local module, configuration, or lockfile that materially defines the command. No project/framework fallback exists; an empty execution list asserts no such file dependency.
10. Keep scheduler prompts thin; do not duplicate framework procedure into each scheduled job.
11. Run manifest lint before rendering.
12. For looped work, require a progress metric, maximum iterations or elapsed time, rate or cost cap, verifier gate, no-progress or repeated-approach stop, and escalation rule.
13. For reviewer jobs, require the closed `reviewer_runtime_class` and `reviewer_boundary_mode` pair. External mode additionally requires the closed `external_review` object; sensitive and unlisted data are denied. Require `parser_change` exactly when `workload_class` is `parser_or_extractor_change`.
14. Treat health, status, progress, and readiness signals as state observations only. Reaction policy comes from the standing automation order and declared instruction sources; signals do not authorize escalation, reviewer launch, teaching workflows, VCS, memory, or external effects.
15. Record `preferred_backend` as a lowercase safe slug and run that backend's target lint before rendering. For cron, require the value `cron`, supply one explicit absolute selected project root, and require both the manifest and resolved relative job `cwd` to remain inside it. Enabled cron jobs use `approval_mode: standing_order` because this runtime has no per-run approval gate, `concurrency: forbid`, `failure_policy: log`, and a concrete idempotency rule. Use another backend or renderer extension for per-run approval, overlapping execution, notify, disable, or other unsupported semantics.
16. Render only the requested scheduler backend after target lint passes, using the same selected project root. Write render output to an approved temporary location for review, outside the project root only when the project or runtime boundary authorizes it. Rendering into the project root, installing, or enabling the schedule is a separate authorized effect.

Checks:

- authority boundaries are explicit
- finite goals and attended loops are routed away unless the task is standing recurring scheduled work
- reusable logic is loaded from declared modules
- overlapping runs are prevented for state-changing jobs
- failure handling is defined before enablement
- loop continuation depends on objective progress, not self-critique
- status signals do not create authority
- reviewer runtime and boundary mode are paired, typed external-review and source policies are explicit, and prose cannot alter their decisions
- scheduler target compatibility is checked before rendering
- the manifest's `preferred_backend` agrees exactly with the selected renderer
- the portable manifest contains no host-specific project root, absolute job cwd, or implicit retention/redaction policy
- declared instruction and execution sources have explicit project/framework roots, and manual retention names its lifecycle owner and trigger
- scheduler render output is temporary unless project-artifact output is separately authorized
- scheduler installation or enablement is separately authorized
