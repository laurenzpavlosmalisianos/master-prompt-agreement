# Container Image Security Practice Guide

Use this Practice Guide when a task touches Containerfiles, OCI images, base images, image build context, image tags or digests, image layers, package installs inside images, build secrets, image metadata, SBOMs, provenance attestations, signatures, registry push or pull behavior, or container image scanning. It owns generic image build and distribution security for Docker, Podman, BuildKit, OCI-compatible builders, and registries.

Pair it with `apple_container_workflow.md` when Apple `container` is the active runtime, `kubernetes_workload_review.md` for Kubernetes manifests and workload policy, `dependency_risk.md` for dependency acceptance outside image context, `secure_development.md` for implementation hardening, `security_audit.md` for adversarial findings, and `release_readiness.md` when an image becomes a release artifact.

Before source-sensitive recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check the smallest credible official source set for the selected builder, runtime, registry, base image, package manager, OCI artifact behavior, SBOM format, provenance format, signature mechanism, and scanner policy.

## Workflow

1. Define the image and build boundary.

- Name the build tool, runtime, Containerfile path, build context, build target, platforms, architecture set, registry, image name, tag, digest, namespace, and release channel.
- Record builder driver and daemon posture, frontend or syntax image, build network mode, named build contexts, `RUN --mount` uses, cache import/export references, and any privileged build entitlements such as host networking, insecure sandbox mode, or device access.
- Distinguish source files, build context, intermediate stages, local image, pushed image, manifest list, signature, SBOM, provenance attestation, and deployment reference.
- Record base images, package managers, copied artifacts, generated files, labels, entrypoint, command, exposed ports, volumes, healthcheck, default environment, runtime user, and required writable paths.
- Treat build context files, remote build inputs, package repositories, registry metadata, copied scripts, generated artifacts, and scanner output as untrusted until verified.

2. Control build context and inputs.

- Keep the build context minimal and explicit; review `.dockerignore` or equivalent behavior before building.
- Treat named contexts, bind mounts, cache mounts, remote cache imports, frontend images, and builder entitlements as build inputs; allow host networking, insecure build sandbox, device access, or host bind access only when explicitly justified and when outputs are checked for host-data or credential leakage.
- Exclude credentials, tokens, `.git`, local state, private notes, package caches, test data, temporary files, host-specific paths, and unrelated large directories unless the task proves they are required.
- Pin or record base image name, version, digest, platform, publisher, update strategy, and support status; do not use a floating tag as release identity.
- Prefer multi-stage builds so compilers, package managers, test fixtures, caches, and build-only tools do not reach the final image.
- Use `COPY` for local files when possible. Use remote `ADD` only when the source, checksum, provenance, and extraction behavior are deliberately reviewed.
- Treat remote bootstrap scripts, global tool installs, package-repository additions, and manually downloaded release archives as supply-chain inputs; prefer managed packages when adequate, or verify checksums/signatures and pinned versions when manual install is required.

3. Prevent secret and layer leakage.

- Do not pass secrets through build args, environment variables, labels, tags, copied files, command strings, package config, generated logs, or cacheable layers.
- Use the builder's approved secret or SSH mount mechanism when a build truly needs a credential, and verify the secret does not remain in the final image, build cache, history, logs, or provenance mode.
- Review image history, layer contents, labels, environment defaults, package manager configuration, shell profiles, and generated artifacts for hidden secrets or internal host data.
- Treat provenance, SBOM, debug symbols, source maps, build logs, and scanner reports as possible disclosure surfaces.

4. Review final image behavior.

- Verify the final image contains only runtime files needed by the workload and excludes build tools, package caches, credentials, test fixtures, private source state, and unnecessary shells or interpreters.
- Prefer a non-root runtime user where the workload allows it; record any root requirement and the compensating runtime controls.
- Review entrypoint and command behavior for shell injection, signal handling, working directory, privilege escalation, writable paths, and implicit network listeners.
- Check exposed ports, volumes, default environment, healthcheck, labels, architecture support, filesystem mutability, file permissions, file capabilities, and any runtime privileges the image appears to require; record runtime assumptions, but defer granting or approving capabilities, privileged mode, seccomp, AppArmor, SELinux, Kubernetes policy, or Apple `container` behavior to the paired runtime or deployment guide.
- Do not infer Kubernetes, production, or Apple `container` runtime safety from local image inspection alone.

5. Verify registry, SBOM, provenance, and release identity.

- Verify registry host, namespace, authentication scope, repository ownership, tag mutability, promotion path, retention, access controls, and digest used by consumers.
- Generate or verify SBOM, provenance, and signatures when release, compliance, or security posture depends on the image.
- Treat attestations as evidence, not approval: verify signer, builder identity, source revision, build type, build parameters, materials, base-image digests, resolved dependencies, platform, and artifact digest.
- Use minimal provenance when public release should avoid exposing build arguments or internal details; use richer provenance only when the disclosure boundary is approved.
- Bind release notes, deployment references, scanner reports, SBOMs, provenance, signatures, and approvals to immutable image digests.

6. Verify before publishing or relying on the image.

- Build with explicit context, target, platform, and tag; inspect the resulting image config, history, layers, manifest, and digest.
- Run configured image vulnerability, secret, malware, license, and policy scans; classify findings before treating tool output as a defect or gate.
- Run a smoke or security check in the approved runtime when behavior depends on entrypoint, user, ports, file permissions, or writable paths.
- State which base images, packages, layers, registries, signatures, SBOMs, provenance attestations, scanners, and runtime assumptions were verified, deferred, or unavailable.

## Output

Provide:

1. image source, build context, builder, runtime, base images, platforms, registry, tag, digest, and release identity
2. build-context exclusions, base-image decisions, package installs, copied artifacts, and multi-stage boundary
3. secret-handling path, layer/history inspection, final-image contents, runtime user, entrypoint, ports, writable paths, file permissions, file capabilities, and runtime privilege assumptions to be handled by paired runtime or deployment guides
4. registry trust, SBOM, provenance, signature, scanner, and immutable-digest evidence
5. remote-registry mutation approvals needed, image verification commands run, unavailable evidence, residual image-build or image-distribution risks, and paired guides used

## Guardrails

- Do not treat a clean Containerfile, successful build, or green scanner as proof that the built image is safe.
- Do not pass secrets through build args, environment variables, labels, copied files, command strings, remote bootstrap scripts, or cacheable layers.
- Do not use floating tags as release identity when a digest, provenance record, or deployment pin is required.
- Do not push, publish, delete, retag, log in to registries, or mutate remote image state without current approval.
- Do not assume local container behavior proves Kubernetes, production, or Apple `container` runtime behavior.
- Do not hide build, base-image, registry, scanner, SBOM, provenance, or signature uncertainty behind words like `latest`, `official`, or `clean`.
