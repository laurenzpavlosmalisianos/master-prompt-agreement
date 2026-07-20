"""Reference freshness and monitor-root governance tests."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.validation_test_support import SCRIPTS_DIR as _SCRIPTS_DIR

import check_reference_freshness  # noqa: E402
import url_safety  # noqa: E402


class ReferenceFreshnessTests(unittest.TestCase):
    def test_source_pack_metadata_scopes_entries_to_sources_section(self) -> None:
        template = (
            Path(__file__).resolve().parents[1]
            / "project_state_templates"
            / "SOURCE_PACKS.md"
        )

        issues = check_reference_freshness.source_pack_metadata_issues(
            template.parents[1],
            template,
            check_reference_freshness.date.fromisoformat("2026-07-13"),
            180,
        )

        self.assertEqual([], issues)

    def test_source_update_template_matches_closed_table_contract(self) -> None:
        template = (
            Path(__file__).resolve().parents[1]
            / "project_state_templates"
            / "SOURCE_UPDATE.md"
        )
        text = template.read_text(encoding="utf-8")

        rows, structural_errors = (
            check_reference_freshness.source_update_table_rows(text)
        )
        issues = check_reference_freshness.source_update_state_issues(
            template.parents[1],
            template,
            check_reference_freshness.date.fromisoformat("2026-07-13"),
            180,
            text=text,
        )

        self.assertEqual([], structural_errors)
        self.assertTrue(any("source" in row for _line, row in rows), rows)
        self.assertTrue(any("feed" in row for _line, row in rows), rows)
        self.assertEqual([], issues)

    def test_reference_freshness_fence_state_requires_matching_delimiter_and_length(self) -> None:
        lines = [
            "visible-before",
            "```text",
            "hidden-after-open",
            "~~~",
            "hidden-after-mismatched-close",
            "```",
            "visible-after-matched-close",
            "````text",
            "hidden-after-long-open",
            "```",
            "hidden-after-short-close",
            "`````",
            "visible-after-longer-close",
            "```bad`info",
            "visible-after-malformed-open",
            "    ```text",
            "visible-after-over-indented-open",
        ]

        stripped = dict(
            check_reference_freshness.strip_fenced_code("\n".join(lines))
        )

        for line_no in (2, 3, 4, 5, 6, 8, 9, 10, 11, 12):
            with self.subTest(line_no=line_no):
                self.assertEqual("", stripped[line_no])
        for line_no in (1, 7, 13, 14, 15, 16, 17):
            with self.subTest(line_no=line_no):
                self.assertEqual(lines[line_no - 1], stripped[line_no])

    def test_source_pack_fences_cannot_expose_or_hide_metadata(self) -> None:
        text = "\n".join(
            [
                "## Sources",
                "- [official-doc] Mismatched close",
                "  ```text",
                "  Evidence URL: https://hidden.example/mismatched",
                "  ~~~",
                "  Role: hidden mismatch",
                "  ```",
                "  Evidence URL: https://visible.example/mismatched",
                "- [official-doc] Short close",
                "  ````text",
                "  Evidence URL: https://hidden.example/short",
                "  ```",
                "  Role: hidden short",
                "  `````",
                "  Evidence URL: https://visible.example/short",
                "- [official-doc] Over-indented opener",
                "    ```text",
                "  Evidence URL: https://visible.example/over-indented",
                "- [official-doc] Malformed opener",
                "  ```bad`info",
                "  Evidence URL: https://visible.example/malformed",
            ]
        )

        blocks = check_reference_freshness.source_pack_entry_blocks(text)
        rendered = "\n".join(line for _line_no, lines in blocks for line in lines)

        self.assertEqual(4, len(blocks), blocks)
        self.assertNotIn("https://hidden.example/mismatched", rendered)
        self.assertNotIn("https://hidden.example/short", rendered)
        for suffix in ("mismatched", "short", "over-indented", "malformed"):
            with self.subTest(suffix=suffix):
                self.assertIn(f"https://visible.example/{suffix}", rendered)

    def test_reference_freshness_allows_date_placeholders_only_in_declared_state_blueprints(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        placeholder_message = "source-state placeholder date must be replaced before use"

        for name in ("SOURCE_PACKS.md", "SOURCE_UPDATE.md"):
            with self.subTest(name=name):
                template_path = repo_root / "project_state_templates" / name
                text = template_path.read_text(encoding="utf-8")

                template_issues = check_reference_freshness.source_claim_issues(
                    repo_root,
                    template_path,
                    reference_file=False,
                    text=text,
                )
                live_issues = check_reference_freshness.source_claim_issues(
                    repo_root,
                    repo_root / name,
                    reference_file=False,
                    text=text,
                )
                undeclared_template_issues = check_reference_freshness.source_claim_issues(
                    repo_root,
                    repo_root / "project_state_templates" / f"UNDECLARED_{name}",
                    reference_file=False,
                    text=text,
                )

                self.assertNotIn(
                    placeholder_message,
                    [issue.message for issue in template_issues],
                )
                self.assertIn(
                    placeholder_message,
                    [issue.message for issue in live_issues],
                )
                self.assertIn(
                    placeholder_message,
                    [issue.message for issue in undeclared_template_issues],
                )

    def test_reference_freshness_flags_latest_claims_without_claim_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example latest release",
                        "  https://example.com/releases",
                        "  Use as evidence that Example 3.2 is the latest release.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        self.assertIn(
            "concrete external source-state claim lacks an ISO date in the same block",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_ignores_internal_clause_numbers_in_public_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            doc = root / "master_service_agreement.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Agreement",
                        "",
                        "3.2.2. Reviewer agreement is not verification: material factual claims must be checked against governing text before they can support the vote ledger. The current User may request more evidence.",
                        "11.7.5. Deterministic scripts are authoritative only for declared invariants. Run them with no network by default and logged inputs.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                True,
            )

        self.assertEqual([], issues)

    def test_reference_freshness_public_doc_scan_uses_declared_public_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for rel in ("SECURITY.md", "GOVERNANCE.md", "SPECIFICATION.md", "CONFORMANCE.md", "examples/demo.md"):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Public Surface\n", encoding="utf-8")

            paths = check_reference_freshness.iter_public_markdown_files(
                root,
                include_non_reference_docs=True,
                reference_dirs=(),
            )
            rels = {path.relative_to(root).as_posix() for path in paths}

        self.assertIn("SECURITY.md", rels)
        self.assertIn("GOVERNANCE.md", rels)
        self.assertIn("SPECIFICATION.md", rels)
        self.assertIn("CONFORMANCE.md", rels)
        self.assertIn("examples/demo.md", rels)

    def test_reference_freshness_does_not_count_dated_url_as_claim_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example latest release",
                        "  https://example.com/releases/2026-06-12",
                        "  Use as evidence that Example 3.2 is the latest release.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        self.assertIn(
            "concrete external source-state claim lacks an ISO date in the same block",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_rejects_never_checked_source_update_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "SOURCE_UPDATE.md").write_text(
                "\n".join(
                    [
                        "# Source Update Plan",
                        "",
                        "| Surface | Source | Kind | Tier | Scope | Volatility | Check Method | Access Policy | Monitoring Mode | Cadence | Last Checked | Allowed Use | Action Rule |",
                        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                        "| Python | https://docs.python.org/3/ | official docs | [official-doc] | current | version-sensitive | direct GET | robots/terms checked on 2026-06-12 | one_off | weekly | never | normative after verification | review before version claims |",
                        "",
                        "| Surface | Feed | Tier | Scope | Check Method | Access Policy | Conditional State | Dedupe Key | Last Checked | Last Seen | Allowed Use | Triage Rule | Output |",
                        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                        "| Security | https://example.com/security/feed.xml | [vendor-doc] | advisories | RSS | robots/terms checked on 2026-06-12 | ETag | GUID | 2026-06-12 | never | source discovery only | verify primary source | TODO |",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        messages = [issue.message for issue in issues]
        self.assertIn("Last Checked is never; check or remove the source row", messages)
        self.assertIn("Last Seen is never; check or remove the source row", messages)

    def test_reference_freshness_rejects_non_iso_checked_dates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "SOURCE_UPDATE.md").write_text(
                "\n".join(
                    [
                        "# Source Update Plan",
                        "",
                        "| Surface | Source | Kind | Tier | Scope | Volatility | Check Method | Access Policy | Monitoring Mode | Cadence | Last Checked | Allowed Use | Action Rule |",
                        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                        "| Python | https://docs.python.org/3/ | official docs | [official-doc] | current | version-sensitive | direct GET | robots/terms checked on 2026-06-12 | manual | weekly | last week | normative after verification | review before version claims |",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        self.assertIn(
            "Last Checked must be an ISO date, not 'last week'",
            [issue.message for issue in issues],
        )
        self.assertIn(
            "source update Monitoring Mode must be one of: one_off, recurring",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_requires_source_update_url_unless_local(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "SOURCE_UPDATE.md").write_text(
                "\n".join(
                    [
                        "# Source Update Plan",
                        "",
                        "| Surface | Source | Kind | Tier | Scope | Volatility | Check Method | Access Policy | Monitoring Mode | Cadence | Last Checked | Allowed Use | Action Rule |",
                        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                        "| Python | Python docs | official docs | [official-doc] | current | version-sensitive | direct GET | robots/terms checked on 2026-06-12 | one_off | weekly | 2026-06-12 | normative after verification | review before version claims |",
                        "| Local | User pasted source | local | [case-study] | fixed | stable | manual | approved local source | one_off | one-off | 2026-06-12 | evidence-only | review |",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        self.assertEqual(
            ["source update row Source or Feed must contain an https URL"],
            [issue.message for issue in issues if "Source or Feed" in issue.message],
        )

    def test_reference_freshness_rejects_source_update_semantic_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "SOURCE_UPDATE.md").write_text(
                "\n".join(
                    [
                        "# Source Update Plan",
                        "",
                        "| Surface | Source | Kind | Tier | Scope | Volatility | Check Method | Access Policy | Monitoring Mode | Cadence | Last Checked | Allowed Use | Action Rule |",
                        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                        "| Security | https://agency.example/advisories/bulletin-26-04 | advisory | [official-doc] | current | high-volatility | direct GET | [policy] | recurring | weekly | 2026-06-12 | evidence-only | review |",
                        "",
                        "| Surface | Feed | Tier | Scope | Check Method | Access Policy | Conditional State | Dedupe Key | Last Checked | Last Seen | Allowed Use | Triage Rule | Output |",
                        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                        "| News | https://example.com/ | [vendor-doc] | updates | RSS | blocked | ETag | GUID | 2026-06-12 | feed-guid-123 | source discovery only | verify | report |",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        messages = [issue.message for issue in issues]
        self.assertIn("Access Policy must be explicit before use", messages)
        self.assertIn(
            "recurring source update row must use a durable parent root or feed",
            messages,
        )
        self.assertIn("blocked Access Policy belongs in open gaps, not a populated source row", messages)
        self.assertIn("source update row must use a specific durable parent surface, not a whole-domain URL", messages)

    def test_reference_freshness_requires_source_pack_version_and_access_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "SOURCE_PACKS.md").write_text(
                "\n".join(
                    [
                        "# Source Packs",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- [official-doc] Python documentation",
                        "  Evidence URL: https://docs.python.org/3/",
                        "  Scope: Python version behavior.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        messages = [issue.message for issue in issues]
        self.assertIn("source-pack entry missing Version Anchor", messages)
        self.assertIn("source-pack entry missing Access Policy", messages)
        self.assertIn("source-pack entry missing Role", messages)
        self.assertIn("source-pack entry missing Allowed Use", messages)
        self.assertIn("source-pack entry missing Last Checked", messages)

    def test_reference_freshness_validates_source_pack_role_and_allowed_use(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "SOURCE_PACKS.md").write_text(
                "\n".join(
                    [
                        "# Source Packs",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- [official-doc] Python documentation",
                        "  Evidence URL: https://docs.python.org/3/",
                        "  Role: interesting idea",
                        "  Allowed Use: adopt whatever it says",
                        "  Version Anchor: current documentation root checked 2026-06-12",
                        "  Access Policy: robots/terms checked on 2026-06-12",
                        "  Last Checked: 2026-06-12",
                        "",
                        "- [commentary] Example commentary",
                        "  Evidence URL: https://example.com/commentary/item",
                        "  Role: discovery filter",
                        "  Allowed Use: normative after verification",
                        "  Version Anchor: evidence-only",
                        "  Access Policy: robots/terms checked on 2026-06-12",
                        "  Last Checked: 2026-06-12",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        messages = [issue.message for issue in issues]
        self.assertTrue(any(message.startswith("source-pack Role must be one of") for message in messages))
        self.assertTrue(any(message.startswith("source-pack Allowed Use must be one of") for message in messages))
        self.assertIn(
            "commentary source-pack Allowed Use must be one of: source discovery only",
            messages,
        )

    def test_reference_freshness_enforces_lower_tier_source_update_allowed_use(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "SOURCE_UPDATE.md").write_text(
                "\n".join(
                    [
                        "# Source Update Plan",
                        "",
                        "| Surface | Source | Kind | Tier | Scope | Volatility | Check Method | Access Policy | Monitoring Mode | Cadence | Last Checked | Allowed Use | Action Rule |",
                        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                        "| Agent loops | https://example.com/blog/ | blog | [commentary] | current | high-volatility | RSS | robots/terms checked on 2026-06-12 | recurring | weekly | 2026-06-12 | normative after verification | do not adopt without review |",
                        "| Security case | https://example.com/security/ | case studies | [case-study] | current | incident-triggered | direct GET | robots/terms checked on 2026-06-12 | recurring | weekly | 2026-06-12 | evidence-only | review candidate evidence |",
                        "| Security case bad | https://example.com/security/bad | case studies | [case-study] | current | incident-triggered | direct GET | robots/terms checked on 2026-06-12 | one_off | weekly | 2026-06-12 | source discovery only | review candidate evidence |",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        messages = [issue.message for issue in issues]
        self.assertIn(
            "commentary source update row Allowed Use must be one of: source discovery only",
            messages,
        )
        self.assertNotIn(
            "case-study source update row missing explicit Allowed Use",
            messages,
        )
        self.assertIn(
            "case-study source update row Allowed Use must be one of: evidence-only",
            messages,
        )

    def test_reference_freshness_does_not_skip_populated_bracketed_source_rows(self) -> None:
        text = "\n".join(
            [
                "| Surface | Source | Kind | Tier | Scope | Volatility | Check Method | Access Policy | Monitoring Mode | Cadence | Last Checked | Allowed Use | Action Rule |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                "| [prod] security | http://localhost/private | advisory | [unknown] | current | high-volatility | direct | invalid | sometimes | weekly | not-a-date | adopt | review |",
            ]
        )

        issues = check_reference_freshness.source_update_state_issues(
            Path("."),
            Path("SOURCE_UPDATE.md"),
            check_reference_freshness.date.fromisoformat("2026-07-13"),
            180,
            text=text,
        )
        messages = [issue.message for issue in issues]

        self.assertIn(
            "source update Monitoring Mode must be one of: one_off, recurring",
            messages,
        )
        self.assertIn(
            "Access Policy must be robots/terms checked on YYYY-MM-DD, not applicable, user-supplied, or approved local source",
            messages,
        )
        self.assertIn(
            "source update row Tier must be an allowed bracketed source tier",
            messages,
        )
        self.assertIn("external source URL must use https", messages)

    def test_reference_freshness_rejects_ambiguous_source_update_table_structure(self) -> None:
        header = (
            "| Surface | Source | Kind | Tier | Scope | Volatility | Check Method | "
            "Access Policy | Monitoring Mode | Cadence | Last Checked | Allowed Use | "
            "Action Rule |"
        )
        separator = "|---|---|---|---|---|---|---|---|---|---|---|---|---|"
        valid_row = (
            "| Runtime | https://example.com/releases | docs | [official-doc] | current | "
            "high-volatility | direct | not applicable | recurring | weekly | 2026-07-13 | "
            "normative after verification | review |"
        )
        cases = (
            (
                "duplicate-header",
                header.replace(
                    "| Access Policy | Monitoring Mode |",
                    "| Access Policy | Access Policy | Monitoring Mode |",
                ),
                separator + "---|",
                valid_row.replace(
                    "| not applicable | recurring |",
                    "| blocked | not applicable | recurring |",
                ),
                "SOURCE_UPDATE Source Registry header repeats column(s): access policy",
            ),
            (
                "unknown-and-missing-header",
                header.replace("| Action Rule |", "| Unowned State |"),
                separator,
                valid_row,
                "SOURCE_UPDATE Source Registry header has unknown column(s): Unowned State",
            ),
            (
                "row-width-mismatch",
                header,
                separator,
                valid_row.replace(" | review |", " |"),
                "SOURCE_UPDATE Source Registry row has 12 cells; expected 13",
            ),
        )

        for case_id, case_header, case_separator, row, expected in cases:
            with self.subTest(case_id=case_id):
                text = "\n".join(
                    [
                        "# Source Update",
                        "",
                        "## Source Registry",
                        "",
                        case_header,
                        case_separator,
                        row,
                    ]
                )
                issues = check_reference_freshness.source_update_state_issues(
                    Path("."),
                    Path("SOURCE_UPDATE.md"),
                    check_reference_freshness.date.fromisoformat("2026-07-13"),
                    180,
                    text=text,
                )
                messages = [issue.message for issue in issues]
                self.assertIn(expected, messages)

    def test_reference_freshness_separates_checked_dates_from_feed_cursors(self) -> None:
        text = "\n".join(
            [
                "| Surface | Source | Kind | Tier | Scope | Volatility | Check Method | Access Policy | Monitoring Mode | Cadence | Last Checked | Allowed Use | Action Rule |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                "| Runtime | https://example.com/releases | releases | [official-doc] | current | high-volatility | direct | not applicable | recurring | release-triggered | not applicable | normative after verification | review |",
                "",
                "| Surface | Feed | Tier | Scope | Check Method | Access Policy | Conditional State | Dedupe Key | Last Checked | Last Seen | Allowed Use | Triage Rule | Output |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                "| Runtime | https://example.com/feed.xml | [official-doc] | current | RSS | not applicable | ETag | GUID | 2026-07-13 | feed-guid-123 | source discovery only | verify | report |",
            ]
        )

        issues = check_reference_freshness.source_update_state_issues(
            Path("."),
            Path("SOURCE_UPDATE.md"),
            check_reference_freshness.date.fromisoformat("2026-07-13"),
            180,
            text=text,
        )
        messages = [issue.message for issue in issues]

        self.assertIn(
            "Last Checked must be an ISO date, not 'not applicable'",
            messages,
        )
        self.assertFalse(any("feed-guid-123" in message for message in messages), messages)

    def test_reference_freshness_rejects_unsafe_or_undated_source_pack_evidence(self) -> None:
        text = "\n".join(
            [
                "# Source Packs",
                "",
                "## Sources",
                "",
                "- [official-doc] Example source",
                "  Evidence URL: http://localhost/private",
                "  Role: evidence URL",
                "  Allowed Use: normative after verification",
                "  Version Anchor: current",
                "  Access Policy: not applicable",
                "  Last Checked: not applicable",
            ]
        )

        issues = check_reference_freshness.source_pack_metadata_issues(
            Path("."),
            Path("SOURCE_PACKS.md"),
            check_reference_freshness.date.fromisoformat("2026-07-13"),
            180,
            text=text,
        )
        messages = [issue.message for issue in issues]

        self.assertIn(
            "Last Checked must be an ISO date, not 'not applicable'",
            messages,
        )
        self.assertIn(
            "source-pack Evidence URL external source URL must use https",
            messages,
        )

    def test_reference_freshness_rejects_duplicate_source_pack_authority_fields(self) -> None:
        text = "\n".join(
            [
                "# Source Packs",
                "",
                "## Sources",
                "",
                "- [official-doc] Example source",
                "  Evidence URL: https://example.com/docs/item",
                "  Role: evidence URL",
                "  Role: discovery filter",
                "  Allowed Use: normative after verification",
                "  Allowed Use: prohibited",
                "  Version Anchor: current",
                "  Access Policy: not applicable",
                "  Last Checked: 2026-07-13",
            ]
        )

        issues = check_reference_freshness.source_pack_metadata_issues(
            Path("."),
            Path("SOURCE_PACKS.md"),
            check_reference_freshness.date.fromisoformat("2026-07-13"),
            180,
            text=text,
        )
        messages = [issue.message for issue in issues]

        self.assertIn(
            "source-pack Role must appear exactly once per entry",
            messages,
        )
        self.assertIn(
            "source-pack Allowed Use must appear exactly once per entry",
            messages,
        )

    def test_reference_freshness_rejects_source_pack_entries_without_tier_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "SOURCE_PACKS.md").write_text(
                "\n".join(
                    [
                        "# Source Packs",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Python documentation",
                        "  Evidence URL: https://docs.python.org/3/",
                        "  Version Anchor: current documentation root checked 2026-06-12",
                        "  Access Policy: robots/terms checked on 2026-06-12",
                        "  Last Checked: 2026-06-12",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        self.assertIn("source-pack entry missing tier prefix", [issue.message for issue in issues])

    def test_reference_freshness_rejects_unsafe_source_urls(self) -> None:
        cases = {
            "http://example.com/releases": "external source URL must use https",
            "https://localhost/releases": "external URL points to localhost",
            "https://169.254.169.254/latest/meta-data": "external URL points to non-public address",
            "https://user:" + "token@example.com/releases": "external URL must not contain credentials",
            "https://example.com:abc/releases": "malformed external URL",
        }
        for url, expected in cases.items():
            with self.subTest(url=url), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                refs = root / "private" / "references"
                refs.mkdir(parents=True)
                doc = refs / "sources.md"
                doc.write_text(
                    "\n".join(
                        [
                            "# Sources",
                            "",
                            "Reviewed: 2026-06-12",
                            "",
                            "## Sources",
                            "",
                            "- Example source",
                            f"  {url}",
                            "  Reviewed on 2026-06-12.",
                        ]
                    ),
                    encoding="utf-8",
                )

                issues = check_reference_freshness.collect_issues(
                    root,
                    check_reference_freshness.date.fromisoformat("2026-06-12"),
                    180,
                    False,
                )

            self.assertTrue(any(expected in issue.message for issue in issues), [issue.message for issue in issues])

    def test_reference_freshness_treats_commit_hashes_as_source_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example implementation",
                        "  https://example.com/repo",
                        "  Use current implementation evidence from commit `1a7bf02`.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        self.assertIn(
            "concrete external source-state claim lacks an ISO date in the same block",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_rejects_invalid_claim_dates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example implementation",
                        "  https://example.com/repo",
                        "  Checked on 2026-99-99: Example 3.2 is the latest release.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        self.assertIn(
            "invalid ISO date in source-state claim: '2026-99-99'",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_rejects_unqualified_prerelease_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example stable source",
                        "  https://example.com/spec/v1.2-beta/",
                        "  Use for stable build guidance.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        self.assertIn(
            "pre-release, preview, draft, alpha, beta, or rc source needs an explicit stability qualifier",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_does_not_treat_general_preview_policy_as_source_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            guide = root / "practice_guides" / "review.md"
            guide.parent.mkdir(parents=True)
            guide.write_text(
                "Prefer an existing preview artifact when available; treat a draft as non-final.\n",
                encoding="utf-8",
            )

            issues = check_reference_freshness.source_claim_issues(
                root,
                guide,
                reference_file=False,
            )

        self.assertNotIn(
            "pre-release, preview, draft, alpha, beta, or rc source needs an explicit stability qualifier",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_rejects_parent_roots_inside_case_study_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Security Engineering Case Studies",
                        "",
                        "- [case-study] Example incident",
                        "  https://example.com/blog/",
                        "  https://example.com/blog/example-incident",
                        "  Use as case-study evidence, not doctrine, checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        self.assertIn(
            "case-study entry contains a broad source root as evidence URL; split the parent root into a separate entry or Monitor root line",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_does_not_reject_case_study_monitor_root_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Security Engineering Case Studies",
                        "",
                        "- Example blog source root",
                        "  https://example.com/blog/",
                        "  Use as the bounded parent source root checked on 2026-06-12.",
                        "",
                        "- [case-study] Example incident",
                        "  https://example.com/blog/example-incident",
                        "  Monitor root: Example blog source root above.",
                        "  Use as case-study evidence, not doctrine, checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertNotIn(
            "case-study entry contains a broad source root as evidence URL; split the parent root into a separate entry or Monitor root line",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_does_not_flag_dated_latest_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example latest release",
                        "  https://example.com/releases",
                        "  Use as evidence that Example 3.2 is the latest release; checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        self.assertEqual([], [issue for issue in issues if issue.severity == "error"])

    def test_reference_freshness_monitor_root_audit_does_not_flag_reference_only_exact_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example release post",
                        "  https://example.com/releases/v_01",
                        "  Use as release evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertEqual([], issues)

    def test_reference_freshness_monitor_root_audit_does_not_flag_parent_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example release post",
                        "  https://example.com/releases/",
                        "  https://example.com/releases/v_01",
                        "  Use as release evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertNotIn(
            "Monitor root must be a durable discovery root, not an exact/static source URL",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_does_not_flag_canonical_exact_root_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example canonical changelog endpoint",
                        "  Evidence URL: https://example.com/releases/v_01",
                        "  Monitor root: https://example.com/releases/v_01",
                        "  Monitor host relation: evidence_host",
                        "  Monitor root class: canonical_exact_root",
                        "  Canonical exact root reason: this changelog endpoint is the only update surface for this component.",
                        "  Freshness mechanism kind: http_validator",
                        "  Source authority: publisher-owned release endpoint.",
                        "  Revalidation interval days: 7",
                        "  Replacement discovery mode: alternate_url",
                        "  Replacement discovery reference: https://example.com/changelog/",
                        "  Use as release evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertEqual([], [issue for issue in issues if issue.severity == "error"])

    def test_reference_freshness_monitor_root_audit_rejects_retired_canonical_exact_root_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example exact root",
                        "  Evidence URL: https://example.com/releases/v_01",
                        "  Monitor root: https://example.com/releases/",
                        "  Monitor host relation: evidence_host",
                        "  Monitor root class: canonical_exact_root",
                        "  Canonical exact root reason: retained prose does not certify freshness.",
                        "  Freshness mechanism: ETag comparison.",
                        "  Source authority: publisher-owned release endpoint.",
                        "  Revalidation interval: weekly.",
                        "  Replacement discovery fallback: search the publisher site.",
                        "  Use as release evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertTrue(
            any("retired canonical-exact-root field is not allowed: Freshness mechanism" in issue.message for issue in issues),
            [issue.message for issue in issues],
        )
        self.assertIn(
            "canonical_exact_root requires Freshness mechanism kind",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_rejects_latest_path_without_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example latest page",
                        "  Evidence URL: https://example.com/blog/new-agent-post",
                        "  Monitor root: https://example.com/latest",
                        "  Monitor host relation: evidence_host",
                        "  Use as release evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertIn(
            "Monitor root must be a durable discovery root, not an exact/static source URL",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_does_not_flag_topic_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example topic page",
                        "  Evidence URL: https://example.com/blog/new-agent-post",
                        "  Monitor root: https://example.com/topics/tree",
                        "  Monitor host relation: evidence_host",
                        "  Use as topic evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertEqual([], [issue for issue in issues if issue.severity == "error"])

    def test_reference_freshness_monitor_root_audit_does_not_flag_search_label_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example category feed",
                        "  Evidence URL: https://example.com/search/label/Security",
                        "  Monitor root: https://example.com/search/label/Security",
                        "  Monitor host relation: evidence_host",
                        "  Use as a category discovery root checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertNotIn(
            "Monitor root must be a durable discovery root, not an exact/static source URL",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_rejects_product_specific_root_without_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-24",
                        "",
                        "## Sources",
                        "",
                        "- Example legal record",
                        "  https://records.example/legal/2024/1689",
                        "  Monitor root: https://records.example/official/direct-access.html",
                        "  Monitor host relation: evidence_host",
                        "  Use as official legal evidence checked on 2026-06-24.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-24"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertIn(
            "Monitor root must be a durable discovery root, not an exact/static source URL",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_does_not_flag_section_parent_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example releases",
                        "  https://example.com/releases/",
                        "  Use as the release-monitor root.",
                        "",
                        "- Example release post",
                        "  https://example.com/releases/v_01",
                        "  Use as release evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertNotIn(
            "Monitor root must be a durable discovery root, not an exact/static source URL",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_does_not_flag_reference_only_without_section_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## A",
                        "",
                        "- Example releases",
                        "  https://example.com/releases/",
                        "  Use as the release-monitor root for A.",
                        "",
                        "## B",
                        "",
                        "- Example release post",
                        "  https://example.com/releases/v_01",
                        "  Use as release evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertNotIn(
            "Monitor root must be a durable discovery root, not an exact/static source URL",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_treats_parent_url_as_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example blog root and post",
                        "  https://example.com/blog/",
                        "  https://example.com/blog/post-1",
                        "  Use the first URL as the monitor root and the second as evidence.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertNotIn(
            "Monitor root must be a durable discovery root, not an exact/static source URL",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_rejects_obsolete_reference_only_marker(self) -> None:
        obsolete_marker = "none" + "-one-off"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example release post",
                        "  https://example.com/releases/v_01",
                        f"  Monitor root: {obsolete_marker}.",
                        "  Use as release evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertIn(
            "omit Monitor root for reference-only entries instead of using a synthetic placeholder",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_rejects_exact_monitor_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example release post",
                        "  https://example.com/releases/v_01",
                        "  Monitor root: https://example.com/releases/v_01",
                        "  Monitor host relation: evidence_host",
                        "  Use as release evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertIn(
            "Monitor root must be a durable discovery root, not an exact/static source URL",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_rejects_prose_only_cross_host_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example security feed",
                        "  https://example.com/news/",
                        "  Monitor root: https://third-party.example.net/feed/",
                        "  Monitor host relation: evidence_host",
                        "  Acquisition boundary approval: approved third-party monitor-root endpoint for this source.",
                        "  Use as source discovery or hypothesis generation checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertIn(
            "evidence_host Monitor root must match an entry evidence host",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_does_not_infer_subdomain_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example docs",
                        "  https://developers.example.com/docs/post-1",
                        "  Monitor root: https://example.com/docs/",
                        "  Monitor host relation: evidence_host",
                        "  Use as official docs evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertIn(
            "evidence_host Monitor root must match an entry evidence host",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_host_match_uses_exact_hostname_without_port(self) -> None:
        self.assertTrue(
            check_reference_freshness.host_matches_evidence_host(
                "https://docs.example.com:443/releases",
                "https://docs.example.com/item",
            )
        )
        self.assertFalse(
            check_reference_freshness.host_matches_evidence_host(
                "https://unrelated.example-host.test/releases",
                "https://example-host.test/item",
            )
        )

    def test_reference_freshness_monitor_root_audit_accepts_structured_cross_host_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "DECISIONS.md").write_text(
                "\n".join(
                    [
                        "# Decisions",
                        "",
                        "- 2026-06-12, directive_id: APPROVAL-CROSS-HOST-001",
                        "  Status: active",
                        "  Directive: Permit the named cross-host monitor root.",
                        "  Authority source: User approval",
                        "  Scope: The named source-registry entry",
                        "  Expiry or review trigger: Monitor-root change",
                        "  Affected files or surfaces: SOURCE_PACKS.md",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example approved external feed",
                        "  https://example.com/news/",
                        "  Monitor root: https://third-party.example.net/feed/",
                        "  Monitor host relation: approved_cross_host",
                        "  Approval reference: DECISIONS.md#APPROVAL-CROSS-HOST-001",
                        "  Use as source discovery or hypothesis generation checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertNotIn(
            "evidence_host Monitor root must match an entry evidence host",
            [issue.message for issue in issues],
        )
        self.assertFalse(
            any("Approval reference" in issue.message for issue in issues),
            issues,
        )

    def test_reference_freshness_approval_anchor_requires_exact_active_record(self) -> None:
        anchor = "APPROVAL-CROSS-HOST-001"
        exact_record = "\n".join(
            [
                "# Decisions",
                "",
                f"- 2026-06-12, directive_id: {anchor}",
                "  Status: active",
                "  Directive: Permit the named cross-host monitor root.",
                "    This continuation preserves the bounded rationale.",
                "    - Nested evidence remains part of the directive field.",
                "",
                "## Later material",
                "  Status: revoked",
            ]
        )
        missing_status = "\n".join(
            [
                f"- 2026-06-12, directive_id: {anchor}",
                "  Directive: Missing its own status.",
            ]
        )
        valid_records = {
            "multiline record": exact_record,
            "four-space status field": "\n".join(
                [
                    missing_status,
                    "    Status: active",
                    "    Directive: Four-space canonical field indentation.",
                ]
            ),
            "same-length fence close": "\n".join(
                [
                    missing_status,
                    "  ```text",
                    "  ignored example",
                    "  ```",
                    "  Status: active",
                ]
            ),
            "longer fence close": "\n".join(
                [
                    missing_status,
                    "  ```text",
                    "  ignored example",
                    "  ````",
                    "  Status: active",
                ]
            ),
            "over-indented pseudo-fence": "\n".join(
                [
                    missing_status,
                    "    ```text",
                    "  Status: active",
                    "    ```",
                ]
            ),
        }
        invalid_records = {
            "prefixed identity": exact_record.replace(anchor, f"PREFIX-{anchor}"),
            "suffixed identity": exact_record.replace(anchor, f"{anchor}-SUFFIX"),
            "prose mention": f"# Decisions\n\nApproval granted for {anchor}.\n",
            "revoked identity": exact_record.replace(
                "  Status: active",
                "  Status: revoked",
            ),
            "duplicate status fields": "\n".join(
                [
                    missing_status,
                    "  Status: active",
                    "  Status: active",
                ]
            ),
            "duplicate matching records": "\n".join(
                [
                    f"- 2026-06-12, directive_id: {anchor}",
                    "  Status: active",
                    f"- 2026-06-13, decision_id: {anchor}",
                    "  Status: active",
                ]
            ),
            "later heading status": "\n".join(
                [
                    missing_status,
                    "",
                    "## Unrelated active state",
                    "  Status: active",
                ]
            ),
            "one-space heading status": "\n".join(
                [
                    missing_status,
                    " # Unrelated active state",
                    "  Status: active",
                ]
            ),
            "fenced status": "\n".join(
                [
                    missing_status,
                    "  ```text",
                    "  Status: active",
                    "  ```",
                ]
            ),
            "mismatched fence close": "\n".join(
                [
                    missing_status,
                    "  ```text",
                    "  ~~~",
                    "  Status: active",
                    "  ```",
                ]
            ),
            "short fence close": "\n".join(
                [
                    missing_status,
                    "  ````text",
                    "  ```",
                    "  Status: active",
                    "  ````",
                ]
            ),
            "unindented fence close": "\n".join(
                [
                    missing_status,
                    "  ```text",
                    "  ignored example",
                    "```",
                    "  Status: active",
                ]
            ),
            "prose status": "\n".join(
                [
                    missing_status,
                    "  This prose says Status: active but is not a field.",
                ]
            ),
            "status before record": "\n".join(
                [
                    "  Status: active",
                    missing_status,
                ]
            ),
        }
        source_registry = "\n".join(
            [
                "- Example approved external feed",
                "  Evidence URL: https://example.com/news/item",
                "  Monitor root: https://third-party.example.net/feed/",
                "  Monitor host relation: approved_cross_host",
                f"  Approval reference: DECISIONS.md#{anchor}",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            authority_path = root / "DECISIONS.md"
            for name, record in valid_records.items():
                with self.subTest(name=name):
                    authority_path.write_text(record, encoding="utf-8")
                    exact_issues = check_reference_freshness.monitor_root_issues(
                        root,
                        root / "SOURCE_PACKS.md",
                        source_registry,
                    )
                    self.assertFalse(
                        any(
                            "Approval reference" in issue.message
                            for issue in exact_issues
                        ),
                        exact_issues,
                    )

            for name, record in invalid_records.items():
                with self.subTest(name=name):
                    authority_path.write_text(record, encoding="utf-8")
                    issues = check_reference_freshness.monitor_root_issues(
                        root,
                        root / "SOURCE_PACKS.md",
                        source_registry,
                    )
                    self.assertTrue(
                        any(
                            "Approval reference anchor" in issue.message
                            for issue in issues
                        ),
                        issues,
                    )

    def test_reference_freshness_monitor_host_relation_rejects_missing_and_self_approval(self) -> None:
        missing_relation = "\n".join(
            [
                "- Example feed",
                "  https://example.com/news/item",
                "  Monitor root: https://example.com/news/",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            doc = root / "sources.md"
            missing_issues = check_reference_freshness.monitor_root_issues(
                root,
                doc,
                missing_relation,
            )
            self.assertIn(
                "Monitor root requires Monitor host relation",
                [issue.message for issue in missing_issues],
            )
            doc.write_text(
                "\n".join(
                    [
                        "Reviewed: 2026-06-12",
                        "- Example feed",
                        "  https://example.com/news/item",
                        "  Monitor root: https://external.example.net/feed/",
                        "  Monitor host relation: approved_cross_host",
                        "  Approval reference: sources.md#APPROVAL-SELF-001",
                        "  APPROVAL-SELF-001",
                    ]
                ),
                encoding="utf-8",
            )
            self_approval_issues = check_reference_freshness.monitor_root_issues(root, doc)

        self.assertIn(
            "Approval reference must resolve to a separate authority record, not the source registry itself",
            [issue.message for issue in self_approval_issues],
        )

    def test_reference_freshness_monitor_root_audit_rejects_repository_tree_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example implementation",
                        "  https://code.example/team/project",
                        "  Evidence URL: https://code.example/team/project/tree/main/releases",
                        "  Monitor root: https://code.example/team/project/tree/main/releases",
                        "  Monitor host relation: evidence_host",
                        "  Use as implementation evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertIn(
            "Monitor root must be a durable discovery root, not an exact/static source URL",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_rejects_text_only_monitor_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example implementation",
                        "  https://example.com/blog/post-1",
                        "  Monitor root: Example source roots above.",
                        "  Use as implementation evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertIn(
            "Monitor root must include an https URL; omit the line for reference-only entries",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_does_not_flag_declared_repository_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example implementation",
                        "  https://code.example/team/project",
                        "  Evidence URL: https://code.example/team/project/tree/main/releases",
                        "  Monitor root: https://code.example/team/project",
                        "  Monitor host relation: evidence_host",
                        "  Monitor root class: canonical_exact_root",
                        "  Canonical exact root reason: the publisher-owned repository home is the bounded implementation update surface.",
                        "  Freshness mechanism kind: revision_identifier",
                        "  Source authority: publisher-owned implementation repository.",
                        "  Revalidation interval days: 30",
                        "  Replacement discovery mode: alternate_url",
                        "  Replacement discovery reference: https://docs.example.com/releases/",
                        "  Use as implementation evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertNotIn(
            "Monitor root must be a durable discovery root, not an exact/static source URL",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_binds_canonical_metadata_to_one_exact_root(self) -> None:
        text = "\n".join(
            [
                "- Example implementations",
                "  https://code.example/team/first",
                "  https://code.example/team/second",
                "  Monitor root: https://code.example/team/first",
                "  Monitor root: https://code.example/team/second",
                "  Monitor host relation: evidence_host",
                "  Monitor root class: canonical_exact_root",
                "  Canonical exact root reason: the first endpoint is the bounded update surface.",
                "  Freshness mechanism kind: revision_identifier",
                "  Source authority: publisher-owned implementation repository.",
                "  Revalidation interval days: 30",
                "  Replacement discovery mode: alternate_url",
                "  Replacement discovery reference: https://code.example/team/releases",
            ]
        )

        issues = check_reference_freshness.monitor_root_issues(
            Path("."),
            Path("sources.md"),
            text,
        )

        self.assertIn(
            "canonical_exact_root requires exactly one non-structural Monitor root per source entry",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_monitor_root_audit_rejects_section_obsolete_reference_only_marker(self) -> None:
        obsolete_marker = "none" + "-one-off"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Research Sources",
                        "",
                        f"Monitor root: {obsolete_marker} for individual papers unless an entry states a source root.",
                        "",
                        "- Example paper",
                        "  https://arxiv.org/abs/2601.00001",
                        "  Use as research evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertIn(
            "omit Monitor root for reference-only entries instead of using a synthetic placeholder",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_entry_monitor_root_does_not_require_later_reference_monitor_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example implementation",
                        "  https://example.com/blog/post-1",
                        "  Monitor root: https://example.com/blog/",
                        "  Monitor host relation: evidence_host",
                        "  Use as implementation evidence checked on 2026-06-12.",
                        "",
                        "- Later exact source",
                        "  https://other.example/research/new-paper",
                        "  Use as research evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertNotIn(
            "Monitor root must be a durable discovery root, not an exact/static source URL",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_rejects_whole_domain_monitor_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example implementation",
                        "  https://example.com/blog/post-1",
                        "  Monitor root: https://example.com/",
                        "  Monitor host relation: evidence_host",
                        "  Use as implementation evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertIn(
            "Monitor root must use the smallest durable parent surface, not a whole-domain URL",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_rejects_obsolete_reference_only_marker_with_recurring_root(self) -> None:
        obsolete_marker = "none" + "-one-off"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-12",
                        "",
                        "## Sources",
                        "",
                        "- Example source with mirror",
                        "  https://example.com/resources/post",
                        "  https://mirror.example/resources/post",
                        "  Monitor root: https://example.com/resources",
                        "  Monitor host relation: evidence_host",
                        f"  Monitor root: {obsolete_marker} for mirror evidence.",
                        "  Use as official evidence checked on 2026-06-12.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
                audit_monitor_roots=True,
            )

        self.assertIn(
            "omit Monitor root for reference-only entries instead of using a synthetic placeholder",
            [issue.message for issue in issues],
        )

    def test_reference_freshness_does_not_flag_one_day_timezone_skew(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-13",
                        "",
                        "## Sources",
                        "",
                        "- Example source",
                        "  https://example.com/source",
                        "  Use as source evidence checked on 2026-06-13.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        self.assertEqual([], [issue for issue in issues if issue.severity == "error"])

    def test_reference_freshness_rejects_two_day_future_reviewed_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            doc = refs / "sources.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "Reviewed: 2026-06-14",
                        "",
                        "## Sources",
                        "",
                        "- Example source",
                        "  https://example.com/source",
                        "  Use as source evidence checked on 2026-06-14.",
                    ]
                ),
                encoding="utf-8",
            )

            issues = check_reference_freshness.collect_issues(
                root,
                check_reference_freshness.date.fromisoformat("2026-06-12"),
                180,
                False,
            )

        self.assertIn("future Reviewed date: 2026-06-14", [issue.message for issue in issues])

    def test_reference_freshness_splits_numbered_list_items(self) -> None:
        text = "\n".join(
            [
                "1. Review the current project state.",
                "2. Check section 7.2.1 for local constraints.",
            ]
        )

        self.assertEqual(
            [(1, "1. Review the current project state."), (2, "2. Check section 7.2.1 for local constraints.")],
            check_reference_freshness.paragraph_blocks(text),
        )

    def test_reference_freshness_strips_backtick_from_bare_url(self) -> None:
        self.assertEqual(
            "https://example.com/feed.xml",
            check_reference_freshness.clean_url("https://example.com/feed.xml`"),
        )

    def test_reference_freshness_snapshots_all_inputs_before_hostname_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            references = root / "private" / "references"
            references.mkdir(parents=True)
            (references / "valid.md").write_text(
                "Reviewed: 2026-07-12\nhttps://example.com/releases\n",
                encoding="utf-8",
            )
            (references / "invalid.md").write_bytes(b"Reviewed: \xff\n")

            with mock.patch.object(
                check_reference_freshness,
                "blocked_external_url_reason",
            ) as blocked:
                with self.assertRaises(ValueError):
                    check_reference_freshness.collect_issues(
                        root,
                        check_reference_freshness.date.fromisoformat("2026-07-12"),
                        180,
                        False,
                        resolve_hostnames=True,
                    )

            blocked.assert_not_called()

    def test_reference_freshness_excludes_reference_directory_readme_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            references = root / "references"
            references.mkdir()
            index = references / "README.md"
            registry = references / "sources.md"
            index.write_text("# Registry Index\n", encoding="utf-8")
            registry.write_text("Reviewed: 2026-07-10\n", encoding="utf-8")

            files = check_reference_freshness.reference_markdown_files(
                root,
                (Path("references"),),
            )

        self.assertEqual([registry], files)

    def test_reference_freshness_can_resolve_source_hostnames_when_enabled(self) -> None:
        with mock.patch.object(
            url_safety.socket,
            "getaddrinfo",
            return_value=[(url_safety.socket.AF_INET, url_safety.socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))],
        ):
            issue = check_reference_freshness.source_url_issue(
                "https://example.com/source",
                resolve_hostname=True,
            )

        self.assertIn("resolves to non-public address", issue or "")
