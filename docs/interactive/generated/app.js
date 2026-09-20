"use strict";
const resolveTabLocation = (targets, currentSelectedIndex, fragment, fragmentTargetId) => {
    const targetIndex = fragmentTargetId === null
        ? -1
        : targets.findIndex(({ panelId }) => fragmentTargetId === panelId);
    if (targetIndex >= 0) {
        const target = targets[targetIndex];
        if (target === undefined) {
            throw new Error("Resolved framework-map panel is unavailable");
        }
        const canonicalFragment = `#${target.panelId}`;
        return {
            selectedIndex: targetIndex,
            replacementFragment: fragment === canonicalFragment ? null : canonicalFragment,
        };
    }
    if (fragment !== "" && fragmentTargetId !== null) {
        return {
            selectedIndex: currentSelectedIndex,
            replacementFragment: null,
        };
    }
    const fallbackTarget = targets[0];
    if (fallbackTarget === undefined) {
        throw new Error("At least one framework-map panel is required");
    }
    return {
        selectedIndex: 0,
        replacementFragment: `#${fallbackTarget.panelId}`,
    };
};
(() => {
    const normalizeText = (value) => value.replace(/\s+/gu, " ").trim();
    const requireElementById = (id) => {
        const element = document.getElementById(id);
        if (!(element instanceof HTMLElement)) {
            throw new Error(`Missing required HTML element: ${id}`);
        }
        return element;
    };
    const requireDescription = (button) => {
        const descriptionId = button.getAttribute("aria-describedby");
        if (descriptionId === null) {
            throw new Error(`Missing aria-describedby on diagram control: ${button.textContent ?? ""}`);
        }
        const description = normalizeText(requireElementById(descriptionId).textContent ?? "");
        if (description.length === 0) {
            throw new Error(`Missing diagram description: ${descriptionId}`);
        }
        return description;
    };
    const setupDiagram = () => {
        const controls = requireElementById("diagram-controls");
        const caption = requireElementById("diagram-caption");
        const buttons = Array.from(document.querySelectorAll(".diagram-button"));
        const nodes = Array.from(document.querySelectorAll(".diagram-node"));
        const edges = Array.from(document.querySelectorAll(".diagram-edge"));
        if (!buttons.every((element) => element instanceof HTMLButtonElement)) {
            throw new Error("Every diagram control must be a button");
        }
        if (buttons.length === 0 || nodes.length !== buttons.length) {
            throw new Error("Diagram nodes and controls must have a one-to-one relationship");
        }
        const nodeIds = new Set();
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
        if (new Set(buttonNodeIds).size !== nodeIds.size ||
            !buttonNodeIds.every((nodeId) => nodeId !== undefined && nodeIds.has(nodeId))) {
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
        const setActive = (activeButton) => {
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
    const setupTabs = () => {
        const tabList = requireElementById("surface-tabs");
        const mapShell = tabList.parentElement;
        if (mapShell === null || !mapShell.classList.contains("map-shell")) {
            throw new Error("The surface tab list must belong to the framework map");
        }
        const candidates = Array.from(tabList.querySelectorAll(".tab"));
        if (!candidates.every((element) => element instanceof HTMLAnchorElement)) {
            throw new Error("Every framework-map control must be a link");
        }
        if (candidates.length === 0) {
            throw new Error("At least one framework-map control is required");
        }
        const pairs = candidates.map((tab) => {
            const panelId = tab.dataset["panelId"];
            if (panelId === undefined || tab.hash !== `#${panelId}`) {
                throw new Error(`Framework-map control ${tab.id} has an invalid target`);
            }
            const panel = requireElementById(panelId);
            if (!panel.classList.contains("surface-panel")) {
                throw new Error(`Framework-map control ${tab.id} does not target a surface panel`);
            }
            return { tab, panel };
        });
        if (new Set(pairs.map(({ panel }) => panel.id)).size !== pairs.length) {
            throw new Error("Every framework-map control must target a distinct panel");
        }
        const locationTargets = pairs.map(({ panel }) => ({
            panelId: panel.id,
        }));
        tabList.setAttribute("role", "tablist");
        for (const { tab, panel } of pairs) {
            tab.setAttribute("role", "tab");
            tab.setAttribute("aria-controls", panel.id);
            panel.setAttribute("role", "tabpanel");
            panel.setAttribute("aria-labelledby", tab.id);
            panel.tabIndex = 0;
        }
        let selectedIndex = 0;
        const select = (nextSelectedIndex, moveFocus) => {
            const selectedPair = pairs[nextSelectedIndex];
            if (selectedPair === undefined) {
                return;
            }
            selectedIndex = nextSelectedIndex;
            for (const [index, pair] of pairs.entries()) {
                const selected = index === nextSelectedIndex;
                pair.tab.setAttribute("aria-selected", String(selected));
                pair.tab.tabIndex = selected ? 0 : -1;
                pair.panel.hidden = !selected;
            }
            if (moveFocus) {
                selectedPair.tab.focus();
            }
        };
        const fragmentTargetId = (fragment) => {
            if (!fragment.startsWith("#") || fragment.length === 1) {
                return null;
            }
            try {
                const targetId = decodeURIComponent(fragment.slice(1));
                return document.getElementById(targetId) === null ? null : targetId;
            }
            catch {
                return null;
            }
        };
        const writeFragment = (fragment, replace) => {
            if (replace && document.readyState !== "complete") {
                const originalFragment = window.location.hash;
                window.addEventListener("load", () => {
                    window.setTimeout(() => {
                        if (window.location.hash === originalFragment) {
                            writeFragment(fragment, true);
                        }
                    }, 0);
                }, { once: true });
                return;
            }
            try {
                if (replace) {
                    window.history.replaceState(window.history.state, "", fragment);
                }
                else {
                    window.history.pushState(null, "", fragment);
                }
            }
            catch {
                const scrollX = window.scrollX;
                const scrollY = window.scrollY;
                if (replace) {
                    window.location.replace(fragment);
                }
                else {
                    window.location.hash = fragment;
                }
                window.scrollTo(scrollX, scrollY);
            }
        };
        const syncFromLocation = () => {
            const fragment = window.location.hash;
            const activeElement = document.activeElement;
            const resolution = resolveTabLocation(locationTargets, selectedIndex, fragment, fragmentTargetId(fragment));
            const moveFocus = resolution.selectedIndex !== selectedIndex &&
                pairs.some(({ tab, panel }) => tab === activeElement || panel.contains(activeElement));
            if (resolution.replacementFragment !== null &&
                resolution.replacementFragment !== fragment) {
                writeFragment(resolution.replacementFragment, true);
            }
            select(resolution.selectedIndex, moveFocus);
        };
        const activate = (nextSelectedIndex, moveFocus) => {
            const selectedPair = pairs[nextSelectedIndex];
            if (selectedPair === undefined) {
                return;
            }
            const fragment = `#${selectedPair.panel.id}`;
            if (window.location.hash !== fragment) {
                writeFragment(fragment, false);
            }
            select(nextSelectedIndex, moveFocus);
        };
        syncFromLocation();
        mapShell.classList.add("tabs-enhanced");
        window.addEventListener("hashchange", syncFromLocation);
        window.addEventListener("popstate", syncFromLocation);
        for (const [index, pair] of pairs.entries()) {
            pair.tab.addEventListener("click", (event) => {
                if (event.button !== 0 ||
                    event.altKey ||
                    event.ctrlKey ||
                    event.metaKey ||
                    event.shiftKey) {
                    return;
                }
                event.preventDefault();
                activate(index, false);
            });
            pair.tab.addEventListener("keydown", (event) => {
                if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
                    return;
                }
                let nextIndex;
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
                    case " ":
                        nextIndex = index;
                        break;
                    default:
                        return;
                }
                event.preventDefault();
                activate(nextIndex, true);
            });
        }
    };
    for (const setup of [setupDiagram, setupTabs]) {
        try {
            setup();
        }
        catch (error) {
            console.error("Interactive guide enhancement failed", error);
        }
    }
})();
