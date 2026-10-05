# SEO Practice Guide
Use this Practice Guide for SEO help, indexing diagnosis, organic search troubleshooting, metadata cleanup, structured data work, JavaScript SEO review, local-business search hygiene, content search-readiness, or search appearance review.
Before making source-sensitive recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present. If the request concerns latest guidance, rich-result eligibility, spam policy, AI Search features, crawler behavior, agent-facing context, webmaster tools, or local-business eligibility, reopen the relevant official search-engine, schema, and platform docs.
## Evidence Hierarchy
For provider behavior, eligibility, requirements, policy, and crawler or agent rules, prefer current official search-engine, crawler, agent-facing website, and schema vocabulary documentation.
For site-specific diagnosis and measurement, prefer evidence in this order:
1. Project-owned Search Console, URL Inspection, crawl logs, analytics, and live server evidence.
2. Official provider documentation for the surface being diagnosed.
3. Rendered HTML, HTTP status/header checks, generated sitemap/robots output, and browser-visible content.
4. Public SERP observation, third-party SEO tools, Lighthouse, validators, and site crawlers.
5. SEO blogs, competitor pages, model output, and generic best-practice claims.
Classify SERP observations and third-party tool output as weak evidence unless corroborated by project-owned data or direct page inspection.
Use authenticated Search Console, Business Profile, analytics, URL Inspection, or account-visible tools only under an approved acquisition boundary or current User grant. Otherwise record the missing account evidence as a manual evidence gap.
## Workflow
1. Frame the objective.
- What is the goal: indexing, richer search appearance, traffic recovery, local visibility, or better qualified traffic?
- What is the scope: whole site, section, template, or URL set?
- What evidence exists: Search Console, URL Inspection, crawl logs, analytics, live HTTP, generated output, example queries, or only symptoms?
- Which surface matters: ordinary Google Search, Google Images, local results, Discover, Bing, rich results, AI features, crawler access, agent-facing context, or another surface?
- Which provider's behavior is being judged, and which official source currently documents that behavior?
2. Check crawlability and indexability first.
- Verify status codes, redirects, canonicals, robots rules, `noindex`, duplicate URL patterns, true 404 behavior, and soft-404 risk.
- `robots.txt` controls crawling, not guaranteed indexing. Keep a URL crawlable until a `noindex` directive can be observed. Canonical declarations are signals, not guarantees; align redirects, `rel="canonical"`, sitemaps, internal links, and, for localized variants, `hreflang`.
- Check that important pages are reachable through normal HTML links with `href`.
- Confirm that indexable pages return useful text content to anonymous users and that important resources are not blocked.
- Inspect generated link behavior when internal-link, outbound-link, canonical, or render-hook changes are in scope.
- For JavaScript apps, verify real URLs, server behavior, and rendered output.
- Treat sitemaps as support, not a substitute for internal linking; `lastmod` should be consistently and verifiably accurate and reflect the last significant page update, not trivial changes.
3. Check search appearance.
- Review `<title>` quality, uniqueness, boilerplate, and page-specific description.
- Check canonical, favicon, robots, image metadata, visible intro, and page-type metadata for consistency with the visible page. Check Open Graph and related tags when social, messaging, or link-preview consumers matter.
- Check structured data only when it is represented by user-visible page content and factually supportable.
- For Google Search generative AI features, apply normal Search technical and content requirements first: indexed, snippet-eligible, crawlable, visible, useful content remains the base requirement. Do not invent extra AI-discovery files, AI text files, or AI-specific markup requirements.
- When the provider exposes property-level inclusion or exclusion controls for the target feature, check the effective choice and any parent inheritance or child override using approved account evidence. Preserve the owner's intended participation; diagnosis does not authorize changing it. If account evidence is unavailable or unauthorized, record the gap rather than infer the setting from page markup.
4. Check page-level content quality.
- Evaluate whether each important page has a distinct purpose, audience, search intent, and useful content beyond boilerplate, but treat information architecture, narrative, and editorial strategy as observations for the accountable content or frontend owner, not as SEO-owned change authority. Keep proposed copy, page splits, and narrative changes as hypotheses until that owner approves them.
- Identify and inspect the parts that serve the page's purpose: text and headings, media, tools, relevant user contributions, and information revealed through interaction. Test the intended user task within the approved action boundary; introductory prose alone is insufficient evidence.
- Check for original information, firsthand experience, analysis, examples, evidence, expert judgment, or business-specific detail that goes beyond commodity summaries, as appropriate to the page's purpose.
- Assess the substantive work in the content or supporting system, added user value, execution quality, and factual reliability. Apply expectations appropriate to the purpose and potential harm; source attribution, production method, and length are not substitutes for that assessment.
- Match expertise to the claim: ordinary experience need not have specialist credentials, while consequential factual claims require authoritative corroboration and consistency with established domain consensus where applicable.
- Flag thin reference pages, generic service pages, copied-looking wording, and near-duplicate pages when there is evidence.
- Do not split pages only to capture every fan-out query, long-tail wording variant, or AI-search phrasing unless each page has a distinct useful purpose for humans.
- For AI-assisted content, check accuracy, editorial responsibility, originality, and usefulness.
5. Check answer-engine clarity without inventing new SEO surfaces.
- Important entities, services, locations, authors, dates, and relationships should be explicit in visible text where they matter.
- Key claims should be concise enough to quote or summarize, but still written for people.
- Do not create pages only to feed answer systems if they would not be useful to the intended human audience.
6. Check media, ecommerce, and local eligibility when relevant.
- Use high-quality images and video where they genuinely help the page answer the user's need; verify image and video SEO through the official docs when those surfaces matter.
- For ecommerce, distinguish on-site content and structured data from product-feed or Merchant Center work.
- For local businesses, distinguish on-site identity, Business Profile, citations, and local prominence instead of treating every local-visibility issue as page copy.
- Check whether the business has claimed and maintained its Google Business Profile when Google local visibility is in scope and the property is controlled.
- Check whether the site is verified in Search Console when Google Search evidence is in scope and the property is controlled.
- Check whether official site, contact data, and public business details are consistent enough for knowledge panel and Maps understanding.
- Check `LocalBusiness` structured data only when it reflects visible on-page business information and the page is the right place for that entity data.
- Check major public citations, directories, social profiles, supplier or partner references, and legacy listings for name, address, phone, hours, category, and URL consistency when local visibility is in scope.
- Separate on-site defects from off-site citation, backlink, public-profile, and local-prominence opportunities.
7. Check agent-friendly website signals when task-relevant.
- If the site expects browser agents, buyer agents, booking agents, or AI-assisted comparison workflows, inspect screenshots, DOM, and the accessibility tree as separate evidence channels.
- Prefer stable layout, visible action states, semantic `<button>` and `<a>` elements, associated labels, clear names, and non-hidden actionable controls.
- Do not recommend `llms.txt` for Google Search. When a named non-Google service already consumes an agent-specific file, verify that service's current documentation, privacy scope, links, and parity with the canonical HTML.
- Treat agentic protocols or commerce-agent integrations as experimental, source-fresh, and product-specific until the project explicitly adopts them.
8. Check migration, legacy URL, and authority risks.
- Map legacy URLs with backlinks, citations, or historic indexation to the best current equivalent where supportable.
- Prefer direct permanent redirects for durable replacements.
- Return true 404 or 410 for removed content with no current equivalent.
- Check that redirects, canonicals, sitemap inclusion, and internal links converge on the same preferred URL set.
9. Check measurement and debugging paths.
- Prefer Search Console property data, URL Inspection, Rich Results Test, and page-level inspection over guesswork or public SERP snapshots.
- For a traffic or visibility change, check the target provider's official update and service-status history for the affected surface and market. Record announced start/completion dates and reporting delays; use comparable periods and the provider's current observation guidance. Temporal overlap is a diagnostic lead, not site-specific causal or policy-violation evidence. Continue repairing independently verified technical or security defects during a rollout.
- Recommend validation steps for each fix.
10. Use project-owned search data as an experiment loop when available.
- Use Search Console query/page exports, URL Inspection, crawl logs, and analytics to identify high-impression low-CTR pages, indexed pages with no impressions, important URLs that are not indexed, duplicate or cannibalized query targets, structured-data errors, and search-feature traffic questions.
- Use available feature-specific first-party reports alongside aggregate search data. Record feature scope, measured metric, attribution, aggregation unit, reporting period, availability limits, and overlap before comparing or combining results. Distinguish a missing report or unavailable value from measured zero; impressions alone do not establish clicks, conversions, ranking gains, or causal improvement.
- For Bing AI, Brave Search, DuckDuckGo, Kagi, OpenAI, Anthropic, or other named AI/search surfaces, use the target provider's official crawler, webmaster, source, citation, or AI-performance reports when available, but classify them as surface-specific evidence, not general ranking authority or proof of another provider's behavior.
- Turn each opportunity into a bounded hypothesis: title or snippet alignment, visible content gap, internal-link path, crawl/indexing defect, rendered-content defect, page-speed issue, schema mismatch, or page-purpose overlap.
- Record baseline date, affected URL or template cohort, exact change, validation method, and follow-up window. Do not infer causality from ranking screenshots, isolated query checks, or third-party scores alone.
## Structured Data
- Use structured data to clarify page meaning and qualify for applicable features, not to stuff invisible facts into the page.
- Prefer JSON-LD when the project setup allows it, unless project policy forbids scripts entirely and uses another valid markup approach.
- Choose the narrowest correct type that matches the visible page and business reality.
- Do not add rich-result markup for content that is not visible, not supportable, or not the page's real focus.
- Validate markup with the relevant official tool and inspect rendered source.
- Measure impact with Search Console over time when the site has enough data. Do not assume structured data improves rankings.
## Static-Site And Security Coupling
- Host headers, forwarded headers, redirects, and canonical generation must not let an attacker poison canonical URLs, Open Graph URLs, or absolute links.
- Error pages should return the correct HTTP status and avoid soft-404 behavior.
- Security headers, CSP, HSTS, cache policy, compression, and redirects may be configured outside the repository; verify live behavior before making claims.
- External resources, scripts, iframes, analytics, and embeds can affect privacy, performance, crawlability, and trust.
- Hacked content, injected links, cloaking, malicious redirects, and deceptively concealed content are search-quality and security issues.
## Output
Present findings in this order:
1. Indexing blockers
2. Search appearance issues
3. Structured data or page-meaning issues
4. Content-quality or information-architecture observations routed to the accountable content/frontend owner
5. Local, off-page, or entity issues
6. Measurement gaps
For each finding, provide affected URL or page type, evidence observed, why it matters for the relevant search surface, the smallest credible fix, and how to validate it. Label recommendations as confirmed, likely, or hypothesis.
## Guardrails
- Do not promise rankings, traffic, or crawl timing.
- Separate human evaluation criteria from verified provider ranking behavior; a rubric or documentation revision alone does not establish ranking inputs, weights, or the cause of a site's traffic change.
- Do not recommend keyword stuffing, doorway pages, deceptively hidden text or links, fake structured data, or manipulative link schemes. Accessible disclosure and text for assistive technology are not concealment abuse; verify actual access and behavior.
- Do not claim a sitemap is mandatory when a site is small and comprehensively internally linked.
- Do not recommend structured data for content that users cannot see.
- Do not recommend new machine-readable AI files, AI text files, AI-crawler allowlists, or AI-specific markup as requirements for Google Search AI features or any other search surface without current provider-specific documentation.
- Do not generalize Google, Bing, Brave, DuckDuckGo, Kagi, OpenAI, Anthropic, or crawler-specific guidance to another provider without current provider-specific evidence.
- Do not treat "AEO" or "GEO" as a separate Google Search optimization discipline unless the task explicitly targets another non-Google surface with its own current documentation.
- Do not recommend chunking, rewriting, inauthentic mentions, or schema-first work merely because the target surface uses generative AI.
- Treat each provider user agent separately: automatic search or discovery crawlers, training crawlers, and user-triggered agents or fetchers can have different robots behavior and visibility effects. Verify each user-agent policy; do not assume one rule controls all products, user-triggered fetches, indexing, or URL-only references.
- Do not recommend separate doorway pages for near-identical city, service, or keyword variants.
- Do not add outbound links only for SEO decoration.
- Do not treat off-page citation problems as on-site copy defects.
- Do not turn Search Console warnings, validator output, or Lighthouse scores into source edits before classifying the finding.
- Do not treat page speed work as a replacement for relevance, discoverability, or useful content.
- Do not infer business facts, legal status, opening hours, service areas, awards, prices, or regulated qualifications from competitor pages or generic SEO examples.
- Do not use generative AI to mass-produce content without editorial responsibility, factual review, and user value.
- Separate confirmed issues from hypotheses.
## Verification Profiles
- Metadata or copy review: inspect built HTML for title, meta description, canonical, robots, headings, visible opening text, internal links, image context, and schema if present.
- Crawl and indexing review: check HTTP status, redirects, canonical URL, robots meta, `robots.txt`, sitemap inclusion, internal links, and live anonymous access; use URL Inspection when available.
- Structured data review: inspect rendered markup, validate with official tools, confirm that the marked-up entity or content is user-visible and that each property is accurate, supportable, and permitted by the feature-specific documentation, and record date, URL or snippet, result, and accepted limitations.
- Local-business review: verify Search Console and Business Profile status when available, compare visible business details with legal/contact pages and major citations, and separate on-site fixes from off-site cleanup.
- Agent-friendly website review: inspect rendered screenshots, DOM, accessibility tree, labels, roles, focusability, layout stability, overlays, and visible action targets for the key user journey.
- Agent-facing context review: inspect `/llms.txt`, Markdown mirrors, canonical HTML links, sitemap/robots interaction, private-content exclusions, content parity, and provider-specific crawler or agent documentation for any agent-facing files the project deliberately publishes.
- Full search-readiness audit: combine crawl/indexing, metadata, content quality, structured data, local/entity, image, mobile/page-experience, privacy/deployment, and measurement checks.
