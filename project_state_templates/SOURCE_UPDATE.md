<!-- mpa-generated-state-origin: master-prompt-agreement/project-state/v1 -->

# Source Update Plan

Purpose: project-specific source-update checklist for keeping code, dependencies, docs, and user-facing behavior current.

Use this file when the project depends on changing external sources. Keep it compact. Do not paste documentation dumps, changelogs, or internal transcripts here.

## Update Policy

- Source Acquisition Boundary: [public web / authenticated sources / user-supplied material / approved local tool / approved auxiliary source integration or protocol bridge]
- Approved Check Method: [approved command-line retrieval / approved rendered-page retrieval / approved local fetch tool / user-supplied material / other]
- Egress Boundary: [no network / allowlisted endpoints / approved fetch proxy / authenticated source / user-supplied artifact]
- Default Review Cadence: [manual / weekly / monthly / release-triggered / security-triggered]
- Volatility Model: [stable doctrine / version-sensitive implementation / high-volatility runtime or security surface / incident-triggered]
- Version Review Rule: [keep pins / defer review / review upgrades in current scope]
- Approval Boundary: [which version, dependency, migration, feature, deploy, or irreversible changes require approval]
- Output Location: [TODO.md / DECISIONS.md / release notes / issue tracker / other]

## Cadence Rules

- Stable doctrine: re-check during scheduled framework or architecture reviews, or when a governing standard changes.
- Version-sensitive implementation: re-check before editing the affected stack, dependency, runtime, model, API, or integration.
- High-volatility runtime or security surface: re-check before each material recommendation and after relevant release notes, advisories, or provider-policy changes.
- Incident-triggered source: re-check immediately when a matching CVE, advisory, compromise report, deprecation, outage, exploit pattern, or project incident appears.

## Source Registry

`SOURCE_UPDATE.md` is used with `SOURCE_PACKS.md`. Keep durable source identity, tier, scope, volatility, and action rules in `SOURCE_PACKS.md`. Use this section for sources whose update cadence, feed state, last checked date, or current run status must be tracked here.

When a source is meant for recurring monitoring, keep exact evidence URLs as provenance and record the smallest useful source root or feed for discovery. Use exact URLs for doctrine and claims; use blog indexes, news indexes, research indexes, docs-update pages, roots, feeds, releases, changelogs, update pages, or advisory indexes for recurring checks. Mark one-off title-slug posts, articles, PDFs, announcements, release notes, or version posts as `one_off` instead of silently turning their whole publisher into a monitored source.

Every populated Source Registry row must set `Monitoring Mode` to exactly `recurring` or `one_off`. Use `recurring` only when the Source cell is a durable parent root that must be reconciled in source-root coverage. Use `one_off` for exact evidence inspected without an ongoing root obligation. `Cadence` records schedule or trigger detail; validators do not infer monitoring mode from its prose. Omit disabled sources or record unresolved acquisition gaps under `Open Gaps` instead of encoding another monitoring mode.

| Surface | Source | Kind | Tier | Scope | Volatility | Check Method | Access Policy | Monitoring Mode | Cadence | Last Checked | Allowed Use | Action Rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [language/runtime] | [official docs URL or path] | official docs | [official-doc] | [version or current] | [stable / version-sensitive / high-volatility / incident-triggered] | [method] | [robots/terms checked on YYYY-MM-DD / not applicable / user-supplied / approved local source / blocked] | [recurring / one_off] | [cadence] | [YYYY-MM-DD or never] | [normative after verification / evidence-only / source discovery only / inspiration only / prohibited] | [keep / flag / review] |
| [framework/library] | [release notes URL or path] | release notes | [vendor-doc] | [version or current] | [stable / version-sensitive / high-volatility / incident-triggered] | [method] | [robots/terms checked on YYYY-MM-DD / not applicable / user-supplied / approved local source / blocked] | [recurring / one_off] | [cadence] | [YYYY-MM-DD or never] | [normative after verification / evidence-only / source discovery only / inspiration only / prohibited] | [keep / flag / review] |
| [official implementation repository] | [official repository / releases / changelog / security notes] | implementation source | [official-implementation] | [commit, tag, release, or current] | [version-sensitive / high-volatility / incident-triggered] | [repository release page / release API / approved local source / other approved method] | [robots/terms checked on YYYY-MM-DD / not applicable / user-supplied / approved local source / blocked] | [recurring / one_off] | [release-triggered or scheduled] | [YYYY-MM-DD or never] | [normative after verification / evidence-only / source discovery only / inspiration only / prohibited] | [review releases, tags, security notes, and maturity changes before adopting claims] |
| [model/agent runtime/tool] | [official docs, release notes, security page, or changelog] | runtime docs | [vendor-doc] | [version, current, or project pin] | [stable / version-sensitive / high-volatility / incident-triggered] | [method] | [robots/terms checked on YYYY-MM-DD / not applicable / user-supplied / approved local source / blocked] | [recurring / one_off] | [cadence] | [YYYY-MM-DD or never] | [normative after verification / evidence-only / source discovery only / inspiration only / prohibited] | [keep / flag / review] |
| [security] | [advisory source URL or path] | security advisory | [standard / official-doc / vendor-doc] | [affected dependency or surface] | [stable / version-sensitive / high-volatility / incident-triggered] | [method] | [robots/terms checked on YYYY-MM-DD / not applicable / user-supplied / approved local source / blocked] | [recurring / one_off] | [cadence] | [YYYY-MM-DD or never] | [normative after verification / evidence-only / source discovery only / inspiration only / prohibited] | [review immediately if affected] |

## Feed Watchers

Use this table only for recurring source, blog, news, research, docs-update, release, advisory, RSS, Atom, API, approved channel, podcast, playlist, or interview feeds.

| Surface | Feed | Tier | Scope | Check Method | Access Policy | Conditional State | Dedupe Key | Last Checked | Last Seen | Allowed Use | Triage Rule | Output |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [security/runtime/source surface] | [feed URL or API endpoint] | [vendor-doc / official-doc / research / commentary] | [products, packages, or topics] | [approved HTTP retrieval / approved rendered-page retrieval / approved fetch tool / RSS / platform API] | [robots/terms checked on YYYY-MM-DD / not applicable / user-supplied / approved local source / blocked] | [ETag / Last-Modified / none] | [GUID / canonical URL / composite hash] | [YYYY-MM-DD] | [cursor, ISO date, or none] | [normative after verification / evidence-only / source discovery only / inspiration only / prohibited] | [signals to classify, verify, or ignore] | [artifact, TODO, issue, or report] |

Feed triage is discovery input. Poll only through the approved acquisition and egress boundary. Treat LLM labels, video summaries, transcript summaries, severity guesses, and exploit-class tags as candidate classification until verified against primary sources, advisories, source releases, or project evidence.
Prefer publisher-owned roots and feeds. Do not use third-party feed mirrors, feed proxies, analytics redirects, scraping gateways, or republishing endpoints as monitor roots unless the acquisition boundary explicitly approves them.
Do not remove a useful discovery filter merely because it is not authoritative. Remove or downgrade it when it is noisy, promotional, duplicative, inaccessible, unsafe for the approved acquisition boundary, or no longer produces relevant primary-source leads.

## Update Checklist

1. Inspect current project state before checking external sources.
2. Check `SOURCE_PACKS.md`, this file, and any approved shared framework source reference before doing new external research for the same source family.
3. Check only the smallest credible source set for the requested update surface.
4. Broaden beyond official docs only when official docs are incomplete, stale, ambiguous, or not the best authority for the claim.
5. Record source date, reviewed date, reference tier, version scope, volatility, access method, broadened-source rationale, and gaps. For current-release claims, distinguish the distribution surface, channel or dist-tag, exact version or tag, and prerelease or draft status; record feature maturity, model role, and serving tier separately when relevant.
6. Classify candidate changes: security fix, compatibility fix, migration, dependency update, feature adoption, docs/test update, no action, or reject.
7. For model, agent, tuning, or tool-runtime updates, record reasoning/thinking controls, context or memory preservation, prompt-cache assumptions, tool-calling compatibility, deprecations, serving-stack limits, and trace-data or evaluation-environment assumptions before adopting advice.
8. Ask for approval before material version, dependency, feature, migration, deployment, or irreversible changes.
9. Apply approved changes only.
10. Run the relevant verification profile.
11. Record durable decisions in `DECISIONS.md`, unresolved work in `TODO.md`, and reusable source-registry gaps or additions in `SOURCE_PACKS.md` only when approved. If a source gap is also a shared framework candidate, add only a sanitized reference to `FRAMEWORK_FEEDBACK.md` when that file exists.

## Recent Checks

Keep one current summary per source surface. Replace an older closed check when
its current version, action, and durable source decision are represented in the
registry, implementation, decision record, or verified source-chain closeout.
Retain an older check only while it documents an unresolved gap or supplies
independently necessary provenance; do not append routine no-change checks
indefinitely.

- [YYYY-MM-DD], [surface], [sources checked], Result: [no action / TODO / decision / implemented], Notes: [short note]

## Open Gaps

- [surface] - [missing source or blocked access] - [next action]

## Framework Source Feedback

- [source surface / duplicate research / missing shared root] - [sanitized evidence scope] - [candidate framework-source update or no action] - [FRAMEWORK_FEEDBACK.md entry ID if used]

## Rules

- Prefer official docs, standards bodies, specifications, security advisories, release notes, and project-pinned docs.
- Allowed reference tiers: `[standard]`, `[official-doc]`, `[vendor-doc]`, `[official-implementation]`, `[research]`, `[case-study]`, `[case-study-root]`, `[commentary]`, `[ai-summary]`.
- Use official repositories, tagged source, maintainer-authored design notes, and issue or PR discussions only when implementation behavior is material.
- Use public-sector security authorities, language advisory databases, and peer-reviewed or author-published research when they are the right authority for security or research claims.
- Apply precedence explicitly: standards/specs over summaries, release notes/advisories over commentary, source code or tagged releases for implementation behavior, and research only for stable reusable implications.
- Treat `[case-study]` as case-study evidence, not doctrine; `[case-study-root]` as a recurring parent root for case-study evidence or discovery only; `[commentary]` as source discovery or hypothesis generation; and `[ai-summary]` as orientation only, not doctrine.
- Treat repository popularity and hosting metadata as useful context, not authority by itself.
- Record source authority in the structured `Tier` and `Allowed Use` cells. For lower-tier rows, use `[case-study]` with `evidence-only`, `[case-study-root]` with `source discovery only`, `[commentary]` with `source discovery only`, and `[ai-summary]` with `inspiration only`. Keep free-text action and triage rules explanatory; they do not override those fields.
- Do not silently upgrade pinned versions.
- Do not turn update checks into broad technology surveys.
- Do not store secrets, tokens, credentials, private source dumps, or copied third-party docs here.
