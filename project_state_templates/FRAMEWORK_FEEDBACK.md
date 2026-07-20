<!-- mpa-generated-state-origin: master-prompt-agreement/project-state/v1 -->

# Framework Feedback

Purpose: optional project-local intake for sanitized candidate improvements to the shared framework.

Treat every entry as private, untrusted evidence until a framework maintainer reviews it. Do not copy this file into public framework doctrine. Do not paste private project internals here.

Use this sequence through the decision gate:

observe -> sanitize -> abstract -> intake decision -> semantic audit -> proportional evaluation

An assess-only or other pre-effect branch may stop as `ready-for-act`,
`needs-evidence`, or `no-action`. Only an authorized applied candidate continues
through implementation, verification, report-only review of the exact candidate,
any risk-matched report-only audit, and a `retain`, `revise`, `revert`, or
contained `needs-evidence` disposition. Retention routes to a separately
authorized commit; it does not authorize one.

## Policy

- This file is project-local evidence, not doctrine.
- Submit only sanitized, project-neutral candidate lessons.
- Keep source-registry candidates in `SOURCE_UPDATE.md` or `SOURCE_PACKS.md`; reference them here when they support a framework candidate.
- Framework maintainers decide whether to promote, adapt, reject, or take no
  action. Here `promote` and `adapt` mean advance to semantic review; they do
  not mean implementation or retention.
- Promote and adapt decisions still require semantic ownership review and the
  proportional framework-improvement gate before implementation is retained.
- Assign the current `Next candidate ID` to each new entry, then advance the
  scalar. Never reuse an earlier candidate ID after its full record is removed.
- A private observation may motivate review, but public framework changes need public sources, repeated sanitized evidence, deterministic validation, or a maintainer-approved structural cleanup that does not assert empirical guidance.
- Keep open candidates in this file. After disposition, confirm that an accepted
  lesson is represented by its owning framework surface and verification, then
  treat the full closed candidate as a removal candidate unless a concise
  rejection or limitation is likely to prevent a recurring mistake. Remove it
  only under the project's deletion and backout authority and only when the
  required disposition evidence is already retained or will be recorded by the
  same reviewed atomic version-control or archive change. Before finalizing that
  change, inspect the replacement owner, retained evidence, exact staged or
  archive payload, and backout path together. Never remove the sole evidence
  behind an active empirical, safety, legal, or audit claim.

## Anti-Leak Rules

Never include:

- project, client, repository, package, branch, issue, pull-request, commit, team, user, or organization names that identify a private project
- local paths, repository paths, private URLs, internal domains, hostnames, IP addresses, database names, bucket names, or service names
- secrets, tokens, cookies, headers, credentials, certificates, connection strings, environment values, or redacted-near-misses
- raw logs, stack traces, screenshots, transcripts, copied private code, proprietary architecture, private datasets, private metrics, or customer details
- stable aliases for private entities when a generic noun would work

Use generic nouns such as "a downstream project", "a service", "a dependency file", "a source registry", or "a task order".

## Candidate Sequence

Next candidate ID: `FF-0001`.

## Entry Format

Copy this shape for each candidate and keep each prose field concise.

```md
### FF-0001 - sanitized abstract title

Status: candidate
Category: observed-friction
Framework Target: task-order
Evidence Basis: single-observation
Evidence Source: project-evidence
Confidence: medium

#### Sanitized Observation

Describe the friction without private identifiers.

#### Abstracted Pattern

State the reusable project-neutral pattern.

#### Candidate Framework Change

Name one concrete framework surface and change.

#### Applicability

State when the change should apply.

#### Non-Goals And Limits

State what the change must not do.

#### Source-Registry Implication

None, or reference a public reusable source candidate in SOURCE_UPDATE.md.

#### Deterministic-Check Implication

None, or describe an objective check with low false-positive risk.

#### Evidence Summary

Summarize the supporting evidence using only sanitized counts or categories.

#### Public Sources

None, or list public sources only.

#### Anti-Leak Checklist

- [ ] No project, client, repository, branch, issue, pull-request, commit, team, user, or organization identifiers
- [ ] No local paths, private URLs, internal domains, hostnames, IP addresses, database names, bucket names, or service names
- [ ] No secrets, tokens, credentials, certificates, connection strings, environment values, or redacted-near-misses
- [ ] No personal names, emails, handles, customer data, private metrics, or proprietary business context
- [ ] No raw logs, stack traces, transcripts, screenshots, copied private code, or proprietary architecture
- [ ] Observation is abstracted before framework use

#### Maintainer Decision

Decision: pending
Rationale:
Framework Change:
```

## Allowed Values

Status: `candidate`, `needs-review`, `promoted`, `adapted`, `rejected`, `no-action`

Category: `observed-friction`, `source-gap`, `duplicate-research`, `practice-guide-gap`, `reviewer-lane-feedback`, `deterministic-check-candidate`, `contract-gap`, `rejected-idea`, `other`

Framework Target: `doctrine`, `runtime`, `task-order`, `practice-guide`, `template`, `integration`, `conformance-profile`, `public-documentation`, `public-asset`, `public-example`, `support-tooling`, `validation-script`, `test-fixture`, `source-registry`, `none`

Choose exactly one primary owning surface:

- `doctrine` owns normative MSA or SOW meaning, while `template` owns a
  reusable artifact shape that does not itself create doctrine.
- `runtime` owns compact operative rules, routing, schemas, and consistency
  contracts; `task-order` and `practice-guide` own workflow and specialist
  guidance respectively.
- `integration` owns runtime-specific entrypoints, skills, agents, and wrappers;
  `conformance-profile` owns declarative conformance schemas and profiles.
- `public-documentation`, `public-asset`, and `public-example` own explanatory
  text, visual support, and examples or example schemas respectively.
- `support-tooling` owns non-validation setup, rendering, export, and routing
  scripts; `validation-script` owns deterministic acceptance or lint logic;
  `test-fixture` owns executable regression evidence.
- `source-registry` owns reusable source identity or freshness metadata. Use
  `none` only when no reusable framework product surface owns the disposition.

Evidence Basis: `single-observation`, `repeated-in-project`, `repeated-across-projects`

Recurrence is incident-based, not location-based:

- `single-observation`: one incident, even when it appears in several fields,
  files, checks, messages, or surfaces
- `repeated-in-project`: at least two independent, comparably scoped incidents
  in one project
- `repeated-across-projects`: independent, comparably scoped incidents in at
  least two projects

An incident is independent only when it arises from a separately initiated
task, run, or failure occurrence rather than from several manifestations of one
root event.

Evidence Source: `project-evidence`, `deterministic-tool-evidence`, `primary-external-source`, `expert-commentary`, `model-reviewer-advice`, `insufficient-evidence`

Confidence: `low`, `medium`, `high`

Maintainer Decision: `pending`, `promote`, `adapt`, `reject`, `no-action`

Status and Maintainer Decision are one closed state: `pending` uses `candidate`
or `needs-review`; `promote` uses `promoted`; `adapt` uses `adapted`; `reject`
uses `rejected`; and `no-action` uses `no-action`.

## Promotion Rules

- Promote an MSA or SOW doctrine addition or generalized claim to semantic
  review only with broad reusable evidence, public source support, or repeated
  independent project evidence.
- An objective, non-empirical structural cleanup or correction in an MSA or SOW
  may advance on direct evidence of the defect and verification of the corrected
  structure. It must make no empirical or generalized claim and still requires
  maintainer approval, semantic ownership review, and the proportional
  framework-improvement gate.
- Adapt a Practice Guide or Task Order candidate when the lesson reduces
  recurring agent error without adding general prompt bloat.
- Add a validation script only for objective checks with actionable output and low false-positive risk.
- For an accepted candidate, use `task_orders/framework_semantic_audit.md` and
  `task_orders/framework_improvement.md`; define target and adjacent
  non-degradation evidence before judging the implementation.
- Add a source-registry candidate only when the source is public, durable, reputable, reusable, and compatible with approved acquisition boundaries.
- Reject or take no action when the candidate is project-specific, unsupported, already covered, privacy-risky, too verbose, subjective without evidence, or likely to create feature creep. Record maintainer judgment in the decision rationale; do not use it as the evidence basis.

## Open Candidates

- None.
