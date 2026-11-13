---
name: mpa-kubernetes
description: Checks for Kubernetes workloads. Use when writing or reviewing manifests, Helm charts, Kustomize overlays, RBAC, NetworkPolicy, or admission configuration, or when running kubectl against a cluster.
---

# Kubernetes

API versions, deprecations, and admission features depend on the cluster version. Where a manifest turns on one of them, check the current official documentation for the target cluster's version.

## Manifests

- Review the rendered YAML that reaches the API server, not only chart values or overlays. Chart and provider defaults are not safe by construction.
- A successful render does not mean the API server, the admission chain, or the controller will accept the resource. An admission denial is a policy to understand, not an obstacle to route around.
- Changes to selectors, labels, namespaces, owner references, and finalizers can silently change rollout, routing, garbage collection, or the scope of a policy. Some selector fields are immutable, and changing them forces recreation.
- Deployment, StatefulSet, DaemonSet, Job, and CronJob roll out, fail, and recover differently. Check the behaviour of the kind in use.
- Reference images by digest for releases, and name the rollback path for rollout, Service, Ingress, Secret, configuration, and storage changes.

## Security and tenancy

- Do not widen RBAC, secret access, host access, or public exposure to make a failure go away. Wildcard verbs or resources, `bind`, `escalate`, impersonation, `cluster-admin`, privileged pods, host namespaces, and hostPath are escalation paths that each need a stated reason.
- Check `securityContext`: `runAsNonRoot`, `allowPrivilegeEscalation`, capabilities, seccomp, read-only root filesystem, and service-account token automount.
- A namespace with no NetworkPolicy allows all traffic, and a NetworkPolicy has an effect only when the cluster's network plugin enforces it. Check both, for ingress and egress.
- A cross-namespace Gateway API reference needs a `ReferenceGrant` in the target namespace. Do not loosen that to make routing work.
- Redact kubeconfig contents, tokens, and cluster identifiers from output.
- For live debugging, use ephemeral debug containers. Do not add shells or tools to production images.

## Stateful and extension resources

- Check the reclaim policy before deleting anything near a PersistentVolume or StatefulSet. With `Delete`, removing the claim destroys the data.
- For CRDs and webhooks, check version conversion, schema pruning, failure policy, timeout, and upgrade order. A failing webhook with policy `Fail` can block the whole cluster. Where the cluster supports it and the rule fits, a CEL validating admission policy avoids a new webhook.
- A stuck finalizer blocks deletion, and forcing it off can orphan external resources.

## Cluster access

- `kubectl apply`, `delete`, `edit`, `scale`, and `rollout restart` change a live cluster, and so does switching context for whatever runs next. Confirm the kubeconfig context and namespace before any command, including read-only ones.
- Say plainly when no server-side validation, policy engine, or cluster access was available.
