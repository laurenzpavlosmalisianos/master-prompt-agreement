# Kubernetes Workload Review Practice Guide

Use this Practice Guide when a task touches Kubernetes manifests, Helm or Kustomize output, GitOps resources, RBAC, namespaces, service accounts, Secrets, ConfigMaps, NetworkPolicies, workloads, Services, Ingress, Gateway API resources, CRDs, admission webhooks, storage resources, rollout behavior, or cluster-facing verification. Pair it with `platform_architecture_review.md` when choosing architecture or providers, `data_systems_review.md` for stateful data behavior, `container_image_security.md` for image build, provenance, registry, SBOM, and scanning concerns, and `security_audit.md` for adversarial findings. Kubernetes owns deployment references and runtime policy.

Before source-sensitive Kubernetes recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check current official Kubernetes docs, release and version-skew policy, API reference, and provider-specific docs for the actual target cluster. When security, tenancy, admission, image, or advisory posture is in scope, also check current security docs, Pod Security Standards, RBAC guidance, CVE feed, and provider security docs. Treat Kubernetes minor versions, managed-provider behavior, admission policies, CRDs, controllers, and security defaults as volatile.

## Workflow

1. Frame the cluster and manifest contract.

- identify target cluster, provider, Kubernetes minor version, namespace, kubeconfig context, deployment mechanism, GitOps owner, admission controllers, policy engines, and resource ownership
- distinguish source manifests from rendered output; inspect the exact YAML that will reach the API server before making cluster-facing claims
- identify workload type, selectors, labels, service-account identity, secrets, network paths, storage, autoscaling, disruption, rollout, and backout behavior
- verify CRD, webhook, Helm chart, Kustomize, Gateway, Ingress, CNI, CSI, and cloud-controller assumptions against the installed or declared versions
- do not apply generic Kubernetes advice over project pins, provider constraints, or inspected cluster capabilities

2. Validate API, schema, and version assumptions.

- check API groups and versions against the target cluster and deprecation window
- use server-side dry run, `kubectl diff`, schema validation, or the project-approved equivalent when cluster access and approval allow it
- keep namespace, selector, owner reference, finalizer, and label changes explicit because they can silently change rollout, garbage collection, routing, or policy behavior
- for generated manifests, verify the generator inputs and rendered output; do not trust chart defaults or overlays without inspecting the result
- treat admission denial, policy warnings, and server-side defaulting as evidence that must be classified before editing

3. Review workload reliability and operations.

- verify requests, limits, namespace `ResourceQuota` and `LimitRange`, probes, startup order, graceful termination, disruption budgets, autoscaling, node selection, topology spread, affinity, tolerations, and priority where relevant
- check Deployment, StatefulSet, DaemonSet, Job, and CronJob semantics instead of assuming all workload controllers roll out or recover the same way
- verify image references, tags, digests, pull policy, imagePullSecrets, registry-auth exposure, registry trust, provenance, and architecture support
- define rollback or containment for rollout, selector, service, ingress, secret, config, and persistent-storage changes
- verify observability signals such as events, logs, readiness, metrics, and alert conditions for the changed surface

4. Review security and tenancy boundaries.

- map identities, service accounts, Roles, ClusterRoles, bindings, impersonation, admission permissions, and namespace boundaries
- avoid broad `cluster-admin`, wildcard resources or verbs, `bind`, `escalate`, impersonation, privileged workloads, host namespace access, hostPath, unrestricted capabilities, and broad secret reads unless an explicit project requirement and approval justify them
- apply the project's Pod Security Standards or stronger local policy; check `securityContext`, seccomp, AppArmor or SELinux, capabilities, `allowPrivilegeEscalation`, privileged mode, `runAsNonRoot`, read-only root filesystems, and service-account token mounting
- verify NetworkPolicy ingress and egress posture, DNS assumptions, service exposure, load balancer, ingress, and gateway boundaries
- review Secrets handling, encryption, external-secret controllers, secret projection, environment-variable exposure, and log leakage

5. Review stateful and extension behavior.

- for PersistentVolumes, StorageClasses, StatefulSets, snapshots, and backups, verify reclaim policy, expansion, access mode, data migration, restore path, and zone or topology constraints
- for CRDs and admission webhooks, verify version conversion, schema pruning, webhook availability, failure policy, timeout, side effects, and upgrade or rollback behavior
- for operators and controllers, verify reconciliation authority, finalizers, drift behavior, and permissions
- route data consistency, backup/restore, and replication design through `data_systems_review.md` when the state model changes

6. Verify with project-approved tools.

- run local render, lint, policy, schema, and unit checks configured by the project
- run cluster dry-run, diff, `kubectl auth can-i`, rollout status, event inspection, and smoke checks only when the project contract and approvals allow cluster access
- test failure paths that the change affects: probe failure, image pull failure, denied policy, unavailable dependency, failed rollout, stuck finalizer, denied network path, and rollback
- state clearly when cluster access, server-side validation, provider state, or policy engine results were not available

## Output

Provide:

1. Kubernetes target, version, provider, namespace, renderer, and official source facts used
2. affected API, workload, identity, network, secret, storage, and rollout contracts
3. RBAC, Pod Security, admission, network, secret, CRD, and provider risks
4. render, schema, policy, dry-run, diff, auth, rollout, and smoke checks run
5. unverified cluster, provider, version, policy, and runtime states plus residual risk

## Guardrails

- Do not run `kubectl apply`, delete resources, change contexts, switch namespaces, or touch live clusters without current approval.
- Do not treat a successful YAML render as proof that the API server, admission chain, or controller will accept the resource.
- Do not treat chart or provider defaults as safe without inspecting the rendered and applied behavior.
- Do not widen RBAC, host access, secret access, or public exposure as a convenience fix.
- Do not claim production readiness without rollout, rollback, observability, and policy evidence for the target cluster.
- Do not expose kubeconfig contents, tokens, Secret values, private registry credentials, internal hostnames, cluster IDs, account IDs, or private manifest excerpts in public outputs; redact or summarize them unless the project explicitly authorizes disclosure.
