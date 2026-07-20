# Source-Grounded Research Practice Guide

<!-- mpa-clause-projections: msa-2-5 -->
Use this Practice Guide for research tasks where correctness, recency, and source quality matter more than speed. It enforces source hierarchy, date discipline, decisive-evidence extraction, and separation of fact from inference.

## Evidence Record

For decision-relevant claims, record the smallest useful evidence record:

1. claim
2. source owner and source type
3. locator, version, publication status, and access date
4. claim scope and whether the evidence is direct or interpretive
5. decisive fact or excerpt
6. conflicts, confidence, and open gaps

Retain durable source-backed facts only through an approved state surface or explicit task grant. The record must include verification state, locator, version or date, scope, validation method, and the owning surface's checked or reviewed timestamp. Distinguish an unchecked hypothesis from a directly inspected source statement, and distinguish both from a validated claim. Treat a claim as validated only when the method is sufficient for its type: authoritative normative evidence for the applicable rule, measured target behavior for runtime claims, or appropriate replication, measurement, or triangulation for empirical, performance, security, causal, or benchmark claims. Use the approved owning surface's field names and closed statuses rather than inventing a parallel vocabulary. Otherwise use bounded wording such as “the source reports.” Store only the minimum source locator and validation metadata needed; do not retain secrets, credentials, personal data, private source text, or confidential excerpts unless explicitly required and permitted.

## Durable Research Workspaces

For maintained research workspaces that should compound across sessions or agents, use portable repository-native records with explicit metadata and tolerant readers:

1. catalog layer: stable item identity, topic, source inventory, claim status, dates, locators, tags, ordinary links, and short summaries
2. synthesis layer: source-backed concepts, entities, comparisons, decisions, contradictions, and open questions
3. evidence layer: raw source material or immutable source pointers, used only when the lighter layers cannot answer the question

Before ingesting more material or launching discovery, check whether the existing catalog and synthesis layers already answer the question. Treat new user-provided sources as an append operation; treat broader discovery as a separate opt-in operation with a budget, source boundary, and output contract. Keep question logs as pointers to updated knowledge artifacts instead of duplicating long answers in many places.

When a durable operation is authorized to update the workspace, record it in the approved activity log with operation type, sources added or checked, material outputs changed, skipped or inaccessible items, and remaining questions. Define the side-effect boundary before the operation: true read-only query, append provided sources, discover new sources, update synthesis, or health-check only. A true read-only query makes no workspace change and reports in conversation; an append-only activity log is permitted only when that exact sink was pre-approved as the sole write.

Run health checks on durable research workspaces when their output will influence maintained guidance: orphaned sources, broken links, stale claims, unsupported synthesis, unresolved contradictions, missing source metadata, and open questions that block adoption.

## Browser Research Digests

When an authorized task retains a completed browser research report, copy
`project_state_templates/SOURCE_DEEP_RESEARCH.md` to the approved task evidence
path and follow `docs/source_deep_research_artifacts.md`. Do not use that
artifact for a plan, progress surface, sidebar, history item, or ordinary source
check. Its typed completion, extraction, disposition, verifier-role,
claim-class, method, and evidence-role fields carry machine state; free prose
records bounded evidence and limitations only. Passing its linter never turns
the report, its citations, or reviewer agreement into source authority.

## Iterative Evidence-Seeking Workflows

Use this pattern when a research task spans a large source, tool, or data universe and the agent must decide what evidence to seek before it can answer.
1. Start each step by naming the missing evidence, contradiction, or subquestion that would change the answer.
2. Retrieve or expose only the smallest relevant source or tool candidates from the catalog; candidate retrieval is not commitment. Validate source or tool authority, scope, permission, and freshness before use.
3. Record a step trace: subquestion, selected source or tool, selection reason, decisive output or locator, interpretation, insufficiency or conflict, and next evidence need.
4. Summarize long outputs only as derived evidence with pointers to the raw source, execution trace, or immutable locator. Do not let summaries become the only support for material claims.
5. Structured reports and final answers may cite only sources or tools actually inspected in the trace. Validate citation labels against the trace before publication or durable retention.

## Workflow

1. Define the question precisely.
- state the exact decision or output that will use the answer
- identify which part is stable, version-sensitive, or volatile

2. Choose evidence by claim type.
- standards and official docs for normative or API behavior
- version-matched source code, tests, and release notes for implementation behavior
- independent or replicated empirical evidence for performance, security, or benchmark claims
- vendor claims for vendor surfaces only, not as cross-provider doctrine

3. Build a source ladder.
- `[standard]`: standard, specification, or authoritative public requirement
- `[official-doc]`: official project, language, platform, or public authority documentation
- `[vendor-doc]`: provider documentation, release note, model card, security page, or changelog
- `[official-implementation]`: official source repository, tagged release, or canonical implementation
- `[research]`: peer-reviewed or author-published research, dataset, benchmark, or reproducible study
- `[case-study]`: case-study evidence, not doctrine
- `[case-study-root]`: recurring parent root for case-study evidence or discovery only; not doctrine without exact claim-specific verification
- `[commentary]`: source discovery or hypothesis generation
- `[ai-summary]`: orientation only; not doctrine and not claim evidence unless the task is specifically about that generated artifact

Use lower-tier sources without substitution authority only for discovery, hypothesis generation, interpretation, or claims specifically about that material. When primary evidence is inaccessible, report the failed access and keep the material claim unresolved unless the User approves a scoped, labeled lower-tier substitution with residual risk. Do not treat personal forks, snippet-host entries, private-person repositories, unofficial prompt packs, or anonymous collections as public framework authority unless the task is explicitly about that artifact and the reference is labeled non-normative.

4. Gather decisive evidence before synthesis.
- extract decisive facts first when the source set is long or noisy
- prefer facts, locators, and paraphrase over copied source text; quote only the minimum short excerpt needed to resolve a claim, and record permission, license, confidentiality, redistribution limits, or excerpt-limit uncertainty when it affects quoting, paraphrase, retention, or publication
- save exact dates, versions, scope limits, source conflicts, and missing evidence
- for research sources, record publication status, peer-review status, dataset or benchmark version, conflicts when stated, replication status, and whether the claim needs superseding-version or correction checks

5. Separate fact from inference.
- Fact: directly supported by the source
- Inference: derived from multiple facts
- Speculation: plausible but not sufficiently supported

6. Synthesize only after contradiction check.
- If sources disagree, say so.
- If the latest source changes an earlier assumption, update the assumption.
- If the evidence is weak, lower confidence instead of overstating.

7. Abstract external ideas before adoption.
- for user-supplied or agent-discovered articles, repositories, papers, videos, transcripts, social posts, demos, or product pages, first state the candidate abstraction in original project-neutral language
- name the transferable failure mode, quality pattern, guardrail, or source-monitoring reason; its applicability limits; and the source-specific wording, commands, tools, product names, taxonomies, screenshots, examples, claims, or scope being rejected
- do not retain a source, add a monitor root, or edit reusable guidance only because the source was reviewed; retention needs an independent authority, evidence, or discovery-filter reason
- if the abstraction cannot be stated without copying source expression or depending on the source's product-specific surface, reject it or keep it in a project-local proposal until the User approves a product-specific dependency

8. Use independent reviewers only as evidence lanes.
- use `task_orders/orchestrate.md` for live lane manifests, evidence packets, authority and data boundaries, lifecycle, first-pass isolation, coordinator validation, and post-blind review
- for high-impact, disputed, or broad source-derived changes, split review by topic and file only when each lane receives a coherent claim set small enough for direct source checking
- before accepting a research finding, validate it against the cited primary source and this guide's Evidence Record. Reviewer agreement cannot upgrade source quality or confidence, or cure missing evidence
- if blind review exposes a material technical dispute that requires a further round, use `task_orders/arbitrate.md`. Do not use repeated reviewer rounds to promote weak source evidence into doctrine

## Output

Provide:

1. answer
2. evidence records or summary
3. exact source locators, such as URLs, file paths, repository tags or commits, section IDs, artifact IDs, or document/page references, subject to confidentiality constraints
4. confidence level
5. open questions or evidence gaps
6. acceptance evidence, objective checks, manual acceptance items, and unverifiable residuals when the research supports implementation, publication, compliance, or another acceptance-gated decision
7. for external idea reviews, the accepted abstraction, rejected source-specific material, retained-source rationale or no-retention decision, and any reviewer-lane or arbitration evidence used

## Guardrails

- Do not use stale memory for volatile facts.
- Do not retain or reproduce secrets, credentials, personal data, private source text, or confidential excerpts unless explicitly required and permitted.
- Do not present inference as fact.
- Do not hide source conflicts.
- Do not cite low-quality summaries when a primary source is available.
- Do not skip dates for time-sensitive claims.
- Do not synthesize first and hunt for support later.
- Do not copy external wording or product-specific workflow shape into reusable guidance when the approved outcome is only a pattern abstraction.
- Do not retain or reproduce full public articles, posts, documentation pages, repository docs, transcripts, screenshots, or source dumps; keep locators, decisive facts, and minimal permitted excerpts.
