---
name: mpa-containers
description: "Checks for container images and OCI builds. Use when writing or changing a Dockerfile or Containerfile, BuildKit options, base images, image layers, build secrets, registries, SBOMs, or image signatures. For CI workflows, use mpa-ci-pipeline; for cluster manifests, use mpa-kubernetes."
---

# Container images

- Pipe-to-shell installers, added package repositories, and downloaded archives are supply-chain inputs: pin versions and verify checksums or signatures.
- Use the builder's secret or SSH mount, then confirm the secret is absent from the final image, its history, the build cache, and the logs.
- Inspect the built image's configuration, history, and layers, not only the Containerfile; a clean build does not show what the image contains.
