"""Product-only documentation, conformance, and interactive-guide checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import unittest

from tests.validation_test_support import REPO_ROOT, run_bounded

import context_manifest
import product_manifest
import project_refresh
import recommend_stack


SCRIPT_LINK_RE = re.compile(r"\[`([^`]+\.py)`\]\(([^)]+\.py)\)")
UNSAFE_RUNNER_SCRIPT_RE = re.compile(
    r"<runner>\s+(?!--\s+(?:\\?[\"']))[^`\n]*?/scripts/[A-Za-z0-9_.-]+\.py"
)
UNSAFE_PYTHON_SCRIPT_RE = re.compile(
    r"(?:<candidate-python>\s+-E\s+-S\s+-B|uv run python -E -S -B|"
    r"python3? -E -S -B|py -3 -E -S -B)"
    r"\s+(?!--\s+(?:\\?[\"']))[^`\n]*?/scripts/[A-Za-z0-9_.-]+\.py"
)
COMMAND_DOCUMENT_SUFFIXES = {".json", ".md", ".template", ".txt", ".yaml", ".yml"}
OPTION_ROW_RE = re.compile(r"^- `([^`]+\.py)` — (.+)$", re.MULTILINE)
LONG_OPTION_RE = re.compile(r"`(--[a-z][a-z0-9-]*)`")
POSITIONAL_OPERAND_RE = re.compile(r"positional operands?: `([^`]+)`")
HELP_OPTION_LINE_RE = re.compile(r"^\s+(?:-[A-Za-z0-9?],\s+)?--[a-z]")
HELP_POSITIONAL_LINE_RE = re.compile(r"^\s{2}([a-z][a-z0-9_-]*)\s{2,}")


class ProductQualityTests(unittest.TestCase):
    def test_context_loading_is_task_conditioned_and_minimal_by_default(self) -> None:
        parser = context_manifest.build_parser()
        schedule = recommend_stack.load_schedule()

        small = parser.parse_args(["--small"])
        self.assertEqual("fast", recommend_stack.choose_standard_of_care(small))
        self.assertEqual([], recommend_stack.collect_practice_guides(small, schedule))
        self.assertEqual([], context_manifest.workflow_selection_candidates(small))

        compact_plan = parser.parse_args(["--small", "--planning"])
        compact_module = context_manifest.infer_task_module(compact_plan)
        self.assertEqual("plan", compact_module)
        self.assertEqual(
            "compact_module",
            context_manifest.resolve_task_module_loading(
                compact_plan,
                compact_module,
            )["mode"],
        )

        prompt_review = parser.parse_args(
            [
                "--prompt-agent-quality",
                "--current-info",
                "--source-refresh",
                "--review",
            ]
        )
        selected_guides = recommend_stack.collect_practice_guides(
            prompt_review,
            schedule,
        )
        all_guides = [guide["name"] for guide in schedule["practice_guides"]]
        self.assertIn("prompt_agent_quality", selected_guides)
        self.assertIn("source_freshness_review", selected_guides)
        self.assertLess(len(selected_guides), len(all_guides))

        prompt_quality_only = parser.parse_args(["--prompt-agent-quality"])
        self.assertEqual(
            ["prompt_agent_quality"],
            recommend_stack.collect_practice_guides(
                prompt_quality_only,
                schedule,
            ),
        )
        self.assertEqual(
            [],
            context_manifest.workflow_selection_candidates(prompt_quality_only),
        )

    def test_framework_quality_contract_contains_only_product_guardrails(
        self,
    ) -> None:
        contract = json.loads(
            (REPO_ROOT / "runtime" / "framework_quality_contract.json").read_text(
                encoding="utf-8"
            )
        )
        mistake_classes = contract["repeated_mistake_classes"]
        self.assertEqual(
            {
                "durable-generator-snapshot-only",
                "exact-url-monitor-root",
                "lower-tier-source-adoption",
                "private-path-leak",
                "prose-derived-research-state",
                "prose-derived-source-control",
                "semantic-validator-gap",
                "unabstracted-external-source",
                "unbounded-reviewer-lane",
                "vendor-specific-public-doctrine",
            },
            {mistake_class["id"] for mistake_class in mistake_classes},
        )

        serialized_classes = json.dumps(
            mistake_classes,
            ensure_ascii=False,
            sort_keys=True,
        ).casefold()
        for excluded_mechanism in (
            "authoring-only",
            "authoring workspace",
            "authoring-workspace",
            "compliance collector",
            "public release",
            "selected-export",
            "workspace hygiene",
        ):
            with self.subTest(excluded_mechanism=excluded_mechanism):
                self.assertNotIn(excluded_mechanism, serialized_classes)

        path_leak = next(
            mistake_class
            for mistake_class in mistake_classes
            if mistake_class["id"] == "private-path-leak"
        )
        self.assertIn("Exact product membership", path_leak["guard"])
        self.assertIn("product input and state validators", path_leak["guard"])

    def test_product_entrypoint_loads_charter_and_setup_route(self) -> None:
        text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("runtime/operative_charter.md", text)
        self.assertIn("GETTING_STARTED.md", text)
        self.assertIn("task_orders/init.md", text)

    def test_script_reference_covers_every_product_python_module(self) -> None:
        text = (REPO_ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
        linked = {
            f"scripts/{target}"
            for _label, target in SCRIPT_LINK_RE.findall(text)
            if "/" not in target
        }
        expected = {
            relative
            for relative in product_manifest.PRODUCT_REQUIRED_FILES
            if relative.startswith("scripts/") and relative.endswith(".py")
        }
        self.assertEqual(expected, linked)

    def test_command_option_matrix_matches_every_product_parser(self) -> None:
        readme = (REPO_ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
        routing_text = readme.split(
            "<!-- product-cli-routing-options:start -->",
            1,
        )[1].split("<!-- product-cli-routing-options:end -->", 1)[0]
        matrix_text = readme.split(
            "<!-- product-cli-option-matrix:start -->",
            1,
        )[1].split("<!-- product-cli-option-matrix:end -->", 1)[0]
        routing_options = set(LONG_OPTION_RE.findall(routing_text))
        documented: dict[str, set[str]] = {}
        documented_positionals: dict[str, str] = {}
        for script, description in OPTION_ROW_RE.findall(matrix_text):
            options = set(LONG_OPTION_RE.findall(description))
            if "shared routing triggers" in description:
                options.update(routing_options)
            self.assertNotIn(script, documented, script)
            documented[script] = options
            positional_match = POSITIONAL_OPERAND_RE.search(description)
            if positional_match is not None:
                documented_positionals[script] = positional_match.group(1)

        self.assertEqual(
            {
                "automation_orders_lint.py": "manifest",
                "project_contract_sync.py": "project_root",
                "render_cron.py": "manifest",
                "review_packet_contract.py": "manifest",
                "source_chain_artifact_lint.py": "artifact [artifact ...]",
                "source_deep_research_lint.py": "artifact [artifact ...]",
            },
            documented_positionals,
        )

        expected_commands = {
            Path(relative).name
            for relative in product_manifest.PRODUCT_COMMAND_SCRIPTS
        }
        self.assertEqual(expected_commands, set(documented))

        refresh_parser = project_refresh.build_parser()
        refresh_subcommands: set[str] = set()
        for action in refresh_parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                refresh_subcommands.update(action.choices)
        self.assertTrue(refresh_subcommands)

        for script in sorted(expected_commands):
            actual: set[str] = set()
            invocations = (
                [(), *((subcommand,) for subcommand in sorted(refresh_subcommands))]
                if script == "project_refresh.py"
                else [()]
            )
            if script != "check_prereqs.py":
                for arguments in invocations:
                    completed = run_bounded(
                        [
                            sys.executable,
                            *(
                                ("-E", "-S")
                                if script in {"project_bootstrap.py", "project_refresh.py"}
                                else ()
                            ),
                            "-B",
                            str(REPO_ROOT / "scripts" / script),
                            *arguments,
                            "--help",
                        ],
                        cwd=REPO_ROOT,
                        check=True,
                        timeout_seconds=15.0,
                        max_output_bytes=512 * 1024,
                    )
                    help_text = completed.stdout.casefold()
                    for private_term in (
                        "framework-authoring",
                        "framework authoring",
                        "maintainer-only",
                        "publication",
                    ):
                        self.assertNotIn(
                            private_term,
                            help_text,
                            f"{script} {' '.join(arguments)} --help",
                        )
                    if arguments == () and script in documented_positionals:
                        positional_section = ""
                        if "\npositional arguments:\n" in completed.stdout:
                            positional_section = completed.stdout.split(
                                "\npositional arguments:\n",
                                1,
                            )[1].split("\noptions:\n", 1)[0]
                        actual_positionals = {
                            match.group(1)
                            for match in map(
                                HELP_POSITIONAL_LINE_RE.match,
                                positional_section.splitlines(),
                            )
                            if match is not None
                        }
                        documented_synopsis = documented_positionals.get(script, "")
                        documented_names = set(
                            re.findall(
                                r"[a-z][a-z0-9_-]*",
                                documented_synopsis,
                            )
                        )
                        self.assertEqual(actual_positionals, documented_names, script)
                        if documented_synopsis:
                            usage = " ".join(
                                completed.stdout.split("\n\n", 1)[0].split()
                            )
                            self.assertIn(documented_synopsis, usage, script)
                    for line in completed.stdout.splitlines():
                        if HELP_OPTION_LINE_RE.match(line):
                            actual.update(
                                option
                                for option in re.findall(
                                    r"--[a-z][a-z0-9-]*",
                                    line,
                                )
                                if option != "--help"
                            )
            self.assertEqual(actual, documented[script], script)

    def test_product_documented_python_commands_quote_script_paths(self) -> None:
        for relative in product_manifest.PRODUCT_REQUIRED_FILES:
            path = REPO_ROOT / relative
            if path.suffix not in COMMAND_DOCUMENT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(
                UNSAFE_RUNNER_SCRIPT_RE.search(text),
                f"unsafe <runner> script grammar in {relative}",
            )
            self.assertIsNone(
                UNSAFE_PYTHON_SCRIPT_RE.search(text),
                f"unsafe Python script grammar in {relative}",
            )

    def test_conformance_registry_exposes_only_product_and_project_profiles(self) -> None:
        registry = json.loads(
            (REPO_ROOT / "conformance" / "profiles.json").read_text(encoding="utf-8")
        )
        profile_ids = {profile["id"] for profile in registry["profiles"]}
        self.assertEqual(
            {
                "automation-managed",
                "core-project",
                "framework-product",
                "multi-agent-managed",
                "reviewer-lane-managed",
                "security-managed",
                "source-managed",
            },
            profile_ids,
        )
        self.assertEqual(
            {"framework_product_files"},
            {
                check_id
                for check_id, record in registry["checks"].items()
                if record["subject"] == "framework"
            },
        )

    def test_interactive_guide_has_one_source_and_one_generated_script(self) -> None:
        interactive = REPO_ROOT / "docs" / "interactive"
        expected = {
            "README.md",
            "generated/app.js",
            "index.html",
            "src/app.ts",
            "styles.css",
            "tsconfig.json",
        }
        observed = {
            path.relative_to(interactive).as_posix()
            for path in interactive.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        self.assertEqual(expected, observed)

        html = (interactive / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="generated/app.js"', html)
        self.assertIn("Content-Security-Policy", html)
        self.assertNotIn("createElement", html)
        for match in re.finditer(r"<svg\b([^>]*)>", html):
            attributes = match.group(1)
            self.assertRegex(attributes, r"\bviewBox=")
            self.assertRegex(attributes, r"\bwidth=")
            self.assertRegex(attributes, r"\bheight=")

        generated = (interactive / "generated" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("innerHTML", generated)
        self.assertNotIn("insertAdjacentHTML", generated)
        self.assertNotIn("createElement", generated)

    def test_interactive_diagram_static_and_enhanced_states_agree(self) -> None:
        interactive = REPO_ROOT / "docs" / "interactive"
        html = (interactive / "index.html").read_text(encoding="utf-8")
        stylesheet = (interactive / "styles.css").read_text(encoding="utf-8")
        source = (interactive / "src" / "app.ts").read_text(encoding="utf-8")

        active_edges = {
            (match.group("from"), match.group("to"))
            for match in re.finditer(
                r'<path\s+class="diagram-edge active"\s+'
                r'data-from="(?P<from>[^"]+)"\s+'
                r'data-to="(?P<to>[^"]+)"',
                html,
            )
        }
        self.assertEqual(
            {("context", "recovery"), ("learning", "context")},
            active_edges,
        )
        self.assertIn('id="arrowhead-active"', html)
        self.assertIn('marker-end: url("#arrowhead-active")', stylesheet)
        self.assertEqual(1, stylesheet.count("min-width: 47rem"))
        self.assertNotIn("@media (min-width: 40rem)", stylesheet)
        controls_match = re.search(r"\.diagram-controls\s*\{(?P<body>[^}]*)\}", stylesheet)
        self.assertIsNotNone(controls_match)
        controls_body = controls_match.group("body") if controls_match is not None else ""
        self.assertRegex(controls_body, r"display:\s*grid;")
        self.assertRegex(controls_body, r"visibility:\s*hidden;")
        self.assertRegex(
            stylesheet,
            r"\.diagram-controls\.is-enhanced\s*\{[^}]*visibility:\s*visible;",
        )
        self.assertIn(
            "@media (scripting: none) {\n  .diagram-controls {\n    display: none;",
            stylesheet,
        )
        controls_markup = html.split('id="diagram-controls"', 1)[1].split("</div>", 1)[0]
        self.assertIn('aria-hidden="true"', controls_markup)
        buttons = re.findall(r"<button\b.*?</button>", controls_markup, re.DOTALL)
        self.assertEqual(7, len(buttons))
        for button in buttons:
            self.assertRegex(button, r"\bdisabled(?:\s|>)")
        self.assertIn("Diagram controls must cover every node exactly once", source)
        self.assertIn("setActive(initialButton);", source)
        self.assertIn("button.disabled = false;", source)
        self.assertIn('controls.removeAttribute("aria-hidden");', source)
        self.assertIn('classList.add("is-enhanced")', source)

    def test_pyright_targets_product_code_roots(self) -> None:
        config = json.loads((REPO_ROOT / "pyrightconfig.json").read_text(encoding="utf-8"))
        self.assertEqual(["scripts", "tests"], config["include"])
        self.assertEqual(["scripts"], config["extraPaths"])
        self.assertEqual("3.14", config["pythonVersion"])
        self.assertEqual("standard", config["typeCheckingMode"])


if __name__ == "__main__":
    unittest.main()
