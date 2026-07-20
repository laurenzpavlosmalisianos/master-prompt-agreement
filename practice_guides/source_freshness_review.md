# Source Freshness Review Practice Guide

Use this Practice Guide when a review, audit, plan, setup, or maintenance pass may fail because current primary sources have changed. It compares a pinned claim or source with the current authoritative source and turns changes into hypotheses, checks, and gaps. For source-sensitive project updates that may edit code, config, dependencies, or user-facing behavior, use `task_orders/source_update.md` and load this guide inside that workflow. References to `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` are framework-relative project source surfaces.

## Workflow

1. Define the affected claim and surface.
- identify the claim, file, source-pack entry, dependency pin, setup step, prompt/runtime rule, or release assumption under review
- identify affected code, docs, tests, templates, project state, automation, or user-facing behavior

2. Confirm the acquisition method and egress boundary.
- use the SOW or runtime project contract acquisition boundary first
- if the project has `SOURCE_PACKS.md`, use its approved source list before inventing a new source set
- if the project has `SOURCE_UPDATE.md`, use its source-check history, cadence, feed state, and open gaps before repeating work
- if the allowed method is unclear, ask before using network, browser automation, authenticated sources, auxiliary source integrations, protocol bridges, or external reviewers
- do not mark a source inaccessible from a single method failure when another approved method remains available; for publisher-owned HTML, XML, RSS, Atom, JSON, text, release, and advisory roots, retry a bounded read-only `GET` after `HEAD` or metadata failure before recording an unresolved gap
- record method, status, date, timezone, and access limits

3. Select the smallest credible source set.
- exact evidence URL for provenance
- smallest useful parent root or feed for recurring monitoring: blog/news index, research index, advisory database, docs-update page, changelog, release index, releases, tags, package metadata, sitemap, or channel feed
- infer recurring-root status only from project-neutral collection structure. When a repository home, product landing page, `latest` alias, canonical implementation directory, or other unusual endpoint is itself the bounded update surface, require the source registry's explicit `canonical_exact_root` reason, authority, freshness mechanism, revalidation interval, and replacement-discovery fallback
- use publisher-owned roots and feeds by default; do not use third-party feed mirrors, feed proxies, analytics redirects, scraping gateways, or republishing endpoints unless the acquisition boundary explicitly approves them
- recurring authority roots should regularly publish primary evidence, official updates, release notes, advisories, source code, reproducible research, or structured data
- secondary discovery filters may be recurring when they reliably surface relevant candidate leads and the project action rule requires primary-source or project-evidence verification before adoption
- do not keep corporate newsroom/media-coverage pages, marketing pages, personal newsletters, Substacks, or social feeds as recurring authority roots merely because one exact item was useful
- use an umbrella entry for a conference, report bundle, index, source root, or curated program when linked items are only source-discovery evidence for one shared abstraction. Promote a linked item to a standalone entry only after reviewing it directly and accepting a distinct durable rule, risk, implementation fact, or monitoring need
- tagged source, maintainer design note, release issue, or PR discussion only when implementation behavior is material and official docs are incomplete or ambiguous
- recognized expert commentary only as labeled supplementary interpretation or source discovery; record why the source is considered expert and verify durable claims against primary sources or project evidence before adopting normative guidance

Exact title-slug posts, version posts, PDFs, papers, advisories, release notes, commit-addressed repository file/tree paths, immutable tags/releases, and clearly version-scoped source paths are evidence URLs. Treat branch-based repository paths as mutable unless separately pinned. Monitor a durable parent root or feed when one exists. If no recurring root is justified, omit the monitor-root line instead of checking a stale exact item on every run.

4. Check freshness before synthesis.
- record source owner, type, locator, publication date, accessed-at date, version scope, and volatility
- record the reference tier from `source_grounded_research.md`
- separate stable principles from version-sensitive implementation facts
- for downloadable artifacts, dependencies, advisories, release assets, and source-code evidence, record immutable identifiers when available, such as version, package coordinate, advisory ID, commit SHA, tag, checksum, signature or attestation status, or release asset name
- for current-release claims, distinguish the distribution surface, channel or dist-tag, exact version or tag, and prerelease or draft status; record feature maturity, model role, and serving tier separately when they affect the claim rather than treating `latest` as one scalar
- distinguish the upstream current release, the project-declared or pinned version, the installed toolchain or binary, and any operating-system or package-manager channel that supplied it. An installed-version probe proves only that environment; an upstream release page does not prove what an IDE-bundled toolchain, a distribution repository, a container image, or the project actually runs
- if setup uses `latest`, `current stable`, or an unpinned default, verify the current primary source before recording it
- if the project pins a version, use version-scoped docs and do not silently upgrade it
- mark inaccessible or unverified areas as gaps
- when an approved source is inaccessible, record the attempted URL, failure class, and whether a directly verified primary alternate covers the same claim
- if a source requires authenticated browser state, JavaScript rendering, or another session-bound method, keep it manual or evidence-only unless the project has an explicit recurring acquisition/session grant naming account or session scope, allowed data, egress, retention, rate/terms boundary, and action rule. With that complete grant, it may be a recurring root under the declared boundary; without it, do not schedule it

5. Translate deltas into checks.
- obsolete API, deprecation, changed default, support boundary, or security control
- changed runtime instruction, tool schema, capability discovery behavior, approval boundary, memory behavior, verifier behavior, or agent-orchestration guidance
- stale source registry entry, cadence, monitor root, or one-off evidence classification
- missing documentation, test, release, migration, rollout, or acceptance check

6. Apply only relevant findings.
- update code, tests, docs, or project state only when the fix is in scope
- update `SOURCE_PACKS.md`, `SOURCE_UPDATE.md`, or automation state only when the file is receipt-declared mutable state and source maintenance is in scope or approved; preserve its generated-state origin marker, and route any absent optional generated surface through candidate-input refresh instead of creating it ad hoc
- retain durable source-backed learnings only through an approved state surface or explicit task grant
- reject source changes that do not affect the task

## Output

Provide:

1. affected claim and surface
2. primary source set with reproducible locators, dates, versions, and claim linkage
3. source-derived deltas, hypotheses, or checks
4. accepted fixes or documentation/test updates
5. freshness gaps and residual risk

## Guardrails

- Do not make recurring source refresh a blanket tax on every task.
- Do not expand a project into a general technology survey.
- Do not treat a link existing as proof that the linked guidance still supports the claim.
- Do not cite vendor marketing or community summaries as normative sources when primary sources exist.
- Do not treat repository stars, trending status, README claims, prompt-pack popularity, or video summaries as proof of authority or safety.
- Do not promote unknown-author or offensive/security proof-of-concept repositories into recurring sources. Treat them as non-normative source-discovery input; do not clone, build, install, execute, deobfuscate, or inspect operational exploit source outside an explicitly authorized lab boundary.
- Do not let AI-generated summaries, feed triage, LLM classification, or source-monitor output trigger edits or security conclusions without primary-source or project-evidence verification.
- Do not copy provider system prompts, chat-derived tool lists, or unpublished tool descriptions into framework doctrine.
