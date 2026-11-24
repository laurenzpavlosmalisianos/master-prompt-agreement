---
name: mpa-kubernetes
description: "Checks for Kubernetes workloads and cluster changes. Use when writing or reviewing manifests, Helm charts, Kustomize overlays, RBAC, NetworkPolicy, CRDs, webhooks, PVCs, Gateway API, or admission config, or running kubectl."
---

# Kubernetes

API versions, deprecations, and admission features depend on the cluster version. Where a manifest turns on one of them, check the current official documentation for the target cluster's version.

## Manifests

- Review the rendered YAML that reaches the API server, not only chart values or overlays. Chart and provider defaults are not safe by construction.
- A successful render does not mean the API server, admission chain, or controller will accept the resource. An admission denial is a policy to understand, not an obstacle to route around.
- Changes to selectors, labels, namespaces, owner references, and finalizers can silently change rollout, routing, garbage collection, or policy scope; immutable selector changes force recreation.
- Deployment, StatefulSet, DaemonSet, Job, and CronJob roll out, fail, and recover differently; check the behaviour of the kind in use.
- Reference release images by digest (`mpa-containers`) and name the rollback path for rollout, Service, Ingress, Secret, configuration, and storage changes (`mpa-release`).

## Security and tenancy

- Do not widen RBAC, secret access, host access, or public exposure to make a failure go away. Wildcard verbs or resources, `bind`, `escalate`, impersonation, `cluster-admin`, privileged pods, host namespaces, and `hostPath` are escalation paths that each need a stated reason.
- Check `securityContext` settings (`runAsNonRoot`, `allowPrivilegeEscalation: false`, dropped capabilities, `seccompProfile`, `readOnlyRootFilesystem`) and set `automountServiceAccountToken: false` on the PodSpec or ServiceAccount when API access is unneeded.
- A namespace with no NetworkPolicy allows all traffic, and a NetworkPolicy has an effect only when the cluster's network plugin enforces it. Check both, for ingress and egress.
- A cross-namespace Gateway API reference needs a `ReferenceGrant` in the target namespace; do not loosen it to make routing work.
- For live debugging, use ephemeral debug containers; do not add shells or tools to production images.

## Stateful and extension resources

- Check the reclaim policy before deleting anything near a PersistentVolume or StatefulSet; with `Delete`, removing the claim destroys the data.
- For CRDs and webhooks, check version conversion, schema pruning, failure policy, timeout, and upgrade order; a failing webhook with policy `Fail` can block the whole cluster. Where the cluster supports it and the rule fits, prefer a CEL admission policy over a new webhook.
- A stuck finalizer blocks deletion, and forcing it off can orphan external resources.

## Cluster access

- `kubectl apply`, `delete`, `edit`, `scale`, and `rollout restart` change a live cluster, and switching context changes what runs next. Confirm the kubeconfig context and namespace before any command, including read-only ones, and redact kubeconfig contents, tokens, and cluster identifiers (`mpa-data-privacy`).
- Say plainly when no server-side validation, policy engine, or cluster access was available.
