# Skills

Each directory holds one `SKILL.md` with a `name` and a `description`. A project copies the directories it uses into its skill folder; the [README](../README.md#set-up-a-project) has the commands. The `core` skills suit most projects, and a `languages` or `platforms` skill belongs only where that stack is in use.

A stack skill (the `languages` list, the `platforms` list, `mpa-kubernetes`, `mpa-infrastructure-as-code`, and `mpa-agent-inputs`) holds what changed in recent releases of its stack and checks that are easy to miss; a coverage line at its top says which versions it is current to, when that was checked, and where the stack publishes release notes. Every other skill holds steps that change what an agent does.

| Skill | Category | Covers |
|---|---|---|
| `mpa-review` | core | Reviewing a diff, branch, or subsystem |
| `mpa-external-contribution` | core | Outside pull requests, patches, copied code |
| `mpa-incident` | core | Compromise, leaked secrets, data loss |
| `mpa-dependency-change` | core | Adding or upgrading packages and plugins |
| `mpa-root-cause` | core | Finding the cause of a failure |
| `mpa-migration` | core | Schema and data changes, code ports and rewrites, backing out |
| `mpa-research` | core | External facts the repository cannot settle |
| `mpa-delegation` | core | Helper agents, parallel sessions, unattended runs |
| `mpa-secure-coding` | security | Authentication, authorization, input, endpoints, command strings, secrets |
| `mpa-security-audit` | security | Vulnerability audits |
| `mpa-agent-inputs` | agents | Untrusted text reaching models and tools; Model Context Protocol release changes |
| `mpa-agent-instructions` | agents | Prompts, instruction files, skills, evaluations |
| `mpa-database` | data | Credentials, grants, pooling, generated SQL, recovery |
| `mpa-data-privacy` | data | Personal and production data |
| `mpa-ci-pipeline` | infra | CI/CD workflows, runners, publish jobs, container images |
| `mpa-kubernetes` | infra | Kubernetes and Gateway API release changes and checks |
| `mpa-infrastructure-as-code` | infra | Terraform and OpenTofu release changes and IaC checks |
| `mpa-web-frontend` | web | HTML, forms, ARIA, CSS, rendered result |
| `mpa-seo` | web | Indexing, metadata, structured data |
| `mpa-python` | languages | Python release changes and checks |
| `mpa-javascript-typescript` | languages | TypeScript and Node.js release changes and checks |
| `mpa-go` | languages | Go release changes and checks |
| `mpa-rust` | languages | Rust and Cargo release changes and checks |
| `mpa-swift` | languages | Swift release changes and checks |
| `mpa-php` | languages | PHP and Laravel release changes and checks |
| `mpa-hugo` | platforms | Hugo release changes and checks |
| `mpa-wordpress` | platforms | WordPress release changes and checks |
| `mpa-apache-httpd` | platforms | Apache HTTP Server release changes, the patched release, and `.htaccess` |
| `mpa-nginx` | platforms | nginx release changes and the patched releases |

To customise a skill in a project, copy it to a directory name without the `mpa-` prefix. The update commands in the README replace the `mpa-*` skills this repository ships and leave other names alone.

## Other skills

Skills from other sources can sit beside these under a directory name without the `mpa-` prefix; the update commands in the README leave them untouched. Pin them to a commit.
