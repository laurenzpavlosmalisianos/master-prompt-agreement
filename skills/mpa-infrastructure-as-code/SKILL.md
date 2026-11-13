---
name: mpa-infrastructure-as-code
description: Checks for infrastructure as code. Use when changing Terraform, OpenTofu, Pulumi, CloudFormation, or CDK source, state, plans, or apply steps, or cloud platform and gateway configuration.
---

# Infrastructure as code

## What a command does

- Judge a command by its effects, not its name. `plan`, `preview`, `synth`, `validate`, and `diff` can read credentials, contact providers, lock or refresh state, run data sources, hooks, or project code, write sensitive files, and incur cost. A run that uses credentials or contacts a provider needs approval; a run that stays local and offline does not. Without approval, review the source statically or read an existing plan file, and report what live evidence is missing.
- These change real state and need approval for the specific operation: apply, deploy, destroy, import, move, state removal or edit, forced unlock, refresh-only update, backend migration, and direct provider actions. Applying a saved plan is the change, and tools apply one without a further prompt.
- Auto-approve, disabled locking, targeted apply, forced replacement, and a broad admin identity are not ways past a failing review.

## What to inspect

- Read the evaluated output. For synthesized or transformed templates, review the processed result and the identity that runs the transform.
- Pin provider and module versions and check lockfile checksums. A provider upgrade that appears in a plan uninvited is a defect.
- Lifecycle, protection, retention, and ignore-changes settings can hide drift, block deletion, force replacement, or orphan resources. Check that they are not making a plan look safer than it is.
- Apply-time hooks and custom resources run code whose side effects appear in neither state nor plan. Identify when they run, as whom, and what they can change.

## Plans and drift

- Classify every create, update, replace, delete, import, move, permission change, public exposure, and encryption change. A resource the preview skipped or could not evaluate is not shown to be unchanged.
- Confirm the plan belongs to the intended workspace, account, region, variables, and source revision. Reject unrelated drift. A successful plan does not guarantee a successful apply.
- Before reconciling drift, ask which side is authoritative, the live state or the source. Overwriting live infrastructure to match code is a change to a live system.
- Name the rollback, repair, or import path before a destroy or replace. For stateful stores, confirm that a backup exists and restores.

## State and secrets

- State files, saved plans, previews, and stack exports can hold secrets and resource attributes. Keep them out of source control and public artifacts.
- Values marked sensitive or ephemeral can still leak through state or logs. Check what the mechanism covers.
- The deployment identity does not need every permission the tool is able to grant, and neither do the resources it creates.

## Platform and gateway configuration

- Authentication or policy at a gateway does not replace authorization at the service behind it. Look for paths around the gateway.
- For dynamic configuration or routing, define the propagation delay, validation, rollback, and what happens while the control plane is unavailable.
- A platform that runs agents or other untrusted workloads must not let the workload change or impersonate its own policy, approval, or credential source. Containment has to hold when the control channel is lost.
- Privileged and service identities are not exempt from anomaly containment. Where disabling one would cause an outage, reduce what it can do. Keep emergency access narrow, time-limited, and alerted on every use.
- Do not claim tolerance of a failure mode without a test or recovery record for it. A redundancy diagram is not that record.
