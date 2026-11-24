---
name: mpa-seo
description: "Checks for search indexing. Use when changing robots.txt, noindex, canonical URLs, redirects, sitemaps, hreflang, page metadata, or structured data, or when diagnosing why pages are not indexed. For HTML, CSS, ARIA, or DOM rendering, use mpa-web-frontend."
---

# Search indexing

Search engine behaviour, eligibility rules, and crawler policies differ by provider and change often. Where a decision turns on one, check that provider's current official documentation, and do not carry one provider's guidance over to another.

## Evidence

- Strongest first: the site's own search console data, URL inspection, crawl logs, and live HTTP responses; then the provider's documentation; then rendered HTML and build output. Third-party tools, observed result pages, and lab scores are weak unless corroborated.
- Headers, redirects, and status codes are often configured outside the repository; check live responses before making a claim about them.
- Diagnosing with an account does not include changing that account's settings.

## Crawling and indexing

- `robots.txt` controls crawling, not indexing. A URL blocked there cannot show its `noindex`, so keep it crawlable until `noindex` is seen.
- A canonical is a signal, not a directive. Keep redirects, `rel="canonical"`, sitemaps, internal links, and `hreflang` aligned on one preferred URL set so they do not contradict each other.
- Important pages need ordinary `<a href>` links and content that anonymous visitors receive; for JavaScript applications, check real URLs, server status codes, and rendered output.
- Replaced content gets a direct permanent redirect; removed content with no equivalent returns 404 or 410, not a "not found" page with HTTP 200 (soft 404).
- `lastmod` in a sitemap reflects real, significant changes.
- Host and forwarded headers must not set canonical, Open Graph, or absolute URLs; that is cache and metadata poisoning.
- Search crawlers, training crawlers, and user-triggered fetchers can follow different robots rules; check each user agent.

## Metadata and structured data

- Keep title, H1, description, canonical, and structured data consistent with visible page content. Add structured data only for visible content with the narrowest correct type, and validate it with the provider's tool; eligibility does not promise ranking.
- For generative search features, ordinary requirements apply: indexable, snippet-eligible, useful visible content. Do not present `llms.txt`, special markup, or separate rewrites for answer engines as requirements unless that provider's current documentation says so.
- Do not infer business hours, prices, service areas, or qualifications from competitors or examples.
- Text for assistive technology is not cloaking; hidden text or links, fabricated markup, and link schemes are.

## Claims

- Do not promise rankings, traffic, or crawl timing.
- A traffic change coinciding with a provider update is a lead, not a cause.
- State each proposed change as a hypothesis with a baseline date, the URL set, the exact change, how it is validated, and when to look again. A missing report is not a measured zero.
- Label each conclusion as confirmed, likely, or hypothesis.
