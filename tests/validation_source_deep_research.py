"""Deep-research artifact and digest validation tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest import mock

from tests.validation_test_support import REPO_ROOT, run_bounded

import safe_paths  # noqa: E402
import source_deep_research_lint  # noqa: E402


class SourceDeepResearchTests(unittest.TestCase):
    def test_source_deep_research_git_runner_preserves_policy_and_diagnostics(self) -> None:
        root = Path.cwd()
        normal = source_deep_research_lint.bounded_subprocess.BoundedProcessResult(
            args=("git", "cat-file", "-s", "spec"),
            returncode=8,
            stdout=b"stdout",
            stderr=b"stderr",
            timed_out=False,
            output_exceeded=False,
        )
        with mock.patch.object(
            source_deep_research_lint.bounded_subprocess,
            "run_bounded_process",
            return_value=normal,
        ) as run:
            observed = source_deep_research_lint._bounded_git(
                ["cat-file", "-s", "spec"],
                max_output_bytes=64 * 1024,
                cwd=root,
            )
        self.assertEqual((8, b"stdout", b"stderr"), observed)
        run.assert_called_once_with(
            source_deep_research_lint.git_query.closed_git_query_command(
                ["cat-file", "-s", "spec"]
            ),
            cwd=root,
            env=source_deep_research_lint.git_query.closed_git_query_environment(root),
            timeout_seconds=source_deep_research_lint.GIT_COMMAND_TIMEOUT_SECONDS,
            max_output_bytes=64 * 1024,
            maximum_timeout_seconds=source_deep_research_lint.GIT_COMMAND_TIMEOUT_SECONDS,
            maximum_output_bytes=source_deep_research_lint.GIT_COMMAND_MAX_OUTPUT_BYTES,
            termination_grace_seconds=source_deep_research_lint.GIT_TERMINATION_GRACE_SECONDS,
        )

        cases = (
            (True, False, "Git inspection timed out after 10s"),
            (False, True, "Git inspection output exceeded the 65536-byte limit"),
        )
        for timed_out, output_exceeded, expected in cases:
            result = source_deep_research_lint.bounded_subprocess.BoundedProcessResult(
                args=("git", "cat-file", "-s", "spec"),
                returncode=-9,
                stdout=b"partial stdout",
                stderr=b"partial stderr",
                timed_out=timed_out,
                output_exceeded=output_exceeded,
            )
            with (
                self.subTest(expected=expected),
                mock.patch.object(
                    source_deep_research_lint.bounded_subprocess,
                    "run_bounded_process",
                    return_value=result,
                ),
                self.assertRaises(RuntimeError) as raised,
            ):
                source_deep_research_lint._bounded_git(
                    ["cat-file", "-s", "spec"],
                    max_output_bytes=64 * 1024,
                    cwd=root,
                )
            self.assertEqual(expected, str(raised.exception))

        start_error = source_deep_research_lint.bounded_subprocess.BoundedSubprocessStartError(
            "bounded subprocess could not start: git unavailable"
        )
        start_error.__cause__ = OSError("git unavailable")
        with (
            mock.patch.object(
                source_deep_research_lint.bounded_subprocess,
                "run_bounded_process",
                side_effect=start_error,
            ),
            self.assertRaises(RuntimeError) as raised,
        ):
            source_deep_research_lint._bounded_git(
                ["cat-file", "-s", "spec"],
                max_output_bytes=64 * 1024,
                cwd=root,
            )
        self.assertEqual("Git inspection could not start: git unavailable", str(raised.exception))

        precondition_error = (
            source_deep_research_lint.bounded_subprocess.BoundedSubprocessPreconditionError(
                "precondition failed"
            )
        )
        with (
            mock.patch.object(
                source_deep_research_lint.bounded_subprocess,
                "run_bounded_process",
                side_effect=precondition_error,
            ),
            self.assertRaises(
                source_deep_research_lint.bounded_subprocess.BoundedSubprocessPreconditionError
            ),
        ):
            source_deep_research_lint._bounded_git(
                ["cat-file", "-s", "spec"],
                max_output_bytes=64 * 1024,
                cwd=root,
            )

    def test_source_deep_research_historical_git_decisions_survive_shared_results(self) -> None:
        result_type = source_deep_research_lint.bounded_subprocess.BoundedProcessResult
        command = ("git", "cat-file", "-s", "spec")
        timeout = result_type(
            args=command,
            returncode=-9,
            stdout=b"partial",
            stderr=b"partial",
            timed_out=True,
            output_exceeded=False,
        )
        with mock.patch.object(
            source_deep_research_lint.bounded_subprocess,
            "run_bounded_process",
            return_value=timeout,
        ):
            errors = source_deep_research_lint.historical_repo_evidence_errors(
                "repo:README.md",
                "0" * 40,
                "0" * 64,
                repo_root=Path.cwd(),
            )
        self.assertEqual(
            ["revision-bound Git size inspection failed: Git inspection timed out after 10s"],
            errors,
        )

        size_ok = result_type(
            args=command,
            returncode=0,
            stdout=b"3\n",
            stderr=b"",
            timed_out=False,
            output_exceeded=False,
        )
        blob_exceeded = result_type(
            args=("git", "cat-file", "blob", "spec"),
            returncode=-9,
            stdout=b"abc",
            stderr=b"",
            timed_out=False,
            output_exceeded=True,
        )
        with mock.patch.object(
            source_deep_research_lint.bounded_subprocess,
            "run_bounded_process",
            side_effect=(size_ok, blob_exceeded),
        ):
            errors = source_deep_research_lint.historical_repo_evidence_errors(
                "repo:README.md",
                "0" * 40,
                "0" * 64,
                repo_root=Path.cwd(),
            )
        self.assertEqual(
            [
                "revision-bound Git blob inspection failed: Git inspection output "
                "exceeded the 65539-byte limit"
            ],
            errors,
        )

        size_nonzero = result_type(
            args=command,
            returncode=128,
            stdout=b"",
            stderr=b"fatal",
            timed_out=False,
            output_exceeded=False,
        )
        with mock.patch.object(
            source_deep_research_lint.bounded_subprocess,
            "run_bounded_process",
            return_value=size_nonzero,
        ):
            errors = source_deep_research_lint.historical_repo_evidence_errors(
                "repo:README.md",
                "0" * 40,
                "0" * 64,
                repo_root=Path.cwd(),
            )
        self.assertEqual(
            ["revision/path does not resolve to a retained Git blob"],
            errors,
        )

    def test_source_deep_research_current_successor_must_be_git_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "tracked.md").write_text("tracked\n", encoding="utf-8")
            (root / "untracked.md").write_text("untracked\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", "tracked.md"], cwd=root, check=True)

            self.assertTrue(
                source_deep_research_lint.safe_repo_locator(
                    "repo:tracked.md",
                    repo_root=root,
                )
            )
            self.assertFalse(
                source_deep_research_lint.safe_repo_locator(
                    "repo:untracked.md",
                    repo_root=root,
                )
            )

    def test_source_deep_research_does_not_execute_repository_fsmonitor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tracked = root / "tracked.md"
            tracked.write_text("tracked\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", "tracked.md"], cwd=root, check=True)
            marker = root / "fsmonitor-executed"
            monitor = root / "fsmonitor.sh"
            monitor.write_text(
                "#!/bin/sh\nprintf executed > " + shlex.quote(str(marker)) + "\n",
                encoding="utf-8",
            )
            monitor.chmod(0o700)
            run_bounded(
                ["git", "config", "core.fsmonitor", str(monitor)],
                cwd=root,
                check=True,
            )

            self.assertTrue(
                source_deep_research_lint.safe_repo_locator(
                    "repo:tracked.md",
                    repo_root=root,
                )
            )
            self.assertFalse(marker.exists())

    def test_public_template_matches_executable_schema(self) -> None:
        template = REPO_ROOT / "project_state_templates" / "SOURCE_DEEP_RESEARCH.md"
        text = template.read_text(encoding="utf-8")
        header_errors: list[str] = []
        header = source_deep_research_lint.parse_header(text.splitlines(), header_errors)
        self.assertEqual([], header_errors)
        self.assertEqual(source_deep_research_lint.REQUIRED_HEADER_FIELDS, set(header))
        self.assertEqual(source_deep_research_lint.SCHEMA_VERSION, header["schema_version"])
        self.assertEqual(source_deep_research_lint.ARTIFACT_KIND, header["artifact_kind"])

        headings, sections = source_deep_research_lint.markdown_h2_sections(text)
        self.assertEqual(
            source_deep_research_lint.REQUIRED_SECTIONS,
            set(headings),
        )
        verification_body = "\n".join(sections["Verification Records"]).strip()
        fence = source_deep_research_lint.JSON_FENCE_RE.fullmatch(verification_body)
        if fence is None:
            self.fail("public template Verification Records must be one JSON fence")
        records = json.loads(fence.group("payload"))
        self.assertIsInstance(records, list)
        self.assertEqual(1, len(records))
        self.assertEqual(source_deep_research_lint.RECORD_FIELDS, set(records[0]))
        self.assertEqual(
            source_deep_research_lint.EVIDENCE_BASE_FIELDS,
            set(records[0]["evidence"][0]),
        )

        contract = (
            REPO_ROOT / "docs" / "source_deep_research_artifacts.md"
        ).read_text(encoding="utf-8")
        for owned_surface in (
            "project_state_templates/SOURCE_DEEP_RESEARCH.md",
            "scripts/source_deep_research_lint.py",
            "practice_guides/source_grounded_research.md",
        ):
            with self.subTest(owned_surface=owned_surface):
                self.assertIn(owned_surface, contract)

    def test_source_deep_research_lint_validates_digest_and_stale_extraction(self) -> None:
        def write_digest(
            path: Path,
            records: list[dict[str, object]],
            *,
            header_overrides: dict[str, str] | None = None,
            verification_body: str | None = None,
            extra_sections: str = "",
        ) -> None:
            header = {
                "schema_version": "4",
                "artifact_kind": "browser_deep_research_digest",
                "provider": "Browser Deep Research; exact model not recorded",
                "browser_url": "https://example.com/deep-research/report",
                "started_at": "2026-07-01T08:00:00+02:00",
                "completed_at": "2026-07-01T08:30:00+02:00",
                "completion_status": "completed",
                "completion_evidence": "visible final result surface with title and table of contents",
                "extraction_kind": "snapshot",
                "extraction_method": "visible result body captured through the browser document surface",
                "stale_input_disposition": "none",
            }
            if header_overrides:
                header.update(header_overrides)
            body = verification_body
            if body is None:
                body = "```json\n" + json.dumps(records, indent=2, sort_keys=True) + "\n```"
            path.write_text(
                "\n".join(
                    [
                        *(f"{key}: {value}" for key, value in header.items()),
                        "",
                        "# Deep Research Digest",
                        "",
                        "## Prompt Digest",
                        "",
                        "Broad source discovery.",
                        "",
                        "## Verification Records",
                        "",
                        body,
                        "",
                        "## Rejected or Deferred",
                        "",
                        "- Unsupported candidates rejected.",
                        extra_sections,
                    ]
                ),
                encoding="utf-8",
            )
        valid_record: dict[str, object] = {
            "id": "source-contract",
            "candidate_abstraction": "Verify source-backed claims against the applicable primary source.",
            "claim_class": "external_source",
            "verification_status": "primary_source_verified",
            "verified_at": "2026-07-01",
            "verifier": "accountable model-review coordinator",
            "verifier_role": "coordinator",
            "method": "direct_primary_source_inspection",
            "evidence": [
                {
                    "locator": "https://example.com/primary-source",
                    "source_role": "primary",
                    "checked_at": "2026-07-01",
                    "identity": "primary source page",
                    "supports": "the bounded source contract",
                    "evidence_limit": "the page remains mutable and requires a current recheck",
                }
            ],
            "framework_effect": "Retain the existing source-verification boundary.",
            "source_specific_material_rejected": ["provider-specific wording"],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid = root / "valid.md"
            write_digest(valid, [valid_record])

            stale = root / "stale.md"
            write_digest(
                stale,
                [valid_record],
                header_overrides={
                    "browser_url": "http://research.example.com/report",
                    "completion_evidence": "sidebar said done",
                    "extraction_method": "stale clipboard content",
                },
            )

            valid_report = source_deep_research_lint.validate_digest(valid)
            stale_report = source_deep_research_lint.validate_digest(stale)

        self.assertEqual([], valid_report["errors"])
        self.assertIn("unsafe browser_url: external URL must use https", stale_report["errors"])

        mutation_cases: list[tuple[str, list[dict[str, object]], str | None, str]] = []

        phrase_only_body = "Primary verification completed against official sources."
        mutation_cases.append(
            (
                "phrase-only verification",
                [valid_record],
                phrase_only_body,
                "Verification Records must contain only one ```json fenced array",
            )
        )

        invalid_verifier_role = json.loads(json.dumps(valid_record))
        invalid_verifier_role["verifier_role"] = "proposer"
        mutation_cases.append(
            (
                "invalid verifier role",
                [invalid_verifier_role],
                None,
                "verifier_role must be one of: coordinator, deterministic_verifier, independent_reviewer",
            )
        )

        unsafe_external = json.loads(json.dumps(valid_record))
        unsafe_external["evidence"][0]["locator"] = "http://example.com/primary-source"
        mutation_cases.append(
            (
                "unsafe primary locator",
                [unsafe_external],
                None,
                "locator is not a safe primary URL: external URL must use https",
            )
        )

        missing_local = json.loads(json.dumps(valid_record))
        missing_local.update(
            {
                "claim_class": "local_process",
                "verification_status": "local_evidence_verified",
                "method": "repository_inspection",
            }
        )
        missing_local["evidence"][0].update(
            {
                "locator": "repo:not-a-real-file.md",
                "source_role": "local",
                "revision": "ef9bce9ac1c206b79a15148d17479f9eb954250c",
                "content_sha256": "cd534b9442637a42d794fd813e73e8be69765e5299379da772a26942337d65ad",
                "current_successor": None,
            }
        )
        mutation_cases.append(
            (
                "missing local evidence",
                [missing_local],
                None,
                "revision/path does not resolve to a retained Git blob",
            )
        )

        ambiguous_local = json.loads(json.dumps(missing_local))
        ambiguous_local["evidence"][0]["locator"] = "repo:docs//evidence.md"
        mutation_cases.append(
            (
                "ambiguous local evidence path",
                [ambiguous_local],
                None,
                "locator must use a safe repo: path for local evidence",
            )
        )

        wrong_historical_bytes = json.loads(json.dumps(missing_local))
        wrong_historical_bytes["evidence"][0].update(
            {
                "locator": "repo:README.md",
                "current_successor": "repo:README.md",
            }
        )
        mutation_cases.append(
            (
                "wrong revision-bound bytes",
                [wrong_historical_bytes],
                None,
                "content_sha256 must match the revision-bound Git blob",
            )
        )

        malformed_shape = json.loads(json.dumps(valid_record))
        del malformed_shape["framework_effect"]
        malformed_shape["unknown_record_field"] = "unexpected"
        del malformed_shape["evidence"][0]["identity"]
        malformed_shape["evidence"][0]["unknown_evidence_field"] = "unexpected"
        mutation_cases.extend(
            [
                (
                    "missing record field",
                    [malformed_shape],
                    None,
                    "missing fields: framework_effect",
                ),
                (
                    "unknown record field",
                    [malformed_shape],
                    None,
                    "has unknown fields: unknown_record_field",
                ),
                (
                    "missing evidence field",
                    [malformed_shape],
                    None,
                    "missing fields: identity",
                ),
                (
                    "unknown evidence field",
                    [malformed_shape],
                    None,
                    "has unknown fields: unknown_evidence_field",
                ),
            ]
        )

        duplicate_record = json.loads(json.dumps(valid_record))
        mutation_cases.append(
            (
                "duplicate ids",
                [valid_record, duplicate_record],
                None,
                "duplicate verification record id: source-contract",
            )
        )

        wrong_pairing = json.loads(json.dumps(valid_record))
        wrong_pairing["verification_status"] = "local_evidence_verified"
        wrong_pairing["method"] = "repository_inspection"
        mutation_cases.extend(
            [
                (
                    "wrong status pairing",
                    [wrong_pairing],
                    None,
                    "verification_status must be primary_source_verified for external_source",
                ),
                (
                    "wrong method pairing",
                    [wrong_pairing],
                    None,
                    "method must be direct_primary_source_inspection for external_source",
                ),
            ]
        )

        valid_json_fence = "```json\n" + json.dumps([valid_record]) + "\n```"
        mutation_cases.append(
            (
                "prose outside json fence",
                [valid_record],
                "Unstructured verification claim.\n" + valid_json_fence,
                "Verification Records must contain only one ```json fenced array",
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_repo = root / "fixture-repo"
            fixture_repo.mkdir()
            (fixture_repo / "README.md").write_text("# Fixture repository\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=fixture_repo, check=True)
            run_bounded(["git", "add", "README.md"], cwd=fixture_repo, check=True)
            run_bounded(
                [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                cwd=fixture_repo,
                check=True,
            )
            revision = run_bounded(
                ["git", "rev-parse", "HEAD"],
                cwd=fixture_repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            for _label, records, _body, _expected_error in mutation_cases:
                for record in records:
                    if record.get("claim_class") != "local_process":
                        continue
                    evidence = record.get("evidence")
                    if isinstance(evidence, list):
                        for item in evidence:
                            if isinstance(item, dict) and "revision" in item:
                                item["revision"] = revision

            for index, (label, records, body, expected_error) in enumerate(mutation_cases):
                with self.subTest(label=label):
                    artifact = root / f"mutation-{index}.md"
                    write_digest(artifact, records, verification_body=body)
                    report = source_deep_research_lint.validate_digest(
                        artifact,
                        project_root=fixture_repo,
                    )
                    self.assertTrue(
                        any(expected_error in error for error in report["errors"]),
                        report["errors"],
                    )

            header_cases = (
                ({"schema_version": "3"}, "schema_version must be 4"),
                ({"artifact_kind": "research_notes"}, "artifact_kind must be browser_deep_research_digest"),
                ({"unexpected_header": "value"}, "unknown header fields: unexpected_header"),
                ({"completion_status": "pending"}, "completion_status must be one of: completed"),
                ({"extraction_kind": "screen_text"}, "extraction_kind must be one of: copy, export, snapshot"),
                (
                    {"stale_input_disposition": "accepted"},
                    "stale_input_disposition must be one of: none, rejected, retried",
                ),
                (
                    {"started_at": "July 1, 2026"},
                    "started_at must be not_recorded or an RFC 3339 instant with an explicit Z or ±HH:MM offset",
                ),
                (
                    {"started_at": "2026-07-01T08:00:00"},
                    "started_at must be not_recorded or an RFC 3339 instant with an explicit Z or ±HH:MM offset",
                ),
                (
                    {"started_at": "2026-07-01T08:00:00 Europe/Paris"},
                    "started_at must be not_recorded or an RFC 3339 instant with an explicit Z or ±HH:MM offset",
                ),
                (
                    {"started_at": "unknown"},
                    "started_at must be not_recorded or an RFC 3339 instant with an explicit Z or ±HH:MM offset",
                ),
                (
                    {"started_at": "2026-02-30T08:00:00Z"},
                    "started_at must be a valid RFC 3339 instant",
                ),
                (
                    {
                        "started_at": "2026-07-01T10:00:00+02:00",
                        "completed_at": "2026-07-01T08:30:00+01:00",
                    },
                    "completed_at instant must not be earlier than started_at instant",
                ),
            )
            for index, (overrides, expected_error) in enumerate(header_cases):
                with self.subTest(header_overrides=overrides):
                    artifact = root / f"header-{index}.md"
                    write_digest(artifact, [valid_record], header_overrides=overrides)
                    report = source_deep_research_lint.validate_digest(artifact)
                    self.assertIn(expected_error, report["errors"])

            equivalent_instants = root / "equivalent-instants.md"
            write_digest(
                equivalent_instants,
                [valid_record],
                header_overrides={
                    "started_at": "2026-07-01T10:00:00+02:00",
                    "completed_at": "2026-07-01T08:00:00Z",
                },
            )
            equivalent_report = source_deep_research_lint.validate_digest(
                equivalent_instants
            )
            self.assertEqual([], equivalent_report["errors"])

            partially_recorded = root / "partially-recorded.md"
            write_digest(
                partially_recorded,
                [valid_record],
                header_overrides={
                    "started_at": "not_recorded",
                    "completed_at": "2026-07-01T08:30:00Z",
                },
            )
            partially_recorded_report = source_deep_research_lint.validate_digest(
                partially_recorded
            )
            self.assertEqual([], partially_recorded_report["errors"])

            unrecorded_instants = root / "unrecorded-instants.md"
            write_digest(
                unrecorded_instants,
                [valid_record],
                header_overrides={
                    "started_at": "not_recorded",
                    "completed_at": "not_recorded",
                },
            )
            unrecorded_report = source_deep_research_lint.validate_digest(
                unrecorded_instants
            )
            self.assertEqual([], unrecorded_report["errors"])

            duplicate_section = root / "duplicate-section.md"
            write_digest(
                duplicate_section,
                [valid_record],
                extra_sections="\n## Verification Records\n\n```json\n[]\n```",
            )
            duplicate_report = source_deep_research_lint.validate_digest(duplicate_section)
            self.assertIn("duplicate section: Verification Records", duplicate_report["errors"])

            fenced_heading = root / "fenced-heading.md"
            write_digest(
                fenced_heading,
                [valid_record],
                extra_sections="\n```md\n## Prompt Digest\nspoof\n```",
            )
            fenced_report = source_deep_research_lint.validate_digest(fenced_heading)
            self.assertNotIn("duplicate section: Prompt Digest", fenced_report["errors"])

            empty_sections = root / "empty-sections.md"
            write_digest(empty_sections, [valid_record])
            empty_text = empty_sections.read_text(encoding="utf-8")
            empty_text = empty_text.replace(
                "## Prompt Digest\n\nBroad source discovery.",
                "## Prompt Digest\n",
            ).replace(
                "## Rejected or Deferred\n\n- Unsupported candidates rejected.",
                "## Rejected or Deferred\n",
            )
            empty_sections.write_text(empty_text, encoding="utf-8")
            empty_report = source_deep_research_lint.validate_digest(empty_sections)
            self.assertIn("Prompt Digest must not be empty", empty_report["errors"])
            self.assertIn("Rejected or Deferred must not be empty", empty_report["errors"])

    def test_source_deep_research_refuses_oversized_historical_git_blobs_before_reading(self) -> None:
        oversized = safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 1
        with mock.patch.object(
            source_deep_research_lint,
            "_bounded_git",
            return_value=(0, f"{oversized}\n".encode("ascii"), b""),
        ) as run:
            errors = source_deep_research_lint.historical_repo_evidence_errors(
                "repo:README.md",
                "0" * 40,
                "0" * 64,
            )

        self.assertEqual(1, run.call_count)
        self.assertEqual(
            [
                "revision-bound Git blob exceeds the maintained evidence byte limit "
                f"({oversized} > {safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES})"
            ],
            errors,
        )

    def test_source_deep_research_digest_rejects_unsafe_file_kinds_and_bytes(self) -> None:
        cases = ("invalid-utf8", "oversize", "hardlink", "fifo")
        for case_id in cases:
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                artifact = root / "digest.md"
                if case_id == "invalid-utf8":
                    artifact.write_bytes(b"\xff")
                elif case_id == "oversize":
                    artifact.write_bytes(
                        b"x" * (safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 1)
                    )
                elif case_id == "hardlink":
                    seed = root / "seed.md"
                    seed.write_text("# Digest\n", encoding="utf-8")
                    os.link(seed, artifact)
                else:
                    if not hasattr(os, "mkfifo"):
                        self.skipTest("FIFO creation is unavailable")
                    os.mkfifo(artifact)

                report = source_deep_research_lint.validate_digest(artifact)

            self.assertTrue(report["errors"], report)
            self.assertTrue(
                any(
                    marker in report["errors"][0]
                    for marker in ("valid UTF-8", "input rejected")
                ),
                report,
            )
