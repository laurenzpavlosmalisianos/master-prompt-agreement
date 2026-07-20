type SurfaceItem = Readonly<{
  label: string;
  href: string;
  note: string;
}>;

type SurfaceGroup = Readonly<{
  id: string;
  label: string;
  summary: string;
  items: readonly SurfaceItem[];
}>;

type RuntimeStep = Readonly<{
  title: string;
  body: string;
}>;

type QualityGate = Readonly<{
  title: string;
  status: "automated" | "judgment";
  body: string;
}>;

type ReaderPathItem = Readonly<{
  title: string;
  href: string;
  note: string;
}>;

type DiagramNode = Readonly<{
  id: string;
  title: string;
  lines: readonly string[];
  x: number;
  y: number;
  width: number;
  height: number;
  caption: string;
}>;

type DiagramEdge = Readonly<{
  from: string;
  to: string;
  label: string;
  path: string;
  labelX: number;
  labelY: number;
}>;

const runtimeSteps = [
  {
    title: "Root Context",
    body: "Resolve platform limits, the user task, the selected framework checkout, and the governed project root without loading generated project authority.",
  },
  {
    title: "Recovery Gate",
    body: "For an existing project, read the selected charter and then check the governed project root for the closed journal, lock, and recovery-temp control set before generated authority or state; any control stops ordinary work.",
  },
  {
    title: "Project Contract",
    body: "Only after the recovery gate is clear, load AGENT_PROJECT.md or the configured generated contract. Consult the SOW when routed for canonical or omitted terms, full task-specific checklists or acceptance terms, ambiguity, or contract revision.",
  },
  {
    title: "Runtime Packet",
    body: "Interpret the user request under the project contract, then check state headers and load only task-relevant records. Add only task-conditioned guidance and evidence.",
  },
  {
    title: "Specialist Guidance",
    body: "Use a runtime task module for a known workflow or the full Task Order when needed; add only relevant Practice Guides.",
  },
  {
    title: "Evidence And Verification",
    body: "Inspect files, diffs, logs, sources, and generated output before claims; run checks where objective invariants can be tested.",
  },
  {
    title: "Learning",
    body: "Treat source, review, and feedback output as candidate evidence. Route reusable framework candidates through report-only task_orders/framework_semantic_audit.md, then route only accepted candidates through task_orders/framework_improvement.md; keep project-local changes on their project route.",
  },
] as const satisfies readonly RuntimeStep[];

const refreshSteps = [
  {
    title: "Refresh: Plan And Backout Basis",
    body: "For a verified complete current-format instance, inspect without writing and create one canonical plan. The plan selects either the normal verified exact-preimage bundle or, only where permitted, the explicit ACCEPT-NO-POST-APPLY-BACKOUT exception; mutable-state retirement requires the bundle.",
  },
  {
    title: "Refresh: Approval And Acceptance",
    body: "Approve the exact plan digest and every required action or warning, apply once, verify every active profile, and inspect for exact-current acceptance.",
  },
  {
    title: "Lifecycle: Restore Or Recover",
    body: "Post-success restore exists only for the verified-bundle branch and only while the live postimage still matches. Interrupted transactions instead enter the separate closed-control route and permit only the reported exact-ID recovery action.",
  },
] as const satisfies readonly RuntimeStep[];

const surfaceGroups = [
  {
    id: "authority",
    label: "Authority",
    summary: "Canonical rule, project scope, and runtime projection surfaces.",
    items: [
      {
        label: "Master Service Agreement",
        href: "../../master_service_agreement.md",
        note: "Universal doctrine and precedence.",
      },
      {
        label: "Statement Of Work Template",
        href: "../../statement_of_work_template.md",
        note: "Downstream project contract shape.",
      },
      {
        label: "Operative Charter",
        href: "../../runtime/operative_charter.md",
        note: "Compact always-on runtime layer.",
      },
    ],
  },
  {
    id: "workflow",
    label: "Workflow",
    summary: "Procedures for recurring work shapes.",
    items: [
      {
        label: "Task Order Index",
        href: "../../task_orders/README.md",
        note: "Workflow selection and sequence.",
      },
      {
        label: "Workflow Catalog",
        href: "../../runtime/workflow_catalog.json",
        note: "Machine-readable workflow metadata.",
      },
      {
        label: "Task Modules",
        href: "../../task_orders/README.md#task-orders-vs-runtime-task-modules",
        note: "Compact views for known workflows.",
      },
    ],
  },
  {
    id: "quality",
    label: "Quality",
    summary: "Specialist standards and verification boundaries.",
    items: [
      {
        label: "Practice Guides",
        href: "../../task_orders/README.md#task-orders-vs-practice-guides",
        note: "Domain quality standards.",
      },
      {
        label: "Verification And Quality",
        href: "../verification_and_quality.md",
        note: "Deterministic checks and semantic review.",
      },
      {
        label: "Framework Quality Contract",
        href: "../../runtime/framework_quality_contract.json",
        note: "Structural registry for repeated mistake classes, guard classifications, and owning surfaces.",
      },
      {
        label: "Framework Semantic Audit Task Order",
        href: "../../task_orders/framework_semantic_audit.md",
        note: "Report-only ownership, boundary, lifecycle, and semantic review for reusable candidates.",
      },
      {
        label: "Framework Improvement Task Order",
        href: "../../task_orders/framework_improvement.md",
        note: "Proportional evaluation, authorized effect, verification, and disposition for accepted candidates.",
      },
    ],
  },
  {
    id: "state",
    label: "State",
    summary: "Downstream project state templates and feedback surfaces.",
    items: [
      {
        label: "Project State Templates",
        href: "../repository_taxonomy.md#template-boundaries",
        note: "Templates for active state, decisions, feedback, and source packs.",
      },
      {
        label: "Source And Feedback",
        href: "../source_and_feedback.md",
        note: "Source review and sanitized learning flow.",
      },
      {
        label: "Repository Taxonomy",
        href: "../repository_taxonomy.md",
        note: "Where each kind of file belongs.",
      },
    ],
  },
  {
    id: "lifecycle",
    label: "Lifecycle",
    summary: "Canonical setup, refresh, recovery, and optional managed-runtime surfaces.",
    items: [
      {
        label: "Getting Started",
        href: "../../GETTING_STARTED.md",
        note: "Initial generated-project setup only.",
      },
      {
        label: "Updating A Generated Project",
        href: "../../UPDATING.md",
        note: "Operator orientation for inspection, plan-bound backout-basis selection, approval, apply, backout, and recovery.",
      },
      {
        label: "Framework Refresh Task Order",
        href: "../../task_orders/framework_refresh.md",
        note: "Authoritative recovery gate, verified current-format refresh sequence, post-apply exact-current acceptance, and plan-bound restore contract.",
      },
      {
        label: "Integration Registry",
        href: "../../integrations/registry.json",
        note: "Registered entrypoints and optional wrapper outputs managed by the selected project instance.",
      },
    ],
  },
] as const satisfies readonly SurfaceGroup[];

const qualityGates = [
  {
    title: "Scripts",
    status: "automated",
    body: "Check schema, export, links, state, routing, rendering, and configured file-size ceilings.",
  },
  {
    title: "Semantic Review",
    status: "judgment",
    body: "Decide semantic fit, ownership, source abstraction, and architectural coherence; proportional improvement evaluates incremental output value.",
  },
  {
    title: "Reviewer Lanes",
    status: "judgment",
    body: "Challenge narrow evidence packets without granting authority to reviewer output.",
  },
  {
    title: "Export Boundary",
    status: "automated",
    body: "Check that the export excludes private state and matches declared paths, content, and symlink rules.",
  },
] as const satisfies readonly QualityGate[];

const readerPath = [
  {
    title: "First Read",
    href: "../concepts.md",
    note: "Understand authority, runtime packets, and the state model.",
  },
  {
    title: "Set Up A Project",
    href: "../downstream_setup.md",
    note: "Orient before using GETTING_STARTED.md and task_orders/init.md.",
  },
  {
    title: "Inspect Or Refresh An Instance",
    href: "../../UPDATING.md",
    note: "Classify existing state; use a verified complete current-format pair for planning, select the verified bundle or explicit no-backout basis, require exact-current acceptance, and keep closed-control recovery separate.",
  },
  {
    title: "Maintain The Framework",
    href: "../maintenance_and_release.md",
    note: "Use when changing framework files or preparing a public variant.",
  },
] as const satisfies readonly ReaderPathItem[];

const diagramNodes = [
  {
    id: "context",
    title: "Root Context",
    lines: ["user task", "selected ref", "project root"],
    x: 5,
    y: 60,
    width: 125,
    height: 125,
    caption: "Resolve the user task, selected local framework checkout, and exact governed project root without loading generated project authority.",
  },
  {
    id: "recovery",
    title: "Recovery Gate",
    lines: ["read charter", "root controls", "stop or recover"],
    x: 185,
    y: 60,
    width: 135,
    height: 125,
    caption: "Read the selected charter, then check the governed project root for the closed journal, lock, and recovery-temp control set; any control blocks generated authority and ordinary work.",
  },
  {
    id: "authority",
    title: "Project Contract",
    lines: ["AGENT_PROJECT.md", "SOW when needed"],
    x: 375,
    y: 60,
    width: 125,
    height: 125,
    caption: "When the recovery gate is clear, load the generated project contract; consult the SOW when routed for canonical or omitted terms, full task-specific checklists or acceptance terms, ambiguity, or contract revision.",
  },
  {
    id: "packet",
    title: "Runtime Packet",
    lines: ["charter + contract", "task-relevant state", "task route"],
    x: 555,
    y: 60,
    width: 145,
    height: 125,
    caption: "Interpret the user request under the contract, then load only state and guidance relevant to the task.",
  },
  {
    id: "work",
    title: "Agent Work",
    lines: ["inspect", "implement", "report"],
    x: 755,
    y: 60,
    width: 120,
    height: 125,
    caption: "Agent work remains bounded by authority, scope, and evidence.",
  },
  {
    id: "verification",
    title: "Verification",
    lines: ["checks + review", "refresh: plan basis", "apply + exact-current", "recovery: exact ID"],
    x: 390,
    y: 235,
    width: 220,
    height: 150,
    caption: "Verification combines deterministic checks with expert judgment. A refresh plan selects the normal verified-bundle basis or, where permitted, the explicit no-post-apply-backout basis. Mutable-state retirement and post-success restore require the bundle; interrupted transactions use their separate exact-ID recovery branch.",
  },
  {
    id: "learning",
    title: "Learning",
    lines: [
      "candidate evidence",
      "semantic audit",
      "accepted improvement",
      "verified disposition",
    ],
    x: 650,
    y: 235,
    width: 235,
    height: 185,
    caption: "Reusable framework candidates first receive report-only semantic audit; only accepted candidates enter Framework Improvement. Project-local changes remain on their project route.",
  },
] as const satisfies readonly DiagramNode[];

const diagramEdges = [
  {
    from: "context",
    to: "recovery",
    label: "root",
    path: "M 130 122 L 185 122",
    labelX: 142,
    labelY: 111,
  },
  {
    from: "recovery",
    to: "authority",
    label: "clear",
    path: "M 320 122 L 375 122",
    labelX: 331,
    labelY: 111,
  },
  {
    from: "authority",
    to: "packet",
    label: "terms",
    path: "M 500 122 L 555 122",
    labelX: 511,
    labelY: 111,
  },
  {
    from: "packet",
    to: "work",
    label: "load",
    path: "M 700 122 L 755 122",
    labelX: 713,
    labelY: 111,
  },
  {
    from: "work",
    to: "verification",
    label: "evidence",
    path: "M 815 185 C 815 210 650 220 500 235",
    labelX: 650,
    labelY: 210,
  },
  {
    from: "verification",
    to: "learning",
    label: "route",
    path: "M 610 302 L 650 302",
    labelX: 612,
    labelY: 291,
  },
  {
    from: "learning",
    to: "context",
    label: "retained change",
    path: "M 768 420 C 610 475 210 475 68 185",
    labelX: 360,
    labelY: 447,
  },
] as const satisfies readonly DiagramEdge[];

const byId = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (!(element instanceof HTMLElement)) {
    throw new Error(`Missing required element: ${id}`);
  }
  return element as T;
};

const createElement = <K extends keyof HTMLElementTagNameMap>(
  tagName: K,
  className?: string,
): HTMLElementTagNameMap[K] => {
  const element = document.createElement(tagName);
  if (className !== undefined) {
    element.className = className;
  }
  return element;
};

const createSvgElement = <K extends keyof SVGElementTagNameMap>(
  tagName: K,
  className?: string,
): SVGElementTagNameMap[K] => {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tagName);
  if (className !== undefined) {
    element.setAttribute("class", className);
  }
  return element;
};

const renderStepList = (
  listId: "runtime-loop" | "refresh-loop",
  steps: readonly RuntimeStep[],
): void => {
  const list = byId<HTMLOListElement>(listId);
  for (const step of steps) {
    const item = createElement("li", "runtime-card");
    const heading = createElement("h3");
    heading.textContent = step.title;
    const body = createElement("p");
    body.textContent = step.body;
    item.append(heading, body);
    list.append(item);
  }
};

const renderRuntimeLoop = (): void => {
  renderStepList("runtime-loop", runtimeSteps);
  renderStepList("refresh-loop", refreshSteps);
};

const renderArchitectureDiagram = (): void => {
  const shell = byId<HTMLDivElement>("architecture-diagram");
  const controls = byId<HTMLDivElement>("diagram-controls");
  const caption = byId<HTMLParagraphElement>("diagram-caption");
  const svg = createSvgElement("svg");
  svg.setAttribute("viewBox", "0 0 890 490");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-labelledby", "diagram-title diagram-desc");

  const title = createSvgElement("title");
  title.id = "diagram-title";
  title.textContent = "Master Prompt Agreement framework movement diagram";
  const desc = createSvgElement("desc");
  desc.id = "diagram-desc";
  desc.textContent =
    "The user task, selected framework checkout, and governed project root lead to a root-scoped transaction-control gate before generated project authority; ordinary work then creates evidence for verification. Reusable framework candidates first receive report-only semantic audit, and only accepted candidates enter Framework Improvement; project-local changes remain on their project route.";

  const defs = createSvgElement("defs");
  const marker = createSvgElement("marker");
  marker.id = "arrowhead";
  marker.setAttribute("viewBox", "0 0 10 10");
  marker.setAttribute("refX", "9");
  marker.setAttribute("refY", "5");
  marker.setAttribute("markerWidth", "8");
  marker.setAttribute("markerHeight", "8");
  marker.setAttribute("orient", "auto-start-reverse");
  const markerPath = createSvgElement("path");
  markerPath.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
  markerPath.setAttribute("fill", "#52657a");
  marker.append(markerPath);
  defs.append(marker);

  const edgeLayer = createSvgElement("g");
  const nodeLayer = createSvgElement("g");

  for (const edge of diagramEdges) {
    const path = createSvgElement("path", "diagram-edge");
    path.dataset.from = edge.from;
    path.dataset.to = edge.to;
    path.setAttribute("d", edge.path);
    path.setAttribute("marker-end", "url(#arrowhead)");
    const label = createSvgElement("text", "diagram-label");
    label.setAttribute("x", String(edge.labelX));
    label.setAttribute("y", String(edge.labelY));
    label.textContent = edge.label;
    edgeLayer.append(path, label);
  }

  for (const node of diagramNodes) {
    const group = createSvgElement("g", "diagram-node");
    group.dataset.nodeId = node.id;
    const rect = createSvgElement("rect");
    rect.setAttribute("x", String(node.x));
    rect.setAttribute("y", String(node.y));
    rect.setAttribute("width", String(node.width));
    rect.setAttribute("height", String(node.height));
    rect.setAttribute("rx", "10");
    const text = createSvgElement("text");
    text.setAttribute("x", String(node.x + 16));
    text.setAttribute("y", String(node.y + 32));
    const titleLine = createSvgElement("tspan");
    titleLine.textContent = node.title;
    text.append(titleLine);
    for (const [index, line] of node.lines.entries()) {
      const tspan = createSvgElement("tspan");
      tspan.setAttribute("x", String(node.x + 16));
      tspan.setAttribute("dy", index === 0 ? "1.7em" : "1.45em");
      tspan.textContent = line;
      text.append(tspan);
    }
    group.append(rect, text);
    nodeLayer.append(group);
  }

  svg.append(title, desc, defs, edgeLayer, nodeLayer);
  shell.replaceChildren(svg);

  const setActive = (nodeId: string): void => {
    const activeNode = diagramNodes.find((node) => node.id === nodeId) ?? diagramNodes[0];
    for (const group of nodeLayer.querySelectorAll<SVGGElement>(".diagram-node")) {
      group.classList.toggle("active", group.dataset.nodeId === activeNode.id);
    }
    for (const edge of edgeLayer.querySelectorAll<SVGPathElement>(".diagram-edge")) {
      edge.classList.toggle(
        "active",
        edge.dataset.from === activeNode.id || edge.dataset.to === activeNode.id,
      );
    }
    for (const button of controls.querySelectorAll<HTMLButtonElement>(".diagram-button")) {
      button.setAttribute("aria-pressed", String(button.dataset.nodeId === activeNode.id));
    }
    caption.textContent = activeNode.caption;
  };

  for (const node of diagramNodes) {
    const button = createElement("button", "diagram-button");
    button.type = "button";
    button.dataset.nodeId = node.id;
    button.setAttribute("aria-pressed", "false");
    button.textContent = node.title;
    button.addEventListener("click", () => setActive(node.id));
    controls.append(button);
  }

  setActive(diagramNodes[0].id);
};

const renderSurfacePanel = (group: SurfaceGroup): void => {
  const panel = byId<HTMLDivElement>("surface-panel");
  panel.replaceChildren();
  panel.setAttribute("aria-labelledby", `tab-${group.id}`);

  const heading = createElement("h3");
  heading.textContent = group.label;
  const summary = createElement("p");
  summary.textContent = group.summary;
  const list = createElement("div", "surface-list");

  for (const item of group.items) {
    const link = createElement("a", "surface-link");
    link.href = item.href;
    link.textContent = item.label;

    const note = createElement("span");
    note.textContent = item.note;
    link.append(note);
    list.append(link);
  }

  panel.append(heading, summary, list);
};

const renderTabs = (): void => {
  const tabList = document.querySelector<HTMLElement>(".tabs");
  if (tabList === null) {
    throw new Error("Missing tabs container");
  }

  const selectGroup = (button: HTMLButtonElement, group: SurfaceGroup): void => {
    for (const tab of tabList.querySelectorAll<HTMLButtonElement>(".tab")) {
      const selected = tab === button;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    }
    renderSurfacePanel(group);
  };

  for (const [index, group] of surfaceGroups.entries()) {
    const button = createElement("button", "tab");
    button.type = "button";
    button.id = `tab-${group.id}`;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", "surface-panel");
    button.setAttribute("aria-selected", String(index === 0));
    button.tabIndex = index === 0 ? 0 : -1;
    button.textContent = group.label;
    button.addEventListener("click", () => selectGroup(button, group));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
        return;
      }

      event.preventDefault();
      const tabs = Array.from(tabList.querySelectorAll<HTMLButtonElement>(".tab"));
      const currentIndex = tabs.indexOf(button);
      const lastIndex = tabs.length - 1;
      const nextIndex =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? lastIndex
            : event.key === "ArrowLeft"
              ? currentIndex <= 0 ? lastIndex : currentIndex - 1
              : currentIndex >= lastIndex ? 0 : currentIndex + 1;
      const nextButton = tabs[nextIndex];
      const nextGroup = surfaceGroups[nextIndex];

      if (nextButton !== undefined && nextGroup !== undefined) {
        nextButton.focus();
        selectGroup(nextButton, nextGroup);
      }
    });
    tabList.append(button);
  }

  renderSurfacePanel(surfaceGroups[0]);
};

const renderQualityGates = (): void => {
  const grid = byId<HTMLDivElement>("quality-grid");
  for (const gate of qualityGates) {
    const card = createElement("article", `quality-card ${gate.status === "judgment" ? "warning" : ""}`);
    const heading = createElement("h3");
    heading.textContent = gate.title;
    const status = createElement("strong");
    status.textContent = gate.status === "automated" ? "Objective check" : "Requires judgment";
    const body = createElement("p");
    body.textContent = gate.body;
    card.append(heading, status, body);
    grid.append(card);
  }
};

const renderReaderPath = (): void => {
  const container = byId<HTMLDivElement>("reader-path");
  for (const item of readerPath) {
    const card = createElement("a", "reader-card");
    card.href = item.href;
    const heading = createElement("h3");
    heading.textContent = item.title;
    const note = createElement("span");
    note.textContent = item.note;
    card.append(heading, note);
    container.append(card);
  }
};

renderRuntimeLoop();
renderArchitectureDiagram();
renderTabs();
renderQualityGates();
renderReaderPath();
