# Governance

This file defines how public framework changes are accepted, versioned, and released. It is procedural; it does not override `master_service_agreement.md`.

## Change Classes

1. Doctrine changes
   Changes to the Master Service Agreement (MSA), Statement of Work (SOW) template, operative charter, load order, standards of care, Task Orders, Practice Guides, `SPECIFICATION.md`, `GOVERNANCE.md`, `CONFORMANCE.md`, conformance profiles, or security policy.
2. Support changes
   Changes to deterministic scripts, schemas, tests, integration templates, examples, and generated-output checks.
3. Source-maintenance changes
   Updates to private source registries, source review artifacts, or local maintenance state. These are not public doctrine unless curated into a public framework file.
4. Packaging changes
   Public export, release, repository metadata, license, notice, and documentation-surface changes.

## Versioning

Use semantic versioning for public releases after the first tagged release:

- Major: incompatible changes to required files, authority hierarchy, conformance profiles, bootstrap semantics, or runtime entrypoint behavior.
- Minor: new Task Orders, Practice Guides, optional profiles, adapters, checks, or compatible template fields.
- Patch: clarifications, bug fixes, source updates, tests, and validation improvements that preserve public behavior.

Pre-release tags MAY be used while the framework is still being hardened.

## Portability

- Preserve file-first operation as the default architecture.
- Keep runtime adapters thin and optional.
- Do not make Codex, Claude Code, browser use, MCP, automations, or any hosted service mandatory for core conformance.
- A public change that requires new external access, package installation, credentials, or host configuration MUST be optional or explicitly documented as outside the core profile.

## Removal And Migration

Do not keep obsolete shims, duplicate surfaces, or compatibility layers merely to preserve old workflows. Before a tagged public release, remove or replace obsolete surfaces directly. A tagged release that removes or replaces a public surface, or requires user action, MUST provide release notes or a versioned migration note stating:

- replacement surface, when one exists
- migration action, when users must change files or commands
- removal version or commit
- validation command that detects stale usage when available

## Release Criteria

A public release MUST pass:

- the canonical `scripts/public_release.py prepare` route in the qualified
  Linux release environment, including zero-skip authoring compliance,
  sanitized export validation, strict public conformance, and staged and
  committed handoff receipts for one unchanged export payload
- a fresh ordinary public clone that is independent of authoring Git control
  metadata, object storage, configuration, refs, hooks, and history
- a durable, owner-only checkpoint chain binding the exact release request,
  export, public parent, staged state, commit specification, and candidate
- human review and exact authorization of the full candidate object ID before
  `publish`
- candidate revalidation immediately before the external effect, followed by
  an exact full-object-ID branch refspec under Git's `--force-with-lease`
  compare-and-swap control for the recorded parent
- a durable publication binding and remote reconciliation: an ambiguous result
  MUST be read back before retry; any later controller-push attempt MUST carry
  exact approval of the publication-bound event digest; a third remote object
  blocks publication; once the candidate has been observed at the remote, a
  later branch move MUST NOT trigger automatic republishing
- exact remote branch readback at the verified candidate before the branch
  publication is reported complete
- rendered verification under `practice_guides/visual_verification.md` when a public visual, its embedding surface, or the architecture or content it depicts changed

Before release, inspect the generated exported tree as a first-time user and confirm that private source registries, local paths, maintenance notes, review artifacts, credentials, and generated downstream state are absent. Do not publish or mirror the authoring checkout directly. The handoff checker does not mutate the export, public clone, authoring checkout, or Git state; it uses and restores only its dedicated temporary root. It does not establish remote freshness or clone-creation provenance, stage files, commit, tag, push, publish a release, or authorize any of those effects; follow the canonical procedure in `docs/maintenance_and_release.md`.

The controller's durable checkpoints permit phase-local resume after process
exit; they do not permit editing or weakening prior evidence. When an
uncheckpointed clone already exists after `export-verified`, resume may reuse
it only after closed-topology binding, a fresh remote-parent observation, and
the complete staged handoff gate; clone creation, materialization, and staging
are not repeated on that recovery path. Cleanup is a separate destructive
action requiring exact path review and explicit authorization. The controller
supports branch updates only. A tag, hosted
release, or other distribution effect requires its own reviewed procedure and
authority and MUST NOT be inferred from branch readback.

## Source-Backed Changes

Prompting, runtime, security, automation, language, and web-platform guidance SHOULD be source-backed when it encodes volatile facts. Use primary documentation, primary research, or clearly labeled design judgment. Do not turn social-media claims, one-off experiments, or private workflow anecdotes into public doctrine without independent support or narrow labeling.

## Maintainer Rule

The framework may be maintained in a richer private authoring checkout. Public release remains a selected generated export of the framework product surfaces, not a mirror of local maintenance state. Use a fresh ordinary clone of the public repository in a new destination for each publication; the authoring checkout is never the publisher.
