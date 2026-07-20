# Command And Script Reference

This is the complete, categorized reference for every public command and
import-only support module in `scripts/`; framework validation checks that its
file inventory stays complete. These tools provide deterministic support for
setup, routing, verification, source handling, automation, and framework
publication. They do not grant authority or replace the governing markdown
files. Run an argument-parsing command with `--help` for its exact current
flags, choices, argument requirements, and safety descriptions before using it;
`check_prereqs.py` instead emits its JSON diagnostic directly. Network access,
external writes, scheduler changes, and other state-changing operations still
require the applicable project authority.
The maintained script contract targets Python 3.14 or newer;
`check_prereqs.py` sets `runner_usable` to `false` when the interpreter or
platform is unsupported. Its `runner` is the resolved executable of the
interpreter that actually produced the report, never a merely discovered
`uv`, `python3`, or `py` spelling; its commands are diagnostic only when
`runner_usable` is false. An outer container or `uv` prefix is retained only
when that exact boundary invoked the successful diagnostic. The selected
Python/platform must also expose
descriptor-relative, no-follow file access, POSIX advisory locking, and the
other reported transaction primitives so authority-bearing inputs can be
opened and changed safely. Native Windows lifecycle transactions are not
currently supported; a `py -3 -B` candidate is usable only when a POSIX-capable
environment produces a no-error report with `runner_usable: true`.

## Downstream Setup And Project Validation

| Command | Role |
|---|---|
| [`check_prereqs.py`](check_prereqs.py) | report the exact tested stdlib-only Python interpreter, its explicit usability flag, required platform capabilities, unqualified candidate launchers, and missing optional tools before setup |
| [`project_contract_model.py`](project_contract_model.py) | own the closed project-contract answer/projection model and generate the JSON Schema plus human-readable SOW/runtime blueprints |
| [`project_bootstrap.py`](project_bootstrap.py) | create a first current-format project instance only where no framework-generated surface exists and no selected managed output collides, from confirmed temporary answers, including retained `PROJECT_INPUT.json` and the single project-root `PROJECT_INSTANCE.json` |
| [`project_refresh.py`](project_refresh.py) | inspect and classify an existing generated instance; plan and apply a framework refresh or candidate revision only from a verified complete current-format identity pair with an intact recorded preimage; require exact-current acceptance after apply; create, verify, recover, and restore a plan-bound exact-preimage bundle; or recover an interrupted project transaction by exact identity |
| [`project_contract_sync.py`](project_contract_sync.py) | check SOW/runtime-contract projection drift and referenced project files |
| [`project_instance_lint.py`](project_instance_lint.py) | validate current downstream or framework-authoring retained input, root-scoped instance receipt, bounded roots, mutable-state origin, generation-source provenance, and output digests against the explicitly selected framework checkout |
| [`project_state_lint.py`](project_state_lint.py) | validate project state headers, durable decision/directive records, indexes, and active-record hygiene |
| [`lint_reviewer_lane_feedback.py`](lint_reviewer_lane_feedback.py) | validate reviewer-lane marker structure, references, selected leak patterns, and anti-ranking rules |
| [`conformance_check.py`](conformance_check.py) | run a declared framework or downstream conformance profile, using validators from the invoking framework checkout while treating `--root` as the selected data tree |

Use the `core-project` conformance profile as the routine downstream aggregate
gate. It already invokes retained-input/current-instance validation,
project-contract synchronization, and project-state lint; run child validators
separately only for focused diagnosis.

The import-only [`bootstrap_transaction.py`](bootstrap_transaction.py) module
owns descriptor-relative locking, staging, installation, rollback, durable
recovery state, and verified cleanup for bootstrap and refresh. It is not a
standalone command, history log, or general filesystem transaction helper.
The import-only [`project_state_identity.py`](project_state_identity.py) module
owns the closed Markdown and JSON origin markers used to distinguish generated
mutable state from ordinary same-name project files. Bootstrap discovery and
current-instance validation consume that one owner; the JSON check is bounded,
duplicate-key rejecting, and independent of object-member order.

When the declarative project-contract model changes, regenerate its checked-in
schema and Markdown blueprints with
`uv run python -B scripts/project_contract_model.py --write`. Verification and
CI should use `uv run python -B scripts/project_contract_model.py --check`;
editing a generated asset directly is a stale-asset error.

The import-only [`generated_sow_text.py`](generated_sow_text.py) module owns the
neutral lexical grammar shared by generated-SOW schema, bootstrap,
synchronization, and direct automation-manifest validation.

The shared import-only [`bounded_subprocess.py`](bounded_subprocess.py) module
enforces finite runtime and aggregate stdout/stderr limits, TERM/KILLs the
dedicated process group, and requires leader reap. Its Linux contract requires
one task, the default `SIGCHLD` disposition, no pre-existing direct child,
readable process identity state, and pidfd support. It restores the caller's
prior child-subreaper state only after proving that the leader and every newly
adopted descendant have been reaped. Other POSIX systems provide only
process-group cleanup: commands there must be trusted not to detach, create a
new session, close both captured streams while continuing, or leave background
descendants.

The import-only [`resource_cleanup.py`](resource_cleanup.py) module owns the
attempt-all, failure-preserving aggregation of named zero-argument cleanup
actions. Callers retain resource ownership and adapt descriptors or closable
objects into those actions; an active primary failure is preserved while
cleanup failures are attached as notes.

In full bootstrap mode, unresolved required facts are validation errors: project
purpose and recitals, architecture, in-scope and out-of-scope boundaries, all
seven command values, deliverable description/test/pass-criteria triples, and
stack or runtime standards must be concrete. `--approve-write-plan-sha256`
cannot waive those errors; it only authorizes one complete rendered plan after
the dry run has passed semantic validation.

Normal downstream setup requires an existing governed project root and uses
that same directory as the contract root by default. An explicitly selected
nested contract root keeps authority, retained input, and state below that
directory, while the single `PROJECT_INSTANCE.json` receipt always remains at
the exact project root. Bootstrap never creates the governed project root.
`project_bootstrap.py --project-kind
framework-authoring` is a maintainer mode for this framework checkout: it
requires an explicit nested, non-public contract root and preserves the neutral
root entrypoint. `--setup-profile`
supplies field-atomic reusable defaults; it does not grant authority or replace
concrete project answers. Bootstrap creates a first current-format instance only
when no framework-generated surface exists and no selected managed output path
collides. Existing
current-format instances, contract revisions, and runtime transitions route
through `project_refresh.py` and `task_orders/framework_refresh.md`. Partial,
malformed, inconsistent, older, or unrecognized formats fail closed for
separately reviewed manual project update; a clearly newer schema requires a
supporting framework checkout. Only a verified complete current-format
retained-input/receipt pair with an intact recorded preimage enters refresh planning;
bootstrap and non-current format classification are not update paths.
Every bootstrap-rendered mutable or optional state surface carries one closed
framework origin marker. Current-instance validation requires it; create-only
bootstrap scans the bounded tree for that exact marker at the closed
state-basename set, including outside the requested contract root. A safely read,
singly linked regular same-name file within the byte bound and without the
marker is not reserved; type, hard-link, size, race, read, or marker-identity
inspection failures make discovery fail closed. Missing or malformed markers on
receipt-listed current state invalidate the preimage and require reviewed manual
correction.
Use each command's `--help` output for exact current arguments and safety checks.

### Bootstrap Flag Map

`project_bootstrap.py --help` is the executable source of truth. These groups
make the safety-relevant choices easier to locate:

| Flags | Meaning |
|---|---|
| `--dry-run`, `--answers`, `--project-root`, `--runtime` | inspect the confirmed downstream render plan before writing |
| `--setup-profile` | fill absent reusable defaults without replacing project authority |
| `--framework-ref` | write the stable framework reference used by the runtime entrypoint and verification commands |
| `--framework-revision-policy live|pinned` | record the deliberately selected operating policy; neither value fetches or selects a framework revision |
| `--runtime-wrapper <id>` | select a registered runtime-native wrapper; repeat for the complete initial wrapper set |
| `--approve-write-plan-sha256 <digest>` | required exactly once for every write; approve the domain-separated digest of the reviewed target, inputs/profile, runtime/wrappers, framework identity, ordered warnings, and rendered outputs; never waive semantic errors or conformance warnings |
| `--contract-root`, `--create-contract-root` | explicitly select and approve creation of a nested authority/input/state directory; the receipt remains project-root scoped |
| `--project-kind framework-authoring` | maintainer-only nested authoring instance; no downstream runtime entrypoint is written |

The neutral reusable-profile shape is
[`examples/project_bootstrap_profile.example.json`](../examples/project_bootstrap_profile.example.json).
The closed answer contract is
[`examples/project_bootstrap_answers.schema.json`](../examples/project_bootstrap_answers.schema.json);
[`examples/project_bootstrap_answers.example.json`](../examples/project_bootstrap_answers.example.json)
is a minimal starting example, not a complete field catalog.
Treat the full schema as compiler input rather than a mandatory prompt import:
inspect only definitions for the concrete fields and optional modules in use,
then review the actual rendered dry-run outputs semantically.
Project identity, scope, stack, architecture, commands, deliverables, and paths
remain in the answers file.
The concrete answers must also record either the exact tested interpreter
reported by `check_prereqs.py` or the exact container/`uv` invocation prefix
that actually ran that successful diagnostic; a reusable profile cannot supply
that environment capability.

### Refresh Command Map

`project_refresh.py <command> --help` is the exact interface source of truth.
This table is command navigation, not a second lifecycle procedure;
`task_orders/framework_refresh.md` owns workflow order and branches.

| Command | Meaning |
|---|---|
| `candidate --answers <file> --project-root <root> ...` | render a validated canonical candidate input on stdout from complete revised answers; the output remains temporary data |
| `candidate ... [--runtime-wrapper <id> ... | --clear-runtime-wrappers]` | preserve the verified wrapper set only when the runtime family is unchanged; a runtime-family change must explicitly replace or clear the complete set, and any changed runtime-plus-output mapping requires `REVISE-RUNTIME-WRAPPERS` at apply |
| `inspect --project-root <root> [--contract-root <rel>]` | report one exact no-write lifecycle status: `current`, `distribution-only-drift`, `refresh-available`, `transaction-active`, `recovery-required`, `manual-update-required`, `newer-framework-required`, `runtime-revision-required`, or `invalid`; non-current results carry actionable diagnostics |
| `inspect ... --check` | exit successfully only when the selected checkout already matches the current instance |
| `plan --project-root <root> [--contract-root <rel>] [--candidate-input <file>]` | emit one canonical no-write plan; omit candidate input for a framework-only refresh; a candidate-disabled optional surface produces a path-specific `RETIRE-IMMUTABLE-####` or `RETIRE-MUTABLE-####` action, warning, and exact removal preimage matching its receipt partition; mutable retirement requires the verified exact-preimage bundle, while immutable retirement follows the selected applicable backout path |
| `preview --project-root <root> --plan <file>` | regenerate and expose plan-bound current/target text, unified diffs, digests, and POSIX rwx modes without writing project paths |
| `plan ... --backout-root <absolute-private-dir>` | bind the normal mutating plan to an owner-only exact-preimage bundle root outside the project |
| `plan ... --accept-no-post-apply-backout` | exceptional alternative after explicit owner acceptance; record that transaction recovery supplies no post-success semantic backout and require the matching named apply action; this option cannot authorize optional mutable-state retirement |
| `backout-create --project-root <root> --plan <file> --backout-root <absolute-private-dir>` | capture the exact affected-path preimages in the plan-bound closed bundle |
| `backout-verify --project-root <root> --plan <file> --backout-root <absolute-private-dir> [--require-project-preimage]` | verify the closed manifest and changed-path preimage blobs; with `--require-project-preimage`, additionally prove those bundle-covered preimages still match the live project before apply |
| `backout-recover --project-root <root> --plan <file> --backout-root <absolute-private-dir> --action rollback\|finalize --approve-transaction-id <id>` | recover only an interrupted bundle-creation transaction after validating its plan-bound private root; do not substitute governed-project recovery |
| `backout-restore --project-root <root> --plan <file> --backout-root <absolute-private-dir> --approve-plan-sha256 <digest> --approve-refresh-transaction-id <id>` | after success, restore the exact changed-path preimages only while every plan-listed managed target, including preserved targets without bundle blobs, still matches its post-apply bytes and POSIX rwx mode |
| `apply --project-root <root> --plan <file> --approve-plan-sha256 <digest>` | revalidate and apply exactly the reviewed plan; repeat `--approve-action` and `--approve-warning` for every named required approval |
| `recover --project-root <root> --action rollback\|finalize --approve-transaction-id <id>` | execute only the recovery action permitted by the inspected durable transaction state |

Planning writes canonical JSON to stdout only and embeds the canonical candidate
snapshot used by apply; changing the source candidate later does not mutate that
plan. It does not materialize a candidate or mode probe in the project root, its
parent, or an implicit scratch directory. Candidate rendering stays in memory,
and planned creation modes are derived from the process umask with immediate
restoration. The active profile union runs only against the exact installed
project tree, directly for a no-op and after candidate installation inside
apply's rollback-capable transaction for a mutating plan. Relative framework
references therefore retain their real project-root semantics, and any profile
error or warning blocks a no-op or triggers rollback of a mutating candidate;
an unproved clean rollback reports `recovery-required`. The normal mutating
path requires an existing absolute, current-user-owned,
non-symlink backout root outside the project with no group or world permissions.
Create the bundle, verify it with `--require-project-preimage`, and approve the
plan's `USE-EXACT-PREIMAGE-BUNDLE` action before apply. The manifest binds the
plan digest and deterministic `refresh_transaction_id`; apply verifies it again.
The bundle stores preimages only for paths changed by apply. Restore is a
conservative whole-instance operation: every plan-listed managed target,
including preserved targets without bundle blobs, must still match its exact
post-apply regular-file bytes and POSIX rwx mode or the backout window closes.
Exactness is bounded to those file bytes, existence, POSIX rwx modes, and
introduced parent-directory topology; ownership, ACLs, extended attributes,
timestamps, inode identity, platform-specific flags, and special permission
bits are outside this mechanism's claim.
An interrupted `backout-create` reports a distinct private-root transaction;
resume only through `backout-recover` with its exact ID, then recreate after
rollback or verify after finalization. Never pass that transaction to ordinary
governed-project recovery.
Use `--accept-no-post-apply-backout` only as an explicit exceptional alternative.
Optional mutable-state retirement always requires the verified exact-preimage
bundle; the exception is rejected because transaction rollback does not provide
post-success restoration of deleted project state.
Store candidate input and plan files in an approved temporary location outside
managed project surfaces. Treat the bundle as private because it may contain
exact project-specific bytes. Delete candidate input after verification; retain
the plan and bundle only for the approved backout window, then remove them rather
than creating a permanent refresh log. Retained
or candidate project input must not contain secrets; review its materialized
paths, commands, and private facts before tracking, sharing, or publishing a
downstream repository. Refresh uses only the checkout executing the command; it
never fetches, installs, or chooses “latest.” See
[`UPDATING.md`](../UPDATING.md) for authority, live/pinned, current-format, and
recovery boundaries.

`framework_content_sha256` binds the reviewed downstream-effective file map;
`framework_distribution_sha256` binds the complete neutral public package for
provenance. When only that broader identity differs, inspection returns
`distribution-only-drift` and `inspect --check` fails because exact `current` is
its sole success state. A nonempty exact effective delta requires the named
`ACCEPT-SELECTED-FRAMEWORK-CHANGE` approval when the instance is current-format.
Unavailable, missing, malformed, or older lifecycle identity evidence fails
closed for reviewed manual project update, as does any recorded-input,
receipt-parity, digest, or managed-file preimage inconsistency; a clearly newer
schema requires a supporting framework checkout. A distribution warning alone
does not prove operative drift.

The runner is an argv prefix to which the framework appends one Python script
path and its arguments, so its accepted grammar is deliberately narrow. Direct
runners must be exactly `uv run python -B`, `python[version] -B`, or `py -3 -B`
(the executable token may be an explicit path). The only supported outer shape
is `<qualified-exec-wrapper> exec [-w|--workdir <directory>] <target>
<direct-runner>`, and the currently qualified wrapper executable is `container`.
A string check cannot establish what an opaque executable does. Qualify another
wrapper's argv-preservation semantics and add its bounded grammar and negative
tests to the validator before recording it; approval alone does not bypass this
fail-closed check. Shell or evaluator prefixes, argument dispatchers,
terminators, redirection or expansion syntax, and prefixes that already select
inline code, a module, or a script are invalid.

The runner is only the argv prefix; it does not imply a working directory.
Every lifecycle recipe therefore supplies the framework script through the
exact `<framework-checkout-as-visible-to-runner>` path. For a direct runner that
is the selected checkout path. For a qualified wrapper it is the corresponding
path inside the wrapper's mount namespace. A bare `scripts/...` suffix is valid
only when the runner is independently guaranteed to start in that framework
checkout; public bootstrap and refresh recipes do not make that assumption.

## Task Routing And Context

These commands share additive task-description flags from
[`routing_policy.py`](routing_policy.py). Their output recommends loading and
verification; it does not authorize an action.

| Command | Role |
|---|---|
| [`recommend_stack.py`](recommend_stack.py) | recommend Risk Level, Evidence Scope, Practice Guides, checks, and second-review posture |
| [`evidence_scope.py`](evidence_scope.py) | refine evidence scope from task flags and explicit paths or a Git diff base |
| [`verification_plan.py`](verification_plan.py) | group routed checks into execution phases |
| [`context_manifest.py`](context_manifest.py) | emit the concrete always-on, routing-support, module, guide, evidence, and check manifest |
| [`prompt_load_report.py`](prompt_load_report.py) | inventory configured framework file-byte ceilings or one selected downstream runtime's mandatory files and unresolved dynamic loads |
| [`query_clause_map.py`](query_clause_map.py) | query canonical-clause projection and operative-home metadata |

The import-only [`verification_registry.py`](verification_registry.py) is the
single typed registry for each required check's stable ID, display text,
execution phase, declarative activation rule, and owning guide. Routing reports
emit canonical check records with both `check_id` and `text`; consumers should
join or compare checks by `check_id`, not by display wording.

`evidence_scope.py` resolves `--path` and Git-derived paths against `--root`
(the invocation working directory by default), rejects paths that escape through
absolute, traversal, URI-like, Windows-style, or symlinked components, and
includes untracked files when `--diff-base` is used. An `--impact-review`
request widens the minimum recommendation to `feature-slice`.

`context_manifest.py` lists the project contract separately from always-on
framework files. Its `task_module_loading` result evaluates the catalog's stable
`use_full_when_conditions`: a matched positive task-characteristic flag adds the
canonical full Task Order. Its `selection_evidence` records whether compact
selection came from an explicit `--task-module` or one non-conflicting intent
flag; multiple candidate modules remain unresolved. Invalid or incomplete
condition metadata also produces an explicit unresolved route.
Catalog entries with `direct_full_when_flags` bypass compact-module selection and
expose their canonical order in the manifest's `task_order` field; incident,
data-loss, and secret-exposure characteristics currently use this route.
Use `--full` to require the canonical Task Order directly; this routing output
does not itself grant authority.

With no selection arguments, `prompt_load_report.py` emits the framework-source
inventory used by framework compliance. It includes all registered integration
templates and is not a downstream runtime closure. Pass `--project-root` and
`--runtime` together to resolve one rendered downstream entrypoint, its
operative charter, project contract, present startup-state headers, and any
always-loaded Scope of Authority module. `--contract-root` defaults to `.` and
selects a nested generated contract when needed. Alternative runtime entrypoints
are excluded; task-conditioned modules, state, procedures, guides, canonical
sources, and evidence remain listed under `unresolved_dynamic_loads`. Reported
byte and line counts establish file inventory and configured file-size-ceiling
compliance for full-load files. Header-only obligations record safe path and
presence without reading contents or attributing sizes. Neither is token or
prompt/context-cost measurement, compactness evidence, or quality evidence.

## Source And Automation Workflows

[`examples/automation_orders.example.json`](../examples/automation_orders.example.json)
is a minimum lint-valid disabled schema-v7 draft. It cannot render or execute
as-is: confirm or change its selected `cron` backend as appropriate and, before enablement, replace
the per-run draft with a typed authority, state, idempotency, and verification
contract. Keep `cwd` portable and pass the selected absolute project root
explicitly to linting and rendering. Schema v7 treats `objective`, `description`,
and command text as descriptive or executable text, never as policy evidence.
Activation and boundary decisions come only from closed fields:
`workload_class`; the paired reviewer classifications plus `external_review`;
`source_access_class` plus `source_policy`; `authority`; `idempotency`;
`state_policy`; closed explicitly rooted `instruction_sources` and
`execution_sources`; and the structured scheduler `retention` and `redaction`
objects. `parser_change` is required exactly when `workload_class` is
`parser_or_extractor_change`. There are no legacy field aliases.

The closed schema-v7 policy surfaces are:

- `idempotency`: `mode` is `deduplicate`, `disabled_only`, `read_only`, `replace`, or `transactional`; `key` is required for deduplicate/replace/transactional and otherwise is `null`. Enabled jobs cannot use `disabled_only`; `read_only` requires `write_scope: none`.
- `state_policy`: `persistence` is `none`, `project_file`, or `external_store`; `checkpoint` is `none`, `per_run`, or `transactional`; `resume` is `restart` or `cursor`; `reference` is `null`, a safe project-relative file, or a neutral external-store reference as selected by persistence. Checkpoints and cursor resume require persistent state. Project files require repository/artifact write scope and remain under the artifact roots when that is the declared scope; external stores require external write scope.
- `authority`: closed `basis`, `source_ref`, `effect_class`, `resource_refs`, `allowed_actions`, `validity`, `failure_action`, and `verification` fields. The basis, effect, failure action, and validity mode must agree with approval mode, autonomy, write scope, and failure policy. Every enabled job requires this object; cron accepts enabled standing-project grants only.
- `external_review`: required exactly for `reviewer_boundary_mode: external`; it enumerates allowed public/user-supplied data classes and closes authentication, egress, redaction, retained artifacts, retention days, and request count. `sensitive_data` and `unlisted_data` must both be `deny`.
- `source_policy`: required for `authenticated`, `account_visible`, and `sensitive` access and forbidden for `public_unauthenticated`; it closes aliases, read capabilities, scopes, request and retention bounds, terms-review date, denied writes, and required primary-source verification.
- `parser_change`: required exactly for parser/extractor workloads; it records fixture paths and SHA-256 digests, expected/approved output coverage, schema and implementation versions, change and approval records, a verification command, completed evidence gates, and a closed fail-closed action.
- `instruction_sources` and `execution_sources`: each entry is a closed `root`/`path` object whose root is exactly `project` or `framework`; resolution never falls back across roots. Every job binds the framework-rooted automation task order and scheduled-automation guide; the compact runtime module is optional and cannot substitute for that fixed closure. Other instruction sources stay under approved instruction roots or project state. Execution sources name project/framework scripts, wrappers, local modules, configuration, or lockfiles that materially define the command; an empty list asserts no such file dependency.
- `scheduler_artifacts.retention`: the portable contract permits `bounded_days`, `delete_after_run`, `indefinite`, or `manual_archive_or_truncate`. `days` is non-null only for `bounded_days`; `manual_owner` and `manual_trigger` are nonempty only for manual mode and otherwise null. Retention governs the log, not outputs, checkpoints, replay evidence, or the active lock. Automated modes must be performed by the backend or rejected. Cron accepts `indefinite` and fully specified manual retention and performs no automated retention. The lock remains persistent coordination state until the schedule is disabled/uninstalled and quiescent. `scheduler_artifacts.redaction` is `command_redacts_before_capture` or `retain_verbatim`.

| Command | Role |
|---|---|
| [`automation_orders_lint.py`](automation_orders_lint.py) | validate schema-v7 automation orders, closed typed authority/idempotency/state/workload and conditional reviewer/source/parser policies, top-level preferred backend, portable project-relative `cwd`, bounded timeout, explicit rooted instruction/execution sources, manual-retention field shape and presence, confined scheduler artifacts, and optional scheduler compatibility against one explicit selected project root |
| [`render_cron.py`](render_cron.py) | render enabled standing-order, non-overlapping jobs only when `preferred_backend` is `cron` and the manifest plus every resolved job `cwd` independently remain inside the selected project root; create a versioned pre-launch drift seal over each complete job, project/framework/cwd identities, cache-isolated Python launch flags, fixed runtime-source closure, and declared source bytes, without installing entries |
| [`run_scheduled_job.py`](run_scheduled_job.py) | runtime target emitted by the cron renderer; verify the cache-isolated Python launch profile and local module origins, read and validate through retained no-follow descriptors, refuse job/root/runtime/declared-source drift before artifact creation until rerendering, create or require owner-only scheduler artifacts, preserve the active lock inode, length-frame per-run output under the cumulative byte cap, enforce overlap and timeout, and terminate the non-detached process group on a limit or unexpected background child; the unkeyed seal is drift detection, not execution attestation or authenticity |
| [`codex_automation_registry_lint.py`](codex_automation_registry_lint.py) | validate the private portable Codex schema-v6 registry when present: closed top-level and per-kind objects, typed cadence roles and execution environments, formal RRULEs, explicit broad-discovery policy, operator-trigger route authority with structured visibility/value stage assignments, declared instruction-source paths, and paused recovery wakeups; prompt prose supplies no classification, cadence, source-path, verification, or authority evidence |
| [`check_reference_freshness.py`](check_reference_freshness.py) | inspect source-registry freshness and optional monitor-root metadata |
| [`reference_snapshot.py`](reference_snapshot.py) | create a bounded evidence snapshot from an approved local or external source |
| [`review_packet_contract.py`](review_packet_contract.py) | validate one project-neutral lifecycle bundle, runtime-class provenance, stage transitions, packet-ready/pre-submission receipts, disclosure bytes, and retained output/verification evidence; prepare deterministic non-writing receipt proposals; export the canonical hashing helpers used by source-chain checks |
| [`source_chain_artifact_lint.py`](source_chain_artifact_lint.py) | validate source-monitor, review, apply, and assurance artifacts against the complete public contract in [`docs/source_chain_artifacts.md`](../docs/source_chain_artifacts.md), resolving relative artifact paths from one explicit selected project root and rejecting paths outside the contract's single declared artifact tree before reads; compare trigger-authority-supplied route/timezone values and optional exact stage provenance; prepare canonical non-writing review-decision hash proposals; verify semantic and exact-byte review-packet evidence when external review is approved or used |
| [`source_chain_preflight.py`](source_chain_preflight.py) | enforce date, slot, canonical scope, expected route/timezone, explicit project root, predecessor, and current-artifact identity requirements before a source-chain stage |
| [`source_chain_status.py`](source_chain_status.py) | summarize source-chain terminal and success state for one logical date, run slot, canonical scope, expected route, timezone, and explicit project root |
| [`source_chain_wait.py`](source_chain_wait.py) | wait within a declared timeout for one source-chain artifact under an explicit project root with matching date, slot, scope, expected route, and timezone; optionally require current monitor-input hashes at the monitor-to-review handoff |
| [`source_deep_research_lint.py`](source_deep_research_lint.py) | validate typed browser research digests against the public [artifact contract](../docs/source_deep_research_artifacts.md), using explicit `--project-root` for local evidence |
| [`source_registry_access_audit.py`](source_registry_access_audit.py) | perform an explicitly authorized bounded live-access audit of registry URLs |

Network-capable helpers that use `url_safety.safe_urlopen` connect directly and
ignore process-level proxy settings. Proxy-backed acquisition requires a
separately reviewed transport; proxy environment variables do not route these
helpers.

Receipt preparation requires both `--prepare-receipt packet_ready` or
`--prepare-receipt pre_submission` and an explicit timezone-aware
`--validated-at` value. It emits a `prepared` object only when the proposed
state passes schema, lifecycle, chronology, and exact-byte validation. It never
modifies the lifecycle bundle. Record the proposed fields, then run the command
again without preparation flags to validate the stored record. Receipt
preparation cannot be combined with `--external-status`.

Review-decision hash preparation uses
`source_chain_artifact_lint.py --prepare-decision-hashes <review-artifact>`. It
does not modify the artifact or require route/timezone values. It rejects
incomplete, duplicate, empty, or semantically invalid finding blocks and
emits each canonical payload with its proposed SHA-256. Record the emitted
`finding_hash` values, then run normal review validation with
`--verify-decision-hashes`. Normal validation can additionally bind exact
per-stage provenance through the provider-neutral `--expected-model-label`,
`--expected-reasoning-effort`, and `--expected-execution-mode` flags.

## Framework Maintenance And Publication

| Command | Role |
|---|---|
| [`link_check.py`](link_check.py) | validate local links and anchors; external link checks are opt-in network activity |
| [`practice_guide_scaffold.py`](practice_guide_scaffold.py) | create a new Practice Guide scaffold bundle for maintainer review |
| [`render_integrations.py`](render_integrations.py) | preflight every selected registered integration source and target, then atomically render complete files into a separate output tree |
| [`validate_framework.py`](validate_framework.py) | validate public structure, registries, routing, templates, terminology, and configured loaded-surface byte ceilings against one unchanged framework-product surface |
| [`framework_consistency.py`](framework_consistency.py) | validate cross-file authority, workflow, schema, and projection contracts |
| [`framework_quality_lint.py`](framework_quality_lint.py) | validate the structural registry of repeated mistake classes, guard classifications, required owners, and workflow entries; it does not execute the registered deterministic or semantic checks |
| [`framework_compliance.py`](framework_compliance.py) | aggregate the full on-demand framework verification suite for one required `authoring-source` or `public-export` tree role |
| [`authoring_workspace_hygiene.py`](authoring_workspace_hygiene.py) | perform a bounded, two-pass physical audit of one framework-authoring workspace against an operator-supplied classification policy; read that policy as the sole content input, inspect only names and metadata for arbitrary workspace payloads, and report exact approval-required cleanup candidates and physical anomalies without traversing Git internals, deleting, or fixing anything |
| [`public_export.py`](public_export.py) | create a fresh sanitized public export at a destination outside and not above the repository; retain the complete output ancestor chain, write source bytes into new regular files, apply portable product-file rwx bits, normalize and revalidate root/subdirectory/marker modes to `0700`/`0755`/`0644`, and transport no source ownership, timestamps, special bits, ACLs, extended attributes, or platform flags; an existing empty destination may be replaced directly, while `--force` replaces only an intact exporter-owned nonempty tree; every existing destination is moved intact to `.<output-name>.previous-export-<token>/tree`, reported, and never pruned inside the transaction; failures distinguish revalidated retained paths from nominal locations whose current binding is unverified |
| [`public_handoff_check.py`](public_handoff_check.py) | qualified-Linux-container-only staged/committed gate producing a schema-4 receipt that proves one schema-2 sanitized export exactly matches an independent public clone's worktree, immutable index, and terminal state; it requires procfs descriptor paths, consumes exactly one reviewed Git executable by absolute path or inherited descriptor, executes the retained descriptor under a minimal environment, records its SHA-256, and confines ephemeral index-parser state through the retained temporary-root descriptor to a distinct initially/finally empty directory; it snapshots public and authoring Git control metadata and object storage, rejects shared identities, links, includes, worktree-specific config, alternate ref storage, shallow state, locks, unsupported entries, and terminal mutation, and keeps object stores separately bounded; staged phase binds parent `HEAD`, while committed phase additionally proves the raw candidate commit/tree/blob graph; both bind the selected direct-commit branch, upstream, full caller-supplied parent commit, clone-local Git storage, object format, and credential-free selected remote target through a domain-separated digest that discloses no URL; it accepts only literal lowercase reviewed HTTPS or SSH/scp-style publication URLs and rejects custom remote-helper schemes, embedded credential-shaped URL components, `.gitattributes`, `info/attributes`, and clone-local transport, hook, attributes, whitespace, signing, push-option, or ambiguous push-routing controls; an optional committed-phase full tag ref is bound to its exact direct object ID, commit-or-tag type, and peeled candidate commit; the release procedure separately requires a fresh ordinary clone because the checker cannot prove creation provenance; it never fetches, stages, commits, tags, configures, or pushes and does not mutate protected roots or Git state |
| [`public_handoff_lifecycle.py`](public_handoff_lifecycle.py) | close the deterministic lifecycle around the read-only handoff gate: validate operation-root topology and credential-free native Git routing; parse one exact remote-parent record; replace only a disposable independent clone's worktree payload while preserving its ordinary `.git` directory and excluding the export marker; validate receipt continuity; and check exact remote readback records. It never invokes Git, chooses credentials, commits, tags, or pushes |
| [`public_release.py`](public_release.py) | run the canonical resumable branch-publication workflow: qualify the authoring source, export and verify the public surface, construct and verify a commit in a fresh independent public clone, persist strictly ordered phase checkpoints, recover an exact retained pre-checkpoint clone only through fresh topology, remote-parent, cached-diff, and full staged-handoff verification, publish one exact approved candidate with Git's `--force-with-lease` compare-and-swap control, reconcile ambiguous push outcomes, and verify remote readback without persisting credentials |
| [`public_release_check.py`](public_release_check.py) | validate one explicitly selected `authoring-source` or `public-export` tree against its publication boundary |

### Public Release Command Map

`public_release.py` owns the normal branch-publication interface. Run it with
the exact Python interpreter also supplied to `prepare`; all paths are exact
absolute paths. Its `--help` output is the definitive flag reference.
The high-level controller accepts one lowercase HTTPS `--remote-url` because
its authenticated push boundary is the GitHub CLI. The low-level handoff
checker remains transport-generic and can validate separately reviewed HTTPS
or SSH routing; that does not extend the controller's credential policy.

| Command | Required arguments | Result |
|---|---|---|
| `prepare` | `--release-root`, `--authoring-root`, `--git-executable`, `--uv-executable`, `--python-executable`, `--remote-name`, `--branch`, `--remote-url`, `--public-name`, `--public-email`, `--commit-message` | create a new operation at an absent root and advance through a verified public candidate; optional `--commit-timestamp` fixes an explicit offset-aware second |
| `status` | `--release-root` | validate the durable ledger and report the recorded phase and nominal next action without network access; mutable artifacts may still require review |
| `resume` | `--release-root` | revalidate live state and continue candidate preparation from the last complete checkpoint; an existing clone after `export-verified` is never trusted or restaged and advances only through fresh topology, remote-parent, cached-diff, and complete staged-handoff checks |
| `publish` | `--release-root`, `--approve-candidate`; also `--github-cli` and `--github-config-dir` when a push is still required; after an existing controller-push binding, `--approve-retry-event` with its exact event digest | revalidate the exact candidate, reconcile remote state, and when needed push it with the recorded-parent `--force-with-lease` control before readback; omit the retry flag on the first attempt |
| `readback` | `--release-root` | reconcile an existing publication binding without issuing another push |

`publish` records the candidate, parent, refspec digest, and
credential-boundary digest before any controller-issued push. When the remote
already equals the candidate, it instead records an observed-candidate
publication binding with a domain-separated no-credential sentinel; this does
not claim the controller performed the earlier push. It never records
credential material or the GitHub CLI configuration-directory path. If a push
result is ambiguous, use `readback` before retrying. If the remote remains the
recorded parent, retry `publish` only for a controller-push binding with no
prior candidate observation, using the same exact candidate and
credential-helper executable and supplying the publication-bound
`last_event_sha256` from `status` through `--approve-retry-event`. The flag is
invalid on the first attempt and must be supplied on each retry invocation. If
the remote is a third object, stop and resolve the conflict through a new
reviewed release.

The controller supports branch publication only. Tags and hosted releases are
separate external effects. See
[`docs/maintenance_and_release.md`](../docs/maintenance_and_release.md) for the
phase and cleanup rules.

### Authoring Workspace Hygiene Policy

Run the report-only audit from the framework-authoring root with a tracked,
repo-relative policy path:

```bash
uv run python -B scripts/authoring_workspace_hygiene.py \
  --root . \
  --policy operator/workspace_hygiene.json \
  --format text
```

The policy is a closed JSON object. Every path array must be sorted, contain no
duplicates, and use normalized repo-relative paths. Public product roots and
`.git` are classified by the checker and must not be repeated as authoring
top-level entries.

| Field | Contract |
|---|---|
| `schema_version` | integer `1` |
| `allowed_top_level_entries` | one-component authoring-only roots that may exist beside the public product and `.git` |
| `allowed_empty_directories` | exact directories whose otherwise-fileless role, plus their ancestors, is retained; descendants are not covered |
| `allowed_empty_subtree_roots` | directory roots whose own otherwise-fileless role, ancestors, and fileless descendants are retained |
| `disposable_subtrees` | non-public subtrees reported as approval-required deletion candidates; the command never removes them |

Each path in the last three arrays must remain below a classified non-Git
top-level root. Disposable paths cannot overlap an empty-directory allowance or
select a public product path. A declaration classifies a path if it exists; it
does not create the path or require it to be present.

```json
{
  "allowed_empty_directories": [
    "evidence/review-handoff"
  ],
  "allowed_empty_subtree_roots": [
    "work/retained-scans"
  ],
  "allowed_top_level_entries": [
    "evidence",
    "operator",
    "work"
  ],
  "disposable_subtrees": [
    "work/generated-scratch"
  ],
  "schema_version": 1
}
```

The release check includes conservative high-confidence credential-value and
credential-reference detection. It deliberately avoids treating generic
entropy as proof of a secret, and passing it is not a completeness claim for
unknown or newly introduced formats. Publication still requires inspection,
source review, and any separately approved repository/history secret scan
appropriate to the release environment.

The handoff check consumes the export ownership marker as its sole payload
manifest but requires that marker itself to remain outside the public Git tree.
Staged and committed phases bind the exact public parent, remote target, export
payload, retained Git executable, isolated temporary root, public clone, and
independence from authoring Git control metadata and object storage. The check
rejects linked or shared/reference clones, alternate or multiply linked object
storage, unsupported indexes, replacement refs, grafts, payload drift,
unmanifested worktree entries, embedded URL credentials, and ambiguous push
routing. Its receipt proves one bounded local state; it neither establishes
remote freshness nor protects mutable state after the check.

`public_release.py` is the normative composer of these low-level checks. It
creates the fresh clone, stages and commits the export, persists the receipts
through `public_release_state.py`, and revalidates them at later boundaries.
Do not replace that controller with a hand-built command chain merely to bypass
its checkpoint, lease, or approval checks.

Once staging begins, an export failure retains and reports uncertain candidate,
promoted, backup, or unrestored state rather than recursively deleting it. A
safe pre-promotion restoration requires the exact retained preimage and leaves
the empty backup wrapper for inspection. Inspect and clean reported paths only
through a separately authorized step after revalidating both the successful
output and the reported artifact. For an `authoring-source`, the release checker
ignores ambient `GIT_*` routing, binds the physical worktree and terminal index
name, parses one immutable descriptor-derived index snapshot in an isolated Git
context, rejects unsupported split or sparse index forms, and revalidates the
filesystem and Git bindings at closeout. The exporter retains that same checked
root and index generation through selected-source reads, candidate validation,
promotion, and its terminal source confirmation; a `public-export` check does
not consult Git.

Each inspected public text or JSON file is limited to 4 MiB so
credential and boundary scanning remains a bounded operation; larger public
artifacts need an explicitly designed, independently verified release path
rather than silently bypassing the text scanner.

`framework_compliance.py` requires zero skipped unit tests for publication
evidence. A skipped environment-gated test makes that aggregate check fail with
the skip count; rerun the same suite in an approved isolation container that
provides the declared tools and boundaries instead of treating the host run as
complete evidence. When the maintained private authoring surface has a
Git-tracked, single-link regular validation entrypoint, the aggregate calls that
entrypoint in self-test mode. Mere presence, an ignored file, or a symlink does
not activate it.

For `authoring-source`, the aggregate runs the physical workspace hygiene check
as its final collector, after every test and validator that could create
residue. The checker requires Linux procfs descriptor mount identity and records
but does not traverse nested mount points, including same-device bind mounts.
The tracked operator policy supplies authoring-only classifications and declared
empty roles without publishing those local exceptions. Ownership comparisons
are runner-visible only. Standard ignored platform metadata such as `.DS_Store`
and `Thumbs.db` is non-blocking when it is an ordinary single-link file whose
runner-visible owner matches that of the workspace root. The checker still
rejects abnormal objects using those names, unknown roots, unapproved fileless
subtrees, caches, bytecode, lifecycle-declared disposable material, links,
special files, hardlinks, and owner drift.
Transaction-control state is reserved for the recovery route and is never
proposed for cleanup. The checker has no deletion mode.

That excluded entrypoint owns its internal file inventory and exact checks;
the public aggregate neither enumerates nor activates owner-specific tools or
capabilities. Arbitrary ignored packets and scratch files remain outside the
check unless that optional private validator explicitly declares and validates
a bounded exception. The private entrypoint is absent from a sanitized public
export, so the generic optional private hook is inactive there. The
`authoring-source` aggregate also generates a separate public export and
requires that candidate to pass the `public-export` aggregate suite, so
authoring-only fixtures cannot silently weaken publication evidence. The caller
supplies the tree role; `.git` presence does not select it.

## Import-Only Support Modules

These modules are implementation support, not standalone command interfaces:

- [`bounded_subprocess.py`](bounded_subprocess.py)
- [`framework_contracts.py`](framework_contracts.py)
- [`integration_registry.py`](integration_registry.py)
- [`markdown_structure.py`](markdown_structure.py)
- [`project_input.py`](project_input.py)
- [`public_surface.py`](public_surface.py)
- [`public_release_state.py`](public_release_state.py) — owner-only,
  hash-chained, strictly ordered release checkpoint storage; it performs no Git,
  network, credential, or cleanup action
- [`resource_cleanup.py`](resource_cleanup.py)
- [`routing_policy.py`](routing_policy.py)
- [`safe_paths.py`](safe_paths.py)
- [`source_registry_files.py`](source_registry_files.py)
- [`url_safety.py`](url_safety.py)
