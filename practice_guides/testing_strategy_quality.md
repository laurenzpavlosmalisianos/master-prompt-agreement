# Testing Strategy Quality Practice Guide

Use this Practice Guide when designing, reviewing, generating, repairing, or relying on tests as acceptance evidence. It judges whether the test portfolio can actually catch the relevant failure, not whether a command merely turned green.

Pair it with the owning domain guide when the tested surface is security, migrations, data systems, frontend rendering, APIs, Kubernetes, language-specific runtime, framework, or toolchain behavior, prompt or agent workflows, memory, tool choice, generated output, rubrics, or release readiness.

Before source-sensitive recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check current official docs for the selected test framework, runner, browser automation tool, language runtime, CI environment, and any security or compliance baseline that defines required evidence.
Prefer project policy and current official documentation over generated tests, examples, blog posts, copied snippets, or model memory; cite or record the source used when it materially affects the test design.

## Workflow

1. Define the behavior contract under test.

- State the approved requirement, invariant, bug reproduction, user-visible behavior, protocol rule, data shape, or failure mode.
- Identify the independent source of truth for expected results: specification, known-good fixture, worked example, prior baseline, user-observed behavior, or approved oracle.
- For compatibility surfaces with incomplete formal standards, define an explicit authority ladder: normative specification first, reference or canonical implementation when applicable, de facto ecosystem behavior, then measured current behavior. Tie fixtures, differential checks, or conformance tests to that ladder.
- Separate objective checks from manual acceptance items.
- Map user-environment behavior such as operating system, windowing surface, input method, locale, accessibility mode, device class, hardware capability, or browser/runtime target to an explicit matrix of automated checks, manual checks, and known unverified cells.
- Name high-risk paths that need negative, boundary, concurrency, property, fuzz, sanitizer, or adversarial checks.
- Test durable scaffolds, installers, generators, and rendered project systems as
  state transitions rather than only fresh snapshots. Declare only the lifecycle
  transitions the product intentionally supports, such as first creation,
  inspection or no-op, current-format refresh or revision, interruption recovery,
  exact backout, or retirement. Exercise a representative predecessor-to-current
  path only when conversion is an intentional supported feature, and route that
  state transformation to `migration_safety.md`. For a current-only product,
  prove that a target with no framework-generated surface and no selected
  managed-output collision can enter first creation; that an ordinary collision
  is preserved and rejected before mutation; that any generated surface with an absent identity, or any partial,
  malformed, inconsistent, older, or unrecognized format, fails before mutation
  and requests a reviewed manual update; and that a clearly newer format requests
  a supporting implementation.
- For language, runtime, framework, or generated-code ports, preserve or create behavior-level suites at stable external boundaries such as CLI, protocol, API, wire format, fixtures, or user-visible output so tests do not depend on the implementation language or internal module shape.

2. Choose the smallest sufficient test portfolio.

- Prefer fast, isolated tests for local logic and explicit integration tests for boundaries where components interact.
- Scale verification scope with blast radius: start with the narrowest checks that cover the changed behavior, then broaden when the change touches shared interfaces, shared configuration, generated artifacts, runtime matrices, or consumers beyond the edited files.
- Use end-to-end or UI tests only for user journeys, wiring, browser behavior, accessibility, or cross-component behavior that smaller tests cannot prove.
- Classify tests by what they touch: process, filesystem, clock, randomness, network, database, external service, browser, device, cluster, or privileged resource.
- Keep generated tests, snapshots, golden files, and broad regression suites tied to a named invariant; review generated tests as code.
- Record what the selected tests deliberately do not prove.

3. Check oracle and assertion quality.

- Each material test should fail if the changed behavior is broken.
- Expected values must not be recomputed through the same algorithm or data path being tested.
- Assertions should be specific enough to catch the defect without overfitting incidental implementation details.
- Include negative cases for deny, validation, permission, parser, migration, compatibility, and error-path rules.
- For probabilistic, model, search, ranking, agent, or generated-output behavior, define tolerance, seed, fixture, evaluator, rubric, model/runtime/tool versions, test corpus, and residual uncertainty.
- When free-form reasoning, traces, or generated explanations are mapped to fixed labels, answer choices, scores, or schemas, keep generation and extraction stages separate; version the mapper, oracle, or script; and report limitations introduced by the mapping protocol.
- When assertion quality is uncertain, consider mutation testing, fault injection, or a deliberate temporary break only with explicit experiment or implementation authority, a disposable or test-owned target, a captured baseline, and verified restoration. In review-only work, recommend the probe instead of mutating files or state.

4. Control the environment.

- Isolate mutable test state; reset only disposable or explicitly test-owned databases, files, mocks, browser state, caches, queues, clocks, randomness, and global registries between tests. Never reset production, shared, or non-test state merely to improve isolation, and verify restoration when a probe changes persistent state.
- Treat build, test, render, and candidate outputs as lifecycle-managed verification artifacts. Before running, classify each location as task-owned disposable output, retained candidate or evidence governed by a declared retention or promotion rule, or shared or user-owned cache, and prefer isolated paths. When retention ends, remove only task-owned paths through an authorized cleanup route. Use a clean rebuild or shared-cache purge only when required by the verification profile or invariant and authorized for the affected paths; never erase unrelated state.
- Avoid uncontrolled third-party systems in automated tests; replace them with approved fixtures, fakes, contract tests, or stable staging dependencies.
- Verify test data ownership, classification, retention, redaction, and synthetic-data boundaries when tests touch protected data.
- Make parallel execution safe by removing order dependencies and shared mutable state, or document the required serialization.
- Pin or record runtime, browser, OS, service, schema, seed, and fixture versions when results depend on them.

5. Treat flakiness as a test defect until proven otherwise.

- Reproduce nondeterminism before dismissing a failure.
- Identify whether the variation comes from timing, concurrency, order dependency, environment drift, external services, resource limits, random data, or the product.
- Quarantine only with owner, reason, expiry, and replacement coverage.
- Retries may collect evidence; they do not make a failing invariant pass.
- Do not hide fault-revealing failures behind broad flaky-test labels.

6. Review test maintainability.

- Tests should explain scenario, action, and expected outcome without complex control flow.
- Helpers, fixtures, and mocks should clarify intent, not obscure the behavior under test.
- Keep tests near the behavior or in a clearly owned suite; remove stale tests when the behavior no longer exists.
- Avoid asserting private structure when public behavior, contract, or state transition is the real invariant.
- Update docs, runbooks, examples, or generated fixtures when the tested contract changes.

7. Produce acceptance evidence.

- Record exact commands, environment, test selection, seeds, fixtures, skipped or quarantined tests, and relevant logs or reports.
- State which required invariants passed, failed, were not run, or remain manual.
- For residual gaps, name the smallest additional test, inspection, or manual acceptance item that would close them.

## Output

Provide:

1. behavior contract and independent oracle
2. selected test portfolio and omitted coverage
3. environment and data controls
4. assertion, negative-case, and flakiness review
5. commands run, results, skipped tests, residual gaps, and manual acceptance items

## Guardrails

- Do not treat coverage percentage, snapshot count, test count, or green CI as proof that the material invariant is tested.
- Do not accept tests whose expected value is produced by the implementation under test.
- Do not rely on one broad end-to-end test when a smaller test would expose the failure more directly.
- Do not treat generated tests as trustworthy until their oracle, isolation, and failure signal are reviewed.
- Do not skip, quarantine, or retry away a failing test without preserving the failure and assigning an owner.
- Do not claim verification when required tests were not run, were filtered out, or could not exercise the changed path.
