# Infrastructure As Code Review Practice Guide

Use this Practice Guide when a task touches infrastructure-as-code source, generated or transformed output, providers, modules, stack state, plan files, previews, diff artifacts, drift detection, policy-as-code results, direct provider actions, lifecycle or ownership-transfer rules, apply-time code hooks, import or move operations, workspace/account targeting, or infrastructure apply/deploy gates. It owns IaC source and execution-review semantics: what the code says, what the tool plans, what state records, and what approval is required before changing infrastructure.

Pair it with `platform_architecture_review.md` when choosing platform design, `kubernetes_workload_review.md` for Kubernetes manifests and cluster behavior, `migration_safety.md` for external-state or data migrations, `release_readiness.md` for deploy readiness, `secure_development.md` and `security_audit.md` for vulnerability work, `dependency_risk.md` for package dependencies outside IaC provider/module semantics, and `data_systems_review.md` for data-store design and recovery.

Before source-sensitive recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check the smallest credible official source set for the selected IaC tool, provider, cloud, backend, policy engine, module registry, deployment mode, and target environment.

## Workflow

1. Define the IaC target and authority boundary.

- Name the tool, version, provider set, module set, backend, state location, lock behavior, stack or workspace, account, subscription, project, tenant, region, environment, and deployment identity.
- Distinguish authored source, generated or synthesized output, variable files, parameter files, secrets files, state, saved plans, previews, diff artifacts, policy results, and apply/deploy commands.
- Identify who owns the resources, who can approve changes, and the actual effects of format, render, synthesize, transform, validate, plan, refresh, preview, diff, policy, cost, apply, and deploy commands. A command called `plan`, `preview`, or `synth` is not presumed read-only.
- Treat any path that accesses credentials or live backends, contacts providers, refreshes or locks state, runs data sources, macros, transforms, hooks, or project code, writes sensitive artifacts, incurs cost, or mutates infrastructure as approval-sensitive according to its actual effects. Apply, deploy, direct provider actions, generated-output fast paths, import, move, remove/forget, state edit, refresh-only update, destroy, replacement, backend migration, drift remediation, and permission expansion remain state-changing.

2. Inspect source, generated output, and dependencies.

- Inspect the exact source files and generated artifacts the tool will evaluate; do not rely on high-level module names or summaries.
- Verify provider and module sources, version constraints, lock files, checksums, registry host, mirrors, plugin caches, and upgrade intent.
- Review variables, locals, parameters, outputs, stack configuration, environment variables, and defaults for hidden environment coupling.
- Review lifecycle, protection, retention, and ownership-transfer semantics that alter apply behavior. Classify whether they invoke provider side effects, hide drift, block deletion, force ordering, force replacement, retain orphaned resources, or transfer ownership outside the stack.
- For generated or synthesized IaC, review generated templates, manifests, plans, or preview output in addition to the source-language code.
- For template transforms, macros, includes, serverless expansions, or other pre-deployment expansion systems, review the processed output, transform ownership/source, execution identity, parameters, packaged artifacts, and generated resources; do not treat the authored source alone as the evaluated source.
- For apply-time code hooks, identify hook type, create/update/delete/destroy trigger phase, execution identity and location, source or package provenance, inputs, outputs, logs, timeout/retry behavior, and resources it can mutate. Route implementation-level shell or application-code review to paired guides, but keep side-effect classification and approval here.
- Record any provider, module, or cloud API behavior that depends on volatile current documentation.

3. Protect state, plans, secrets, and outputs.

- Treat state files, saved plans, previews, stack exports, drift reports, and deployment history as sensitive artifacts because they can contain resource attributes, generated values, identifiers, and secrets.
- Prefer remote state or managed backends with encryption, access control, audit logging, locking, and least-privilege access when state is shared or sensitive.
- Do not commit state, saved plans, local backend files, credentials, tool metadata directories, stack secret stores, parameter files with secrets, generated keys, or decrypted outputs.
- Use tool-native secret, sensitive, ephemeral, write-only, dynamic reference, or secure-parameter mechanisms where available; verify their limitations rather than assuming they remove all disclosure.
- Review outputs and logs for resource IDs, credentials, connection strings, keys, account identifiers, tenant identifiers, and deployment history leakage.

4. Review plan, preview, or diff evidence.

- Prefer an existing source-bound plan, preview, diff artifact, or synthesized output when available. Before producing new evidence, inspect the complete execution chain, backend, providers, data sources, macros, transforms, hooks, credentials, network, state-lock/write behavior, output location, and project code. Run it only when those effects are authorized and bounded. Otherwise use static source or existing-artifact inspection and report the missing live evidence.
- Classify creates, updates, replacements, deletions, imports, moves, remove/forget operations, refresh-only changes, direct provider actions, apply-time hook side effects, ignored resources, retained or orphaned resources, unknown values, permission changes, network exposure, public access, encryption changes, tag changes, and generated-name changes.
- Pay special attention to destroy modes, complete deployment modes, targeted or forced replacement modes, auto-approval, disabled locking, forced unlocks, drift reconciliation, and provider actions that bypass ordinary CRUD.
- Remember that preview evidence is not proof of successful deployment; runtime conditions, quotas, eventual consistency, custom resources, provider bugs, and policy or admission checks can still fail.
- Compare plan evidence against the intended scope and reject unrelated drift, accidental provider upgrades, workspace mistakes, or account/region mismatches.
- For known or suspected drift, require an explicit ordinary-versus-drift-aware plan decision; classify drift-aware remediation as a live-state overwrite that needs owner approval, not a routine update.
- For transformed or macro-expanded deployments, classify whether the reviewed evidence comes from processed output and whether any direct-expansion mode bypasses ordinary plan or preview review; require explicit owner approval and substitute processed-output evidence when ordinary review evidence is unavailable.

5. Review security, policy, and blast radius.

- Map changed identities, roles, policies, service accounts, trust relationships, network paths, public endpoints, encryption settings, logging, data retention, backups, and destructive privileges.
- Run configured format, validate, lint, policy-as-code, cost, security, and cloud-specific checks; classify their findings before using them as gates.
- Verify least privilege for the deployment identity and for resources created by the IaC; do not accept broad admin permissions because the tool can create them.
- Check blast radius for shared modules, cross-stack references, remote state data sources, exported values, global names, DNS, certificates, IAM resources, databases, queues, buckets, and multi-account or multi-region stacks.
- Identify rollback, remediation, import, or manual repair path before approving destructive or replacement operations.

6. Verify apply/deploy readiness.

- Confirm the reviewed plan, preview, or diff artifact is tied to the same source revision, variables, backend, workspace, account, region, and provider selections that will be applied.
- Require explicit approval before infrastructure-mutating commands, especially when saved plans are treated as approval tokens by the tool.
- Verify state locking, drift status, concurrent run controls, credentials, quotas, policy results, and deployment windows before apply/deploy.
- After approved apply/deploy, compare control-plane operation status, resource or stack events, actual outputs, state, and drift status against the reviewed plan and rollback or repair expectations; route application service health and release validation to the paired readiness or platform guide.

## Output

Provide:

1. IaC tool, version, backend, state location, workspace/account/region, providers, modules, and authority boundary
2. source files, generated artifacts, variables, secrets, state, plan/preview/diff evidence, and dependency-lock facts
3. create/update/replace/delete/import/move/drift/permission/public-exposure blast-radius classification
4. validation, lint, policy, cost, security, drift, lock, and provider checks run
5. apply/deploy approvals needed, residual risks, unavailable evidence, rollback or repair path, and paired guides used

## Guardrails

- Do not run apply, deploy, destroy, import, move, remove/forget, state edit, forced unlock, backend migration, or privileged cloud commands without current approval.
- Do not run render, synthesize, transform, validate, plan, refresh, preview, diff, policy, or cost commands merely because their names sound read-only; classify and authorize their real credential, network, state, code-execution, artifact-write, and cost effects first.
- Do not use generated-output fast paths, direct provider actions, transformed-output expansion, drift remediation, or shortcut deploy modes as convenience paths around plan, preview, diff, or processed-output review.
- Do not approve apply-time code hooks without explicit owner approval, execution-identity and provenance review, and classification of side effects not represented in managed state or preview evidence.
- Do not treat green lint, validate, plan, preview, or diff output as proof that deployment is safe or will succeed.
- Do not store state, saved plans, decrypted secrets, generated keys, or sensitive outputs in source control or public artifacts.
- Do not use auto-approval, disabled locking, targeted apply, forced replacement, destroy mode, complete mode, or broad admin deployment identity as convenience fixes.
- Do not trust module names, generated code, provider defaults, or cloud console summaries without inspecting the exact source, generated output, state context, and plan evidence.
- Do not resolve drift by overwriting live infrastructure until the owner confirms whether the live state or the IaC source is authoritative.
- Do not remove resources from state, retain or orphan resources, or rely on lifecycle/protection settings to make a plan look safe unless ownership transfer, decommissioning, and follow-up management are explicitly approved and documented.
