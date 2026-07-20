# Change Impact Review Practice Guide

Use this Practice Guide for code review, risky diffs, migrations, and any change where a small patch may alter shared behavior. Diff size is not blast radius.
For generated or agent-assisted changes, excessive diff size is a reviewability risk even when blast radius is uncertain.

## Best Use Cases

- reviews of shared helpers, middleware, config defaults, or schema code
- changes with many unchanged consumers
- low-diff, high-impact patches
- release or migration reviews
- bug fixes that may preserve the symptom but break another path

## Workflow

1. Start at the smallest scope.

- Begin with the patch or touched files.
- Widen only when a changed invariant propagates outward.
- If a generated diff exceeds the project's reviewability threshold, decompose it into atomic, incremental tasks before detailed review.
- For agent-generated changes, use the diff as a comprehension and feedback surface; request focused changes or split work when the reviewer cannot explain the changed behavior.

2. Identify the changed invariants.

- contracts and return values
- public API shape, function signatures, type boundaries, and validation boundaries
- policy, routing, deny-list, allow-list, release-gate, and validator ownership boundaries
- auth or permission semantics
- data shape and nullability
- migration, rollback, forward-compatibility, and mixed-version deployment assumptions
- timing, ordering, caching, and retries
- defaults, feature flags, and fallbacks
- side effects, logging, and error handling

3. Find the consumers.

- List direct callers, downstream readers, and background jobs that rely on the changed invariant.
- Pay special attention to unchanged code that assumes the old behavior.

4. Trace the blast radius.

- Follow the invariant until it stops propagating.
- Escalate to feature-slice or trust-boundary review when the path crosses modules, services, or privilege boundaries.
- When the project spans multiple supported operating systems, architectures, hardware classes, browsers, clusters, runtimes, or deployment targets, state which targets the change affects, which targets were verified, and which remain compatible but unverified or unsupported.

5. Hunt for silent break modes.

- stale caches
- hidden permission changes
- serialization drift
- duplicate policy checks that drift across code, configuration, generated artifacts, scripts, prompts, or automation
- validators or review checks that inspect the wrong source of truth, workspace root, generated artifact, or excluded surface instead of the declared product surface
- partial rollout failures
- metrics or alert blind spots
- tests that still pass while behavior changed
- APIs that still compile while allowing unsafe or ambiguous misuse

6. Apply a maintainability-smell baseline as review probes.

- Project standards, the SOW/project scope, and accepted project decisions override this baseline.
- Treat these labels as heuristic probes or possible Weakness findings, not hard violations, unless project rules or observed behavior make the issue concrete.
- Skip issues already enforced by active tooling unless the current evidence shows the tool missed the case.
- Check for unclear names, duplicated logic shape, behavior placed far from the data it mainly uses, recurring parameter groups, primitives or strings replacing domain concepts, repeated branch cascades on the same kind of value, one logical change scattered across many files, one module changing for unrelated reasons, speculative hooks or abstractions, long navigation through another object or module's internals, pass-through wrappers with no policy value, and inheritance or interface use that is mostly rejected by the implementation.
- Report a smell only when it names the changed invariant, the affected consumer or maintainer action, and the concrete maintenance risk or smallest future failure path. Otherwise record it as a rejected probe or omit it.

7. Emit findings or residual risks.

- State the affected invariant.
- State who depends on it.
- State whether the safer fix belongs in local code, an API/type/signature change, a guardrail, or a migration plan.
- State the smallest extra test, review step, or fix that would close the risk.

## Output

Provide:

- starting Evidence Scope, meaning the files, diffs, tests, logs, schemas, runtime paths, or consumers actually inspected
- changed invariants
- affected consumers and boundaries
- concrete findings or residual risks
- smallest additional checks

For each concrete finding, include severity, file or diff location, observed evidence, affected invariant, dependent consumer or boundary, smallest credible fix, and the verification step that would prove the invariant is restored.

## Guardrails

- Do not equate a small diff with a small risk.
- Do not accept a large generated diff merely because it compiles; use size as a decomposition signal.
- Do not outsource understanding of generated code to the generator; reviewers still own the changed behavior.
- Do not review only changed lines when unchanged consumers depend on them.
- Do not treat passing new tests as proof that old guarantees still hold.
- Shared primitives deserve wider scrutiny than leaf code.
- Shared validators, policy helpers, source registries, and release gates deserve ownership and surface-scope review, not only syntax or word-count checks.
