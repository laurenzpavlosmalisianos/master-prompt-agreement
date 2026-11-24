# Skills

Each directory holds one `SKILL.md` with a `name` and a `description`. `mpa.py init --skills` takes `core` (the default), `all`, `none`, an installable bundle (`core`, `security`, `agents`, `data`, `infra`, `web`), or a comma list of skill names and bundles. `mpa.py update --add-skill` and `--remove-skill` accept skill names and installable bundles, space- or comma-separated (or via repeated flags), to change the set later. `languages` and `platforms` are individual-only pick-lists, not installable bundles; pick their skills by name. A name is accepted with or without the `mpa-` prefix. See [docs/cli.md](../docs/cli.md) for all CLI options.

| Skill | Category | Install | Covers |
|---|---|---|---|
| `mpa-review` | core | bundle | Reviewing a diff, branch, or subsystem |
| `mpa-external-contribution` | core | bundle | Outside pull requests, patches, copied code |
| `mpa-incident` | core | bundle | Compromise, leaked secrets, data loss |
| `mpa-dependency-change` | core | bundle | Adding or upgrading packages and plugins |
| `mpa-root-cause` | core | bundle | Finding the cause of a failure |
| `mpa-migration` | core | bundle | Schema and data changes, code ports and rewrites, backing out |
| `mpa-release` | core | bundle | Releases, deployments, publishing |
| `mpa-research` | core | bundle | External facts the repository cannot settle |
| `mpa-secure-coding` | security | bundle | Authentication, authorization, input, endpoints |
| `mpa-security-audit` | security | bundle | Vulnerability audits |
| `mpa-agent-inputs` | agents | bundle | Prompt injection, tool servers, retrieval, agent memory |
| `mpa-agent-instructions` | agents | bundle | Prompts, instruction files, skills, evaluations |
| `mpa-database` | data | bundle | Credentials, grants, tenancy, SQL, DDL |
| `mpa-data-privacy` | data | bundle | Personal and production data |
| `mpa-ci-pipeline` | infra | bundle | CI/CD workflows, runners, publish jobs |
| `mpa-containers` | infra | bundle | Containerfiles, images, registries |
| `mpa-kubernetes` | infra | bundle | Manifests and Helm charts |
| `mpa-infrastructure-as-code` | infra | bundle | IaC source, state, plans, platform configuration |
| `mpa-web-frontend` | web | bundle | HTML, forms, ARIA, CSS, rendered result |
| `mpa-seo` | web | bundle | Indexing, metadata, structured data |
| `mpa-python` | languages | individual | Python packaging, threads, untrusted input |
| `mpa-javascript-typescript` | languages | individual | Package shape, type stripping, untrusted input |
| `mpa-go` | languages | individual | Go modules, toolchains, concurrency, unsafe code |
| `mpa-rust` | languages | individual | Cargo manifests, unsafe Rust, operating-system boundaries |
| `mpa-swift` | languages | individual | Swift concurrency, availability, persistence, build plugins |
| `mpa-php` | languages | individual | PHP, Composer, and Laravel security checks |
| `mpa-shell` | languages | individual | Shell scripts and command-line wrappers |
| `mpa-hugo` | platforms | individual | Hugo templates, rendering security, modules, builds |
| `mpa-wordpress` | platforms | individual | WordPress plugins, themes, REST APIs, hardening |

To customise a skill in a project, copy it to a directory name without the `mpa-` prefix. `mpa.py update` replaces the `mpa-*` skills it ships and leaves other names alone.

## External companion skills

This repository ships only its own original Apache-2.0 Markdown skills and bundles no third-party files or links. Teams can pair MPA with vetted first-party vendor skills as additive companions—keeping committed `mpa-*` skills intact so teammates and cloud sessions without local plugins retain full coverage. Install workspace-level companions without the `mpa-` prefix; `mpa.py update` leaves them untouched, and `mpa.py check` counts non-`mpa-*` skill directories sharing the startup budget without opening or parsing their files. See [docs/external-skills.md](../docs/external-skills.md) for vetted companions and pinning rules.
