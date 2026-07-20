#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

import routing_policy
import safe_paths
import verification_registry

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEDULE_PATH = REPO_ROOT / "runtime" / "operative_schedule.json"
CLI_FLAGS = tuple(routing_policy.cli_flags())


def has_any_flag(args: argparse.Namespace, flags: tuple[str, ...]) -> bool:
    return any(getattr(args, name, False) for name in flags)


def load_schedule() -> dict:
    return safe_paths.loads_json_no_duplicates(
        SCHEDULE_PATH.read_text(encoding="utf-8")
    )


def choose_standard_of_care(args: argparse.Namespace) -> str:
    if has_any_flag(args, routing_policy.FORENSIC_FLAGS):
        return "forensic"
    if has_any_flag(args, routing_policy.ADVERSARIAL_FLAGS):
        return "adversarial"
    if has_any_flag(args, routing_policy.CAREFUL_FLAGS):
        return "careful"
    return "fast" if args.small else "standard"


def collect_practice_guides(args: argparse.Namespace, schedule: dict) -> list[str]:
    return [
        guide["name"]
        for guide in schedule["practice_guides"]
        if has_any_flag(args, tuple(guide.get("trigger_flags", ())))
    ]


def minimum_evidence(schedule: dict, standard_of_care: str) -> dict:
    return schedule["minimum_evidence_by_risk"][standard_of_care]


def choose_evidentiary_scope(
    args: argparse.Namespace,
    standard_of_care: str,
    schedule: dict | None = None,
) -> str:
    schedule = schedule or load_schedule()
    baseline_scope = minimum_evidence(schedule, standard_of_care)["minimum_scope"]
    if has_any_flag(args, routing_policy.FORENSIC_FLAGS):
        return baseline_scope
    if has_any_flag(args, routing_policy.ADVERSARIAL_FLAGS):
        return baseline_scope
    if args.multi_file and (args.impact_review or args.review or args.audit):
        return "feature-slice"
    if args.impact_review and (args.review or args.audit):
        return "feature-slice"
    return baseline_scope


def needs_second_review(args: argparse.Namespace, standard_of_care: str) -> bool:
    del args
    return standard_of_care in {"adversarial", "forensic"}


def collect_required_checks(
    args: argparse.Namespace,
    standard_of_care: str,
    schedule: dict | None = None,
) -> list[verification_registry.VerificationCheck]:
    """Resolve the risk floor and active registry rules to stable check objects."""

    schedule = schedule or load_schedule()
    checks: list[verification_registry.VerificationCheck] = []
    selected_ids: set[str] = set()
    baseline_ids = minimum_evidence(schedule, standard_of_care)["required_checks"]
    for check in verification_registry.resolve_check_ids(baseline_ids):
        checks.append(check)
        selected_ids.add(check.check_id)
    for check in verification_registry.CHECKS:
        if check.check_id in selected_ids:
            continue
        if check.is_active(args, standard_of_care):
            checks.append(check)
            selected_ids.add(check.check_id)
    return checks


def report_checks(
    checks: list[verification_registry.VerificationCheck],
) -> list[dict[str, str | None]]:
    return [check.as_report_item() for check in checks]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recommend a Risk Level, Practice Guides, and checks for a task.",
        allow_abbrev=False,
    )
    for flag, help_text in CLI_FLAGS:
        parser.add_argument(f"--{flag}", action="store_true", help=help_text)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    schedule = load_schedule()
    standard_of_care = choose_standard_of_care(args)
    result = {
        "schema_version": 1,
        "evidentiary_scope": choose_evidentiary_scope(
            args, standard_of_care, schedule
        ),
        "practice_guides": collect_practice_guides(args, schedule),
        "required_checks": report_checks(
            collect_required_checks(args, standard_of_care, schedule)
        ),
        "second_review_recommended": needs_second_review(args, standard_of_care),
        "standard_of_care": standard_of_care,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
