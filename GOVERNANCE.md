# Governance

This file defines how framework product changes are classified, accepted, and
versioned. It is procedural; it does not override
`master_service_agreement.md`.

## Change Classes

Classify a change by its highest-impact behavior. When one candidate spans more
than one class, apply every relevant acceptance gate; the labels are routing
aids, not a way to lower review.

1. Doctrine changes
   Changes to the Master Service Agreement (MSA), Statement of Work (SOW)
   template, operative charter, load order, standards of care,
   `SPECIFICATION.md`, `GOVERNANCE.md`, `CONFORMANCE.md`, conformance profiles,
   or security policy.
2. Procedure changes
   Changes to Task Orders, Practice Guides, risk routing, or reusable source and
   verification workflows.
3. Support changes
   Changes to product scripts, schemas, integration templates, tests, and
   deterministic checks.
4. Orientation changes
   Changes to product documentation, examples, diagrams, or repository
   metadata that do not alter normative behavior.

## Versioning

Use semantic versioning for tagged product versions:

- Major: incompatible changes to required files, authority hierarchy, conformance profiles, bootstrap semantics, or runtime entrypoint behavior.
- Minor: new Task Orders, Practice Guides, optional profiles, adapters, checks, or compatible template fields.
- Patch: clarifications, bug fixes, source updates, tests, and validation
  improvements that preserve product behavior.

Pre-release tags MAY identify versions that are not yet declared stable.

## Portability

- Preserve file-first operation as the default architecture.
- Keep runtime adapters thin and optional.
- Do not make Codex, Claude Code, browser use, MCP, automations, or any hosted service mandatory for core conformance.
- A product change that requires new external access, package installation,
  credentials, or host configuration MUST be optional or explicitly documented
  as outside the core profile.

## Removal And Migration

Do not keep obsolete shims, duplicate surfaces, or compatibility layers merely
to preserve old workflows. A tagged version that removes or replaces a product
surface, or requires user action, MUST provide release notes or a versioned
migration note stating:

- replacement surface, when one exists
- migration action, when users must change files or commands
- removal version or commit
- validation command that detects stale usage when available

## Change Acceptance

A product change MUST:

- preserve the authority hierarchy and assign each changed concept to one
  owning surface;
- keep initialization, current-format refresh, recovery, conformance, and
  orientation surfaces semantically consistent;
- pass the `framework-product` profile and every focused check relevant to the
  changed behavior;
- receive semantic review when it changes shared authority, lifecycle behavior,
  procedure, security, source policy, or evidence claims;
- receive rendered verification under
  `practice_guides/visual_verification.md` when a visual, its embedding surface,
  or the architecture or content it depicts changes;
- contain no credentials, maintainer-local paths, project-specific records, or
  generated downstream state; and
- document any user action required by a tagged version.

Passing deterministic checks is necessary for the invariants they cover, but
it does not replace source review, semantic judgment, or project-specific
acceptance.

## Source-Backed Changes

Prompting, runtime, security, automation, language, and web-platform guidance
SHOULD be source-backed when it encodes volatile facts. Use primary
documentation, primary research, or clearly labeled design judgment. Do not
turn social-media claims, one-off experiments, or project-local workflow
anecdotes into product doctrine without independent support or narrow labeling.
