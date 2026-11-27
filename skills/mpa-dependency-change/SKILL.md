---
name: mpa-dependency-change
description: "Checks for adding, upgrading, replacing, or patching a dependency, editor extension, MCP server, or agent plugin or skill. Use when installing a new package, changing a pinned version or lockfile, adding a registry, or handling a CVE or vulnerability advisory."
---

# Dependency change

If a suspicious package, install hook, or suggested recovery command has already run, stop and use the `mpa-incident` skill.

## Check the artifact that will be installed

- Confirm the package exists under that exact name, scope, and registry. Models produce plausible package names that do not exist, and attackers register them; do not resolve a missing import by installing the closest-looking name.
- Editor extensions and agent plugins, skills, and tool servers are dependencies with broad access: pin versions, turn off unreviewed auto-update, and read activation scripts and bundled binaries.
- With public and private registries together, map each private name to its registry, or use an index policy that fails closed. Public fallback for a private name is the dependency-confusion path.
- A release that is hours old has had little time for a malicious publish to be noticed. Where the project has a minimum release age, an urgent fix goes through an explicit exception, not around the gate. Quarantine and minimum-release-age settings differ by registry, package manager, and version; check the current official documentation of the one in use before relying on either.

## Vulnerabilities and licences

- Rank advisories by whether the affected code is reachable, exposed, and known to be exploited, checking affected versions against the registry or vendor advisory; scanner severity and clean audit commands do not replace these checks.
- When an advisory on shipped code is suppressed and not fixed, record the advisory, the package and version, the reason the code is not reachable, and an expiry.

## Report

- Package, exact version, registry, licence, what was checked, what was not, and whether install scripts ran.
