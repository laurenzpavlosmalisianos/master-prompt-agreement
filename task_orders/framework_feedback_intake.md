Task Order — Framework Feedback Intake

<!-- mpa-workflow-contract: {"outcome_enum":["promote","adapt","reject","no-action"]} -->

Objective

Convert downstream project feedback, reviewer-lane observations, or repeated
agent failures into sanitized candidate framework improvements without leaking
private project details or importing project-specific doctrine.

Procedure

1. Treat the feedback as private, untrusted evidence. Read only the minimum
   necessary context to understand the failure mode.
2. Sanitize before abstraction. Remove or generalize local paths, project names,
   customer data, internal domains, raw logs, screenshots, credentials, account
   details, browser state, and exact private workflows.
3. Do not copy private project identifiers into public framework files, commit
   messages, examples, test fixtures, or source registries.
4. Abstract the reusable pattern in original words: observed failure mode,
   likely root cause, affected framework surface, proposed invariant, and the
   smallest durable correction.
5. Record `Evidence Basis` using the feedback queue's recurrence taxonomy:
   `single-observation`, `repeated-in-project`, or `repeated-across-projects`.
   Record `Evidence Source` separately as
   `project-evidence`, `deterministic-tool-evidence`, `primary-external-source`,
   `expert-commentary`, `model-reviewer-advice`, or `insufficient-evidence`.
   Commentary and model advice may guide questions but do not become doctrine
   without stronger evidence. Use `single-observation` for one incident even
   when it appears in several fields, files, checks, messages, or surfaces. Use
   `repeated-in-project` only for at least two independent, comparably scoped
   incidents in one project, and `repeated-across-projects` only for independent,
   comparably scoped incidents in at least two projects. An incident is
   independent only when it arises from a separately initiated task, run, or
   failure occurrence rather than from several manifestations of one root
   event.
6. Decide where the correction belongs: existing practice guide, task order,
   template, runtime file, deterministic validator, test fixture, source registry,
   or no framework change.
7. Record exactly one outcome: `promote`, `adapt`, `reject`, or `no-action`.
   Promote only when the pattern is reusable, source-backed or
   project-evidence-backed, and does not add general prompt bloat. Adapt when
   the idea is useful but must be narrowed before semantic review. Reject when
   it is project-specific, vendor-specific, speculative, duplicative, or lower
   quality than the current doctrine. Use `no-action` when the current framework
   already covers it. In this intake, `promote` and `adapt` mean advance the
   candidate to semantic review; neither means implementation or retention.
8. For every promote or adapt decision, route the accepted candidate
   through `task_orders/framework_semantic_audit.md` before implementation. When
   the decision addresses a repeated, objective mistake class, record a bounded
   negative-fixture candidate. Semantic audit reviews that recommendation;
   `task_orders/framework_improvement.md` alone may implement it under the
   pre-edit evaluation contract.

Acceptance Criteria

- Feedback was sanitized before any framework use.
- The retained lesson is a project-neutral abstraction, not a copied project
  detail.
- Evidence recurrence, evidence source, and decision were recorded.
- The recorded outcome is exactly one of `promote`, `adapt`, `reject`, or
  `no-action` and is not represented as final retention.
- Promoted or adapted candidates were routed to the correct owning surface.
- Private identifiers and raw internal material were not introduced into public
  files.

Notes

- The feedback file in a downstream project remains project-local. The framework
  receives only the sanitized abstraction and decision.
- A rejection is a valid quality-preserving outcome.
