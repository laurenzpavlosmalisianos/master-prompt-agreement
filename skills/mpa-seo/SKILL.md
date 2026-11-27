---
name: mpa-seo
description: "Checks for search indexing. Use when changing robots.txt, noindex, canonical URLs, redirects, sitemaps, hreflang, page metadata, or structured data, or when diagnosing why pages are not indexed. For HTML, CSS, ARIA, or DOM rendering, use mpa-web-frontend."
---

# Search indexing

Search engine behaviour, eligibility rules, and crawler policies differ by provider and change often. Where a decision turns on one, check that provider's current official documentation, and do not carry one provider's guidance over to another.

## Crawling and indexing

- Important pages need ordinary `<a href>` links and content that anonymous visitors receive; for JavaScript applications, check real URLs, server status codes, and rendered output, and put the canonical in the served HTML. Do not serve `noindex` on a page that script is meant to make indexable; a crawler may skip rendering a page that arrives with it.
- Replaced content gets a direct permanent redirect, kept as long as possible, and at least a year after a site move; removed content with no equivalent returns 404 or 410, not a "not found" page with HTTP 200 (soft 404).
- Search crawlers, training crawlers, and user-triggered fetchers can follow different robots rules, and some providers set generative-AI use in account settings as well as `robots.txt`; check each user agent and setting.

## Metadata and structured data

- For generative search features, ordinary requirements apply: indexable, snippet-eligible, useful visible content. Do not present `llms.txt`, special markup, or separate rewrites for answer engines as requirements unless that provider's current documentation says so.

## Claims

- Do not promise rankings, traffic, or crawl timing.
- A traffic change coinciding with a provider update is a lead, not a cause.
- State each proposed change as a hypothesis with a baseline date, the URL set, the exact change, how it is validated, and when to look again. A missing report is not a measured zero.
- Label each conclusion as confirmed, likely, or hypothesis.
