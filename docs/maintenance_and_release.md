# Maintenance And Release

Use this chapter when revising or publishing the framework itself. It does not
replace `GOVERNANCE.md`, `SECURITY.md`, `CONFORMANCE.md`, or the applicable Task
Orders.

## Maintenance Discipline

- Read `runtime/operative_charter.md` before acting.
- Inspect current files before changing architecture or terminology.
- Preserve unrelated user changes and keep edits on their owning surfaces.
- Prefer semantic fixes over additional prose.
- Add deterministic checks only when they enforce a real invariant.

## Review Before Retention

For a reusable framework change, confirm that:

- the change has an owning file
- external sources were abstracted and independently evaluated, not copied
- Task Orders and Practice Guides remain distinct
- public files contain no local authoring state or private workflow detail
- templates, schemas, validation, documentation, and examples remain aligned
- generated systems pass the lifecycle review in
  `task_orders/framework_semantic_audit.md`
- an improvement candidate receives one explicit disposition under
  `task_orders/framework_improvement.md`

## Maintenance Verification

`<runner>` means the validated local Python invocation selected for the
checkout. `<framework-root>` means the exact absolute checkout path as visible
to that runner. The normal maintenance aggregate is:

```bash
<runner> <framework-root>/scripts/framework_compliance.py --tree-role authoring-source
```

This command is maintenance evidence, not publication evidence. The
`authoring-source` aggregate ends with a bounded physical-workspace inventory.
That inventory covers ignored residue, fileless directories, nested mount
boundaries, links, ownership anomalies, and declared disposable material that
Git does not represent. It reports cleanup candidates but never deletes or
repairs them. Review each candidate and obtain the applicable deletion
authorization before cleanup.

Passing scripts prove only their declared structural and behavioral
invariants. Semantic quality still requires the relevant Task Orders, Practice
Guides, source evidence, and reviewer judgment.

## Public Release Model

Publication has two separate trust transitions:

1. the richer authoring checkout becomes one marker-bound sanitized export;
2. that exact export payload becomes one commit in a fresh ordinary clone of
   the public repository.

The authoring checkout is never the publisher. Its `.git` directory, private
history, private authoring records, local configuration, refs, hooks, and object
store must never enter or be shared with the public clone. The public commit is
built on the freshly inspected public parent, so the public repository retains
only its own history.

[`scripts/public_release.py`](../scripts/public_release.py) is the canonical
branch-release controller. It preserves the existing descriptor-bound
source/export and handoff checks while
[`scripts/public_release_state.py`](../scripts/public_release_state.py) records
completed phases in a durable ledger. A shell or controller exit therefore does
not invalidate unrelated, already verified phases.

The controller currently publishes one branch update. Tags, hosted releases,
and release notes remain separate external effects and require a separately
reviewed procedure; branch readback is not evidence that any of them exists.

## Preconditions

Run the controller only in a qualified Linux container that provides procfs
descriptor paths, the selected installed `uv`, the selected Python interpreter,
Git, and any GitHub CLI credential boundary used for the push. Before
`prepare`:

- finish semantic, rendered, and manual review of the exact authoring state
- inspect `scripts/public_surface.py` and the public-facing diff
- confirm public links, examples, templates, and terminology
- inspect the intended public content for secrets and private information
- select an absent absolute operation root outside and non-nested with the
  authoring checkout
- resolve and review the exact absolute Git, `uv`, and Python executable paths
- use one credential-free lowercase HTTPS remote URL for both fetch and push
- choose the public remote, branch, commit identity, and professional commit
  message

The controller must run with the exact interpreter supplied through
`--python-executable`. When the project uses `uv`, an appropriate invocation
prefix is:

```bash
<uv> run --no-project --no-config --no-env-file --offline \
  --no-python-downloads --python <python> \
  python -I -S -B <framework-root>/scripts/public_release.py
```

`<uv>` and `<python>` must be their reviewed resolved absolute paths. Use the
command's `--help` output as the executable source of truth for flags.

## Prepare A Candidate

`prepare` creates the operation root, runs the publication-boundary authoring
aggregate, creates and verifies the sanitized export, creates a fresh ordinary
public clone, materializes only the export payload, stages it, runs the staged
handoff gate, creates the public commit, and runs the committed handoff gate.
It does not push.

```bash
<release-controller> prepare \
  --release-root <absent-absolute-operation-root> \
  --authoring-root <absolute-framework-root> \
  --git-executable <resolved-git> \
  --uv-executable <resolved-uv> \
  --python-executable <resolved-python> \
  --remote-name <remote> \
  --branch <branch> \
  --remote-url <credential-free-lowercase-https-url> \
  --public-name <public-author-name> \
  --public-email <public-author-email> \
  --commit-message <public-commit-message>
```

`--commit-timestamp` is optional. When omitted, `prepare` records the current
UTC second. All request values then become immutable operation inputs.

The JSON result reports the current phase, nominal next action, checkpoint
digest, and verified candidate object ID when one exists. The nominal action is
phase guidance, not a guarantee that mutable artifacts remain usable. Review
the candidate and public clone before authorizing publication.

## Inspect And Resume

```bash
<release-controller> status --release-root <absolute-operation-root>
<release-controller> resume --release-root <absolute-operation-root>
```

`status` validates the checkpoint ledger and reports its latest recorded phase
without network access. It does not claim that mutable external state remains
unchanged. `resume` reopens the recorded tools, revalidates the applicable live
artifacts, and advances only from the last fully recorded phase. Never edit a
ledger event, export, clone, or request to make a resume pass.

The state directory is owner-only and contains a strictly ordered,
hash-chained, atomically appended event sequence:

| Phase | Evidence retained | Normal next action |
|---|---|---|
| `initialized` | exact request and controller digest | qualify and export |
| `export-verified` | export marker and selected tool digests | clone, stage, and verify |
| `staged-verified` | public parent, staged receipt, and commit specification | create and verify candidate |
| `candidate-verified` | candidate object ID and committed receipt | review, then publish |
| `publication-bound` | candidate, parent, exact refspec digest, credential-boundary digest, and controller-push or observed-candidate mode | reconcile before retrying |
| `push-observed` | remote observed at the candidate | remote readback only |
| `readback-verified` | branch read back at the candidate | complete |

The ledger is durable evidence, not a permission source. The exact candidate
still requires authority at the push boundary.

After `prepare` atomically claims its unique absent root and initializes the
ledger, each mutating controller command holds a separate nonblocking operation
lease for the remainder of its lifetime. A concurrent `resume`, `publish`, or
`readback` against the same state fails immediately instead of racing the
clone, ledger, or external-effect boundary. `status` performs no network or
release effect; while validating the ledger, it may complete only the bounded
unlink-and-fsync recovery of a state-owned safe `.next` event residue.

## Publish And Reconcile

For the first push attempt, supply the exact reviewed candidate, resolved
GitHub CLI executable, and current-user-owned, non-group/world-writable GitHub
CLI configuration directory whose `hosts.yml` is a single-link owner-only file:

```bash
<release-controller> publish \
  --release-root <absolute-operation-root> \
  --approve-candidate <full-candidate-object-id> \
  --github-cli <resolved-github-cli> \
  --github-config-dir <absolute-owned-nonwritable-github-config-directory>
```

The first attempt MUST omit `--approve-retry-event`; no earlier push attempt
exists to authorize.

The controller revalidates the export and candidate, freshly reads the remote
branch, records a `publication-bound` controller-push event, and pushes only
the exact full-object-ID refspec with Git's `--force-with-lease`
compare-and-swap lease for the recorded parent.
It disables hooks, implicit refspecs, tags, submodule recursion, signing, push
options, and ambient credential helpers. It uses the GitHub CLI only as an
in-memory Git credential helper. Credential material and the
configuration-directory path are not written to the release ledger or
repository.

After an interrupted or ambiguous push, run `status`, then reconcile before
assuming success or retrying:

```bash
<release-controller> readback --release-root <absolute-operation-root>
```

`readback` requires a durable publication binding and never issues a push. If
the remote is the candidate, it records `push-observed` and
`readback-verified`. If it remains the recorded parent and the binding mode is
`controller-push` with no candidate observation, obtain the exact
`last_event_sha256` reported by `status`. A deliberate retry must repeat the
same candidate and credential-helper executable and add
`--approve-retry-event <publication-bound-event-sha256>`. Supply that digest on
each retry invocation; a different or missing digest fails before the push. A
third remote object is a conflict and blocks publication. Once the candidate
has been observed, never repush merely because a later readback fails or the
branch moves.

If the remote already equals the candidate, `publish` can reconcile without
the GitHub CLI flags. It first records an `adopt-observed-candidate`
publication binding whose credential-boundary field contains a
domain-separated no-credential sentinel, then records the verified remote
state; it does not imply that this controller performed the earlier push. If
that observed branch later returns to the parent, publication blocks rather
than repushing. If the remote initially equals the parent, both
credential-boundary flags are required.

## Failure Scope And Invalidation

Do not restart the entire workflow for a failure whose evidence boundary is
still intact. Apply the narrowest safe response:

| Condition | Valid evidence | Required response |
|---|---|---|
| process exits after a completed checkpoint | checkpoints through that phase | run `status`, then `resume`, `publish`, or `readback` as reported |
| failure while still `initialized`, with no export present | initialization only | run `resume`; rerun qualification and export in the same operation |
| uncheckpointed export or retained export artifact exists while still `initialized` | initialization only | preserve and inspect the artifact; use a new absent operation root unless a separately reviewed recovery proves it safe |
| handoff failure after clone materialization and staging but before `staged-verified` | verified export plus an untrusted retained clone | run `resume`; it binds the closed topology, observes the live remote parent, reruns the cached-diff check, and accepts the retained clone only through the complete staged handoff verifier; it does not clone, materialize, or stage again |
| partial, corrupt, symlinked, or remote-drifted clone before `staged-verified` | verified export; retained clone is not trusted | preserve the failed clone as evidence; after exact cleanup authorization, remove only that clone and run `resume`, or use a fresh release root |
| failure after `staged-verified` but before candidate checkpoint | export and staged receipt | run `resume`; it rechecks staged state before committing |
| failed push and remote remains the recorded parent | verified candidate and controller-push publication binding | run `readback`; then retry `publish` only with the same candidate and credential-helper executable plus `--approve-retry-event <publication-bound-event-sha256>` from `status` |
| ambiguous push result | verified candidate and publication binding | run `readback` before any retry; never infer failure from the client exit alone |
| remote equals a third object | local checkpoints only | stop; resolve the remote conflict through a new reviewed release |
| authoring source changes before `export-verified` | initialization only | requalify before sealing the export |
| authoring source changes after `export-verified` without altering the bound controller script generation | the sealed export and its downstream evidence | the change is outside this operation's snapshot; start a new operation only to include it |
| export payload, candidate, request, controller generation, or a bound tool changes incompatibly | only evidence before the affected boundary | fail closed and start a new operation where reported; never rewrite checkpoints |
| remote was observed at candidate, then changes | local proof of the earlier observation only | investigate; do not automatically republish |

The controller reports a local failure and preserves inspectable state. It has
no cleanup command. Never recursively delete an operation root, export,
candidate clone, retained exporter backup, or uncertain staging artifact as an
automatic recovery action.

## Visual Release Evidence

Framework SVGs use one fixed, self-contained design-token language on an opaque
canvas. The host page's light or dark theme therefore does not alter their
palette or contrast, and duplicate light/dark asset sets are unnecessary.
Responsive wide and narrow assets remain separate only because their geometry
differs.

When a visual or its embedding changes, render and inspect every declared
layout width locally, then inspect the committed README on GitHub in both light
and dark themes. GitHub sanitization and responsive embedding are part of the
live presentation boundary even when the SVG palette itself is theme-neutral.
Check text clipping, overlap, connector-label spacing, contrast, alt text, and
link targets. Source inspection alone is insufficient.

## Low-Level Audit Surfaces

The controller composes these narrower tools:

- `framework_compliance.py --tree-role authoring-source --publication-boundary`
- `public_export.py --publication-boundary`
- `public_release_check.py --tree-role public-export`
- `conformance_check.py --profile framework-public-release --strict-warnings`
- `public_handoff_lifecycle.py`
- `public_handoff_check.py --phase staged|committed`

Their `--help` output and [`scripts/README.md`](../scripts/README.md) document
the individual contracts. They remain useful for audit, tests, and diagnosis;
manually stitching them together is not the normative branch-publication
workflow and must not be used to bypass controller state or candidate approval.

## Cleanup And Limits

Retain the operation root until remote readback and any needed investigation
are complete. Cleanup is a separate destructive action: enumerate exact paths,
revalidate their identity and role, obtain explicit authorization, and remove
only those approved paths. Public release code never deletes the authoring
checkout or private history.

Owner-only mode is not isolation from a compromised process running as the
same UID. The qualified container must exclude untrusted same-UID processes and
mount-namespace mutation, including concurrent synchronization or replacement
of the controller checkout while a command starts or runs. Selection of the
initial `uv` launcher by absolute path is part of this prequalified-container
trust basis; after Python starts, the controller descriptor-binds and
revalidates every delegated tool use it owns. These controls also do not prove
DNS answers, TLS or SSH peer identity, credential scope, remote-service
behavior, or hosted-release authorization; establish those properties at their
owning boundaries.
