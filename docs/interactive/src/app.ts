(() => {
  const normalizeText = (value: string): string => value.replace(/\s+/gu, " ").trim();

  const requireElementById = <T extends HTMLElement>(id: string): T => {
    const element = document.getElementById(id);
    if (!(element instanceof HTMLElement)) {
      throw new Error(`Missing required HTML element: ${id}`);
    }
    return element as T;
  };

  const requireDescription = (button: HTMLButtonElement): string => {
    const descriptionId = button.getAttribute("aria-describedby");
    if (descriptionId === null) {
      throw new Error(`Missing aria-describedby on diagram control: ${button.textContent ?? ""}`);
    }

    const description = normalizeText(
      requireElementById<HTMLElement>(descriptionId).textContent ?? "",
    );
    if (description.length === 0) {
      throw new Error(`Missing diagram description: ${descriptionId}`);
    }
    return description;
  };

  const setupDiagram = (): void => {
    const controls = requireElementById<HTMLElement>("diagram-controls");
    const caption = requireElementById<HTMLParagraphElement>("diagram-caption");
    const buttons = Array.from(document.querySelectorAll(".diagram-button"));
    const nodes = Array.from(document.querySelectorAll<SVGElement>(".diagram-node"));
    const edges = Array.from(document.querySelectorAll<SVGPathElement>(".diagram-edge"));

    if (!buttons.every((element): element is HTMLButtonElement => element instanceof HTMLButtonElement)) {
      throw new Error("Every diagram control must be a button");
    }
    if (buttons.length === 0 || nodes.length !== buttons.length) {
      throw new Error("Diagram nodes and controls must have a one-to-one relationship");
    }

    const nodeIds = new Set<string>();
    for (const node of nodes) {
      const nodeId = node.dataset["nodeId"];
      if (nodeId === undefined || nodeIds.has(nodeId)) {
        throw new Error("Every diagram node must have a unique data-node-id");
      }
      nodeIds.add(nodeId);
    }
    for (const edge of edges) {
      const from = edge.dataset["from"];
      const to = edge.dataset["to"];
      if (from === undefined || to === undefined || !nodeIds.has(from) || !nodeIds.has(to)) {
        throw new Error("Every diagram edge must connect declared nodes");
      }
    }
    for (const button of buttons) {
      const nodeId = button.dataset["nodeId"];
      if (nodeId === undefined || !nodeIds.has(nodeId)) {
        throw new Error("Every diagram control must target a declared node");
      }
    }
    const buttonNodeIds = buttons.map((button) => button.dataset["nodeId"]);
    if (
      new Set(buttonNodeIds).size !== nodeIds.size ||
      !buttonNodeIds.every((nodeId) => nodeId !== undefined && nodeIds.has(nodeId))
    ) {
      throw new Error("Diagram controls must cover every node exactly once");
    }

    const pressedButtons = buttons.filter((button) => button.getAttribute("aria-pressed") === "true");
    const initialButton = pressedButtons[0];
    if (pressedButtons.length !== 1 || initialButton === undefined) {
      throw new Error("The diagram must declare exactly one initial focus control");
    }
    const initialNodeId = initialButton.dataset["nodeId"];
    const activeNodes = nodes.filter((node) => node.classList.contains("active"));
    if (activeNodes.length !== 1 || activeNodes[0]?.dataset["nodeId"] !== initialNodeId) {
      throw new Error("The initial diagram control and active node must agree");
    }
    if (normalizeText(caption.textContent ?? "") !== requireDescription(initialButton)) {
      throw new Error("The initial diagram caption must describe the active control");
    }

    const setActive = (activeButton: HTMLButtonElement): void => {
      const nodeId = activeButton.dataset["nodeId"];
      if (nodeId === undefined) {
        throw new Error("Diagram control is missing data-node-id");
      }

      for (const node of nodes) {
        node.classList.toggle("active", node.dataset["nodeId"] === nodeId);
      }
      for (const edge of edges) {
        const touchesNode = edge.dataset["from"] === nodeId || edge.dataset["to"] === nodeId;
        edge.classList.toggle("active", touchesNode);
      }
      for (const button of buttons) {
        button.setAttribute("aria-pressed", String(button === activeButton));
      }
      caption.textContent = requireDescription(activeButton);
    };

    for (const button of buttons) {
      button.addEventListener("click", () => setActive(button));
    }
    setActive(initialButton);
    for (const button of buttons) {
      button.disabled = false;
    }
    controls.removeAttribute("aria-hidden");
    controls.classList.add("is-enhanced");
  };

  type TabPair = Readonly<{
    tab: HTMLAnchorElement;
    panel: HTMLElement;
  }>;

  const setupTabs = (): void => {
    const tabList = requireElementById<HTMLElement>("surface-tabs");
    const mapShell = tabList.parentElement;
    if (mapShell === null || !mapShell.classList.contains("map-shell")) {
      throw new Error("The surface tab list must belong to the framework map");
    }

    const candidates = Array.from(tabList.querySelectorAll(".tab"));
    if (!candidates.every((element): element is HTMLAnchorElement => element instanceof HTMLAnchorElement)) {
      throw new Error("Every framework-map control must be a link");
    }
    if (candidates.length === 0) {
      throw new Error("At least one framework-map control is required");
    }

    const pairs: TabPair[] = candidates.map((tab) => {
      const panelId = tab.dataset["panelId"];
      if (panelId === undefined || tab.hash !== `#${panelId}`) {
        throw new Error(`Framework-map control ${tab.id} has an invalid target`);
      }

      const panel = requireElementById<HTMLElement>(panelId);
      if (!panel.classList.contains("surface-panel")) {
        throw new Error(`Framework-map control ${tab.id} does not target a surface panel`);
      }
      return { tab, panel };
    });
    if (new Set(pairs.map(({ panel }) => panel.id)).size !== pairs.length) {
      throw new Error("Every framework-map control must target a distinct panel");
    }

    const targetIndex = pairs.findIndex(({ panel }) => `#${panel.id}` === window.location.hash);
    const initialIndex = targetIndex < 0 ? 0 : targetIndex;

    tabList.setAttribute("role", "tablist");
    for (const { tab, panel } of pairs) {
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", panel.id);
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tab.id);
      panel.tabIndex = 0;
    }

    const select = (selectedIndex: number, moveFocus: boolean): void => {
      const selectedPair = pairs[selectedIndex];
      if (selectedPair === undefined) {
        return;
      }

      for (const [index, pair] of pairs.entries()) {
        const selected = index === selectedIndex;
        pair.tab.setAttribute("aria-selected", String(selected));
        pair.tab.tabIndex = selected ? 0 : -1;
        pair.panel.hidden = !selected;
      }
      if (moveFocus) {
        selectedPair.tab.focus();
      }
    };

    select(initialIndex, false);
    mapShell.classList.add("tabs-enhanced");

    for (const [index, pair] of pairs.entries()) {
      pair.tab.addEventListener("click", (event) => {
        event.preventDefault();
        select(index, false);
      });
      pair.tab.addEventListener("keydown", (event) => {
        let nextIndex: number | undefined;
        switch (event.key) {
          case "ArrowLeft":
            nextIndex = index === 0 ? pairs.length - 1 : index - 1;
            break;
          case "ArrowRight":
            nextIndex = index === pairs.length - 1 ? 0 : index + 1;
            break;
          case "Home":
            nextIndex = 0;
            break;
          case "End":
            nextIndex = pairs.length - 1;
            break;
          default:
            return;
        }

        event.preventDefault();
        select(nextIndex, true);
      });
    }
  };

  for (const setup of [setupDiagram, setupTabs]) {
    try {
      setup();
    } catch (error: unknown) {
      console.error("Interactive guide enhancement failed", error);
    }
  }
})();
