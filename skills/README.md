# Skills

Each directory holds one `SKILL.md` with a `name` and a `description`. `mpa.py init --skills` takes `core` (the default), `all`, `none`, an installable bundle (`core`, `security`, `agents`, `data`, `infra`, `web`), or a comma list of skill names and bundles. `mpa.py update --add-skill` and `--remove-skill` accept skill names and installable bundles, space- or comma-separated (or via repeated flags), to change the set later. `languages` and `platforms` are individual-only pick-lists, not installable bundles; pick their skills by name. A name is accepted with or without the `mpa-` prefix. See [docs/cli.md](../docs/cli.md) for all CLI options.

A stack skill (the `languages` list except `mpa-shell`, the `platforms` list, `mpa-kubernetes`, `mpa-infrastructure-as-code`, and `mpa-agent-inputs`) holds what changed in recent releases of its stack and checks that are easy to miss; a coverage line at its top says which versions it is current to, when that was checked, and where the stack publishes release notes. Every other skill holds steps that change what an agent does.

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
| `mpa-agent-inputs` | agents | bundle | Untrusted text reaching models and tools; Model Context Protocol release changes |
| `mpa-agent-instructions` | agents | bundle | Prompts, instruction files, skills, evaluations |
| `mpa-delegation` | agents | bundle | Helper agents, parallel sessions, unattended runs |
| `mpa-database` | data | bundle | Credentials, grants, tenancy, SQL, DDL |
| `mpa-data-privacy` | data | bundle | Personal and production data |
| `mpa-ci-pipeline` | infra | bundle | CI/CD workflows, runners, publish jobs |
| `mpa-containers` | infra | bundle | Containerfiles, images, registries |
| `mpa-kubernetes` | infra | bundle | Kubernetes and Gateway API release changes and checks |
| `mpa-infrastructure-as-code` | infra | bundle | Terraform and OpenTofu release changes and IaC checks |
| `mpa-web-frontend` | web | bundle | HTML, forms, ARIA, CSS, rendered result |
| `mpa-seo` | web | bundle | Indexing, metadata, structured data |
| `mpa-python` | languages | individual | Python checks |
| `mpa-javascript-typescript` | languages | individual | JavaScript and TypeScript checks |
| `mpa-go` | languages | individual | Go release changes and checks |
| `mpa-rust` | languages | individual | Rust and Cargo release changes and checks |
| `mpa-swift` | languages | individual | Swift release changes and checks |
| `mpa-php` | languages | individual | PHP and Laravel release changes and checks |
| `mpa-shell` | languages | individual | Shell scripts and command-line wrappers |
| `mpa-hugo` | platforms | individual | Hugo release changes and checks |
| `mpa-wordpress` | platforms | individual | WordPress release changes and checks |
| `mpa-apache-httpd` | platforms | individual | Apache HTTP Server release changes, security fixes, and `.htaccess` |
| `mpa-nginx` | platforms | individual | nginx release changes and security fixes |

To customise a skill in a project, copy it to a directory name without the `mpa-` prefix. `mpa.py update` replaces the `mpa-*` skills it ships and leaves other names alone.

## Other skills

Skills from other sources can sit beside these under a directory name without the `mpa-` prefix; `mpa.py update` leaves them untouched. Pin them to a commit.
