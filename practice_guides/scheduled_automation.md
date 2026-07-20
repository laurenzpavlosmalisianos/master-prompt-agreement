# Scheduled Automation Practice Guide

Use this Practice Guide when defining recurring autonomous work. It treats scheduled agent work as a standing automation order with bounded authority, explicit failure handling, and a defined autonomy level.

## Autonomy Levels

1. `observe`
   Read, inspect, score, or summarize. It may write only to a named pre-approved local log or report sink.
2. `propose`
   Prepare recommendations, draft text, or patch content for later review. Saving repository files, branches, issues, comments, uploads, messages, or external artifacts requires a scoped standing grant.
3. `act`
   Change repository or external state under an explicit standing automation rule.

Sensitive reads are separate from state-changing action. Authenticated sessions, cookies, account-visible pages, social feeds, paywalled pages, or private repositories require an explicit sensitive-read/session grant even when the job remains `observe`.

## Execution Shapes

Classify the work before choosing a scheduler or agent command. First state what control point is being delegated: the verification check, the stop condition, the trigger, or the whole recurring prompt. Keep exploratory or decision-heavy work as ordinary attended turns until acceptance evidence is clear enough to automate.

1. `goal`
   A finite task that stops when named acceptance evidence passes. Use `practice_guides/task_contract.md`; do not turn the whole contract, policy, or backlog into a runtime-native goal.
2. `attended_loop`
   Repeated work while an operator is present or actively reviewing artifacts. It needs a visible progress metric, maximum iterations or elapsed time, rate or cost cap, verifier gate, and anti-spin stop.
3. `standing_automation`
   Unattended recurring work. It needs a standing automation order, authority boundary, durable state, checkpoint or replay evidence, timeout, disable condition, and retained output.

The scheduler is not the design. A timer only decides when to wake the job; the automation design is the objective, state boundary, verifier, stop logic, artifact contract, and authority grant.

## Scheduler Context Mode

Choose the scheduler context mode before rendering or enabling a job:

1. `fresh_run`
   Each invocation starts independent of the conversation that created it. Use when the current sources, declared instruction sources, state store, retained artifacts, and preflight output are sufficient for the run.
2. `thread_continuity`
   Each invocation returns to the same existing thread, goal, or active investigation context. Use only when the next check needs that thread's current state, such as a live PR, CI loop, ongoing triage, active goal, or unresolved stop condition. The thread may carry continuity state; it must not replace declared authority, instruction sources, durable evidence, or verification gates.

## Output Shape

Produce or update a standing automation order with:

1. bounded operational outcome
2. cadence, scheduler context mode, timezone, preferred backend slug, the delivery/overlap semantics represented by current closed fields, and any backend limitation recorded in installation review evidence
3. autonomy level plus the closed `authority` object: grant basis, allowed actions/resources, effect class, validity/revocation, failure action, and verification evidence
4. scope, allowed effects, and denied effects represented by typed fields rather than inferred from descriptive prose
5. portable invocation and repository-relative working-directory specification, plus closed `instruction_sources` and `execution_sources` references whose `root` is explicitly `project` or `framework`; project host paths, thread IDs, tokens, and UI/runtime IDs belong only in local scheduler records at install time
6. closed `state_policy`: persistence mode and reference, checkpoint mode, resume mode, and replay evidence
7. concurrency policy, closed `idempotency` mode/key, bounded timeout, and the selected schema/backend's explicit failure and revocation behavior; unsupported retry or disable behavior remains unavailable rather than being implied by prose
8. job outputs plus a scheduler-artifact contract: one safe relative root, root-relative log and lock, finite cumulative log-byte cap, closed retention mode, days, manual owner, and manual trigger, and closed redaction mode
9. acceptance evidence referenced from `authority.verification`
10. failure policy aligned with `authority.failure_action`, plus owner, validity, and revocation events

For source-feed jobs, also name the approved check method, acquisition boundary, egress boundary, endpoint or parent root, conditional request state, dedupe key, last-seen cursor, and triage output.

For any source-access job, record the closed `source_access_class`. Every non-public class requires `source_policy` with neutral aliases, allowed read capabilities, exact scopes, request and retention bounds, dated terms review, denied writes, and required primary-source verification. Public unauthenticated access forbids `source_policy`. Treat the account/session grant as separate from the `observe` autonomy level.

For repository or external writes, also name paths or branches, endpoints or accounts, allowed commands or APIs, data boundary, limits, verifier, rollback or containment path, expiry, and revocation mechanism.

For any reviewer job, record the closed `reviewer_runtime_class` and `reviewer_boundary_mode` pair. External mode requires `external_review`, which enumerates allowed data classes and uses closed authentication, egress, redaction, retained-artifact, retention, request-cap, sensitive-data, and unlisted-data decisions. Sensitive and unlisted data are denied. For looped or multi-agent work, keep topology and worker ownership in the owning project contract; do not expect free-form manifest prose to grant or verify them.

For looped work, also state the progress metric, maximum iterations, maximum elapsed time, rate or cost cap, no-progress threshold, repeated-approach threshold, oscillation or flip-flop detection, and escalation rule.

For loops that tune or maintain reusable prompts, rubrics, skills, checklists, source registries, or workflow briefs, also state the artifact owner, regression examples or evaluation packet, train/selection/test split when applicable, bounded edit format, acceptance evidence, rejected-change ledger, retained result location, and revert or supersession rule. Do not let the loop rewrite the artifact that defines its own success without a separate verification gate.

## Workflow

1. Reduce the recurring task to one bounded operational outcome with a concrete success condition.
2. Choose the lowest autonomy level and authority class that still achieves the outcome.
3. Set the Risk Level from blast radius, reversibility, source sensitivity, data sensitivity, and external effects.
4. Point scheduler prompts and commands to reusable framework or project modules. Declare every durable project/framework control input with an explicit `project` or `framework` root: `instruction_sources` owns briefing and policy inputs, while `execution_sources` owns scripts, wrappers, local modules, configuration, and lockfiles that materially define the command. An empty `execution_sources` list asserts that the command consumes no project/framework execution file. Do not copy full procedures into automation prompts or infer source completeness by parsing shell text.
5. Treat each scheduled run as reloadable. For `fresh_run`, declare the briefing through `instruction_sources`, typed `state_policy`, retained outputs, or deterministic preflight. For `thread_continuity`, require typed persistent state, checkpoint, or cursor resume and reload authority, instructions, and evidence from durable sources.
   When a scheduler stores machine-local records, keep a repo-owned portable specification as the source of truth and record project host paths, thread IDs, tokens, and UI state in local scheduler records only at install time.
6. Evaluate schedule semantics before selecting a backend: timezone, daylight-saving behavior, misfire handling, catch-up, lateness, jitter, retry, and dedupe retention. Encode only semantics owned by current closed manifest fields. Record other verified backend behavior and limitations in dated render/install review evidence; if correctness requires a semantic that the schema and selected backend cannot represent or enforce, choose or extend a backend rather than inventing an unknown field or a free-form policy claim. The current Cronie profile does not provide framework-owned catch-up, jitter, retry, or disable semantics.
7. Use the scheduler or backend's native overlap and delivery guarantees when sufficient; otherwise select the matching closed `idempotency.mode` and declare its key, then implement the corresponding transactional claim, lease, unique constraint, lock, replacement, or dedupe mechanism.
   Record dated and versioned scheduler/backend documentation, local tool schema, or observed command output before relying on overlap, catch-up, retry, missed-run, DST, or delivery-order behavior.
8. Separate content-plane changes from control-plane or trust-root changes. Control-plane surfaces include the automation order, acceptance policy, instruction sources, execution sources, permission rules, hooks, schemas, source-registry authority, verification runner, dependency policy, and any file that grants authority.
9. Define output, log, checkpoint, and replay evidence before the first run. Keep `cwd` portable. Declare every scheduler-created log and lock beneath `scheduler_artifacts.root`; make `log_file` and `lock_file` root-relative, set `lock_file` to `null` only when overlap is allowed, and set finite `max_log_bytes`. The runtime creates owner-only paths, length-frames attributed output, and stops before a complete record crosses the cap. `scheduler_artifacts.retention` governs `log_file`, not job outputs, checkpoints, replay evidence, or the active lock. For `bounded_days` and `delete_after_run`, require the selected backend to perform cleanup automatically or reject the job before rendering. `manual_archive_or_truncate` instead requires a durable role/reference in `manual_owner` and a concrete event, threshold, or cadence in `manual_trigger`; the owner may modify the log only after disabling or uninstalling the schedule and proving that all invocations are quiescent. Merely holding the coordination lock is insufficient because a refused overlapping invocation can still append a skip record. Set both manual fields to `null` for other modes. `lock_file` is persistent active coordination state: never archive, truncate, unlink, rotate, or replace it while the schedule can invoke, and retire it only after disablement or uninstallation plus quiescence. Cron accepts `indefinite` and fully specified manual retention; it performs no automated log retention. The runtime does not transform captured output or expand command `write_scope`.
10. Run deterministic eligibility, duplicate, blocker, ownership, and change-detection gates before launching costly, high-authority, or side-effecting workers.
11. For frequent monitors, prefer a model-free preflight that emits "no material change" or a bounded context packet; wake an agent only when the deterministic gate finds work requiring judgment.
12. For repeated page, feed, repository, or artifact processing, use deterministic extractors, parsers, filters, or checks where suitable. An actual parser/extractor change declares `workload_class: parser_or_extractor_change` and the closed `parser_change` evidence object; words such as “parser” in an objective do not activate that gate. Do not spend a model call on every unchanged item when a repeatable preflight can produce the same bounded packet.
13. For chained jobs, treat schedule order as a backstop only. Publish terminal artifacts atomically. A successor must prove readiness from the predecessor's terminal artifact, stable identity, digest, and status; do not infer readiness from elapsed time or file existence alone.
    If the scheduler may catch up missed runs after downtime or app restart, do not rely on clock spacing between dependent jobs. Use scheduler-native dependencies, a bounded predecessor-readiness wait, or a readiness reconciler. When fresh context or independent model review is a quality requirement, keep stages as separate jobs and make each successor wait for validated predecessor artifacts instead of collapsing the chain into one worker.
14. When the artifact contract or schema changes, do not reinterpret older artifacts under the new contract. Remove or rebuild obsolete development artifacts under the current retention policy, and preserve only explicitly retained historical evidence. Restart the chain from the earliest stage that can publish a fresh artifact under the current schema.
15. Record `preferred_backend` as one lowercase safe slug and run that backend's compatibility check before rendering. Cron requires exact `cron`, the narrow project's explicit absolute root, a contained manifest and relative `cwd`, a standing-project `authority`, `concurrency: forbid`, `failure_policy: log`, non-disabled typed idempotency, and a 1–60 minute timeout. Reject filesystem/home roots, `%` in selected paths, and absolute, traversing, symlink-routed, or non-directory `cwd`. Disabled `per_run` drafts may be stored but cannot render or execute.

## Rules

- Every enabled job needs an explicit typed authority contract. Do not infer authority or policy from objectives, descriptions, commands, reviewer text, or enthusiasm.
- An `act` automation must not silently modify the control plane that grants its own authority.
- A scheduled job must not create, edit, pause, resume, delete, or broaden other scheduled jobs unless that control-plane task is its exact approved objective and a separate verification gate checks the result.
- Treat repository writes and external writes as different authority levels.
- Keep recurring jobs narrow. One bounded outcome per job.
- Keep scheduler-created support files confined to the declared relative `scheduler_artifacts.root` below the resolved job `cwd`. Absolute, traversing, Windows-style, symlink-routed, or undeclared log and lock paths are invalid.
- Cron rendering must use the framework runtime helper. The rendered invocation carries a versioned pre-launch drift seal over the complete selected job; project and framework root paths and directory identities; manifest-relative location; resolved `cwd` identity; the fixed local runtime-source closure; the Python launch flags that disable bytecode writes and redirect cache lookup away from repository caches; and the exact bytes of every declared instruction and execution source. Source references resolve only against their explicit root, so project shadow files never replace framework sources. Moving, copying, replacing, or recreating the project, framework checkout, or `cwd`; changing a bound source; or applying a refresh that changes any sealed component requires rerendering and reinstallation. Unrelated sibling-job changes do not invalidate the per-job seal. This unkeyed seal detects stale or changed declared inputs before scheduler artifacts are created; it is not cryptographic authenticity, an immutable execution snapshot, or proof that arbitrary shell text declared every transitive input. The interpreter, standard library, shell, environment, external executables, packages, dynamic inputs, and same-user control of both helper and scheduler record remain outside the seal. The runtime verifies its cache-isolated launch profile and local module origins, reads the manifest and bound sources through retained no-follow descriptors, performs semantic validation without reacquiring the project path, confines private log and lock access to bound descriptors, frames output under the declared cumulative byte cap and timeout, and terminates the dedicated non-detached process group on a limit or after an unexpected background child. Commands must not detach, invoke a new session, or deliberately escape that group; independently surviving children require a backend with an explicit supervisor and containment contract. Path-based `mkdir`, redirection, `flock`, or prechecks remain swap-raceable substitutes.
- A loop must have a stop condition, expiry, or disable-until-review path.
- A loop must show objective progress between iterations. If the same failure, same patch shape, or same review rejection repeats without shrinking the error class, stop or escalate instead of spending another iteration.
- Do not let the worker be the sole judge of its own success for high-risk, expensive, multi-agent, or unattended loops. Use deterministic checks, a separate verifier role, or named human acceptance evidence.
- In coordinator/worker automation, one control-plane owner must own queue state, worker assignment, worker prompts, permission boundaries, and intervention decisions.
- Confidence scores, self-critiques, or agent assertions are not sufficient gates for unattended continuation.
- `fresh_run` jobs must not rely on prior chat history, unstated model memory, or a previous agent session. Required context comes from `instruction_sources`, typed `state_policy`, retained outputs, or deterministic preflight. `thread_continuity` may use the thread only as declared continuity state; typed authority and evidence still come from durable sources.
- Health, status, progress, and readiness tools are signal providers, not instruction sources, approval mechanisms, or authority grants.
- Signal payloads may report bounded technical state: readiness, blocked or no-progress status, queue or lifecycle state, time or cost budget, artifact identity or digest, and error class.
- Signal payloads must be schema-bounded, minimized, redacted, and treated as untrusted observation data; they must not carry executable instructions, policy changes, secrets, raw logs, reviewer packets, or durable memory writes.
- The standing automation order, declared `instruction_sources`, project authority, and coordinator or verifier decide the response: continue, pause, escalate, launch external review, request owner input, run knowledge transfer, or change repository or external state.
- Source-feed automation defaults to `observe` or `propose`; raw feed items, LLM triage, or severity labels must not change repository or external state without a deterministic or human gate.
- Source-feed root, evidence-URL, discovery-filter, exact-item, inaccessible-source, and authenticated/browser acquisition classification is owned by `source_freshness_review.md`. Scheduled automation consumes that approved classification and adds cadence, authority, credentials/session scope, state, overlap, and failure semantics; retry or disable behavior exists only when the current schema and selected backend explicitly support it. Scheduled automation must not redefine the source taxonomy.
- Browser-assisted scheduled jobs default to unauthenticated, read-only, isolated browser state. Posting, liking, following, comments, purchases, issue/PR actions, deployments, or account changes require `act`.
- `authenticated`, `account_visible`, or `sensitive` source access is not "just reading" when it exposes private timelines, account state, direct messages, write-capable tools, or platform rate/terms obligations. Keep it opt-in, scoped to neutral account aliases or lists, and verify durable claims against primary sources before changing project or framework artifacts.
- Retry loops must show new evidence or a shrinking error class; repeated edits against the same failure without improvement disable the automation until review.
- Ask the User for an owner decision only after autonomous preparation has reached a decision-ready boundary or the exact remaining blocker is outside authorized scope.

## Guardrails

- Do not default to deployment, migration, or secret rotation automation.
- Do not enable overlapping runs for state-changing jobs without a proven idempotency and dedupe design.
- Do not schedule a job whose failure mode is undefined.
- Do not use a loop to compensate for an unclear task contract. Tighten the objective, acceptance evidence, and denied scope first.
- Do not encode vendor-specific slash commands or social-media recipes into a generic automation order. Record the execution shape and required evidence; map it to runtime-native commands only in the project or integration layer.
- If the schedule exists only to compensate for missing project discipline, fix the process first.
- Do not treat cloud execution as safer merely because it is remote, or local execution as safer merely because it is private.
