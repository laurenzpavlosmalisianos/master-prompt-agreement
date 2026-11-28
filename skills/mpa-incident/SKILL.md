---
name: mpa-incident
description: "Guides the response to a suspected compromise, a leaked or committed secret, data loss, or a destructive mistake. Use when a credential appears in a commit, log, or chat, a malicious package may have run, or data was deleted, and before cleaning anything up."
---

# Incident

Cleaning up first destroys evidence and can widen the damage. Until the user says otherwise, investigate and recommend, and change nothing on affected systems, accounts, credentials, or history. Urgency does not change who approves an action.

## First steps

- Keep timestamped notes in UTC that separate confirmed facts, hypotheses, actions taken, and gaps.
- Prefer reversible isolation and quarantine to deletion.

## Leaked or committed secret

- Rewriting history is a separate decision for the user. It disrupts collaborators and removes evidence.

## Code may have run on a workstation or runner

- Password resets and reimaging do not invalidate certificates or tickets that were already issued. Those need revocation of their own.
- Some payloads react destructively to revocation or loss of network. Snapshot first where possible, suspend processes in preference to killing them, and revoke from a clean device.

## Data loss or a destructive mistake

- List what could restore it (reflog, snapshots, backups, trash, replicas, point-in-time logs) and the retention jobs, lifecycle rules, and trash expiry that would purge them; recommend pausing those before running anything that might overwrite a source.

## Report

- The report contains a timestamped timeline separating confirmed facts, hypotheses, actions taken and by whom, unknowns, credentials to revoke, and recovery checks that passed.
