"""Verification-registry and task-routing contract tests."""

from __future__ import annotations

import unittest

from tests.validation_test_support import SCRIPTS_DIR as _SCRIPTS_DIR

import recommend_stack  # noqa: E402
import routing_policy  # noqa: E402
import verification_plan  # noqa: E402
import verification_registry  # noqa: E402


def _check_ids(
    checks: list[verification_registry.VerificationCheck],
) -> set[str]:
    return {check.check_id for check in checks}


class ValidationRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = recommend_stack.build_parser()
        self.schedule = recommend_stack.load_schedule()

    def routed_check_ids(self, argv: list[str]) -> tuple[str, set[str]]:
        args = self.parser.parse_args(argv)
        care = recommend_stack.choose_standard_of_care(args)
        return care, _check_ids(
            recommend_stack.collect_required_checks(args, care, self.schedule)
        )

    def test_registry_has_valid_stable_identity_and_references(self) -> None:
        guides = {item["name"] for item in self.schedule["practice_guides"]}
        self.assertEqual(
            [],
            verification_registry.registry_errors(
                allowed_flags=routing_policy.allowed_trigger_flags(),
                known_guides=guides,
            ),
        )
        self.assertEqual(
            len(verification_registry.CHECKS),
            len(verification_registry.CHECKS_BY_ID),
        )

    def test_every_activation_clause_has_a_positive_and_negative_witness(self) -> None:
        empty_args = self.parser.parse_args([])
        for check in verification_registry.CHECKS:
            for position, clause in enumerate(check.activation):
                with self.subTest(check_id=check.check_id, clause=position):
                    care = clause.care_levels[0] if clause.care_levels else "standard"
                    positive_flags = list(clause.all_flags)
                    if clause.any_flags:
                        positive_flags.append(clause.any_flags[0])
                    positive = self.parser.parse_args(
                        [f"--{flag.replace('_', '-')}" for flag in positive_flags]
                    )
                    self.assertTrue(clause.matches(positive, care))
                    if clause.any_flags or clause.all_flags or clause.care_levels:
                        negative_care = (
                            "standard" if clause.care_levels else care
                        )
                        self.assertFalse(clause.matches(empty_args, negative_care))

    def test_minimum_evidence_uses_registry_ids_at_each_risk_level(self) -> None:
        cases = (
            (
                [],
                "standard",
                "touched-files",
                {
                    "baseline.changed-file",
                    "baseline.applicable-verification",
                },
            ),
            (["--small"], "fast", "patch", {"baseline.changed-surface"}),
            (
                ["--multi-file"],
                "careful",
                "touched-files",
                {
                    "baseline.affected-edge",
                    "baseline.regression-acceptance",
                },
            ),
            (
                ["--security"],
                "adversarial",
                "trust-boundary",
                {
                    "baseline.failure-mode-review",
                    "baseline.independent-validation",
                },
            ),
            (
                ["--incident"],
                "forensic",
                "repo-slice",
                {
                    "baseline.failure-mode-review",
                    "baseline.independent-validation",
                    "baseline.evidence-preservation",
                    "baseline.timeline-provenance",
                    "baseline.no-destructive-before-evidence",
                },
            ),
        )
        for argv, expected_care, expected_scope, required in cases:
            with self.subTest(argv=argv):
                args = self.parser.parse_args(argv)
                care = recommend_stack.choose_standard_of_care(args)
                checks = recommend_stack.collect_required_checks(
                    args, care, self.schedule
                )
                self.assertEqual(expected_care, care)
                self.assertEqual(
                    expected_scope,
                    recommend_stack.choose_evidentiary_scope(
                        args, care, self.schedule
                    ),
                )
                self.assertTrue(required <= _check_ids(checks))

    def test_domain_routes_select_the_expected_guide_and_check_ids(self) -> None:
        cases = (
            ("source-refresh", "source_freshness_review", {"sources.delta-hypotheses", "sources.freshness-gaps"}),
            ("logic-review", "logical_spec_review", {"logic.consistency-case-coverage"}),
            ("testing-strategy", "testing_strategy_quality", {"testing.behavior-oracle-portfolio", "testing.assertions-negative-isolation"}),
            ("data-systems", "data_systems_review", {"data.model-workload-invariants", "data.tradeoffs", "data.failure-modes"}),
            ("api-contract-security", "api_contract_security", {"api.contract-boundary", "api.validation-authorization"}),
            ("privacy-data-handling", "privacy_data_handling", {"privacy.classify-boundary", "privacy.handling-lifecycle"}),
            ("database-security", "backend_database_security", {"database.boundary", "database.security-verification"}),
            ("platform-architecture", "platform_architecture_review", {"platform.boundary", "platform.tradeoffs", "platform.failure-modes"}),
            ("infrastructure-as-code", "infrastructure_as_code_review", {"iac.boundary", "iac.verification"}),
            ("prompt-agent-quality", "prompt_agent_quality", {"agent.current-sources", "agent.acceptance-evals", "agent.tool-memory-verifier-boundaries", "agent.runtime-goal-contract"}),
            ("knowledge-transfer", "knowledge_transfer", {"knowledge.scope-depth-evidence", "knowledge.grounding", "knowledge.optional-comprehension"}),
            ("source-originality", "source_originality_review", {"originality.behavior-contract", "originality.license-provenance", "originality.fingerprint-scan"}),
            ("container-image-security", "container_image_security", {"container.image-boundary", "container.image-verification"}),
            ("build-pipeline-integrity", "build_pipeline_integrity", {"pipeline.boundary", "pipeline.integrity-verification"}),
            ("secure-development", "secure_development", {"secure-development.asset-boundaries", "secure-development.verification-profile", "secure-development.tool-output-triage"}),
            ("html-quality", "html_quality", {"html.source-contract", "html.semantic-accessibility", "html.validator-triage"}),
            ("css-quality", "css_quality", {"language.current-sources", "css.support-layout-fallback"}),
            ("javascript-quality", "javascript_coding_quality", {"language.current-sources", "javascript.runtime-contract"}),
            ("swift-quality", "swift_coding_quality", {"language.current-sources", "language.build-type-lint-test"}),
            ("rust-quality", "rust_coding_quality", {"language.current-sources", "language.build-type-lint-test"}),
            ("typescript-quality", "typescript_coding_quality", {"language.current-sources", "language.build-type-lint-test"}),
            ("python-quality", "python_coding_quality", {"language.current-sources", "language.build-type-lint-test"}),
            ("go-quality", "go_coding_quality", {"language.current-sources", "language.build-type-lint-test"}),
            ("shell-cli-quality", "shell_cli_coding_quality", {"language.current-sources", "shell.contract"}),
            ("sql-quality", "sql_query_quality", {"language.current-sources", "sql.contract"}),
            ("kubernetes-quality", "kubernetes_workload_review", {"kubernetes.target-assumptions", "kubernetes.rendered-verification"}),
            ("apple-container-workflow", "apple_container_workflow", {"apple-container.runtime-assumptions", "apple-container.boundary-cleanup"}),
            ("seo", "seo", {"seo.current-surface-rules", "seo.technical-inspection", "seo.baseline-followup"}),
            ("scholarly-writing", "scholarly_writing", {"scholarly.style-guide", "scholarly.citation-locators", "scholarly.terminology-metadata", "scholarly.typography"}),
            (
                "video-creation-quality",
                "video_creation_quality",
                {
                    "video.brief-delivery-contract",
                    "video.rights-accessibility-plan",
                    "video.temporal-technical-playback",
                },
            ),
            (
                "delegated-communication-coverage",
                "delegated_communication_coverage",
                {
                    "communications.grant-activation-boundary",
                    "communications.disclosure-effect-gate",
                    "communications.expiry-revocation-audit-loop",
                },
            ),
            ("scheduled", "scheduled_automation", {"automation.failure-escalation", "automation.idempotency-lock", "automation.observe-before-act"}),
        )
        for flag, guide, expected_checks in cases:
            with self.subTest(flag=flag):
                args = self.parser.parse_args([f"--{flag}"])
                care = recommend_stack.choose_standard_of_care(args)
                guides = recommend_stack.collect_practice_guides(
                    args, self.schedule
                )
                checks = _check_ids(
                    recommend_stack.collect_required_checks(
                        args, care, self.schedule
                    )
                )
                self.assertIn(guide, guides)
                self.assertTrue(expected_checks <= checks)

    def test_frontend_visual_and_combined_container_routes_are_additive(self) -> None:
        frontend = self.parser.parse_args(["--frontend-quality"])
        frontend_guides = recommend_stack.collect_practice_guides(
            frontend, self.schedule
        )
        frontend_checks = _check_ids(
            recommend_stack.collect_required_checks(
                frontend, "careful", self.schedule
            )
        )
        self.assertIn("html_quality", frontend_guides)
        self.assertNotIn("source_originality_review", frontend_guides)
        self.assertTrue(
            {
                "html.source-contract",
                "html.semantic-accessibility",
                "css.support-layout-fallback",
                "visual.baseline",
                "visual.viewports",
                "frontend.layout-contracts",
                "frontend.source-ownership",
                "frontend.evidence-triangulation",
                "frontend.narrative-paths",
                "frontend.user-journeys",
            }
            <= frontend_checks
        )
        self.assertNotIn("originality.license-provenance", frontend_checks)

        combined = self.parser.parse_args(
            ["--apple-container-workflow", "--container-image-security"]
        )
        combined_checks = _check_ids(
            recommend_stack.collect_required_checks(
                combined, "adversarial", self.schedule
            )
        )
        self.assertIn("apple-container.image-assumptions", combined_checks)

    def test_video_creation_route_excludes_adjacent_nonproduction_media_tasks(
        self,
    ) -> None:
        video_check_ids = {
            "video.brief-delivery-contract",
            "video.rights-accessibility-plan",
            "video.temporal-technical-playback",
        }
        for flag in ("current-info", "source-originality", "visual", "html-quality"):
            with self.subTest(flag=flag):
                args = self.parser.parse_args([f"--{flag}"])
                care = recommend_stack.choose_standard_of_care(args)
                self.assertNotIn(
                    "video_creation_quality",
                    recommend_stack.collect_practice_guides(args, self.schedule),
                )
                self.assertTrue(
                    video_check_ids.isdisjoint(
                        _check_ids(
                            recommend_stack.collect_required_checks(
                                args, care, self.schedule
                            )
                        )
                    )
                )

    def test_specialized_delivery_checks_have_required_phases(self) -> None:
        expected = {
            "video.brief-delivery-contract": "before_edit",
            "video.rights-accessibility-plan": "before_edit",
            "video.temporal-technical-playback": "before_completion",
            "communications.grant-activation-boundary": "before_edit",
            "communications.disclosure-effect-gate": "during_work",
            "communications.expiry-revocation-audit-loop": "before_completion",
        }
        self.assertEqual(
            expected,
            {
                check_id: verification_registry.get_check(check_id).phase
                for check_id in expected
            },
        )

    def test_delegated_coverage_checks_bind_mode_specific_authority_and_effects(
        self,
    ) -> None:
        grant = verification_registry.get_check(
            "communications.grant-activation-boundary"
        ).text
        effect = verification_registry.get_check(
            "communications.disclosure-effect-gate"
        ).text

        for required in (
            "authority to prepare",
            "dormant no-effect",
            "shadow read",
            "independent exact activation",
            "mailbox",
            "account",
            "tenant",
            "acting identity",
        ):
            self.assertIn(required, grant)
        self.assertNotIn("sender identity", grant)

        for required in (
            "mode-specific effect",
            "message class",
            "audience evidence",
            "sink and destination",
            "data projection",
            "idempotency",
            "connector-result",
            "acceptance",
            "dispatch",
            "final-delivery",
            "every outbound communication",
            "recipient",
            "acting-identity",
            "sink-specific protocol invariants",
            "Return-Path",
            "sender-facing automatic responses",
        ):
            self.assertIn(required, effect)
        self.assertNotIn("sender eligibility", effect)

    def test_delegated_communication_coverage_route_is_explicit_and_adversarial(
        self,
    ) -> None:
        args = self.parser.parse_args(["--delegated-communication-coverage"])
        care = recommend_stack.choose_standard_of_care(args)
        guides = set(recommend_stack.collect_practice_guides(args, self.schedule))
        checks = _check_ids(
            recommend_stack.collect_required_checks(args, care, self.schedule)
        )

        self.assertEqual("adversarial", care)
        self.assertEqual(
            "trust-boundary",
            recommend_stack.choose_evidentiary_scope(args, care, self.schedule),
        )
        self.assertEqual(
            {
                "delegated_communication_coverage",
                "privacy_data_handling",
                "prompt_injection_review",
            },
            guides,
        )
        self.assertTrue(
            {
                "communications.grant-activation-boundary",
                "communications.disclosure-effect-gate",
                "communications.expiry-revocation-audit-loop",
                "privacy.classify-boundary",
                "privacy.handling-lifecycle",
                "input.untrusted-data",
            }
            <= checks
        )

        external_effect = self.parser.parse_args(["--external-effect"])
        self.assertNotIn(
            "delegated_communication_coverage",
            recommend_stack.collect_practice_guides(external_effect, self.schedule),
        )
        self.assertTrue(
            {
                "communications.grant-activation-boundary",
                "communications.disclosure-effect-gate",
                "communications.expiry-revocation-audit-loop",
            }.isdisjoint(
                _check_ids(
                    recommend_stack.collect_required_checks(
                        external_effect, "adversarial", self.schedule
                    )
                )
            )
        )

    def test_incident_and_sql_routes_do_not_select_adjacent_guides(self) -> None:
        incident = self.parser.parse_args(["--incident"])
        incident_guides = recommend_stack.collect_practice_guides(
            incident, self.schedule
        )
        security = self.parser.parse_args(["--security"])
        self.assertIn("incident_response", incident_guides)
        self.assertNotIn("security_audit", incident_guides)
        self.assertTrue(
            _check_ids(
                recommend_stack.collect_required_checks(
                    security, "adversarial", self.schedule
                )
            )
            <= _check_ids(
                recommend_stack.collect_required_checks(
                    incident, "forensic", self.schedule
                )
            )
        )

        sql = self.parser.parse_args(["--sql-quality"])
        self.assertNotIn(
            "backend_database_security",
            recommend_stack.collect_practice_guides(sql, self.schedule),
        )

    def test_risk_and_action_boundaries_remain_distinct(self) -> None:
        cases = (
            (["--review", "--small"], "careful", "touched-files", False),
            (["--agentic"], "careful", "touched-files", False),
            (["--release"], "careful", "touched-files", False),
            (["--audit", "--multi-file"], "careful", "feature-slice", False),
            (["--audit", "--security"], "adversarial", "trust-boundary", True),
        )
        for argv, expected_care, expected_scope, second_review in cases:
            with self.subTest(argv=argv):
                args = self.parser.parse_args(argv)
                care = recommend_stack.choose_standard_of_care(args)
                self.assertEqual(expected_care, care)
                self.assertEqual(
                    expected_scope,
                    recommend_stack.choose_evidentiary_scope(
                        args, care, self.schedule
                    ),
                )
                self.assertEqual(
                    second_review,
                    recommend_stack.needs_second_review(args, care),
                )

        readiness = self.parser.parse_args(["--release"])
        release_action = self.parser.parse_args(
            ["--release", "--external-effect"]
        )
        self.assertNotIn(
            "effects.authorization-boundary",
            _check_ids(
                recommend_stack.collect_required_checks(
                    readiness, "careful", self.schedule
                )
            ),
        )
        self.assertIn(
            "effects.authorization-boundary",
            _check_ids(
                recommend_stack.collect_required_checks(
                    release_action, "adversarial", self.schedule
                )
            ),
        )

    def test_planning_suppresses_only_the_post_edit_regression_route(self) -> None:
        planned = self.parser.parse_args(["--planning", "--multi-file"])
        direct = self.parser.parse_args(["--multi-file"])
        self.assertNotIn(
            "change.targeted-regression",
            _check_ids(
                recommend_stack.collect_required_checks(
                    planned, "careful", self.schedule
                )
            ),
        )
        self.assertIn(
            "change.targeted-regression",
            _check_ids(
                recommend_stack.collect_required_checks(
                    direct, "careful", self.schedule
                )
            ),
        )

    def test_reports_expose_stable_ids_text_and_canonical_phase(self) -> None:
        args = self.parser.parse_args(["--prompt-agent-quality"])
        checks = recommend_stack.collect_required_checks(
            args, "careful", self.schedule
        )
        report = recommend_stack.report_checks(checks)
        self.assertTrue(report)
        self.assertTrue(
            all(
                set(item) == {"check_id", "text", "phase", "owning_guide"}
                for item in report
            )
        )
        self.assertEqual(
            [check.check_id for check in checks],
            [item["check_id"] for item in report],
        )

        grouped = verification_plan.group_checks(checks)
        flattened = [
            item
            for phase in verification_registry.PHASES
            for item in grouped[phase]
        ]
        self.assertCountEqual(report, flattened)
        for phase, items in grouped.items():
            self.assertTrue(all(item["phase"] == phase for item in items))

    def test_unknown_check_id_is_rejected_with_identity_in_diagnostic(self) -> None:
        with self.assertRaisesRegex(
            KeyError, "unknown verification check ID: unknown.check"
        ):
            verification_registry.get_check("unknown.check")


if __name__ == "__main__":
    unittest.main()
