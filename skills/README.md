# Skills

Each directory holds one `SKILL.md` with a `name` and a `description`. `mpa.py init --skills` takes `core` (the default), `all`, `none`, a group, or a comma list of names and groups. `mpa.py update --add-skill` and `--remove-skill` take skill names, not groups, and change the set later. A name is accepted with or without the `mpa-` prefix.

| Skill | Group | Covers |
|---|---|---|
| `mpa-review` | core | Reviewing a diff, branch, or subsystem |
| `mpa-external-contribution` | core | Outside pull requests, patches, copied code |
| `mpa-incident` | core | Compromise, leaked secrets, data loss |
| `mpa-dependency-change` | core | Adding or upgrading packages and plugins |
| `mpa-root-cause` | core | Finding the cause of a failure |
| `mpa-migration` | core | Schema and data changes, backing out |
| `mpa-release` | core | Releases, deployments, publishing |
| `mpa-research` | core | External facts the repository cannot settle |
| `mpa-secure-coding` | security | Authentication, authorization, input, endpoints |
| `mpa-security-audit` | security | Vulnerability audits |
| `mpa-agent-inputs` | security | Prompt injection, tool servers, retrieval, agent memory |
| `mpa-agent-instructions` | security | Prompts, instruction files, skills, evaluations |
| `mpa-data-privacy` | security | Personal and production data |
| `mpa-database` | security | Credentials, grants, tenancy, SQL, DDL |
| `mpa-ci-pipeline` | infra | CI/CD workflows, runners, publish jobs |
| `mpa-containers` | infra | Containerfiles, images, registries |
| `mpa-kubernetes` | infra | Manifests and Helm charts |
| `mpa-infrastructure-as-code` | infra | IaC source, state, plans, platform configuration |
| `mpa-web-frontend` | web | HTML, forms, ARIA, CSS, rendered result |
| `mpa-seo` | web | Indexing, metadata, structured data |
| `mpa-python` | languages | Python packaging, threads, untrusted input |
| `mpa-javascript-typescript` | languages | Package shape, type stripping, untrusted input |
| `mpa-go` | languages | Go modules, toolchains, concurrency, unsafe code |
| `mpa-rust` | languages | Cargo manifests, unsafe Rust, operating-system boundaries |
| `mpa-swift` | languages | Swift concurrency, availability, persistence, build plugins |
| `mpa-php` | languages | PHP and Laravel security checks |
| `mpa-shell` | languages | Shell scripts and command-line wrappers |

To change a skill in a project, copy it to a directory name without the `mpa-` prefix. `mpa.py update` replaces the `mpa-*` skills it ships and leaves other names alone.
