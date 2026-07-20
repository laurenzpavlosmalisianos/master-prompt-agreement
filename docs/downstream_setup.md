# Downstream Setup

Use this chapter for orientation. The executable setup procedure remains
`GETTING_STARTED.md` and `task_orders/init.md`.

## Setup Shape

1. Give the agent read access to this framework checkout and write access to the
   target project.
2. The agent reads `runtime/operative_charter.md` and `task_orders/init.md`.
3. The agent inspects the target project before asking setup questions.
4. The agent writes a temporary answers JSON outside both repositories.
5. Through the intended execution boundary, the agent runs
   `<candidate-python> -B <framework-checkout-on-diagnostic-host>/scripts/check_prereqs.py`;
   only its exact executing interpreter is qualified.
6. The agent resolves the checkout inside that retained runner and runs
   `<runner> <framework-checkout-as-visible-to-runner>/scripts/project_bootstrap.py --dry-run`.
7. After reviewing the complete rendered plan, the agent reruns the same command
   with `--approve-write-plan-sha256 <write_plan_sha256>`. The plan digest is
   required even when the informational warning list is empty and changes with
   the target, inputs/profile, runtime/wrappers, framework identity, warnings,
   output names, or rendered bytes.
8. The non-dry bootstrap transaction runs one strict union of every profile in
   the generated receipt and rolls back the installed outputs if that union
   reports a warning or error.
9. The agent and User perform the required post-write human or manual review,
   then remove the temporary raw answers file through the approved cleanup path.

Core conformance includes required-surface preflight,
retained-input/current-receipt validation, project-contract synchronization,
and project-state lint.
Optional active profiles extend it with checks for their generated surfaces.
The approved non-dry bootstrap runs one strict union of the receipt-listed
active profiles inside the write transaction; any conformance warning or error
fails the transaction and triggers rollback. The digest approval is valid only
for the unchanged dry-run warning sequence and does not waive this gate. An incomplete rollback leaves at least one closed-set
transaction control rather than a successful setup result.

Post-write human or manual review remains a distinct acceptance obligation;
deterministic conformance does not replace it. Do not immediately rerun the same
conformance profiles; rerun conformance only for recovery verification, focused
diagnosis, later drift, or independently requested evidence. Run child
validators separately only for focused diagnosis, not as duplicate conformance
evidence.

`examples/project_bootstrap_answers.example.json` is a minimal starting
example. `examples/project_bootstrap_answers.schema.json` is the closed
machine-readable answer contract; inspect only definitions for the fields and
optional modules in use, then review the actual rendered dry-run outputs. The
full schema and output templates are compiler inputs, not mandatory prompt
imports. Use targeted schema lookup and `project_bootstrap.py --help` instead
of inferring supported fields from the example.

Bootstrap creates a first current-format instance only when no
framework-generated surfaces exist and no selected managed output path collides. Preserve
an ordinary same-name file and follow the non-colliding-layout or
project-specific integration route in `GETTING_STARTED.md`; absence of generated
identity alone does not authorize overwrite. Complete current-format instances use
[`UPDATING.md`](../UPDATING.md) and
[`task_orders/framework_refresh.md`](../task_orders/framework_refresh.md).
Refresh keeps retained mutable state byte-for-byte unchanged and regenerates
receipt-owned immutable outputs. A reviewed candidate may disable an optional
surface only through the plan-bound `RETIRE-IMMUTABLE-####` or
`RETIRE-MUTABLE-####` action matching its receipt partition, a path-specific
warning, and the applicable exact-preimage controls. Refresh separates framework changes from project-contract revision and
binds apply authority to one exact plan digest. Partial, malformed,
inconsistent, older, or unrecognized formats
fail closed for a separately reviewed manual project update; a clearly newer
schema requires a supporting framework checkout. Bootstrap rerender and state
reset are not update paths.
If any of `.mpa-bootstrap-recovery.json`, `.mpa-bootstrap.lock`, or
`.mpa-bootstrap-recovery.tmp` exists at the project root, ordinary work must
stop before loading generated project authority and use bounded inspection,
followed by exact-ID recovery only when inspection identifies a permitted
action.

An optional reusable bootstrap profile may fill absent setup defaults when the
User supplies or approves it. It is not project authority: project answers
replace profile fields atomically, and environment capabilities, project
identity, scope, stack, architecture, commands, deliverables, and paths remain
project-specific.

The answers must set `framework_verification_runner` to the exact tested
interpreter reported by `scripts/check_prereqs.py`, or to the exact environment,
container, or `uv` invocation prefix only when it actually ran that successful
diagnostic. A reusable profile must
not supply this capability. The SOW owns the runner requirement; the generated
runtime contract reuses it verbatim and must not silently fall back to another
environment.

## Generated Downstream Files

Typical generated files are:

- `STATEMENT_OF_WORK.md`
- `AGENT_PROJECT.md`
- a runtime entrypoint such as `AGENTS.md` or `CLAUDE.md`
- `TODO.md`
- `DECISIONS.md`
- `PROJECT_INPUT.json`, the retained fully materialized regeneration source
- project-root `PROJECT_INSTANCE.json`, the single current-state
  generated-instance receipt

Retained input materializes project facts such as paths and commands. Keep
secrets out, minimize unnecessary sensitive material while retaining required
project facts, and review the file before tracking, sharing, or publishing the
downstream repository. Public
framework export ignores do not sanitize downstream repositories. The current
instance receipt carries the retained contract effective date and its
`contract_root` field locates nested authority and input; it is not a
refresh-history log.

Optional files such as `SOURCE_PACKS.md`, `SOURCE_UPDATE.md`,
`SOURCE_MONITOR_RESEARCHER.md`, `FRAMEWORK_FEEDBACK.md`,
`REVIEWER_LANE_FEEDBACK.md`, `PRECEDENTS.md`, `SECURITY_VERIFICATION.md`, and
`AUTOMATION_ORDERS.json` are selected during initialization or an approved
candidate-input refresh only when the project needs that surface. Procedures
may edit a receipt-declared mutable surface while preserving its origin marker.
`SOURCE_MONITOR_RESEARCHER.md` is instead generated immutable procedure from
retained configuration and refreshes with the framework; project additions use
the declared source/state/overlay owners. Procedures do not create, copy,
rename, or delete optional generated state ad hoc.
Applicable selected optional surfaces also activate receipt-listed conformance
profiles. Do not hand-prune generated files; remove an optional surface through
refresh so retained input, the generated managed-file set, any applicable
active-profile declaration, and the receipt update together. Its plan must
expose the exact partition-matched `RETIRE-IMMUTABLE-####` or
`RETIRE-MUTABLE-####` action, path-specific warning, and applicable exact-preimage
controls.

## Stable Framework Reference

If generated downstream files may be committed, shared, or published, use a
stable framework reference with `--framework-ref`. Avoid committing personal
absolute paths into shared project entrypoints.

Select `--framework-revision-policy live` or `pinned` deliberately. A pinned
reference stays operator-fixed until a separate explicit revision-selection
action. A live reference can expose changed operative-charter bytes before
generated project files refresh. Neither policy fetches, installs, or chooses a
newer framework checkout. See [`UPDATING.md`](../UPDATING.md) for lifecycle
details.

## Native Runtime Wrappers

Runtime-native wrappers are launchers, not workflow owners. The setup wrapper
routes to `GETTING_STARTED.md` and `task_orders/init.md`. The refresh wrapper
routes to [`UPDATING.md`](../UPDATING.md) and
[`task_orders/framework_refresh.md`](../task_orders/framework_refresh.md), never
to initialization. Neither wrapper duplicates its canonical procedure.
