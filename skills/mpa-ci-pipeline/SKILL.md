---
name: mpa-ci-pipeline
description: "Checks for CI/CD pipelines. Use when changing workflow files, triggers, token permissions, runners, OIDC trust, caches, artifacts, or release and publish jobs. For release sign-off, use mpa-release; for image builds, use mpa-containers."
---

# CI/CD pipeline

Default token permissions, trigger semantics, OIDC claims, and cache isolation differ by platform. Where a decision turns on one of them, check the platform's current official documentation.

## Untrusted input

- Chained workflows are a trust boundary: a low-privilege workflow can influence a privileged one through artifacts, caches, outputs, names, and status.

## Identity and pinning

- Set the workflow token to read-only at the top level and grant write scopes per job; do not rely on the platform default. Every step in a job can read every token and secret that job has.
- Prefer short-lived OIDC federation to stored cloud, registry, or publishing secrets. When several trust configurations match one publishing identity, each grants on its own; they do not narrow one another.
- Anyone who can edit a workflow file can exfiltrate every secret it reaches. Protect workflow files with required review.
- Pin third-party actions, reusable workflows, setup tools, and runner images to a commit or digest; a tag can move. A commit pin does not cover the actions, images, or downloads the pinned action pulls in.
- For each cache, check who can write and read it. A step whose cache or artifact a lower-trust job can read holds no secrets.
- GitHub workflow dependency lockfile (2026, where the plan offers it): `gh actions-lock`, from the `github/gh-actions-lock` extension, writes `.github/workflows/actions.lock`, which pins every action of each workflow onboarded to it, transitive ones included, so those need no SHA in the workflow file. Rerun it when a `uses:` line changes and do not edit the file by hand. It does not pin a local `./` action, which runs whatever is checked out; an action that the local action uses fails the job unless the workflow has a lockfile entry for it. A `$/` reference (not on GitHub Enterprise Server) cannot carry a ref and resolves to the commit of the file that contains it, so it needs no pin. The lockfile does not lock the actions inside a called reusable workflow, which that workflow's repository must lock or pin; the reusable workflow call itself, runner and container images, and anything an action downloads still need their own pins.

## Artifacts and claims

- Bind each release artifact to its source revision, workflow identity, and an immutable digest.
- Set retention and access on logs and artifacts to avoid leaking secrets or personal data.
