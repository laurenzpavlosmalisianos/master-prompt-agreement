"""Behavioral checks for shared operative-Markdown parsing."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.validation_test_support import REPO_ROOT

import check_reference_freshness  # noqa: E402
import conformance_check  # noqa: E402
import framework_consistency  # noqa: E402
import integration_registry  # noqa: E402
import link_check  # noqa: E402
import lint_reviewer_lane_feedback  # noqa: E402
import markdown_structure  # noqa: E402
import project_bootstrap  # noqa: E402
import project_contract_sync  # noqa: E402
import project_state_lint  # noqa: E402
import prompt_load_report  # noqa: E402
import source_chain_artifact_lint  # noqa: E402
import source_deep_research_lint  # noqa: E402
import source_registry_access_audit  # noqa: E402
import validate_framework  # noqa: E402


STRUCTURAL_TEXT = """## Live
live: yes
````text
## Hidden By Fence
hidden-fence: yes
```
## Hidden After Short Closer
~~~~
## Hidden After Mismatched Closer
````
<!--
## Hidden By Comment
hidden-comment: yes
-->
## Visible After Comment
visible-comment-close: yes
    ```text
## Visible After Overindented Pseudo-Fence
```bad`info
## Visible After Invalid Backtick Info
"""

VISIBLE_HEADINGS = [
    "Live",
    "Visible After Comment",
    "Visible After Overindented Pseudo-Fence",
    "Visible After Invalid Backtick Info",
]


class MarkdownStructureTests(unittest.TestCase):
    def test_shared_visibility_honors_fence_and_comment_boundaries(self) -> None:
        sections = markdown_structure.markdown_sections(STRUCTURAL_TEXT)
        operative = "\n".join(
            line for _line_number, line in markdown_structure.operative_lines(STRUCTURAL_TEXT)
        )

        self.assertEqual(VISIBLE_HEADINGS, [section.title for section in sections])
        self.assertNotIn("hidden-fence", operative)
        self.assertNotIn("hidden-comment", operative)
        self.assertIn("visible-comment-close", operative)

    def test_comment_masking_handles_inline_standalone_and_unterminated_comments(self) -> None:
        text = "\n".join(
            (
                "visible <!-- hidden-inline --> tail",
                "<!--",
                "## hidden-multiline",
                "-->",
                "## visible-after-standalone-close",
                "<!-- unterminated",
                "## hidden-after-unterminated-open",
            )
        )

        visible = list(markdown_structure.operative_lines(text))

        self.assertEqual("visible                        tail", visible[0][1])
        self.assertIn((5, "## visible-after-standalone-close"), visible)
        self.assertNotIn("hidden-multiline", "\n".join(line for _n, line in visible))
        self.assertNotIn(
            "hidden-after-unterminated-open",
            "\n".join(line for _n, line in visible),
        )

    def test_comment_masking_handles_multiple_short_literal_and_escaped_openers(self) -> None:
        text = "\n".join(
            (
                "<!-- closed --> <!--",
                "hidden-after-second-opener: yes",
                "-->",
                "<!-->",
                "visible-after-short-comment: yes",
                "<!--->",
                "visible-after-three-hyphen-comment: yes",
                "literal `<!--` remains visible",
                "visible-after-code-span: yes",
                r"escaped \<!-- remains visible",
                "visible-after-escape: yes",
            )
        )

        rendered = "\n".join(
            line for _line_number, line in markdown_structure.operative_lines(text)
        )

        self.assertNotIn("hidden-after-second-opener", rendered)
        self.assertIn("visible-after-short-comment", rendered)
        self.assertIn("visible-after-three-hyphen-comment", rendered)
        self.assertIn("visible-after-code-span", rendered)
        self.assertIn("visible-after-escape", rendered)

    def test_entrypoint_contract_cannot_be_borrowed_from_second_same_line_comment(self) -> None:
        output, rendered = project_bootstrap.render_entrypoint(
            "codex",
            "$FRAMEWORK",
            contract_root_ref=".mpa/contracts",
        )
        hidden = "<!-- closed --> <!--\n" + rendered + "\n-->\n"

        framework_ref, errors = integration_registry.entrypoint_authority_load_references(
            output,
            hidden,
            contract_root_ref=".mpa/contracts",
        )

        self.assertIsNone(framework_ref)
        self.assertTrue(
            any("framework core occurs 0 times" in error for error in errors),
            errors,
        )

    def test_section_consumers_share_visibility_and_exclude_body_decoys(self) -> None:
        expected = VISIBLE_HEADINGS
        self.assertEqual(
            expected,
            list(project_contract_sync.markdown_sections(STRUCTURAL_TEXT)),
        )
        self.assertEqual(
            expected,
            list(project_state_lint.markdown_h2_sections(STRUCTURAL_TEXT)),
        )
        self.assertEqual(
            expected,
            source_deep_research_lint.markdown_h2_sections(STRUCTURAL_TEXT)[0],
        )
        self.assertEqual(
            expected,
            list(conformance_check.markdown_h2_sections(STRUCTURAL_TEXT)),
        )
        self.assertNotIn(
            "hidden-fence",
            "\n".join(project_contract_sync.markdown_sections(STRUCTURAL_TEXT)["Live"]),
        )
        self.assertNotIn(
            "hidden-comment",
            "\n".join(project_state_lint.markdown_h2_sections(STRUCTURAL_TEXT)["Live"][0]),
        )

    def test_plain_and_line_consumers_ignore_fenced_and_commented_fields(self) -> None:
        plain = """Definitions
Live: yes
````text
Fenced: no
````
<!--
Commented: no
-->
"""
        parsed = project_contract_sync.plain_sections(plain, {"Definitions"})
        self.assertIn("Live: yes", parsed["Definitions"])
        self.assertNotIn("Fenced: no", parsed["Definitions"])
        self.assertNotIn("Commented: no", parsed["Definitions"])

        line_consumers = (
            lint_reviewer_lane_feedback.non_fenced_lines,
            source_registry_access_audit.non_fenced_lines,
        )
        for consumer in line_consumers:
            with self.subTest(consumer=consumer.__module__):
                rendered = "\n".join(line for _line_number, line in consumer(STRUCTURAL_TEXT))
                self.assertNotIn("hidden-fence", rendered)
                self.assertNotIn("hidden-comment", rendered)
                self.assertIn("visible-comment-close", rendered)

        validated = "\n".join(validate_framework.non_fenced_lines(STRUCTURAL_TEXT))
        state = "\n".join(
            project_state_lint.non_fenced_lines(Path("TODO.md"), STRUCTURAL_TEXT)
        )
        self.assertNotIn("hidden-fence", validated)
        self.assertNotIn("hidden-comment", state)

    def test_source_chain_blocks_cannot_borrow_fenced_or_commented_fields(self) -> None:
        text = """## Accepted Findings
finding_id: live
classification: accept-source-entry
````text
finding_id: fenced
classification: accept-source-entry
````
<!--
finding_id: commented
classification: accept-source-entry
-->
"""

        blocks, errors = source_chain_artifact_lint.decision_blocks_with_errors(
            text,
            require_section=True,
            section_only=True,
        )

        self.assertEqual([], errors)
        self.assertEqual(["live"], [block["finding_id"].value for block in blocks])

    def test_deep_research_retains_only_the_intentional_json_fence_payload(self) -> None:
        text = """## Prompt Digest
id: live
````text
id: fenced-decoy
````
## Verification Records
```json
[]
```
## Rejected or Deferred
None.
"""

        _headings, sections = source_deep_research_lint.markdown_h2_sections(text)

        self.assertNotIn("fenced-decoy", "\n".join(sections["Prompt Digest"]))
        self.assertEqual("```json\n[]\n```", "\n".join(sections["Verification Records"]))

    def test_link_consumer_uses_only_operative_markdown(self) -> None:
        text = """[visible](https://example.com/visible)
````text
[fenced](https://example.com/fenced)
````
<!-- [commented](https://example.com/commented) -->
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "links.md"
            path.write_text(text, encoding="utf-8")
            links = link_check.links_in_file(path)

        self.assertEqual([(1, "https://example.com/visible")], links)

    def test_entrypoint_and_prompt_module_parsers_keep_special_markers_explicit(self) -> None:
        lines = list(map(str, STRUCTURAL_TEXT.splitlines()))
        active = integration_registry._active_line_indexes(lines)
        active_text = "\n".join(lines[index] for index in sorted(active))
        self.assertNotIn("Hidden By Fence", active_text)
        self.assertNotIn("Hidden By Comment", active_text)
        self.assertIn("Visible After Invalid Backtick Info", active_text)

        label = sorted(prompt_load_report.KNOWN_PROJECT_MODULE_LABELS)[0]
        contract = "\n".join(
            (
                "## Active Project Modules",
                "````text",
                f"- {label}: fenced.md",
                "```",
                "````",
                "<!--",
                f"- {label}: commented.md",
                "-->",
                f"- {label}: live.md",
            )
        )
        modules, errors = prompt_load_report.active_project_modules(contract)
        self.assertEqual([], errors)
        self.assertEqual([{"label": label, "path": "live.md"}], modules)

    def test_source_update_tables_ignore_fenced_decoys_and_keep_source_lines(self) -> None:
        headers = check_reference_freshness.SOURCE_UPDATE_TABLE_HEADERS["Source Registry"]
        separator = tuple("---" for _header in headers)
        decoy = tuple("decoy" for _header in headers)
        live = tuple("live" for _header in headers)
        text = "\n".join(
            (
                "## Source Registry",
                "````text",
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join(separator) + " |",
                "| " + " | ".join(decoy) + " |",
                "````",
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join(separator) + " |",
                "| " + " | ".join(live) + " |",
            )
        )

        rows, errors = check_reference_freshness.source_update_table_rows(text)

        self.assertEqual([], errors)
        self.assertEqual(9, rows[0][0])
        self.assertEqual("live", rows[0][1]["source"])

        noncontiguous = "\n".join(
            (
                "## Source Registry",
                "| " + " | ".join(headers) + " |",
                "````text",
                "hidden",
                "````",
                "| " + " | ".join(separator) + " |",
                "| " + " | ".join(live) + " |",
            )
        )
        gap_rows, gap_errors = check_reference_freshness.source_update_table_rows(
            noncontiguous
        )
        self.assertEqual([], gap_rows)
        self.assertTrue(
            any("must be followed by a Markdown separator row" in error for _line, error in gap_errors),
            gap_errors,
        )

    def test_consistency_structures_ignore_fenced_and_commented_decoys(self) -> None:
        table = """````text
| Source | Disposition | Operative Home | Notes |
|---|---|---|---|
| hidden | retained | `hidden.md` | no |
````
| Source | Disposition | Operative Home | Notes |
|---|---|---|---|
| live | retained | `live.md` | yes |
"""
        self.assertEqual(
            ["live"],
            [row["source"] for row in framework_consistency.parse_human_clause_table(table)],
        )

        detached = table + """````text
fenced interruption
````
| detached | retained | `detached.md` | no |
"""
        self.assertEqual(
            ["live"],
            [
                row["source"]
                for row in framework_consistency.parse_human_clause_table(detached)
            ],
        )

        phases = framework_consistency.load_order_phase_blocks(
            "````\n1. `Hidden`\n````\n<!--\n2. `Commented`\n-->\n3. `Live`\n"
        )
        self.assertEqual(["Live"], list(phases))
        self.assertFalse(
            framework_consistency.conditional_state_line_is_bounded(
                "````\nLoad TODO.md only when needed.\n````\n",
                "TODO.md",
            )
        )
        self.assertTrue(
            framework_consistency.conditional_state_line_is_bounded(
                "Load TODO.md only when needed.\n",
                "TODO.md",
            )
        )

    def test_msa_inventory_and_script_index_ignore_fenced_decoys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "master_service_agreement.md").write_text(
                "````\nArticle 9 — Hidden\n9.1. Hidden\n````\n"
                "<!--\nArticle 8 — Commented\n8.1. Commented\n-->\n"
                "Article 1 — Live\n1.1. Live\n",
                encoding="utf-8",
            )
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "live.py").write_text("pass\n", encoding="utf-8")
            (scripts / "README.md").write_text(
                "````\n[live.py](live.py)\n````\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(framework_consistency, "REPO_ROOT", root),
                mock.patch.object(validate_framework, "REPO_ROOT", root),
            ):
                self.assertEqual(
                    ["Article 1", "1.1"],
                    framework_consistency.msa_clause_ids(),
                )
                self.assertEqual(
                    ["public script missing from scripts/README.md: scripts/live.py"],
                    validate_framework.script_index_errors(),
                )
                (scripts / "README.md").write_text(
                    "[live.py](live.py)\n",
                    encoding="utf-8",
                )
                self.assertEqual([], validate_framework.script_index_errors())


if __name__ == "__main__":
    unittest.main()
