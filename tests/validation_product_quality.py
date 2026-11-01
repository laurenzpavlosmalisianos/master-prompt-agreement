"""Product-only documentation and conformance checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import unittest

from tests.validation_test_support import REPO_ROOT, run_bounded

import context_manifest
import integration_registry
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
                "mermaid-diagram-syntax",
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
        agents_text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        claude_raw = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        claude_lines = [
            line.strip()
            for line in claude_raw.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(["@AGENTS.md"], claude_lines)
        claude_effective = claude_raw.replace("@AGENTS.md", agents_text)

        for name, text in (("AGENTS.md", agents_text), ("CLAUDE.md", claude_effective)):
            with self.subTest(entrypoint=name):
                self.assertIn("runtime/operative_charter.md", text)
                self.assertIn("GETTING_STARTED.md", text)
                self.assertIn("task_orders/init.md", text)
                self.assertEqual(
                    1,
                    text.count(integration_registry.RECOVERY_GUARD_MARKER),
                )
                self.assertIn("Before loading a target project's `AGENT_PROJECT.md`", text)
                charter_pos = text.index(
                    "Read `runtime/operative_charter.md` before using the framework."
                )
                guard_pos = text.index(integration_registry.RECOVERY_GUARD_MARKER)
                recovery_tmp_pos = text.index(".mpa-bootstrap-recovery.tmp")
                self.assertLess(charter_pos, guard_pos)
                self.assertLess(guard_pos, recovery_tmp_pos)

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
            self.assertTrue(path.is_file(), f"missing required product file: {relative}")
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

    def test_pyright_targets_product_code_roots(self) -> None:
        config = json.loads((REPO_ROOT / "pyrightconfig.json").read_text(encoding="utf-8"))
        self.assertEqual(["scripts", "tests"], config["include"])
        self.assertEqual(["scripts"], config["extraPaths"])
        self.assertEqual("3.14", config["pythonVersion"])
        self.assertEqual("standard", config["typeCheckingMode"])


if __name__ == "__main__":
    unittest.main()
