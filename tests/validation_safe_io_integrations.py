"""Safe file access, reference/scaffold, and integration-rendering tests."""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from typing import Any, cast
import unittest
from unittest import mock

from tests.validation_test_support import REPO_ROOT

import bootstrap_transaction  # noqa: E402
import integration_registry  # noqa: E402
import project_bootstrap  # noqa: E402
import project_contract_model  # noqa: E402
import product_manifest  # noqa: E402
import reference_snapshot  # noqa: E402
import render_integrations  # noqa: E402
import safe_paths  # noqa: E402


class SafeIoIntegrationTests(unittest.TestCase):
    def test_registry_owns_runtime_specific_authority_load_grammars(self) -> None:
        expected = {
            "claude-code": "claude-markdown-read-v1",
            "codex": "codex-markdown-read-v1",
            "generic": "generic-markdown-read-v1",
        }
        registry = integration_registry.load_registry(REPO_ROOT)
        for family, syntax_id in expected.items():
            with self.subTest(family=family):
                config = registry["families"][family]
                self.assertEqual(
                    syntax_id,
                    config["entrypoint"]["authority_load_syntax"],
                )
                output, rendered = project_bootstrap.render_entrypoint(
                    family,
                    "$FRAMEWORK",
                    contract_root_ref="contracts",
                )
                reference, errors = (
                    integration_registry.entrypoint_authority_load_references(
                        output,
                        rendered,
                        contract_root_ref="contracts",
                    )
                )
                self.assertEqual([], errors)
                self.assertEqual("$FRAMEWORK", reference)
                if family == "claude-code":
                    self.assertFalse(
                        any(
                            line.strip().startswith("@")
                            for line in rendered.splitlines()
                        ),
                        rendered,
                    )

    def test_runtime_entrypoints_load_charter_then_guard_project_authority(self) -> None:
        for family in integration_registry.family_names(REPO_ROOT):
            output, rendered = project_bootstrap.render_entrypoint(
                family,
                "$FRAMEWORK",
                contract_root_ref="contracts",
            )
            rendered_guard_clause = integration_registry.render_project_file_references(
                integration_registry.RECOVERY_GUARD_CLAUSE,
                "contracts",
            )
            guard_block = (
                f"{integration_registry.RECOVERY_GUARD_MARKER}\n"
                f"{rendered_guard_clause}\n\n"
            )
            lines = rendered.splitlines()
            guard_index = lines.index(integration_registry.RECOVERY_GUARD_MARKER)
            framework_index = lines.index(integration_registry.FRAMEWORK_CORE_MARKER)
            contract_index = lines.index(integration_registry.PROJECT_CONTRACT_MARKER)
            state_index = lines.index(integration_registry.STATE_LOADING_MARKER)
            routing_index = lines.index(integration_registry.ROUTING_AFTER_STATE_MARKER)
            with self.subTest(family=family, mutation="valid"):
                self.assertLess(framework_index, guard_index)
                self.assertLess(guard_index, contract_index)
                self.assertLess(contract_index, state_index)
                self.assertLess(state_index, routing_index)
                self.assertTrue(
                    all(
                        routing_index < index
                        for index, line in enumerate(lines)
                        if "runtime/task_modules/" in line
                        or "practice_guides/" in line
                        or "scripts/recommend_stack.py" in line
                    ),
                    rendered,
                )
                reference, errors = (
                    integration_registry.entrypoint_authority_load_references(
                        output,
                        rendered,
                        contract_root_ref="contracts",
                    )
                )
                self.assertEqual([], errors)
                self.assertEqual("$FRAMEWORK", reference)

            inactive_decoys = rendered.replace(
                integration_registry.FRAMEWORK_CORE_MARKER,
                "<!-- Read `contracts/AGENT_PROJECT.md` before recovery. -->\n"
                "```text\n"
                "Read `contracts/TODO.md` before recovery.\n"
                "```\n"
                + integration_registry.FRAMEWORK_CORE_MARKER,
                1,
            )
            with self.subTest(family=family, mutation="inactive-pre-guard-decoys"):
                reference, errors = (
                    integration_registry.entrypoint_authority_load_references(
                        output,
                        inactive_decoys,
                        contract_root_ref="contracts",
                    )
                )
                self.assertEqual([], errors)
                self.assertEqual("$FRAMEWORK", reference)

            mutations = {
                "missing-marker": rendered.replace(
                    integration_registry.RECOVERY_GUARD_MARKER + "\n",
                    "",
                    1,
                ),
                "missing-clause": rendered.replace(
                    rendered_guard_clause + "\n",
                    "",
                    1,
                ),
                "fenced-clause-decoy": rendered.replace(
                    rendered_guard_clause,
                    "```text\n"
                    + rendered_guard_clause
                    + "\n```",
                    1,
                ),
                "guard-before-framework-marker": rendered.replace(
                    guard_block,
                    "",
                    1,
                ).replace(
                    integration_registry.FRAMEWORK_CORE_MARKER,
                    guard_block + integration_registry.FRAMEWORK_CORE_MARKER,
                    1,
                ),
                "guard-after-project-marker": rendered.replace(
                    guard_block,
                    "",
                    1,
                ).replace(
                    integration_registry.PROJECT_CONTRACT_MARKER,
                    integration_registry.PROJECT_CONTRACT_MARKER + "\n" + guard_block,
                    1,
                ),
                "intervening-active-instruction": rendered.replace(
                    integration_registry.RECOVERY_GUARD_MARKER,
                    "Consult neutral framework guidance before checking recovery.\n"
                    + integration_registry.RECOVERY_GUARD_MARKER,
                    1,
                ),
                "pre-guard-project-contract-read": rendered.replace(
                    integration_registry.FRAMEWORK_CORE_MARKER,
                    "Read `contracts/AGENT_PROJECT.md` before recovery.\n"
                    + integration_registry.FRAMEWORK_CORE_MARKER,
                    1,
                ),
                "pre-guard-sow-read": rendered.replace(
                    integration_registry.FRAMEWORK_CORE_MARKER,
                    "Consult `contracts/STATEMENT_OF_WORK.md` before recovery.\n"
                    + integration_registry.FRAMEWORK_CORE_MARKER,
                    1,
                ),
                "pre-guard-state-read": rendered.replace(
                    integration_registry.FRAMEWORK_CORE_MARKER,
                    "Read `contracts/TODO.md` before recovery.\n"
                    + integration_registry.FRAMEWORK_CORE_MARKER,
                    1,
                ),
            }
            for mutation, candidate in mutations.items():
                with self.subTest(family=family, mutation=mutation):
                    reference, errors = (
                        integration_registry.entrypoint_authority_load_references(
                            output,
                            candidate,
                            contract_root_ref="contracts",
                        )
                    )
                    self.assertIsNone(reference)
                    self.assertTrue(
                        any("recovery guard" in error for error in errors),
                        errors,
                    )

            routing_before_state = rendered.replace(
                integration_registry.ROUTING_AFTER_STATE_MARKER + "\n",
                "",
                1,
            ).replace(
                integration_registry.STATE_LOADING_MARKER,
                integration_registry.ROUTING_AFTER_STATE_MARKER
                + "\n"
                + integration_registry.STATE_LOADING_MARKER,
                1,
            )
            with self.subTest(family=family, mutation="routing-before-state"):
                reference, errors = (
                    integration_registry.entrypoint_authority_load_references(
                        output,
                        routing_before_state,
                        contract_root_ref="contracts",
                    )
                )
                self.assertIsNone(reference)
                self.assertTrue(
                    any("post-state-routing order" in error for error in errors),
                    errors,
                )

    def test_runtime_entrypoints_bind_the_compact_sow_conflict_clause(self) -> None:
        contract_root_ref = "contracts/project"
        registry = integration_registry.load_registry(REPO_ROOT)
        for family in integration_registry.family_names(REPO_ROOT):
            template_path = registry["families"][family]["entrypoint"]["path"]
            template = (REPO_ROOT / template_path).read_text(encoding="utf-8")
            self.assertEqual(
                1,
                template.count(
                    integration_registry.PROJECT_CONTRACT_CONFLICT_CLAUSE_TOKEN
                ),
            )
            output, rendered = project_bootstrap.render_entrypoint(
                family,
                "$FRAMEWORK",
                contract_root_ref=contract_root_ref,
            )
            conflict_clause = (
                integration_registry.render_project_contract_conflict_clause(
                    "$FRAMEWORK",
                    contract_root_ref,
                )
            )
            self.assertEqual(1, rendered.count(conflict_clause))

            without_clause = rendered.replace(conflict_clause + "\n", "", 1)
            mutations = {
                "deleted": without_clause,
                "moved-after-state-marker": without_clause.replace(
                    integration_registry.STATE_LOADING_MARKER,
                    integration_registry.STATE_LOADING_MARKER
                    + "\n"
                    + conflict_clause,
                    1,
                ),
                "wrong-contract-root": rendered.replace(
                    conflict_clause,
                    conflict_clause.replace(
                        f"{contract_root_ref}/STATEMENT_OF_WORK.md",
                        "STATEMENT_OF_WORK.md",
                        1,
                    ),
                    1,
                ),
                "wrong-refresh-reference": rendered.replace(
                    conflict_clause,
                    conflict_clause.replace(
                        "$FRAMEWORK/task_orders/framework_refresh.md",
                        "$FRAMEWORK/task_orders/refresh.md",
                        1,
                    ),
                    1,
                ),
            }
            for mutation, candidate in mutations.items():
                with self.subTest(family=family, mutation=mutation):
                    reference, errors = (
                        integration_registry.entrypoint_authority_load_references(
                            output,
                            candidate,
                            contract_root_ref=contract_root_ref,
                        )
                    )
                    self.assertIsNone(reference)
                    self.assertTrue(
                        any(
                            "exact rendered SOW-conflict clause" in error
                            for error in errors
                        ),
                        errors,
                    )

    def test_recovery_guard_uses_the_transaction_writer_closed_control_set(
        self,
    ) -> None:
        expected = (
            bootstrap_transaction.RECOVERY_JOURNAL_NAME,
            bootstrap_transaction.TRANSACTION_LOCK_NAME,
            bootstrap_transaction._RECOVERY_JOURNAL_TEMP_NAME,
        )
        self.assertEqual(
            expected,
            project_contract_model.ENTRYPOINT_RECOVERY_CONTROL_PATHS,
        )
        self.assertEqual(
            project_contract_model.ENTRYPOINT_RECOVERY_GUARD_MARKER,
            integration_registry.RECOVERY_GUARD_MARKER,
        )
        for path in expected:
            with self.subTest(path=path):
                self.assertEqual(
                    1,
                    project_contract_model.ENTRYPOINT_RECOVERY_GUARD_CLAUSE.count(
                        f"`{path}`"
                    ),
                )

    def test_orphan_lock_and_temp_cannot_be_omitted_before_authority_loading(
        self,
    ) -> None:
        orphan_controls = (
            bootstrap_transaction.TRANSACTION_LOCK_NAME,
            bootstrap_transaction._RECOVERY_JOURNAL_TEMP_NAME,
        )
        for family in integration_registry.family_names(REPO_ROOT):
            output, rendered = project_bootstrap.render_entrypoint(
                family,
                "$FRAMEWORK",
                contract_root_ref="contracts",
            )
            rendered_clause = integration_registry.render_project_file_references(
                integration_registry.RECOVERY_GUARD_CLAUSE,
                "contracts",
            )
            stop_directive = (
                "If any exists, stop ordinary project work and do not load "
                "generated project authority or state."
            )
            self.assertIn(stop_directive, rendered_clause)
            self.assertLess(
                rendered.index(rendered_clause),
                rendered.index(integration_registry.PROJECT_CONTRACT_MARKER),
            )
            self.assertLess(
                rendered.index(rendered_clause),
                rendered.index(integration_registry.STATE_LOADING_MARKER),
            )
            for artifact in orphan_controls:
                with self.subTest(family=family, orphan_artifact=artifact):
                    self.assertLess(
                        rendered_clause.index(f"`{artifact}`"),
                        rendered_clause.index(stop_directive),
                    )
                    incomplete_clause = rendered_clause.replace(
                        f"`{artifact}`",
                        f"`{artifact}.omitted`",
                        1,
                    )
                    candidate = rendered.replace(
                        rendered_clause,
                        incomplete_clause,
                        1,
                    )
                    reference, errors = (
                        integration_registry.entrypoint_authority_load_references(
                            output,
                            candidate,
                            contract_root_ref="contracts",
                        )
                    )
                    self.assertIsNone(reference)
                    self.assertTrue(
                        any("exact recovery clause" in error for error in errors),
                        errors,
                    )

    def test_registry_rejects_unknown_authority_load_grammar(self) -> None:
        registry = json.loads(
            (REPO_ROOT / "integrations" / "registry.json").read_text(
                encoding="utf-8"
            )
        )
        registry["families"]["generic"]["entrypoint"][
            "authority_load_syntax"
        ] = "unknown-v1"

        with self.assertRaisesRegex(
            ValueError,
            "generic.entrypoint.authority_load_syntax must be one of",
        ):
            integration_registry.validate_registry(registry, REPO_ROOT)

    def test_nested_contract_reference_inventory_is_model_owned(self) -> None:
        self.assertEqual(
            project_contract_model.DOWNSTREAM_CONTRACT_REFERENCE_FILES,
            integration_registry.PROJECT_FILE_NAMES,
        )
        self.assertTrue(
            set(project_contract_model.MANUAL_STATE_TEMPLATES).isdisjoint(
                integration_registry.PROJECT_FILE_NAMES
            )
        )

    def test_bootstrap_entrypoint_matches_shared_integration_renderer(self) -> None:
        contract_root = "contracts/project"
        framework_ref = "$FRAMEWORK"
        for family in integration_registry.family_names(REPO_ROOT):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as temp_dir:
                output_root = Path(temp_dir)
                plan = render_integrations.build_registered_render_plan(
                    family,
                    REPO_ROOT,
                    output_root,
                    framework_ref,
                    force=False,
                    contract_root_ref=contract_root,
                )
                render_integrations.install_render_plan(plan)
                output_name, bootstrap_text = project_bootstrap.render_entrypoint(
                    family,
                    framework_ref,
                    contract_root_ref=contract_root,
                )
                rendered_text = (output_root / output_name).read_text(encoding="utf-8")
                self.assertEqual(rendered_text, bootstrap_text)

    def test_registered_render_plan_rejects_invalid_entrypoint_authority_before_write(
        self,
    ) -> None:
        registry = json.loads(
            (REPO_ROOT / "integrations" / "registry.json").read_text(
                encoding="utf-8"
            )
        )
        codex_config = registry["families"]["codex"]
        source_template = (
            REPO_ROOT / codex_config["entrypoint"]["path"]
        ).read_text(encoding="utf-8")
        guard_block = (
            f"{integration_registry.RECOVERY_GUARD_MARKER}\n"
            f"{integration_registry.RECOVERY_GUARD_CLAUSE}\n\n"
        )
        without_guard = source_template.replace(guard_block, "", 1)
        self.assertNotEqual(source_template, without_guard)
        mutations = {
            "missing-recovery-guard": without_guard,
            "moved-recovery-guard": without_guard.replace(
                integration_registry.PROJECT_CONTRACT_MARKER,
                integration_registry.PROJECT_CONTRACT_MARKER
                + "\n"
                + guard_block,
                1,
            ),
            "wrong-nested-contract-reference": source_template.replace(
                "Read `AGENT_PROJECT.md` before acting.",
                "Read `wrong/AGENT_PROJECT.md` before acting.",
                1,
            ),
            "malformed-charter-load": source_template.replace(
                "Read `{{FRAMEWORK_ROOT}}/runtime/operative_charter.md` before acting.",
                "Consult `{{FRAMEWORK_ROOT}}/runtime/operative_charter.md` before acting.",
                1,
            ),
            "fenced-recovery-decoy": without_guard.replace(
                "</framework-core>",
                "</framework-core>\n\n```text\n" + guard_block + "```",
                1,
            ),
            "commented-recovery-decoy": without_guard.replace(
                "</framework-core>",
                "</framework-core>\n\n<!--\n" + guard_block + "-->",
                1,
            ),
        }
        for case_id, candidate in mutations.items():
            self.assertNotEqual(source_template, candidate, case_id)
            with self.subTest(case=case_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                integration_root = root / "integrations"
                template_root = integration_root / "templates" / "codex"
                shutil.copytree(
                    REPO_ROOT / codex_config["template_root"],
                    template_root,
                )
                (integration_root / "registry.json").write_text(
                    json.dumps(
                        {"families": {"codex": codex_config}},
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                entrypoint = root / codex_config["entrypoint"]["path"]
                entrypoint.write_text(candidate, encoding="utf-8")
                output_root = root / "rendered"

                with self.assertRaisesRegex(
                    ValueError,
                    "registry-selected authority grammar",
                ):
                    render_integrations.build_registered_render_plan(
                        "codex",
                        root,
                        output_root,
                        "$FRAMEWORK",
                        force=False,
                        contract_root_ref="contracts",
                    )
                self.assertFalse(output_root.exists())

    def test_render_integrations_cli_all_materializes_the_registered_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "rendered"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "render_integrations.py",
                        "--integration",
                        "all",
                        "--framework-ref",
                        "$FRAMEWORK",
                        "--output-dir",
                        str(output_root),
                    ],
                ),
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                result = render_integrations.main()

            registry = integration_registry.load_registry(REPO_ROOT)
            for family, config in registry["families"].items():
                with self.subTest(family=family):
                    family_root = output_root / family
                    expected_outputs = {
                        config["entrypoint"]["output"],
                        *(
                            wrapper["repo_output"]
                            for wrapper in config["wrappers"].values()
                        ),
                    }
                    actual_outputs = {
                        path.relative_to(family_root).as_posix()
                        for path in family_root.rglob("*")
                        if path.is_file()
                    }
                    self.assertEqual(expected_outputs, actual_outputs)
                    for relative in sorted(expected_outputs):
                        target = family_root / relative
                        self.assertTrue(target.is_file(), target)
                        if target.suffix in {".json", ".md"} or target.name in {
                            "AGENTS.md",
                            "CLAUDE.md",
                            "SKILL.md",
                        }:
                            text = target.read_text(encoding="utf-8")
                            self.assertNotIn("{{", text, target)
                            self.assertNotIn("}}", text, target)
                            self.assertFalse(
                                safe_paths.contains_host_identity_path(text),
                                target,
                            )

                    entrypoint = family_root / config["entrypoint"]["output"]
                    entrypoint_text = entrypoint.read_text(encoding="utf-8")
                    framework_ref, errors = (
                        integration_registry.entrypoint_authority_load_references(
                            config["entrypoint"]["output"],
                            entrypoint_text,
                            contract_root_ref=".",
                        )
                    )
                    self.assertEqual([], errors)
                    self.assertEqual("$FRAMEWORK", framework_ref)

        self.assertEqual(0, result)
        self.assertIn("Rendered ", stdout.getvalue())

    def test_codex_project_refresh_skill_is_a_thin_distinct_registered_route(self) -> None:
        registry = integration_registry.load_registry(REPO_ROOT)
        codex = registry["families"]["codex"]
        wrapper_path = codex["wrappers"]["project_refresh"]["path"]
        self.assertEqual(
            "integrations/templates/codex/skills/project-refresh/SKILL.md.template",
            wrapper_path,
        )
        source = (REPO_ROOT / wrapper_path).read_text(encoding="utf-8")
        self.assertIn("\nname: master-prompt-refresh-project\n", source)
        frontmatter = source.partition("---\n")[2].partition("\n---")[0]
        for trigger in ("inspect", "update", "refresh", "revise", "recover"):
            with self.subTest(trigger=trigger):
                self.assertIn(trigger, frontmatter)
        self.assertNotIn("migrate", frontmatter)
        self.assertNotIn("detach", frontmatter)
        self.assertEqual(1, source.count("{{FRAMEWORK_ROOT}}/UPDATING.md"))
        self.assertEqual(
            1,
            source.count("{{FRAMEWORK_ROOT}}/task_orders/framework_refresh.md"),
        )
        self.assertEqual(1, source.count("scripts/project_refresh.py inspect"))
        self.assertNotIn("task_orders/init.md", source)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            plan = render_integrations.build_registered_render_plan(
                "codex",
                REPO_ROOT,
                output_root,
                "$FRAMEWORK",
                force=False,
                contract_root_ref=".",
            )
            render_integrations.install_render_plan(plan)
            rendered = (
                output_root
                / ".agents"
                / "skills"
                / "master-prompt-refresh-project"
                / "SKILL.md"
            ).read_text(encoding="utf-8")

        self.assertIn("$FRAMEWORK/UPDATING.md", rendered)
        self.assertIn("$FRAMEWORK/task_orders/framework_refresh.md", rendered)
        self.assertNotIn("{{", rendered)
        self.assertNotIn("}}", rendered)

    def test_codex_lifecycle_skills_load_task_orders_before_operator_guides(
        self,
    ) -> None:
        registry = integration_registry.load_registry(REPO_ROOT)
        rendered = integration_registry.render_wrapper_outputs(
            "codex",
            ["project_init", "project_refresh"],
            ".",
            ".",
            REPO_ROOT,
        )
        fixtures = {
            "project_init": (
                "task_orders/init.md",
                "GETTING_STARTED.md",
                "only when the User asks for setup explanation, manual command "
                "guidance, or troubleshooting",
                "first current-format setup",
            ),
            "project_refresh": (
                "task_orders/framework_refresh.md",
                "UPDATING.md",
                "only when the User asks for update explanation, manual command "
                "guidance, or troubleshooting",
                "existing generated instance",
            ),
        }
        for wrapper_id, (
            task_order,
            operator_guide,
            conditional_phrase,
            lifecycle_phrase,
        ) in fixtures.items():
            output = registry["families"]["codex"]["wrappers"][wrapper_id][
                "repo_output"
            ]
            text = rendered[output]
            lines = text.splitlines()
            active = integration_registry._active_line_indexes(lines)
            active_lines = [lines[index] for index in sorted(active)]
            task_line = next(
                line
                for line in active_lines
                if task_order in line and line.startswith(("2. Read `", "3. Read `"))
            )
            guide_line = next(
                line
                for line in active_lines
                if operator_guide in line and line.startswith(("3. Consult `", "4. Consult `"))
            )
            with self.subTest(wrapper=wrapper_id):
                self.assertLess(text.index(task_line), text.index(guide_line))
                self.assertIn("workflow source of truth", task_line)
                self.assertIn(conditional_phrase, guide_line)
                self.assertIn(
                    "informative orientation, not the workflow owner",
                    guide_line,
                )
                self.assertIn(lifecycle_phrase, text)
                config = registry["families"]["codex"]["wrappers"][wrapper_id]
                self.assertEqual(
                    [],
                    integration_registry.wrapper_lifecycle_errors(
                        text,
                        output=output,
                        lifecycle=config["lifecycle"],
                        authority_precondition=config["authority_precondition"],
                    ),
                )
                mutations = {
                    "before-task-order": text.replace(
                        task_line + "\n" + guide_line,
                        guide_line + "\n" + task_line,
                        1,
                    ),
                    "read": text.replace(
                        guide_line,
                        guide_line.replace("Consult `", "Read `", 1),
                        1,
                    ),
                    "follow": text.replace(
                        guide_line,
                        guide_line.replace("Consult `", "Follow `", 1),
                        1,
                    ),
                    "unconditional": text.replace(
                        guide_line,
                        guide_line.replace(f" {conditional_phrase}", "", 1),
                        1,
                    ),
                }
                for mutation, candidate in mutations.items():
                    with self.subTest(wrapper=wrapper_id, mutation=mutation):
                        self.assertTrue(
                            any(
                                "conditional numbered Consult" in error
                                for error in integration_registry.wrapper_lifecycle_errors(
                                    candidate,
                                    output=output,
                                    lifecycle=config["lifecycle"],
                                    authority_precondition=config[
                                        "authority_precondition"
                                    ],
                                )
                            )
                        )

    def test_refresh_skill_surfaces_load_charter_then_check_recovery(self) -> None:
        paths = (
            ".agents/skills/master-prompt-refresh-project/SKILL.md",
            "integrations/templates/codex/skills/project-refresh/SKILL.md.template",
        )
        for rel in paths:
            with self.subTest(path=rel):
                source = (REPO_ROOT / rel).read_text(encoding="utf-8")
                lines = source.splitlines()
                active = integration_registry._active_line_indexes(lines)
                numbered_steps = [
                    lines[index]
                    for index in range(len(lines))
                    if index in active
                    and len(lines[index]) >= 3
                    and lines[index][0].isdigit()
                    and lines[index][1:3] == ". "
                ]
                self.assertGreaterEqual(len(numbered_steps), 2, numbered_steps)
                self.assertTrue(
                    numbered_steps[0].startswith("1. Read "),
                    numbered_steps,
                )
                self.assertIn("runtime/operative_charter.md", numbered_steps[0])
                self.assertTrue(
                    numbered_steps[1].startswith(
                        "2. After loading the charter and before loading generated "
                        "project authority or state"
                    ),
                    numbered_steps,
                )
                self.assertIn(
                    "<project-root>/.mpa-bootstrap-recovery.json",
                    numbered_steps[1],
                )
                self.assertIn(
                    "<project-root>/.mpa-bootstrap.lock",
                    numbered_steps[1],
                )
                self.assertIn(
                    "<project-root>/.mpa-bootstrap-recovery.tmp",
                    numbered_steps[1],
                )
                self.assertIn("scripts/project_refresh.py inspect", numbered_steps[1])
                self.assertIn("--approve-transaction-id", numbered_steps[1])

    def test_integration_registry_rejects_traversal_paths(self) -> None:
        registry = {
            "families": {
                "bad": {
                    "entrypoint": {
                        "output": "AGENTS.md",
                        "path": "../outside.template",
                    },
                    "template_root": "integrations/templates/codex",
                }
            }
        }

        with self.assertRaises(ValueError):
            integration_registry.validate_registry(registry, REPO_ROOT)

    def test_integration_registry_rejects_uri_windows_and_lexically_ambiguous_paths(self) -> None:
        unsafe_paths = (
            "https://example.com/template",
            "integrations\\templates\\entry.template",
            "integrations//templates/entry.template",
            "integrations/./templates/entry.template",
        )
        for unsafe in unsafe_paths:
            registry = {
                "families": {
                    "bad": {
                        "entrypoint": {"output": "AGENTS.md", "path": unsafe},
                        "template_root": "integrations/templates/codex",
                    }
                }
            }
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                integration_registry.validate_registry(registry, REPO_ROOT)

    def test_integration_registry_input_is_bounded_utf8_single_link_json(self) -> None:
        cases = (
            ("invalid-utf8", "must be UTF-8"),
            ("duplicate-key", "duplicate JSON key: families"),
            (
                "oversized",
                f"{integration_registry.INTEGRATION_REGISTRY_MAX_BYTES}-byte input limit",
            ),
            ("symlinked-file", "must not use symlink path components"),
            ("symlinked-parent", "must not use symlink path components"),
            ("hardlinked", "must have exactly one hard link"),
        )
        for case_id, expected in cases:
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                integrations = root / "integrations"
                integrations.mkdir()
                registry_path = integrations / "registry.json"
                valid_payload = b'{"families":{}}'

                if case_id == "invalid-utf8":
                    registry_path.write_bytes(b"\xff\xfe")
                elif case_id == "duplicate-key":
                    registry_path.write_bytes(b'{"families":{},"families":{}}')
                elif case_id == "oversized":
                    registry_path.write_bytes(
                        b" "
                        * (integration_registry.INTEGRATION_REGISTRY_MAX_BYTES + 1)
                    )
                elif case_id == "symlinked-file":
                    source = root / "registry-source.json"
                    source.write_bytes(valid_payload)
                    registry_path.symlink_to(source)
                elif case_id == "symlinked-parent":
                    integrations.rmdir()
                    source_parent = root / "registry-parent"
                    source_parent.mkdir()
                    (source_parent / "registry.json").write_bytes(valid_payload)
                    integrations.symlink_to(source_parent, target_is_directory=True)
                else:
                    source = root / "registry-source.json"
                    source.write_bytes(valid_payload)
                    os.link(source, registry_path)

                with self.assertRaisesRegex(ValueError, expected):
                    integration_registry.load_registry(root)

    def test_integration_registry_rejects_symlinked_registered_paths(self) -> None:
        cases = (
            "template-root",
            "entrypoint",
            "wrapper",
            "wrapper-parent",
        )
        for case_id in cases:
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                templates = root / "integrations" / "templates"
                templates.mkdir(parents=True)
                template_root = templates / "demo"

                if case_id == "template-root":
                    real_template_root = templates / "demo-real"
                    real_template_root.mkdir()
                    (real_template_root / "AGENTS.md.template").write_text(
                        "entrypoint\n",
                        encoding="utf-8",
                    )
                    (real_template_root / "wrapper.md.template").write_text(
                        "wrapper\n",
                        encoding="utf-8",
                    )
                    template_root.symlink_to(
                        real_template_root,
                        target_is_directory=True,
                    )
                    wrapper_ref = (
                        "integrations/templates/demo/wrapper.md.template"
                    )
                else:
                    template_root.mkdir()
                    entrypoint = template_root / "AGENTS.md.template"
                    if case_id == "entrypoint":
                        real_entrypoint = template_root / "AGENTS-real.md.template"
                        real_entrypoint.write_text("entrypoint\n", encoding="utf-8")
                        entrypoint.symlink_to(real_entrypoint.name)
                    else:
                        entrypoint.write_text("entrypoint\n", encoding="utf-8")

                    if case_id == "wrapper":
                        real_wrapper = template_root / "wrapper-real.md.template"
                        real_wrapper.write_text("wrapper\n", encoding="utf-8")
                        (template_root / "wrapper.md.template").symlink_to(
                            real_wrapper.name
                        )
                        wrapper_ref = (
                            "integrations/templates/demo/wrapper.md.template"
                        )
                    elif case_id == "wrapper-parent":
                        real_wrapper_parent = template_root / "wrappers-real"
                        real_wrapper_parent.mkdir()
                        (real_wrapper_parent / "wrapper.md.template").write_text(
                            "wrapper\n",
                            encoding="utf-8",
                        )
                        (template_root / "wrappers").symlink_to(
                            real_wrapper_parent.name,
                            target_is_directory=True,
                        )
                        wrapper_ref = (
                            "integrations/templates/demo/wrappers/wrapper.md.template"
                        )
                    else:
                        (template_root / "wrapper.md.template").write_text(
                            "wrapper\n",
                            encoding="utf-8",
                        )
                        wrapper_ref = (
                            "integrations/templates/demo/wrapper.md.template"
                        )

                registry = {
                    "families": {
                        "demo": {
                            "entrypoint": {
                                "authority_load_syntax": "generic-markdown-read-v1",
                                "output": "AGENTS.md",
                                "path": (
                                    "integrations/templates/demo/AGENTS.md.template"
                                ),
                            },
                            "template_root": "integrations/templates/demo",
                            "wrappers": {
                                "helper": {
                                    "authority_precondition": None,
                                    "lifecycle": (
                                        integration_registry.WRAPPER_PROJECT_INIT_LIFECYCLE
                                    ),
                                    "path": wrapper_ref,
                                }
                            },
                        }
                    }
                }

                with self.assertRaisesRegex(
                    ValueError,
                    "must not use symlink path components",
                ):
                    integration_registry.validate_registry(registry, root)

    def test_integration_registry_rejects_template_root_replacement_during_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template_root = root / "integrations" / "templates" / "demo"
            template_root.mkdir(parents=True)
            (template_root / "AGENTS.md.template").write_text(
                "entrypoint\n",
                encoding="utf-8",
            )
            registry = {
                "families": {
                    "demo": {
                        "entrypoint": {
                            "authority_load_syntax": "generic-markdown-read-v1",
                            "output": "AGENTS.md",
                            "path": (
                                "integrations/templates/demo/AGENTS.md.template"
                            ),
                        },
                        "template_root": "integrations/templates/demo",
                        "wrappers": {},
                    }
                }
            }
            moved_template_root = template_root.with_name("demo-opened")
            real_open = os.open
            substituted = False

            def replace_opened_directory(
                path: Any,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal substituted
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                if path == template_root.name and dir_fd is not None and not substituted:
                    substituted = True
                    template_root.rename(moved_template_root)
                    template_root.symlink_to(
                        moved_template_root,
                        target_is_directory=True,
                    )
                return descriptor

            with (
                mock.patch.object(
                    safe_paths.os,
                    "open",
                    side_effect=replace_opened_directory,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "changed while it was being validated",
                ),
            ):
                integration_registry.validate_registry(registry, root)

        self.assertTrue(substituted)

    def test_safe_paths_rejects_lexically_ambiguous_repo_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for unsafe in ("docs//guide.md", "docs/./guide.md", "https://example.com/guide.md", "docs\\guide.md"):
                with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                    safe_paths.normalize_repo_relative_path(
                        unsafe,
                        root,
                        description="test path",
                    )

    def test_safe_json_inputs_reject_duplicate_keys_oversize_symlinks_and_nonregular_files(self) -> None:
        with self.assertRaisesRegex(
            safe_paths.DuplicateJSONKeyError,
            "duplicate JSON key: runner",
        ) as duplicate:
            safe_paths.loads_json_no_duplicates(
                '{"runner":"reviewed","nested":{"runner":"first","runner":"second"}}'
            )
        self.assertIsInstance(duplicate.exception, json.JSONDecodeError)

        for token in ("NaN", "Infinity", "-Infinity", "1e9999"):
            with self.subTest(token=token), self.assertRaisesRegex(
                safe_paths.NonFiniteJSONNumberError,
                "non-finite JSON number",
            ) as nonfinite:
                safe_paths.loads_json_no_duplicates(f'{{"value":{token}}}')
            self.assertIsInstance(nonfinite.exception, json.JSONDecodeError)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            regular = root / "regular.json"
            regular.write_text("{}", encoding="utf-8")
            self.assertEqual(
                b"{}",
                safe_paths.read_regular_file_bytes(
                    regular,
                    description="test input",
                    max_bytes=16,
                ),
            )

            oversized = root / "oversized.json"
            oversized.write_bytes(b"x" * 17)
            with self.assertRaisesRegex(ValueError, "16-byte input limit"):
                safe_paths.read_regular_file_bytes(
                    oversized,
                    description="test input",
                    max_bytes=16,
                )

            symlinked = root / "symlinked.json"
            symlinked.symlink_to(regular)
            with self.assertRaisesRegex(ValueError, "symlink path components"):
                safe_paths.read_regular_file_bytes(
                    symlinked,
                    description="test input",
                    max_bytes=16,
                )

            outside = root / "outside"
            outside.mkdir()
            (outside / "input.json").write_bytes(b"{}")
            symlinked_parent = root / "symlinked-parent"
            symlinked_parent.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink path components"):
                safe_paths.read_regular_file_bytes(
                    symlinked_parent / "input.json",
                    description="test input",
                    max_bytes=16,
                )

            hardlink = root / "hardlink.json"
            os.link(regular, hardlink)
            with self.assertRaisesRegex(ValueError, "exactly one hard link"):
                safe_paths.read_regular_file_bytes(
                    hardlink,
                    description="test input",
                    max_bytes=16,
                )

            if hasattr(os, "mkfifo"):
                fifo = root / "input.fifo"
                os.mkfifo(fifo)
                with self.assertRaisesRegex(ValueError, "must be a regular file"):
                    safe_paths.read_regular_file_bytes(
                        fifo,
                        description="test input",
                        max_bytes=16,
                    )

    def test_safe_file_read_binds_parent_before_path_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            parent = root / "parent"
            parent.mkdir()
            candidate = parent / "input.json"
            candidate.write_bytes(b"original")
            moved_parent = root / "opened-parent"
            real_open = os.open
            substituted = False

            def intercept_open(
                path: Any,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal substituted
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                if path == parent.name and dir_fd is not None and not substituted:
                    substituted = True
                    parent.rename(moved_parent)
                    parent.mkdir()
                    (parent / candidate.name).write_bytes(b"replacement")
                return descriptor

            with mock.patch.object(safe_paths.os, "open", side_effect=intercept_open):
                raw = safe_paths.read_regular_file_bytes(
                    candidate,
                    description="test input",
                    max_bytes=32,
                )

            self.assertTrue(substituted)
            self.assertEqual(b"original", raw)

    def test_safe_file_read_fails_closed_without_descriptor_walk_support(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "input.json"
            candidate.write_bytes(b"{}")

            with (
                mock.patch.object(safe_paths, "OPEN_SUPPORTS_DIR_FD", False),
                self.assertRaisesRegex(ValueError, "requires os.open dir_fd support"),
            ):
                safe_paths.read_regular_file_bytes(
                    candidate,
                    description="test input",
                    max_bytes=16,
                )

            with (
                mock.patch.object(safe_paths.os, "O_NOFOLLOW", 0),
                self.assertRaisesRegex(ValueError, "requires platform flag O_NOFOLLOW"),
            ):
                safe_paths.read_regular_file_bytes(
                    candidate,
                    description="test input",
                    max_bytes=16,
                )

    def test_safe_file_read_binds_file_before_final_path_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = root / "input.json"
            candidate.write_bytes(b"original")
            moved_file = root / "opened-input.json"
            real_open = os.open
            substituted = False

            def intercept_open(
                path: Any,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal substituted
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                if path == candidate.name and dir_fd is not None and not substituted:
                    substituted = True
                    candidate.rename(moved_file)
                    candidate.write_bytes(b"replacement")
                return descriptor

            with mock.patch.object(safe_paths.os, "open", side_effect=intercept_open):
                raw = safe_paths.read_regular_file_bytes(
                    candidate,
                    description="test input",
                    max_bytes=32,
                )

            self.assertTrue(substituted)
            self.assertEqual(b"original", raw)

    def test_safe_file_read_rejects_concurrent_same_inode_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "input.json"
            candidate.write_bytes(b"original")
            real_read = os.read
            mutated = False

            def intercept_read(descriptor: int, length: int) -> bytes:
                nonlocal mutated
                chunk = real_read(descriptor, length)
                if not mutated:
                    mutated = True
                    candidate.write_bytes(b"changed-content")
                return chunk

            with (
                mock.patch.object(safe_paths.os, "read", side_effect=intercept_read),
                self.assertRaisesRegex(ValueError, "changed while it was being read"),
            ):
                safe_paths.read_regular_file_bytes(
                    candidate,
                    description="test input",
                    max_bytes=32,
                )

            self.assertTrue(mutated)

    def test_integration_registry_rejects_unsafe_family_names(self) -> None:
        registry = {
            "families": {
                "../escape": {
                    "entrypoint": {
                        "authority_load_syntax": "codex-markdown-read-v1",
                        "output": "AGENTS.md",
                        "path": "integrations/templates/codex/AGENTS.md.template",
                    },
                    "template_root": "integrations/templates/codex",
                }
            }
        }

        with self.assertRaises(ValueError):
            integration_registry.validate_registry(registry, REPO_ROOT)

    def test_integration_registry_rejects_unknown_keys_and_duplicate_wrapper_sources(self) -> None:
        unknown = {
            "families": {},
            "invented": True,
        }
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            integration_registry.validate_registry(unknown, REPO_ROOT)

        duplicate_wrapper = {
            "families": {
                "codex": {
                    "entrypoint": {
                        "authority_load_syntax": "codex-markdown-read-v1",
                        "output": "AGENTS.md",
                        "path": "integrations/templates/codex/AGENTS.md.template",
                    },
                    "template_root": "integrations/templates/codex",
                    "wrappers": {
                        "first": {
                            "authority_precondition": (
                                integration_registry.WRAPPER_AUTHORITY_PRECONDITION_ID
                            ),
                            "lifecycle": (
                                integration_registry.WRAPPER_AUTHORITY_CONSUMER_LIFECYCLE
                            ),
                            "path": "integrations/templates/codex/skills/seo/SKILL.md.template",
                            "repo_output": ".agents/skills/seo/SKILL.md",
                        },
                        "second": {
                            "authority_precondition": (
                                integration_registry.WRAPPER_AUTHORITY_PRECONDITION_ID
                            ),
                            "lifecycle": (
                                integration_registry.WRAPPER_AUTHORITY_CONSUMER_LIFECYCLE
                            ),
                            "path": "integrations/templates/codex/skills/seo/SKILL.md.template",
                            "repo_output": ".agents/skills/duplicate/SKILL.md",
                        },
                    },
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "duplicates wrapper"):
            integration_registry.validate_registry(duplicate_wrapper, REPO_ROOT)

    def test_registry_closes_wrapper_packages_and_rejects_unknown_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template_root = root / "integrations" / "templates" / "codex"
            skill_root = template_root / "skills" / "demo"
            skill_root.mkdir(parents=True)
            (template_root / "AGENTS.md.template").write_text(
                "entrypoint\n",
                encoding="utf-8",
            )
            wrapper_path = skill_root / "SKILL.md.template"
            wrapper_path.write_text(
                "---\nname: demo\ndescription: demo\n---\n\n"
                f"{integration_registry.WRAPPER_AUTHORITY_PRECONDITION_MARKER}\n"
                f"{integration_registry.WRAPPER_AUTHORITY_PRECONDITION_CLAUSE}\n\n"
                "Ensure project `AGENT_PROJECT.md` is loaded.\n"
                "Read `{{FRAMEWORK_ROOT}}/runtime/operative_charter.md`.\n",
                encoding="utf-8",
            )
            registry = {
                "families": {
                    "codex": {
                        "entrypoint": {
                            "authority_load_syntax": "codex-markdown-read-v1",
                            "output": "AGENTS.md",
                            "path": (
                                "integrations/templates/codex/AGENTS.md.template"
                            ),
                        },
                        "template_root": "integrations/templates/codex",
                        "wrappers": {
                            "demo": {
                                "authority_precondition": (
                                    integration_registry.WRAPPER_AUTHORITY_PRECONDITION_ID
                                ),
                                "lifecycle": (
                                    integration_registry.WRAPPER_AUTHORITY_CONSUMER_LIFECYCLE
                                ),
                                "path": (
                                    "integrations/templates/codex/skills/demo/"
                                    "SKILL.md.template"
                                ),
                                "repo_output": ".agents/skills/demo/SKILL.md",
                            }
                        },
                    }
                }
            }

            self.assertIs(registry, integration_registry.validate_registry(registry, root))

            unexpected_file = skill_root / "asset.txt"
            unexpected_file.write_text("unregistered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unregistered integration content"):
                integration_registry.validate_registry(registry, root)
            unexpected_file.unlink()

            unexpected_directory = skill_root / "assets"
            unexpected_directory.mkdir()
            with self.assertRaisesRegex(ValueError, "unregistered integration content"):
                integration_registry.validate_registry(registry, root)
            unexpected_directory.rmdir()

            wrapper_path.write_text(
                "---\nname: demo\ndescription: demo\n---\n\n"
                f"{integration_registry.WRAPPER_AUTHORITY_PRECONDITION_MARKER}\n"
                f"{integration_registry.WRAPPER_AUTHORITY_PRECONDITION_CLAUSE}\n\n"
                "Ensure project `AGENT_PROJECT.md` is loaded.\n"
                "Read `{{UNKNOWN_ROOT}}/runtime/operative_charter.md`.\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unresolved template placeholder"):
                integration_registry.validate_registry(registry, root)

    def test_registry_enforces_closed_wrapper_lifecycle_preconditions(self) -> None:
        registry = integration_registry.load_registry(REPO_ROOT)
        lifecycles = {
            (family, wrapper): wrapper_config["lifecycle"]
            for family, config in registry["families"].items()
            for wrapper, wrapper_config in config["wrappers"].items()
        }
        self.assertEqual(
            {
                ("claude-code", "security_audit"): (
                    integration_registry.WRAPPER_AUTHORITY_CONSUMER_LIFECYCLE
                ),
                ("claude-code", "seo"): (
                    integration_registry.WRAPPER_AUTHORITY_CONSUMER_LIFECYCLE
                ),
                ("codex", "project_init"): (
                    integration_registry.WRAPPER_PROJECT_INIT_LIFECYCLE
                ),
                ("codex", "project_refresh"): (
                    integration_registry.WRAPPER_PROJECT_REFRESH_LIFECYCLE
                ),
                ("codex", "security_audit"): (
                    integration_registry.WRAPPER_AUTHORITY_CONSUMER_LIFECYCLE
                ),
                ("codex", "seo"): (
                    integration_registry.WRAPPER_AUTHORITY_CONSUMER_LIFECYCLE
                ),
            },
            lifecycles,
        )
        for config in registry["families"].values():
            for wrapper_config in config["wrappers"].values():
                self.assertIn("lifecycle", wrapper_config)
                self.assertIn("authority_precondition", wrapper_config)

        marker = integration_registry.WRAPPER_AUTHORITY_PRECONDITION_MARKER
        clause = integration_registry.WRAPPER_AUTHORITY_PRECONDITION_CLAUSE

        def wrapper_text(body: str) -> str:
            return (
                "---\nname: demo\ndescription: demo\n---\n\n"
                "# Demo\n\n"
                f"{body}\n"
            )

        valid_body = (
            f"{marker}\n{clause}\n\n"
            "Ensure project `AGENT_PROJECT.md` is loaded."
        )
        invalid_cases = (
            (
                "missing",
                f"{clause}\n\nEnsure project `AGENT_PROJECT.md` is loaded.",
                "marker occurs 0 times",
            ),
            (
                "fenced-decoy",
                f"```text\n{marker}\n{clause}\n```\n\n"
                "Ensure project `AGENT_PROJECT.md` is loaded.",
                "marker occurs 0 times",
            ),
            (
                "commented-decoy",
                f"<!--\n{marker}\n{clause}\n-->\n\n"
                "Ensure project `AGENT_PROJECT.md` is loaded.",
                "marker occurs 0 times",
            ),
            (
                "late",
                "Ensure project `AGENT_PROJECT.md` is loaded.\n\n"
                f"{marker}\n{clause}",
                "reference occurs before the wrapper authority precondition",
            ),
            (
                "paraphrased",
                f"{marker}\nConfirm setup first.\n\n"
                "Ensure project `AGENT_PROJECT.md` is loaded.",
                "must contain the exact active clause once",
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template_root = root / "integrations" / "templates" / "codex"
            skill_root = template_root / "skills" / "demo"
            skill_root.mkdir(parents=True)
            (template_root / "AGENTS.md.template").write_text(
                "entrypoint\n",
                encoding="utf-8",
            )
            wrapper_path = skill_root / "SKILL.md.template"
            wrapper_path.write_text(wrapper_text(valid_body), encoding="utf-8")
            fixture = {
                "families": {
                    "codex": {
                        "entrypoint": {
                            "authority_load_syntax": "codex-markdown-read-v1",
                            "output": "AGENTS.md",
                            "path": "integrations/templates/codex/AGENTS.md.template",
                        },
                        "template_root": "integrations/templates/codex",
                        "wrappers": {
                            "demo": {
                                "authority_precondition": (
                                    integration_registry.WRAPPER_AUTHORITY_PRECONDITION_ID
                                ),
                                "lifecycle": (
                                    integration_registry.WRAPPER_AUTHORITY_CONSUMER_LIFECYCLE
                                ),
                                "path": (
                                    "integrations/templates/codex/skills/demo/"
                                    "SKILL.md.template"
                                ),
                                "repo_output": ".agents/skills/demo/SKILL.md",
                            }
                        },
                    }
                }
            }
            self.assertIs(
                fixture,
                integration_registry.validate_registry(fixture, root),
            )

            for case_id, body, expected_error in invalid_cases:
                with self.subTest(case=case_id):
                    wrapper_path.write_text(wrapper_text(body), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, expected_error):
                        integration_registry.validate_registry(fixture, root)

            wrapper_path.write_text(wrapper_text(valid_body), encoding="utf-8")
            fixture["families"]["codex"]["wrappers"]["demo"][
                "authority_precondition"
            ] = "unknown-policy"
            with self.assertRaisesRegex(
                ValueError,
                "requires authority_precondition",
            ):
                integration_registry.validate_registry(fixture, root)

            fixture["families"]["codex"]["wrappers"]["demo"][
                "authority_precondition"
            ] = integration_registry.WRAPPER_AUTHORITY_PRECONDITION_ID

            fixture["families"]["codex"]["wrappers"]["demo"][
                "lifecycle"
            ] = "unknown-lifecycle-v1"
            with self.assertRaisesRegex(ValueError, "lifecycle must be one of"):
                integration_registry.validate_registry(fixture, root)

            fixture["families"]["codex"]["wrappers"]["demo"][
                "lifecycle"
            ] = integration_registry.WRAPPER_PROJECT_INIT_LIFECYCLE
            fixture["families"]["codex"]["wrappers"]["demo"][
                "authority_precondition"
            ] = None
            with self.assertRaisesRegex(ValueError, "does not permit it"):
                integration_registry.validate_registry(fixture, root)

        source = json.loads(
            (REPO_ROOT / "integrations" / "registry.json").read_text(
                encoding="utf-8"
            )
        )
        for family, config in source["families"].items():
            for wrapper in config["wrappers"]:
                for field in ("lifecycle", "authority_precondition"):
                    with self.subTest(
                        family=family,
                        wrapper=wrapper,
                        omitted=field,
                    ):
                        fixture = json.loads(json.dumps(source))
                        fixture["families"][family]["wrappers"][wrapper].pop(field)
                        with self.assertRaisesRegex(
                            ValueError,
                            "must explicitly declare",
                        ):
                            integration_registry.validate_registry(
                                fixture,
                                REPO_ROOT,
                            )

    def test_registry_binds_wrapper_frontmatter_to_native_output_identity(self) -> None:
        fixtures = (
            (
                "codex",
                "project_init",
                ".agents/skills/wrong-name/SKILL.md",
                "must match its registry-owned destination identity",
            ),
            (
                "claude-code",
                "security_audit",
                ".claude/agents/wrong-name.md",
                "must be the one native wrapper template file",
            ),
        )
        source = json.loads(
            (REPO_ROOT / "integrations" / "registry.json").read_text(
                encoding="utf-8"
            )
        )
        for family, wrapper, output, expected_error in fixtures:
            with self.subTest(family=family, wrapper=wrapper):
                registry = json.loads(json.dumps(source))
                registry["families"][family]["wrappers"][wrapper][
                    "repo_output"
                ] = output
                with self.assertRaisesRegex(
                    ValueError,
                    expected_error,
                ):
                    integration_registry.validate_registry(registry, REPO_ROOT)

    def test_registered_renderer_matches_bootstrap_wrapper_outputs_exactly(self) -> None:
        framework_ref = "$FRAMEWORK"
        contract_root = "contracts"
        for family in integration_registry.family_names(REPO_ROOT):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as temp_dir:
                output_root = Path(temp_dir)
                plan = render_integrations.build_registered_render_plan(
                    family,
                    REPO_ROOT,
                    output_root,
                    framework_ref,
                    force=False,
                    contract_root_ref=contract_root,
                )
                planned = {
                    item.target.relative_to(output_root).as_posix(): item.content.decode(
                        "utf-8"
                    )
                    for item in plan.files
                }
                wrapper_ids = integration_registry.wrapper_names(family, REPO_ROOT)
                expected_wrappers = integration_registry.render_wrapper_outputs(
                    family,
                    wrapper_ids,
                    framework_ref,
                    contract_root,
                    REPO_ROOT,
                )
                self.assertEqual(
                    expected_wrappers,
                    {
                        output: planned[output]
                        for output in expected_wrappers
                    },
                )
                self.assertEqual(1 + len(wrapper_ids), len(planned))

    def test_checked_in_codex_skill_outputs_match_self_reference_render(self) -> None:
        registry = integration_registry.load_registry(REPO_ROOT)
        wrapper_ids = integration_registry.wrapper_names("codex", REPO_ROOT)
        rendered = integration_registry.render_wrapper_outputs(
            "codex",
            wrapper_ids,
            ".",
            ".",
            REPO_ROOT,
        )
        for wrapper_id, wrapper in registry["families"]["codex"]["wrappers"].items():
            with self.subTest(wrapper=wrapper_id):
                output = wrapper["repo_output"]
                if not product_manifest.is_product_path(output):
                    continue
                self.assertTrue((REPO_ROOT / output).is_file(), output)
                self.assertEqual(
                    rendered[output],
                    (REPO_ROOT / output).read_text(encoding="utf-8"),
                )

    def test_codex_skill_references_resolve_from_each_skill_directory(self) -> None:
        framework_files = {
            "runtime/operative_charter.md",
            "GETTING_STARTED.md",
            "UPDATING.md",
            "task_orders/init.md",
            "task_orders/framework_refresh.md",
            "scripts/project_refresh.py",
            "practice_guides/security_audit.md",
            "practice_guides/seo.md",
        }
        project_files = {
            "AGENT_PROJECT.md",
            "STATEMENT_OF_WORK.md",
            "SOURCE_PACKS.md",
            "SOURCE_UPDATE.md",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            framework_root = root / "framework"
            contract_root = project_root / "contracts"
            for relative in framework_files:
                path = framework_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n", encoding="utf-8")
            for name in project_files:
                path = contract_root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n", encoding="utf-8")

            wrapper_ids = integration_registry.wrapper_names("codex", REPO_ROOT)
            rendered = integration_registry.render_wrapper_outputs(
                "codex",
                wrapper_ids,
                "../framework",
                "contracts",
                REPO_ROOT,
            )
            output_by_id = integration_registry.wrapper_output_map(
                "codex",
                wrapper_ids,
                REPO_ROOT,
            )

            expected_by_id = {
                "project_init": {
                    "../../../../framework/runtime/operative_charter.md",
                    "../../../../framework/GETTING_STARTED.md",
                    "../../../../framework/task_orders/init.md",
                },
                "project_refresh": {
                    "../../../../framework/runtime/operative_charter.md",
                    "../../../../framework/UPDATING.md",
                    "../../../../framework/task_orders/framework_refresh.md",
                    "../../../../framework/scripts/project_refresh.py",
                },
                "security_audit": {
                    "../../../../framework/runtime/operative_charter.md",
                    "../../../../framework/practice_guides/security_audit.md",
                    "../../../contracts/AGENT_PROJECT.md",
                    "../../../contracts/STATEMENT_OF_WORK.md",
                    "../../../contracts/SOURCE_PACKS.md",
                    "../../../contracts/SOURCE_UPDATE.md",
                },
                "seo": {
                    "../../../../framework/runtime/operative_charter.md",
                    "../../../../framework/practice_guides/seo.md",
                    "../../../contracts/AGENT_PROJECT.md",
                    "../../../contracts/STATEMENT_OF_WORK.md",
                    "../../../contracts/SOURCE_PACKS.md",
                    "../../../contracts/SOURCE_UPDATE.md",
                },
            }
            for wrapper_id, expected_references in expected_by_id.items():
                output = output_by_id[wrapper_id]
                skill_path = project_root / output
                skill_path.parent.mkdir(parents=True, exist_ok=True)
                skill_path.write_text(rendered[output], encoding="utf-8")
                for reference in expected_references:
                    with self.subTest(wrapper=wrapper_id, reference=reference):
                        self.assertIn(reference, rendered[output])
                        self.assertTrue(
                            (skill_path.parent / reference).resolve().is_file(),
                            skill_path.parent / reference,
                        )

    def test_checked_in_codex_launcher_references_resolve_from_skill_directory(self) -> None:
        expected = {
            ".agents/skills/master-prompt-new-project/SKILL.md": (
                "../../../runtime/operative_charter.md",
                "../../../GETTING_STARTED.md",
                "../../../task_orders/init.md",
            ),
            ".agents/skills/master-prompt-refresh-project/SKILL.md": (
                "../../../runtime/operative_charter.md",
                "../../../UPDATING.md",
                "../../../task_orders/framework_refresh.md",
                "../../../scripts/project_refresh.py",
            ),
        }
        for relative, references in expected.items():
            skill = REPO_ROOT / relative
            text = skill.read_text(encoding="utf-8")
            for reference in references:
                with self.subTest(skill=relative, reference=reference):
                    self.assertIn(reference, text)
                    self.assertTrue((skill.parent / reference).resolve().is_file())

    def test_render_integrations_rejects_unsafe_framework_ref_and_overwrite(self) -> None:
        self.assertIn(
            "framework reference must not contain shell or Markdown metacharacters",
            safe_paths.framework_reference_errors("</system>"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template_root = root / "templates"
            output_root = root / "out"
            template_root.mkdir()
            output_root.mkdir()
            (template_root / "AGENTS.md.template").write_text(
                "Read {{FRAMEWORK_ROOT}}/runtime/operative_charter.md\n",
                encoding="utf-8",
            )
            (output_root / "AGENTS.md").write_text("existing\n", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                render_integrations.render_templates(template_root, output_root, "$FRAMEWORK", force=False)

    def test_render_integrations_canonicalizes_framework_and_nested_contract_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template_root = root / "templates"
            output_root = root / "out"
            template_root.mkdir()
            (template_root / "AGENTS.md.template").write_text(
                "Read {{FRAMEWORK_ROOT}}/runtime/operative_charter.md, "
                "AGENT_PROJECT.md, @./AGENT_PROJECT.md, and "
                "already/AGENT_PROJECT.md.\n",
                encoding="utf-8",
            )

            written = render_integrations.render_templates(
                template_root,
                output_root,
                "/",
                force=False,
                contract_root_ref="contracts/AGENT_PROJECT.md-bundle",
            )
            rendered = written[0].read_text(encoding="utf-8")

        self.assertIn("/runtime/operative_charter.md", rendered)
        self.assertNotIn("//runtime", rendered)
        self.assertIn(
            "contracts/AGENT_PROJECT.md-bundle/AGENT_PROJECT.md",
            rendered,
        )
        self.assertIn(
            "@./contracts/AGENT_PROJECT.md-bundle/AGENT_PROJECT.md",
            rendered,
        )
        self.assertIn("already/AGENT_PROJECT.md", rendered)
        self.assertNotIn(
            "contracts/AGENT_PROJECT.md-bundle/already/AGENT_PROJECT.md",
            rendered,
        )

    def test_nested_contract_root_reaches_every_integration_entrypoint(self) -> None:
        expected_imports = {
            "claude-code": "Read `contracts/AGENT_PROJECT.md`",
            "codex": "Read `contracts/AGENT_PROJECT.md`",
            "generic": "Read `contracts/AGENT_PROJECT.md`",
        }
        families = integration_registry.family_names(REPO_ROOT)
        self.assertEqual(set(expected_imports), set(families))
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            for family in families:
                expected = expected_imports[family]
                with self.subTest(family=family):
                    family_output = output_root / family
                    plan = render_integrations.build_registered_render_plan(
                        family,
                        REPO_ROOT,
                        family_output,
                        "$FRAMEWORK",
                        force=False,
                        contract_root_ref="contracts",
                    )
                    render_integrations.install_render_plan(plan)
                    config = integration_registry.family_config(family, REPO_ROOT)
                    entrypoint = family_output / config["entrypoint"]["output"]
                    rendered = entrypoint.read_text(encoding="utf-8")
                    self.assertIn(expected, rendered)

    def test_render_integrations_rejects_symlink_sources_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template_root = root / "templates"
            output_root = root / "out"
            template_root.mkdir()
            output_root.mkdir()
            outside_template = root / "outside.template"
            outside_template.write_text("Read {{FRAMEWORK_ROOT}}\n", encoding="utf-8")
            (template_root / "AGENTS.md.template").symlink_to(outside_template)

            with self.assertRaises(ValueError):
                render_integrations.render_templates(template_root, output_root, "$FRAMEWORK", force=True)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template_root = root / "templates"
            output_root = root / "out"
            template_root.mkdir()
            output_root.mkdir()
            (template_root / "AGENTS.md.template").write_text(
                "Read {{FRAMEWORK_ROOT}}\n",
                encoding="utf-8",
            )
            (output_root / "AGENTS.md").symlink_to(root / "outside.md")

            with self.assertRaises(ValueError):
                render_integrations.render_templates(
                    template_root,
                    output_root,
                    "$FRAMEWORK",
                    force=True,
                )

    def test_render_integrations_rejects_duplicate_rendered_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template_root = root / "templates"
            output_root = root / "out"
            template_root.mkdir()
            (template_root / "same").write_bytes(b"plain")
            (template_root / "same.template").write_text(
                "{{FRAMEWORK_ROOT}}",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "render to one target"):
                render_integrations.render_templates(
                    template_root,
                    output_root,
                    "$FRAMEWORK",
                    force=False,
                )

        self.assertFalse(output_root.exists())

    def test_render_integrations_rejects_file_directory_target_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template_root = root / "templates"
            output_root = root / "out"
            template_root.mkdir()
            (template_root / "folder").mkdir()
            (template_root / "folder.template").write_text(
                "{{FRAMEWORK_ROOT}}",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "both a file and directory"):
                render_integrations.render_templates(
                    template_root,
                    output_root,
                    "$FRAMEWORK",
                    force=False,
                )

        self.assertFalse(output_root.exists())

    def test_render_integrations_preflights_all_sources_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template_root = root / "templates"
            output_root = root / "out"
            template_root.mkdir()
            (template_root / "a.md.template").write_text(
                "Read {{FRAMEWORK_ROOT}}\n",
                encoding="utf-8",
            )
            (template_root / "z.md.template").write_text(
                "Unresolved {{UNKNOWN}}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unresolved template placeholder"):
                render_integrations.render_templates(
                    template_root,
                    output_root,
                    "$FRAMEWORK",
                    force=False,
                )

        self.assertFalse(output_root.exists())

    def test_render_integrations_rejects_nonregular_template_entries(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template_root = root / "templates"
            output_root = root / "out"
            template_root.mkdir()
            os.mkfifo(template_root / "blocked")

            with self.assertRaisesRegex(ValueError, "directory or regular file"):
                render_integrations.render_templates(
                    template_root,
                    output_root,
                    "$FRAMEWORK",
                    force=False,
                )

        self.assertFalse(output_root.exists())

    def test_safe_write_bytes_is_atomic_and_preserves_forced_target_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "output.bin"
            safe_paths.write_bytes(target, b"\x00first\xff", root=root)
            self.assertEqual(b"\x00first\xff", target.read_bytes())
            target.chmod(0o640)

            safe_paths.write_bytes(
                target,
                b"\x00replacement\xff",
                force=True,
                root=root,
            )

            self.assertEqual(b"\x00replacement\xff", target.read_bytes())
            self.assertEqual(0o640, stat.S_IMODE(target.stat().st_mode))
            self.assertEqual([], list(root.glob(".output.bin.tmp-*")))

    def test_output_directory_binding_rejects_substituted_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "base"
            target = base / "ancestor" / "leaf"
            target.mkdir(parents=True)
            binding = safe_paths.open_output_directory(target)
            moved = base / "ancestor-moved"
            (base / "ancestor").rename(moved)
            (base / "ancestor").symlink_to(moved, target_is_directory=True)
            try:
                with self.assertRaisesRegex(
                    ValueError,
                    "pathname component no longer identifies",
                ):
                    binding.require_lexical_binding()
            finally:
                binding.close()
                binding.close()
            with self.assertRaisesRegex(ValueError, "binding is closed"):
                binding.fileno()

    def test_output_directory_unchanged_chain_allows_unrelated_sibling_creation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "base"
            target = base / "ancestor" / "leaf"
            target.mkdir(parents=True)
            binding = safe_paths.open_output_directory(
                target,
                create_missing=False,
            )
            try:
                (target.parent / "unrelated-sibling").mkdir()
                binding.require_unchanged_chain(description="release tree")
            finally:
                binding.close()

    def test_output_directory_no_create_mode_leaves_missing_path_absent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "base"
            base.mkdir()
            target = base / "missing"

            with self.assertRaises(
                safe_paths.OutputDirectoryBindingError
            ) as failure:
                safe_paths.open_output_directory(
                    target,
                    create_missing=False,
                )

            self.assertFalse(target.exists())
            self.assertEqual((), failure.exception.created_or_uncertain_paths)
            self.assertIsInstance(failure.exception.__cause__, FileNotFoundError)

    def test_output_directory_interruption_preserves_exception_and_receipt(
        self,
    ) -> None:
        cases = (
            ("mkdir", KeyboardInterrupt("injected mkdir interruption")),
            ("fsync", SystemExit(29)),
        )
        for operation, injected in cases:
            with self.subTest(
                operation=operation,
                exception=type(injected).__name__,
            ):
                with tempfile.TemporaryDirectory() as temp_dir:
                    base = Path(temp_dir) / "base"
                    base.mkdir()
                    target = base / "created"
                    real_mkdir = os.mkdir
                    real_fsync = os.fsync

                    def create_then_interrupt(
                        path: str | bytes,
                        mode: int = 0o777,
                        *,
                        dir_fd: int | None = None,
                    ) -> None:
                        real_mkdir(path, mode=mode, dir_fd=dir_fd)
                        raise injected

                    def sync_then_interrupt(descriptor: int) -> None:
                        real_fsync(descriptor)
                        raise injected

                    side_effect = (
                        create_then_interrupt
                        if operation == "mkdir"
                        else sync_then_interrupt
                    )
                    with (
                        mock.patch.object(
                            safe_paths.os,
                            operation,
                            side_effect=side_effect,
                        ),
                        self.assertRaises(type(injected)) as failure,
                    ):
                        safe_paths.open_output_directory(target)

                    self.assertIs(injected, failure.exception)
                    self.assertTrue(target.is_dir())
                    notes = getattr(failure.exception, "__notes__", ())
                    self.assertIn(str(target), "\n".join(notes))

    def test_output_directory_cleanup_fault_preserves_interruption_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "base"
            base.mkdir()
            target = base / "created"
            interruption = KeyboardInterrupt("injected allocation interruption")
            original_fsync = os.fsync
            original_close = os.close
            close_calls: list[int] = []
            leaked_descriptor: list[int] = []

            def sync_then_interrupt(descriptor: int) -> None:
                original_fsync(descriptor)
                raise interruption

            def fault_first_close(descriptor: int) -> None:
                close_calls.append(descriptor)
                if not leaked_descriptor:
                    leaked_descriptor.append(descriptor)
                    raise OSError("injected descriptor cleanup failure")
                original_close(descriptor)

            try:
                with (
                    mock.patch.object(
                        safe_paths.os,
                        "fsync",
                        side_effect=sync_then_interrupt,
                    ),
                    mock.patch.object(
                        safe_paths.os,
                        "close",
                        side_effect=fault_first_close,
                    ),
                    self.assertRaises(KeyboardInterrupt) as failure,
                ):
                    safe_paths.open_output_directory(target)
            finally:
                for descriptor in leaked_descriptor:
                    try:
                        original_close(descriptor)
                    except OSError:
                        pass

            self.assertIs(interruption, failure.exception)
            self.assertGreaterEqual(len(close_calls), 2)
            notes = "\n".join(getattr(failure.exception, "__notes__", ()))
            self.assertIn(str(target), notes)
            self.assertIn("injected descriptor cleanup failure", notes)

    def test_shared_descriptor_cleanup_attempts_all_and_preserves_primary(
        self,
    ) -> None:
        descriptors = [os.open(os.devnull, os.O_RDONLY) for _ in range(3)]
        original_close = os.close
        close_calls: list[int] = []
        faulted = False
        primary = KeyboardInterrupt("injected primary interruption")

        def close_then_fault(descriptor: int) -> None:
            nonlocal faulted
            close_calls.append(descriptor)
            original_close(descriptor)
            if not faulted:
                faulted = True
                raise OSError("injected shared cleanup failure")

        with mock.patch.object(
            safe_paths.os,
            "close",
            side_effect=close_then_fault,
        ):
            safe_paths._cleanup_descriptors(
                tuple((f"descriptor {index}", descriptor) for index, descriptor in enumerate(descriptors)),
                primary=primary,
            )

        self.assertEqual(descriptors, close_calls)
        self.assertIn(
            "injected shared cleanup failure",
            "\n".join(getattr(primary, "__notes__", ())),
        )
        for descriptor in descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_output_directory_factory_rechecks_all_retained_ancestors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "base"
            target = base / "ancestor" / "leaf"
            target.mkdir(parents=True)
            moved = base / "ancestor-moved"
            original_open = safe_paths.os.open
            substituted = False

            def substitute_after_leaf_open(
                path: str | bytes,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal substituted
                descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
                if path == target.name and not substituted:
                    (base / "ancestor").rename(moved)
                    (base / "ancestor").symlink_to(
                        moved,
                        target_is_directory=True,
                    )
                    substituted = True
                return descriptor

            with (
                mock.patch.object(
                    safe_paths.os,
                    "open",
                    side_effect=substitute_after_leaf_open,
                ),
                self.assertRaises(
                    safe_paths.OutputDirectoryBindingError
                ) as failure,
            ):
                safe_paths.open_output_directory(target)

            self.assertTrue(substituted)
            self.assertIn(
                "pathname component no longer identifies",
                str(failure.exception.__cause__),
            )

    def test_output_directory_binding_reports_created_path_when_reopen_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "base"
            base.mkdir()
            target = base / "new" / "leaf"
            original_open = safe_paths.os.open
            new_component_opens = 0

            def fail_created_component_reopen(
                path: str | bytes,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal new_component_opens
                if path == "new":
                    new_component_opens += 1
                    if new_component_opens == 2:
                        raise OSError("injected reopen failure")
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with (
                mock.patch.object(
                    safe_paths.os,
                    "open",
                    side_effect=fail_created_component_reopen,
                ),
                self.assertRaises(safe_paths.OutputDirectoryBindingError) as failure,
            ):
                safe_paths.open_output_directory(target)

            self.assertTrue((base / "new").is_dir())
            self.assertIn(base / "new", failure.exception.created_or_uncertain_paths)

    def test_safe_write_preserves_existing_target_when_install_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "output.txt"
            target.write_text("existing\n", encoding="utf-8")

            with (
                mock.patch.object(
                    safe_paths.os,
                    "replace",
                    side_effect=OSError("simulated install failure"),
                ),
                self.assertRaisesRegex(OSError, "simulated install failure"),
            ):
                safe_paths.write_text(
                    target,
                    "replacement\n",
                    force=True,
                    root=root,
                )

            self.assertEqual("existing\n", target.read_text(encoding="utf-8"))
            self.assertEqual([], list(root.glob(".output.txt.tmp-*")))

    def test_safe_write_nonforce_does_not_clobber_target_appearing_at_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "output.txt"
            real_link = os.link

            def install_after_target_appears(
                source: str,
                destination: str,
                **kwargs: Any,
            ) -> None:
                target.write_text("appeared\n", encoding="utf-8")
                real_link(source, destination, **kwargs)

            with (
                mock.patch.object(
                    safe_paths.os,
                    "link",
                    side_effect=install_after_target_appears,
                ),
                self.assertRaisesRegex(FileExistsError, "appeared during atomic"),
            ):
                safe_paths.write_text(target, "intended\n", root=root)

            self.assertEqual("appeared\n", target.read_text(encoding="utf-8"))
            self.assertEqual([], list(root.glob(".output.txt.tmp-*")))

    def test_safe_write_does_not_follow_parent_appearing_during_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "root"
            outside = Path(temp_dir) / "outside"
            root.mkdir()
            outside.mkdir()
            target = root / "nested" / "output.txt"
            real_mkdir = os.mkdir

            def replace_parent_with_symlink(
                path: str,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> None:
                if path == "nested":
                    (root / "nested").symlink_to(outside, target_is_directory=True)
                    return
                real_mkdir(path, mode=mode, dir_fd=dir_fd)

            with (
                mock.patch.object(
                    safe_paths.os,
                    "mkdir",
                    side_effect=replace_parent_with_symlink,
                ),
                self.assertRaises(OSError),
            ):
                safe_paths.write_text(target, "intended\n", root=root)

            self.assertFalse((outside / "output.txt").exists())

    def test_reference_snapshot_blocks_local_urls_before_opening(self) -> None:
        with mock.patch.object(reference_snapshot, "safe_urlopen") as opener:
            with self.assertRaises(SystemExit):
                reference_snapshot.fetch_url("http://example.com/status")
            with self.assertRaises(SystemExit):
                reference_snapshot.fetch_url("https://localhost/status")
            with self.assertRaises(SystemExit):
                reference_snapshot.fetch_url("https://169.254.169.254/latest/meta-data")

        opener.assert_not_called()

    def test_reference_snapshot_encodes_github_path_and_ref_separator(self) -> None:
        payload = base64.b64encode(b"# Example\n").decode("ascii")
        response = mock.MagicMock()
        response.__enter__.return_value.headers = {"content-type": "application/json; charset=utf-8"}
        response.__enter__.return_value.read.return_value = json.dumps({"content": payload}).encode("utf-8")
        response.__exit__.return_value = None
        with mock.patch.object(reference_snapshot, "safe_urlopen", return_value=response) as opener:
            self.assertEqual("# Example\n", reference_snapshot.fetch_github("owner/repo", "docs/a?b&c.md", "a" * 40))

        self.assertEqual(
            "https://api.github.com/repos/owner/repo/contents/docs/a%3Fb%26c.md?ref=" + "a" * 40,
            opener.call_args.args[0].full_url,
        )

    def test_reference_snapshot_rejects_ambiguous_github_paths_and_malformed_payloads(self) -> None:
        for path in ("docs//source.md", "docs/./source.md", "docs\\source.md"):
            with self.subTest(path=path), self.assertRaises(SystemExit):
                reference_snapshot.fetch_github("owner/repo", path, "a" * 40)

        wrong_type = mock.MagicMock()
        wrong_type.__enter__.return_value.headers = {"content-type": "text/html"}
        wrong_type.__enter__.return_value.read.return_value = b"<html>not JSON</html>"
        malformed = mock.MagicMock()
        malformed.__enter__.return_value.headers = {"content-type": "application/json"}
        malformed.__enter__.return_value.read.return_value = json.dumps({"content": "%%%"}).encode("utf-8")

        with mock.patch.object(reference_snapshot, "safe_urlopen", return_value=wrong_type):
            with self.assertRaisesRegex(SystemExit, "JSON content type"):
                reference_snapshot.fetch_github("owner/repo", "docs/source.md", "a" * 40)
        with mock.patch.object(reference_snapshot, "safe_urlopen", return_value=malformed):
            with self.assertRaisesRegex(SystemExit, "not valid base64"):
                reference_snapshot.fetch_github("owner/repo", "docs/source.md", "a" * 40)

    def test_reference_snapshot_rejects_symlink_and_oversized_local_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.md"
            source.write_text("source\n", encoding="utf-8")
            linked = root / "linked.md"
            linked.symlink_to(source)
            oversized = root / "oversized.md"
            oversized.write_bytes(b"x" * (reference_snapshot.MAX_SNAPSHOT_BYTES + 1))
            invalid_utf8 = root / "invalid-utf8.md"
            invalid_utf8.write_bytes(b"\xff\xfe")
            hardlink_origin = root / "hardlink-origin.md"
            hardlink_origin.write_text("hardlinked source\n", encoding="utf-8")
            hardlinked = root / "hardlinked.md"
            os.link(hardlink_origin, hardlinked)
            output = root / "snapshot.md"

            for candidate, expected in (
                (linked, "must not be a symlink"),
                (oversized, "byte input limit"),
                (invalid_utf8, "UTF-8 text"),
                (hardlinked, "exactly one hard link"),
            ):
                with self.subTest(candidate=candidate):
                    with mock.patch(
                        "sys.argv",
                        [
                            "reference_snapshot.py",
                            "--source-file",
                            str(candidate),
                            "--source-label",
                            "source.md",
                            "--output",
                            str(output),
                        ],
                    ):
                        with self.assertRaisesRegex(SystemExit, expected):
                            reference_snapshot.main()

    def test_reference_snapshot_reads_opened_leaf_not_symlink_substitution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.md"
            source.write_text("BENIGN-SOURCE-CONTENT\n", encoding="utf-8")
            opened_source = root / "opened-source.md"
            private_source = root / "private.md"
            private_source.write_text(
                "PRIVATE-SENTINEL-MUST-NOT-LEAK\n",
                encoding="utf-8",
            )
            output = root / "snapshot.md"
            real_open = os.open
            substituted = False

            def substitute_leaf_after_open(
                path: Any,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal substituted
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                if path == source.name and dir_fd is not None and not substituted:
                    substituted = True
                    source.rename(opened_source)
                    source.symlink_to(private_source)
                return descriptor

            with (
                mock.patch.object(
                    safe_paths.os,
                    "open",
                    side_effect=substitute_leaf_after_open,
                ),
                mock.patch(
                    "sys.argv",
                    [
                        "reference_snapshot.py",
                        "--source-file",
                        str(source),
                        "--source-label",
                        "source.md",
                        "--output",
                        str(output),
                    ],
                ),
                mock.patch("sys.stdout", new_callable=io.StringIO),
            ):
                self.assertEqual(0, reference_snapshot.main())

            rendered = output.read_text(encoding="utf-8")
            self.assertTrue(substituted)
            self.assertTrue(source.is_symlink())
            self.assertIn("BENIGN-SOURCE-CONTENT", rendered)
            self.assertNotIn("PRIVATE-SENTINEL-MUST-NOT-LEAK", rendered)

    def test_reference_snapshot_requires_safe_label_for_outside_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            work = root / "work"
            outside = root / "outside.md"
            output = work / "snapshot.md"
            work.mkdir()
            outside.write_text("# Outside\n", encoding="utf-8")

            with mock.patch("sys.argv", ["reference_snapshot.py", "--source-file", str(outside), "--output", str(output)]):
                with mock.patch.object(reference_snapshot.Path, "cwd", return_value=work):
                    with self.assertRaises(SystemExit):
                        reference_snapshot.main()

            with mock.patch(
                "sys.argv",
                [
                    "reference_snapshot.py",
                    "--source-file",
                    str(outside),
                    "--source-label",
                    "outside.md",
                    "--output",
                    str(output),
                ],
            ):
                with mock.patch.object(reference_snapshot.Path, "cwd", return_value=work):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        self.assertEqual(0, reference_snapshot.main())

            self.assertEqual(
                {"output": str(output), "source": "outside.md"},
                json.loads(stdout.getvalue()),
            )

            text = output.read_text(encoding="utf-8")
            self.assertIn("Source: outside.md", text)
            self.assertNotIn(str(outside), text)

    def test_reference_snapshot_rejects_unsafe_title_and_labels(self) -> None:
        with self.assertRaises(SystemExit):
            reference_snapshot.validate_plain_label("--title", "Bad\nTitle")
        with self.assertRaises(SystemExit):
            reference_snapshot.validate_plain_label("--title", "</system>")
        with self.assertRaises(SystemExit):
            reference_snapshot.validate_plain_label("--source-label", "https://example.com/source")

    def test_reference_snapshot_uses_source_date_epoch_in_utc(self) -> None:
        with mock.patch.dict(reference_snapshot.os.environ, {"SOURCE_DATE_EPOCH": "86399"}, clear=False):
            self.assertEqual("1970-01-01", reference_snapshot.retrieved_date(None))

    def test_reference_snapshot_uses_content_safe_markdown_fence(self) -> None:
        content = "trusted text\n```text\n# injected heading\n```\nmore text"
        rendered = reference_snapshot.render_snapshot("Example", "source.md", content, "2026-06-19")

        self.assertIn("````text\ntrusted text", rendered)
        self.assertIn("# injected heading", rendered)
        self.assertTrue(rendered.rstrip().endswith("````"))
