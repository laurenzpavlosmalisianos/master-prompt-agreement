---
name: mpa-infrastructure-as-code
description: "Terraform and OpenTofu release changes through Terraform 1.17 and OpenTofu 1.13 and checks that are easy to miss. Use for any work on Terraform, OpenTofu, Pulumi, CloudFormation, or CDK source, state, IAM, plans, or a tool upgrade."
---

# Infrastructure as code

Current to Terraform 1.17.2 and OpenTofu 1.13.10, checked 2026-11-27. For a newer release of either, read what changed after it in the release notes (https://developer.hashicorp.com/terraform/language/upgrade-guides, https://opentofu.org/blog/) before relying on this file. The entries are the changes that are easy to miss, not the full release notes.

## What a command does

- These change real state, which takes effect outside the repository: apply, deploy, destroy, import, move, state removal or edit, forced unlock, refresh-only update, backend migration, and direct provider actions. Applying a saved plan is the change and usually runs without a further prompt.

## What to inspect

- Read the evaluated output. For synthesized or transformed templates, review the processed result and the identity that runs the transform.

## Plans and drift

- Confirm the plan belongs to the intended workspace, account, region, variables, and source revision; reject unrelated drift. A successful plan does not guarantee a successful apply.
- A plan made with `-refresh=false` or with `-minimal-refresh` (Terraform 1.17+, which refreshes only resources that already have planned changes) does not show drift on the rest. Do not take it as a drift check, and do not use either across a provider upgrade.
- Module `source` and `version` (Terraform 1.15+, OpenTofu 1.8+) and provider requirements (Terraform 1.17+) may reference locals and variables, so the code a plan runs can depend on variable values. Review the resolved versions in the lock file and the module manifest, not only the configuration.
- Name the rollback, repair, or import path before a destroy or replace, and confirm recovery for stateful stores.
- `lifecycle { destroy = false }` (Terraform 1.16+, OpenTofu 1.12+) is not a guard like `prevent_destroy`: a destroy or replace then removes the object from state and leaves it running, unmanaged and still billed, and a replace creates a second one beside it.
- An upgrade can change a plan without any change in the configuration. From OpenTofu 1.12 `replace_triggered_by` also fires when the referenced resource is replaced, not only when it is updated. From OpenTofu 1.13 `base64gzip` returns different bytes for the same input, so resources that take its result, such as instance user data, show an update or a replace.

## State and secrets

- State files, saved plans, previews, and stack exports hold secrets and resource attributes; keep them out of source control and public artifacts.
- `sensitive` only redacts display; Terraform and OpenTofu still store the value in plain text in state and plan files, so protect the state with backend access control and with encryption at rest or OpenTofu state encryption (1.7+). Ephemeral values (Terraform 1.10+, OpenTofu 1.11+) and write-only arguments (Terraform 1.11+, OpenTofu 1.11+) stay out of state and plans, with two exceptions: OpenTofu 1.11 writes ephemeral resources into a saved plan (1.12 does not), and a `store` block in `terraform_data` (Terraform 1.16+) copies its input into state on purpose. Check logs and command output separately.
- The deployment identity does not need every permission the tool can grant, and neither do the resources it creates.
- Module and provider installation trusts the registries and git hosts it contacts. Fixes for hostile ones: Terraform 1.16.6 and 1.17.0 (CVE-2026-78669, HTTP/2 resource exhaustion); OpenTofu 1.12.3 (a crafted git address reads an arbitrary file), 1.12.6 (credentials resent to the target of a redirect from an OCI registry), and 1.12.8 and 1.13.2 (CPU exhaustion during `tofu init`).
