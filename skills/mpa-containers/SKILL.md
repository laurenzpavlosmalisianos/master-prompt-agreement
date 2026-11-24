---
name: mpa-containers
description: "Checks for container images and OCI builds. Use when writing or changing a Dockerfile or Containerfile, BuildKit options, base images, image layers, build secrets, registries, SBOMs, or image signatures. For CI workflows, use mpa-ci-pipeline; for cluster manifests, use mpa-kubernetes."
---

# Container images

## Build inputs

- Build context files, remote inputs, package repositories, copied scripts, frontend or syntax images, and imported caches are untrusted build inputs.
- Check the ignore file: credentials, `.git`, local state, and caches stay out of the context because anything in it can end up in a layer.
- Record base images by digest; a tag can be repointed and does not identify a release.
- Pipe-to-shell installers, added package repositories, and downloaded archives are supply-chain inputs: pin versions and verify checksums or signatures (`mpa-dependency-change`).
- Builder entitlements (host networking, insecure sandbox mode, device access, host bind mounts) need a stated reason; when used, check the output for host data or credentials.

## Secrets and layers

- A secret passed through a build argument, `ENV`, a label, a copied file, or a `RUN` command persists in image history, layers, cache, or provenance; deleting it in a later layer does not remove it.
- Use the builder's secret or SSH mount, then confirm the secret is absent from the final image, its history, the build cache, and the logs.
- Provenance, SBOMs, debug symbols, source maps, and build logs disclose internal detail; for public images, check what they reveal.

## Final image and distribution

- Inspect the built image's configuration, history, and layers, not only the Containerfile; a clean build does not show what the image contains.
- Local image inspection does not show how it runs; capabilities, seccomp, and admission policy apply at run time (`mpa-kubernetes`).
- Bind deployment references, scan reports, SBOMs, signatures, and approvals to digests, and verify attestations against trust policy (`mpa-ci-pipeline`).
- Registry login, push, retag, and delete take effect outside the repository; retagging silently changes what consumers pull.
