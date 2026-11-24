---
name: mpa-infrastructure-as-code
description: "Checks for infrastructure as code and cloud platform changes. Use when changing Terraform, OpenTofu, Pulumi, CloudFormation, or CDK source, state, drift, IAM, plans, apply steps, or gateway configuration."
---

# Infrastructure as code

## What a command does

- Judge a command by its effects, not its name. `plan`, `preview`, `synth`, `validate`, and `diff` can read credentials, contact providers, lock or refresh state, run data sources, hooks, or project code, write sensitive files, and incur cost. A run that uses credentials or contacts a provider needs approval; a local offline run does not. Without approval, review source statically or read an existing plan file and report what live evidence is missing.
- These change real state and need approval for the specific operation: apply, deploy, destroy, import, move, state removal or edit, forced unlock, refresh-only update, backend migration, and direct provider actions. Applying a saved plan is the change and usually runs without a further prompt.
- Auto-approve, disabled locking, targeted apply, forced replacement, and a broad admin identity are not ways past a failing review.

## What to inspect

- Read the evaluated output. For synthesized or transformed templates, review the processed result and the identity that runs the transform.
- Pin provider and module versions and check lockfile checksums; an uninvited provider upgrade in a plan is a defect.
- Lifecycle, protection, retention, and ignore-changes settings can hide drift, block deletion, force replacement, or orphan resources; check that they are not making a plan look safer than it is.
- Apply-time hooks and custom resources run code whose side effects appear in neither state nor plan. Identify when they run, as whom, and what they can change.

## Plans and drift

- Classify every create, update, replace, delete, import, move, permission change, public exposure, and encryption change. A resource the preview skipped or could not evaluate is not shown to be unchanged.
- Confirm the plan belongs to the intended workspace, account, region, variables, and source revision; reject unrelated drift. A successful plan does not guarantee a successful apply.
- Before reconciling drift, ask which side is authoritative, the live state or the source; overwriting live infrastructure to match code changes a live system.
- Name the rollback, repair, or import path before a destroy or replace, and confirm recovery for stateful stores (`mpa-migration`).

## State and secrets

- State files, saved plans, previews, and stack exports hold secrets and resource attributes; keep them out of source control and public artifacts.
- Values marked sensitive or ephemeral can still leak through state or logs; check what the mechanism covers.
- The deployment identity does not need every permission the tool can grant, and neither do the resources it creates.

## Platform and gateway configuration

- Look for paths around a gateway; gateway auth or policy does not replace service authorization (`mpa-secure-coding`).
- For dynamic configuration or routing, define propagation delay, validation, rollback, and behaviour while the control plane is unavailable.
- A platform running agents or other untrusted workloads must not let the workload change or impersonate its own policy, approval, or credential source; containment must hold when the control channel is lost (`mpa-agent-inputs`).
- Privileged and service identities are not exempt from anomaly containment. Where disabling one would cause an outage, narrow what it can do; keep emergency access narrow, time-limited, and alerted on every use.
- Do not claim tolerance of a failure mode without a test or recovery record for it; a redundancy diagram is not that record.
