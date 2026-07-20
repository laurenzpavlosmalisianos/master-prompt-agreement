Annex B - Agent Capabilities (CAPABILITIES.md)

_Describes the Agent runtime, available tools, technical strengths, and verified limits. Capability describes what is technically possible; it never grants authority._

Runtime Manifest

[Document only facts verified for this project or runtime.]

- Agent or runtime identifier: [model, product, CLI, IDE, hosted routine, local loop, or browser-backed surface]
- Tool surfaces: [filesystem, shell, browser, MCP, connectors, subagents, code interpreter, renderers, simulators, other]
- Native instruction and enforcement surfaces: [entrypoints or path-scoped rules, skills, hooks, permissions, extensions, verified lifecycle coverage and enforcement-strength evidence, or none]
- Execution boundary: [host process / container / VM / cloud worker / browser session / other]
- Workspace boundary: [read roots, write roots, mounts, ignored paths, protected paths]
- Network boundary: [none / approved fetch path / browser only / allowlist / general egress]
- Connected services and identity: [none / User session / service account / connector / token source]
- Memory or state surfaces: [none / project files / approved memory store / automation memory / other]
- Last verified: [date, method, and evidence]

Primary Specializations

[List what this Agent is best at. Examples:]

- Python (systems programming, CLI tools, data pipelines)
- Rust (memory-safe systems, CLI applications)
- TypeScript (full-stack, strict mode)
- Static site generation and content builds
- SQL and relational query optimization

Secondary Capabilities

[List supporting skills. Examples:]

- Shell scripting
- Git history inspection and conflict diagnosis
- Containers and composition
- CI/CD pipeline authoring and release automation
- Technical writing, documentation, READMEs, and changelogs

Known Limits

[Be honest about what the Agent cannot verify or do without more authority or tooling.]

- Cannot infer current facts, laws, prices, model behavior, platform defaults, or security guidance without checking current approved sources.
- Cannot verify visual output unless an approved browser, screenshot, renderer, simulator, or device-inspection tool is available. Flag unverified visual claims as manual or tool-blocked acceptance items.
- Cannot use authenticated services unless an approved credential or session mechanism exists and the task authorizes that use.
- Cannot persist memory across sessions unless the project defines an approved memory or state surface and the current task grants the write.
- Context window is finite. For large codebases, work in focused slices with explicit evidence and handoff boundaries.

Notes

- This annex is optional. If omitted, the Agent operates with its default capabilities and the SOW authority boundary.
- Update this annex when the model, runtime, tool or native instruction and enforcement surface, execution boundary, or connected services change.
- This annex grants no authority. Runtime authority comes from platform and tool restrictions, the current User task, the MSA, and the SOW. `AGENT_PROJECT.md` projects SOW terms; Task Orders provide subordinate procedure.
