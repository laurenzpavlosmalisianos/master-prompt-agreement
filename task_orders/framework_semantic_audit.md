Task Order — Framework Semantic Audit

<!-- mpa-workflow-contract: {"outcome_enum":["approve","approve-with-edits","reject","needs-evidence"]} -->

Objective

Review every bounded candidate that would change a shared or reusable framework
product surface for semantic quality, ownership, boundary fit, and readiness
before publication or reuse. The surface may be doctrine, a template, a guide,
a Task Order, a runtime or integration file, deterministic support, or public
orientation, documentation, example, test, or visual material; candidate origin
or file type does not bypass this audit.

Mode: `report-only`. This task order never edits framework files. An accepted
result routes to `task_orders/framework_improvement.md`, which owns any
authorized candidate change and its pre-edit evaluation contract.

Procedure

1. Define the scope as one file or a coherent batch of affected shared or
   reusable product surfaces. Do not mix unrelated domains merely because they
   are adjacent in the repository. Ordinary downstream or project-local work
   that has no shared or reusable framework-product effect remains outside this
   audit.
2. Load `runtime/framework_quality_contract.json` and identify one owning surface
   for each reviewed concept. Supporting surfaces may link or route to the owner,
   but must not restate the owner's doctrine in a way that can drift.
3. Check overlap and non-goals. If two files appear to own the same concept,
   identify the correct owner and report the exact move, replacement route, or
   deletion.
4. Check the capability boundary. Record what the selected model, native
   runtime, implemented project, and existing framework already supply or
   enforce, then name the exact missing project-authority or workflow gap and
   its proposed framework owner. If an adequate path already covers the case,
   reject the framework addition; if the boundary cannot be established, use
   `needs-evidence`.
5. Check source basis. Source-derived rules must be expressed as original,
   project-neutral abstractions. Reject source-specific wording, taxonomy,
   commands, product names, examples, screenshots, and workflow shape unless the
   framework intentionally depends on that exact public standard or runtime.
6. Check public/private boundary. Public files must not expose local paths,
   private project names, private workflow details, personal setup choices, raw
   logs, browser state, or reviewer transcripts.
7. Check vendor-specific public doctrine. A public guide may name a class of
   tools, protocols, runtimes, or model capabilities only when that class is the
   actual subject. Otherwise keep vendor and product choices in project-local or
   private files.
8. Check verification meaning. A validator is acceptable only when the invariant
   is objective. Name structural validators as structural checks; do not claim
   that they prove semantic quality.
9. For a reusable generator, scaffold, installer, renderer, or integration whose
   artifacts outlive one invocation, review its supported lifecycle rather than
   only a fresh output snapshot. Name the applicable create, inspect or no-op,
   current-format refresh, failure-recovery, and retirement transitions; name
   unsupported transitions explicitly and require deterministic rejection. If
   the product intentionally supports a format transition, require objective
   scenario evidence for that exact transition, including at least one
   representative predecessor-to-current path. Do not require or infer
   predecessor support merely because a format or generator evolves. For a
   current-only product, require evidence that a target with no generated
   surface can enter first creation; that any generated surface with an absent
   identity, or any partial, malformed, inconsistent, older, or unrecognized
   format, fails closed for a reviewed manual update; and that a clearly newer
   format requests a supporting implementation. Route any intentionally
   supported state transformation and recovery detail to
   `practice_guides/migration_safety.md`.
10. Recommend a negative fixture when the reviewed change closes a repeated
   mistake class and the failure can be checked deterministically. Do not add or
   update it in this audit. Do not recommend a shallow fixture that only counts
   words, sections, or files unless that is the actual invariant.
11. Record exactly one result: `approve`, `approve-with-edits`, `reject`, or
   `needs-evidence`. For `approve` or `approve-with-edits`, also select the
   one binding primary evaluation class from the catalog's closed producer
   contract for `task_orders/framework_improvement.md`:
   `objective-structural`, `targeted-regression`, `behavioral-matched`,
   `rendered-semantic`, or `claim-grade`. For `reject` or `needs-evidence`, state
   the smallest missing evidence or the exact reason no framework change should
   be made. An accepted semantic result routes to framework improvement; it is
   not implementation authority and does not bypass proportional evaluation.
   Apply that task order's class decision boundaries. `approve-with-edits`
   records the exact corrections required in the candidate handoff; it does not
   apply them.
12. Bind the accepted handoff to the reviewed candidate scope, owning surface,
    required corrections, outcome, and evaluation class. A later scope or class
    change requires a new semantic audit; using stronger supporting evidence
    does not change the recorded primary class.

Acceptance Criteria

- Every retained rule has one owning surface and no conflicting duplicate owner.
- Every shared or reusable framework product surface affected by the candidate
  is included; no candidate bypasses review because it originated in source,
  feedback, audit, verification, code, support material, or a non-template file.
- The selected model, native runtime, implemented project, and existing
  framework capability boundary was inspected, and every accepted addition has
  an exact documented framework-owned gap.
- Source-derived material was abstracted before adoption and source-specific
  surfaces were rejected or explicitly justified.
- Public/private boundary and vendor-specific public doctrine checks were
  applied.
- Deterministic checks are described as structural or objective checks only.
- A durable generated system has evidence for each claimed lifecycle transition,
  not only a successful first render. Predecessor-to-current evidence exists
  only for intentionally supported transitions; unsupported formats have
  deterministic fail-closed evidence.
- Any new repeated mistake class has an exact proposed negative fixture when it
  can be tested objectively.
- The result uses exactly one closed outcome. Every accepted result produces
  exactly one binding proportional evaluation class from the catalog's five
  declared classes before implementation.
- The accepted handoff binds candidate scope, owning surface, required
  corrections, outcome, and evaluation class.
- The audit makes no framework edits.

Notes

- This task order is semantic review. It complements deterministic validators;
  it is not replaced by them.
- If a reviewer lane is used, follow `task_orders/orchestrate.md` for its lane
  plan, evidence packet, authority and data boundaries, lifecycle, output
  contract, stop condition, and coordinator validation. This audit supplies the
  semantic-review question and disposition only.
