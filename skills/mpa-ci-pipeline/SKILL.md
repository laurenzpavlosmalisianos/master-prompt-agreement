---
name: mpa-ci-pipeline
description: Checks for CI/CD pipelines. Use when changing workflow files, triggers, token permissions, runners, OIDC trust, caches, artifacts, or release and publish jobs.
---

# CI/CD pipeline

Default token permissions, trigger semantics, OIDC claims, and cache isolation differ by platform. Where a decision turns on one of them, check the platform's current official documentation.

## Untrusted input

- Untrusted in a workflow: pull requests from forks, issue and comment text, commit messages, branch and tag names, external payloads, and artifacts or caches written by other workflows.
- Do not interpolate those fields into shell commands, workflow expressions, or generated code. Pass them through environment variables or quoted inputs. Expression injection in a privileged job hands over that job's secrets and token.
- A trigger that runs with secrets or a write token and also checks out or runs code from a fork is an escalation path. Avoid it. If it cannot be avoided, the untrusted step runs with no secrets and no write token.
- Chained workflows are a trust boundary. A low-privilege workflow can influence a privileged one through artifacts, caches, outputs, names, and status.
- Keep jobs that run untrusted code, jobs that hold secrets, and publish jobs separate. Untrusted code does not get container runtime sockets, host mounts, persistent workspaces, or privileged self-hosted runners.

## Identity and pinning

- Set the workflow token to read-only at the top level and grant write scopes per job; do not rely on the platform default. Every step in a job can read every token and secret that job has.
- Prefer short-lived OIDC federation to stored cloud, registry, or publishing secrets. When several trust configurations match one publishing identity, each grants on its own. They do not narrow one another.
- Anyone who can edit a workflow file can exfiltrate every secret it reaches. Protect workflow files with required review.
- The identity that triggers a build does not approve its own protected release step. Configure branch and environment protection so that a CI token cannot approve or merge to a protected branch or delete run logs.
- Pin third-party actions, reusable workflows, setup tools, and runner images to a commit or digest. A tag can be moved.
- For each cache, check who can write it and who reads it. A step whose cache or artifact a lower-trust job can read holds no secrets.

## Artifacts and claims

- Bind each release artifact to its source revision, the workflow identity, and an immutable digest.
- An attached SBOM, signature, or attestation is not a verification. Check the signer identity against the trust policy and the subject digest against the artifact.
- Logs and artifacts can disclose secrets and personal data. Set their retention and access on purpose.
- A green pipeline shows that the jobs passed. Review permission and trigger changes directly in the diff.
- Call a build hermetic or offline only when network isolation was enforced and checked.
- Changes to branch protection, environment protection, release credentials, or who may publish need explicit approval, even when the edit is one line of configuration.
