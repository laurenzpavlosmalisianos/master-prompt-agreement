# Build Pipeline Integrity Practice Guide

Use this Practice Guide when designing, changing, or reviewing CI/CD workflow configuration, build jobs, release jobs, runner trust, workflow permissions, OIDC, secrets, caches, artifacts, provenance, SBOMs, attestations, signatures, or publish handoffs.

Load this guide for pipeline control-plane integrity. Pair it with `shell_cli_coding_quality.md` for script mechanics inside jobs, `dependency_risk.md` for package changes, `container_image_security.md` for image build and registry review, `infrastructure_as_code_review.md` for IaC plans or applies, and `release_readiness.md` for final release or deployment decisions.

Before making provider-specific claims, verify current official documentation for the active CI/CD platform and the project's configured runner, token, artifact, and release mechanisms.

## Workflow

1. Define the pipeline boundary.

- identify provider, workflow files, generated workflow inputs, reusable workflows or includes, protected branches, required checks, environments, review-owner rules, and release or publish jobs
- map trigger events, branch and tag patterns, manual inputs, schedules, dependency events, workflow chaining, and external webhooks
- state runner type, runner labels or groups, base image, workspace persistence, network access, mounted credentials, and cleanup behavior
- identify artifacts, caches, logs, provenance, SBOMs, signatures, and release handoff points

2. Separate trusted and untrusted paths.

- classify pull requests, forked code, issue text, comments, commit messages, branch names, artifacts from other workflows, and external payloads as untrusted unless project evidence proves otherwise
- do not interpolate untrusted event fields directly into shell, generated code, prompts, release notes, or workflow expressions that affect privileged decisions
- avoid privileged triggers that check out or execute untrusted code; if unavoidable, document the exact necessity, owner approval, and containment path
- treat workflow chaining as a trust boundary when a low-privilege workflow can influence a high-privilege workflow through artifacts, caches, names, outputs, or status

3. Review permissions, identity, and secrets.

- set workflow and job permissions to the least privilege needed for each job
- remember that third-party workflow steps and job steps can access available tokens and environment data unless constrained by the platform
- prefer short-lived OIDC federation over long-lived cloud, registry, or package-publishing secrets when the platform and target service support it
- scope secrets to environments, repositories, organizations, or jobs deliberately; keep approvals for protected environments explicit
- prevent CI from approving, merging, or changing protected branches unless the project has a specific owner-approved automation policy

4. Review runner and dependency execution risk.

- pin third-party workflow steps, reusable workflow sources, setup steps, and runner images to immutable references or an approved update policy
- audit the source and permission expectations of workflow steps that execute code or receive tokens
- separate untrusted-code jobs from secret-bearing jobs and publish jobs
- classify runner-managed tool and dependency homes or caches separately from task-owned targets, logs, and temporary output; preserve managed state unless the runner or project contract requires replacement, and isolate or clean only task-owned state
- when the exact dependency graph and required artifacts can be prepared separately, restrict normal network access to explicit preparation and run remaining build and verification phases without network by default; treat any named network-dependent check as a separately scoped exception, record the source and trust basis of reused caches, and claim offline or hermetic execution only when those properties were enforced and verified
- check cache keys, restore scopes, workspace sharing, artifact download paths, and package-manager caches for cross-branch or cross-trust contamination
- avoid exposing container runtime sockets, host mounts, persistent workspaces, or privileged self-hosted runners to untrusted code

5. Review artifacts and provenance.

- bind release candidates to exact source revision, workflow identity, build inputs, runner identity, artifact digest, and immutable storage location
- record the exact build, package, or publish invocation that produced a promoted artifact when the command is not already fixed by reviewed workflow configuration
- generate SBOMs, provenance, attestations, or signatures only for a defined purpose, consumer, and policy; generation may support inventory or analysis even before promotion, but attachment alone is not verification
- before reliance or promotion, validate each artifact by its own contract: SBOM scope, completeness, format, and subject binding; signature identity, trust policy, and subject digest; attestation identity, subject digest, predicate type and content, build/source claims, and policy
- keep test artifacts, diagnostic artifacts, and release artifacts separate
- record retention, redaction, and access rules for logs and artifacts that may contain secrets, personal data, or protected source

6. Verify pipeline behavior.

- run the provider's syntax, policy, or workflow validation where available
- inspect the permission diff, trigger diff, changed reusable workflows, and affected required checks
- test representative trusted and untrusted events where the platform allows it, or document why a safe reproduction is not available
- inspect logs for secret exposure and check that skipped jobs, conditional jobs, and protected-environment gates behaved as intended
- verify artifact digest, attestation, signature, SBOM, and release handoff evidence before claiming supply-chain integrity

## Output

Provide the smallest applicable subset:

1. provider, workflow files, triggers, job graph, runners, branch protections, and environments
2. trusted and untrusted input map, including privileged workflow paths
3. token, permission, secret, OIDC, cache, and runner decisions
4. third-party action and reusable-workflow provenance
5. artifact, SBOM, attestation, signature, and release handoff evidence
6. validation commands, event cases, logs inspected, and residual risks
7. paired guides used for dependencies, scripts, images, IaC, release, or security findings

## Guardrails

- Do not treat green CI as evidence that the pipeline itself is safe.
- Do not grant broad token permissions or secrets to jobs that process untrusted code or untrusted artifacts.
- Do not use mutable workflow-step, workflow, runner-image, or setup-tool references without an explicit update and review policy.
- Do not let untrusted workflow output influence privileged publish, deploy, or approval jobs without a controlled, verified handoff.
- Do not publish a release artifact without an exact digest; apply provenance, signature, attestation, and consumer-side verification requirements from the declared release policy.
- Do not change branch protection, environment protection, release credentials, or publish authority without explicit project approval.
