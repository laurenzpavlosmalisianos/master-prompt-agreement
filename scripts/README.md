# Command And Module Reference

This is the complete product-side index for `scripts/`. It covers every
installed command and import-only support module. The scripts provide
deterministic support for setup, refresh, conformance, routing, evidence,
source workflows, integrations, and automation; they do not grant authority or
replace the governing Markdown files.

Run commands only from a no-error prerequisite report with
`runner_usable: true`, using its exact tested CPython interpreter and required
`-E -S -B` startup flags.
The optional `git_query` report separately checks the trusted system Git
executable and its minimum version through a bounded repository-independent
probe. PATH presence in `tools.git` is only an inventory observation.
Unavailable Git-query capability produces a warning without invalidating the
Python runner for commands that do not query Git. This snapshot grants no
later execution authority; Git-backed commands revalidate their own bindings.
If diagnostic teardown fails, `git_query.cleanup_failed` is true and the report
contains an error, returns nonzero, and refuses runner qualification.
When that runner uses a wrapper or container, resolve
`<framework-checkout-as-visible-to-runner>` in the runner's namespace. When a
script path could contain spaces or begin with a dash, terminate interpreter
options and quote the path:

```text
<qualified-python> -E -S -B -- '<framework-root>/scripts/<command>.py' [arguments]
```

The maintained runtime is CPython 3.14 or newer on a POSIX environment with the
import-boundary and transaction primitives reported by `check_prereqs.py`.
`-E` ignores `PYTHON*` environment configuration, `-S` suppresses automatic
`site`, `.pth`, and startup-customization loading, and `-B` prevents bytecode
writes. Each command's
`--help` output is the executable source of truth for exact argument order,
repeatability, choices, and defaults. The maps below keep every command and its
safety-relevant flags discoverable without loading implementation source.

The setup, refresh, contract-synchronization, instance-lint, and `core-project`
interfaces operate on downstream project instances. Their `--project-kind`
discriminator accepts `downstream`; framework-product validation is the
separate distribution-level conformance profile described below.

## Complete Long-Option Matrix

This matrix covers every installed command. It omits argparse's automatic
`--help`; positional operands and refresh subcommands are described in the
workflow maps below. “Shared routing triggers” means the exact closed set in
the next paragraph, not an open extension point.

<!-- product-cli-routing-options:start -->
Shared routing triggers:
`--agentic`, `--ambiguous`, `--api-contract-security`,
`--apple-container-workflow`, `--audit`, `--briefing`,
`--build-pipeline-integrity`, `--container-image-security`, `--css-quality`,
`--current-info`, `--data-loss`, `--data-systems`, `--database-security`,
`--debugging`, `--delegated-communication-coverage`, `--dependency-change`,
`--destructive`, `--external-effect`, `--frontend-quality`, `--go-quality`,
`--hard-to-reverse`, `--html-quality`, `--impact-review`, `--incident`,
`--infrastructure-as-code`, `--javascript-quality`, `--knowledge-transfer`,
`--kubernetes-quality`, `--logic-review`, `--migration`, `--multi-file`,
`--planning`, `--platform-architecture`, `--privacy-data-handling`,
`--privileged-effect`, `--prompt-agent-quality`, `--python-quality`,
`--release`, `--review`, `--rust-quality`, `--scheduled`,
`--scholarly-writing`, `--secret-exposure`, `--secure-development`,
`--security`, `--seo`, `--shell-cli-quality`, `--small`,
`--source-originality`, `--source-refresh`, `--sql-quality`, `--swift-quality`,
`--testing-strategy`, `--typescript-quality`, `--untrusted-input`,
`--user-facing`, `--video-creation-quality`, and `--visual`.
<!-- product-cli-routing-options:end -->

<!-- product-cli-option-matrix:start -->
- `check_prereqs.py` — no long options.
- `project_contract_model.py` — `--check`, `--write`.
- `project_bootstrap.py` — `--answers`, `--approve-write-plan-sha256`, `--contract-root`, `--create-contract-root`, `--dry-run`, `--framework-ref`, `--framework-revision-policy`, `--project-kind`, `--project-root`, `--runtime`, `--runtime-wrapper`, `--setup-profile`.
- `project_refresh.py` — `--accept-no-post-apply-backout`, `--action`, `--answers`, `--approve-action`, `--approve-plan-sha256`, `--approve-refresh-transaction-id`, `--approve-transaction-id`, `--approve-warning`, `--backout-root`, `--candidate-input`, `--check`, `--clear-runtime-wrappers`, `--contract-root`, `--framework-ref`, `--framework-revision-policy`, `--plan`, `--project-kind`, `--project-root`, `--rebind-authority-modules`, `--require-project-preimage`, `--runtime`, `--runtime-wrapper`.
- `project_contract_sync.py` — positional operand: `project_root`; `--contract-root`, `--project-kind`, `--strict-warnings`.
- `project_instance_lint.py` — `--contract-root`, `--framework-root`, `--project-kind`, `--project-root`.
- `project_state_lint.py` — `--project-root`, `--root`.
- `lint_reviewer_lane_feedback.py` — `--path`, `--root`.
- `conformance_check.py` — `--contract-root`, `--exact-product-tree`, `--format`, `--list`, `--profile`, `--project-kind`, `--root`, `--strict-warnings`.
- `recommend_stack.py` — shared routing triggers.
- `evidence_scope.py` — shared routing triggers plus `--diff-base`, `--path`, `--root`.
- `verification_plan.py` — shared routing triggers.
- `context_manifest.py` — shared routing triggers plus `--act`, `--act-autonomy`, `--binding`, `--binding-ratification`, `--broad-scope`, `--browser-session`, `--coverage-ledger`, `--critical-surface`, `--delegated`, `--external-evidence`, `--external-reviewer`, `--external-tool-output`, `--full`, `--full-task-order`, `--human-reviewer`, `--interested-coordinator`, `--multi-agent`, `--no-decision`, `--non-cron-backend`, `--panel`, `--path`, `--project-write`, `--remediation`, `--same-author-tests`, `--scheduler-change`, `--state-edits`, `--task-module`.
- `prompt_load_report.py` — `--contract-root`, `--project-root`, `--runtime`.
- `query_clause_map.py` — `--disposition`, `--home`.
- `render_integrations.py` — `--contract-root`, `--force`, `--framework-ref`, `--framework-root`, `--integration`, `--output-dir`.
- `link_check.py` — `--exclude-dir`, `--external`, `--include`, `--include-root-path`, `--no-anchors`, `--root`, `--timeout`.
- `check_reference_freshness.py` — `--audit-monitor-roots`, `--format`, `--hostname-resolution-timeout-seconds`, `--include-non-reference-docs`, `--max-age-days`, `--max-hostname-resolution-cache-entries`, `--max-hostname-resolution-requests`, `--max-source-bytes`, `--max-source-files`, `--max-unique-hosts`, `--reference-dir`, `--resolve-hostnames`, `--root`, `--run-deadline`, `--today`, `--warnings-as-errors`.
- `reference_snapshot.py` — `--force`, `--github-path`, `--github-repo`, `--output`, `--ref`, `--retrieved-date`, `--source-file`, `--source-label`, `--title`, `--url`.
- `review_packet_contract.py` — positional operand: `manifest`; `--external-status`, `--prepare-receipt`, `--validated-at`.
- `source_chain_preflight.py` — `--artifacts-root`, `--expected-model-route`, `--expected-timezone`, `--logical-date`, `--monitor-scope`, `--project-root`, `--repair-current-slot`, `--run-slot`, `--stage`.
- `source_chain_artifact_lint.py` — positional operands: `artifact [artifact ...]`; `--expected-execution-mode`, `--expected-model-label`, `--expected-model-route`, `--expected-reasoning-effort`, `--expected-timezone`, `--prepare-decision-hashes`, `--project-root`, `--required-policy-file`, `--stage`, `--verify-current-input-hashes`, `--verify-decision-hashes`.
- `source_chain_status.py` — `--artifacts-root`, `--expected-model-route`, `--expected-timezone`, `--format`, `--logical-date`, `--monitor-scope`, `--project-root`, `--run-slot`.
- `source_chain_wait.py` — `--artifact`, `--expected-execution-mode`, `--expected-model-label`, `--expected-model-route`, `--expected-reasoning-effort`, `--expected-timezone`, `--logical-date`, `--monitor-scope`, `--poll-seconds`, `--project-root`, `--run-slot`, `--stage`, `--timeout-seconds`, `--verify-current-input-hashes`.
- `source_deep_research_lint.py` — positional operands: `artifact [artifact ...]`; `--max-evidence-items`, `--max-git-queries`, `--max-records`, `--project-root`, `--run-deadline`.
- `source_registry_access_audit.py` — `--check-robots`, `--format`, `--max-read-bytes`, `--max-source-bytes`, `--max-source-entries`, `--max-source-files`, `--max-transport-requests`, `--max-unique-urls`, `--max-url-references`, `--monitor-roots-only`, `--reference-dir`, `--root`, `--run-deadline`, `--timeout`, `--user-agent`, `--workers`.
- `automation_orders_lint.py` — positional operand: `manifest`; `--project-root`, `--target`.
- `render_cron.py` — positional operand: `manifest`; `--force`, `--output`, `--project-root`.
- `run_scheduled_job.py` — `--expected-job-sha256`, `--expected-runtime-bundle-sha256`, `--job-id`, `--manifest`, `--project-root`.
<!-- product-cli-option-matrix:end -->

## Setup, Refresh, And Conformance

| Command | Interface and purpose |
|---|---|
| [`check_prereqs.py`](check_prereqs.py) | No required arguments. Emits JSON for the exact interpreter, platform capabilities, optional tools, usable runner, and safely quoted command examples. |
| [`project_contract_model.py`](project_contract_model.py) | `--check` verifies generated schema/blueprints; `--write` regenerates them after a reviewed model change. |
| [`project_bootstrap.py`](project_bootstrap.py) | First current-format downstream setup. Core flags: `--dry-run`, `--answers`, `--project-root`, `--runtime`, `--framework-ref`, `--framework-revision-policy`, repeatable `--runtime-wrapper`, optional `--setup-profile`, `--contract-root`, `--create-contract-root`, `--project-kind downstream`, and write-only `--approve-write-plan-sha256`. |
| [`project_refresh.py`](project_refresh.py) | Current-format lifecycle with subcommands `candidate`, `inspect`, `plan`, `preview`, `apply`, `recover`, `backout-create`, `backout-verify`, `backout-recover`, and `backout-restore`. See the command map below. |
| [`project_contract_sync.py`](project_contract_sync.py) | Validate generated SOW/runtime projection and referenced project files. Supply positional `project_root` plus optional layout flags; `--strict-warnings` promotes warnings. |
| [`project_instance_lint.py`](project_instance_lint.py) | Validate retained input, the root receipt, managed roots, provenance, and output digests for the selected framework checkout. |
| [`project_state_lint.py`](project_state_lint.py) | Validate state headers, indexes, active TODO hygiene, and durable decisions/directives for `--root`; use `--project-root` when state is nested. |
| [`lint_reviewer_lane_feedback.py`](lint_reviewer_lane_feedback.py) | Validate one reviewer-lane feedback surface with `--path` and `--root`. |
| [`conformance_check.py`](conformance_check.py) | `--list` lists profiles. Otherwise supply `--profile` and the applicable matrix options. `framework-product --exact-product-tree` checks a distribution tree; `core-project` is the routine generated-project gate. |

Treat the full schema as compiler input for setup and candidate rendering;
targeted field lookup is only an orientation aid.

### Bootstrap Safety Map

| Flags | Meaning |
|---|---|
| `--dry-run --answers <json> --project-root <root> --project-kind downstream --runtime <id>` | Validate and render the complete plan without writing. |
| `--setup-profile <json>` | Fill absent reusable defaults; never replace project-specific authority. |
| `--framework-ref <path>` | Record the stable framework reference visible to the selected runner. |
| `--framework-revision-policy live|pinned` | Record the chosen revision policy; neither choice fetches or selects a revision. |
| `--runtime-wrapper <id>` | Repeat for the complete selected wrapper set. |
| `--contract-root <relative> --create-contract-root` | Select and, when approved, create a nested authority/state root; the receipt stays at project root. |
| `--approve-write-plan-sha256 <digest>` | Authorize exactly the validated plan digest; it does not waive errors or warnings. |

Before dry run, inventory every planned target. Require that no selected managed output collides.
Bootstrap never creates the governed project root; establish and approve that directory
separately before invoking bootstrap.

### Refresh Command Map

| Subcommand | Safety-relevant arguments and result |
|---|---|
| `candidate` | `--answers`, `--project-root`, layout/runtime options; emit canonical candidate input without changing the project. |
| `inspect` | `--project-root`, optional `--contract-root`, optional `--check`; classify current, drift, refresh, recovery, manual-update, or newer-framework status. Exact current-schema authority-only drift has the distinct `authority-module-rebind-required` status with `errors: []` and eligibility evidence. |
| `plan` | `--project-root`, optional `--candidate-input`, and either `--backout-root` or explicit `--accept-no-post-apply-backout`; emit canonical plan JSON. A current schema-6 authority-digest-only recovery may instead add `--rebind-authority-modules --accept-no-post-apply-backout`. |
| `preview` | `--project-root --plan`; expose exact target text, diffs, digests, and POSIX rwx modes without writing. |
| `backout-create` | `--project-root --plan --backout-root`; capture plan-bound changed-path preimages. |
| `backout-verify` | Same roots plus optional `--require-project-preimage`; verify the closed bundle and, when requested, live preimage parity. |
| `backout-recover` | Add `--action rollback|finalize --approve-transaction-id`; recover only an interrupted bundle transaction. |
| `apply` | `--project-root --plan --approve-plan-sha256`; repeat `--approve-action` and `--approve-warning` for every named requirement. |
| `recover` | `--project-root --action rollback|finalize --approve-transaction-id`; execute only the action reported as permitted by `inspect`. |
| `backout-restore` | `--project-root --plan --backout-root --approve-plan-sha256 --approve-refresh-transaction-id`; restore only while the complete post-apply identity still matches. |

Use `preview --project-root <root> --plan <file>` before approval and follow
[`task_orders/framework_refresh.md`](../task_orders/framework_refresh.md) for
the governing sequence. Effective framework drift requires
`ACCEPT-SELECTED-FRAMEWORK-CHANGE`; a changed wrapper set requires
`REVISE-RUNTIME-WRAPPERS`. Optional-state removal requires its exact numbered
`RETIRE-MUTABLE-####` or `RETIRE-IMMUTABLE-####` action.
Intentional byte drift limited to receipt-recorded external authority modules
uses the current-only, receipt-only `--rebind-authority-modules` route. Review
the exact module bytes and require its `REBIND-AUTHORITY-MODULES`,
`ACCEPT-NO-POST-APPLY-BACKOUT`, and warning approvals; structural, coverage,
path, redirect, missing-file, candidate, generated-output, framework, and
retirement changes remain blocked from that route.
A normal schema-6 plan binds current-receipt snapshots in
`current_authority_modules` and target-receipt snapshots in `authority_modules`;
apply asserts their path union. The rebind route leaves the unavailable
superseded-current list empty. Verified-bundle restore asserts the union of the
displaced target set and restored current set.

Bootstrap creates only a first instance. Refresh accepts only a verified,
complete current-format identity and exact recorded preimage. Older, newer,
partial, malformed, or unrecognized instances fail closed to the route reported
by `inspect`; approval never converts them into an update candidate. Store
temporary answers, plans, and backout bundles outside managed project surfaces.

## Routing, Context, And Verification

| Command | Interface and purpose |
|---|---|
| [`recommend_stack.py`](recommend_stack.py) | Supply task flags/description inputs to recommend risk, evidence scope, guides, checks, and review posture. |
| [`evidence_scope.py`](evidence_scope.py) | Refine evidence scope from explicit paths or an approved Git diff base; output is bounded and diagnostic. |
| [`verification_plan.py`](verification_plan.py) | Group routed checks into deterministic execution phases. |
| [`context_manifest.py`](context_manifest.py) | Emit always-on, routing-support, task-module, guide, evidence, and check loads for the selected task. |
| [`prompt_load_report.py`](prompt_load_report.py) | Report configured framework byte ceilings or one downstream runtime's mandatory and unresolved dynamic loads. |
| [`query_clause_map.py`](query_clause_map.py) | Query canonical-clause projection and operative-home metadata. |

Routing output is advice bounded by the declared registries. It cannot expand
scope, grant external effects, or weaken a project verification command.

## Integrations And Local Link Validation

| Command | Interface and purpose |
|---|---|
| [`render_integrations.py`](render_integrations.py) | Select registered integration IDs, an explicit output root, and required template inputs; preflight all targets before atomically rendering the complete output tree. |
| [`link_check.py`](link_check.py) | Validate local links and anchors under the selected root. External URL checks are explicit network activity and require their opt-in flags and applicable authority. |

## Source And Research Workflows

| Command | Interface and purpose |
|---|---|
| [`check_reference_freshness.py`](check_reference_freshness.py) | Select `--root`; repeat `--reference-dir` for every local registry directory. File/byte limits and the whole-run deadline cover the shared registry plus selected public-document snapshot. Selected documentation is inventoried and read through one descriptor-bound generation per declared root; concurrent deletion, addition, substitution, or safe-path binding failure stops the CLI with a bounded diagnostic. Hostname resolution separately bounds unique hosts, uncached requests, cache entries, and per-request time. Optional controls include `--max-age-days`, `--today`, `--include-non-reference-docs`, `--audit-monitor-roots`, `--resolve-hostnames`, `--hostname-resolution-timeout-seconds`, `--max-source-files`, `--max-source-bytes`, `--max-unique-hosts`, `--max-hostname-resolution-requests`, `--max-hostname-resolution-cache-entries`, `--run-deadline`, `--warnings-as-errors`, and `--format`. No private directory is assumed. |
| [`reference_snapshot.py`](reference_snapshot.py) | Snapshot one approved local or external source into an explicit bounded output; network acquisition and hostname resolution remain explicit. |
| [`review_packet_contract.py`](review_packet_contract.py) | Validate lifecycle bundles and stage provenance; optional receipt preparation requires `--prepare-receipt packet_ready|pre_submission` and timezone-aware `--validated-at`. Preparation emits a proposal and never edits the bundle. |
| [`source_chain_preflight.py`](source_chain_preflight.py) | Require the selected project root, logical date, slot, scope, route, timezone, predecessor, and current artifact identity before a stage. |
| [`source_chain_artifact_lint.py`](source_chain_artifact_lint.py) | Validate monitor/review/apply/assurance artifacts. `--prepare-decision-hashes` emits canonical finding hashes; normal validation can require route/timezone, model label, reasoning effort, execution mode, and exact review-packet evidence. |
| [`source_chain_status.py`](source_chain_status.py) | Summarize terminal/success state for one date, slot, scope, route, timezone, and project root. |
| [`source_chain_wait.py`](source_chain_wait.py) | Wait only within the declared timeout for a matching artifact; optional current-input hash checks bind monitor-to-review handoff. |
| [`source_deep_research_lint.py`](source_deep_research_lint.py) | Validate typed browser-research digests and explicitly rooted local evidence under shared record, evidence-item, Git-query, and whole-run deadline limits. Exact repeated revision-bound local evidence is queried once per run; mutable current-successor paths are revalidated. |
| [`source_registry_access_audit.py`](source_registry_access_audit.py) | Perform an explicitly authorized bounded live-access audit. Repeat `--reference-dir` for selected registries; visited-entry, retained-file, byte, URL, transport-attempt, and whole-run limits are explicit. Safe-path binding failures become bounded structured diagnostics before any network work, and no private directory is assumed. |

Network-capable helpers connect directly and ignore ambient proxy settings.
Proxy-backed acquisition needs a separately reviewed transport. Retrieved and
browser content remains untrusted data until the source workflow validates and
adopts it.

## Automation

| Command | Interface and purpose |
|---|---|
| [`automation_orders_lint.py`](automation_orders_lint.py) | Validate the selected automation manifest, project root, authority/idempotency/state policies, scheduler paths, bounded resources, and optional backend target. |
| [`render_cron.py`](render_cron.py) | Render enabled standing-order jobs only when the validated manifest selects cron; require explicit project/output roots and preserve the complete drift seal. It does not install entries. |
| [`run_scheduled_job.py`](run_scheduled_job.py) | Runtime target for rendered jobs. Before any adjacent local source executes, it verifies the dedicated fixed-runtime-bundle seal and loads the boundary and local modules from that exact descriptor-read snapshot. It then verifies the complete project/framework/cwd/job/source seal, enforces owner-only artifacts, lock/overlap/timeout/output bounds, and process-group cleanup before recording a run. It is normally invoked by generated scheduler output. |

## Import-Only Product Modules

These modules have no standalone command interface:

- [`bootstrap_transaction.py`](bootstrap_transaction.py) — descriptor-relative
  locking, staging, installation, rollback, recovery, and verified cleanup for
  bootstrap and refresh. Its internal `.mpa-bootstrap-recovery.previous`
  preservation artifact must coexist with the durable `.mpa-bootstrap.lock`,
  and lock retirement refuses while it exists; it is therefore not a fourth
  independent member of the public three-artifact startup gate.
- [`bounded_subprocess.py`](bounded_subprocess.py) — finite runtime/output,
  process-group termination, and child-reaping contract.
- [`generated_sow_text.py`](generated_sow_text.py) — shared generated-SOW
  lexical grammar.
- [`git_query.py`](git_query.py) — closed, credential-free Git configuration
  query boundary used by product commands.
- [`integration_registry.py`](integration_registry.py) — integration registry,
  template, and entrypoint interpretation.
- [`markdown_structure.py`](markdown_structure.py) — fence/comment-aware
  Markdown structure parsing.
- [`product_manifest.py`](product_manifest.py) — exact installable file
  inventory, downstream-effective identity, and product import closure.
- [`python_import_boundary.py`](python_import_boundary.py) — source-only local
  import boundary for product commands that execute across a trust boundary.
- [`project_input.py`](project_input.py) — retained input parsing and canonical
  serialization support.
- [`project_state_identity.py`](project_state_identity.py) — closed origin
  markers for generated mutable state.
- [`resource_cleanup.py`](resource_cleanup.py) — attempt-all,
  failure-preserving cleanup aggregation.
- [`routing_policy.py`](routing_policy.py) — shared routing predicates and
  policy evaluation.
- [`safe_paths.py`](safe_paths.py) — bounded regular-file, no-follow,
  descriptor-relative, and path-containment primitives.
- [`source_registry_files.py`](source_registry_files.py) — bounded source
  registry enumeration and snapshots.
- [`url_safety.py`](url_safety.py) — direct-connection URL validation, address
  policy, and bounded HTTP transport.
- [`verification_registry.py`](verification_registry.py) — canonical
  verification-check registry shared by routing and planning.

The checked-in product tests verify that this index names every installed
Python module exactly through its links. A new product script is incomplete
until its manifest entry, this reference, behavior tests, and relevant
documentation are updated together.
