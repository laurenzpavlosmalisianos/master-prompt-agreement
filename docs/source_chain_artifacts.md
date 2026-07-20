# Source-Chain Artifact Contract

This chapter is the public, project-neutral artifact shape for the optional
monitor, review, apply, and assurance chain. The executable authority is
`scripts/source_chain_artifact_lint.py`; framework consistency checks keep the
four templates below aligned with its required fields and schema version.
Each stage header is closed: only the fields shown by its versioned contract
are accepted, and arbitrary project extension fields are rejected.

Using this contract does not create a scheduler, choose a model, authorize
network access, approve an external reviewer, or grant permission to edit or
commit. The project trigger authority supplies the route, timezone, scope,
date, slot, acquisition boundary, and any apply authority. A project may run
only the bounded prefix its task needs, but a later stage must bind and verify
every required predecessor.

## Chain Identity

Artifact schema version 6 binds each chain to:

- `chain_id`: `source-<logical-date>-<run-slot>`;
- one canonical `monitor_scope` and the SHA-256 of its UTF-8 bytes;
- a trigger-authority-supplied `model_route` and IANA `timezone`;
- one deterministic `stage_run_id` per stage and a collision-resistant
  `attempt_id` per invocation; and
- UTC start and completion timestamps.

The scope is NFKC-normalized and case-folded to a lowercase slug containing
only letters, digits, dots, underscores, or hyphens. `model_label`,
`reasoning_effort`, and `execution_mode` record the visible stage provenance;
use the literal `not_exposed` when the runtime does not expose a setting.
These fields do not prove capability or correctness. A private or downstream
adapter may enforce stricter route and per-stage execution-identity assignments.

Artifact paths under a project `review_artifacts/` tree are conventionally:

<!-- source-chain-canonical-paths -->
```text
monitor: review_artifacts/source_monitor/{logical_date}_{run_slot}.md
review: review_artifacts/source_review/{logical_date}_{run_slot}.md
apply: review_artifacts/source_apply/{logical_date}_{run_slot}.md
assurance: review_artifacts/automation_assurance/{logical_date}_{run_slot}.md
```
<!-- /source-chain-canonical-paths -->

## Monitor Header

<!-- source-chain-stage:monitor -->
```yaml
artifact_schema_version: 6
chain_id: source-YYYY-MM-DD-HHMM
stage: monitor
stage_run_id: monitor-YYYY-MM-DD-HHMM
attempt_id: monitor-YYYY-MM-DDTHHMMSSZ-<unique-suffix>
logical_date: YYYY-MM-DD
run_slot: HHMM
monitor_scope: <canonical-lowercase-scope>
monitor_scope_sha256: <sha256-of-canonical-scope>
model_route: <route-id-from-trigger-authority>
model_label: <exact-visible-model-or-runtime-label>
reasoning_effort: <exact-visible-setting-or-not_exposed>
execution_mode: <exact-visible-setting-or-not_exposed>
timezone: <IANA-timezone-from-trigger-authority>
started_at_utc: YYYY-MM-DDTHH:MM:SSZ
completed_at_utc: YYYY-MM-DDTHH:MM:SSZ
status: pass | no-findings | blocked | partial
source_status: pass | no-findings | partial | blocked
workspace_status: clean | dirty | concurrent_change | unknown
external_reviewer_status: not_needed | considered_skipped | blocked | approved | used
external_reviewer_packet_scope: <approved-scope-or-none>
external_reviewer_approval_source: <authority-source-or-none>
external_reviewer_packet_sha256: <sha256-or-none>
external_reviewer_packet_manifest: <review_artifacts-path-or-none>
external_reviewer_packet_manifest_sha256: <sha256-or-none>
external_reviewer_redaction: <retained-boundary-record-or-none>
inaccessible_source_count: <nonnegative-count>
unresolved_inaccessible_source_count: <nonnegative-count>
source_root_coverage_count: <nonnegative-count>
source_registry_files:
  - path: <repo-relative-source-registry>
    sha256: <sha256-or-unavailable>
    reason: <required-only-when-unavailable>
policy_files:
  - path: <repo-relative-policy-input>
    sha256: <sha256-or-unavailable>
    reason: <required-only-when-unavailable>
```
<!-- /source-chain-stage:monitor -->

The split `source_status` and `workspace_status` prevents a dirty workspace
from being misreported as source evidence. With
`--verify-current-input-hashes`, every declared available source and policy
input is read again and every approved monitor root in those registries must
have one coverage record. A successful monitor may not use
`sha256: unavailable`; that state is reserved for a partial or blocked artifact
with an explicit reason.

### SOURCE_UPDATE monitoring mode

For a declared `SOURCE_UPDATE.md` input, every populated Source Registry row
uses an exact `Monitoring Mode` of `recurring` or `one_off`. A `recurring` row
contributes its durable Source URL to the monitor's expected source-root
coverage; a `one_off` row does not. The separate `Cadence` cell is explanatory
schedule or trigger detail and is not parsed to infer this status. Feed Watcher
rows are recurring by their exact table contract. Disabled sources are omitted,
and unresolved acquisition gaps belong under `Open Gaps`. These fields
determine coverage accounting only; they do not create a scheduler or grant
acquisition authority.

## Review Header

<!-- source-chain-stage:review -->
```yaml
artifact_schema_version: 6
chain_id: source-YYYY-MM-DD-HHMM
stage: review
stage_run_id: review-YYYY-MM-DD-HHMM
attempt_id: review-YYYY-MM-DDTHHMMSSZ-<unique-suffix>
logical_date: YYYY-MM-DD
run_slot: HHMM
monitor_scope: <same-canonical-scope>
monitor_scope_sha256: <same-scope-sha256>
model_route: <same-route-id>
model_label: <exact-visible-model-or-runtime-label>
reasoning_effort: <exact-visible-setting-or-not_exposed>
execution_mode: <exact-visible-setting-or-not_exposed>
timezone: <same-IANA-timezone>
started_at_utc: YYYY-MM-DDTHH:MM:SSZ
completed_at_utc: YYYY-MM-DDTHH:MM:SSZ
status: pass | no-findings | blocked | partial | failed
external_reviewer_status: not_needed | considered_skipped | blocked | approved | used
external_reviewer_packet_scope: <approved-scope-or-none>
external_reviewer_approval_source: <authority-source-or-none>
external_reviewer_packet_sha256: <sha256-or-none>
external_reviewer_packet_manifest: <review_artifacts-path-or-none>
external_reviewer_packet_manifest_sha256: <sha256-or-none>
external_reviewer_redaction: <retained-boundary-record-or-none>
input_monitor_state: resolved | missing | invalid
input_monitor_artifact: review_artifacts/source_monitor/YYYY-MM-DD_HHMM.md
input_monitor_stage_run_id: monitor-YYYY-MM-DD-HHMM
input_monitor_attempt_id: <monitor-attempt-id-or-unavailable>
input_monitor_sha256: <sha256-or-unavailable>
inaccessible_source_count: <nonnegative-count>
unresolved_inaccessible_source_count: <nonnegative-count>
accepted_findings: <accepted-decision-block-count>
manual_findings: <accepted-manual-decision-block-count>
rejected_findings: <rejected-count>
```
<!-- /source-chain-stage:review -->

A successful or no-findings review requires a resolved, successful monitor.
The review rechecks rather than blindly copies access gaps. Each accepted
finding uses the decision block below; the header counts must agree with the
parsed blocks.

## Apply Header

<!-- source-chain-stage:apply -->
```yaml
artifact_schema_version: 6
chain_id: source-YYYY-MM-DD-HHMM
stage: apply
stage_run_id: apply-YYYY-MM-DD-HHMM
attempt_id: apply-YYYY-MM-DDTHHMMSSZ-<unique-suffix>
logical_date: YYYY-MM-DD
run_slot: HHMM
monitor_scope: <same-canonical-scope>
monitor_scope_sha256: <same-scope-sha256>
model_route: <same-route-id>
model_label: <exact-visible-model-or-runtime-label>
reasoning_effort: <exact-visible-setting-or-not_exposed>
execution_mode: <exact-visible-setting-or-not_exposed>
timezone: <same-IANA-timezone>
started_at_utc: YYYY-MM-DDTHH:MM:SSZ
completed_at_utc: YYYY-MM-DDTHH:MM:SSZ
status: pass | no-op | blocked | partial | failed
external_reviewer_status: not_needed | considered_skipped | blocked | approved | used
external_reviewer_packet_scope: <approved-scope-or-none>
external_reviewer_approval_source: <authority-source-or-none>
external_reviewer_packet_sha256: <sha256-or-none>
external_reviewer_packet_manifest: <review_artifacts-path-or-none>
external_reviewer_packet_manifest_sha256: <sha256-or-none>
external_reviewer_redaction: <retained-boundary-record-or-none>
authority_grant: <current-grant-or-none-for-unsuccessful-stage>
authority_scope: <approved-files-effects-and-VCS-scope>
authority_source: <active-request-or-named-standing-grant>
input_review_state: resolved | missing | invalid
input_review_artifact: review_artifacts/source_review/YYYY-MM-DD_HHMM.md
input_review_stage_run_id: review-YYYY-MM-DD-HHMM
input_review_attempt_id: <review-attempt-id-or-unavailable>
input_review_sha256: <sha256-or-unavailable>
base_commit: <commit-or-unavailable>
changed_files:
  - <repo-relative-path>
commit: <commit-list-none-or-unavailable>
verification:
  - command: <exact-command>
    covers: <finding-id-or-target>
    tree_or_artifact: <commit-tree-export-or-artifact-identity>
    dirty_tree: clean | tracked-diff-matches-changed_files | exported-artifact | not_applicable-readonly
    touched_files: <paths-or-none>
    expected_assertion: <objective-invariant-tested>
    output_ref: <sha256-log-or-artifact-reference>
    environment: <approved-runtime-identity>
    exit_code: <canonical-unsigned-32-bit-decimal-integer>
```
<!-- /source-chain-stage:apply -->

Only decision blocks with `apply_mode: auto`, an eligible change class and
quality gate, and a verified canonical finding hash are auto-eligible. A
successful apply needs actual authority, exact changed-file reconciliation,
and successful verification covering every auto-applied finding. The contract
does not grant commit authority. Record `exit_code` in canonical unsigned
base-10 form from `0` through `4294967295`, without a sign or leading zeroes.

When a successful apply creates a commit, run precommit gates first, commit
only the accepted changed files, verify that exact commit or tree, and only
then publish and lint the apply artifact with the real commit identity. The
apply artifact cannot be part of the source-change commit whose identity it
records; retain it later under the applicable evidence-retention and VCS
authority. Do not amend the source-change commit merely to make that evidence
self-referential.

## Assurance Header

<!-- source-chain-stage:assurance -->
```yaml
artifact_schema_version: 6
chain_id: source-YYYY-MM-DD-HHMM
stage: assurance
stage_run_id: assurance-YYYY-MM-DD-HHMM
attempt_id: assurance-YYYY-MM-DDTHHMMSSZ-<unique-suffix>
logical_date: YYYY-MM-DD
run_slot: HHMM
monitor_scope: <same-canonical-scope>
monitor_scope_sha256: <same-scope-sha256>
model_route: <same-route-id>
model_label: <exact-visible-model-or-runtime-label>
reasoning_effort: <exact-visible-setting-or-not_exposed>
execution_mode: <exact-visible-setting-or-not_exposed>
timezone: <same-IANA-timezone>
started_at_utc: YYYY-MM-DDTHH:MM:SSZ
completed_at_utc: YYYY-MM-DDTHH:MM:SSZ
status: pass | blocked | partial | failed
input_monitor_state: resolved | missing | invalid
input_monitor_artifact: review_artifacts/source_monitor/YYYY-MM-DD_HHMM.md
input_monitor_stage_run_id: monitor-YYYY-MM-DD-HHMM
input_monitor_attempt_id: <monitor-attempt-id-or-unavailable>
input_monitor_sha256: <sha256-or-unavailable>
input_review_state: resolved | missing | invalid
input_review_artifact: review_artifacts/source_review/YYYY-MM-DD_HHMM.md
input_review_stage_run_id: review-YYYY-MM-DD-HHMM
input_review_attempt_id: <review-attempt-id-or-unavailable>
input_review_sha256: <sha256-or-unavailable>
input_apply_state: resolved | missing | invalid | not_applicable
input_apply_artifact: review_artifacts/source_apply/YYYY-MM-DD_HHMM.md
input_apply_stage_run_id: apply-YYYY-MM-DD-HHMM
input_apply_attempt_id: <apply-attempt-id-or-unavailable>
input_apply_sha256: <sha256-none-or-unavailable>
latest_commit: <latest-apply-commit-none-or-unavailable>
unresolved_findings: <nonnegative-count>
unresolved_inaccessible_source_count: <nonnegative-count>
```
<!-- /source-chain-stage:assurance -->

A passing assurance record requires successful resolved predecessors. Its
unresolved access blocks must exactly reconcile the unresolved monitor and
review gaps, and `latest_commit` must match the resolved apply record when the
apply stage created a commit.

## Supporting Blocks

Put access blocks under an exact `## Inaccessible Sources` heading. Monitor
and review counts must equal the number of blocks; assurance includes only
unresolved blocks it reconciles.

<!-- source-chain-block:inaccessible -->
```yaml
source_ref: <stable-source-id>
target_kind: root | link
url: <exact-https-URL-attempted>
failure_kind: <lowercase-failure-class>
failure_detail: <bounded-evidence>
coverage_status: unresolved | primary_alternate_verified
alternate_primary_url: <verified-primary-URL-or-none>
```
<!-- /source-chain-block:inaccessible -->

Put recurring-root coverage under an exact `## Source Root Coverage` heading
in monitor artifacts.

<!-- source-chain-block:source-root-coverage -->
```yaml
source_ref: <stable-source-id>
registry_path: <repo-relative-source-registry>
monitor_root: <smallest-durable-https-root-feed-or-index>
source_role: authority-root | discovery-filter
status: checked | skipped | blocked | inaccessible | not_in_scope
cursor_kind: item | validator | no_item_list | not_applicable
latest_seen_key: <release-tag-feed-guid-commit-etag-or-none>
latest_seen_url: <exact-latest-primary-URL-or-none>
reason: <coverage-signal-skip-or-block-rationale>
```
<!-- /source-chain-block:source-root-coverage -->

`cursor_kind` owns the cursor semantics; `reason` is explanatory prose and is
not parsed to infer them. Use `item` only with `status: checked`, a non-absent
item key, and an exact item URL distinct from `monitor_root`. Use `validator`
only with `status: checked`, a non-absent retrieval validator such as an ETag,
Last-Modified value, or content digest in `latest_seen_key`, and the exact URL
validated in `latest_seen_url`; that URL may equal `monitor_root`. Use
`no_item_list` only with `status: checked`, `latest_seen_key: none`, and
`latest_seen_url` equal to `monitor_root`. Every non-checked status uses
`cursor_kind: not_applicable` with both latest-seen fields set to `none`.

Place every accepted review finding beneath exactly one `## Accepted Findings`
heading, and make each finding a complete block. The linter reads decision
fields only from that section and rejects duplicate headings, duplicate fields,
or unknown fields; rejected-finding prose therefore cannot become apply
authority. Compute `finding_hash` from the canonical payload exported by the
linter; do not invent it. While preparing a new block, set
`finding_hash: unavailable`, then run the non-writing preparation command below
and copy its proposed hash into the block. `affected_files`, `evidence`, and
`required_verification` are indented lists.

<!-- source-chain-block:review-decision -->
```yaml
finding_id: <stable-id>
finding_hash: <canonical-sha256-or-unavailable-during-preparation>
classification: accept-source-entry | accept-rule-update | accept-test-or-validator-update
apply_mode: auto | manual
change_class: content-plane | source-entry-content | source-registry-authority | control-plane | validation | public-private-boundary
source_tier: [standard] | [official-doc] | [vendor-doc] | [official-implementation] | [research] | [case-study] | [case-study-root] | [commentary] | [ai-summary]
source_role: authority-root | evidence-url | discovery-filter
quality_gate: primary_verified | non_normative_source_entry | reject_low_tier
durable_abstraction: <original-project-neutral-abstraction>
applicability: <where-and-when-it-improves-the-project>
rejected_source_specifics: <wording-workflow-product-details-not-adopted>
affected_files:
  - <repo-relative-path>
risk: low | medium | high
evidence_url: <exact-https-URL-or-repo-relative-evidence>
monitor_root: <durable-https-root-or-reference-only>
root_decision: monitor | reference-only | reject-monitor-root | unresolved
evidence:
  - <claim-specific-evidence>
required_verification:
  - <objective-or-labeled-semantic-gate>
```
<!-- /source-chain-block:review-decision -->

## Validation

Always take the expected route and timezone from the owning trigger authority,
not from an artifact under review. Use the monitor hash gate at the
monitor-to-review handoff, while the monitor still claims to represent the
current source and policy inputs, and use the decision-hash gate before apply:

```bash
<runner> <framework-ref>/scripts/source_chain_artifact_lint.py --project-root <project-root> --stage monitor --expected-model-route <route-id> --expected-timezone <IANA-timezone> --verify-current-input-hashes <monitor-artifact>
<runner> <framework-ref>/scripts/source_chain_artifact_lint.py --project-root <project-root> --stage review --expected-model-route <route-id> --expected-timezone <IANA-timezone> --verify-decision-hashes <review-artifact>
<runner> <framework-ref>/scripts/source_chain_artifact_lint.py --project-root <project-root> --stage apply --expected-model-route <route-id> --expected-timezone <IANA-timezone> <apply-artifact>
<runner> <framework-ref>/scripts/source_chain_artifact_lint.py --project-root <project-root> --stage assurance --expected-model-route <route-id> --expected-timezone <IANA-timezone> <assurance-artifact>
```

Relative artifact paths resolve from the explicit project root, not from the
caller's working directory, and validation rejects paths outside that project's
single top-level `review_artifacts/` tree before reading artifact bytes.

Prepare canonical decision payloads and SHA-256 values without modifying the
review artifact:

```bash
<runner> <framework-ref>/scripts/source_chain_artifact_lint.py --prepare-decision-hashes <review-artifact>
```

Preparation is a separate mode: it does not need route or timezone arguments
and cannot be combined with chain-validation or expected-identity options. It
rejects incomplete, duplicate, empty, or semantically invalid decision
blocks and emits stable JSON containing each canonical payload and proposed
`finding_hash`. After recording the proposed values, run normal review
validation with `--verify-decision-hashes`.

When an owning trigger authority assigns exact per-stage provenance, add
`--expected-model-label`, `--expected-reasoning-effort`, and
`--expected-execution-mode` to normal artifact validation. These generic flags
compare exact values; they do not select a provider or model.

`source_chain_preflight.py`, `source_chain_wait.py`, and
`source_chain_status.py` use the same explicit `--project-root`, date, slot,
scope, route, and timezone.
Preflight, status, and wait without `--verify-current-input-hashes` validate the
artifact as historical evidence: they validate its recorded input-identity
fields but do not compare them with mutable live files. This is required after
an apply stage legitimately changes a monitored registry. A review waiting on
its monitor predecessor must instead call `source_chain_wait.py --stage
monitor` with `--verify-current-input-hashes`; the flag is invalid for other
stages.
Their successful output is evidence about the declared contract, not proof that
the source search was complete or that a semantic decision was correct.

## Retention And Supersession

The maintained source registries and accepted implementation own current
source truth; chain artifacts are bounded evidence. Retain every required
predecessor through assurance so the input, decision, change, and verification
bindings remain inspectable. After closure, retain a completed chain's minimum
self-contained bound set only while it supports an unresolved decision,
current source or release claim, reproducibility requirement, audit identity,
incident obligation, or recurring precedent.

Once the reusable result is represented by its owning source record, rule,
decision, implementation, or regression test, and its required provenance is
already retained or will be recorded by the same reviewed atomic
version-control or archive change, duplicate failed attempts, superseded
development-schema artifacts, and intermediate no-change chains become removal
candidates. Before finalizing that change, inspect the replacement owner,
retained evidence, exact staged or archive payload, and backout path together.
Do not retain a downstream artifact as traceability evidence after deleting a
predecessor on which that claim depends, do not rewrite historical artifacts to
resemble current evidence, and never delete the sole evidence behind an active
claim or obligation.
