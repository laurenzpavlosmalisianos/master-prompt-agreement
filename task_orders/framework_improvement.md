Task Order — Framework Improvement

<!-- mpa-workflow-contract: {"outcome_enum":["ready-for-act","retain","revise","revert","needs-evidence","no-action"],"invocation_mode_enum":["assess","act"]} -->

Objective

Turn an accepted, bounded framework candidate into the smallest authorized
change that earns its prompt, process, and maintenance cost, while preserving
useful empirical controls and preventing regressions relative to the current
framework and capable native defaults.

Mode: `assess` by default. Use `act` only under direct framework-maintainer
authority or a framework-authoring project contract that carries an explicit
maintainer-granted standing authority for the candidate and its effects. A
downstream SOW may authorize project-local feedback or proposals, but it cannot
authorize edits to shared framework product surfaces.

The machine-readable contract in `runtime/workflow_catalog.json` owns the legal
mode/outcome pairs. `assess` may end only at `ready-for-act`, `needs-evidence`,
or `no-action`; `act` may end at `retain`, `revise`, `revert`, or
`needs-evidence`, and may use `no-action` only when its admission recheck stops
the candidate before any effect. `ready-for-act` and `no-action` are zero-effect states.
`revert` requires restoration through `backout`; it is not zero-effect until
that restoration is verified. `needs-evidence` permits no unaccepted candidate
effect to remain active.

Entry Conditions

- Reload `AGENT_PROJECT.md` and consult `STATEMENT_OF_WORK.md` when authority,
  approval, source, verification, or publication terms can affect the change.
- Require a sanitized feedback candidate or an equivalently bounded source,
  audit, or verification handoff with one owning surface and a
  `framework_semantic_audit` outcome of `approve` or `approve-with-edits`.
- Require the exact candidate scope, owning surface, required corrections, and
  primary evidence class bound by that semantic audit. A scope or class change
  requires re-audit; stronger supporting evidence may be added without changing
  the recorded primary class.
- Bind source-derived candidates to their accepted abstraction and source
  evidence. Treat any source-chain deferral or handoff as a candidate, not as
  implementation authority.
- Stop for `reject`, `needs-evidence`, missing authority to perform the bounded
  assessment, stale evidence, or an unreviewed change in candidate scope.
  Missing edit or effect authority is expected in `assess` mode and routes to
  `ready-for-act`; it is not an assessment blocker.

Procedure

1. State the decision in one sentence: the observed problem, the candidate
   correction, the owning surface, and the behavior or invariant that should
   improve.
2. Confirm that the semantic audit's native-capability admission remains
   current. Verify what the selected model and runtime already provide and what
   project authority, current facts, acceptance criteria, durable state, source
   discipline, or verification the framework must add. Use `no-action` when
   capable native/default behavior or existing framework doctrine already
   handles the case well enough, or when the expected value does not justify
   added context and maintenance cost.
   `no-action` is a pre-edit, zero-effects exit only.
3. Confirm and use the one primary evidence class bound by the semantic audit;
   do not reselect or downgrade it:
   - `objective-structural` for a deterministic invariant, factual/source
     correction, generated lifecycle rule, or documentation/contract defect
     whose acceptance is fully decided by objective evidence;
   - `targeted-regression` when an objective oracle fully decides an observed
     behavior correction or exact sanitized reproduction;
   - `behavioral-matched` when the decision is the incremental outcome value of
     a prompt, agent, workflow, routing, or reviewer change rather than whether
     one objective failure was corrected;
   - `rendered-semantic` when acceptance depends on bounded human or independent
     judgment about visual, editorial, explanatory, or similar output;
   - `claim-grade` overrides the other classes for a causal claim; a public
     inferential or estimated quantitative claim; a recurring-default or broadly
     generalized claim; or a consequential model-routing, reviewer-topology, or
     similar decision that lighter evidence cannot answer and therefore requires
     a separately authorized high-assurance protocol. An exact deterministic
     quantity whose oracle fully decides the narrow statement remains
     `objective-structural` or `targeted-regression` as applicable.
4. Define acceptance and adjacent non-degradation before editing. Record the
   target check or oracle, affected and adjacent cases, critical approval,
   privacy, scope, safety, and side-effect guardrails, treatment of missing or
   inconclusive evidence, stop conditions, and the containment or backout path.
   Use `not applicable` only with a reviewed reason.
5. Match evidence cost to the decision:
   - For `objective-structural`, use the smallest direct source inspection,
     structural check, behavioral check, or deterministic check that proves the
     real invariant, plus the relevant adjacent checks. Retain dated
     primary-source evidence when the corrected fact is external; do not
     manufacture a lexical or count-only validator for it.
   - For `targeted-regression`, require the current behavior to fail for the
     intended reason, the candidate to pass, and selected adjacent behavior to
     remain passing. Do not accept an unrelated failure or a count-only proxy.
   - For `behavioral-matched`, prefer representative real work or an exact
     sanitized reproduction. Hold the target task and, when applicable, the
     project snapshot fixed; bind the exact current and candidate treatment
     identities. Hold budget and every other non-intervention input fixed. Keep
     model route, runtime, tools, and permissions the same unless one or more of
     those factors or the budget are explicitly bound components of the
     predeclared treatment. Record every intentionally changed factor and limit
     the claim to the bundled treatment unless its components are separately
     isolated. Include the simplest capable
     native/default or concise reference only when the decision depends on that
     comparison. Separate replay/development cases from selection and final
     held-out cases when a selection or generalization decision depends on them.
     When execution randomness, sampled cases, or judgment affects retention,
     predeclare the target population or task family, sampling unit, and source
     of variation; use independent tasks or, when execution variation within a
     task is at issue, repeated runs. Repeated runs never add independent task
     coverage.
     Predeclare treatment allocation and use pairing, ordering balance, or
     randomization when applicable; bind the primary metric or rubric, a
     practically meaningful improvement and adjacent non-degradation margin,
     and a prospective sample-size or precision rationale. Analyze the observed
     effect and method-appropriate uncertainty at the declared sampling unit
     while preserving pairing, clustering, and repeated-measures dependence.
     Report task-level n, the number of independent units after accounting for
     that dependence, and any method-defined effective n when it differs. A
     narrow deterministic single-case decision may instead record why the oracle
     fully decides that exact case and limit its claim accordingly;
     objective-structural and targeted-regression checks with exact
     deterministic oracles remain exempt from this stochastic-comparison
     contract.
   - For `rendered-semantic`, predeclare the review dimensions and retain the
     smallest reproducible evidence needed for the decision. Reviewer agreement
     is advisory, not proof.
   - For `claim-grade`, bind a separately approved, versioned protocol locator
     before implementation. The protocol must define the target population and
     sampling unit; the decision question or estimand; treatment, comparator,
     allocation, and any causal identification assumptions; primary outcomes
     and practical decision margins; sampling or repetition plan and prospective
     precision or sample-size rationale; effect and uncertainty reporting that
     preserves the declared sampling unit and dependence structure and reports
     task-level, independent, and any method-defined effective n; missing-data
     and exclusion handling; a prospectively fixed analysis or inference method,
     uncertainty construction, and decision rule, including nominal error,
     coverage, or decision calibration where applicable; multiple-comparison and
     stopping policy; evaluation provenance and contamination handling; evaluator
     class and version/configuration or human role and qualification; separately
     stated independence, treatment masking, and calibration or reliability
     controls, each marked not applicable only with a reason; invalidation
     conditions; and the permitted claim scope. It may choose any defensible statistical or causal method;
     this framework mandates neither a school of inference nor a fixed sample
     count. Do not relabel an engineering current-versus-candidate check as a
     no-framework causal study.

   For an adaptive `behavioral-matched` or `claim-grade` comparison, record the
   candidate family, primary outcomes, evaluation looks, stopping policy, and
   handling of multiple comparisons before the first confirmatory access. Any
   earlier access not governed by an already-declared adaptive method makes the
   observed result exploratory. Treat final
   held-out evidence as consumed once inspection can influence the candidate,
   evaluator, metric, or stopping decision. An exception applies only when a
   prospectively valid method, declared before first access, covers the actual
   feedback channel and information revealed, adaptive candidate generation and
   selection, every look and stopping rule, and multiplicity across candidates
   and outcomes. Otherwise further confirmation requires fresh protected
   evidence; report any reused result as exploratory and narrow the claim.

   For `behavioral-matched` and `claim-grade`, retain a provenance and
   contamination receipt for the evaluation tasks or corpus: identity and
   version or collection/release window; development, selection, or final role;
   authorized role-bounded delivery of task contents to the evaluated model and
   of the declared grading packet to the evaluator; any pre-run, development,
   optimization, answer, or undeclared packet exposure to the candidate author,
   optimizer, treatment-development process, evaluator, or evaluated model;
   near-duplicate and answer-leakage checks; and known, suspected, or unknown
   contamination, including training-data exposure when relevant. Authorized
   role-bounded evaluation delivery is not contamination. Known or suspected
   exposure outside that declared delivery requires fresh confirmation or a
   narrower claim. Unknown exposure must be disclosed, not silently treated as clean.

   Inconclusive evidence supports only a narrower claim or `needs-evidence`; it
   does not establish improvement or non-degradation.
6. Treat synthetic cases as diagnostic fixtures, not evidence of broad
   usefulness. Add a durable negative fixture only for a repeated, objective
   mistake class. A green validator proves only the invariants it actually
   checks.
7. In `assess` mode, once the pre-edit contract is complete, record
   `ready-for-act` and stop before implementation and changed-file verification.
   Resume only in `act` mode with authority bound to the exact candidate and
   evaluation contract.
8. In `act` mode, implement only the authorized minimal change. Keep evaluation
   cases, rubrics, promotion gates, and authority rules fixed during the
   candidate comparison unless a separately reviewed change explicitly owns
   them. Use native harness isolation and worktree or transaction controls when
   risk warrants them; this framework does not require a provider-specific
   runner.
9. In `act` mode, verify the exact candidate and record the evidence class, current and
   candidate identities when compared, changed files, checks and meaningful
   outcomes, missing evidence, failures, side effects, independent review when
   used, and residual limitations. No candidate authorizes its own retention.
   If evidence becomes materially insufficient after an effect, restore the
   predeclared containment or backout state before recording `needs-evidence`.
10. In `act` mode, after candidate verification and before final disposition,
    run `task_orders/review.md` in report-only mode against the exact verified
    candidate and add a report-only `task_orders/audit.md` pass when scope,
    criticality, or release posture warrants it. These passes may not edit the
    candidate. Triage every material finding; an accepted correction returns to
    `revise` and repeats the predeclared evaluation, verification, and applicable
    report-only review. Only an exact candidate with no untriaged material
    finding may be retained.
11. Record exactly one disposition:
   - `ready-for-act` in `assess` mode when the bounded candidate, authority
     requirements, and pre-edit evaluation contract are complete but effects are
     not yet authorized; this is an authorization handoff, not retention;
   - `retain` when acceptance and critical non-degradation checks pass and the
     change still earns its cost;
   - `revise` when a bounded correction remains authorized, then repeat the
     predeclared evaluation before retention;
   - `revert` when an applied or isolated candidate effect regresses a critical
     invariant, exceeds its authority, or no longer earns its cost and therefore
     requires restoration;
   - `needs-evidence` when a material decision cannot yet be supported and no
     unaccepted candidate effects remain active;
   - `no-action` before editing, in either invocation mode, when the current
     framework or native path is sufficient or a zero-effect assessed candidate
     fails its declared acceptance. If an applied candidate proves unnecessary
     or unsupported, use `revert`, not `no-action`.
12. Route a retained change only to separately authorized `commit`; its
    risk-matched report-only review and audit have already completed against the
    exact candidate. Route an applied change that requires restoration through
    `backout`. Publication and downstream project refresh remain separate
    authorized workflows.

Acceptance Criteria

- The candidate entered through sanitized intake or an equivalently bounded
  source, audit, or verification handoff and passed semantic ownership review.
- The native/default admission check and one primary evidence class were
  recorded before implementation.
- Acceptance, adjacent non-degradation, missing-evidence handling, and
  containment or backout were defined before the candidate was judged.
- Verification used a meaningful oracle for the claimed improvement and did not
  present synthetic fixtures, reviewer agreement, counts, or green tooling as
  broader proof.
- A stochastic behavioral comparison recorded its population and sampling unit,
  independent task or repetition rationale, applicable allocation design,
  primary decision margin, prospective precision rationale, dependence-
  preserving effect and uncertainty, and task-level, independent, and any
  method-defined effective n, or documented a narrow deterministic exact-case
  exception. A claim-grade evaluation bound its approved versioned protocol and
  minimum method fields. Adaptive held-out use covered the actual feedback,
  candidate-selection, look, stopping, and multiplicity lifecycle; evaluation
  contamination followed its declared receipt rules.
- The exact verified candidate passed its applicable report-only review and
  audit with no untriaged material finding; review-origin corrections repeated
  the predeclared evaluation before retention.
- An assess-only candidate ends at `ready-for-act`, `needs-evidence`, or
  `no-action`; an applied candidate and its exact changed files end at `retain`,
  `revise`, `revert`, or a contained or restored `needs-evidence` state.
  An `act` invocation may instead end at `no-action` only before editing.
  `ready-for-act` and `no-action` have no candidate effects, `revert` requires
  verified restoration, and `needs-evidence` has no unaccepted candidate
  effects.
- No causal, public inferential or estimated quantitative, recurring-default,
  or broadly generalized claim exceeds the evidence class
  that produced it.

Notes

- Rigor is proportional, not optional. A deterministic correction should not be
  forced through a study, and a behavioral or causal claim should not be reduced
  to a syntax check.
- Real project use is the preferred source of improvement cases. Raw private
  evidence remains project-local; only sanitized abstractions and bounded
  evidence references enter framework maintenance.
- Keep high-assurance study machinery available for decisions that need it.
  Its existence does not make it the default path, and validation of that
  machinery does not by itself demonstrate framework usefulness.
