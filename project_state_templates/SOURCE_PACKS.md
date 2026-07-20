<!-- mpa-generated-state-origin: master-prompt-agreement/project-state/v1 -->

# Source Packs

Purpose: optional project-local source packs for source-sensitive work. Use this file when a project wants a maintained list of sources that agents may consult before making version-sensitive, security-sensitive, legal-sensitive, or standards-sensitive recommendations.

Keep this file compact. Do not paste full articles, documentation dumps, transcripts, screenshots, PDFs, or private source material here. Store only the source identity, tier, role, allowed use, scope, volatility, reviewed date, acquisition method, and project-specific action rule.

## Policy

- Owner: [person/team]
- Source Acquisition Boundary: [public web / authenticated sources / user-supplied material / approved local fetch tool / approved auxiliary source integration or protocol bridge / none]
- Egress Boundary: [no network / allowlisted endpoints / approved fetch proxy / authenticated source / user-supplied artifact]
- Review Cadence: [manual / weekly / monthly / release-triggered / security-triggered / task-triggered]
- Approval Boundary: [what source-derived changes require approval]
- Relationship To `SOURCE_UPDATE.md`: [SOURCE_PACKS.md lists sources / SOURCE_UPDATE.md tracks update runs and decisions]
- Shared Framework Source Reference: [framework source pack, framework monitor output, exported registry, or none]. Use approved shared framework sources before adding duplicate project-local sources for the same surface.

## Source Tiers

Allowed tiers:

- `[standard]`
- `[official-doc]`
- `[vendor-doc]`
- `[official-implementation]`
- `[research]`
- `[case-study]`
- `[case-study-root]`
- `[commentary]`
- `[ai-summary]`

Rules:

- Prefer standards, official documentation, release notes, security advisories, and official implementation repositories.
- Before researching a source family from scratch, check this file, `SOURCE_UPDATE.md`, and any approved shared framework source reference for an already-maintained source, reviewed date, open gap, or rejected source.
- Treat `[case-study]` as case-study evidence, not doctrine.
- Treat `[case-study-root]` as a recurring parent root for case-study evidence or discovery only; it does not become doctrine or authority without exact claim-specific primary verification.
- Treat `[commentary]` as source discovery or hypothesis generation.
- Treat `[ai-summary]` as orientation only; not doctrine.
- Record those lower-tier boundaries in the structured `Allowed Use` field:
  `[case-study]` uses `evidence-only`, `[case-study-root]` and `[commentary]`
  use `source discovery only`, and `[ai-summary]` uses `inspiration only`.
  Free-text scope, action, and notes explain the entry but do not override its
  tier or allowed use.
- Do not use personal forks, snippet-host entries, private-person repositories, social posts, or unofficial prompt packs as normative sources unless the task is explicitly about that artifact and the entry is labeled non-normative.
- Re-check source-sensitive claims before use when versions, defaults, provider behavior, security posture, legal rules, or standards may have changed.

## Source Roles

- Authority root: a durable primary source root, feed, changelog, standard, documentation set, advisory database, release surface, or official implementation source that may support framework or project changes after verification.
- Evidence URL: the exact article, advisory, release note, paper, repository path, or documentation page that supports a reviewed claim.
- Discovery filter: a lower-tier feed, index, search page, curated list, or expert/commentary source used only to find candidates. Findings from discovery filters require primary-source or project-evidence verification before any rule, source registry, code, priority, or policy change.

External ideas are not automatically sources. When a user supplies or an agent
discovers an article, repository, paper, video, transcript, social post,
product page, or pasted text, first record the source-derived abstraction in
original words and list the source-specific wording, commands, product names,
examples, or workflow shape that were rejected. Add the source to this file
only when it still has a separate role as authority, evidence, or discovery
after that abstraction pass.

## Sources

Use one compact entry per source or source family.

### [Surface Name]

Reviewed: [YYYY-MM-DD]

- [tier] [source name]
  Evidence URL: [exact article / report / advisory / release note / spec / repository path / local approved path]
  Role: [authority root / evidence URL / discovery filter]
  Allowed Use: [normative after verification / evidence-only / source discovery only / inspiration only / prohibited / approved copied material with license record]
  Version Anchor: [current / project pin / tag / commit / docs version / distribution surface + channel or dist-tag + exact version / standard version / evidence-only]
  Access Policy: [robots/terms checked on YYYY-MM-DD / not applicable / user-supplied / approved local source / blocked]
  Last Checked: [YYYY-MM-DD]
  Monitor Root: [optional; structurally evident feed / blog or news index / research index / docs-update page / release or tags index / changelog / advisory database / package metadata / channel root, or an explicitly classified canonical exact root]
  Monitor host relation: [required with Monitor Root; evidence_host / approved_cross_host]
  Approval reference: [required only for approved_cross_host; safe repo-relative authority record#approval-id]
  Monitor root class: [omit for a structurally evident collection root / canonical_exact_root]
  Canonical exact root reason: [required only for canonical_exact_root]
  Freshness mechanism kind: [required only for canonical_exact_root; http_validator / content_digest / item_cursor / release_identifier / revision_identifier]
  Source authority: [required only for canonical_exact_root]
  Revalidation interval days: [required only for canonical_exact_root; positive integer]
  Replacement discovery mode: [required only for canonical_exact_root; alternate_url / manual_authority_review]
  Replacement discovery reference: [required only for canonical_exact_root; one safe HTTPS URL for alternate_url, or one safe resolvable repo-relative procedure or registry locator for manual_authority_review]
  Scope: [what this source may inform]
  Volatility: [stable / version-sensitive / high-volatility / incident-triggered]
  Acquisition: [approved method]
  Cadence: [manual / scheduled / release-triggered / incident-triggered]
  Action Rule: [how agents should use or ignore findings from this source]
  Notes: [short project-specific caveat]

## Open Source Gaps

- [surface] - [missing source or blocked access] - [next action]

## Upstream Framework Candidates

- [source surface or repeated gap] - [why this may belong in the shared framework source registry] - [public evidence URL or sanitized project evidence scope] - [proposed action] - [FRAMEWORK_FEEDBACK.md entry ID if used]

## Monitor Root Discipline

- Use exact item URLs for evidence and durable parent roots for recurring monitoring.
- Prefer publisher-owned roots and feeds. Do not use third-party feed mirrors, feed proxies, analytics redirects, scraping gateways, or republishing endpoints as monitor roots unless the acquisition boundary explicitly approves them.
- Set `Monitor host relation` to `evidence_host` only when every monitor-root hostname exactly matches an explicit evidence URL hostname in the entry; do not infer common authority from parent/subdomain shape. Use `approved_cross_host` only with a separate, safe, resolvable repo-relative `Approval reference` naming the durable approval record and its stable approval identifier. Free-text rationale never grants cross-host authority.
- Do not use a PDF, title-slug post, exact release note, versioned documentation page, repository file/tree path, or tag-specific release page as a recurring monitor root.
- If a source is useful only once, omit `Monitor Root` and keep the exact evidence URL.
- When recording current release state, distinguish the distribution surface, channel or dist-tag, exact version or tag, and prerelease or draft status. Record feature maturity, model role, and serving tier separately when they affect the claim; none is implied by the word `latest`.
- URL shape alone may establish only a project-neutral collection class such as a feed, blog/news/research/docs index, category/topic/tag index, changelog, advisory index, releases page, or tags page. A repository home, product landing page, `latest` alias, or other source-specific endpoint is not implicitly approved by its publisher name.
- Use `Monitor root class: canonical_exact_root` only for an authoritative page or endpoint that is itself the bounded update surface. Explanatory reason and authority prose remain informational; certification requires the closed `Freshness mechanism kind`, a positive `Revalidation interval days`, the closed `Replacement discovery mode`, and a safe explicit `Replacement discovery reference`. `alternate_url` requires one safe HTTPS URL different from every monitor root. `manual_authority_review` requires one safe, resolvable repo-relative procedure or registry locator.
- Do not remove a useful discovery filter merely because it is not authoritative. Remove or downgrade it when it is noisy, promotional, duplicative, inaccessible, unsafe for the approved acquisition boundary, or no longer produces relevant primary-source leads.
