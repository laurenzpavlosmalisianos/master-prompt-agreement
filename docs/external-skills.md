# External first-party skills

This guide lives only in the Master Prompt Agreement repository. Installed MPA files under `templates/` and `skills/mpa-*/` stay offline, link-free, and original Apache-2.0 text with no bundled third-party skills or licences.

Projects can pair MPA with vetted first-party vendor skills as **additive companions** when a platform or security vendor ships up-to-date lookup guidance or multi-phase audit tooling that complements MPA's static checklists.

## Additive companions

| Vendor repository | Pairs with | Role alongside MPA |
|---|---|---|
| [GoogleChrome/modern-web-guidance-src](https://github.com/GoogleChrome/modern-web-guidance-src) | `mpa-web-frontend` | Supplies current web-platform lookup guidance and browser-compatibility checks alongside MPA's accessibility, DOM, and rendering verification rules. |
| [cloudflare/security-audit-skill](https://github.com/cloudflare/security-audit-skill) | `mpa-secure-coding`, `mpa-security-audit` | Supplies multi-phase security audit workflows alongside MPA's secure-coding checks and audit rules of engagement. Invoke Cloudflare's audit skill explicitly during dedicated multi-phase audits so its audit report format does not collide with `mpa-security-audit`'s report structure. |

## Additive-companion rules

- **Keep committed `mpa-*` skills intact:** do not delete overlapping `mpa-*` skills when installing a local or user-level external companion. Teammates and cloud sessions running without local plugins rely on the repository's committed `mpa-*` skills and would lose coverage if they were removed.
- **Keep namespaces separate:** install workspace-level external skills under `.agents/skills/<name>/` or `.claude/skills/<name>/` without the `mpa-` prefix. `mpa.py update` never touches non-`mpa-*` directories. `mpa.py check` counts non-`mpa-*` directories in each skill folder and notes that they share the startup listing budget without opening or parsing their files.

## Vetting and pinning

Treat external skills, installer commands, and bundled scripts as privileged dependencies and untrusted agent inputs (see `mpa-dependency-change` and `mpa-agent-inputs`):

- **Do not run floating install one-liners:** avoid `npx ...@latest` commands or installers that pull a moving default branch.
- **Inspect before installing:** read `SKILL.md`, every bundled script, and any requested tool permissions or hooks before adding the skill to a developer machine or repository.
- **Pin an exact version or commit SHA:** record the exact package version, tag, or commit SHA you reviewed, disable unreviewed auto-updates, and review upgrades as diffs before adopting them.

`CONTRIBUTING.md` sets the first-party vendor admission criteria for this page, and `tools/hygiene.py` allows only these exact HTTPS repository root URLs here.
