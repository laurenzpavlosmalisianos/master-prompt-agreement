Task Order — Source-Sensitive Project Update

<!-- mpa-workflow-contract: {"mode_enum":["observe","propose","act"]} -->

Objective

Update project code, configuration, dependencies, or user-facing features against current official or project-approved sources without guessing, silently upgrading pins, or expanding scope.

Procedure

Mode: run this task as `observe`, `propose`, or `act`. Default to `observe` unless the User or SOW explicitly selects another mode.
- `observe`: inspect approved project state and sources, then write only the approved report artifact. Do not edit tracked project files, stage, commit, push, install packages, or change external systems.
- `propose`: inspect, classify, and write only the approved proposal or report artifact with proposed edits. Stop before editing operative project files until the User approves exact changes.
- `act`: implement only approved changes under the project's approval boundary, then verify and update state.
Source-acquisition, automation, integration, or reviewer authority does not by itself select `propose` or `act`, and a monitoring trigger does not authorize project changes.
Regardless of project layout, Source Update does not directly edit shared or
reusable framework product surfaces. It may update separately authorized
project-local source evidence or records; a source-derived candidate for
framework doctrine, templates, runtime files, integrations, scripts, tests,
public documentation, or other reusable product surfaces must stop at a bounded
`propose` handoff and route through `task_orders/framework_semantic_audit.md` and
`task_orders/framework_improvement.md`. Authorized project-local application,
configuration, documentation, and test updates retain the direct `act` path.

1. Read `AGENT_PROJECT.md` for active stack, commands, source-acquisition boundary, version policy, version-control policy, branch policy, backout policy, approval boundaries, verification profiles, critical surfaces, any `SOURCE_PACKS.md` approved source list, and any `SOURCE_UPDATE.md` update registry. Consult `STATEMENT_OF_WORK.md` only when canonical project terms or omitted details matter.
2. Confirm the requested update surface. If the user says "check official sources", "check the source host", "update against latest docs", "modernize this framework/library/tool", or similar, treat the task as source-sensitive.
3. If the approved acquisition method or egress path is missing or does not allow the needed source access, stop and ask before using network, rendered-page automation, authenticated sources, repository hosts, auxiliary source integrations, or protocol bridges.
   Do not use proxy rotation, residential proxies, browser-fingerprint impersonation, CAPTCHA or anti-bot bypass, stealth browser modes, or mobile-device/app automation unless the project contract and current task approval authorize the exact method, target, account boundary, and evidence handling.
4. Inspect the current project state before checking external sources:
   - installed or pinned versions
   - lockfiles and package manifests
   - framework or generator config
   - themes, plugins, modules, integrations, and build commands
   - affected templates, components, routes, content models, scripts, or deployment files
5. Load `practice_guides/source_freshness_review.md`. Also load `practice_guides/source_grounded_research.md` for user-supplied or agent-discovered articles, papers, posts, talks, summaries, source-derived claims, or other external ideas; `practice_guides/source_originality_review.md` when external repositories, code, assets, examples, docs, demos, prompts, tests, UI or product references, or other external material might influence implementation or reusable framework text; `practice_guides/dependency_risk.md` for dependency additions or upgrades; `practice_guides/migration_safety.md` for breaking or irreversible changes; and `practice_guides/security_audit.md` when security advisories, CVEs, authentication, secrets, or trust boundaries are involved. If the task retains a completed browser research report, copy `project_state_templates/SOURCE_DEEP_RESEARCH.md` to the approved evidence path and follow `docs/source_deep_research_artifacts.md`; do not create that artifact for an incomplete report or an ordinary source check.
6. Select the smallest credible source set. If `SOURCE_PACKS.md` exists, use it as the project-approved source list before adding new sources. If `SOURCE_UPDATE.md` exists, use it for source-check cadence, previous runs, open gaps, and action rules. If the project contract, `SOURCE_PACKS.md`, or `SOURCE_UPDATE.md` names an approved shared framework source reference, framework monitor output, or exported source registry for the same surface, inspect that first and avoid duplicate external research unless the shared source is stale, incomplete, inaccessible, or narrower than the current project need:
   - project-pinned or version-scoped docs for existing pins
   - official docs, release notes, changelogs, migration guides, and security advisories
   - official repository releases, tags, source, and issue or discussion references when the repository host is the primary source; for framework source packs, use organization, standards, publisher/project-owner, or canonical implementation repositories rather than personal forks, snippet-host entries, or private-person repositories
   - unknown-author or offensive/security proof-of-concept repositories only as non-normative source-discovery input; inspect repository metadata, README, docs, and license by default, and do not clone, build, install dependencies, execute, deobfuscate binaries or shellcode, or inspect operational exploit source unless the User explicitly authorizes a controlled lab boundary for that task
   - standards or compatibility data when behavior depends on browser, runtime, protocol, accessibility, or security requirements
   - public-sector security authorities, language advisory databases, and peer-reviewed or author-published research when they are the right authority for the claim
   - maintainer-authored design notes, tagged source code, or implementation discussions when official docs are incomplete, stale, ambiguous, or not precise enough
   - recognized expert commentary only as labeled supplementary interpretation, source discovery, or hypothesis generation; verify durable claims against primary sources, source code, standards, advisories, or measured project behavior before adoption
   For feed or API monitoring, use only the approved acquisition and egress boundary. Record endpoint, cursor or conditional state, dedupe key, and output location.
   Record source authority by claim type: project contract for project requirements, normative specification for conformance, measured target runtime for observed behavior, exact tagged source for implementation internals, authoritative advisory or KEV data for exploitation status, and expert commentary only for framing questions or finding primary sources.
7. Compare current project behavior against the current sources. Classify each candidate change:
   - security or compatibility fix
   - required migration or deprecation cleanup
   - version/API update
   - feature adoption
   - documentation/test update
   - no action or reject
   When a locally available, version-matched first-party agent guide or skill
   covers the same domain as maintained guidance, treat it as a conditional
   primary technical source, not another layer to append. Bind its version,
   scope, and permissions; inventory overlap; remove or narrow duplicated text;
   retain only portable fallback, cross-cutting safeguards, and project-specific
   constraints; and verify both first-party-present and fallback routes. Do not
   copy its wording, activate changed instructions without review, or replace
   maintained guidance automatically.
   For user-supplied or agent-discovered articles, repositories, papers, talks, social posts, or
   other external ideas, first write the project-neutral abstraction in your own
   words: the durable rule, failure mode, quality pattern, or source-entry
   reason; where it applies; and which source-specific commands, tools, wording,
   product names, claims, or scope are deliberately rejected. Do not copy source
   phrasing, prompt text, command surfaces, file names, taxonomy, examples, or
   product-specific workflows into reusable project or framework artifacts unless
   the task explicitly authorizes that exact dependency and the rights basis is
   reviewed. If no reusable abstraction survives that pass, record the rejection
   and do not stretch the source into doctrine or a recurring monitor root. Do
   not add a source to `SOURCE_PACKS.md`, a framework source registry, or a
   recurring monitor root merely because it inspired an abstraction; retain it
   only when it remains an authoritative source, approved evidence anchor, or
   useful discovery filter after the abstraction review.
8. In `observe` mode, write the approved report artifact with the checked sources, candidate findings, evidence, gaps, and later verification commands, then stop. If no file sink was approved, report in conversation only. Do not update `SOURCE_PACKS.md`, `SOURCE_UPDATE.md`, `TODO.md`, `DECISIONS.md`, tracked project files, staging, commits, package installs, or external systems in observe mode unless the User has explicitly changed the mode. In `propose` or `act` mode, present an update brief before editing unless the User has already approved the exact change. Include:
   - current project state
   - checked sources with canonical locator, accessed-at time and timezone, version, commit or tag when relevant, section locator, claim supported, retrieval method, and ETag, Last-Modified, hash, or replay pointer when feasible
   - recommended changes and rejected changes
   - for external ideas used as input: allowed-use classification, project-neutral abstraction, rejected source-specific wording, commands, tools, product names, examples, taxonomy, workflow shape, and adoption or rejection decision
   - risk level, critical surfaces, and expected files
   - branch or backout posture when the update may need side-branch work or rollback
   - required approvals for version changes, dependency changes, feature changes, migrations, deploy changes, or irreversible actions
   - verification commands
9. Implement only approved project-local changes in `act` mode.
   Keep the patch minimal and project-consistent. Do not copy upstream code or
   assets without explicit approval and license review. In `propose` mode, stop
   after the approved proposal or report artifact. Keep every reusable framework
   candidate in the bounded handoff until semantic audit and framework
   improvement separately authorize and verify its effect.
10. Update project docs, comments, examples, or tests only when needed to keep the project accurate after the change.
11. Run the agreed verification commands. If a check cannot run, report the blocker and remaining risk.
12. In `propose` mode, include any proposed `SOURCE_PACKS.md`, `SOURCE_UPDATE.md`, `TODO.md`, or `DECISIONS.md` deltas inside the approved proposal or report artifact only; do not edit those operative files. In `act` mode, update `SOURCE_PACKS.md` when the approved source list, tier, volatility, acquisition method, or action rule changed, and update `SOURCE_UPDATE.md` when a source-check run, reviewed date, cadence, last-seen state, result, or open gap changed, only when each file is already receipt-declared mutable state; preserve its exact generated-state origin marker. If either optional source surface is absent, keep the proposed content in the report and route its enablement through an approved candidate-input refresh before resuming the write. Update receipt-declared `TODO.md` only for unresolved follow-up work. Record durable choices in receipt-declared `DECISIONS.md` when the project chooses to pin, upgrade, defer, or reject a source-derived change. If the project repeatedly rechecks a source family already covered by the framework, or discovers a high-quality source missing from the shared framework registry, keep a concise framework-source candidate in receipt-declared `SOURCE_PACKS.md` or the source-update proposal. Classify its ownership directly: a shared or reusable framework candidate routes to `task_orders/framework_semantic_audit.md`; invoke `task_orders/insights.md` only when its separate decision trigger applies.

Acceptance Criteria

- Current project state was inspected before relying on external sources.
- External sources were checked through the approved acquisition method and egress path and recorded with reproducible locators, versions, claim linkage, and retrieval state.
- Existing project and approved framework source registries were checked before redundant source research, or the reason for bypassing them was stated.
- Pinned versions were not silently upgraded.
- The User approved material version, dependency, feature, migration, deploy, or irreversible changes before implementation.
- Applied changes are limited to the approved update surface.
- Source Update did not directly edit a shared or reusable framework product
  surface; such a candidate was routed through semantic audit and framework
  improvement.
- Verification commands were run or blockers were reported.
- In `observe` mode, only the approved report artifact was written. In `propose` mode, only the approved proposal or report artifact was written. In `act` mode, receipt-declared `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` were updated when project source lists, review status, cadence, or source-run state changed and that update was approved; absent optional source surfaces were proposed for candidate-input refresh rather than created ad hoc.
- Rejected source-derived ideas are documented when they are likely to recur.
- User-supplied or agent-discovered external ideas were abstracted before any source-derived
  doctrine, source-pack entry, code, docs, examples, tests, or monitor root was
  proposed; source-specific wording and product surfaces were rejected unless
  explicitly authorized; and source registries were updated only for retained
  authority, evidence, or discovery roles.
- When applicable, overlapping first-party agent guidance was version-bound and
  used as a conditional primary technical source; duplicated maintained guidance
  was removed or narrowed, and both first-party-present and fallback routes
  remained explicit and verified.
- Any retained browser research digest used the public typed artifact contract,
  passed its linter, and remained evidence rather than instruction or adoption
  authority.

Notes

- For static sites, source-sensitive surfaces often include the site generator, theme, modules, shortcode/template APIs, build flags, asset pipeline, hosting adapter, accessibility guidance, and search or metadata requirements.
- Do not redesign a project merely because an upstream release added new features.
- Do not treat "latest" as automatically better than the project's pinned version.
- If the update surface becomes broad, split the work into a plan with explicit hold points before editing.
