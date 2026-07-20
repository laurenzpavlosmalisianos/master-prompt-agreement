# Apple Container Workflow Practice Guide

Use this Practice Guide when a task touches Apple's `container` CLI, Apple Containerization-backed local Linux container workflows, container machines, image build or run commands, registry login or push, mounts, volumes, networks, DNS, ports, SSH, Rosetta, custom kernels, nested virtualization, `container exec`, or host/container command boundaries. Do not load it for generic Docker, Podman, or Kubernetes work unless Apple `container` is the active runtime.

Pair with `container_image_security.md` whenever the task touches Containerfiles, image build context, base images, image layers, remote build inputs, package installs, SBOMs, provenance, signatures, registry push or pull behavior, or image scanning. This guide owns Apple `container` runtime, machine, host-boundary, mount, and lifecycle behavior; `container_image_security.md` owns generic image-build and distribution security.

Before source-sensitive recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check the installed `container` version and the matching Apple `container` release-tag documentation, not only the current main branch. Load release-tag or installed-help documentation for the touched commands first; add targeted Apple Containerization, OCI, tutorial, how-to, or troubleshooting sources only when the active behavior depends on them. Treat macOS support, Apple silicon requirements, CLI flags, networking behavior, builder behavior, and Containerization internals as volatile.

## Workflow

1. Frame the runtime and host contract.

- record host macOS version, hardware architecture, installed `container` version, active machine, system status, project-approved command runner, registry policy, and allowed external effects
- distinguish Apple `container` from Docker-compatible daemons; do not assume a Docker socket, Docker Compose behavior, shared-VM networking, or daemon semantics
- inspect the exact image name, tag, digest, architecture, Containerfile, build context, installed-release ignore behavior, registry host and namespace, and working directory
- identify whether the task is writable development, read-only external review, isolated verification, image build, image publishing, artifact extraction, or production-like rehearsal
- classify `container system start/stop`, machine changes, registry authentication, image push, network changes, and resource deletion as state-changing
- when the container is used as an agent workspace, apply the agent-runtime readiness contract from `prompt_agent_quality.md`, then verify the Apple `container`-specific host boundary, mount profile, guest lifecycle, endpoint publication, log access, and artifact or scratch paths

2. Verify release and documentation alignment.

- prefer release-tag docs for the installed version; use current-branch docs only for exploratory work and mark the mismatch
- check current official Apple `container`, `containerization`, command reference, tutorial, how-to, release, and troubleshooting sources for active CLI behavior
- record unsupported or platform-limited behavior rather than papering over it with Docker assumptions
- when behavior depends on OCI image interoperability, verify image media type, platform, config, registry, and runtime support against the actual tools in use

3. Verify Apple-specific builder and image integration.

- when image build or distribution is in scope, load `container_image_security.md`; it owns build-context, layer, secret, base-image, SBOM, provenance, signature, scan, and registry-distribution rules
- in this guide, verify the installed Apple `container` release's builder behavior, ignore-file semantics, output format, image identity, architecture selection, and runtime interoperability
- for multi-platform images, verify `--arch` output, runtime platform selection, Rosetta assumptions, and target deployment architecture
- distinguish Apple builder or runtime defects from generic Containerfile, OCI image, package, provenance, or registry defects and route the latter to the image-security owner

4. Review run, exec, mount, and network boundaries.

- verify `--env`, host-variable inheritance, `--env-file`, `--ssh`, `--mount`, `--volume`, `--publish`, `--publish-socket`, `--network`, DNS, user and group overrides, capabilities, runtime handler, init image, read-only root filesystem, custom kernel, nested virtualization, and resource flags before running
- mount only necessary host paths, prefer read-only mounts for external review, and verify ownership, permissions, symlinks, and cleanup for host-mounted files
- separate writable development profiles from read-only review profiles; write reviewer reports or generated artifacts to an explicit scratch path or volume, not to a broad host project mount
- verify a claimed read-only host mount with a harmless write-denial check before relying on it for external-review isolation
- pass commands as structured argv through the approved runner; avoid untrusted shell strings inside `container run` or `container exec`
- prove commands ran in the intended container, machine, working directory, architecture, and environment before interpreting output
- treat host environment inheritance, env files, SSH-agent forwarding, capability additions, runtime or init-image changes, port publishing, socket publishing, registry login, image push, custom kernel, nested virtualization, and network or DNS changes as approval-sensitive
- when a tool depends on guest isolation primitives, verify the relevant guest kernel support and record unavailable controls as runtime limitations, not as successful isolation

5. Manage lifecycle and cleanup deliberately.

- inspect running and stopped containers, machines, builder state, images, volumes, networks, and logs before deleting or resetting anything
- verify machine home-mount mode before using or mutating machines; broad or writable home mounts are host-exposure decisions, not harmless defaults
- verify resource limits for memory and CPU on containers and builder VMs when builds or tests are resource-sensitive
- do not delete containers, images, volumes, machines, networks, or builder state merely to make a command pass
- document cleanup actions, persisted volumes, exported artifacts, and host file changes
- if the task uses `container` for framework or project checks, report that the result is local runtime evidence, not proof of downstream production behavior
- keep reusable agent-readiness scripts, setup notes, port inventories, access helpers, and log paths in the project or private integration layer that owns the environment; this guide defines the review contract, not project-local command names

## Output

Provide:

1. sanitized host/runtime facts, `container` version, machine class, image, architecture, registry posture, and release-doc facts used
2. affected build, run, exec, mount, volume, network, port, review-profile, scratch-output, and registry contracts
3. host-boundary, credential, image-provenance, architecture, guest-isolation, and lifecycle risks
4. `container` status, inspect, build, run, exec, log, stats, registry, mount-permission, guest-sandbox, and cleanup checks run
5. agent-readiness contract when a container is used as an agent workspace, including preflight, resume, ports, logs, artifacts, and access-helper boundaries
6. unverified host, release, registry, network, image, and deployment states plus residual risk

## Guardrails

- Do not assume Docker daemon, Docker Compose, or shared-VM semantics when the active runtime is Apple `container`.
- Do not run registry login, image push, system start/stop, machine mutation, network mutation, custom-kernel, nested-virtualization, host-home exposure, or destructive cleanup commands without approval.
- Do not rely on registry `auto` transport for sensitive credentials or pushes without verifying host, namespace, scheme, and credential scope.
- Do not mount broad host directories, secrets, or project-private state unless the task requires it and the boundary is explicit.
- Do not run unattended or external reviewer lanes on a broad writable host-project mount.
- Do not encode project-local container names, host paths, non-production access-helper details, service names, package managers, or product-specific setup commands into public framework doctrine; keep them in the owning project or private integration layer.
- Do not report host/container evidence with hostnames, usernames, personal machine names, absolute host paths, registry account names, local mount paths, serial or device identifiers, or private project paths unless the SOW explicitly approves recording them; prefer repo-relative paths and stable labels.
- Do not claim production parity from a local Apple `container` run without separate target-runtime evidence.
- Do not use current-branch documentation as proof of installed-release behavior without recording the version mismatch.
