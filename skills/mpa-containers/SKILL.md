---
name: mpa-containers
description: Checks for container images. Use when writing or changing a Dockerfile or Containerfile, base images, build secrets, registries, SBOMs, or image signatures.
---

# Container images

## Build inputs

- Build context files, remote inputs, package repositories, copied scripts, frontend or syntax images, and imported caches are untrusted build inputs.
- Check the ignore file. Credentials, `.git`, local state, and caches stay out of the context, because anything in the context can end up in a layer.
- Record base images by digest. A tag can be repointed, so it does not identify a release.
- Pipe-to-shell installers, added package repositories, and downloaded archives are supply-chain inputs. Pin versions and verify checksums or signatures.
- Builder entitlements such as host networking, insecure sandbox mode, device access, and host bind mounts need a stated reason. When they are in effect, check the output for host data or credentials.

## Secrets and layers

- A secret passed through a build argument, `ENV`, a label, a copied file, or a `RUN` command string persists in image history, layers, cache, or provenance. Deleting it in a later layer does not remove it.
- Use the builder's secret or SSH mount. Then confirm the secret is absent from the final image, its history, the build cache, and the logs.
- Provenance, SBOMs, debug symbols, source maps, and build logs disclose internal detail. For public images, check what they reveal.

## Final image and distribution

- Inspect the built image's configuration, history, and layers, not only the Containerfile. A clean build does not show what the image contains.
- Inspecting an image locally does not show how it runs. Capabilities, seccomp, and admission policy are set at run time; see the `mpa-kubernetes` skill.
- An attestation is evidence, not approval. Verify the signer, builder identity, source revision, and subject digest.
- Bind deployment references, scan reports, SBOMs, signatures, and approvals to digests.
- Registry login, push, retag, and delete take effect outside the repository. A retag silently changes what consumers pull.
