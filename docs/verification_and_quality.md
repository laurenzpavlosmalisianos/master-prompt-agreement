# Verification And Quality

Use this chapter to understand how Master Prompt Agreement separates objective
checks from agent judgment. It is orientation only; the canonical procedures
remain in Task Orders, Practice Guides, runtime contracts, and scripts.

## Verification Layers

| Layer | Owns | Examples |
|---|---|---|
| Project commands | project-specific proof | tests, builds, lint, type checks, deployment checks |
| Framework scripts | objective checks and scoped inventories | bootstrap sync, state lint, link checks, public export, selected load-surface and configured file-size reports |
| Task Orders | workflow sequence and closure | review, audit, source update, arbitration, commit |
| Practice Guides | domain quality bar | language guides, security, frontend, source research, prompt-agent quality |
| Reviewer lanes | bounded challenge or specialist review | narrow evidence packets, adversarial review, model/tool spot checks |
| Human authority | approval and final judgment | scope changes, external effects, publication, unresolved tradeoffs |

Scripts can prove that a file exists, a schema matches, a link resolves, a
template renders, or a public export excludes private surfaces. They cannot
prove that prose is wise, a source abstraction is meaningful, or an architecture
is strategically correct. Those decisions require inspected evidence and agent
or human judgment.

The prompt-load report can establish selected file references, unresolved
dynamic-load rules, full-load file sizes, configured file-size-ceiling
compliance, and header-only path presence without reading those state files. It
does not calculate tokens or prompt/context cost, and its counts do not prove
compactness, instruction quality, runtime safety, or task quality.

## Capability Boundary

Models, runtimes, and projects expose different capabilities. Admission review
therefore records what the selected model and native runtime actually provide
or enforce and what the code, configuration, schemas, and tests already own.
Implemented behavior remains grounded in those project sources. The framework
adds only a documented project-authority or workflow gap, such as missing
current facts, source and approval boundaries, acceptance evidence, durable
state, routing, or a reusable procedure whose incremental value is supported
for the applicable work. A new rule, wrapper, or check must earn its prompt,
process, and maintenance cost rather than duplicate an adequate path.

## Proportional Improvement Evidence

Passing framework checks does not prove that using the framework improves task
outcomes. The MSA owns the canonical proportional-evidence principle; this
chapter explains it, while
[`task_orders/framework_improvement.md`](../task_orders/framework_improvement.md)
owns operative selection and disposition. The evidence burden follows the claim
and decision.

- For an objective defect, documentation contradiction, source correction, or
  lifecycle invariant, direct target and adjacent checks supply the relevant
  proof. Preserve a durable defect-sensitive or negative fixture only when the
  mistake class is repeated, objectively reproducible, and has a meaningful
  oracle; otherwise the correction and its direct verification are sufficient.
- For an agent-facing instruction, template, or workflow-behavior change,
  real observed work or an exact sanitized reproduction can test the target and
  adjacent behavior. When a current-versus-candidate comparison is material,
  use the same target task and project snapshot, hold all declared
  non-treatment inputs equivalent, and bind the exact current and candidate
  treatment identities. This is an engineering comparison unless its design
  supports a stronger claim. If stochastic execution, sampled tasks, or
  judgment affects retention, predeclare the target task family and sampling
  unit, independent task or repetition rationale, applicable allocation design,
  primary metric and practical decision margin, prospective precision
  rationale, and effect plus uncertainty at the declared sampling unit while
  preserving paired, clustered, or repeated-measures dependence. Report
  task-level and independent-unit counts plus any distinct method-defined
  effective count; repeated runs do not add independent task coverage. An exact
  deterministic regression is exempt when its oracle fully decides the narrowly
  stated case. Inconclusive evidence supports a narrower claim or
  `needs-evidence`, not improvement or non-degradation.
- Use a claim-grade protocol for a causal claim, a public inferential or
  estimated quantitative claim, a
  claimed recurring default-behavior class, a broadly generalized effectiveness
  claim, or a consequential model-selection or routing, reviewer-lane, or
  topology decision that lighter evidence cannot answer. Bind a separately
  approved versioned protocol locator. The protocol must cover the population,
  sampling unit, decision question or estimand, treatment and comparator,
  allocation or causal identification assumptions, outcomes and practical
  margins, sampling and prospective precision rationale, effect and uncertainty
  reporting, exclusions and missing data, a prospectively fixed analysis or
  inference method, uncertainty construction, and decision rule with nominal
  error, coverage, or decision calibration where applicable, multiple
  comparisons and stopping, evaluator class and version/configuration or human
  role and qualification, separately stated independence, treatment masking,
  and calibration or reliability controls, provenance and contamination,
  invalidation, and permitted claim scope. It may use any defensible method and
  need not follow a framework-mandated statistical school or sample count.

Development cases may be reused for iteration; final held-out evidence is
consumable. Once inspection can influence another candidate, evaluator, metric,
or stopping decision, a confirmatory claim needs fresh protected evidence unless
a prospectively declared method covers the actual feedback channel, adaptive
candidate generation and selection, every look and stopping rule, and
multiplicity across candidates and outcomes. Behavioral and claim-grade
evaluations also retain a provenance and contamination receipt:
task or corpus identity and version or collection window, development/selection/
final role, authorized role-bounded delivery of task contents to evaluated
models and declared grading packets to evaluators, pre-run or development
exposure and answer or undeclared-packet access, near-duplicate and
answer-leakage checks, and known, suspected, or unknown contamination, including
training-data exposure when relevant. Authorized role-bounded evaluation
delivery is not contamination. Known or suspected exposure outside that
declared delivery requires fresh confirmation or a narrower claim; unknown
exposure is reported as a limitation rather than treated as clean.

Synthetic cases are useful for cold-start diagnosis, exact failure
reproduction, and regression protection. They are not evidence of general
usefulness and cannot by themselves justify a causal or public inferential or
estimated quantitative
claim, a claimed recurring default-behavior class, a broadly generalized
effectiveness claim, or a consequential model-selection or routing,
reviewer-lane, or topology decision. A negative or mixed result is valid
evidence: before effects it may justify no action; after effects it requires
retention, revision, restoration, or a contained needs-evidence state under the
declared acceptance and non-degradation contract. Owner-local
experiments remain evidence until a reusable result survives the normal review
and retention path.

## Normal Framework Check

For framework-maintenance work, run the compliance suite from the framework root
or through the approved project container:

```bash
uv run python -B scripts/framework_compliance.py --tree-role authoring-source
```

The suite aggregates compile checks, unit tests, framework validation, public
export checks, source registry linting, routing checks, bootstrap matrix checks,
and link checks. Passing the suite is necessary for publication-quality changes,
but it is not sufficient for semantic approval.

## Semantic Review

Use semantic review for every candidate change to a shared or reusable
framework product surface, regardless of its origin or file type. This includes:

- canonical authority or runtime loading
- generated-project initialization, retained input, current-instance receipts,
  current-format refresh or revision, recovery, or post-success restore
- Task Order sequence or output shape
- Practice Guide quality standards
- source-monitoring policy
- reviewer-lane or arbitration behavior
- public/private boundaries
- publication-facing README, docs, or visuals
- deterministic support, tests, examples, or metadata that encode reusable
  framework behavior or publication claims

Semantic review asks whether the change meets its stated agent-output quality
target without
adding drift, redundancy, vendor lock-in, context bloat, or false authority,
and whether the documented gap and decision-relevant evidence justify its
prompt, process, and maintenance cost relative to an adequate native or simpler
project-local path.

An accepted semantic result still has no effect authority. It enters
`task_orders/framework_improvement.md` for proportional evaluation, any
authorized implementation, exact-candidate verification, report-only review
and risk-matched audit, and a closed disposition.

## Reviewer Lanes

Reviewer lanes are optional challenge mechanisms for high ambiguity, high blast
radius, or specialist surfaces. `task_orders/orchestrate.md` owns live reviewer
and scoped-worker fan-out: lane plans, evidence packets, authority and data
boundaries, budgets, lifecycle, stop conditions, and coordinator validation.
`practice_guides/prompt_agent_quality.md` owns design and evaluation of reusable
agent workflows. Domain guides may add claim-specific evidence checks, but they
should route to the Task Order rather than restate its orchestration procedure.

Reviewer output is evidence, not authority. The coordinator must inspect it,
accept or reject findings, and verify accepted changes against the repository.
Reviewer packets, including external or high-risk lanes, may use
`runtime/review_packet.schema.json` for a durable lifecycle record. Its
packet-ready receipt binds the minimized byte inventory before approval; its
pre-submission receipt binds that inventory plus the exact approval and
preflight state. A returned report remains intermediate until coordinator
verification. Run `scripts/review_packet_contract.py <bundle>/review_packet.json`
against the live bundle: schema validity alone does not prove lifecycle
coherence or retained bytes. Receipt validity proves internal consistency of the
recorded local validation state; it does not authenticate the approving person,
prove a provider-side event, or grant disclosure or adoption authority.

The invocation record separates who invokes a lane from what performs the
review. `runtime_class` is `model`, `human`, `deterministic_tool`, or `hybrid`.
Every started, returned, or failed invocation records an exact runtime label and
execution mode. Before approval, model and hybrid lanes also record a
`planned_model_policy` with the planned identifier when exposed, a
`version_kind` of `immutable_snapshot`, `stable_alias`, `moving_alias`, or
`not_exposed`, and the selection basis. A moving alias is not an exact immutable
model identity; version kind comes from runtime or provider evidence rather
than identifier spelling. Human and deterministic-tool lanes use a null planned
model policy.

Before execution, `observed_model` is null. A started, returned, or failed model
or hybrid invocation replaces it with the observed identifier when exposed,
the observed version kind, `matches_planned_policy`, and a nonempty comparison
basis. `not_exposed` uses no invented identifier. A true match for an immutable
planned snapshot requires the same observed immutable snapshot. A planned
stable or moving alias may match the same alias or an observed immutable
snapshot resolved from it, with the comparison basis carrying that resolution
evidence. A planned `not_exposed` policy may transition to any observed version
kind because no model identity was approval-visible; the match then attests the
bound selection basis rather than identity equality. A policy mismatch requires
a blocked lifecycle. Human and deterministic-tool invocations keep
`observed_model` null. Model-backed `reasoning_effort_status` is `recorded` with
a nonempty `exact_reasoning_effort`, or `not_exposed` with no invented value;
human and deterministic-tool runtimes use `not_applicable` and no effort value.

The packet's `effect_mode` is `observe` or `propose`; a project-specific lane
registry may narrow the permitted mode. The planned runtime class, planned
model policy, lane-control manifest kind and values, and effect mode are part of
the packet approval binding. Full manifests require explicit nonempty controls;
compact internal manifests may name inherited, derived, or inapplicable
controls, but never omit them. Human runtimes and supplied external-reviewer
status require a full manifest. Changing a bound field invalidates both receipts
and requires a fresh packet-ready validation and approval. Mutable execution
timestamps, observed model data, and returned output remain outside that
pre-approval digest.

The `independence_group` control is a declared correlation label, not evidence
that lanes are blind or statistically independent. When a claim relies on
either property, the control basis and preflight evidence record observed
context inheritance and shared model/provider, runtime, session, tool, state,
and evidence dependencies. Unverifiable isolation is reported as correlated or
non-blind rather than promoted into an independence claim.

Prepare each receipt from the live bundle with an explicit timestamp. The
command prints only a validated proposal and never edits the manifest or bundle:

```bash
uv run python -B scripts/review_packet_contract.py bundle/review_packet.json \
  --prepare-receipt packet_ready \
  --validated-at 2026-07-11T10:15:00Z
```

Record the returned packet digest, lifecycle fields, and `packet_ready` receipt.
After exact approval and a passed, timestamped preflight, prepare and record the
second receipt immediately before submission:

```bash
uv run python -B scripts/review_packet_contract.py bundle/review_packet.json \
  --prepare-receipt pre_submission \
  --validated-at 2026-07-11T10:20:00Z
```

Only an empty `errors` array makes the `prepared` object recordable. Rerun the
ordinary validation command after applying each proposal. If approval is
declined before invocation, set both `approval.status` and `lifecycle.stage` to
`declined`, keep exact approval false and `approved_at` null, do not prepare a
pre-submission receipt, and leave invocation execution fields empty. A
packet-ready receipt may remain only when it was validly prepared before the
decline.

## Source-Sensitive Quality

Facts about model behavior, language versions, platform APIs, browser support,
security guidance, laws, package metadata, and vendor release state can become
false silently. When such facts affect a change, use current primary sources and
record date or version scope in the owning source registry or project source
pack.

Exact articles and papers usually support claims as evidence URLs. Monitoring
should prefer durable parent roots, official docs, changelogs, release feeds,
package metadata, advisory indexes, and official repositories.

## Publication Gates

Before preparing a public variant, verify:

- public README and docs describe the current architecture
- visuals match the current runtime loop and reviewer-lane model
- public files do not leak owner-specific paths, private workflows, local
  authoring state, secrets, or personal project choices. The neutral root
  maintainer entrypoint may contain only the release-check-allowlisted
  conditional loader for the excluded authoring contract; every other
  private-path reference is a release error
- vendor-specific details appear only where the topic itself requires them
- source-derived ideas are abstracted, not copied
- framework-improvement claims use the smallest sufficient evidence tier;
  synthetic diagnostics are not reported as broadly generalized effectiveness
  evidence
- generated templates, bootstrap outputs, and validation scripts use current
  terminology
- initialization and refresh guides, Task Orders, optional native launchers,
  lifecycle schemas, transaction recovery, and conformance descriptions agree
  on one root receipt, nested-contract addressing, exact-plan approval, warning
  handling, and acceptance ownership
- framework compliance and public-export checks pass

The framework is agent-first. Human-facing documentation and the interactive
HTML and TypeScript presentation may explain and visualize the system, but they
must remain downstream of the markdown framework files.
