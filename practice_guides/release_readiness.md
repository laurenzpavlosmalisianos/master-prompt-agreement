# Release Readiness Practice Guide

Use this Practice Guide before release, deployment, or merge of high-impact work. It checks rollout, rollback, operational, and verification gaps that ordinary code review may not cover.

## Workflow

1. Bind the exact release candidate.
- commit, tag, artifact digest, package version, or generated bundle
- target environment, configuration, migration sequence, and deployment sequence
- evidence cutoff time and required checks

2. Check user-visible change scope.
- behavior changes
- migration or config changes
- dependency or infrastructure changes
- documentation changes

3. Check release blockers.
- failing required checks
- warnings that project policy marks as release-blocking
- warnings that invalidate required evidence
- required validators, release gates, or generated-artifact checks that validate only shape, counts, parsing, or stale scratch artifacts instead of the declared product-surface invariant
- unresolved supply-chain or source-trust blockers: unexpected lockfile or package-source changes, unverified artifact provenance, missing required SBOM or attestation evidence, unresolved dependency advisories, unreviewed generated, retrieved, or third-party content, or unmet license or attribution obligations
- blockers that prevent meaningful security, fuzzing, property-based, sanitizer, or coverage checks from running on high-risk input surfaces
- missing required native-artifact or updater evidence under the applicable `secure_development.md` profile; build flags or signatures alone do not satisfy that profile
- unapproved or undocumented compatibility breaks
- missing env vars, secrets handling, rollback, or containment path
- stale docs, changelog, or runbooks for user-facing or operational changes
- for public developer tools, missing or stale tested-platform support, unsupported-path notes, setup prerequisites, verification commands, data-flow or architecture notes where material, license and security-reporting surfaces, or cleanup guidance

4. Check operational readiness.
- rollout entry criteria
- feature flags, staged rollout, abort threshold, and recovery action
- owner and escalation path
- observability, logging, alerting, monitoring, or runbook changes when needed
- coverage, replay, minimized reproducer, or regression-range evidence when fuzzing or dynamic security testing is part of the profile

5. Check deployment sequencing.
- order of services, jobs, migrations, cache invalidation, background work, artifact generation, or asset rebuilds
- stop condition and owner for each irreversible or hard-to-reverse step

6. Produce the release assessment.
- Technical readiness: `ready | blocked`
- Authorization: `granted | pending | not applicable`

Pending approval does not change technical evidence. A release cannot proceed unless required authorization is granted.

## Output

Provide:

1. exact release candidate and evidence cutoff
2. technical readiness
3. authorization state and required owner decisions
4. blockers
5. rollout entry criteria, abort threshold, recovery action, and owner
6. rollback or containment notes
7. follow-up actions

## Guardrails

- Do not let a green test run hide rollout risk.
- Do not ignore docs drift for user-facing or operational changes.
- Do not mark a release technically ready without a rollback or containment story.
- Do not downgrade test blockers as harmless when they prevent verification of parsers, protocols, deserializers, upload paths, IPC, templating, or other untrusted-input-heavy surfaces.
- Do not treat a release recommendation as authorization to merge, deploy, publish, or release.
- Do not let optional post-release follow-up masquerade as a pre-release condition.
