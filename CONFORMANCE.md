# Conformance

Conformance is profile-based. A project or framework checkout conforms only to the profile it explicitly claims.

Run:

```bash
<runner> -- "<framework-checkout-as-visible-to-runner>/scripts/conformance_check.py" --profile <profile-id> --root <path>
```

`<runner>` is the exact retained runner qualified by the successful prerequisite
diagnostic; `<framework-checkout-as-visible-to-runner>` is the checkout path in
that runner's namespace. Retain a container or `uv` prefix only when it actually
invoked the qualifying diagnostic. Do not install tools merely to run
conformance checks unless that setup action is approved.

The invoking framework checkout supplies the executable validators. `--root`
selects the tree inspected as data; it does not select same-named scripts to
execute from that tree.

## Result policy

Reports retain per-check and aggregate errors and warnings. Warnings remain
visible and are nonfatal by default; warning-bearing output is therefore not
evidence of warning-free conformance. `--strict-warnings` changes only the
aggregate status and exit result, without rewriting per-check diagnostics or
status. Errors always fail and cannot be waived. Checks with an explicitly
strict warning contract, including source freshness, remain strict without the
aggregate option.

Bootstrap `--approve-write-plan-sha256` approves only the complete rendered
write plan reported by the reviewed dry run and is required even when its
informational warning list is empty. Refresh `--approve-warning` approves only
the named warning in one exact plan. Neither option approves conformance
warnings. Initial setup acceptance and
refresh apply use strict warning handling; a later non-strict diagnostic may
retain warnings as evidence, but it is not a warning-free acceptance result.

The approved non-dry bootstrap runs one strict union of the receipt-listed
active profiles inside the write transaction; any conformance warning or error
fails the transaction and triggers rollback. Post-write human or manual review
remains a distinct acceptance obligation; deterministic conformance does not
replace it. Do not immediately rerun the same conformance profiles; rerun
conformance only for recovery verification, focused diagnosis, later drift, or
independently requested evidence.

The `profile_required_surfaces` prerequisite phase owns required-surface
diagnostics. A check whose required surface is unavailable is reported as
blocked instead of running and repeating the prerequisite error; independent
checks still run so they can report distinct root causes. Structured child
validators must write exactly one JSON report to stdout and leave stderr empty.
Nonempty stderr is a protocol failure, but it does not replace or corrupt a
valid stdout report. The aggregate already invokes its declared child
validators; run those commands separately only for focused diagnosis, not as
duplicate conformance evidence.

## Profiles

The machine-readable profile registry is `conformance/profiles.json`. Its schema is `conformance/profile.schema.json`. If this file and the registry disagree, the registry controls profile membership and required checks.

### `framework-product`

Use for a Master Prompt Agreement product distribution. The profile verifies
the exact positive inventory from `scripts/product_manifest.py`, required
product surfaces, and the bounded manifest check declared in
`conformance/profiles.json`. Select `--exact-product-tree` for a distribution
checkout: that mode also rejects undeclared files, directories, symlinks, and
special entries. Its only non-product exception is a physical root `.git` file
or directory. Cache directories, bytecode, OS metadata such as `.DS_Store` and
`Thumbs.db`, and every other undeclared entry fail this mode. The command does
not infer the mode from mutable Git metadata. Run the exact-tree qualification
before tests or other tools can create local residue. Omit the flag only when
checking required product files inside a larger intentional source tree.

A passing exact-tree result proves the declared product inventory and the closed
tree boundary above. It does not run the shipped product test suite and does not
establish source truth, semantic quality, effectiveness, or suitability for a
particular downstream project.

### `core-project`

Use for a downstream project with a generated runtime contract. The default
layout has the project and contract roots at the same path; a receipt may record
a supported nested contract root.

Required evidence is defined by `conformance/profiles.json`. In ordinary terms,
this profile validates the generated SOW, compact runtime contract, active state
files, retained `PROJECT_INPUT.json`, current root-scoped
`PROJECT_INSTANCE.json`, entrypoint references, and project-contract sync.
`PROJECT_INPUT.json` is regeneration data, not authority; the SOW governs.
`PROJECT_INSTANCE.json` is the single receipt for only the current generated
state, not a lifecycle history. Its `contract_root` locates nested input and
authority, and its
`contract_effective_date` must match retained input; refresh timestamps do not
belong in the receipt. Conformance does not establish that retained input is safe
to publish: it must contain no secrets and requires downstream privacy review
before tracking, sharing, or distribution.

The instance check treats downstream-effective drift as an error. A different
complete-distribution digest with the same effective file map is a provenance
warning instead: it does not prove generated or operative drift, but it prevents
a warning-free claim and fails an aggregate run that requests strict warnings.
The lifecycle inspector reports that case as `distribution-only-drift`; its
`--check` gate succeeds only for exact status `current`.

This profile and the framework lifecycle tooling support only the current
retained-input and receipt schemas. An absent pair is eligible for bootstrap only when no
framework-generated surface exists and no selected managed output path collides.
A partial, malformed, inconsistent, older,
or unrecognized format fails closed for separately reviewed manual project
update and cannot claim `core-project` conformance. A clearly newer schema
requires a framework checkout that supports it and likewise cannot claim
conformance under the current checkout.

Initial bootstrap and refresh apply run their profile acceptance inside their
transactions, so a successful lifecycle command does not need an immediate
standalone repetition. Run standalone conformance for recovery verification,
focused diagnosis, later drift, or independently requested evidence, including
after a contract revision, runtime transition, or post-success restore when the
lifecycle receipt is unavailable or separate evidence is required. The profile
does not fetch or select framework revisions; validators come from the explicitly
invoked checkout. A passing profile proves the declared structural and
current-instance invariants only, not that the selected checkout was the right release
to select. An exact historical restore can correctly fail selected-checkout
currency; report that state rather than relabeling the restored receipt as
current.

A non-generated or intentionally pruned setup that omits a required surface may
receive a bounded manual review, but it cannot claim this profile. Focused child
diagnostics and manual inspection are not substitutes for the aggregate gate.

### `source-managed`

Use when the project maintains source registries or source-update workflows.

Adds the source registry and source-update state surfaces declared in `conformance/profiles.json`.

### `security-managed`

Use when the project maintains recurring security verification.

Adds the recurring security verification surface declared in `conformance/profiles.json`.

### `automation-managed`

Use when the project defines standing automation orders.

Adds the automation manifest and lint checks declared in `conformance/profiles.json`.

### `multi-agent-managed`

Use when the project retains recurring multi-agent review, arbitration, or precedent lessons.

Adds the retained precedent surface declared in `conformance/profiles.json`.

### `reviewer-lane-managed`

Use when the project records reusable reviewer-lane routing evidence.

Adds `REVIEWER_LANE_FEEDBACK.md` and its lint check. Do not claim this profile merely because a task once used a reviewer; claim it only when reviewer-lane evidence is intentionally maintained as project state.

## Rules

- Claim conformance to a profile only when its aggregate check passes. Report a non-passing run as an attempted or failed profile check, with the failed check and limitation; reporting the failure does not establish conformance.
- Do not treat a higher profile as automatically better. Select the smallest profile matching the project’s real workflow.
- Do not move project-specific source lists or local working records into the
  framework product merely to satisfy a profile.
- Conformance checks verify structure and declared evidence. They do not prove output quality, source truth, security, or legal compliance.
