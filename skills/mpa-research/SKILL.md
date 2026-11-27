---
name: mpa-research
description: "Rules for looking up current external facts. Use when searching the web or checking official docs, changelogs, latest versions, prices, deprecations, advisories, or unpinned external services that the repository and installed copy cannot settle."
---

# Research

Answer from the repository and the installed copy first: the lockfile, pinned documentation, and installed source settle most questions about a dependency. Look outside when they cannot, because training data is a snapshot.

## Which sources

- Prefer official primary documentation for the exact version in use (reference, changelog, release notes, advisories), or source and tests at the matching tag. Mirrors, blogs, forums, and search snippets help locate the primary source; they do not replace it.

## Versions

- When the project pins a version, read the documentation for that version. Do not upgrade as a side effect of research.

## Report

- Give the sources in the reply: locator, version or date, and the fact taken from each.
