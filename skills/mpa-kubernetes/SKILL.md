---
name: mpa-kubernetes
description: "Kubernetes and Gateway API release changes through Kubernetes 1.37 and Gateway API v1.7 and checks that are easy to miss. Use for any work on manifests, Helm charts, Kustomize overlays, RBAC, NetworkPolicy, Gateway API, or a cluster upgrade."
---

# Kubernetes

Current to Kubernetes 1.37.3 and Gateway API v1.7.0, checked 2026-11-27. For a newer release of either, read what changed after it in the release notes (https://kubernetes.io/releases/, https://github.com/kubernetes-sigs/gateway-api/releases) before relying on this file; up to those versions no lookup is needed.

## Manifests

- A successful render does not mean the API server, admission chain, or controller will accept the resource. An admission denial is a policy to understand, not an obstacle to route around.
- Reference release images by digest and name the rollback path for rollout, Service, Ingress, Secret, configuration, and storage changes.

## Security and tenancy

- Check `securityContext` settings (`runAsNonRoot`, `allowPrivilegeEscalation: false`, dropped capabilities, `seccompProfile`, `readOnlyRootFilesystem`) and set `automountServiceAccountToken: false` on the PodSpec or ServiceAccount when API access is unneeded.
- A cross-namespace Gateway API reference needs a `ReferenceGrant` in the target namespace, except attachment to a Gateway, which the listener's `allowedRoutes` (or, for a ListenerSet in Gateway API 1.5+, the Gateway's `allowedListeners`) controls; do not loosen either to make routing work.
- For live debugging, use ephemeral debug containers; do not add shells or tools to production images.

## Cluster access

- Say plainly when no server-side validation, policy engine, or cluster access was available.

## Release changes, newest first

- 1.37: on nodes with SELinux, a volume whose CSIDriver sets `seLinuxMount: true` is mounted with the Pod's label and is no longer relabelled file by file, so two Pods with different labels cannot share it on one node and the second fails to start. `securityContext.seLinuxChangePolicy: Recursive` on the Pod keeps the old behaviour.
- 1.37: a static Pod that references a Secret, a ConfigMap, or another API object is refused; the kubelet has denied these since 1.34 and the opt-out is gone. kube-proxy warns when `mode` is unset, because the default is to move from `iptables` to `nftables`; `ipvs` mode is deprecated since 1.35 and planned for removal in 1.40. Admission webhooks no longer receive TokenReview and access review requests by default. `kubectl run -f` and kube-dns are deprecated. kubeadm no longer reads its `v1beta3` configuration; convert to `v1beta4` with `kubeadm config migrate` from an earlier release before the upgrade.
- 1.36: Service `spec.externalIPs` is deprecated and returns a warning; kube-proxy support is to go off by default in 1.40 at the earliest and for good in 1.43 at the earliest. Use a LoadBalancer or NodePort Service or Gateway API. `gitRepo` volumes no longer run (off by default since 1.33); fetch with an init container. The API server rejects an IP or CIDR value with leading zeros or with host bits set, such as `192.0.2.5/24`. Stable from this release: user namespaces (`hostUsers: false`), image volumes, and MutatingAdmissionPolicy in `admissionregistration.k8s.io/v1`. For user namespaces, from 1.37.3, 1.36.7, and 1.35.11 the kubelet refuses to start when the subordinate ID range of the `kubelet` user in `/etc/subuid` or `/etc/subgid` reaches 4294967295, or while a Pod on the node still holds a range that does.
- Ingress NGINX, the `ingress-nginx` controller, was retired on 2026-03-24 and gets no further fixes, security fixes included. Build nothing new on it; move to Gateway API (`ingress2gateway` converts Ingress resources) or to a maintained Ingress controller.
- 1.35: the kubelet does not start on a cgroup v1 node unless `failCgroupV1: false` is set. It also checks pull credentials for an image that is already on the node: a Pod that uses a private image pulled for another Pod needs credentials of its own, with `imagePullPolicy: IfNotPresent` or `Never` as well; images loaded onto the node outside the kubelet are exempt by default. CPU and memory of a running Pod can be changed through its `resize` subresource. The kubelet flag `--pod-infra-container-image` is removed, and a kubelet that still gets it does not start.
- 1.34: Service `trafficDistribution: PreferClose` is deprecated; `PreferSameZone` means the same, and `PreferSameNode` is new. A Pod that sets `host` in a probe or a lifecycle handler no longer meets the Restricted Pod Security standard. Dynamic Resource Allocation is stable in `resource.k8s.io/v1`.
- 1.33: the `v1` Endpoints API is deprecated and warns on every read and write; use EndpointSlices. The annotation `service.kubernetes.io/topology-mode` is deprecated in favour of `trafficDistribution`. Sidecars are stable as init containers with `restartPolicy: Always`.
- No beta or stable API version stops being served in 1.33 to 1.37; alpha versions do.
- Gateway API 1.7: HTTPRoute `retry` (`codes`, `attempts`, `backoff`) is in the Standard channel; `attempts` defaults to 1, and 0 turns retries off. Rule names must be unique within an HTTPRoute or GRPCRoute.
- Gateway API 1.6: TCPRoute and UDPRoute are `v1`, and their `v1alpha2` versions are deprecated. The CORS filter is in the Standard channel. A ValidatingAdmissionPolicy in the release refuses experimental CRDs on top of Standard ones and an older release on top of a newer one.
